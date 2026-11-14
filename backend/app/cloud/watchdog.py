"""Validated watchdog wire contracts and device-scoped transactional ingestion."""

import hashlib
import json
from typing import Annotated, Generic, Literal, TypeVar

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.cloud.service import _id, _timeline, observed, stamp

Identifier = Annotated[str, Field(min_length=1, max_length=128)]
Quantity = Annotated[int, Field(ge=0, le=1_000_000_000)]


class Data(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class InventoryItem(Data):
    id: Identifier
    quantity: Quantity


class InventoryData(Data):
    inventory: list[InventoryItem] = Field(max_length=100)
    transferred: list[InventoryItem] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def unique_items(self):
        identifiers = [item.id for item in self.inventory]
        transferred = [item.id for item in self.transferred]
        if len(set(identifiers)) != len(identifiers) or len(set(transferred)) != len(transferred):
            raise ValueError("Inventory product IDs must be unique")
        return self


class UnfreezeData(Data):
    stocked_items: list[Identifier] = Field(max_length=100)
    units: Quantity

    @model_validator(mode="after")
    def unique_items(self):
        if len(set(self.stocked_items)) != len(self.stocked_items):
            raise ValueError("Stocked product IDs must be unique")
        return self


class Clinic(Data):
    id: Identifier
    name: Annotated[str, Field(min_length=1, max_length=200)]
    phone: Annotated[str, Field(max_length=64)] | None = None
    drive_minutes: float = Field(ge=0, le=525600)


class PowerData(InventoryData):
    protocol: Literal["P1", "P2", "P3", "P4"]
    window_minutes: float = Field(ge=0, le=525600)
    limiting_medicine: Identifier
    reachable_clinics: list[Clinic] = Field(max_length=100)


class DoorsData(Data):
    duration_s: float = Field(ge=0, le=31_536_000)
    stocked: bool


class TelemetryData(Data):
    temp_c: float = Field(ge=-273.15, le=1000)
    humidity: float | None = Field(default=None, ge=0, le=100)
    fridge_display_temp_c: float | None = Field(default=None, ge=-273.15, le=1000)
    alarm: Annotated[str, Field(max_length=128)] | None = None


class TamperData(Data):
    sensor_temp_c: float = Field(ge=-273.15, le=1000)
    fridge_display_temp_c: float = Field(ge=-273.15, le=1000)
    mismatch_c: float = Field(ge=-1273.15, le=1273.15)
    fridge_mode: Literal["normal", "defrost"]
    fridge_power_w: float = Field(ge=0, le=100000)
    stocked_items: list[Identifier] = Field(max_length=100)
    code: Literal["H1"]

    @model_validator(mode="after")
    def consistent_mismatch(self):
        if abs(self.mismatch_c - (self.fridge_display_temp_c - self.sensor_temp_c)) > 0.02:
            raise ValueError("Mismatch must equal fridge display minus sensor temperature")
        if len(self.stocked_items) != len(set(self.stocked_items)):
            raise ValueError("Stocked product IDs must be unique")
        return self


AlarmKind = Literal["power_outage", "fridge_tamper", "unfreeze"]
AlarmCode = Literal["P1", "P2", "P3", "P4", "H1"]


class AlarmAckData(Data):
    alarm_kind: AlarmKind | None
    code: AlarmCode | None
    doors: bool
    acknowledged_by: Literal["knob"]


class AlarmResolvedData(Data):
    # Null kind only for a reset that cleared nothing but the doors warning.
    alarm_kind: AlarmKind | None
    code: AlarmCode | None
    acknowledged_at: float | None = Field(ge=0, le=253402300799)
    doors: bool = False
    resolved_by: Literal["knob", "reset"]

    @model_validator(mode="after")
    def something_resolved(self):
        if self.alarm_kind is None and not self.doors:
            raise ValueError("alarm_resolved needs alarm_kind or doors")
        return self


D = TypeVar("D", bound=Data)


class Envelope(Data, Generic[D]):
    device_id: Identifier
    event_id: Identifier | None = None
    ts: str = Field(min_length=1, max_length=64)
    data: D

    @model_validator(mode="after")
    def timestamp_and_size(self):
        self.ts = stamp(observed(self.ts))
        if len(self.model_dump_json().encode("utf-8")) > 12000 or len(json.dumps(self.model_dump()).encode("ascii")) > 12000:
            raise ValueError("Watchdog envelope must not exceed 12000 encoded bytes")
        return self


class UnfreezeAllowed(Envelope[Data]):
    event: Literal["unfreeze_allowed"]


class UnfreezeCheck(Envelope[UnfreezeData]):
    event: Literal["unfreeze_check_required"]


class PowerOutage(Envelope[PowerData]):
    event: Literal["power_outage"]


class DoorsOpen(Envelope[DoorsData]):
    event: Literal["doors_open"]


class InventorySync(Envelope[InventoryData]):
    event: Literal["inventory_changed"]


class Telemetry(Envelope[TelemetryData]):
    event: Literal["telemetry"]


class FridgeTamper(Envelope[TamperData]):
    event: Literal["fridge_tamper"]


class AlarmAck(Envelope[AlarmAckData]):
    event: Literal["alarm_acknowledged"]


class AlarmResolved(Envelope[AlarmResolvedData]):
    event: Literal["alarm_resolved"]


def ingest_watchdog(service, body: Envelope) -> dict:
    payload = body.model_dump(mode="json", exclude_unset=True)
    event = payload["event"]
    event_id = payload.get("event_id") or hashlib.sha256(
        json.dumps([body.device_id, event, body.ts], separators=(",", ":")).encode()
    ).hexdigest()
    payload["event_id"] = event_id
    if event == "telemetry":
        return service.ingest({"device_id": body.device_id, "event_id": event_id, "ts": body.ts,
                               "temp_c": payload["data"]["temp_c"],
                               "alarm_active": bool(payload["data"].get("alarm"))},
                              "temperature", envelope=payload)

    received = stamp()
    key = hashlib.sha256(f"{body.device_id}:{event_id}".encode()).hexdigest()

    def operation(state):
        device, location = service._location_for(state, body.device_id)
        previous = state["events"].get(key)
        if previous is not None:
            if previous["payload"] != payload:
                raise HTTPException(409, "event_id already used for different data")
            return {**previous["result"], "duplicate": True}
        latest = device.get("watchdog_observed_at", {}).get(event)
        if event == "power_outage":
            latest = max(latest or "", device.get("last_status_at") or "", location.get("last_status_at") or "")
        elif event == "fridge_tamper":
            latest = max(latest or "", device.get("last_temperature_at") or "")
        elif event in {"alarm_acknowledged", "alarm_resolved"}:
            reports = device.get("watchdog_observed_at", {})
            latest = max(latest or "", reports.get("alarm_acknowledged", ""), reports.get("alarm_resolved", ""))
        stale = bool(latest and body.ts <= latest)
        device["last_seen"] = received
        service._incident(state, location, "OFFLINE", False, "Device heartbeat overdue")
        data = payload["data"]
        if not stale:
            device.setdefault("watchdog_observed_at", {})[event] = body.ts
            if event == "inventory_changed":
                snapshot = {"id": key, "device_id": device["id"], "location_id": location["id"],
                            "clinic_id": location["clinic_id"], "ts": body.ts, "received_at": received,
                            "event_id": event_id, "inventory": data["inventory"],
                            "stock_present": any(item["quantity"] > 0 for item in data["inventory"]),
                            "canonical_stock_updated": False,
                            "transferred": data.get("transferred", [])}
                state["device_inventory"][key] = snapshot
                # Only the pointer is mutable. The snapshot is committed via the outbox.
                device["inventory_snapshot_id"] = key
            elif event == "fridge_tamper":
                service._incident(state, location, "TAMPER", True,
                                  "H1: device reports fridge display disagrees with independent sensor; inspect the unit", "H1")
                alert = next(a for a in state["alerts"].values() if a["location_id"] == location["id"]
                             and a["type"] == "TAMPER" and a.get("recovered_at") is None
                             and a["status"] != "resolved_by_user")
                alert.update(protocol="H1", device_reported_assessment=data, assessment_source="device_unverified")
            elif event in {"alarm_acknowledged", "alarm_resolved"}:
                kind = {"power_outage": "POWER_LOSS", "fridge_tamper": "TAMPER", "unfreeze": "UNFREEZE_CHECK"}.get(data["alarm_kind"])
                kinds = {kind} if kind else set()
                if data.get("doors"):
                    kinds.add("DOORS_OPEN")
                resolving = event == "alarm_resolved"
                for alert in state["alerts"].values():
                    if (alert["location_id"] != location["id"] or alert["type"] not in kinds
                            or alert["status"] == "resolved_by_user" or body.ts < alert["created_at"]):
                        continue
                    # Acknowledge only live incidents; resolve any not yet resolved.
                    if alert.get("recovered_at") is not None if not resolving else alert["status"] == "resolved":
                        continue
                    if not resolving:
                        alert.update(status="acknowledged", acknowledged_by="knob", acknowledged_at=body.ts,
                                     device_acknowledged_at=body.ts, device_acknowledged_by="knob")
                        continue
                    # The operator at the fridge confirms the protocol was followed
                    # (knob) or cleared the alarm (reset): close the incident.
                    by = data["resolved_by"]
                    alert.update(status="resolved", resolved_at=body.ts, resolved_by=by,
                                 recovered_at=alert.get("recovered_at") or body.ts,
                                 device_resolved_at=body.ts, device_resolved_by=by)
                    if alert["type"] == "POWER_LOSS" and by == "reset":
                        location["power_on"] = True
            elif event == "doors_open":
                service._incident(state, location, "DOORS_OPEN", True, "Device reports doors left open; inspect the unit")
            elif event == "unfreeze_check_required":
                identifier = str(_id(state))
                state["notifications"][identifier] = {
                    "id": identifier, "alert_id": None, "device_id": device["id"],
                    "location_id": location["id"], "type": event, "severity": "warning",
                    "message": "Device reports stock during unfreeze; operator inspection required",
                    "created_at": received, "status": "pending", "event_id": event_id,
                }
            elif event == "power_outage":
                device["last_status_at"] = body.ts
                device["status"] = "power_outage"
                location.update(power_on=False, last_status_at=body.ts)
                service._incident(state, location, "POWER_LOSS", True,
                                  "Explicit power outage: follow protocol 25; independently assess stock", 25)
                alert = next(a for a in state["alerts"].values() if a["location_id"] == location["id"]
                             and a["type"] == "POWER_LOSS" and a.get("recovered_at") is None
                             and a["status"] != "resolved_by_user")
                alert.update(device_reported_protocol=data["protocol"],
                             device_reported_assessment={k: v for k, v in data.items() if k != "protocol"},
                             assessment_source="device_unverified", clinical_safety_certified=False)
        _timeline(state, location["id"], event, device_id=device["id"], event_id=event_id,
                  observed_at=body.ts, stale=stale)
        service._alarm(state, location)
        result = {"ok": True, "event_id": event_id, "alarm_state": location["alarm_state"],
                  "duplicate": False, "stale": stale}
        state["events"][key] = {"id": key, "device_id": device["id"], "location_id": location["id"],
                                "clinic_id": location["clinic_id"], "event_type": event, "event": event,
                                "ts": body.ts, "received_at": received, "data": data,
                                "payload": payload, "result": result}
        return result

    return service.mutate(operation)
