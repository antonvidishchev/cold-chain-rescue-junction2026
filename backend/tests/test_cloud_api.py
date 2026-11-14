"""Cloud contracts: explicit fictional bootstrap and no legacy database imports."""

import io
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.cloud.api import create_app
from app.cloud.service import CloudService, STATE_KEY, STATE_KIND, bootstrap_demo, check_offline, stamp, utcnow
from app.cloud.store import MemoryStore

DEVICE = "unoq-fridge-a"
DH = {"x-functions-key": "device-function", "x-device-key": "device-secret"}
OH = {"x-functions-key": "operator-secret"}


class Media:
    def __init__(self):
        self.images = {}
        self.queue = []
        self.fail = False

    def upload_image(self, image_id, data, content_type):
        assert content_type == "image/jpeg"
        self.images[image_id] = data

    def read_image(self, image_id):
        return self.images[image_id]

    def enqueue_image(self, image_id):
        if self.fail:
            raise RuntimeError("Queue unavailable")
        self.queue.append(image_id)


@pytest.fixture
def cloud(monkeypatch):
    monkeypatch.setenv("COLDCHAIN_OPERATOR_KEY", "operator-secret")
    monkeypatch.setenv("COLDCHAIN_DEVICE_FUNCTION_KEY", "device-function")
    monkeypatch.setenv("COLDCHAIN_DEVICE_KEYS", json.dumps({DEVICE: "device-secret", "unoq-fridge-b": "other-secret"}))
    for key in ("COLDCHAIN_MIN_C", "COLDCHAIN_MAX_C", "COLDCHAIN_RISE_C", "COLDCHAIN_RISE_WINDOW_SECONDS", "COLDCHAIN_CONSECUTIVE_READINGS", "COLDCHAIN_OFFLINE_SECONDS", "COLDCHAIN_IMAGE_MAX_BYTES", "COLDCHAIN_IMAGE_MAX_PIXELS"):
        monkeypatch.delenv(key, raising=False)
    store = MemoryStore()
    bootstrap_demo(store)
    media = Media()
    with TestClient(create_app(store, media)) as client:
        yield client, store, media


def reading(client, value, seconds_ago=0, event=None, **fields):
    payload = {"device_id": DEVICE, "temp_c": value, "observed_at": stamp(utcnow() - timedelta(seconds=seconds_ago)), **fields}
    if event:
        payload["event_id"] = event
    return client.post("/api/telemetry/temperature", headers=DH, json=payload)


def jpeg():
    output = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(output, format="JPEG")
    return output.getvalue()


def test_explicit_bootstrap_and_five_fictional_clinics(cloud):
    client, store, _ = cloud
    empty = MemoryStore()
    with TestClient(create_app(empty)) as unseeded:
        assert unseeded.get("/api/inventory").json() == []
        assert empty.get(STATE_KIND, STATE_KEY) is None
    assert bootstrap_demo(store) == {"created": False, "clinics": 5}
    inventory = client.get("/api/inventory").json()
    assert {row["city"] for row in inventory} == {"Helsinki", "Espoo", "Tampere", "Vantaa", "Oulu"}
    assert {"fridge-a", "fridge-b", "clinic-c"} <= {row["id"] for row in inventory}
    assert all(row["synthetic"] and "fictional" in row["name"] for row in inventory)
    assert client.get(f"/api/devices/{DEVICE}/config", headers=DH).json()["max_c"] == 6


@pytest.mark.parametrize("path,payload", [
    ("/api/telemetry", {"device_id": DEVICE, "temp_c": 5}),
    ("/api/telemetry/status", {"device_id": DEVICE, "status": "nominal"}),
    (f"/api/devices/{DEVICE}/heartbeat", {}),
    (f"/api/devices/{DEVICE}/commands/1/ack", {}),
])
def test_device_mutations_require_both_scoped_keys(cloud, path, payload):
    client, _, _ = cloud
    for headers in ({}, OH, {"x-device-key": "device-secret"}, {"x-functions-key": "device-function"},
                    {"x-functions-key": "device-function", "x-device-key": "other-secret"}):
        assert client.post(path, json=payload, headers=headers).status_code == 401


