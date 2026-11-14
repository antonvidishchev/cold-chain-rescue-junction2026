"""Decision logic of the ColdChain Watchdog.

Pure Python with no Uno Q imports, so it can be unit-tested on a laptop.
``main.py`` turns each :class:`Outcome` into Bridge calls (buzzer, LED matrix)
and backend stub calls.
"""

from __future__ import annotations

import copy
import random
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

# Buzzer patterns understood by the sketch (``play_pattern``).
PATTERN_STOP = 0
PATTERN_UNFREEZE = 1
PATTERN_URGENT = 2
PATTERN_DOORS = 3
PATTERN_URGENT_REMINDER = 4  # chirp every few seconds, no siren
PATTERN_ACK = 5  # short rising confirmation chirp

# Modulino Knob: this many clockwise detents within the window acknowledge the alarm.
KNOB_ACK_STEPS = 5
KNOB_WINDOW_S = 3.0
ACK_TEXT = "ALARM ACK"
ACK_MESSAGE_SECONDS = 5
RESOLVED_TEXT = "DONE"

DOORS_ALARM_SECONDS = 15
# Time to pack the stock into cool boxes and load the car, added to the drive.
HANDLING_MINUTES = 15

DOORS_TEXT = "CLOSE THE DOORS"
UNFREEZE_TEXT = "CHECK"

HACK_TEXT = "H1"  # emergency code of the runbook: fridge data mismatch
HACK_TITLE = "Fridge screen disagrees with the sensor: trust the sensor, isolate the fridge, call IT security"

# Simulated smart fridge (typical cloud-API fields: air temperature, setpoint,
# door contact, compressor / defrost state, power draw, error code).
FRIDGE_MODEL = "SmartFridge SF-200 (simulated)"
FRIDGE_SETPOINT_C = 5.0
# A healthy fridge's own probe tracks the Arduino sensor but usually reads a
# little colder: mean offset plus per-reading noise, so now and then it is
# slightly warmer. Clamped well inside TAMPER_TOLERANCE_C.
FRIDGE_SENSOR_OFFSET_C = -0.3
FRIDGE_SENSOR_NOISE_C = 0.2  # standard deviation per reading
FRIDGE_SENSOR_MAX_DEV_C = 1.0
FAKE_DISPLAY_TEMP_C = 4.0  # what a hacked fridge screen keeps showing
TAMPER_TOLERANCE_C = 2.0  # max |Arduino - fridge screen| before the alarm
FRIDGE_POWER_NORMAL_W = 85.0
FRIDGE_POWER_DEFROST_W = 320.0
# DEMO ONLY: a hacked fridge defrosts, so its interior warms up. The board sits
# at room temperature (shifted to fridge level by the sketch), so we add the
# warming on top of the sensor reading while the hack is active.
DEFROST_WARMING_C_PER_S = 1.0
DEFROST_WARMING_MAX_C = 10.0

# Simulated fridge camera: stills served from assets/camera/<frame>.jpg,
# named fridge_[empty_]<scene> depending on whether the fridge holds stock.
CAMERA_NORMAL = "normal"
CAMERA_DOOR_OPEN = "door_open"
CAMERA_HEATING = "heating"
CAMERA_POWER_OUTAGE = "power_outage"

COMMANDS = ("unfreeze", "power_outage", "doors_open", "hack_fridge", "empty", "fill", "reset")


@dataclass
class Outcome:
    """What the device must do in reaction to a command."""

    command: str
    message: str
    pattern: int | None = None  # buzzer pattern to play; None = leave as is
    display: tuple[str, str] | None = None  # ("text"|"alarm"|"temp", text)
    stubs: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"command": self.command, "message": self.message, "stubs": [name for name, _ in self.stubs]}


