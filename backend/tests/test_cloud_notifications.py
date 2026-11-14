"""Web Push contract tests: all delivery is injected or mocked, never networked."""

import base64
import json
from collections import Counter
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.cloud import notifications as push
from app.cloud.store import MemoryStore


def encoded(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def subscription(suffix="one", clinics=None):
    return {
        "endpoint": f"https://fcm.googleapis.com/fcm/send/{suffix}",
        "keys": {"p256dh": encoded(b"\x04" + b"x" * 64), "auth": encoded(b"a" * 16)},
        "clinic_ids": clinics or [],
    }


@pytest.fixture
def setup(monkeypatch):
    for name in ("VAPID_PRIVATE_KEY", "VAPID_PUBLIC_KEY", "VAPID_SUBJECT", "PUSH_ALLOWED_HOSTS",
                 "PUSH_MAX_SUBSCRIPTIONS", "PUSH_MAX_ATTEMPTS"):
        monkeypatch.delenv(name, raising=False)
    store = MemoryStore()
    app = FastAPI()
    app.state.store = store
    app.include_router(push.router)
    with TestClient(app) as client:
        yield store, client


def register(client, suffix="one", clinics=None):
    result = client.post("/api/push/subscriptions", json=subscription(suffix, clinics))
    assert result.status_code == 201, result.text
    return result.json()


def notice(store, key="notice-1", location="clinic-a"):
    value = {"id": key, "alert_id": "alert-1", "location_id": location, "type": "EXCURSION",
             "message": "Temperature exceeded safe range", "created_at": "2026-11-14T10:00:00Z",
             "status": "pending", "private_metadata": "do not send"}
    assert store.create(push.NOTIFICATIONS, key, value)


def test_public_key_only_and_lazy_store(setup, monkeypatch):
    store, client = setup
    monkeypatch.setattr(push, "get_store", lambda: pytest.fail("public-key must not load storage"))
    assert client.get("/api/push/public-key").status_code == 503
    monkeypatch.setenv("VAPID_PUBLIC_KEY", "public-only")
    monkeypatch.setenv("VAPID_PRIVATE_KEY", "secret")
    result = client.get("/api/push/public-key")
    assert result.json() == {"public_key": "public-only"}
    assert result.headers["cache-control"] == "no-store"
    assert client.get("/api/push/subscriptions").status_code == 405
    client.app.state.store = None
    monkeypatch.setattr(push, "get_store", lambda: store)
    register(client)


def test_tokens_idempotency_filter_and_key_permissions(setup):
    store, client = setup
    created = register(client, clinics=["clinic-a"])
    assert set(created) == {"id", "removal_token"}
    saved = store.get(push.SUBSCRIPTIONS, created["id"])
    assert created["removal_token"] not in json.dumps(saved)
    assert saved["endpoint"] == subscription()["endpoint"]
    assert client.post("/api/push/subscriptions", json=subscription(clinics=["clinic-a"])).json() == {"id": created["id"]}
    updated = subscription(clinics=["clinic-b"])
    assert client.post("/api/push/subscriptions", json=updated).status_code == 403
    updated["removal_token"] = "z" * 43
    assert client.post("/api/push/subscriptions", json=updated).status_code == 403
    updated["removal_token"] = created["removal_token"]
    assert client.post("/api/push/subscriptions", json=updated).status_code == 200
    assert store.get(push.SUBSCRIPTIONS, created["id"])["clinic_ids"] == ["clinic-b"]
    updated.pop("removal_token")
    updated["keys"]["auth"] = encoded(b"b" * 16)
    assert client.post("/api/push/subscriptions", json=updated).status_code == 403
    path = f"/api/push/subscriptions/{created['id']}"
    for headers in ({}, {"Authorization": f"Bearer {created['id']}"}, {"Authorization": "Bearer wrong"}):
        assert client.delete(path, headers=headers).status_code == 403
    assert client.get(path).status_code == 405
    assert client.delete(path, headers={"Authorization": f"Bearer {created['removal_token']}"}).status_code == 204
    assert store.get(push.SUBSCRIPTIONS, created["id"]) is None
    assert store.list(push.SLOTS) == []


@pytest.mark.parametrize("endpoint", [
    "http://fcm.googleapis.com/send/a", "https://user@fcm.googleapis.com/send/a",
    "https://user:password@fcm.googleapis.com/send/a", "https://127.0.0.1/send/a",
    "https://[::1]/send/a", "https://localhost/send/a", "https://foo.localhost/send/a",
    "https://169.254.169.254/latest/meta-data", "https://fcm.googleapis.com:8443/send/a",
    "https://fcm.googleapis.com.evil.example/send/a", "https://evilnotify.windows.com/send/a",
    "https://notify.windows.com.evil.example/send/a", "https://example.com/send/a",
    "https://fcm.googleapis.com/send/a#fragment", "https://fcm.googleapis.com./send/a",
    "https://fcm.googleapis.com\\@localhost/send/a", "https://fcm.googleapis.com\n/send/a",
    "https://%66cm.googleapis.com/send/a", "https://fcm.googleapis.com:abc/send/a",
])
def test_ssrf_endpoint_rejection(setup, endpoint):
    store, client = setup
    body = subscription()
    body["endpoint"] = endpoint
    assert client.post("/api/push/subscriptions", json=body).status_code == 422
    assert store.list(push.SUBSCRIPTIONS) == []


@pytest.mark.parametrize("host", [
    "fcm.googleapis.com", "updates.push.services.mozilla.com", "updates-autopush.push.services.mozilla.com",
    "wns2-db5p.notify.windows.com", "web.push.apple.com", "fcm.googleapis.com:443",
])
def test_default_provider_allowlist(setup, host):
    _, client = setup
    body = subscription()
    body["endpoint"] = f"https://{host}/send/opaque-token"
    assert client.post("/api/push/subscriptions", json=body).status_code == 201


def test_allowlist_override(setup, monkeypatch):
    _, client = setup
    monkeypatch.setenv("PUSH_ALLOWED_HOSTS", "push.example.org,.push.example.net,localhost,127.0.0.1")
    for host, expected in [("push.example.org", 201), ("a.push.example.net", 201),
                           ("evilpush.example.net", 422), ("fcm.googleapis.com", 422),
                           ("localhost", 422), ("127.0.0.1", 422)]:
        body = subscription()
        body["endpoint"] = f"https://{host}/send/token"
        assert client.post("/api/push/subscriptions", json=body).status_code == expected


@pytest.mark.parametrize("field,value", [
    ("auth", encoded(b"a" * 15)), ("auth", encoded(b"a" * 17)), ("auth", "!" * 22),
    ("auth", encoded(b"a" * 16)[:-1] + "h"), ("auth", encoded(b"a" * 16) + "=="),
    ("p256dh", encoded(b"\x03" + b"x" * 64)), ("p256dh", encoded(b"x" * 64)),
    ("p256dh", "/" * 87),
])
def test_key_validation(setup, field, value):
    _, client = setup
    body = subscription()
    body["keys"][field] = value
    assert client.post("/api/push/subscriptions", json=body).status_code == 422


def test_capacity_and_slot_reuse(setup, monkeypatch):
    store, client = setup
    monkeypatch.setenv("PUSH_MAX_SUBSCRIPTIONS", "2")
    first = register(client)
    register(client, "two")
    assert client.post("/api/push/subscriptions", json=subscription("three")).status_code == 429
    assert client.post("/api/push/subscriptions", json=subscription()).status_code == 200
    client.delete(f"/api/push/subscriptions/{first['id']}", headers={"Authorization": f"Bearer {first['removal_token']}"})
    register(client, "three")
    assert len(store.list(push.SUBSCRIPTIONS)) == len(store.list(push.SLOTS)) == 2


def test_atomic_slots_enforce_capacity_when_listing_is_stale(setup, monkeypatch):
    store, client = setup
    monkeypatch.setenv("PUSH_MAX_SUBSCRIPTIONS", "1")
    register(client)
    original_list = store.list
    monkeypatch.setattr(store, "list", lambda kind: [] if kind == push.SUBSCRIPTIONS else original_list(kind))
    assert client.post("/api/push/subscriptions", json=subscription("two")).status_code == 429


def test_fanout_partial_failure_retries_without_duplicates(setup):
    store, client = setup
    first = register(client, "one", ["clinic-a"])
    second = register(client, "two")
    register(client, "three", ["clinic-b"])
    notice(store)
    calls = Counter()
    payloads = []

    def send(sub, payload):
        calls[sub["id"]] += 1
        payloads.append(payload)
        if sub["id"] == second["id"] and calls[sub["id"]] == 1:
            raise RuntimeError("secret endpoint and credentials must not be stored")

    assert push.process_notifications(store, send) == {"sent": 1, "failed": 1, "expired": 0}
    assert store.get(push.NOTIFICATIONS, "notice-1")["status"] == "pending"
    assert "secret" not in json.dumps(store.list(push.DELIVERIES))
    assert push.process_notifications(store, send) == {"sent": 1, "failed": 0, "expired": 0}
    assert push.process_notifications(store, send)["sent"] == 0
    assert calls == {first["id"]: 1, second["id"]: 2}
    assert store.get(push.NOTIFICATIONS, "notice-1")["status"] == "sent"
    assert set(payloads[0]) == {"id", "alert_id", "location_id", "type", "message", "created_at"}


@pytest.mark.parametrize("status", [404, 410])
def test_expired_subscription_removed_and_capacity_released(setup, status):
    store, client = setup
    created = register(client)
    notice(store)

    def send(sub, payload):
        error = RuntimeError("provider secret")
        error.response = SimpleNamespace(status_code=status)
        raise error

    assert push.process_notifications(store, send)["expired"] == 1
    assert store.get(push.SUBSCRIPTIONS, created["id"]) is None
    assert store.list(push.SLOTS) == []
    assert store.list(push.DELIVERIES)[0]["status"] == "expired"
    assert push.process_notifications(store, send)["expired"] == 0


def test_retry_limit_is_finite_and_successes_are_retained(setup, monkeypatch):
    store, client = setup
    monkeypatch.setenv("PUSH_MAX_ATTEMPTS", "999")
    register(client)
    notice(store)
    attempts = []

    def send(sub, payload):
        attempts.append(sub["id"])
        return SimpleNamespace(status_code=503)

    for _ in range(8):
        push.process_notifications(store, send)
    assert len(attempts) == 5
    assert store.get(push.NOTIFICATIONS, "notice-1")["status"] == "failed"
    assert store.list(push.DELIVERIES)[0]["attempts"] == 5


@pytest.mark.parametrize("missing", ["VAPID_PRIVATE_KEY", "VAPID_SUBJECT"])
def test_disabled_sender_leaves_pending_and_does_not_load_store(setup, monkeypatch, missing):
    store, _ = setup
    notice(store)
    monkeypatch.setenv("VAPID_PRIVATE_KEY", "private")
    monkeypatch.setenv("VAPID_SUBJECT", "mailto:operator@example.org")
    monkeypatch.delenv(missing)
    monkeypatch.setattr(push, "get_store", lambda: pytest.fail("disabled sender must not load storage"))
    assert push.process_notifications() == {"sent": 0, "failed": 0, "expired": 0}
    assert push.process_notifications(store)["sent"] == 0
    assert store.get(push.NOTIFICATIONS, "notice-1")["status"] == "pending"


def test_existing_subscription_revalidated_before_sending(setup, monkeypatch):
    store, client = setup
    register(client)
    notice(store)
    monkeypatch.setenv("PUSH_ALLOWED_HOSTS", "web.push.apple.com")
    calls = []
    assert push.process_notifications(store, lambda *args: calls.append(args))["failed"] == 1
    assert calls == []


def test_real_sender_wrapper_disables_proxy_redirects_and_bounds_timeout(setup, monkeypatch):
    import pywebpush
    import requests

    store, client = setup
    register(client)
    notice(store)
    monkeypatch.setenv("VAPID_PRIVATE_KEY", "private-secret")
    monkeypatch.setenv("VAPID_SUBJECT", "mailto:operator@example.org")
    observed = []

    def request(session, method, url, **kwargs):
        observed.append((session.trust_env, method, url, kwargs))
        return SimpleNamespace(status_code=302)

    def webpush(**kwargs):
        assert kwargs["vapid_private_key"] == "private-secret"
        assert kwargs["vapid_claims"] == {"sub": "mailto:operator@example.org"}
        assert set(kwargs["subscription_info"]) == {"endpoint", "keys"}
        assert "private" not in kwargs["data"]
        return kwargs["requests_session"].post(kwargs["subscription_info"]["endpoint"], timeout=999, allow_redirects=True)

    monkeypatch.setattr(requests.Session, "request", request)
    monkeypatch.setattr(pywebpush, "webpush", webpush)
    assert push.process_notifications(store)["failed"] == 1
    assert len(observed) == 1
    trust_env, method, _, kwargs = observed[0]
    assert trust_env is False
    assert method.lower() == "post"
    assert kwargs["allow_redirects"] is False
    assert kwargs["timeout"] == 5


def test_delivery_lease_and_snapshot_prevent_midflight_duplicates(setup):
    store, client = setup
    created = register(client)
    notice(store)
    calls = []

    def send(sub, payload):
        calls.append(sub["id"])
        store.create(push.SUBSCRIPTIONS, "late", {"id": "late", **subscription("late")})
        assert push.process_notifications(store, lambda *args: pytest.fail("leased delivery resent"))["sent"] == 0

    push.process_notifications(store, send)
    assert calls == [created["id"]]
    assert len(store.list(push.DELIVERIES)) == 1
