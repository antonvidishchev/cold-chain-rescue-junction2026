from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api.ws import hub
from app.db import get_session
from app.domain import planner
from app.domain.thresholds import Range
from app.models import StockItem, StorageLocation, TransferPlan
from app.monitoring import stock_with_products, used_units

router = APIRouter(prefix="/api/transfers", tags=["transfers"])


@router.get("")
def list_plans(session: Session = Depends(get_session)) -> list[TransferPlan]:
    return list(session.exec(select(TransferPlan).order_by(TransferPlan.created_at.desc())).all())


class ProposeIn(BaseModel):
    source_location_id: str


@router.post("/propose")
async def propose(body: ProposeIn, session: Session = Depends(get_session)) -> TransferPlan:
    source = session.get(StorageLocation, body.source_location_id)
    if source is None:
        raise HTTPException(404, "Unknown source location")

    items = [
        planner.Item(s.id, p.id, p.name, Range(p.min_c, p.max_c), s.quantity, s.units)
        for s, p in stock_with_products(session, source.id)
    ]
    targets = [
        planner.Target(
            loc.id, loc.name, loc.kind, Range(loc.min_c, loc.max_c),
            loc.capacity_units - used_units(session, loc.id), loc.power_on,
        )
        for loc in session.exec(select(StorageLocation).where(StorageLocation.id != source.id)).all()
    ]
    result = planner.propose(items, targets)
    plan = TransferPlan(
        source_location_id=source.id,
        moves=result.moves,
        unplaced=result.unplaced,
        rationale="Deterministic plan: powered targets whose range fits each product's storage range, "
        "with enough free capacity; on-site backup preferred over partner sites.",
    )
    session.add(plan)
    session.commit()
    session.refresh(plan)
    await hub.broadcast({"type": "transfer", "data": plan.model_dump(mode="json")})
    return plan


class ApproveIn(BaseModel):
    by: str


@router.post("/{plan_id}/approve")
async def approve(plan_id: int, body: ApproveIn, session: Session = Depends(get_session)) -> TransferPlan:
    """Human approval. Records the approver and updates the inventory to reflect the move."""
    plan = session.get(TransferPlan, plan_id)
    if plan is None:
        raise HTTPException(404, "Plan not found")
    if plan.status != "proposed":
        raise HTTPException(409, f"Plan is already {plan.status}")
    for move in plan.moves:
        item = session.get(StockItem, move["stock_id"])
        if item is not None:
            item.location_id = move["target_location_id"]
            session.add(item)
    plan.status = "approved"
    plan.approved_by = body.by
    plan.approved_at = datetime.now(timezone.utc)
    session.add(plan)
    session.commit()
    session.refresh(plan)
    await hub.broadcast({"type": "transfer", "data": plan.model_dump(mode="json")})
    return plan
