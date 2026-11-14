"""Public-demo Web Push API and outbox dispatcher.

Include ``router`` in the cloud app and call ``process_notifications(store)`` from
its timer. POST accepts endpoint, keys, optional clinic_ids and removal_token;
DELETE /subscriptions/{id} requires ``Authorization: Bearer <removal_token>``.
Only the initial POST returns that token. No route returns stored subscriptions.

Configuration: VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY, VAPID_SUBJECT,
PUSH_ALLOWED_HOSTS (comma-separated exact hosts or dot-prefixed suffixes),
PUSH_MAX_SUBSCRIPTIONS (default 100), PUSH_MAX_ATTEMPTS (1..5, default 5).
Delivery receipts prevent repeats to successful recipients. As with any external
side effect, a process crash after sending but before saving a receipt can cause
redelivery; clients should deduplicate by notification id.
"""

import base64
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import threading
import time
from typing import Annotated, Callable
from urllib.parse import urlsplit

from fastapi import APIRouter, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

router = APIRouter(prefix="/api/push", tags=["push"])
SUBSCRIPTIONS = "PushSubscriptions"
SLOTS = "PushSubscriptionSlots"
DELIVERIES = "PushDeliveries"
NOTIFICATIONS = "Notifications"
_DEFAULT_HOSTS = (
    "fcm.googleapis.com", "updates.push.services.mozilla.com",
    ".push.services.mozilla.com", "web.push.apple.com", ".notify.windows.com",
)
_LOCK = threading.RLock()
_PROCESS_LOCK = threading.RLock()


def get_store():
    from .store import get_store as load_store

    return load_store()


def _store(request: Request):
    store = getattr(request.app.state, "store", None)
    return store if store is not None else get_store()


def _limit(name: str, default: int, maximum: int) -> int:
    try:
        return max(1, min(int(os.getenv(name, str(default))), maximum))
    except ValueError:
        return default


def validate_endpoint(endpoint: str) -> str:
    """Validate again at send time, including records stored under an old policy."""
    if len(endpoint) > 4096 or any(ord(c) <= 32 or ord(c) >= 127 for c in endpoint) or "\\" in endpoint:
        raise ValueError("Invalid push endpoint")
    try:
        parsed = urlsplit(endpoint)
        host = parsed.hostname or ""
        if (parsed.scheme != "https" or parsed.username is not None
                or parsed.password is not None or parsed.port not in (None, 443)
                or parsed.fragment or not re.fullmatch(r"[a-z0-9]+(?:[.-][a-z0-9]+)*", host)):
            raise ValueError("Invalid push endpoint")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError("IP push endpoints are forbidden")
        if host == "localhost" or host.endswith(".localhost") or "." not in host:
            raise ValueError("Invalid push host")
        configured = os.getenv("PUSH_ALLOWED_HOSTS")
        allowed = configured.split(",") if configured is not None else _DEFAULT_HOSTS
        if not any(
            host == entry or (entry.startswith(".") and host.endswith(entry) and host != entry[1:])
            for entry in (item.strip().lower() for item in allowed) if entry
        ):
            raise ValueError("Push host is not allowed")
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Invalid or disallowed push endpoint") from exc
    return endpoint


def _key(value: str, size: int) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("Push keys must be unpadded base64url")
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except ValueError as exc:
        raise ValueError("Invalid push key") from exc
    if (len(raw) != size or base64.urlsafe_b64encode(raw).decode().rstrip("=") != value
            or (size == 65 and raw[0] != 4)):
        raise ValueError("Invalid push key length or encoding")
    return value


class PushKeys(BaseModel):
    model_config = ConfigDict(extra="forbid")
    p256dh: str = Field(min_length=87, max_length=87)
    auth: str = Field(min_length=22, max_length=22)

    @field_validator("p256dh")
    @classmethod
    def public_key(cls, value: str) -> str:
        return _key(value, 65)

    @field_validator("auth")
    @classmethod
    def auth_key(cls, value: str) -> str:
        return _key(value, 16)