@pytest.mark.parametrize("path,payload", [
    (f"/api/devices/{DEVICE}/commands", {"command": "silence"}),
    ("/api/alerts/1/ack", {"by": "Operator"}), ("/api/alerts/1/resolve", {}),
    ("/api/alerts/1/checklist/inspect", {"by": "Operator", "done": True}),
    ("/api/transfers/propose", {"source_location_id": "fridge-a"}),
    ("/api/transfers/1/approve", {"by": "Operator"}),
    ("/api/sim/power", {"location_id": "fridge-a", "on": False}),
    ("/api/sim/fridge-report", {"location_id": "fridge-a", "temp_c": 4}),
    ("/api/sim/camera", {"location_id": "fridge-a", "stock_present": True}),
])
def test_all_operator_mutations_protected(cloud, path, payload):
    client, _, _ = cloud
    assert client.post(path, json=payload).status_code == 401
    assert client.post(path, json=payload, headers=DH).status_code == 401


def test_fail_closed_with_empty_environment(cloud, monkeypatch):
    client, _, _ = cloud
    monkeypatch.setenv("COLDCHAIN_OPERATOR_KEY", "")
    monkeypatch.setenv("COLDCHAIN_DEVICE_FUNCTION_KEY", "")
    assert client.post("/api/sim/power", json={"location_id": "fridge-a", "on": False}, headers=OH).status_code == 401
    assert client.get(f"/api/devices/{DEVICE}/config", headers=DH).status_code == 401


def test_public_reads_redact_device_and_nested_secrets(cloud):
    client, store, _ = cloud
    device = store.get("Devices", DEVICE)
    device.update(device_key="DO-NOT-EXPOSE", arbitrary_private="DO-NOT-EXPOSE")
    store.put("Devices", DEVICE, device)
    location = store.get("Locations", "fridge-a")
    location["metadata"] = {"connection_string": "DO-NOT-EXPOSE", "nested": {"api_key": "DO-NOT-EXPOSE"}}
    store.put("Locations", "fridge-a", location)
    for route in ("/api/inventory", "/api/products", "/api/devices", "/api/readings", "/api/alerts", "/api/transfers", "/api/timeline", "/api/images"):
        response = client.get(route)
        assert response.status_code == 200
        assert "DO-NOT-EXPOSE" not in response.text
    assert client.get(f"/api/devices/{DEVICE}/config").status_code == 401
    assert client.get(f"/api/devices/{DEVICE}/commands").status_code == 401


def test_legacy_and_new_telemetry_event_dedup_and_older_events(cloud):
    client, _, _ = cloud
    payload = {"device_id": DEVICE, "event_id": "one", "temperature_c": 5.5, "clinic_id": "helsinki", "observed_at": stamp()}
    first = client.post("/api/telemetry/temperature", json=payload, headers=DH)
    assert first.status_code == 200
    assert first.json()["duplicate"] is False
    assert client.post("/api/telemetry/temperature", json=payload, headers=DH).json()["duplicate"] is True
    assert client.post("/api/telemetry/temperature", json={**payload, "temperature_c": 10}, headers=DH).status_code == 409
    assert reading(client, 15, 100, "older").json()["stale"] is True
    location = next(r for r in client.get("/api/inventory").json() if r["id"] == "fridge-a")
    assert location["last_temp_c"] == 5.5
    rows = client.get("/api/readings?location_id=fridge-a").json()
    assert [r["temp_c"] for r in rows] == [15, 5.5]
    assert client.post("/api/telemetry", headers=DH, json={"device_id": DEVICE, "temp_c": 4}).status_code == 200
    assert client.post("/api/telemetry", headers=DH, json={"device_id": DEVICE, "temp_c": 4, "event_id": "no-time"}).json()["duplicate"] is False
    assert client.post("/api/telemetry", headers=DH, json={"device_id": DEVICE, "temp_c": 4, "event_id": "no-time"}).json()["duplicate"] is True


@pytest.mark.parametrize("extra", [
    {"clinic_id": "espoo"}, {"location_id": "fridge-b"}, {"observed_at": "2026-01-01T12:00:00"},
    {"observed_at": "2026-01-01T12:00:00+02:00"}, {"observed_at": "invalid"}, {"temp_c": "NaN"},
    {"temp_c": "Infinity"}, {"temperature_c": 100},
])
def test_bad_telemetry_rejected(cloud, extra):
    client, _, _ = cloud
    response = client.post("/api/telemetry", headers=DH, json={"device_id": DEVICE, "temp_c": 4, **extra})
    assert response.status_code == 422


