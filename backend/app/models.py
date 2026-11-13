"""Database models."""

from datetime import datetime, timezone

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Product(SQLModel, table=True):
    """A medicine/reagent with its storage instructions (these govern thresholds)."""

    id: str = Field(primary_key=True)
    name: str
    min_c: float
    max_c: float
    max_excursion_minutes: int = 0
    notes: str = ""


class StorageLocation(SQLModel, table=True):
    id: str = Field(primary_key=True)
    name: str
    kind: str = "fridge"  # fridge | backup_fridge | partner_site
    address: str = ""
    min_c: float = 2.0
    max_c: float = 8.0
    capacity_units: int
    monitored: bool = False
    # live/simulated state
    power_on: bool = True
    reported_temp_c: float | None = None  # what the (smart) fridge claims about itself
    camera_stock_present: bool | None = None  # simulated camera; None = derive from inventory
    alarm_state: str = "NORMAL"
    out_of_range_since: datetime | None = None
    last_temp_c: float | None = None


class StockItem(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    product_id: str = Field(foreign_key="product.id")
    location_id: str = Field(foreign_key="storagelocation.id")
    quantity: int
    units: int  # capacity units occupied


class Device(SQLModel, table=True):
    id: str = Field(primary_key=True)
    location_id: str = Field(foreign_key="storagelocation.id")
    last_seen: datetime | None = None
    last_seq: int = 0
    silenced: bool = False


class Reading(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    device_id: str = Field(index=True)
    location_id: str = Field(index=True)
    ts: datetime
    temp_c: float
    alarm_active: bool = False


class Alert(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    location_id: str = Field(index=True)
    type: str  # EXCURSION | POWER_LOSS | TAMPER
    message: str
    created_at: datetime = Field(default_factory=utcnow)
    status: str = "open"  # open | acknowledged | resolved
    acknowledged_by: str | None = None
    acknowledged_at: datetime | None = None


class DeviceCommand(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    device_id: str = Field(index=True)
    command: str  # silence | unsilence | test_alarm
    created_at: datetime = Field(default_factory=utcnow)
    delivered: bool = False


class TransferPlan(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    source_location_id: str
    status: str = "proposed"  # proposed | approved | rejected
    created_at: datetime = Field(default_factory=utcnow)
    approved_by: str | None = None
    approved_at: datetime | None = None
    moves: list[dict] = Field(default_factory=list, sa_column=Column(JSON))
    unplaced: list[dict] = Field(default_factory=list, sa_column=Column(JSON))
    rationale: str = ""
