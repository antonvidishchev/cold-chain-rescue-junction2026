"""Engine, session dependency and demo seeding."""

import json
from collections.abc import Iterator

from sqlmodel import Session, SQLModel, create_engine, select

from app.config import settings
from app.models import Device, Product, StockItem, StorageLocation

engine = create_engine(
    settings.db_url,
    connect_args={"check_same_thread": False} if settings.db_url.startswith("sqlite") else {},
)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session


def init_db(seed: bool = True) -> None:
    SQLModel.metadata.create_all(engine)
    if seed:
        with Session(engine) as session:
            seed_demo_data(session)


def seed_demo_data(session: Session) -> None:
    """Load seed/*.json once (no-op if products already exist)."""
    if session.exec(select(Product)).first():
        return
    load = lambda name: json.loads((settings.seed_dir / name).read_text())  # noqa: E731
    for p in load("products.json"):
        session.add(Product(**p))
    for loc in load("locations.json"):
        session.add(StorageLocation(**loc))
    session.flush()
    for s in load("stock.json"):
        session.add(StockItem(**s))
    for d in load("devices.json"):
        session.add(Device(**d))
    session.commit()