def test_incident_rules_acknowledgement_recovery_and_checklist(cloud):
    client, store, _ = cloud
    assert reading(client, 9, 10).status_code == 200
    assert client.get("/api/alerts").json() == []
    assert reading(client, 10, 5).json()["alarm_state"] == "EXCURSION"
    reading(client, 11, 3)
    alerts = client.get("/api/alerts").json()
    assert len(alerts) == 1
    identifier = alerts[0]["id"]
    assert len(store.list("Notifications")) == 1
    ack = client.post(f"/api/alerts/{identifier}/ack", json={"by": "Pharmacist"}, headers=OH).json()
    assert ack["status"] == "acknowledged" and ack["recovered_at"] is None
    assert client.post(f"/api/alerts/{identifier}/resolve", headers=OH).status_code == 409
    updated = client.patch(f"/api/alerts/{identifier}/checklist/inspect", headers=OH, json={"done": True, "by": "Pharmacist"})
    assert updated.json()["checklist"][0]["done"]
    assert client.get(f"/api/alerts/{identifier}/timeline").json()
    reading(client, 4)
    recovered = client.get(f"/api/alerts/{identifier}").json()
    assert recovered["status"] == "acknowledged" and recovered["recovered_at"]
    assert client.post(f"/api/alerts/{identifier}/resolve", headers=OH).json()["status"] == "resolved"
    commands = client.get(f"/api/devices/{DEVICE}/commands", headers=DH).json()
    assert [c["command"] for c in commands] == ["silence"]


def test_rapid_rise_requires_five_minute_coverage(cloud):
    client, _, _ = cloud
    base = utcnow() - timedelta(seconds=600)
    def sample(seconds, temperature):
        return client.post("/api/telemetry", headers=DH, json={"device_id": DEVICE, "temp_c": temperature, "ts": stamp(base + timedelta(seconds=seconds))})
    sample(0, 3)
    sample(60, 5)
    assert not any(a["type"] == "RAPID_RISE" for a in client.get("/api/alerts").json())
    sample(300, 5)
    assert any(a["type"] == "RAPID_RISE" for a in client.get("/api/alerts").json())


def test_sparse_rapid_rise_window_does_not_trigger(cloud):
    client, _, _ = cloud
    reading(client, 3, 1000)
    reading(client, 5)
    assert not any(a["type"] == "RAPID_RISE" for a in client.get("/api/alerts").json())


def test_status_protocol_25_dedup_old_status_and_offline(cloud):
    client, store, _ = cloud
    power = {"device_id": DEVICE, "status": "power_outage", "event_id": "power", "observed_at": stamp()}
    assert client.post("/api/telemetry/status", json=power, headers=DH).json()["alarm_state"] == "POWER_LOSS"
    assert client.post("/api/telemetry/status", json=power, headers=DH).json()["duplicate"] is True
    older = {"device_id": DEVICE, "status": "nominal", "observed_at": stamp(utcnow() - timedelta(minutes=1))}
    assert client.post("/api/telemetry/status", json=older, headers=DH).json()["stale"] is True
    assert client.get("/api/alerts").json()[0]["protocol"] == 25
    device = store.get("Devices", DEVICE)
    device["last_seen"] = stamp(utcnow() - timedelta(seconds=91))
    store.put("Devices", DEVICE, device)
    assert any(row["device_id"] == DEVICE for row in check_offline(store))
    check_offline(store)
    offline = [a for a in client.get("/api/alerts").json() if a["type"] == "OFFLINE"]
    assert len(offline) == 1
    assert client.post(f"/api/devices/{DEVICE}/heartbeat", headers=DH).status_code == 200
    assert client.get(f"/api/alerts/{offline[0]['id']}").json()["recovered_at"]


def test_future_command_expiry_is_not_an_observation_time(cloud):
    client, _, _ = cloud
    response = client.post(f"/api/devices/{DEVICE}/commands", headers=OH,
                           json={"command": "capture_image", "expires_at": stamp(utcnow() + timedelta(hours=1))})
    assert response.status_code == 200


