"""ColdChain Watchdog: Linux (MPU) side of the Arduino Uno Q.

* receives Modulino Thermo readings from the sketch over Bridge
* serves a REST API on :7000 (WebUI brick) used by the React dashboard
* reacts to the simulation commands via ``logic.Watchdog``
* drives the buzzer and the LED matrix through Bridge calls
* reports every event to the (future) backend through ``backend_stub``

HTTP handlers only change state and queue device actions; the App loop
performs the Bridge and backend calls, so the API stays responsive.
"""

from __future__ import annotations

import json
import queue
import threading
import time
from pathlib import Path

from arduino.app_bricks.web_ui import WebUI
from arduino.app_utils import App, Bridge
from fastapi import HTTPException

import backend_stub
from logic import COMMANDS, PATTERN_URGENT_REMINDER, Outcome, Watchdog

DATA_DIR = Path(__file__).parent / "data"
TELEMETRY_SECONDS = 30.0

medicines = json.loads((DATA_DIR / "medicines.json").read_text())
clinics_doc = json.loads((DATA_DIR / "clinics.json").read_text())

watchdog = Watchdog(medicines, clinics_doc)
lock = threading.Lock()
actions: queue.Queue[Outcome] = queue.Queue()
loop_state = {"doors_shown": False, "last_telemetry": 0.0}


# ----- Bridge: sketch -> Python ----------------------------------------
def on_reading(temp_c: float, humidity: float) -> None:
    with lock:
        watchdog.update_reading(temp_c, humidity)


Bridge.provide("on_reading", on_reading)


# ----- REST API ---------------------------------------------------------
def api_state() -> dict:
    with lock:
        return watchdog.snapshot()


def api_inventory() -> dict:
    with lock:
        return {"inventory": watchdog.inventory, "summary": watchdog.inventory_summary()}


def api_clinics() -> dict:
    with lock:
        return {
            "main": watchdog.main_site,
            "clinics": watchdog.clinics,
            "assessment": watchdog.assess_power_outage(),
        }


def api_command(name: str) -> dict:
    if name not in COMMANDS:
        raise HTTPException(status_code=404, detail=f"unknown command {name!r}; use one of {list(COMMANDS)}")
    with lock:
        outcome = watchdog.handle(name)
        state = watchdog.snapshot()
    print(f"[command] {name}: {outcome.message}", flush=True)
    actions.put(outcome)
    return {"result": outcome.to_dict(), "state": state}


ui = WebUI()
ui.expose_api("GET", "/api/state", api_state)
ui.expose_api("GET", "/api/inventory", api_inventory)
ui.expose_api("GET", "/api/clinics", api_clinics)
ui.expose_api("POST", "/api/command/{name}", api_command)


# ----- device actions ---------------------------------------------------
def bridge_call(method: str, *args) -> None:
    try:
        Bridge.call(method, *args)
    except Exception as exc:  # the sketch may still be booting
        print(f"[bridge] {method}{args} failed: {exc}", flush=True)


def apply_display(display: tuple[str, str]) -> None:
    kind, text = display
    if kind == "text":
        bridge_call("show_text", text)
    elif kind == "alarm":
        bridge_call("show_alarm", text)
    else:
        bridge_call("show_temp")


def perform(outcome: Outcome) -> None:
    if outcome.pattern is not None:
        bridge_call("play_pattern", outcome.pattern)
    if outcome.display is not None:
        apply_display(outcome.display)
        loop_state["doors_shown"] = outcome.display[0] == "text"
    for stub_name, payload in outcome.stubs:
        backend_stub.STUBS[stub_name](payload)


def loop() -> None:
    try:
        perform(actions.get(timeout=0.5))
    except queue.Empty:
        pass

    # Smart fridge vs Arduino sensor: raise the H1 alarm when they disagree.
    with lock:
        tamper = watchdog.check_fridge_tamper()
    if tamper is not None:
        print(f"[fridge] {tamper.message}", flush=True)
        perform(tamper)

    now = time.time()
    with lock:
        fridge_display = watchdog.fridge_state()["display_temp_c"]
        doors_open = watchdog.doors_open()
        idle = watchdog.idle_display()
        alarm_kind = watchdog.alarm["kind"] if watchdog.alarm else None
        temp_c, humidity = watchdog.temp_c, watchdog.humidity

    # "Close the doors" lasts 15 s, then the matrix returns to alarm / temperature.
    if loop_state["doors_shown"] and not doors_open:
        loop_state["doors_shown"] = False
        apply_display(idle)
        if alarm_kind == "power_outage":
            bridge_call("play_pattern", PATTERN_URGENT_REMINDER)

    if temp_c is not None and now - loop_state["last_telemetry"] >= TELEMETRY_SECONDS:
        loop_state["last_telemetry"] = now
        backend_stub.send_telemetry({"temp_c": temp_c, "humidity": humidity, "fridge_display_temp_c": fridge_display, "alarm": alarm_kind})


print(f"ColdChain Watchdog {backend_stub.DEVICE_ID}: API on :7000, backend stub enabled={backend_stub.BACKEND_ENABLED}", flush=True)
App.run(user_loop=loop)
