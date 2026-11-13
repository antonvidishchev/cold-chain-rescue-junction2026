from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api.ws import hub
from app.db import get_session
from app.models import Alert, Device, DeviceCommand

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get("")
def list_alerts(status: str | None = None, session: Session = Depends(get_session)) -> list[Alert]:
    query = select(Alert).order_by(Alert.created_at.desc())
    if status:
        query = query.where(Alert.status == status)
    return list(session.exec(query).all())


class AckIn(BaseModel):
    by: str


@router.post("/{alert_id}/ack")
async def acknowledge(alert_id: int, body: AckIn, session: Session = Depends(get_session)) -> Alert:
    """Someone takes ownership: record who, and silence the buzzer at that location."""
    alert = session.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(404, "Alert not found")
    alert.status = "acknowledged"
    alert.acknowledged_by = body.by
    alert.acknowledged_at = datetime.now(timezone.utc)
    session.add(alert)
    for device in session.exec(select(Device).where(Device.location_id == alert.location_id)):
        device.silenced = True
        session.add(device)
        session.add(DeviceCommand(device_id=device.id, command="silence"))
    session.commit()
    session.refresh(alert)
    await hub.broadcast({"type": "alert", "data": alert.model_dump(mode="json")})
    return alert


@router.post("/{alert_id}/resolve")
async def resolve(alert_id: int, session: Session = Depends(get_session)) -> Alert:
    alert = session.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(404, "Alert not found")
    alert.status = "resolved"
    session.add(alert)
    session.commit()
    session.refresh(alert)
    await hub.broadcast({"type": "alert", "data": alert.model_dump(mode="json")})
    return alert
