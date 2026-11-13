"""ColdChain Rescue backend."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import alerts, devices, inventory, simulation, telemetry, transfers, ws
from app.config import settings
from app.db import init_db


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="ColdChain Rescue", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in (telemetry, devices, inventory, alerts, simulation, transfers, ws):
    app.include_router(module.router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}
