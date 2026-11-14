"""One JSON entity per logical record, with ETags and bounded atomic batches.

Transactional domain kinds share a partition; telemetry archives, images and
notifications use their own kind partitions. No dataset is stored as an aggregate.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import threading
from functools import lru_cache
from typing import Protocol

from app.cloud.settings import storage_connection_string


class ConflictError(RuntimeError):
    pass


class Record(dict):
    def __init__(self, value: dict, version: str | int):
        super().__init__(value)
        self.version = version


class Store(Protocol):
    def get(self, kind: str, key: str) -> dict | None: ...
    def list(self, kind: str) -> list[dict]: ...
    def create(self, kind: str, key: str, value: dict) -> bool: ...
    def put(self, kind: str, key: str, value: dict) -> None: ...
    def delete(self, kind: str, key: str) -> None: ...
    def compare_and_swap(self, kind: str, key: str, expected: dict, replacement: dict) -> bool: ...
    def transaction(self, changes: list[tuple[str, str, dict | None, dict | None]]) -> None: ...
    def query(self, kind: str, *, device_id: str | None = None, location_id: str | None = None,
              since: str | None = None, until: str | None = None) -> list[dict]: ...


def encoded_key(key: str) -> str:
    return hashlib.sha256(str(key).encode("utf-8")).hexdigest()


TRANSACTION_KINDS = frozenset({"Locations", "Devices", "Products", "Stock", "Alerts", "Commands", "Transfers", "Events", "Timeline", "Outbox", "DomainMeta"})


def partition_key(kind: str) -> str:
    return encoded_key("TransactionalDomain" if kind in TRANSACTION_KINDS else kind)


def row_key(kind: str, key: str) -> str:
    return f"{encoded_key(kind)}-{encoded_key(key)}" if kind in TRANSACTION_KINDS else encoded_key(key)


def _json(value: dict) -> str:
    return json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":"))


def _check_batch(changes) -> None:
    if not changes or len(changes) > 100:
        raise ValueError("Transaction requires 1–100 entity changes")
    if len({partition_key(kind) for kind, _, _, _ in changes}) != 1:
        raise ValueError("Transaction entities must share a partition")
    if len({(kind, str(key)) for kind, key, _, _ in changes}) != len(changes):
        raise ValueError("Transaction cannot change a record twice")


class MemoryStore:
    """Explicit test injection only. Production get_store never chooses this."""

    def __init__(self):
        self._rows: dict[tuple[str, str], tuple[dict, int]] = {}
        self._lock = threading.RLock()
        self._version = 0
        self._keys: dict[str, set[str]] = {}

    def get(self, kind: str, key: str) -> dict | None:
        with self._lock:
            row = self._rows.get((kind, str(key)))
            return Record(copy.deepcopy(row[0]), row[1]) if row else None

    def list(self, kind: str) -> list[dict]:
        with self._lock:
            return [Record(copy.deepcopy(self._rows[(kind, key)][0]), self._rows[(kind, key)][1])
                    for key in self._keys.get(kind, set())]

    def create(self, kind: str, key: str, value: dict) -> bool:
        data = json.loads(_json(value))
        with self._lock:
            index = (kind, str(key))
            if index in self._rows:
                return False
            self._version += 1
            self._rows[index] = (data, self._version)
            self._keys.setdefault(kind, set()).add(str(key))
            return True

    def put(self, kind: str, key: str, value: dict) -> None:
        data = json.loads(_json(value))
        with self._lock:
            index = (kind, str(key))
            current = self._rows.get(index)
            version = getattr(value, "version", None)
            if current and version != current[1]:
                raise ConflictError("Record changed; re-read before updating")
            if not current and version is not None:
                raise ConflictError("Record was deleted")
            self._version += 1
            self._rows[index] = (data, self._version)
            self._keys.setdefault(kind, set()).add(str(key))

    def compare_and_swap(self, kind: str, key: str, expected: dict, replacement: dict) -> bool:
        with self._lock:
            current = self.get(kind, key)
            if current is None or current != expected:
                return False
            version = getattr(expected, "version", None)
            if version is not None and current.version != version:
                return False
            self.put(kind, key, Record(replacement, current.version))
            return True

    def transaction(self, changes: list[tuple[str, str, dict | None, dict | None]]) -> None:
        _check_batch(changes)
        prepared = [(kind, str(key), expected, json.loads(_json(value)) if value is not None else None)
                    for kind, key, expected, value in changes]
        with self._lock:
            for kind, key, expected, _ in prepared:
                current = self.get(kind, key)
                if expected is None:
                    if current is not None:
                        raise ConflictError("Transaction create collision")
                elif current is None or current != expected or current.version != getattr(expected, "version", None):
                    raise ConflictError("Transaction ETag conflict")
            for kind, key, _, value in prepared:
                self._version += 1
                if value is None:
                    self._rows.pop((kind, key), None)
                    self._keys.setdefault(kind, set()).discard(key)
                else:
                    self._rows[(kind, key)] = (value, self._version)
                    self._keys.setdefault(kind, set()).add(key)

    def query(self, kind: str, *, device_id: str | None = None, location_id: str | None = None,
              since: str | None = None, until: str | None = None) -> list[dict]:
        return [row for row in self.list(kind)
                if (device_id is None or row.get("device_id") == device_id)
                and (location_id is None or row.get("location_id") == location_id)
                and (since is None or row.get("ts", row.get("created_at", "")) >= since)
                and (until is None or row.get("ts", row.get("created_at", "")) <= until)]

    def delete(self, kind: str, key: str) -> None:
        with self._lock:
            self._rows.pop((kind, str(key)), None)
            self._keys.setdefault(kind, set()).discard(str(key))


class AzureTableStore:
    def __init__(self, table_client=None):
        if table_client is not None:
            self._table = table_client
            return
        from azure.data.tables import TableServiceClient
        from azure.identity import DefaultAzureCredential

        connection = storage_connection_string()
        if connection:
            service = TableServiceClient.from_connection_string(connection)
        else:
            endpoint = os.getenv("STORAGE_ACCOUNT_URL", "")
            if not endpoint.startswith("https://"):
                raise ValueError("STORAGE_ACCOUNT_URL (HTTPS Table endpoint) is required")
            service = TableServiceClient(endpoint=endpoint, credential=DefaultAzureCredential())
        self._table = service.get_table_client(os.getenv("COLDCHAIN_TABLE_NAME", "ColdChain"))

    def initialize(self) -> None:
        """Explicit provisioning step; never called by normal API requests."""
        from azure.core.exceptions import ResourceExistsError
        try:
            self._table.create_table()
        except ResourceExistsError:
            pass

    @staticmethod
    def _entity(kind: str, key: str, value: dict) -> dict:
        text = _json(value)
        if len(text) > 420_000:
            raise ValueError("Individual cloud record exceeds 840 KiB capacity")
        chunks = [text[i:i + 30_000] for i in range(0, len(text), 30_000)]
        entity = {"PartitionKey": partition_key(kind), "RowKey": row_key(kind, key), "Kind": kind,
                  "Chunks": len(chunks), **{f"Data{i:02}": chunk for i, chunk in enumerate(chunks)}}
        for source, column in (("device_id", "DeviceId"), ("location_id", "LocationId"), ("ts", "ObservedAt"), ("created_at", "CreatedAt")):
            if value.get(source) is not None:
                entity[column] = str(value[source])
        return entity

    @staticmethod
    def _record(entity) -> Record:
        text = "".join(entity[f"Data{i:02}"] for i in range(entity["Chunks"]))
        return Record(json.loads(text), entity.metadata["etag"])

    def get(self, kind: str, key: str) -> dict | None:
        from azure.core.exceptions import ResourceNotFoundError
        try:
            return self._record(self._table.get_entity(partition_key(kind), row_key(kind, key)))
        except ResourceNotFoundError:
            return None

    def list(self, kind: str) -> list[dict]:
        return self.query(kind)

    def query(self, kind: str, *, device_id: str | None = None, location_id: str | None = None,
              since: str | None = None, until: str | None = None) -> list[dict]:
        filters = ["PartitionKey eq @partition", "Kind eq @kind"]
        parameters = {"partition": partition_key(kind), "kind": kind}
        if kind in TRANSACTION_KINDS:
            filters.extend(["RowKey ge @prefix", "RowKey lt @prefix_end"])
            parameters.update(prefix=encoded_key(kind) + "-", prefix_end=encoded_key(kind) + ".")
        for column, name, value, operator in (("DeviceId", "device", device_id, "eq"),
                                             ("LocationId", "location", location_id, "eq"),
                                             ("ObservedAt", "since", since, "ge"),
                                             ("ObservedAt", "until", until, "le")):
            if value is not None:
                filters.append(f"{column} {operator} @{name}")
                parameters[name] = value
        return [self._record(entity) for entity in self._table.query_entities(
            " and ".join(filters), parameters=parameters)]

    def transaction(self, changes: list[tuple[str, str, dict | None, dict | None]]) -> None:
        from azure.core import MatchConditions
        from azure.core.exceptions import HttpResponseError
        from azure.data.tables import UpdateMode
        _check_batch(changes)
        operations = []
        total_bytes = 0
        for kind, key, expected, replacement in changes:
            entity = self._entity(kind, key, replacement if replacement is not None else {})
            total_bytes += len(_json(entity).encode("utf-8"))
            if expected is None:
                if replacement is None:
                    raise ValueError("Cannot delete an absent record")
                operations.append(("create", entity))
            else:
                version = getattr(expected, "version", None)
                if version is None:
                    raise ValueError("Transaction expected record must retain its ETag")
                options = {"etag": version, "match_condition": MatchConditions.IfNotModified}
                if replacement is None:
                    operations.append(("delete", entity, options))
                else:
                    operations.append(("update", entity, {**options, "mode": UpdateMode.REPLACE}))
        if total_bytes > 3_500_000:
            raise ValueError("Transaction payload exceeds safe 4 MiB batch budget")
        try:
            self._table.submit_transaction(operations)
        except HttpResponseError as exc:
            if exc.status_code in {404, 409, 412}:
                raise ConflictError("Transaction conflict; re-read and retry") from exc
            raise

    def create(self, kind: str, key: str, value: dict) -> bool:
        from azure.core.exceptions import ResourceExistsError
        try:
            self._table.create_entity(self._entity(kind, key, value))
            return True
        except ResourceExistsError:
            return False

    def put(self, kind: str, key: str, value: dict) -> None:
        from azure.core import MatchConditions
        from azure.core.exceptions import ResourceModifiedError, ResourceNotFoundError
        from azure.data.tables import UpdateMode
        version = getattr(value, "version", None)
        if version is None:
            if not self.create(kind, key, value):
                raise ConflictError("Record exists; re-read before updating")
            return
        try:
            self._table.update_entity(self._entity(kind, key, value), mode=UpdateMode.REPLACE,
                                      etag=version, match_condition=MatchConditions.IfNotModified)
        except (ResourceModifiedError, ResourceNotFoundError) as exc:
            raise ConflictError("Record changed; retry operation") from exc

    def compare_and_swap(self, kind: str, key: str, expected: dict, replacement: dict) -> bool:
        current = self.get(kind, key)
        if current is None or current != expected:
            return False
        version = getattr(expected, "version", None)
        if version is not None and current.version != version:
            return False
        try:
            self.put(kind, key, Record(replacement, current.version))
            return True
        except ConflictError:
            return False

    def delete(self, kind: str, key: str) -> None:
        from azure.core import MatchConditions
        from azure.core.exceptions import ResourceModifiedError, ResourceNotFoundError
        row = self.get(kind, key)
        if row is None:
            return
        try:
            self._table.delete_entity(partition_key(kind), row_key(kind, key), etag=row.version,
                                      match_condition=MatchConditions.IfNotModified)
        except ResourceModifiedError as exc:
            raise ConflictError("Record changed; retry deletion") from exc
        except ResourceNotFoundError:
            pass


@lru_cache(maxsize=1)
def get_store() -> AzureTableStore:
    return AzureTableStore()
