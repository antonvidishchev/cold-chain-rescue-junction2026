"""Atomic Table-backed domain operations and explicit fictional demo bootstrap."""

import copy
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Callable

from fastapi import HTTPException

from app.cloud.settings import Settings
from app.cloud.store import ConflictError, Store
from app.cloud.repository import KINDS, load_state, project_outbox
from app.domain import planner
from app.domain.thresholds import Range, effective_range

STATE_KIND = "DomainMeta"
STATE_KEY = "v2"
COLLECTIONS = tuple(KINDS)
COMMANDS = {"silence", "unsilence", "test_alarm", "capture_image"}
CHECKLIST_LABELS = {
    "inspect": "Unit is inspected",
    "protect": "Incident acted upon. Stock transferred to another unit or location",
    "verify": "Recovery verified",
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def stamp(value: datetime | None = None) -> str:
    return (value or utcnow()).astimezone(timezone.utc).isoformat()


def observed(value: str | datetime | None) -> datetime:
    if value is None:
        return utcnow()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
        if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
            raise ValueError("UTC offset required")
        if parsed > utcnow() + timedelta(minutes=5):
            raise ValueError("Observed time is too far in the future")
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, AttributeError) as exc:
        raise HTTPException(422, "observed_at/ts must be an ISO UTC timestamp, not over five minutes in the future") from exc


def empty_state() -> dict:
    return {**{name: {} for name in COLLECTIONS}, "next_id": 0}


def _id(state: dict) -> int:
    state["next_id"] += 1
    return state["next_id"]


def _get(state: dict, collection: str, key: str | int) -> dict:
    value = state[collection].get(str(key))
    if value is None:
        raise HTTPException(404, f"Unknown {collection} record")
    return value


def _timeline(state: dict, location_id: str, event: str, **details) -> None:
    key = _id(state)
    state["timeline"][str(key)] = {"id": key, "location_id": location_id, "type": event,
                                   "created_at": stamp(), **details}


def bootstrap_demo(store: Store) -> dict:
    """Explicit, idempotent fixture: five fictional clinics, never request-time seeding."""
    settings = Settings.load()
    state = empty_state()
    locations = [
        ("fridge-a", "Helsinki", "helsinki", "fridge", 20),
        ("fridge-b", "Espoo", "espoo", "backup_fridge", 8),
        ("clinic-c", "Tampere", "tampere", "partner_site", 15),
        ("clinic-vantaa", "Vantaa", "vantaa", "partner_site", 20),
        ("clinic-oulu", "Oulu", "oulu", "partner_site", 20),
    ]
    for identifier, city, clinic_id, kind, capacity in locations:
        state["locations"][identifier] = {
            "id": identifier, "clinic_id": clinic_id, "name": f"{city} Demo Clinic (fictional)",
            "city": city, "address": f"Fictional demonstration site, {city}", "synthetic": True,
            "kind": kind, "min_c": settings.min_c, "max_c": min(settings.max_c, 5.0) if identifier == "clinic-c" else settings.max_c,
            "capacity_units": capacity, "monitored": True, "power_on": True,
            "reported_temp_c": None, "camera_stock_present": None, "alarm_state": "NORMAL",
            "out_of_range_since": None, "last_temp_c": None, "last_reading_at": None,
        }
        device_id = "unoq-fridge-a" if identifier == "fridge-a" else f"unoq-{identifier}"
        state["devices"][device_id] = {
            "id": device_id, "location_id": identifier, "clinic_id": clinic_id,
            "last_seen": None, "registered_at": stamp(), "last_seq": 0,
            "silenced": False, "status": "nominal", "last_temperature_at": None, "last_status_at": None,
        }
    for product_id, name, upper, minutes in [
        ("insulin-aspart", "Insulin aspart (pens)", 8, 60),
        ("mmr-vaccine", "MMR vaccine", 8, 30),
        ("influenza-vaccine", "Influenza vaccine", 8, 30),
        ("pcr-reagent", "PCR master mix", 6, 15),
    ]:
        state["products"][product_id] = {"id": product_id, "name": name, "min_c": 2,
            "max_c": upper, "max_excursion_minutes": minutes, "notes": "Fictional demo values; follow product SmPC."}
    for product, location, quantity, units in [
        ("insulin-aspart", "fridge-a", 40, 4), ("mmr-vaccine", "fridge-a", 30, 3),
        ("influenza-vaccine", "fridge-a", 60, 6), ("pcr-reagent", "fridge-a", 10, 2),
        ("insulin-aspart", "fridge-b", 20, 2),
    ]:
        identifier = _id(state)
        state["stock"][str(identifier)] = {"id": identifier, "product_id": product,
            "location_id": location, "quantity": quantity, "units": units}
    if store.get(STATE_KIND, STATE_KEY) is not None:
        return {"created": False, "clinics": 5}
    changes = [(STATE_KIND, STATE_KEY, None, {"id": STATE_KEY, "next_id": state["next_id"]})]
    for collection in ("locations", "devices", "products", "stock"):
        changes.extend((KINDS[collection], key, None, value) for key, value in state[collection].items())
    try:
        store.transaction(changes)
    except ConflictError:
        if store.get(STATE_KIND, STATE_KEY) is None:
            raise
        return {"created": False, "clinics": 5}
    return {"created": True, "clinics": 5}