def test_equal_timestamp_reading_does_not_change_next_incident_decision(cloud):
    client, _, _ = cloud
    at = stamp(utcnow() - timedelta(seconds=10))
    assert client.post("/api/telemetry", headers=DH, json={"device_id": DEVICE, "temp_c": 4, "ts": at}).status_code == 200
    assert client.post("/api/telemetry", headers=DH, json={"device_id": DEVICE, "temp_c": 12, "ts": at}).json()["stale"]
    reading(client, 12)
    assert not any(a["type"] == "EXCURSION" for a in client.get("/api/alerts").json())


def test_commands_not_consumed_idempotent_ack_and_expiry(cloud):
    client, store, _ = cloud
    response = client.post(f"/api/devices/{DEVICE}/commands", headers=OH, json={"command": "capture_image"})
    command = response.json()
    assert response.status_code == 200
    for _ in range(2):
        assert client.get(f"/api/devices/{DEVICE}/commands", headers=DH).json()[0]["id"] == command["id"]
    assert client.post(f"/api/devices/{DEVICE}/heartbeat", headers=DH).json()["commands"]
    ack_url = f"/api/devices/{DEVICE}/commands/{command['id']}/ack"
    first = client.post(ack_url, headers=DH).json()
    assert first["status"] == "acknowledged"
    assert client.post(ack_url, headers=DH).json() == first
    assert client.get(f"/api/devices/{DEVICE}/commands", headers=DH).json() == []
    expired = client.post(f"/api/devices/{DEVICE}/commands", headers=OH, json={"command": "capture_image"}).json()
    record = store.get("Commands", str(expired["id"]))
    record["expires_at"] = stamp(utcnow() - timedelta(seconds=1))
    store.put("Commands", str(expired["id"]), record)
    assert client.get(f"/api/devices/{DEVICE}/commands", headers=DH).json() == []
    assert client.post(f"/api/devices/{DEVICE}/commands/{expired['id']}/ack", headers=DH).status_code == 409
    other_headers = {"x-functions-key": "device-function", "x-device-key": "other-secret"}
    assert client.post(f"/api/devices/unoq-fridge-b/commands/{command['id']}/ack", headers=other_headers).status_code == 404


def test_immediate_transfer_flow_and_revalidation(cloud):
    client, _, _ = cloud
    client.post("/api/sim/power", json={"location_id": "fridge-a", "on": False}, headers=OH)
    plan = client.post("/api/transfers/propose", json={"source_location_id": "fridge-a"}, headers=OH).json()
    assert plan["moves"] and not plan["unplaced"]
    approved = client.post(f"/api/transfers/{plan['id']}/approve", json={"by": "Pharmacist"}, headers=OH)
    assert approved.json()["status"] == "approved"
    inventory = client.get("/api/inventory").json()
    assert next(row for row in inventory if row["id"] == "fridge-a")["stock"] == []
    assert sum(len(row["stock"]) for row in inventory) == 5
    assert client.post(f"/api/transfers/{plan['id']}/approve", json={"by": "Pharmacist"}, headers=OH).status_code == 409


def test_changed_transfer_target_rejects_entire_move(cloud):
    client, _, _ = cloud
    plan = client.post("/api/transfers/propose", json={"source_location_id": "fridge-a"}, headers=OH).json()
    target = plan["moves"][-1]["target_location_id"]
    client.post("/api/sim/power", headers=OH, json={"location_id": target, "on": False})
    assert client.post(f"/api/transfers/{plan['id']}/approve", json={"by": "Pharmacist"}, headers=OH).status_code == 409
    inventory = client.get("/api/inventory").json()
    assert len(next(row for row in inventory if row["id"] == "fridge-a")["stock"]) == 4


def test_concurrent_telemetry_deduplicates_atomically(cloud):
    _, store, _ = cloud
    payload = {"device_id": DEVICE, "temp_c": 4, "event_id": "concurrent", "observed_at": stamp()}
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: CloudService(store).ingest(payload, "temperature"), range(12)))
    assert sum(not r["duplicate"] for r in results) == 1
    assert len(CloudService(store).state()["readings"]) == 1


