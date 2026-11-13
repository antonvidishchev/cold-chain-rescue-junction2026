"""Alarm state machine for a monitored location."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from app.domain.thresholds import Range


class AlarmState(StrEnum):
    NORMAL = "NORMAL"
    WARNING = "WARNING"
    EXCURSION = "EXCURSION"
    POWER_LOSS = "POWER_LOSS"


@dataclass(frozen=True)
class Evaluation:
    state: AlarmState
    out_of_range_since: datetime | None


def evaluate(
    *,
    temp_c: float,
    now: datetime,
    allowed: Range | None,
    stock_present: bool,
    power_on: bool,
    out_of_range_since: datetime | None,
    grace: timedelta,
) -> Evaluation:
    """Compute the next state. TAMPER is evaluated separately (see tamper.py)."""
    in_range = allowed is None or allowed.contains(temp_c)
    since = None if in_range else (out_of_range_since or now)

    if not power_on and stock_present:
        return Evaluation(AlarmState.POWER_LOSS, since)

    if in_range:
        return Evaluation(AlarmState.NORMAL, None)

    if stock_present and now - since >= grace:
        return Evaluation(AlarmState.EXCURSION, since)
    return Evaluation(AlarmState.WARNING, since)