class Subscription(BaseModel):
    model_config = ConfigDict(extra="forbid")
    endpoint: str = Field(min_length=1, max_length=4096)
    keys: PushKeys
    clinic_ids: list[Annotated[str, Field(min_length=1, max_length=128)]] = Field(default_factory=list, max_length=100)
    removal_token: str | None = Field(default=None, min_length=32, max_length=256)

    @field_validator("endpoint")
    @classmethod
    def endpoint_policy(cls, value: str) -> str:
        return validate_endpoint(value)

    @field_validator("clinic_ids")
    @classmethod
    def normalize_clinics(cls, value: list[str]) -> list[str]:
        return sorted(set(value))


def _authorized(record: dict, token: str | None) -> bool:
    expected = record.get("removal_token_hash", "")
    return bool(token and expected and hmac.compare_digest(
        expected, hashlib.sha256(token.encode()).hexdigest(),
    ))


@router.get("/public-key")
def public_key(response: Response):
    value = os.getenv("VAPID_PUBLIC_KEY", "").strip()
    if not value:
        raise HTTPException(503, "Push notifications are not configured")
    response.headers["Cache-Control"] = "no-store"
    return {"public_key": value}


@router.post("/subscriptions")
def subscribe(body: Subscription, request: Request, response: Response):
    store = _store(request)
    subscription_id = hashlib.sha256(body.endpoint.encode()).hexdigest()
    value = {"endpoint": body.endpoint, "keys": body.keys.model_dump(), "clinic_ids": body.clinic_ids}
    response.headers["Cache-Control"] = "no-store"
    with _LOCK:
        existing = store.get(SUBSCRIPTIONS, subscription_id)
        if existing is not None:
            changed = any(existing.get(key) != item for key, item in value.items())
            if changed and not _authorized(existing, body.removal_token):
                raise HTTPException(403, "Removal token required to change subscription")
            if changed:
                existing.update(value)
                store.put(SUBSCRIPTIONS, subscription_id, existing)
            return {"id": subscription_id}
        maximum = _limit("PUSH_MAX_SUBSCRIPTIONS", 100, 10000)
        if len(store.list(SUBSCRIPTIONS)) >= maximum:
            raise HTTPException(429, "Subscription capacity reached")
        # Atomic slots enforce the bound even across independent API workers.
        slot = next((str(i) for i in range(maximum) if store.create(
            SLOTS, str(i), {"id": str(i), "subscription_id": subscription_id},
        )), None)
        if slot is None:
            raise HTTPException(429, "Subscription capacity reached")
        token = secrets.token_urlsafe(32)
        value.update(id=subscription_id, slot=slot, removal_token_hash=hashlib.sha256(token.encode()).hexdigest())
        if not store.create(SUBSCRIPTIONS, subscription_id, value):
            store.delete(SLOTS, slot)
            raise HTTPException(409, "Subscription already exists; retry registration")
        response.status_code = 201
        return {"id": subscription_id, "removal_token": token}


@router.delete("/subscriptions/{subscription_id}", status_code=204)
def unsubscribe(subscription_id: str, request: Request, authorization: Annotated[str | None, Header()] = None):
    token = authorization[7:] if authorization and authorization.startswith("Bearer ") else None
    if not token or len(token) > 256:
        raise HTTPException(403, "Valid removal token required")
    store = _store(request)
    with _LOCK:
        record = store.get(SUBSCRIPTIONS, subscription_id)
        if record is None or not _authorized(record, token):
            raise HTTPException(403, "Valid removal token required")
        _remove_subscription(store, subscription_id, record)
    return Response(status_code=204)


def _remove_subscription(store, subscription_id: str, record: dict):
    store.delete(SUBSCRIPTIONS, subscription_id)
    if "slot" in record:
        store.delete(SLOTS, record["slot"])


class PushSendError(Exception):
    def __init__(self, status_code: int | None = None):
        super().__init__("Push delivery failed")
        self.status_code = status_code


def _configured_sender() -> Callable | None:
    private_key = os.getenv("VAPID_PRIVATE_KEY", "").strip()
    subject = os.getenv("VAPID_SUBJECT", "").strip()
    if not private_key or not subject:
        return None
    from pywebpush import webpush
    from requests import Session

    class SafeSession(Session):
        def __init__(self):
            super().__init__()
            self.trust_env = False

        def request(self, method, url, **kwargs):
            validate_endpoint(url)
            kwargs["allow_redirects"] = False
            kwargs["timeout"] = 5
            return super().request(method, url, **kwargs)

    def send(subscription: dict, payload: dict):
        with SafeSession() as session:
            result = webpush(
                subscription_info={"endpoint": subscription["endpoint"], "keys": subscription["keys"]},
                data=json.dumps(payload, separators=(",", ":")),
                vapid_private_key=private_key, vapid_claims={"sub": subject},
                requests_session=session, timeout=5, ttl=300,
            )
            status = getattr(result, "status_code", None)
            if status is None or not 200 <= status < 300:
                raise PushSendError(status)
            return result

    return send