def select_protocol(window_minutes: int, reachable: list[dict]) -> str:
    """Protocol id from the printed runbook (docs/runbook.md)."""
    if not reachable:
        return "P4"
    if window_minutes <= 60:
        return "P1"
    if window_minutes <= 240:
        return "P2"
    return "P3"


PROTOCOL_TITLES = {
    "P1": "Critical: transfer immediately to the nearest reachable clinic",
    "P2": "Urgent: call clinics in order and order a courier",
    "P3": "Watch: keep doors closed, prepare transfer",
    "P4": "No clinic reachable in time: pack on site and quarantine",
}


class Watchdog:
    def __init__(
        self,
        medicines: list[dict],
        clinics_doc: dict,
        clock: Callable[[], float] = time.time,
        rng: random.Random | None = None,
    ):
        self.rng = rng or random.Random()
        self.fridge_offset_c: float = FRIDGE_SENSOR_OFFSET_C  # redrawn on every reading
        self._catalogue = copy.deepcopy(medicines)
        self.inventory: list[dict] = copy.deepcopy(medicines)
        self.main_site: dict = clinics_doc["main"]
        self.clinics: list[dict] = sorted(clinics_doc["clinics"], key=lambda c: c["drive_minutes"])
        self.clock = clock
        self.alarm: dict | None = None
        self.doors_open_until: float = 0.0
        self.temp_c: float | None = None
        self.humidity: float | None = None
        self.temp_ts: float | None = None
        self.events: deque[dict] = deque(maxlen=50)
        self.raw_temp_c: float | None = None  # sensor reading before simulated defrost warming
        self.fridge_hacked: bool = False
        self.hacked_at: float | None = None
        self.tamper_raised: bool = False  # mismatch alarm already raised since last reset
        self.knob_steps: int = 0  # clockwise detents accumulated in the current gesture
        self.knob_last_ts: float = 0.0
        self.ack_message_until: float = 0.0
        self.power_out: bool = False  # mains power lost until reset
        self.defrosting: bool = False  # allowed unfreeze of an empty fridge, until reset

    # ----- state -------------------------------------------------------
    @property
    def stocked(self) -> bool:
        return any(m.get("quantity", 0) > 0 for m in self.inventory)

    def stocked_items(self) -> list[dict]:
        return [m for m in self.inventory if m.get("quantity", 0) > 0]

    def doors_open(self) -> bool:
        return self.clock() < self.doors_open_until

    def ack_message_active(self) -> bool:
        return self.clock() < self.ack_message_until

    def alarm_acknowledged(self) -> bool:
        return bool(self.alarm and self.alarm.get("acknowledged_at"))

    def defrost_warming_c(self) -> float:
        """Simulated interior warming of a hacked (defrosting) fridge."""
        if not self.fridge_hacked or self.hacked_at is None:
            return 0.0
        elapsed = max(0.0, self.clock() - self.hacked_at)
        return min(DEFROST_WARMING_MAX_C, DEFROST_WARMING_C_PER_S * elapsed)

    def update_reading(self, temp_c: float, humidity: float) -> None:
        self.raw_temp_c = round(float(temp_c), 2)
        self.temp_c = round(self.raw_temp_c + self.defrost_warming_c(), 2)
        self.humidity = round(float(humidity), 1)
        self.temp_ts = self.clock()
        # Drawn per reading (not per API call) so the fridge screen stays steady
        # between sensor readings.
        noise = self.rng.gauss(0.0, FRIDGE_SENSOR_NOISE_C)
        self.fridge_offset_c = max(
            -FRIDGE_SENSOR_MAX_DEV_C, min(FRIDGE_SENSOR_MAX_DEV_C, FRIDGE_SENSOR_OFFSET_C + noise)
        )

    def inventory_summary(self) -> dict:
        items = self.stocked_items()
        return {
            "stocked": bool(items),
            "items": len(items),
            "units": sum(m["quantity"] for m in items),
        }

    def _log(self, kind: str, message: str) -> None:
        self.events.appendleft({"ts": self.clock(), "kind": kind, "message": message})

    # ----- simulated smart fridge -------------------------------------
    def fridge_state(self) -> dict:
        """Data the smart fridge reports over its (simulated) cloud API."""
        if self.fridge_hacked:
            # Attacker put the controller into defrost but keeps the screen "healthy".
            display = FAKE_DISPLAY_TEMP_C
        elif self.temp_c is not None:
            display = round(self.temp_c + self.fridge_offset_c, 1)
        else:
            display = FRIDGE_SETPOINT_C
        return {
            "online": True,
            "model": FRIDGE_MODEL,
            "mode": "defrost" if self.fridge_hacked else "normal",
            "setpoint_c": FRIDGE_SETPOINT_C,
            "display_temp_c": display,
            "door_open": self.doors_open(),
            "compressor_on": not self.fridge_hacked,
            "defrost_active": self.fridge_hacked,
            "power_w": FRIDGE_POWER_DEFROST_W if self.fridge_hacked else FRIDGE_POWER_NORMAL_W,
            "error_code": None,
        }

    def fridge_mismatch_c(self) -> float | None:
        """Fridge screen minus Arduino sensor; None without a sensor reading."""
        if self.temp_c is None:
            return None
        return round(self.fridge_state()["display_temp_c"] - self.temp_c, 2)

    def check_fridge_tamper(self) -> Outcome | None:
        """Compare the fridge's reported temperature with the Arduino sensor.

        Returns an Outcome the first time the mismatch is seen (until reset).
        """
        mismatch = self.fridge_mismatch_c()
        if mismatch is None or abs(mismatch) <= TAMPER_TOLERANCE_C or not self.stocked:
            return None
        if self.tamper_raised:
            return None
        self.tamper_raised = True

        fridge = self.fridge_state()
        msg = (
            f"Fridge data mismatch: fridge screen shows {fridge['display_temp_c']:.1f} C, "
            f"Arduino sensor measures {self.temp_c:.1f} C (diff {abs(mismatch):.1f} C). "
            "Possible hacked fridge: trust the sensor, follow runbook H1."
        )
        self._log("fridge_tamper", msg)
        if not self.alarm or self.alarm["kind"] != "power_outage":
            self.alarm = {
                "kind": "fridge_tamper",
                "severity": "critical",
                "title": f"FRIDGE DATA MISMATCH - code {HACK_TEXT}",
                "message": msg,
                "protocol": HACK_TEXT,
                "protocol_title": HACK_TITLE,
                "display_text": HACK_TEXT,
                "started_at": self.clock(),
                "deadline": None,
            }
        payload = {
            "sensor_temp_c": self.temp_c,
            "fridge_display_temp_c": fridge["display_temp_c"],
            "mismatch_c": mismatch,
            "fridge_mode": fridge["mode"],
            "fridge_power_w": fridge["power_w"],
            "stocked_items": [m["id"] for m in self.stocked_items()],
            "code": HACK_TEXT,
        }
        return Outcome(
            "fridge_tamper",
            msg,
            pattern=PATTERN_URGENT,
            display=self.idle_display(),
            stubs=[("report_fridge_tamper", payload)],
        )

    def camera_frame(self) -> str:
        """Which simulated camera still matches the current state.

        A hacked fridge looks normal on camera too: its screen shows a healthy
        temperature, only the Arduino sensor reveals the problem.
        """
        kind = self.alarm["kind"] if self.alarm else None
        if self.power_out or kind == "power_outage":
            scene = CAMERA_POWER_OUTAGE
        elif self.doors_open():
            scene = CAMERA_DOOR_OPEN
        elif kind == "unfreeze" or self.defrosting:
            scene = CAMERA_HEATING
        else:
            scene = CAMERA_NORMAL
        return f"fridge_{scene}" if self.stocked else f"fridge_empty_{scene}"

    def snapshot(self) -> dict:
        now = self.clock()
        frame = self.camera_frame()
        alarm = None
        if self.alarm:
            alarm = dict(self.alarm)
            if alarm.get("deadline"):
                alarm["seconds_left"] = max(0, int(alarm["deadline"] - now))
        return {
            "now": now,
            "temp_c": self.temp_c,
            "humidity": self.humidity,
            "temp_age_s": None if self.temp_ts is None else round(now - self.temp_ts, 1),
            "inventory": self.inventory_summary(),
            "alarm": alarm,
            "doors_open": self.doors_open(),
            "doors_seconds_left": max(0, int(self.doors_open_until - now)),
            "fridge": self.fridge_state(),
            "fridge_mismatch_c": self.fridge_mismatch_c(),
            "camera": {"frame": frame, "url": f"/camera/{frame}.jpg", "simulated": True},
            "main_site": self.main_site,
            "events": list(self.events),
        }

    def idle_display(self) -> tuple[str, str]:
        """What the matrix shows when no temporary message is running."""
        if self.alarm:
            if self.alarm.get("acknowledged_at"):
                return ("text", f"ACK {self.alarm['display_text']}")
            return ("alarm", self.alarm["display_text"])
        return ("temp", "")

    # ----- Modulino Knob -----------------------------------------------
    def knob_turn(self, steps: int) -> Outcome | None:
        """Operator turned the knob; positive steps are clockwise detents.

        KNOB_ACK_STEPS clockwise detents within KNOB_WINDOW_S acknowledge the
        active alarm and/or the doors warning. Counter-clockwise resets the count.
        """
        now = self.clock()
        if steps <= 0 or now - self.knob_last_ts > KNOB_WINDOW_S:
            self.knob_steps = 0
        self.knob_last_ts = now
        if steps <= 0:
            return None
        self.knob_steps += steps
        if self.knob_steps < KNOB_ACK_STEPS:
            return None
        self.knob_steps = 0
        # Ignore turning while "ALARM ACK" / "DONE" is still on the matrix, so one
        # long turn cannot acknowledge and resolve in a single gesture.
        if self.ack_message_active():
            return None

        pending_alarm = self.alarm is not None and not self.alarm.get("acknowledged_at")
        doors = self.doors_open()
        if not pending_alarm and not doors:
            if self.alarm is not None:  # already acknowledged: protocol followed
                return self._resolve_by_knob()
            return None

        acknowledged = []
        if pending_alarm:
            self.alarm["acknowledged_at"] = now
            self.alarm["acknowledged_by"] = "knob"
            acknowledged.append(self.alarm["title"])
        if doors:
            self.doors_open_until = 0.0
            acknowledged.append("doors left open")
        self.ack_message_until = now + ACK_MESSAGE_SECONDS
        msg = f"Acknowledged at the fridge (knob): {', '.join(acknowledged)}"
        self._log("alarm_ack", msg)
        payload = {
            "alarm_kind": self.alarm["kind"] if self.alarm else None,
            "code": self.alarm.get("protocol") if self.alarm else None,
            "doors": doors,
            "acknowledged_by": "knob",
        }
        return Outcome(
            "knob_ack",
            msg,
            pattern=PATTERN_ACK,
            display=("text", ACK_TEXT),
            stubs=[("report_alarm_ack", payload)],
        )

    # ----- commands ----------------------------------------------------
    def handle(self, command: str) -> Outcome:
        handler = getattr(self, f"_cmd_{command}", None)
        if command not in COMMANDS or handler is None:
            raise ValueError(f"unknown command: {command}")
        return handler()

    def _cmd_unfreeze(self) -> Outcome:
        if not self.stocked:
            self.defrosting = True
            msg = "Unfreeze allowed: the fridge is empty"
            self._log("unfreeze_allowed", msg)
            return Outcome("unfreeze", msg, stubs=[("report_unfreeze_allowed", {})])

        items = self.stocked_items()
        msg = f"Suspicious unfreeze blocked: {len(items)} medicines in the fridge. Operator must check."
        self._log("unfreeze_blocked", msg)
        if not self.alarm or self.alarm["kind"] != "power_outage":
            self.alarm = {
                "kind": "unfreeze",
                "severity": "warning",
                "title": "Suspicious unfreeze command",
                "message": msg,
                "protocol": None,
                "display_text": UNFREEZE_TEXT,
                "started_at": self.clock(),
                "deadline": None,
            }
        payload = {"stocked_items": [m["id"] for m in items], "units": sum(m["quantity"] for m in items)}
        return Outcome(
            "unfreeze",
            msg,
            pattern=PATTERN_UNFREEZE,
            display=self.idle_display(),
            stubs=[("notify_operator_unfreeze_check", payload)],
        )

    def assess_power_outage(self) -> dict | None:
        """Safe window, reachable clinics and protocol; None when the fridge is empty."""
        items = self.stocked_items()
        if not items:
            return None
        limiting = min(items, key=lambda m: m["max_excursion_minutes"])
        window = int(limiting["max_excursion_minutes"])
        clinics = []
        for c in self.clinics:
            total = c["drive_minutes"] + HANDLING_MINUTES
            clinics.append({**c, "minutes_needed": total, "reachable": total <= window})
        reachable = [c for c in clinics if c["reachable"]]
        protocol = select_protocol(window, reachable)
        return {
            "window_minutes": window,
            "limiting_medicine": {"id": limiting["id"], "name": limiting["name"]},
            "protocol": protocol,
            "protocol_title": PROTOCOL_TITLES[protocol],
            "clinics": clinics,
            "reachable_count": len(reachable),
        }

    def _cmd_power_outage(self) -> Outcome:
        self.power_out = True
        assessment = self.assess_power_outage()
        if assessment is None:
            msg = "Power outage with an empty fridge: nothing to do"
            self._log("power_outage_empty", msg)
            return Outcome("power_outage", msg)

        now = self.clock()
        protocol = assessment["protocol"]
        msg = (
            f"Power outage: follow protocol {protocol}. Stock is safe for {assessment['window_minutes']} min "
            f"(limited by {assessment['limiting_medicine']['name']}); "
            f"{assessment['reachable_count']} clinics reachable in time."
        )
        self._log("power_outage", msg)
        self.alarm = {
            "kind": "power_outage",
            "severity": "critical",
            "title": f"POWER OUTAGE - protocol {protocol}",
            "message": msg,
            "display_text": protocol,
            "started_at": now,
            "deadline": now + assessment["window_minutes"] * 60,
            **assessment,
        }
        payload = {
            "protocol": protocol,
            "window_minutes": assessment["window_minutes"],
            "limiting_medicine": assessment["limiting_medicine"]["id"],
            "reachable_clinics": [
                {"id": c["id"], "name": c["name"], "phone": c.get("phone"), "drive_minutes": c["drive_minutes"]}
                for c in assessment["clinics"]
                if c["reachable"]
            ],
            "inventory": [{"id": m["id"], "quantity": m["quantity"]} for m in self.stocked_items()],
        }
        return Outcome(
            "power_outage",
            msg,
            pattern=PATTERN_URGENT,
            display=("alarm", protocol),
            stubs=[("report_power_outage", payload)],
        )

    def _cmd_doors_open(self) -> Outcome:
        self.doors_open_until = self.clock() + DOORS_ALARM_SECONDS
        msg = f"Doors left open: '{DOORS_TEXT}' for {DOORS_ALARM_SECONDS} s"
        self._log("doors_open", msg)
        return Outcome(
            "doors_open",
            msg,
            pattern=PATTERN_DOORS,
            display=("text", DOORS_TEXT),
            stubs=[("report_doors_open", {"duration_s": DOORS_ALARM_SECONDS, "stocked": self.stocked})],
        )

    def _cmd_hack_fridge(self) -> Outcome:
        """Simulate the 2026 fridge attacks: defrost while the screen reports a normal temperature.

        No beep here: the siren starts when check_fridge_tamper() sees the sensors disagree.
        The interior then warms up (see defrost_warming_c), so the mismatch grows reading by reading.
        """
        if not self.fridge_hacked:
            self.hacked_at = self.clock()
        self.fridge_hacked = True
        msg = "Simulated attack: fridge controller set to defrost, its screen is frozen at a healthy temperature"
        self._log("hack_fridge", msg)
        return Outcome("hack_fridge", msg)

    def _cmd_empty(self) -> Outcome:
        self.inventory = []
        msg = "Fridge emptied"
        self._log("inventory", msg)
        return Outcome("empty", msg, stubs=[("sync_inventory", {"inventory": []})])

    def _cmd_fill(self) -> Outcome:
        self.inventory = copy.deepcopy(self._catalogue)
        msg = f"Fridge filled with {len(self.inventory)} medicines"
        self._log("inventory", msg)
        payload = {"inventory": [{"id": m["id"], "quantity": m["quantity"]} for m in self.inventory]}
        return Outcome("fill", msg, stubs=[("sync_inventory", payload)])

    def _resolve_by_knob(self) -> Outcome:
        """Second clockwise turn after the acknowledgement: protocol followed, clear the alarm.

        For a power outage the protocol moves the stock to other clinics, so the
        fridge ends up empty (and stays dark until the power is back / reset).
        """
        alarm = self.alarm
        now = self.clock()
        self._clear_alarms()
        self.ack_message_until = now + ACK_MESSAGE_SECONDS
        msg = f"Protocol followed, alarm resolved at the fridge (knob): {alarm['title']}"
        stubs: list[tuple[str, dict[str, Any]]] = []
        if alarm["kind"] == "power_outage" and self.stocked:
            moved = [{"id": m["id"], "quantity": m["quantity"]} for m in self.stocked_items()]
            self.inventory = []
            msg += f". Stock moved to other clinics: {len(moved)} medicines, fridge is now empty"
            stubs.append(("sync_inventory", {"inventory": [], "transferred": moved}))
        self._log("alarm_resolved", msg)
        payload = {
            "alarm_kind": alarm["kind"],
            "code": alarm.get("protocol"),
            "acknowledged_at": alarm.get("acknowledged_at"),
            "resolved_by": "knob",
        }
        return Outcome(
            "knob_resolve",
            msg,
            pattern=PATTERN_ACK,
            display=("text", RESOLVED_TEXT),
            stubs=[("report_alarm_resolved", payload), *stubs],
        )

    def _clear_alarms(self) -> None:
        self.alarm = None
        self.doors_open_until = 0.0
        self.fridge_hacked = False
        self.hacked_at = None
        self.tamper_raised = False
        self.knob_steps = 0
        self.ack_message_until = 0.0

    def _cmd_reset(self) -> Outcome:
        """Operator clears everything; any active alarm is reported as resolved."""
        alarm = self.alarm
        doors = self.doors_open()
        self._clear_alarms()
        self.power_out = False
        self.defrosting = False
        msg = "Alarms cleared by operator"
        self._log("reset", msg)
        stubs: list[tuple[str, dict[str, Any]]] = []
        if alarm is not None or doors:
            stubs.append((
                "report_alarm_resolved",
                {
                    "alarm_kind": alarm["kind"] if alarm else None,
                    "code": alarm.get("protocol") if alarm else None,
                    "acknowledged_at": alarm.get("acknowledged_at") if alarm else None,
                    "doors": doors,
                    "resolved_by": "reset",
                },
            ))
        return Outcome("reset", msg, pattern=PATTERN_STOP, display=("temp", ""), stubs=stubs)
