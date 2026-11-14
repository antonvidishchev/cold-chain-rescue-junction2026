import json
import sys
from pathlib import Path

import pytest

PY_DIR = Path(__file__).resolve().parents[1] / "python"
sys.path.insert(0, str(PY_DIR))

from logic import (  # noqa: E402
    DOORS_ALARM_SECONDS,
    HANDLING_MINUTES,
    KNOB_ACK_STEPS,
    KNOB_WINDOW_S,
    PATTERN_ACK,
    PATTERN_DOORS,
    PATTERN_STOP,
    PATTERN_UNFREEZE,
    PATTERN_URGENT,
    Watchdog,
    select_protocol,
)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def data():
    medicines = json.loads((PY_DIR / "data" / "medicines.json").read_text())
    clinics = json.loads((PY_DIR / "data" / "clinics.json").read_text())
    return medicines, clinics


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def wd(data, clock):
    return Watchdog(*data, clock=clock)


def test_data_files_are_complete(data):
    medicines, clinics = data
    assert len(clinics["clinics"]) == 10
    assert "Vanha Jorvaksentie 3" in clinics["main"]["address"]
    for m in medicines:
        assert m["storage_min_c"] < m["storage_max_c"]
        assert m["max_excursion_minutes"] > 0 and m["quantity"] > 0


def test_unfreeze_allowed_when_empty(wd):
    wd.handle("empty")
    out = wd.handle("unfreeze")
    assert out.pattern is None
    assert wd.alarm is None
    assert [s for s, _ in out.stubs] == ["report_unfreeze_allowed"]


def test_unfreeze_blocked_when_stocked(wd):
    out = wd.handle("unfreeze")
    assert out.pattern == PATTERN_UNFREEZE
    assert wd.alarm["kind"] == "unfreeze"
    assert out.display == ("alarm", "CHECK")
    assert [s for s, _ in out.stubs] == ["notify_operator_unfreeze_check"]


def test_power_outage_empty_does_nothing(wd):
    wd.handle("empty")
    out = wd.handle("power_outage")
    assert out.pattern is None and out.display is None and out.stubs == []
    assert wd.alarm is None


def test_power_outage_stocked_picks_protocol_and_clinics(wd, clock):
    out = wd.handle("power_outage")
    alarm = wd.alarm
    window = min(m["max_excursion_minutes"] for m in wd.inventory)
    assert out.pattern == PATTERN_URGENT
    assert alarm["window_minutes"] == window
    assert alarm["deadline"] == clock.t + window * 60
    assert out.display == ("alarm", alarm["protocol"])
    for c in alarm["clinics"]:
        assert c["reachable"] == (c["drive_minutes"] + HANDLING_MINUTES <= window)
    drive = [c["drive_minutes"] for c in alarm["clinics"]]
    assert drive == sorted(drive)
    assert out.stubs[0][0] == "report_power_outage"
    clock.t += 90
    assert wd.snapshot()["alarm"]["seconds_left"] == window * 60 - 90


def test_power_outage_overrides_unfreeze_alarm(wd):
    wd.handle("unfreeze")
    wd.handle("power_outage")
    wd.handle("unfreeze")
    assert wd.alarm["kind"] == "power_outage"


@pytest.mark.parametrize(
    "window,reachable,expected",
    [(60, [1], "P1"), (61, [1], "P2"), (240, [1], "P2"), (241, [1], "P3"), (500, [], "P4"), (30, [], "P4")],
)
def test_select_protocol(window, reachable, expected):
    assert select_protocol(window, reachable) == expected


def test_window_follows_inventory(wd):
    wd.inventory = [m for m in wd.inventory if m["id"].startswith("insulin")]
    assert wd.assess_power_outage()["protocol"] == "P3"


def test_doors_open_lasts_15_seconds(wd, clock):
    out = wd.handle("doors_open")
    assert out.pattern == PATTERN_DOORS
    assert out.display == ("text", "CLOSE THE DOORS")
    assert wd.doors_open()
    clock.t += DOORS_ALARM_SECONDS
    assert not wd.doors_open()


def test_empty_and_fill(wd):
    n = len(wd.inventory)
    wd.handle("empty")
    assert not wd.stocked and wd.inventory_summary()["items"] == 0
    out = wd.handle("fill")
    assert wd.stocked and len(wd.inventory) == n
    assert out.stubs[0][0] == "sync_inventory"


def test_reset_clears_alarm(wd):
    wd.handle("power_outage")
    out = wd.handle("reset")
    assert wd.alarm is None and out.pattern == PATTERN_STOP and out.display == ("temp", "")


def test_unknown_command(wd):
    with pytest.raises(ValueError):
        wd.handle("self_destruct")


# ----- simulated smart fridge / hacked fridge ---------------------------
def test_healthy_fridge_mirrors_sensor(wd):
    wd.update_reading(5.0, 40.0)
    fridge = wd.fridge_state()
    assert fridge["mode"] == "normal" and fridge["compressor_on"] and not fridge["defrost_active"]
    assert fridge["display_temp_c"] == pytest.approx(5.3)
    assert wd.check_fridge_tamper() is None
    assert wd.alarm is None


def test_hacked_fridge_raises_h1_alarm_once(wd):
    wd.update_reading(22.0, 40.0)
    wd.handle("hack_fridge")
    assert wd.fridge_state()["display_temp_c"] == 4.0
    assert wd.fridge_state()["defrost_active"] and not wd.fridge_state()["compressor_on"]
    out = wd.check_fridge_tamper()
    assert out is not None
    assert out.pattern == PATTERN_URGENT
    assert out.display == ("alarm", "H1")
    assert [name for name, _ in out.stubs] == ["report_fridge_tamper"]
    assert wd.alarm["kind"] == "fridge_tamper" and wd.alarm["protocol"] == "H1"
    assert wd.check_fridge_tamper() is None  # raised only once
    assert wd.snapshot()["fridge_mismatch_c"] == pytest.approx(-18.0)


