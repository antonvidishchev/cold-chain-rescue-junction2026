from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api.ws import hub
from app.db import get_session
from app.models import Device, Reading, StorageLocation
from app.monitoring import evaluate_location

router = APIRouter(prefix="/api", tags=["telemetry"])


class TelemetryIn(BaseModel):
    device_id: str
    ts: datetime | None = None
    temp_c: float
    seq: int = 0
    alarm_active: bool = False


@router.post("/telemetry")
async def post_telemetry(body: TelemetryIn, session: Session = Depends(get_session)) -> dict:
    device = session.get(Device, body.device_id)
    if device is None:
        raise HTTPException(404, f"Unknown device {body.device_id}")
    loc = session.get(StorageLocation, device.location_id)
    ts = body.ts or datetime.now(timezone.utc)

    reading = Reading(
        device_id=device.id, location_id=loc.id, ts=ts, temp_c=body.temp_c, alarm_active=body.alarm_active
    )
    device.last_seen = datetime.now(timezone.utc)
    device.last_seq = body.seq
    loc.last_temp_c = body.temp_c
    session.add_all([reading, device, loc])
    session.commit()
    session.refresh(reading)

    events = [{"type": "reading", "data": reading.model_dump(mode="json")}]
    events += evaluate_location(session, loc)
    await hub.broadcast(*events)
    return {"ok": True, "alarm_state": loc.alarm_state}


@router.get("/readings")
def get_readings(location_id: str, limit: int = 300, session: Session = Depends(get_session)) -> list[Reading]:
    rows = session.exec(
        select(Reading).where(Reading.location_id == location_id).order_by(Reading.ts.desc()).limit(limit)
    ).all()
    return list(reversed(rows))
