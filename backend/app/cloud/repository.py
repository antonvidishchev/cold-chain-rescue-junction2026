"""Lazy per-record unit of work; only changed records enter a Table transaction."""

import copy
from collections.abc import MutableMapping

from app.cloud.store import TRANSACTION_KINDS, ConflictError

KINDS = {"locations": "Locations", "devices": "Devices", "products": "Products", "stock": "Stock",
         "readings": "Readings", "alerts": "Alerts", "commands": "Commands", "transfers": "Transfers",
         "events": "Events", "timeline": "Timeline", "notifications": "Notifications",
         "device_inventory": "DeviceInventory"}


class Records(MutableMapping):
    def __init__(self, store, kind, filters=None):
        self.store = store
        self.kind = kind
        self.filters = filters or {}
        self.originals = {}
        self.current = {}
        self.loaded = False
        self.deleted = set()

    def __getitem__(self, key):
        key = str(key)
        if key in self.deleted:
            raise KeyError(key)
        if key not in self.current:
            record = self.store.get(self.kind, key)
            if record is None:
                raise KeyError(key)
            self.originals[key] = record
            self.current[key] = copy.deepcopy(dict(record))
        return self.current[key]

    def __setitem__(self, key, value):
        key = str(key)
        if key not in self.originals:
            self.originals[key] = self.store.get(self.kind, key)
        self.current[key] = value
        self.deleted.discard(key)

    def __delitem__(self, key):
        self[key]
        self.deleted.add(str(key))

    def _load(self):
        if not self.loaded:
            rows = self.store.query(self.kind, **self.filters) if self.filters else self.store.list(self.kind)
            for row in rows:
                key = str(row["id"])
                if key not in self.current and key not in self.deleted:
                    self.originals[key] = row
                    self.current[key] = copy.deepcopy(dict(row))
            self.loaded = True

    def __iter__(self):
        self._load()
        return iter([key for key in self.current if key not in self.deleted])

    def __len__(self):
        self._load()
        return len(self.current) - len(self.deleted)

    def changes(self):
        for key in self.current.keys() | self.deleted:
            original = self.originals.get(key)
            replacement = None if key in self.deleted else self.current[key]
            if original == replacement:
                continue
            if self.kind in TRANSACTION_KINDS:
                yield self.kind, key, original, replacement
            else:
                if original is not None or replacement is None:
                    raise ValueError("Archived domain records are immutable")
                outbox_key = f"{self.kind}:{key}"
                yield "Outbox", outbox_key, None, {
                    "id": outbox_key, "destination_kind": self.kind, "destination_key": key, "value": replacement,
                }


def load_state(store, meta, reading_filters=None):
    return {"next_id": meta.get("next_id", 0),
            **{name: Records(store, kind, reading_filters if name == "readings" else None)
               for name, kind in KINDS.items()}}


def project_outbox(store):
    """Create-only projections, replayable after crashes; remove only after success."""
    for pending in store.list("Outbox"):
        store.create(pending["destination_kind"], pending["destination_key"], pending["value"])
        try:
            store.transaction([("Outbox", pending["id"], pending, None)])
        except ConflictError:
            # Another projector may have removed this same immutable outbox row.
            continue
