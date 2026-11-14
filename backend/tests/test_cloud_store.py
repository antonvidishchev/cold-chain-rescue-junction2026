"""Store tests need no Azure account, SQLite, or legacy conftest."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest

from app.cloud.settings import Settings, storage_connection_string
from app.cloud.store import AzureTableStore, ConflictError, MemoryStore, encoded_key, get_store


def test_memory_contract_copies_and_conflicts():
    store = MemoryStore()
    original = {"id": "a/#?\\", "nested": {"v": 1}}
    assert store.create("Images", original["id"], original)
    assert not store.create("Images", original["id"], original)
    original["nested"]["v"] = 99
    first = store.get("Images", original["id"])
    second = store.get("Images", original["id"])
    assert first["nested"]["v"] == 1
    first["nested"]["v"] = 2
    store.put("Images", original["id"], first)
    with pytest.raises(ConflictError):
        store.put("Images", original["id"], second)
    with pytest.raises(ConflictError):
        store.put("Images", original["id"], {"replacement": True})
    assert store.list("Unknown") == []
    assert store.list("Images")[0]["nested"]["v"] == 2
    store.delete("Images", original["id"])
    assert store.get("Images", original["id"]) is None
    store.delete("Images", original["id"])


def test_concurrent_claim_has_exactly_one_winner():
    store = MemoryStore()
    store.create("ImageAnalyses", "image", {"id": "image", "status": "pending"})
    expected = store.get("ImageAnalyses", "image")
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: store.compare_and_swap("ImageAnalyses", "image", expected,
                           {"id": "image", "status": "processing"}), range(20)))
    assert sum(results) == 1
    assert store.get("ImageAnalyses", "image")["status"] == "processing"


class Entity(dict):
    def __init__(self, value, version):
        super().__init__(deepcopy(value))
        self.metadata = {"etag": str(version)}


class FakeTable:
    def __init__(self):
        self.rows = {}
        self.version = 0
        self.last_condition = None

    def create_table(self):
        self.initialized = True

    def create_entity(self, entity):
        from azure.core.exceptions import ResourceExistsError
        key = (entity["PartitionKey"], entity["RowKey"])
        if key in self.rows:
            raise ResourceExistsError()
        self.version += 1
        self.rows[key] = Entity(entity, self.version)

    def get_entity(self, partition_key, row_key):
        from azure.core.exceptions import ResourceNotFoundError
        if (partition_key, row_key) not in self.rows:
            raise ResourceNotFoundError()
        return deepcopy(self.rows[(partition_key, row_key)])

    def query_entities(self, query, parameters):
        assert query.startswith("PartitionKey eq @partition and Kind eq @kind")
        return [deepcopy(row) for (partition, _), row in self.rows.items()
                if partition == parameters["partition"] and row["Kind"] == parameters["kind"]]

    def update_entity(self, entity, mode, etag, match_condition):
        from azure.core.exceptions import ResourceModifiedError
        key = (entity["PartitionKey"], entity["RowKey"])
        if self.rows[key].metadata["etag"] != etag:
            raise ResourceModifiedError()
        self.last_condition = match_condition
        self.version += 1
        self.rows[key] = Entity(entity, self.version)

    def delete_entity(self, partition, key, etag, match_condition):
        assert self.rows[(partition, key)].metadata["etag"] == etag
        del self.rows[(partition, key)]


def test_azure_adapter_roundtrip_safe_keys_and_etags():
    from azure.core import MatchConditions
    table = FakeTable()
    store = AzureTableStore(table)
    store.initialize()
    assert table.initialized
    value = {"id": "/\\#?\n雪", "text": "雪" * 20000, "nested": [None, True, 12.5]}
    assert store.create("ImageAnalyses", value["id"], value)
    assert not store.create("ImageAnalyses", value["id"], value)
    entity = next(iter(table.rows.values()))
    assert entity["RowKey"] == encoded_key(value["id"])
    assert len(entity["RowKey"]) == 64
    assert all(len(v.encode("utf-16-le")) <= 65536 for k, v in entity.items() if k.startswith("Data"))
    assert store.get("ImageAnalyses", value["id"]) == value
    assert store.list("ImageAnalyses") == [value]
    old = store.get("ImageAnalyses", value["id"])
    replacement = {**old, "done": True}
    assert store.compare_and_swap("ImageAnalyses", value["id"], old, replacement)
    assert not store.compare_and_swap("ImageAnalyses", value["id"], old, replacement)
    assert table.last_condition == MatchConditions.IfNotModified
    with pytest.raises(ConflictError):
        store.put("ImageAnalyses", value["id"], old)
    with pytest.raises(ConflictError):
        store.put("ImageAnalyses", value["id"], replacement)
    store.delete("ImageAnalyses", value["id"])
    assert store.get("ImageAnalyses", value["id"]) is None


def test_azure_oversized_record_fails_explicitly():
    with pytest.raises(ValueError, match="capacity"):
        AzureTableStore._entity("state", "id", {"data": "x" * 430000})


def test_no_memory_fallback_and_fail_closed_settings(monkeypatch):
    for key in ("STORAGE_CONNECTION_STRING", "STORAGE_ACCOUNT_URL", "COLDCHAIN_OPERATOR_KEY", "COLDCHAIN_DEVICE_FUNCTION_KEY", "COLDCHAIN_DEVICE_KEYS"):
        monkeypatch.delenv(key, raising=False)
    get_store.cache_clear()
    with pytest.raises(ValueError, match="STORAGE_ACCOUNT_URL"):
        get_store()
    assert Settings.load().operator_key == ""
    assert Settings.load().device_function_key == ""
    assert Settings.load().device_keys == {}
    monkeypatch.setenv("COLDCHAIN_DB_URL", "sqlite:///this-must-not-be-used.db")
    monkeypatch.setenv("COLDCHAIN_GRACE_SECONDS", "0")
    assert Settings.load().consecutive_readings == 2
    assert Settings.load().offline_seconds == 90
    assert Settings.load().rise_window_seconds == 300
    assert Settings.load().min_c == 2
    assert Settings.load().max_c == 8


@pytest.mark.parametrize("connection", [
    "DefaultEndpointsProtocol=https;AccountName=production;AccountKey=secret;EndpointSuffix=core.windows.net",
    "TableEndpoint=https://example.org;AccountName=production;AccountKey=secret",
    "UseDevelopmentStorage=true;DevelopmentStorageProxyUri=http://example.org",
])
def test_production_shared_key_connection_rejected(monkeypatch, connection):
    monkeypatch.setenv("STORAGE_CONNECTION_STRING", connection)
    with pytest.raises(ValueError):
        storage_connection_string()


def test_explicit_local_storage_allowed(monkeypatch):
    monkeypatch.setenv("STORAGE_CONNECTION_STRING", "UseDevelopmentStorage=true")
    assert storage_connection_string() == "UseDevelopmentStorage=true"


@pytest.mark.parametrize("name,value", [("COLDCHAIN_MIN_C", "nan"), ("COLDCHAIN_RISE_C", "0"), ("COLDCHAIN_OFFLINE_SECONDS", "-1")])
def test_invalid_settings_rejected(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        Settings.load()


def test_memory_transaction_atomic_conflict_and_partition_limits():
    store = MemoryStore()
    store.transaction([("Stock", "one", None, {"id": "one", "location_id": "a"}),
                       ("Transfers", "plan", None, {"id": "plan", "status": "proposed"})])
    stock = store.get("Stock", "one")
    plan = store.get("Transfers", "plan")
    changed = store.get("Transfers", "plan")
    changed["status"] = "approved"
    store.put("Transfers", "plan", changed)
    with pytest.raises(ConflictError):
        store.transaction([("Stock", "one", stock, {**stock, "location_id": "b"}),
                           ("Transfers", "plan", plan, {**plan, "status": "approved"})])
    assert store.get("Stock", "one")["location_id"] == "a"
    with pytest.raises(ValueError, match="partition"):
        store.transaction([("Readings", "a", None, {"id": "a"}), ("Stock", "b", None, {"id": "b"})])
    with pytest.raises(ValueError, match="1–100"):
        store.transaction([("Stock", str(i), None, {"id": str(i)}) for i in range(101)])


def test_durable_outbox_replays_after_projection_failure(monkeypatch):
    from app.cloud.service import CloudService, bootstrap_demo, stamp
    store = MemoryStore()
    bootstrap_demo(store)
    original_create = store.create
    def fail_archive(kind, key, value):
        if kind == "Readings":
            raise RuntimeError("archive unavailable")
        return original_create(kind, key, value)
    monkeypatch.setattr(store, "create", fail_archive)
    payload = {"device_id": "unoq-fridge-a", "temp_c": 4, "event_id": "crash", "observed_at": stamp()}
    with pytest.raises(RuntimeError, match="archive unavailable"):
        CloudService(store).ingest(payload, "temperature")
    assert len(store.list("Events")) == 1
    assert len(store.list("Outbox")) == 1
    monkeypatch.setattr(store, "create", original_create)
    assert CloudService(store).ingest(payload, "temperature")["duplicate"]
    assert len(store.list("Readings")) == 1
    assert store.list("Outbox") == []


def test_azure_transaction_encodes_one_entity_per_record_with_etags():
    from azure.core import MatchConditions
    from app.cloud.store import Record, partition_key
    class BatchTable:
        def submit_transaction(self, operations):
            self.operations = operations
    table = BatchTable()
    store = AzureTableStore(table)
    stock = Record({"id": "lot", "location_id": "a"}, 'W/"stock-v1"')
    plan = Record({"id": "plan", "status": "proposed"}, 'W/"plan-v1"')
    store.transaction([("Stock", "lot", stock, {**stock, "location_id": "b"}),
                       ("Transfers", "plan", plan, {**plan, "status": "approved"}),
                       ("Outbox", "Reading:1", None, {"id": "Reading:1", "value": {"temp_c": 4}})])
    assert len(table.operations) == 3
    assert len({operation[1]["PartitionKey"] for operation in table.operations}) == 1
    assert table.operations[0][2]["etag"] == stock.version
    assert table.operations[1][2]["etag"] == plan.version
    assert table.operations[0][2]["match_condition"] == MatchConditions.IfNotModified
    assert table.operations[2][0] == "create"
    assert partition_key("Readings") != partition_key("Stock")
    assert all(operation[1]["Chunks"] == 1 for operation in table.operations)


def test_azurite_per_record_transactions_and_atomic_rejection(monkeypatch):
    import os
    from uuid import uuid4
    from azure.data.tables import TableServiceClient
    from app.cloud.service import CloudService, bootstrap_demo, stamp
    connection = os.getenv("COLDCHAIN_TEST_AZURITE")
    if not connection:
        pytest.skip("COLDCHAIN_TEST_AZURITE required for isolated emulator")
    if "127.0.0.1" not in connection or "AccountName=devstoreaccount1;" not in connection:
        pytest.fail("Only private local Azurite is permitted")
    client = TableServiceClient.from_connection_string(connection).get_table_client("transactiontest" + uuid4().hex)
    store = AzureTableStore(client)
    store.initialize()
    try:
        assert bootstrap_demo(store)["created"]
        assert not bootstrap_demo(store)["created"]
        service = CloudService(store)
        payload = {"device_id": "unoq-fridge-a", "temp_c": 4, "event_id": "event", "observed_at": stamp()}
        assert not service.ingest(payload, "temperature")["duplicate"]
        assert service.ingest(payload, "temperature")["duplicate"]
        assert len(store.list("Readings")) == 1
        assert len(store.list("Events")) == 1
        assert not store.list("Outbox")
        plan = service.propose("fridge-a")
        service.approve(str(plan["id"]), "Test pharmacist")
        assert not [s for s in store.list("Stock") if s["location_id"] == "fridge-a"]
        stock = store.list("Stock")[0]
        stale = store.get("Transfers", str(plan["id"]))
        current = store.get("Transfers", str(plan["id"]))
        current["approved_by"] = "Other operator"
        store.put("Transfers", str(plan["id"]), current)
        with pytest.raises(ConflictError):
            store.transaction([("Stock", str(stock["id"]), stock, {**stock, "location_id": "impossible"}),
                               ("Transfers", str(plan["id"]), stale, {**stale, "approved_by": "Stale writer"})])
        assert store.get("Stock", str(stock["id"]))["location_id"] == stock["location_id"]
        assert store.get("DomainState", "v1") is None
    finally:
        client.delete_table()
