import json
import random
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
    return Watchdog(*data, clock=clock, rng=random.Random(42))


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


def test_reset_reports_active_alarm_resolved(wd, clock):
    wd.handle("power_outage")
    turn(wd, clock, KNOB_ACK_STEPS)
    out = wd.handle("reset")
    assert out.stubs == [("report_alarm_resolved", {
        "alarm_kind": "power_outage", "code": "P1", "acknowledged_at": clock.t,
        "doors": False, "resolved_by": "reset",
    })]


def test_reset_reports_doors_only(wd):
    wd.handle("doors_open")
    (name, payload), = wd.handle("reset").stubs
    assert name == "report_alarm_resolved"
    assert payload["alarm_kind"] is None and payload["doors"] is True


def test_reset_without_alarm_reports_nothing(wd):
    assert wd.handle("reset").stubs == []


def test_unknown_command(wd):
    with pytest.raises(ValueError):
        wd.handle("self_destruct")


# ----- simulated smart fridge / hacked fridge ---------------------------
def test_healthy_fridge_mirrors_sensor(wd):
    wd.update_reading(5.0, 40.0)
    fridge = wd.fridge_state()
    assert fridge["mode"] == "normal" and fridge["compressor_on"] and not fridge["defrost_active"]
    assert 4.0 <= fridge["display_temp_c"] <= 6.0
    assert wd.check_fridge_tamper() is None
    assert wd.alarm is None


@pytest.mark.parametrize("offset, shown", [(-0.5, 4.0), (-0.4, 4.5), (0.0, 4.5), (0.4, 4.5), (0.5, 5.0)])
def test_fridge_screen_snaps_to_4_5_in_demo_band(wd, offset, shown):
    wd.update_reading(4.5, 40.0)
    wd.fridge_offset_c = offset
    assert wd.fridge_state()["display_temp_c"] == pytest.approx(shown)


def test_hacked_fridge_screen_is_not_snapped(wd):
    wd.handle("hack_fridge")
    assert wd.fridge_state()["display_temp_c"] == 4.0


def test_healthy_fridge_usually_reads_a_little_lower(wd):
    diffs = []
    for _ in range(500):
        wd.update_reading(5.0, 40.0)
        diffs.append(wd.fridge_state()["display_temp_c"] - 5.0)
        assert wd.fridge_state() == wd.fridge_state()  # steady between readings
    lower = sum(d < 0 for d in diffs) / len(diffs)
    assert 0.8 <= lower < 1.0  # mostly colder, occasionally not
    assert -0.5 < sum(diffs) / len(diffs) < -0.1
    assert max(abs(d) for d in diffs) <= 1.05
    assert wd.check_fridge_tamper() is None


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


def test_hack_warms_fridge_and_raises_h1_at_demo_temperature(wd):
    wd.update_reading(2.0, 40.0)  # board offset to fridge level for the demo
    wd.handle("hack_fridge")
    assert wd.check_fridge_tamper() is None  # screen 4.0 vs sensor 2.0: not yet
    wd.clock.t += 10
    wd.update_reading(2.0, 40.0)
    assert wd.temp_c == pytest.approx(12.0) and wd.raw_temp_c == pytest.approx(2.0)
    assert wd.fridge_state()["display_temp_c"] == 4.0
    out = wd.check_fridge_tamper()
    assert out is not None and out.display == ("alarm", "H1")
    wd.clock.t += 1000
    wd.update_reading(2.0, 40.0)
    assert wd.temp_c == pytest.approx(12.0)  # warming is capped
    wd.handle("reset")
    wd.update_reading(2.0, 40.0)
    assert wd.temp_c == pytest.approx(2.0)


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


def test_knob_ignored_while_ack_message_shows(wd, clock):
    wd.handle("power_outage")
    assert turn(wd, clock, KNOB_ACK_STEPS) is not None
    assert turn(wd, clock, KNOB_ACK_STEPS) is None  # one long turn: no instant resolve
    assert wd.alarm_acknowledged()


def test_second_knob_turn_resolves_alarm(wd, clock):
    wd.handle("power_outage")
    turn(wd, clock, KNOB_ACK_STEPS)
    clock.t += 6
    out = turn(wd, clock, KNOB_ACK_STEPS)
    assert out is not None and out.command == "knob_resolve"
    assert out.pattern == PATTERN_ACK and out.display == ("text", "DONE")
    assert [s for s, _ in out.stubs] == ["report_alarm_resolved", "sync_inventory"]
    assert wd.alarm is None and wd.idle_display() == ("temp", "")
    assert wd.events[0]["kind"] == "alarm_resolved"
    clock.t += 6
    assert not wd.ack_message_active()
    assert turn(wd, clock, KNOB_ACK_STEPS) is None  # nothing left to do


