from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.db import get_session
from app.models import Device, Product, StorageLocation
from app.monitoring import allowed_range, stock_present, stock_with_products

router = APIRouter(prefix="/api", tags=["inventory"])


@router.get("/products")
def list_products(session: Session = Depends(get_session)) -> list[Product]:
    return list(session.exec(select(Product)).all())


@router.get("/inventory")
def get_inventory(session: Session = Depends(get_session)) -> list[dict]:
    """Every storage location with its stock, capacity, effective range and live state."""
    result = []
    for loc in session.exec(select(StorageLocation)).all():
        rows = stock_with_products(session, loc.id)
        used = sum(s.units for s, _ in rows)
        rng = allowed_range(session, loc)
        devices = session.exec(select(Device).where(Device.location_id == loc.id)).all()
        result.append(
            {
                **loc.model_dump(mode="json"),
                "used_units": used,
                "free_units": loc.capacity_units - used,
                "stock_present": stock_present(session, loc),
                "effective_range": {"min_c": rng.min_c, "max_c": rng.max_c} if rng else None,
                "devices": [d.model_dump(mode="json") for d in devices],
                "stock": [
                    {**s.model_dump(mode="json"), "product": p.model_dump(mode="json")} for s, p in rows
                ],
            }
        )
    return result
