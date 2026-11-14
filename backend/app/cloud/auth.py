"""App-level authentication: anonymous Functions routing does not validate keys."""

import secrets

from fastapi import HTTPException, Request

from app.cloud.settings import Settings


def _matches(actual: str | None, expected: str) -> bool:
    return bool(actual and expected) and secrets.compare_digest(actual.encode(), expected.encode())


def require_operator(request: Request) -> None:
    if not _matches(request.headers.get("x-functions-key"), Settings.load().operator_key):
        raise HTTPException(401, "Valid operator key required")


def require_device(request: Request, device_id: str) -> None:
    settings = Settings.load()
    if not _matches(request.headers.get("x-functions-key"), settings.device_function_key):
        raise HTTPException(401, "Valid device function key required")
    if not _matches(request.headers.get("x-device-key"), settings.device_keys.get(device_id, "")):
        raise HTTPException(401, "Valid scoped device key required")
