"""Client for the ColdChain cloud backend (Azure Functions).

Every event the watchdog raises goes through one function here. Each function
builds the JSON envelope and logs it. With ``BACKEND_ENABLED=1`` it is also
POSTed to ``COLDCHAIN_API_URL`` with the device credentials.

Configuration comes from the environment, falling back to a ``.env`` file next
to this module. That file holds the device keys and is gitignored: never commit
it, and never log the request headers.
"""

from __future__ import annotations

import json
import os
import queue
import random
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ENV_FILE = Path(__file__).with_name(".env")


def load_env_file(path: Path = ENV_FILE) -> None:
    """Load KEY=VALUE lines into os.environ without overriding real env vars."""
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


load_env_file()

API_URL = os.environ.get("COLDCHAIN_API_URL", "http://localhost:8000").rstrip("/")
DEVICE_ID = os.environ.get("COLDCHAIN_DEVICE_ID", "unoq-fridge-a")
BACKEND_ENABLED = os.environ.get("BACKEND_ENABLED", "0") == "1"
# An Azure Functions cold start can take well over the old 2 s.
HTTP_TIMEOUT = 20.0
MAX_ATTEMPTS = 4
RETRY_STATUSES = {408, 429, 500, 502, 503, 504}


def auth_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if os.environ.get("COLDCHAIN_DEVICE_KEY"):
        headers["x-device-key"] = os.environ["COLDCHAIN_DEVICE_KEY"]
    if os.environ.get("COLDCHAIN_DEVICE_FUNCTION_KEY"):
        headers["x-functions-key"] = os.environ["COLDCHAIN_DEVICE_FUNCTION_KEY"]
    return headers


# The deployed backend may lag the repo: its strict telemetry schema can reject
# the newer ``fridge_display_temp_c`` field with 422. After one such rejection
# we stop sending it until the app restarts (i.e. after a backend redeploy).
_optional_telemetry_fields = {"fridge_display_temp_c"}
_dropped_fields: set[str] = set()


def _post(path: str, payload: dict[str, Any]) -> tuple[int | None, str]:
    req = urllib.request.Request(
        f"{API_URL}{path}",
        data=json.dumps(payload).encode(),
        method="POST",
        headers=auth_headers(),
    )
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            return resp.status, resp.read(300).decode(errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(300).decode(errors="replace")
    except (urllib.error.URLError, OSError) as exc:
        return None, str(exc)


def _deliver(path: str, payload: dict[str, Any]) -> None:
    """POST with retries; the same event_id/ts/payload is reused so retries are idempotent."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        status, body = _post(path, payload)
        if status is not None and 200 <= status < 300:
            print(f"[backend] {path} -> {status} {body}", flush=True)
            return
        extra = _optional_telemetry_fields & payload["data"].keys()
        if status == 422 and payload["event"] == "telemetry" and extra:
            print(f"[backend] {path} rejected {sorted(extra)}; dropping them", flush=True)
            _dropped_fields.update(extra)
            payload["data"] = {k: v for k, v in payload["data"].items() if k not in extra}
            payload["event_id"] = uuid.uuid4().hex  # changed payload needs a new ID
            continue
        if status is not None and status not in RETRY_STATUSES:
            print(f"[backend] {path} -> {status} {body}", flush=True)
            return
        if attempt < MAX_ATTEMPTS:
            time.sleep(min(30, 2**attempt) + random.random())
    print(f"[backend] {path} gave up after {MAX_ATTEMPTS} attempts: {status} {body}", flush=True)


# Sending happens on one background thread so a slow backend never blocks the
# watchdog loop (buzzer, display), while events still go out in order.
_outbox: queue.Queue[tuple[str, dict[str, Any]]] = queue.Queue(maxsize=500)


def _worker() -> None:
    while True:
        path, payload = _outbox.get()
        try:
            _deliver(path, payload)
        except Exception as exc:  # never let the sender thread die
            print(f"[backend] {path} crashed: {exc}", flush=True)


if BACKEND_ENABLED:
    threading.Thread(target=_worker, name="backend-sender", daemon=True).start()


def _send(path: str, event: str, data: dict[str, Any]) -> dict[str, Any]:
    if event == "telemetry":
        data = {k: v for k, v in data.items() if k not in _dropped_fields}
    payload = {
        "device_id": DEVICE_ID,
        "event": event,
        "event_id": uuid.uuid4().hex,
        "ts": datetime.now(timezone.utc).isoformat(),
        "data": data,
    }
    print(f"[backend-stub] POST {path} {json.dumps(payload)}", flush=True)
    if not BACKEND_ENABLED:
        return payload
    try:
        _outbox.put_nowait((path, payload))
    except queue.Full:
        print(f"[backend] outbox full, dropping {event}", flush=True)
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


def report_alarm_ack(data: dict[str, Any]) -> dict[str, Any]:
    """Operator acknowledged the alarm at the fridge (Modulino Knob)."""
    return _send("/api/events/alarm-ack", "alarm_acknowledged", data)


def report_alarm_resolved(data: dict[str, Any]) -> dict[str, Any]:
    """Operator confirmed at the fridge (second knob turn) that the protocol was followed."""
    return _send("/api/events/alarm-resolved", "alarm_resolved", data)


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
    "report_alarm_ack": report_alarm_ack,
    "report_alarm_resolved": report_alarm_resolved,
    "sync_inventory": sync_inventory,
    "send_telemetry": send_telemetry,
}
