"""Stubs for the (future) ColdChain backend.

Every event the watchdog raises goes through one function here. Today each
function builds the JSON payload and logs it. Set ``BACKEND_ENABLED=1`` to
also POST it to ``COLDCHAIN_API_URL`` once the backend exists; the endpoint
paths below are proposals for that backend.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

API_URL = os.environ.get("COLDCHAIN_API_URL", "http://localhost:8000").rstrip("/")
DEVICE_ID = os.environ.get("COLDCHAIN_DEVICE_ID", "unoq-fridge-a")
BACKEND_ENABLED = os.environ.get("BACKEND_ENABLED", "0") == "1"
HTTP_TIMEOUT = 2.0


def _send(path: str, event: str, data: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "device_id": DEVICE_ID,
        "event": event,
        "ts": datetime.now(timezone.utc).isoformat(),
        "data": data,
    }
    print(f"[backend-stub] POST {path} {json.dumps(payload)}", flush=True)
    if not BACKEND_ENABLED:
        return payload
    # TODO(backend): confirm the endpoint and auth once the backend is built.
    req = urllib.request.Request(
        f"{API_URL}{path}",
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT):
            pass
    except (urllib.error.URLError, OSError) as exc:
        print(f"[backend-stub] {path} failed: {exc}", flush=True)
    return payload


def report_unfreeze_allowed(data: dict[str, Any]) -> dict[str, Any]:
    """Unfreeze command accepted because the fridge is empty."""
    return _send("/api/events/unfreeze-allowed", "unfreeze_allowed", data)


def notify_operator_unfreeze_check(data: dict[str, Any]) -> dict[str, Any]:
    """Unfreeze command with medicines inside: ask the operator to check."""
    return _send("/api/notifications/operator", "unfreeze_check_required", data)


def report_power_outage(data: dict[str, Any]) -> dict[str, Any]:
    """Power outage with stock: protocol, safe window and reachable clinics."""
    return _send("/api/events/power-outage", "power_outage", data)


def report_doors_open(data: dict[str, Any]) -> dict[str, Any]:
    """Fridge doors left open."""
    return _send("/api/events/doors-open", "doors_open", data)


def report_fridge_tamper(data: dict[str, Any]) -> dict[str, Any]:
    """Smart fridge reports a temperature that disagrees with the Arduino sensor."""
    return _send("/api/events/fridge-tamper", "fridge_tamper", data)


def sync_inventory(data: dict[str, Any]) -> dict[str, Any]:
    """Fridge inventory changed (emptied or filled)."""
    return _send("/api/inventory/sync", "inventory_changed", data)


def send_telemetry(data: dict[str, Any]) -> dict[str, Any]:
    """Periodic temperature reading."""
    return _send("/api/telemetry", "telemetry", data)


STUBS = {
    "report_unfreeze_allowed": report_unfreeze_allowed,
    "notify_operator_unfreeze_check": notify_operator_unfreeze_check,
    "report_power_outage": report_power_outage,
    "report_doors_open": report_doors_open,
    "report_fridge_tamper": report_fridge_tamper,
    "sync_inventory": sync_inventory,
    "send_telemetry": send_telemetry,
}