def _status(exc: Exception) -> int | None:
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None) if response is not None else getattr(exc, "status_code", None)
    return status if isinstance(status, int) else None


def process_notifications(store=None, sender: Callable | None = None) -> dict[str, int]:
    """Dispatch pending Notifications; injected sender receives (subscription, payload).

    Receipts are claimed before delivery using the store's optimistic put. A
    short lease permits recovery after interrupted workers. Error messages and
    response bodies are never persisted or returned.
    """
    counts = {"sent": 0, "failed": 0, "expired": 0}
    sender = sender if sender is not None else _configured_sender()
    if sender is None:
        return counts
    store = store if store is not None else get_store()
    maximum = _limit("PUSH_MAX_ATTEMPTS", 5, 5)
    with _PROCESS_LOCK:
        for listed in store.list(NOTIFICATIONS):
            notification_id = str(listed["id"])
            notice = store.get(NOTIFICATIONS, notification_id)
            if notice is None or notice.get("status") != "pending":
                continue
            if "push_recipient_ids" not in notice:
                notice["push_recipient_ids"] = [
                    sub["id"] for sub in store.list(SUBSCRIPTIONS)
                    if not sub.get("clinic_ids") or notice.get("location_id") in sub["clinic_ids"]
                ]
                store.put(NOTIFICATIONS, notification_id, notice)
                notice = store.get(NOTIFICATIONS, notification_id)
            payload = {key: notice.get(key) for key in ("id", "alert_id", "location_id", "type", "created_at")}
            payload["message"] = str(notice.get("message", ""))[:300]
            states = []
            for subscription_id in notice["push_recipient_ids"]:
                receipt_id = hashlib.sha256(f"{notification_id}:{subscription_id}".encode()).hexdigest()
                store.create(DELIVERIES, receipt_id, {
                    "id": receipt_id, "notification_id": notification_id,
                    "subscription_id": subscription_id, "status": "pending", "attempts": 0,
                })
                receipt = store.get(DELIVERIES, receipt_id)
                if receipt["status"] in ("sent", "expired", "failed"):
                    states.append(receipt["status"])
                    continue
                if receipt.get("lease_until", 0) > time.time():
                    states.append("pending")
                    continue
                if receipt["attempts"] >= maximum:
                    receipt.update(status="failed", error="retry_limit")
                    store.put(DELIVERIES, receipt_id, receipt)
                    states.append("failed")
                    continue
                subscription = store.get(SUBSCRIPTIONS, subscription_id)
                if subscription is None:
                    receipt.update(status="expired")
                    store.put(DELIVERIES, receipt_id, receipt)
                    states.append("expired")
                    continue
                receipt.update(attempts=receipt["attempts"] + 1, lease_until=time.time() + 60)
                store.put(DELIVERIES, receipt_id, receipt)
                receipt = store.get(DELIVERIES, receipt_id)
                try:
                    validate_endpoint(subscription["endpoint"])
                    result = sender(subscription, payload)
                    status = getattr(result, "status_code", None)
                    if status is not None and not 200 <= status < 300:
                        raise PushSendError(status)
                except Exception as exc:
                    if _status(exc) in (404, 410):
                        _remove_subscription(store, subscription_id, subscription)
                        receipt.update(status="expired", error="subscription_expired")
                        counts["expired"] += 1
                    else:
                        receipt.update(status="failed" if receipt["attempts"] >= maximum else "pending", error="delivery_failed")
                        counts["failed"] += 1
                else:
                    receipt.update(status="sent")
                    receipt.pop("error", None)
                    counts["sent"] += 1
                receipt["lease_until"] = 0
                store.put(DELIVERIES, receipt_id, receipt)
                states.append(receipt["status"])
            if "pending" not in states:
                notice["status"] = "failed" if "failed" in states else "sent"
                store.put(NOTIFICATIONS, notification_id, notice)
    return counts
