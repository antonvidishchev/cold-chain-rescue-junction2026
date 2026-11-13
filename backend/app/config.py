"""Runtime settings, read from environment variables."""

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    db_url: str = os.environ.get("COLDCHAIN_DB_URL", "sqlite:///./coldchain.db")
    cors_origins: list[str] = field(
        default_factory=lambda: os.environ.get("COLDCHAIN_CORS_ORIGINS", "http://localhost:5173").split(",")
    )
    tamper_tolerance_c: float = float(os.environ.get("COLDCHAIN_TAMPER_TOLERANCE_C", "2.0"))
    default_grace_seconds: int = int(os.environ.get("COLDCHAIN_GRACE_SECONDS", "30"))
    seed_dir: Path = Path(__file__).resolve().parent.parent / "seed"


settings = Settings()