def test_small_mismatch_is_tolerated(wd):
    wd.update_reading(5.0, 40.0)
    wd.handle("hack_fridge")  # screen shows 4.0, sensor 5.0: within tolerance
    assert wd.check_fridge_tamper() is None


def test_no_tamper_alarm_without_sensor_or_stock(wd):
    wd.handle("hack_fridge")
    assert wd.check_fridge_tamper() is None  # no sensor reading yet
    wd.update_reading(22.0, 40.0)
    wd.handle("empty")
    assert wd.check_fridge_tamper() is None


def test_hack_does_not_overwrite_power_outage_alarm(wd):
    wd.update_reading(22.0, 40.0)
    wd.handle("power_outage")
    wd.handle("hack_fridge")
    out = wd.check_fridge_tamper()
    assert out is not None and out.pattern == PATTERN_URGENT
    assert wd.alarm["kind"] == "power_outage"


def test_reset_clears_hack(wd):
    wd.update_reading(22.0, 40.0)
    wd.handle("hack_fridge")
    wd.check_fridge_tamper()
    wd.handle("reset")
    assert wd.alarm is None and not wd.fridge_hacked
    assert wd.check_fridge_tamper() is None
    wd.handle("hack_fridge")
    assert wd.check_fridge_tamper() is not None  # armed again


# ----- Modulino Knob acknowledgement --------------------------------------
def turn(wd, clock, clicks, dt=0.1):
    out = None
    for _ in range(clicks):
        clock.t += dt
        out = wd.knob_turn(1) or out
    return out


def test_knob_acknowledges_power_outage(wd, clock):
    wd.handle("power_outage")
    protocol = wd.alarm["protocol"]
    out = turn(wd, clock, KNOB_ACK_STEPS)
    assert out is not None and out.command == "knob_ack"
    assert out.pattern == PATTERN_ACK
    assert out.display == ("text", "ALARM ACK")
    assert [s for s, _ in out.stubs] == ["report_alarm_ack"]
    alarm = wd.snapshot()["alarm"]
    assert alarm["acknowledged_at"] == clock.t and alarm["acknowledged_by"] == "knob"
    assert alarm["protocol"] == protocol and alarm["seconds_left"] > 0  # alarm stays visible
    assert wd.idle_display() == ("text", f"ACK {protocol}")
    assert wd.ack_message_active()
    clock.t += 5
    assert not wd.ack_message_active()
    assert wd.events[0]["kind"] == "alarm_ack"


def test_knob_needs_enough_clicks(wd, clock):
    wd.handle("power_outage")
    assert turn(wd, clock, KNOB_ACK_STEPS - 1) is None
    assert not wd.alarm_acknowledged()


def test_knob_clicks_must_be_within_window(wd, clock):
    wd.handle("power_outage")
    assert turn(wd, clock, KNOB_ACK_STEPS, dt=KNOB_WINDOW_S + 0.5) is None
    assert not wd.alarm_acknowledged()


def test_knob_counter_clockwise_resets_count(wd, clock):
    wd.handle("power_outage")
    turn(wd, clock, KNOB_ACK_STEPS - 1)
    assert wd.knob_turn(-1) is None
    assert turn(wd, clock, KNOB_ACK_STEPS - 1) is None
    assert turn(wd, clock, 1) is not None


def test_knob_multi_step_delta(wd, clock):
    wd.handle("unfreeze")
    assert wd.knob_turn(KNOB_ACK_STEPS) is not None
    assert wd.idle_display() == ("text", "ACK CHECK")


def test_knob_without_alarm_does_nothing(wd, clock):
    assert turn(wd, clock, KNOB_ACK_STEPS * 2) is None
    assert all(e["kind"] != "alarm_ack" for e in wd.events)


def test_knob_second_ack_is_noop(wd, clock):
    wd.handle("power_outage")
    assert turn(wd, clock, KNOB_ACK_STEPS) is not None
    assert turn(wd, clock, KNOB_ACK_STEPS) is None


def test_knob_acknowledges_doors_warning(wd, clock):
    wd.handle("doors_open")
    out = turn(wd, clock, KNOB_ACK_STEPS)
    assert out is not None and out.stubs[0][1]["doors"] is True
    assert not wd.doors_open()
    assert wd.alarm is None and wd.idle_display() == ("temp", "")


def test_knob_acknowledges_h1(wd, clock):
    wd.update_reading(4.5, 40)
    wd.handle("hack_fridge")
    wd.update_reading(12.0, 40)
    assert wd.check_fridge_tamper() is not None
    assert turn(wd, clock, KNOB_ACK_STEPS) is not None
    assert wd.idle_display() == ("text", "ACK H1")


def test_new_alarm_after_ack_is_unacknowledged(wd, clock):
    wd.handle("unfreeze")
    turn(wd, clock, KNOB_ACK_STEPS)
    wd.handle("power_outage")
    assert not wd.alarm_acknowledged()
    assert wd.idle_display()[0] == "alarm"


def test_reset_after_ack(wd, clock):
    wd.handle("power_outage")
    turn(wd, clock, KNOB_ACK_STEPS)
    wd.handle("reset")
    assert wd.alarm is None and not wd.ack_message_active() and wd.knob_steps == 0
