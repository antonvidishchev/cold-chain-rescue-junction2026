"""ColdChain Watchdog: Linux (MPU) side of the Arduino Uno Q.

Loop:
  1. receive temperature readings from the sketch over Bridge (``on_reading``)
  2. evaluate the local alarm rule using the config cached from the backend
  3. switch the buzzer via ``Bridge.call("set_alarm", ...)``
  4. send telemetry and poll for commands (silence / test_alarm)

The rule runs locally, so the buzzer still works when the backend is down.
Only the standard library is used for HTTP, to keep the App Lab image lean.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from arduino.app_utils import App, Bridge

API_URL = os.environ.get("COLDCHAIN_API_URL", "http://192.168.1.10:8000").rstrip("/")
DEVICE_ID = os.environ.get("COLDCHAIN_DEVICE_ID", "unoq-fridge-a")
LOOP_SECONDS = 2.0
CONFIG_REFRESH_SECONDS = 10.0
HTTP_TIMEOUT = 1.5

# Safe defaults used until the backend has been reached at least once:
# typical 2-8 C fridge range, assume stock is present (fail loud, not silent).
_config = {
    "min_c": 2.0,
    "max_c": 8.0,
    "grace_seconds": 30,
    "stock_present": True,
    "silenced": False,
}
_lock = threading.Lock()
_latest = {"temp_c": None, "humidity": None}
_state = {"out_of_range_since": None, "alarm": False, "test_until": 0.0, "seq": 0, "last_config": 0.0}


def on_reading(temp_c: float, humidity: float) -> None:
    with _lock:
        _latest["temp_c"] = float(temp_c)
        _latest["humidity"] = float(humidity)


Bridge.provide("on_reading", on_reading)


def _http(method: str, path: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{API_URL}{path}", data=data, method=method, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else None


def should_alarm(temp_c: float | None, now: float) -> bool:
    """Local alarm rule: stock present AND out of range for longer than the grace period."""
    if temp_c is None:
        return False
    out_of_range = temp_c < _config["min_c"] or temp_c > _config["max_c"]
    if not out_of_range:
        _state["out_of_range_since"] = None
        return False
    if _state["out_of_range_since"] is None:
        _state["out_of_range_since"] = now
    elapsed = now - _state["out_of_range_since"]
    return bool(_config["stock_present"]) and elapsed >= _config["grace_seconds"]


def refresh_config(now: float) -> None:
    if now - _state["last_config"] < CONFIG_REFRESH_SECONDS:
        return
    _state["last_config"] = now
    try:
        cfg = _http("GET", f"/api/devices/{DEVICE_ID}/config")
        for key in _config:
            if key in cfg:
                _config[key] = cfg[key]
    except (urllib.error.URLError, OSError, ValueError) as exc:
        print(f"[config] backend unreachable, using cached config: {exc}", flush=True)


def handle_commands(now: float) -> None:
    try:
        commands = _http("GET", f"/api/devices/{DEVICE_ID}/commands") or []
    except (urllib.error.URLError, OSError, ValueError):
        return
    for cmd in commands:
        name = cmd.get("command")
        if name == "silence":
            _config["silenced"] = True
        elif name == "unsilence":
            _config["silenced"] = False
        elif name == "test_alarm":
            _state["test_until"] = now + 3
        print(f"[command] {name}", flush=True)


def send_telemetry(temp_c: float, alarm: bool) -> None:
    _state["seq"] += 1
    payload = {
        "device_id": DEVICE_ID,
        "ts": datetime.now(timezone.utc).isoformat(),
        "temp_c": round(temp_c, 2),
        "seq": _state["seq"],
        "alarm_active": alarm,
    }
    try:
        _http("POST", "/api/telemetry", payload)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        print(f"[telemetry] send failed: {exc}", flush=True)


def loop() -> None:
    now = time.monotonic()
    refresh_config(now)
    handle_commands(now)

    with _lock:
        temp_c = _latest["temp_c"]

    alarm = should_alarm(temp_c, now)
    buzz = (alarm and not _config["silenced"]) or now < _state["test_until"]
    if not alarm:
        _config["silenced"] = False  # re-arm once back in range
    if buzz != _state["alarm"]:
        Bridge.call("set_alarm", buzz)
        _state["alarm"] = buzz

    if temp_c is not None:
        send_telemetry(temp_c, alarm)

    time.sleep(LOOP_SECONDS)


print(f"ColdChain Watchdog {DEVICE_ID} -> {API_URL}", flush=True)
App.run(user_loop=loop)
