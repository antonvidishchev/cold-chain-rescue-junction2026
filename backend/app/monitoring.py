"""Glue between the database and the domain rules.

``evaluate_location`` is called whenever something relevant changes (new
reading, power toggle, fridge self-report, camera) and returns the events to
push to dashboards.
"""

from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from app.config import settings
from app.domain.alarm_state import AlarmState, evaluate
from app.domain.tamper import is_tampered
from app.domain.thresholds import Range, effective_range
from app.models import Alert, Device, Product, StockItem, StorageLocation


def as_utc(dt: datetime | None) -> datetime | None:
    """SQLite drops tzinfo; treat stored datetimes as UTC."""
    if dt is None or dt.tzinfo is not None:
        return dt
    return dt.replace(tzinfo=timezone.utc)


def stock_with_products(session: Session, location_id: str) -> list[tuple[StockItem, Product]]:
    rows = session.exec(
        select(StockItem, Product).where(StockItem.location_id == location_id).where(StockItem.product_id == Product.id)
    )
    return list(rows.all())


def used_units(session: Session, location_id: str) -> int:
    return sum(s.units for s, _ in stock_with_products(session, location_id))


def stock_present(session: Session, loc: StorageLocation) -> bool:
    if loc.camera_stock_present is not None:
        return loc.camera_stock_present
    return bool(stock_with_products(session, loc.id))


def allowed_range(session: Session, loc: StorageLocation) -> Range | None:
    """Product instructions govern thresholds; fall back to the fridge's own range if it holds nothing."""
    products = [Range(p.min_c, p.max_c) for _, p in stock_with_products(session, loc.id)]
    return effective_range(products) if products else None


def raise_alert(session: Session, location_id: str, type_: str, message: str) -> Alert | None:
    """Create an alert unless one of the same type is already open/acknowledged for this location."""
    existing = session.exec(
        select(Alert)
        .where(Alert.location_id == location_id)
        .where(Alert.type == type_)
        .where(Alert.status != "resolved")
    ).first()
    if existing:
        return None
    alert = Alert(location_id=location_id, type=type_, message=message)
    session.add(alert)
    return alert


def evaluate_location(session: Session, loc: StorageLocation, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    events: list[dict] = []
    if loc.last_temp_c is None:
        return events

    allowed = allowed_range(session, loc)
    present = stock_present(session, loc)
    result = evaluate(
        temp_c=loc.last_temp_c,
        now=now,
        allowed=allowed,
        stock_present=present,
        power_on=loc.power_on,
        out_of_range_since=as_utc(loc.out_of_range_since),
        grace=timedelta(seconds=settings.default_grace_seconds),
    )
    previous = loc.alarm_state
    loc.alarm_state = result.state
    loc.out_of_range_since = result.out_of_range_since

    new_alerts: list[Alert] = []
    if result.state == AlarmState.EXCURSION:
        a = raise_alert(
            session, loc.id, "EXCURSION",
            f"{loc.name}: {loc.last_temp_c:.1f} C outside {allowed.min_c}-{allowed.max_c} C with stock inside",
        )
        new_alerts.append(a)
    if result.state == AlarmState.POWER_LOSS:
        a = raise_alert(session, loc.id, "POWER_LOSS", f"{loc.name}: power lost while holding stock")
        new_alerts.append(a)
    if is_tampered(loc.last_temp_c, loc.reported_temp_c, settings.tamper_tolerance_c):
        a = raise_alert(
            session, loc.id, "TAMPER",
            f"{loc.name}: fridge reports {loc.reported_temp_c:.1f} C, watchdog measures {loc.last_temp_c:.1f} C",
        )
        new_alerts.append(a)

    if result.state == AlarmState.NORMAL:
        for device in session.exec(select(Device).where(Device.location_id == loc.id)):
            device.silenced = False  # re-arm the buzzer for the next excursion

    session.add(loc)
    session.commit()

    for a in new_alerts:
        if a is not None:
            session.refresh(a)
            events.append({"type": "alert", "data": a.model_dump(mode="json")})
    if previous != loc.alarm_state:
        events.append({"type": "state", "data": {"location_id": loc.id, "alarm_state": loc.alarm_state}})
    return events