class CloudService:
    def __init__(self, store: Store):
        self.store = store

    def state(self) -> dict:
        meta = self.store.get(STATE_KIND, STATE_KEY) or {"next_id": 0}
        return load_state(self.store, meta)

    def mutate(self, operation: Callable[[dict], object], reading_filters=None):
        for _ in range(8):
            self.flush_notifications()
            meta = self.store.get(STATE_KIND, STATE_KEY)
            state = load_state(self.store, meta or {"next_id": 0}, reading_filters)
            result = operation(state)
            changes = []
            for name in KINDS:
                changes.extend(state[name].changes())
            if changes:
                # The small revision row serializes decisions that depend on multiple
                # records, while every device/stock/event remains a separate entity.
                replacement = {"id": STATE_KEY, "next_id": state["next_id"],
                               "revision": (meta or {}).get("revision", 0) + 1}
                changes.append((STATE_KIND, STATE_KEY, meta, replacement))
                try:
                    self.store.transaction(changes)
                except ConflictError:
                    continue
            self.flush_notifications()
            return copy.deepcopy(result)
        raise HTTPException(409, "Concurrent update; retry request")

    def flush_notifications(self, state: dict | None = None) -> None:
        # Projection also drains reading history; committed outbox rows survive a crash.
        try:
            project_outbox(self.store)
        except ConflictError:
            pass

    def device(self, device_id: str) -> dict:
        device, _ = self._location_for(self.state(), device_id)
        return device

    def device_inventory(self, device_id: str) -> dict:
        device = self.device(device_id)
        key = device.get("inventory_snapshot_id")
        if key is None:
            raise HTTPException(404, "Device has not synced inventory")
        snapshot = self.store.get("DeviceInventory", key)
        if snapshot is None:
            # A committed snapshot is visible even before a crashed projector resumes.
            pending = self.store.get("Outbox", f"DeviceInventory:{key}")
            snapshot = pending["value"] if pending else None
        if snapshot is None:
            raise HTTPException(503, "Device inventory projection unavailable")
        return snapshot

    @staticmethod
    def _location_for(state: dict, device_id: str, clinic_id: str | None = None, location_id: str | None = None):
        device = _get(state, "devices", device_id)
        location = _get(state, "locations", device["location_id"])
        if not device.get("active", True) or not location.get("active", True):
            raise HTTPException(409, "Device or location is retired")
        if clinic_id is not None and clinic_id not in {location["clinic_id"], location["id"]}:
            raise HTTPException(422, "Device/clinic mismatch")
        if location_id is not None and location_id != location["id"]:
            raise HTTPException(422, "Device/location mismatch")
        return device, location

    @staticmethod
    def _range(state: dict, location: dict) -> Range:
        ranges = [Range(state["products"][s["product_id"]]["min_c"], state["products"][s["product_id"]]["max_c"])
                  for s in state["stock"].values() if s["location_id"] == location["id"] and s["quantity"] > 0]
        product_range = effective_range(ranges)
        if product_range:
            return Range(max(location["min_c"], product_range.min_c), min(location["max_c"], product_range.max_c))
        return Range(location["min_c"], location["max_c"])

    def config(self, device_id: str) -> dict:
        state = self.state()
        device, location = self._location_for(state, device_id)
        rng = self._range(state, location)
        return {"device_id": device_id, "location_id": location["id"], "clinic_id": location["clinic_id"],
                "min_c": rng.min_c, "max_c": rng.max_c, "grace_seconds": 0,
                "stock_present": self._stock_present(state, location), "silenced": device["silenced"],
                "offline_seconds": Settings.load().offline_seconds}

    @staticmethod
    def _stock_present(state, location):
        if location["camera_stock_present"] is not None:
            return location["camera_stock_present"]
        return any(s["location_id"] == location["id"] and s["quantity"] > 0 for s in state["stock"].values())

    def inventory(self) -> list[dict]:
        state = self.state()
        result = []
        for location in state["locations"].values():
            if not location.get("active", True):
                continue
            stock = [{**s, "product": state["products"][s["product_id"]]} for s in state["stock"].values()
                     if s["location_id"] == location["id"]]
            used = sum(s["units"] for s in stock)
            rng = self._range(state, location)
            from app.cloud.display_status import latest_display_status
            display_status, display_at = latest_display_status(
                self.store.query("Events", location_id=location["id"]) if location.get("monitored", True) else [],
                [a for a in state["alerts"].values() if a["location_id"] == location["id"]],
                location["alarm_state"])
            result.append({**location, "display_status": display_status, "display_status_at": display_at, "stock": stock, "used_units": used,
                "free_units": location["capacity_units"] - used, "stock_present": self._stock_present(state, location),
                "effective_range": {"min_c": rng.min_c, "max_c": rng.max_c},
                "devices": [d for d in state["devices"].values() if d["location_id"] == location["id"] and d.get("active", True)]})
        return result

    @staticmethod
    def _incident(state: dict, location: dict, kind: str, active: bool, message: str, protocol: int | str | None = None):
        existing = next((a for a in state["alerts"].values() if a["location_id"] == location["id"]
                         and a["type"] == kind and a.get("recovered_at") is None
                         and a["status"] != "resolved_by_user"), None)
        if not active:
            if existing:
                existing["recovered_at"] = stamp()
                _timeline(state, location["id"], "recovery", alert_id=existing["id"], incident_type=kind)
            return
        if existing:
            return
        identifier = _id(state)
        created = stamp()
        alert = {"id": identifier, "location_id": location["id"], "clinic_id": location["clinic_id"],
            "type": kind, "message": message, "created_at": created, "status": "open",
            "acknowledged_by": None, "acknowledged_at": None, "recovered_at": None, "protocol": protocol,
            "checklist": [{"id": item_id, "label": label, "done": False}
                          for item_id, label in CHECKLIST_LABELS.items()]}
        state["alerts"][str(identifier)] = alert
        state["notifications"][str(identifier)] = {"id": str(identifier), "alert_id": identifier,
            "location_id": location["id"], "type": kind, "message": message,
                        "severity": "warning" if kind == "UNFREEZE_CHECK" else "critical",
            "created_at": created, "status": "pending"}
        _timeline(state, location["id"], "incident", alert_id=identifier, incident_type=kind)

    @staticmethod
    def _alarm(state: dict, location: dict) -> None:
        active = {a["type"] for a in state["alerts"].values()
                  if a["location_id"] == location["id"] and a.get("recovered_at") is None
                  and a["status"] != "resolved_by_user"}
        location["alarm_state"] = next((kind for kind in ("POWER_LOSS", "FAILURE", "OFFLINE", "OVERHEAT", "EXCURSION", "RAPID_RISE", "TAMPER", "DOORS_OPEN", "UNFREEZE_CHECK")
                                       if kind in active), "NORMAL")

    def _evaluate_temperature(self, state: dict, device: dict, location: dict) -> None:
        settings = Settings.load()
        readings = device.get("recent_readings", [])
        if not readings:
            return
        rng = self._range(state, location)
        tail = readings[-settings.consecutive_readings:]
        excursion = len(tail) >= settings.consecutive_readings and all(not rng.contains(r["temp_c"]) for r in tail)
        if excursion or rng.contains(readings[-1]["temp_c"]):
            self._incident(state, location, "EXCURSION", excursion, "Repeated temperatures outside the permitted range")
        cutoff = datetime.fromisoformat(readings[-1]["ts"]) - timedelta(seconds=settings.rise_window_seconds)
        before = [r for r in readings if datetime.fromisoformat(r["ts"]) <= cutoff]
        rise = False
        if before:
            baseline = before[-1]
            # Require coverage without a gap longer than the requested window.
            coverage = [baseline] + [r for r in readings if r["ts"] > baseline["ts"]]
            gaps_ok = all((datetime.fromisoformat(b["ts"]) - datetime.fromisoformat(a["ts"])).total_seconds()
                          <= settings.rise_window_seconds for a, b in zip(coverage, coverage[1:]))
            if gaps_ok and len(coverage) >= 2:
                first, second = coverage[:2]
                span = (datetime.fromisoformat(second["ts"]) - datetime.fromisoformat(first["ts"])).total_seconds()
                fraction = (cutoff - datetime.fromisoformat(first["ts"])).total_seconds() / span if span else 0
                baseline_c = first["temp_c"] + fraction * (second["temp_c"] - first["temp_c"])
                rise = readings[-1]["temp_c"] - baseline_c >= settings.rise_c
        self._incident(state, location, "RAPID_RISE", rise, "Temperature rose by the configured limit over a covered observation window")
        reported = location.get("reported_temp_c")
        tamper = reported is not None and abs(reported - readings[-1]["temp_c"]) >= 2 and self._stock_present(state, location)
        self._incident(state, location, "TAMPER", tamper, "Fridge report disagrees with independent telemetry")
        self._alarm(state, location)

    def ingest(self, payload: dict, event_type: str, *, envelope: dict | None = None) -> dict:
        when = observed(payload.get("observed_at") or payload.get("ts"))
        received = stamp()
        normalized = {**payload, "observed_at": stamp(when), "event_type": event_type}
        event_id = payload.get("event_id")
        fingerprint = hashlib.sha256(str(sorted(normalized.items())).encode()).hexdigest()
        def operation(state):
            device, location = self._location_for(state, payload["device_id"], payload.get("clinic_id"), payload.get("location_id"))
            event_key = hashlib.sha256(f"{device['id']}:{event_id}".encode()).hexdigest() if event_id else None
            if event_key and event_key in state["events"]:
                previous = state["events"][event_key]
                # Absent observed_at is server-generated, so compare original payload.
                if (previous["payload"] != (envelope if envelope is not None else payload)
                        or previous["event_type"] != (envelope["event"] if envelope is not None else event_type)):
                    raise HTTPException(409, "event_id already used for different data")
                return {**previous["result"], "duplicate": True}
            device["last_seen"] = received
            self._incident(state, location, "OFFLINE", False, "Device heartbeat overdue")
            latest_field = "last_temperature_at" if event_type == "temperature" else "last_status_at"
            stale = device.get(latest_field) is not None and stamp(when) <= device[latest_field]
            if event_type == "status" and location.get("last_status_at"):
                stale = stale or stamp(when) <= location["last_status_at"]
            if event_type == "temperature":
                identifier = _id(state)
                reading = {"id": identifier, "device_id": device["id"], "location_id": location["id"],
                    "clinic_id": location["clinic_id"], "ts": stamp(when), "observed_at": stamp(when),
                    "temp_c": payload["temp_c"], "alarm_active": payload.get("alarm_active", False),
                    "seq": payload.get("seq", 0), "event_id": event_id, "received_at": received, "stale": stale}
                if envelope is not None:
                    for field in ("humidity", "fridge_display_temp_c"):
                        if field in envelope["data"]:
                            reading[field] = envelope["data"][field]
                state["readings"][str(identifier)] = reading
                if not stale:
                    device[latest_field] = stamp(when)
                    device["last_seq"] = payload.get("seq", 0)
                    settings = Settings.load()
                    recent = device.get("recent_readings", []) + [{"ts": reading["ts"], "temp_c": reading["temp_c"]}]
                    cutoff = stamp(when - timedelta(seconds=settings.rise_window_seconds))
                    older = [r for r in recent if r["ts"] <= cutoff]
                    window = ([older[-1]] if older else []) + [r for r in recent if r["ts"] > cutoff]
                    # Bounded working window, not telemetry history. If an unusually
                    # dense stream evicts the baseline, rise detection fails safe.
                    keep = max(1024, settings.consecutive_readings)
                    device["recent_readings"] = window[-keep:]
                    if location.get("last_reading_at") is None or stamp(when) > location["last_reading_at"]:
                        location["last_temp_c"] = payload["temp_c"]
                        location["last_reading_at"] = stamp(when)
                        if "fridge_display_temp_c" in reading:
                            location["reported_temp_c"] = reading["fridge_display_temp_c"]
                            location["reported_temp_at"] = stamp(when)
                    if envelope is not None and envelope["data"].get("alarm") == "unfreeze":
                        self._incident(state, location, "UNFREEZE_CHECK", True,
                                       "Device reports stock during unfreeze; operator inspection required")
                    self._evaluate_temperature(state, device, location)
            elif not stale:
                device[latest_field] = stamp(when)
                device["status"] = payload["status"]
                location["last_status_at"] = stamp(when)
                location["power_on"] = payload["status"] != "power_outage"
                self._incident(state, location, "POWER_LOSS", payload["status"] == "power_outage", "Explicit power outage: follow protocol 25", 25)
                self._incident(state, location, "FAILURE", payload["status"] == "failure", "Device reported a failure")
                self._incident(state, location, "OVERHEAT", payload["status"] == "overheat", "Device reported overheating")
                _timeline(state, location["id"], "status", device_id=device["id"], status=payload["status"], observed_at=stamp(when))
            self._alarm(state, location)
            result = {"ok": True, "alarm_state": location["alarm_state"], "duplicate": False, "stale": stale}
            if event_key:
                state["events"][event_key] = {
                    "id": event_key, "payload": envelope if envelope is not None else payload,
                    "event_type": envelope["event"] if envelope is not None else event_type,
                    "event": envelope["event"] if envelope is not None else event_type,
                    "device_id": device["id"], "location_id": location["id"], "clinic_id": location["clinic_id"],
                    "ts": stamp(when), "received_at": received,
                    "data": envelope["data"] if envelope is not None else payload,
                    "fingerprint": fingerprint, "result": result,
                }
            return result
        return self.mutate(operation)

    @staticmethod
    def _pending(state: dict, device_id: str, now: datetime | None = None) -> list[dict]:
        current = stamp(now)
        return [c for c in state["commands"].values() if c["device_id"] == device_id
                and c["status"] == "pending" and c["expires_at"] > current]

    def pending(self, device_id: str) -> list[dict]:
        state = self.state()
        self._location_for(state, device_id)
        return self._pending(state, device_id)

    @staticmethod
    def _queue(state: dict, device_id: str, command: str, expires_at: str | None = None) -> dict:
        identifier = _id(state)
        record = {"id": identifier, "device_id": device_id, "command": command, "created_at": stamp(),
            "expires_at": expires_at or stamp(utcnow() + timedelta(seconds=Settings.load().command_ttl_seconds)),
            "status": "pending", "delivered": False, "acknowledged_at": None}
        state["commands"][str(identifier)] = record
        return record

    def queue(self, device_id: str, command: str, expires_at: str | None = None) -> dict:
        if command not in COMMANDS:
            raise HTTPException(400, f"Unknown command; expected one of {sorted(COMMANDS)}")
        if expires_at:
            try:
                expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                if expiry.tzinfo is None or expiry.utcoffset() != timedelta(0) or expiry <= utcnow():
                    raise ValueError("Expected future UTC time")
            except (TypeError, ValueError) as exc:
                raise HTTPException(422, "Command expiry must be a future UTC timestamp") from exc
            expires_at = stamp(expiry)
        def operation(state):
            _get(state, "devices", device_id)
            return self._queue(state, device_id, command, expires_at)
        return self.mutate(operation)

    def heartbeat(self, device_id: str, clinic_id: str | None = None) -> dict:
        def operation(state):
            device, location = self._location_for(state, device_id, clinic_id)
            device["last_seen"] = stamp()
            self._incident(state, location, "OFFLINE", False, "Device heartbeat overdue")
            self._alarm(state, location)
            return {"ok": True, "device_id": device_id, "last_seen": device["last_seen"], "commands": self._pending(state, device_id)}
        return self.mutate(operation)

    def ack_command(self, device_id: str, command_id: str) -> dict:
        def operation(state):
            device, _ = self._location_for(state, device_id)
            command = _get(state, "commands", command_id)
            if command["device_id"] != device_id:
                raise HTTPException(404, "Command not found")
            if command["status"] == "acknowledged":
                return command
            if command["expires_at"] <= stamp():
                raise HTTPException(409, "Command expired")
            command.update(status="acknowledged", delivered=True, acknowledged_at=stamp())
            if command["command"] in {"silence", "unsilence"}:
                device["silenced"] = command["command"] == "silence"
            return command
        return self.mutate(operation)

    def alert_action(self, alert_id: str, action: str, by: str | None = None) -> dict:
        def operation(state):
            alert = _get(state, "alerts", alert_id)
            if alert["status"] == "resolved_by_user":
                raise HTTPException(409, "Incident is already resolved by a public user")
            if action == "ack":
                if alert["status"] in {"acknowledged", "resolved"}:
                    return alert
                alert.update(status="acknowledged", acknowledged_by=by, acknowledged_at=stamp())
                for device in state["devices"].values():
                    if device["location_id"] == alert["location_id"]:
                        device["silenced"] = True
                        self._queue(state, device["id"], "silence")
            else:
                if alert["status"] == "resolved":
                    return alert
                if not alert["recovered_at"]:
                    raise HTTPException(409, "Recovery must be observed before resolution")
                alert.update(status="resolved", resolved_at=stamp())
            _timeline(state, alert["location_id"], action, alert_id=alert["id"], by=by)
            return alert
        return self.mutate(operation)

    def public_checklist(self, alert_id: str, item_id: str, done: bool) -> dict:
        if item_id not in CHECKLIST_LABELS or type(done) is not bool:
            raise HTTPException(422, "Expected a known checklist item and boolean done")

        def operation(state):
            alert = _get(state, "alerts", alert_id)
            item = next((i for i in alert["checklist"] if i["id"] == item_id), None)
            if item is None:
                raise HTTPException(404, "Checklist item not found")
            if alert["status"] == "resolved_by_user":
                if done and item.get("done") is True:
                    return alert
                raise HTTPException(409, "Incident is already resolved by a public user")
            if alert["status"] == "resolved":
                raise HTTPException(409, "Incident is already resolved")
            if item.get("done") is done:
                return alert
            updated = stamp()
            item.update(done=done, by="public user", updated_at=updated)
            _timeline(state, alert["location_id"], "public_checklist", alert_id=alert["id"],
                      item_id=item_id, done=done, by="public user")
            checked = {i["id"] for i in alert["checklist"] if i.get("done") is True}
            if CHECKLIST_LABELS.keys() <= checked:
                # User testimony closes this incident, not the measured hazard.
                alert.update(status="resolved_by_user", user_resolved_at=updated,
                             resolution_source="public_checklist", user_resolved_by="public user")
                _timeline(state, alert["location_id"], "resolved_by_user", alert_id=alert["id"],
                          by="public user", resolution_source="public_checklist")
                self._alarm(state, _get(state, "locations", alert["location_id"]))
            return alert

        return self.mutate(operation)

    def checklist(self, alert_id: str, item_id: str, done: bool, by: str) -> dict:
        def operation(state):
            alert = _get(state, "alerts", alert_id)
            if alert["status"] == "resolved_by_user":
                raise HTTPException(409, "Incident is already resolved by a public user")
            item = next((i for i in alert["checklist"] if i["id"] == item_id), None)
            if item is None:
                raise HTTPException(404, "Checklist item not found")
            item.update(done=done, by=by, updated_at=stamp())
            _timeline(state, alert["location_id"], "checklist", alert_id=alert["id"], item_id=item_id, done=done, by=by)
            return alert
        return self.mutate(operation)

    def propose(self, source_id: str) -> dict:
        def operation(state):
            source = _get(state, "locations", source_id)
            items = []
            for stock in state["stock"].values():
                if stock["location_id"] != source_id:
                    continue
                product = state["products"][stock["product_id"]]
                items.append(planner.Item(stock["id"], product["id"], product["name"], Range(product["min_c"], product["max_c"]), stock["quantity"], stock["units"]))
            targets = [planner.Target(loc["id"], loc["name"], loc["kind"], Range(loc["min_c"], loc["max_c"]),
                loc["capacity_units"] - sum(s["units"] for s in state["stock"].values() if s["location_id"] == loc["id"]), loc["power_on"])
                for loc in state["locations"].values() if loc["id"] != source_id and loc.get("active", True)]
            result = planner.propose(items, targets)
            identifier = _id(state)
            plan = {"id": identifier, "source_location_id": source["id"], "status": "proposed", "created_at": stamp(),
                "approved_by": None, "approved_at": None, "moves": result.moves, "unplaced": result.unplaced,
                "rationale": "Deterministic powered, compatible targets with available capacity; backup fridge preferred."}
            state["transfers"][str(identifier)] = plan
            _timeline(state, source_id, "transfer_proposed", plan_id=identifier)
            return plan
        return self.mutate(operation)

    def approve(self, plan_id: str, by: str) -> dict:
        def operation(state):
            plan = _get(state, "transfers", plan_id)
            if plan["status"] != "proposed":
                raise HTTPException(409, f"Plan is already {plan['status']}")
            for move in plan["moves"]:
                item = _get(state, "stock", move["stock_id"])
                target = _get(state, "locations", move["target_location_id"])
                product = _get(state, "products", item["product_id"])
                used = sum(s["units"] for s in state["stock"].values() if s["location_id"] == target["id"])
                if item["location_id"] != plan["source_location_id"] or item["quantity"] != move["quantity"] or item["units"] != move["units"]:
                    raise HTTPException(409, "Inventory changed; propose a new plan")
                if not target.get("active", True) or not target["power_on"] or used + item["units"] > target["capacity_units"] or not Range(target["min_c"], target["max_c"]).fits_within(Range(product["min_c"], product["max_c"])):
                    raise HTTPException(409, "Target conditions changed; propose a new plan")
                item["location_id"] = target["id"]
            plan.update(status="approved", approved_by=by, approved_at=stamp())
            _timeline(state, plan["source_location_id"], "transfer_approved", plan_id=plan["id"], by=by)
            return plan
        return self.mutate(operation)

    def simulate(self, action: str, payload: dict) -> dict:
        def operation(state):
            location = _get(state, "locations", payload["location_id"])
            if action == "power":
                location["power_on"] = payload["on"]
                self._incident(state, location, "POWER_LOSS", not payload["on"], "Explicit power outage: follow protocol 25", 25)
            elif action == "camera":
                location["camera_stock_present"] = payload["stock_present"]
            else:
                location["reported_temp_c"] = payload["temp_c"]
            for device in state["devices"].values():
                if device["location_id"] == location["id"]:
                    self._evaluate_temperature(state, device, location)
            self._alarm(state, location)
            return location
        return self.mutate(operation)

    def check_offline(self, now: datetime | None = None) -> list[dict]:
        current = now or utcnow()
        def operation(state):
            overdue = []
            for device in state["devices"].values():
                if not device.get("active", True):
                    continue
                seen = datetime.fromisoformat(device["last_seen"] or device["registered_at"])
                offline = (current - seen).total_seconds() >= Settings.load().offline_seconds
                location = state["locations"][device["location_id"]]
                self._incident(state, location, "OFFLINE", offline, "Device heartbeat overdue")
                self._alarm(state, location)
                if offline:
                    overdue.append({"device_id": device["id"], "location_id": location["id"]})
            return overdue
        return self.mutate(operation)


def check_offline(store: Store, now: datetime | None = None) -> list[dict]:
    return CloudService(store).check_offline(now)


seed_demo = bootstrap_demo
