from datetime import datetime, timedelta, timezone

from app.domain.alarm_state import AlarmState, evaluate
from app.domain.thresholds import Range

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)
GRACE = timedelta(seconds=30)


def run(temp, since=None, stock=True, power=True):
    return evaluate(temp_c=temp, now=NOW, allowed=Range(2, 8), stock_present=stock,
                    power_on=power, out_of_range_since=since, grace=GRACE)


def test_in_range_is_normal():
    assert run(5).state == AlarmState.NORMAL


def test_first_out_of_range_is_warning():
    r = run(10)
    assert r.state == AlarmState.WARNING and r.out_of_range_since == NOW


def test_after_grace_with_stock_is_excursion():
    assert run(10, since=NOW - timedelta(seconds=31)).state == AlarmState.EXCURSION


def test_empty_fridge_never_escalates():
    assert run(10, since=NOW - timedelta(hours=1), stock=False).state == AlarmState.WARNING


def test_power_loss_with_stock():
    assert run(5, power=False).state == AlarmState.POWER_LOSS