def test_resolving_h1_restores_healthy_fridge(wd, clock):
    wd.update_reading(4.5, 40)
    wd.handle("hack_fridge")
    wd.update_reading(12.0, 40)
    wd.check_fridge_tamper()
    turn(wd, clock, KNOB_ACK_STEPS)
    clock.t += 6
    turn(wd, clock, KNOB_ACK_STEPS)
    assert wd.alarm is None and not wd.fridge_hacked
    assert wd.check_fridge_tamper() is None


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


# ----- simulated camera -----------------------------------------------------
def frame(wd):
    return wd.snapshot()["camera"]["frame"]


def test_camera_normal_by_default(wd):
    cam = wd.snapshot()["camera"]
    assert cam == {"frame": "fridge_normal", "url": "/camera/fridge_normal.jpg", "simulated": True}


def test_camera_door_open_for_the_doors_warning(wd, clock):
    wd.handle("doors_open")
    assert frame(wd) == "fridge_door_open"
    clock.t += DOORS_ALARM_SECONDS + 1
    assert frame(wd) == "fridge_normal"


def test_camera_power_outage_outranks_doors(wd):
    wd.handle("doors_open")
    wd.handle("power_outage")
    assert frame(wd) == "fridge_power_outage"


def test_camera_power_outage_with_empty_fridge(wd):
    wd.handle("empty")
    wd.handle("power_outage")
    assert wd.alarm is None
    assert frame(wd) == "fridge_empty_power_outage"
    wd.handle("reset")
    assert frame(wd) == "fridge_empty_normal"


def test_camera_heating_for_unfreeze_alarm(wd):
    wd.handle("unfreeze")
    assert frame(wd) == "fridge_heating"


def test_camera_hacked_fridge_looks_normal(wd):
    wd.update_reading(12.0, 40)
    wd.handle("hack_fridge")
    assert wd.check_fridge_tamper() is not None
    assert frame(wd) == "fridge_normal"


def test_camera_keeps_alarm_frame_until_resolved(wd, clock):
    wd.handle("power_outage")
    turn(wd, clock, KNOB_ACK_STEPS)
    assert wd.alarm_acknowledged()
    assert frame(wd) == "fridge_power_outage"
    clock.t += 6
    turn(wd, clock, KNOB_ACK_STEPS)
    assert wd.alarm is None
    assert frame(wd) == "fridge_empty_power_outage"  # stock moved, power still out


def test_camera_reset_returns_to_normal(wd):
    wd.handle("unfreeze")
    wd.handle("reset")
    assert frame(wd) == "fridge_normal"


def test_camera_follows_empty_and_fill(wd):
    wd.handle("empty")
    assert frame(wd) == "fridge_empty_normal"
    wd.handle("doors_open")
    assert frame(wd) == "fridge_empty_door_open"
    wd.handle("fill")
    assert frame(wd) == "fridge_door_open"


def test_camera_empty_fridge_defrosts_after_allowed_unfreeze(wd):
    wd.handle("empty")
    wd.handle("unfreeze")
    assert wd.alarm is None
    assert frame(wd) == "fridge_empty_heating"
    wd.handle("reset")
    assert frame(wd) == "fridge_empty_normal"


def test_resolving_power_outage_moves_stock_out(wd, clock):
    wd.handle("power_outage")
    turn(wd, clock, KNOB_ACK_STEPS)
    assert wd.stocked  # acknowledging alone keeps the stock
    clock.t += 6
    out = turn(wd, clock, KNOB_ACK_STEPS)
    assert out.command == "knob_resolve"
    assert not wd.stocked and wd.inventory_summary()["units"] == 0
    stubs = dict(out.stubs)
    assert stubs["sync_inventory"]["inventory"] == []
    assert len(stubs["sync_inventory"]["transferred"]) == 16
    assert "moved to other clinics" in wd.events[0]["message"]
    wd.handle("reset")
    assert frame(wd) == "fridge_empty_normal"
    wd.handle("fill")
    assert frame(wd) == "fridge_normal"


def test_resolving_other_alarms_keeps_stock(wd, clock):
    wd.handle("unfreeze")
    turn(wd, clock, KNOB_ACK_STEPS)
    clock.t += 6
    out = turn(wd, clock, KNOB_ACK_STEPS)
    assert out.command == "knob_resolve"
    assert wd.stocked
    assert [s for s, _ in out.stubs] == ["report_alarm_resolved"]
