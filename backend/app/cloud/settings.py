"""Environment-only cloud configuration; never reads legacy SQLite settings."""

import json
import math
import os
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class Settings:
    operator_key: str
    device_function_key: str
    device_keys: dict[str, str]
    min_c: float = 2.0
    max_c: float = 8.0
    rise_c: float = 2.0
    rise_window_seconds: int = 300
    offline_seconds: int = 90
    consecutive_readings: int = 2
    image_max_bytes: int = 5 * 1024 * 1024
    image_max_pixels: int = 12_000_000
    command_ttl_seconds: int = 300

    @classmethod
    def load(cls) -> "Settings":
        keys = json.loads(os.getenv("COLDCHAIN_DEVICE_KEYS", "{}"))
        if not isinstance(keys, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in keys.items()):
            raise ValueError("COLDCHAIN_DEVICE_KEYS must be a JSON object of device IDs to strings")
        result = cls(
            operator_key=os.getenv("COLDCHAIN_OPERATOR_KEY", ""),
            device_function_key=os.getenv("COLDCHAIN_DEVICE_FUNCTION_KEY", ""),
            device_keys=keys,
            min_c=float(os.getenv("COLDCHAIN_MIN_C", "2")),
            max_c=float(os.getenv("COLDCHAIN_MAX_C", "8")),
            rise_c=float(os.getenv("COLDCHAIN_RISE_C", "2")),
            rise_window_seconds=int(os.getenv("COLDCHAIN_RISE_WINDOW_SECONDS", "300")),
            offline_seconds=int(os.getenv("COLDCHAIN_OFFLINE_SECONDS", "90")),
            consecutive_readings=int(os.getenv("COLDCHAIN_CONSECUTIVE_READINGS", "2")),
            image_max_bytes=int(os.getenv("COLDCHAIN_IMAGE_MAX_BYTES", str(5 * 1024 * 1024))),
            image_max_pixels=int(os.getenv("COLDCHAIN_IMAGE_MAX_PIXELS", "12000000")),
            command_ttl_seconds=int(os.getenv("COLDCHAIN_COMMAND_TTL_SECONDS", "300")),
        )
        if not all(math.isfinite(n) for n in (result.min_c, result.max_c, result.rise_c)):
            raise ValueError("Thresholds must be finite")
        if result.min_c >= result.max_c or result.rise_c <= 0:
            raise ValueError("Invalid temperature thresholds")
        if min(result.rise_window_seconds, result.offline_seconds, result.consecutive_readings,
               result.image_max_bytes, result.image_max_pixels, result.command_ttl_seconds) <= 0:
            raise ValueError("Cloud limits must be positive")
        return result


def storage_connection_string() -> str | None:
    """Shared-key credentials are allowed only for an explicit local emulator."""
    connection = os.getenv("STORAGE_CONNECTION_STRING")
    if not connection:
        return None
    parts = dict(part.split("=", 1) for part in connection.split(";") if "=" in part)
    if parts.get("UseDevelopmentStorage", "").lower() == "true":
        proxy = parts.get("DevelopmentStorageProxyUri")
        if proxy and urlparse(proxy).hostname not in {"localhost", "127.0.0.1", "::1", "azurite"}:
            raise ValueError("Development storage proxy must be local")
        return connection
    endpoints = [v for k, v in parts.items() if k.endswith("Endpoint")]
    if not parts.get("TableEndpoint") or not endpoints or any(
        urlparse(endpoint).hostname not in {"localhost", "127.0.0.1", "::1", "azurite"}
        for endpoint in endpoints
    ):
        raise ValueError("STORAGE_CONNECTION_STRING is limited to local/Azurite endpoints; use managed identity")
    return connection
