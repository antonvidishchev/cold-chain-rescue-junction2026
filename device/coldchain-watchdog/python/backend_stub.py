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
import random
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ENV_FILE = Path(__file__).with_name(".env")


def load_env_file(path: Path = ENV_FILE) -> None:
    """Load KEY=VALUE lines into os.environ without overriding real env vars.

    A missing or unreadable file only disables the cloud upload; it must never
    stop the watchdog from starting.
    """
    try:
        if not path.is_file():
            return
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        print(f"[backend] cannot read {path.name}: {type(exc).__name__}", flush=True)
        return
    for line in lines:
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
# Alarm events are retried; telemetry is periodic, so a failed reading is simply
# replaced by the next one instead of being retried.
EVENT_ATTEMPTS = 4
EVENT_QUEUE_MAX = 200
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


def _backoff(attempt: int) -> float:
    return min(30.0, 2.0**attempt) + random.random()


def _deliver(path: str, payload: dict[str, Any], max_attempts: int) -> bool:
    """POST with retries; the same event_id/ts/payload is reused so retries are idempotent."""
    attempt, status, body = 0, None, ""
    while attempt < max_attempts:
        attempt += 1
        status, body = _post(path, payload)
        if status is not None and 200 <= status < 300:
            print(f"[backend] {path} -> {status} {body}", flush=True)
            return True
        extra = _optional_telemetry_fields & payload["data"].keys()
        if status == 422 and payload["event"] == "telemetry" and extra:
            print(f"[backend] {path} rejected {sorted(extra)}; dropping them", flush=True)
            _dropped_fields.update(extra)
            payload["data"] = {k: v for k, v in payload["data"].items() if k not in extra}
            payload["event_id"] = uuid.uuid4().hex  # changed payload needs a new ID
            attempt -= 1  # a schema downgrade is not a failed attempt
            continue
        if status is not None and status not in RETRY_STATUSES:
            break  # 4xx: retrying the same payload cannot help
        if attempt < max_attempts:
            time.sleep(_backoff(attempt))
    print(f"[backend] {path} not delivered ({attempt} attempt(s)): {status if status is not None else 'unreachable'} {body}", flush=True)
    return False


class Outbox:
    """Hands payloads from the watchdog loop to the sender thread.

    ``put_*`` never blocks and never raises, so the cloud being slow or down
    cannot stall the buzzer, display or REST API. Alarm events queue up (oldest
    dropped when full) and go out before telemetry; only the latest telemetry
    reading is kept, so an outage cannot fill memory with stale readings.
    """

    def __init__(self, max_events: int = EVENT_QUEUE_MAX) -> None:
        self._events: deque[tuple[str, dict[str, Any]]] = deque()
        self._telemetry: tuple[str, dict[str, Any]] | None = None
        self._max_events = max_events
        self._cond = threading.Condition()
        self.dropped = 0

    def put_event(self, path: str, payload: dict[str, Any]) -> None:
        with self._cond:
            if len(self._events) >= self._max_events:
                old_path, _ = self._events.popleft()
                self.dropped += 1
                print(f"[backend] outbox full, dropped oldest {old_path}", flush=True)
            self._events.append((path, payload))
            self._cond.notify()

    def put_telemetry(self, path: str, payload: dict[str, Any]) -> None:
        with self._cond:
            if self._telemetry is not None:
                self.dropped += 1  # superseded by a newer reading
            self._telemetry = (path, payload)
            self._cond.notify()

    def get(self, timeout: float | None = None) -> tuple[str, dict[str, Any], int] | None:
        """Next item and its attempt budget: events first, then the latest reading."""
        with self._cond:
            if not self._cond.wait_for(lambda: self._events or self._telemetry, timeout):
                return None
            if self._events:
                path, payload = self._events.popleft()
                return path, payload, EVENT_ATTEMPTS
            path, payload = self._telemetry
            self._telemetry = None
            return path, payload, 1

    def pending(self) -> int:
        with self._cond:
            return len(self._events) + (self._telemetry is not None)


_outbox = Outbox()


def _worker() -> None:
    while True:
        try:
            item = _outbox.get()
            if item is not None:
                _deliver(*item)
        except Exception as exc:  # never let the sender thread die
            print(f"[backend] sender error: {type(exc).__name__}: {exc}", flush=True)
            time.sleep(1.0)


if BACKEND_ENABLED:
    threading.Thread(target=_worker, name="backend-sender", daemon=True).start()


def _send(path: str, event: str, data: dict[str, Any]) -> dict[str, Any]:
    """Log the envelope and queue it for the cloud. Never raises, never blocks."""
    payload: dict[str, Any] = {"event": event, "data": data}
    try:
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
        if BACKEND_ENABLED:
            if event == "telemetry":
                _outbox.put_telemetry(path, payload)
            else:
                _outbox.put_event(path, payload)
    except Exception as exc:  # a bad payload must not break the watchdog loop
        print(f"[backend] could not queue {event}: {type(exc).__name__}: {exc}", flush=True)
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
    """Alarm resolved: second knob turn (protocol followed) or the reset command."""
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
