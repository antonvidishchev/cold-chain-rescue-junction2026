"""Simulator endpoints for the demo: things we cannot physically do at the hackathon."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from app.api.ws import hub
from app.db import get_session
from app.models import StorageLocation
from app.monitoring import evaluate_location

router = APIRouter(prefix="/api/sim", tags=["simulation"])


def _location(session: Session, location_id: str) -> StorageLocation:
    loc = session.get(StorageLocation, location_id)
    if loc is None:
        raise HTTPException(404, f"Unknown location {location_id}")
    return loc


async def _apply(session: Session, loc: StorageLocation) -> dict:
    session.add(loc)
    session.commit()
    events = evaluate_location(session, loc)
    events.append({"type": "location", "data": loc.model_dump(mode="json")})
    await hub.broadcast(*events)
    return loc.model_dump(mode="json")


class FridgeReportIn(BaseModel):
    location_id: str
    temp_c: float | None


@router.post("/fridge-report")
async def fridge_report(body: FridgeReportIn, session: Session = Depends(get_session)) -> dict:
    """What the smart fridge *claims* about itself (possibly a lie, if it was hacked)."""
    loc = _location(session, body.location_id)
    loc.reported_temp_c = body.temp_c
    return await _apply(session, loc)


class PowerIn(BaseModel):
    location_id: str
    on: bool


@router.post("/power")
async def power(body: PowerIn, session: Session = Depends(get_session)) -> dict:
    loc = _location(session, body.location_id)
    loc.power_on = body.on
    return await _apply(session, loc)


class CameraIn(BaseModel):
    location_id: str
    stock_present: bool | None  # None = derive from inventory


@router.post("/camera")
async def camera(body: CameraIn, session: Session = Depends(get_session)) -> dict:
    loc = _location(session, body.location_id)
    loc.camera_stock_present = body.stock_present
    return await _apply(session, loc)
