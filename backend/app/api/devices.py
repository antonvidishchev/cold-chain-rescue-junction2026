from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.config import settings
from app.db import get_session
from app.models import Device, DeviceCommand, StorageLocation
from app.monitoring import allowed_range, stock_present

router = APIRouter(prefix="/api/devices", tags=["devices"])

COMMANDS = {"silence", "unsilence", "test_alarm"}


def _device(session: Session, device_id: str) -> Device:
    device = session.get(Device, device_id)
    if device is None:
        raise HTTPException(404, f"Unknown device {device_id}")
    return device


@router.get("")
def list_devices(session: Session = Depends(get_session)) -> list[Device]:
    return list(session.exec(select(Device)).all())


@router.get("/{device_id}/config")
def get_config(device_id: str, session: Session = Depends(get_session)) -> dict:
    """Config the watchdog caches locally so its alarm rule works offline."""
    device = _device(session, device_id)
    loc = session.get(StorageLocation, device.location_id)
    rng = allowed_range(session, loc)
    return {
        "device_id": device.id,
        "location_id": loc.id,
        "min_c": rng.min_c if rng else loc.min_c,
        "max_c": rng.max_c if rng else loc.max_c,
        "grace_seconds": settings.default_grace_seconds,
        "stock_present": stock_present(session, loc),
        "silenced": device.silenced,
    }


@router.get("/{device_id}/commands")
def pop_commands(device_id: str, session: Session = Depends(get_session)) -> list[dict]:
    """Return pending commands and mark them delivered (the device polls this)."""
    _device(session, device_id)
    pending = session.exec(
        select(DeviceCommand).where(DeviceCommand.device_id == device_id).where(DeviceCommand.delivered == False)  # noqa: E712
    ).all()
    for cmd in pending:
        cmd.delivered = True
        session.add(cmd)
    session.commit()
    return [{"id": c.id, "command": c.command} for c in pending]


class CommandIn(BaseModel):
    command: str


@router.post("/{device_id}/commands")
def queue_command(device_id: str, body: CommandIn, session: Session = Depends(get_session)) -> dict:
    _device(session, device_id)
    if body.command not in COMMANDS:
        raise HTTPException(400, f"Unknown command; expected one of {sorted(COMMANDS)}")
    cmd = DeviceCommand(device_id=device_id, command=body.command)
    session.add(cmd)
    session.commit()
    session.refresh(cmd)
    return {"id": cmd.id, "command": cmd.command}