def test_three_days_five_devices_individual_records_and_bounded_working_state(cloud):
    _, store, _ = cloud
    service = CloudService(store)
    device_ids = list(service.state()["devices"])
    start = utcnow() - timedelta(days=3)
    for minute in range(3 * 24 * 60):
        timestamp = stamp(start + timedelta(minutes=minute))
        for device_id in device_ids:
            service.ingest({"device_id": device_id, "temp_c": 4, "event_id": f"minute-{minute}",
                            "observed_at": timestamp}, "temperature")
    assert len(store.list("Readings")) == 21600
    assert len(store.list("Events")) == 21600
    assert store.list("Outbox") == []
    assert store.get("DomainState", "v1") is None
    assert len(json.dumps(store.get(STATE_KIND, STATE_KEY))) < 200
    assert all(len(json.dumps(row)) < 4000 for row in store.list("Devices"))
    assert all(len(json.dumps(row)) < 1500 for row in store.list("Readings"))
    payload = {"device_id": device_ids[0], "temp_c": 4, "event_id": "minute-0", "observed_at": stamp(start)}
    assert service.ingest(payload, "temperature")["duplicate"]
    assert len(store.list("Readings")) == 21600


def test_image_validation_idempotency_public_synthetic_only(cloud):
    client, store, media = cloud
    raw = jpeg()
    files = {"image": ("sample.jpg", raw, "image/jpeg")}
    fields = {"device_id": DEVICE, "clinic_id": "helsinki", "event_id": "image-one", "synthetic": "true"}
    assert client.post("/api/telemetry/images", data=fields, files=files).status_code == 401
    response = client.post("/api/telemetry/images", headers=DH, data=fields, files=files)
    assert response.status_code == 200, response.text
    identifier = response.json()["id"]
    assert client.post("/api/telemetry/images", headers=DH, data=fields, files=files).json()["duplicate"]
    assert len(store.list("ImageAnalyses")) == 1
    record = store.get("ImageAnalyses", identifier)
    assert record["blob_name"] == identifier + ".jpg"
    record.update(status="completed", description="Synthetic vial shelves")
    store.put("ImageAnalyses", identifier, record)
    metadata = client.get(f"/api/images/{identifier}").json()
    assert metadata["description"] == "Synthetic vial shelves"
    assert "blob_name" not in metadata and "sha256" not in metadata
    assert client.get(f"/api/images/{identifier}/content").content == raw
    private = client.post("/api/telemetry/images", headers=DH, data={"device_id": DEVICE}, files=files).json()["id"]
    assert client.get(f"/api/images/{private}/content").status_code == 404
    assert client.get(f"/api/images/{private}").json()["description"] is None
    assert len(media.images) == 2


@pytest.mark.parametrize("name,content,mime,expected", [
    ("x.png", b"not-jpeg", "image/png", 415), ("x.jpg", b"not-jpeg", "image/jpeg", 422),
    ("x.jpg", b"", "image/jpeg", 413),
])
def test_invalid_images_rejected(cloud, name, content, mime, expected):
    client, store, _ = cloud
    response = client.post("/api/telemetry/images", headers=DH, data={"device_id": DEVICE}, files={"image": (name, content, mime)})
    assert response.status_code == expected
    assert store.list("ImageAnalyses") == []


def test_image_bounds_and_queue_retry(cloud, monkeypatch):
    client, store, media = cloud
    fields = {"device_id": DEVICE, "event_id": "retry"}
    files = {"image": ("x.jpg", jpeg(), "image/jpeg")}
    monkeypatch.setenv("COLDCHAIN_IMAGE_MAX_PIXELS", "1")
    assert client.post("/api/telemetry/images", headers=DH, data=fields, files=files).status_code == 422
    monkeypatch.delenv("COLDCHAIN_IMAGE_MAX_PIXELS")
    monkeypatch.setenv("COLDCHAIN_IMAGE_MAX_BYTES", "10")
    assert client.post("/api/telemetry/images", headers=DH, data=fields, files=files).status_code == 413
    monkeypatch.delenv("COLDCHAIN_IMAGE_MAX_BYTES")
    media.fail = True
    assert client.post("/api/telemetry/images", headers=DH, data=fields, files=files).status_code == 503
    assert store.list("ImageAnalyses")[0]["status"] == "pending"
    media.fail = False
    retried = client.post("/api/telemetry/images", headers=DH, data=fields, files=files)
    assert retried.status_code == 200 and retried.json()["duplicate"]
    assert len(media.queue) == 1
