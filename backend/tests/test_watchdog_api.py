"""Watchdog wire compatibility, authenticated journaling and snapshot isolation."""

import copy
import importlib.util
import json
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.cloud.api import create_app
from app.cloud.service import CloudService, bootstrap_demo, stamp, utcnow
from app.cloud.store import ConflictError, MemoryStore

DEVICE = "unoq-fridge-a"
HEADERS = {"x-functions-key": "device-function", "x-device-key": "device-secret"}
ROUTES = {
    "unfreeze_allowed": "/api/events/unfreeze-allowed",
    "unfreeze_check_required": "/api/notifications/operator",
    "power_outage": "/api/events/power-outage",
    "doors_open": "/api/events/doors-open",
    "inventory_changed": "/api/inventory/sync",
    "telemetry": "/api/telemetry",
    "fridge_tamper": "/api/events/fridge-tamper",
    "alarm_acknowledged": "/api/events/alarm-ack",
    "alarm_resolved": "/api/events/alarm-resolved",
}
DATA = {
    "unfreeze_allowed": {},
    "unfreeze_check_required": {"stocked_items": ["device-product"], "units": 2},
    "power_outage": {"protocol": "P1", "window_minutes": 60, "limiting_medicine": "device-product",
                     "reachable_clinics": [{"id": "clinic-x", "name": "Reported clinic", "phone": None, "drive_minutes": 20}],
                     "inventory": [{"id": "device-product", "quantity": 2}]},
    "doors_open": {"duration_s": 15, "stocked": True},
    "inventory_changed": {"inventory": [{"id": "device-product", "quantity": 2}]},
    "telemetry": {"temp_c": 4.5, "humidity": 44.2, "alarm": "unfreeze"},
    "fridge_tamper": {"sensor_temp_c": 10.0, "fridge_display_temp_c": 4.0, "mismatch_c": -6.0,
                      "fridge_mode": "defrost", "fridge_power_w": 320.0, "stocked_items": ["device-product"], "code": "H1"},
    "alarm_acknowledged": {"alarm_kind": "fridge_tamper", "code": "H1", "doors": False, "acknowledged_by": "knob"},
    "alarm_resolved": {"alarm_kind": "fridge_tamper", "code": "H1", "acknowledged_at": None, "resolved_by": "knob"},
}


def envelope(event, **overrides):
    return {"device_id": DEVICE, "event": event, "ts": stamp(), "data": copy.deepcopy(DATA[event]), **overrides}


@pytest.fixture
def cloud(monkeypatch):
    monkeypatch.setenv("COLDCHAIN_OPERATOR_KEY", "operator-secret")
    monkeypatch.setenv("COLDCHAIN_DEVICE_FUNCTION_KEY", "device-function")
    monkeypatch.setenv("COLDCHAIN_DEVICE_KEYS", json.dumps({DEVICE: "device-secret", "unoq-fridge-b": "other-secret"}))
    store = MemoryStore()
    bootstrap_demo(store)
    with TestClient(create_app(store)) as client:
        yield client, store


def post(client, event, body=None, **kwargs):
    return client.post(ROUTES[event], headers=HEADERS, json=body if body is not None else envelope(event), **kwargs)


@pytest.mark.parametrize("event", ROUTES)
def test_routes_journal_deduplicate_and_scope(cloud, event):
    client, store = cloud
    body = envelope(event)
    first = post(client, event, body)
    assert first.status_code == 200, first.text
    before = {kind: store.list(kind) for kind in ("Events", "Timeline", "Notifications", "Alerts", "Readings", "DeviceInventory", "Devices")}
    again = post(client, event, body)
    assert again.json()["duplicate"] is True
    assert before == {kind: store.list(kind) for kind in before}
    rows = client.get(f"/api/events?device_id={DEVICE}&location_id=fridge-a").json()
    assert len(rows) == 1
    assert rows[0]["event"] == event
    assert rows[0]["data"] == body["data"]
    assert "payload" not in rows[0]
    assert client.get("/api/events?location_id=fridge-b").json() == []
    assert client.get("/api/events?device_id=unoq-fridge-b").json() == []
    changed = copy.deepcopy(body)
    changed["data"] = {**changed["data"], "unexpected": True}
    assert post(client, event, changed).status_code == 422


@pytest.mark.parametrize("event", ROUTES)
def test_all_device_envelopes_require_both_scoped_keys(cloud, event):
    client, store = cloud
    body = envelope(event)
    for headers in ({}, {"x-functions-key": "operator-secret"}, {"x-device-key": "device-secret"},
                    {"x-functions-key": "device-function"}, {**HEADERS, "x-device-key": "other-secret"}):
        assert client.post(ROUTES[event], headers=headers, json=body).status_code == 401
    assert store.list("Events") == []


@pytest.mark.parametrize("event", ROUTES)
@pytest.mark.parametrize("change", ["mismatch", "missing_data", "null_data", "missing_ts", "naive_ts", "non_utc", "future", "location"])
def test_invalid_envelopes_rejected(cloud, event, change):
    client, store = cloud
    body = envelope(event)
    if change == "mismatch":
        body["event"] = "wrong_event"
    elif change == "missing_data":
        del body["data"]
    elif change == "null_data":
        body["data"] = None
    elif change == "missing_ts":
        del body["ts"]
    elif change == "naive_ts":
        body["ts"] = "2026-01-01T00:00:00"
    elif change == "non_utc":
        body["ts"] = "2026-01-01T00:00:00+02:00"
    elif change == "future":
        body["ts"] = stamp(utcnow() + timedelta(minutes=10))
    else:
        body["location_id"] = "fridge-b"
    assert post(client, event, body).status_code == 422
    assert store.list("Events") == []


@pytest.mark.parametrize("event,data", [
    ("inventory_changed", {"inventory": [{"id": "a", "quantity": -1}]}),
    ("inventory_changed", {"inventory": [{"id": "a", "quantity": 1.2}]}),
    ("inventory_changed", {"inventory": [{"id": "a", "quantity": True}]}),
    ("inventory_changed", {"inventory": [{"id": "a", "quantity": 1}] * 2}),
    ("inventory_changed", {"inventory": [{"id": str(i), "quantity": 1} for i in range(101)]}),
    ("inventory_changed", {"inventory": [{"id": "a" * 129, "quantity": 1}]}),
    ("inventory_changed", {"inventory": [{"id": str(i) + "a" * 120, "quantity": 1} for i in range(100)]}),
    ("unfreeze_check_required", {"stocked_items": ["a", "a"], "units": 1}),
    ("unfreeze_check_required", {"stocked_items": ["a"], "units": -1}),
    ("unfreeze_allowed", {"allowed": True}),
    ("doors_open", {"duration_s": -1, "stocked": True}),
    ("doors_open", {"duration_s": 15, "stocked": "true"}),
    ("telemetry", {"temp_c": "NaN"}),
    ("telemetry", {"temp_c": 4, "humidity": 101}),
    ("telemetry", {"temp_c": 4, "alarm": "a" * 129}),
    ("power_outage", {**DATA["power_outage"], "protocol": 25}),
    ("power_outage", {**DATA["power_outage"], "window_minutes": "Infinity"}),
    ("power_outage", {**DATA["power_outage"], "reachable_clinics": [{"id": "x", "name": "n", "drive_minutes": -1}]}),
])
def test_invalid_bounded_data(cloud, event, data):
    client, _ = cloud
    assert post(client, event, envelope(event, data=data)).status_code == 422


@pytest.mark.parametrize("event", [e for e in ROUTES if e != "unfreeze_allowed"])
def test_required_data_fields(cloud, event):
    client, _ = cloud
    for field in DATA[event]:
        if event == "telemetry" and field in {"humidity", "alarm"}:
            continue
        data = copy.deepcopy(DATA[event])
        del data[field]
        assert post(client, event, envelope(event, data=data)).status_code == 422


def test_inventory_snapshot_stale_and_canonical_isolation(cloud):
    client, store = cloud
    assert client.get(f"/api/devices/{DEVICE}/inventory").status_code == 404
    canonical = copy.deepcopy(client.get("/api/inventory").json())
    body = envelope("inventory_changed")
    assert post(client, "inventory_changed", body).status_code == 200
    current = client.get(f"/api/devices/{DEVICE}/inventory").json()
    assert current["inventory"] == body["data"]["inventory"]
    assert current["stock_present"] is True
    assert current["canonical_stock_updated"] is False
    stale = envelope("inventory_changed", ts=stamp(utcnow() - timedelta(hours=1)), data={"inventory": []})
    assert post(client, "inventory_changed", stale).json()["stale"] is True
    assert client.get(f"/api/devices/{DEVICE}/inventory").json() == current
    assert len(store.list("DeviceInventory")) == 1
    assert post(client, "inventory_changed", envelope("inventory_changed", data={"inventory": []})).status_code == 200
    assert client.get(f"/api/devices/{DEVICE}/inventory").json()["stock_present"] is False
    after = client.get("/api/inventory").json()
    assert [(r["stock"], r["stock_present"], r["used_units"]) for r in canonical] == [(r["stock"], r["stock_present"], r["used_units"]) for r in after]
    assert client.get(f"/api/devices/{DEVICE}/config", headers=HEADERS).json()["stock_present"] is True


def test_power_case25_and_unverified_metadata_stale_status(cloud, monkeypatch):
    client, store = cloud
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: pytest.fail("No clinic network calls"))
    body = envelope("power_outage")
    assert post(client, "power_outage", body).json()["alarm_state"] == "POWER_LOSS"
    alert = client.get("/api/alerts").json()[0]
    assert alert["protocol"] == 25
    assert alert["device_reported_protocol"] == "P1"
    assert alert["device_reported_assessment"]["window_minutes"] == 60
    assert alert["clinical_safety_certified"] is False
    assert alert["assessment_source"] == "device_unverified"
    assert "safe for" not in alert["message"]
    assert store.list("Notifications")[0]["type"] == "POWER_LOSS"
    stale = envelope("power_outage", ts=stamp(utcnow() - timedelta(hours=1)), data={**DATA["power_outage"], "protocol": "P4"})
    assert post(client, "power_outage", stale).json()["stale"] is True
    assert client.get("/api/alerts").json()[0]["device_reported_protocol"] == "P1"
    status = {"device_id": DEVICE, "status": "nominal", "ts": stamp()}
    assert client.post("/api/telemetry/status", headers=HEADERS, json=status).status_code == 200
    older = envelope("power_outage", ts=stamp(utcnow() - timedelta(seconds=1)))
    assert post(client, "power_outage", older).json()["stale"] is True
    assert store.get("Locations", "fridge-a")["power_on"] is True


def test_warning_doors_timeline_and_explicit_id_conflicts(cloud):
    client, store = cloud
    post(client, "unfreeze_check_required")
    notice = store.list("Notifications")[0]
    assert notice["severity"] == "warning"
    assert notice["location_id"] == "fridge-a"
    assert post(client, "doors_open").json()["alarm_state"] == "DOORS_OPEN"
    assert any(a["type"] == "DOORS_OPEN" for a in store.list("Alerts"))
    body = envelope("unfreeze_allowed", event_id="explicit")
    assert post(client, "unfreeze_allowed", body).status_code == 200
    assert any(t["type"] == "unfreeze_allowed" for t in store.list("Timeline"))
    assert post(client, "unfreeze_allowed", body).json()["duplicate"] is True
    assert post(client, "doors_open", envelope("doors_open", event_id="explicit")).status_code == 409
    telemetry = envelope("telemetry")
    assert post(client, "telemetry", telemetry).status_code == 200
    telemetry["data"]["humidity"] = 40
    assert post(client, "telemetry", telemetry).status_code == 409


def test_public_sanitization_and_limits(cloud):
    client, store = cloud
    post(client, "inventory_changed")
    event = store.list("Events")[0]
    event["data"]["nested"] = {"api_key": "DO-NOT-EXPOSE", "access_token": "DO-NOT-EXPOSE", "endpoint": "DO-NOT-EXPOSE"}
    event["payload"]["private"] = "DO-NOT-EXPOSE"
    store.put("Events", event["id"], event)
    snapshot = store.list("DeviceInventory")[0]
    snapshot["metadata"] = {"password": "DO-NOT-EXPOSE"}
    store.put("DeviceInventory", snapshot["id"], snapshot)
    assert "DO-NOT-EXPOSE" not in client.get("/api/events").text
    assert "DO-NOT-EXPOSE" not in client.get(f"/api/devices/{DEVICE}/inventory").text
    for limit in (0, 1001):
        assert client.get(f"/api/events?limit={limit}").status_code == 422


def test_outbox_survives_projection_failure_and_retry(cloud, monkeypatch):
    client, store = cloud
    original = store.create
    def unavailable(kind, key, value):
        if kind in {"DeviceInventory", "Notifications"}:
            raise ConflictError("Projection unavailable")
        return original(kind, key, value)
    monkeypatch.setattr(store, "create", unavailable)
    body = envelope("inventory_changed")
    assert post(client, "inventory_changed", body).status_code == 200
    warning = envelope("unfreeze_check_required")
    assert post(client, "unfreeze_check_required", warning).status_code == 200
    assert store.list("DeviceInventory") == []
    assert len(store.list("Outbox")) == 2
    assert client.get(f"/api/devices/{DEVICE}/inventory").json()["inventory"] == body["data"]["inventory"]
    assert post(client, "inventory_changed", body).json()["duplicate"] is True
    monkeypatch.setattr(store, "create", original)
    CloudService(store).flush_notifications()
    assert store.list("Outbox") == []
    assert len(store.list("Notifications")) == len(store.list("DeviceInventory")) == 1


@pytest.mark.parametrize("event,field", [("telemetry", "temp_c"), ("doors_open", "duration_s"), ("power_outage", "window_minutes")])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_json_numbers_rejected(cloud, event, field, value):
    client, _ = cloud
    body = envelope(event)
    body["data"][field] = value
    response = client.post(ROUTES[event], headers={**HEADERS, "content-type": "application/json"},
                           content=json.dumps(body))
    assert response.status_code == 422


def test_normalized_timestamp_hash_and_stale_telemetry(cloud):
    client, store = cloud
    body = envelope("telemetry")
    assert post(client, "telemetry", body).status_code == 200
    body["ts"] = body["ts"].replace("+00:00", "Z")
    assert post(client, "telemetry", body).json()["duplicate"] is True
    stale = envelope("telemetry", ts=stamp(utcnow() - timedelta(hours=1)), data={"temp_c": 80, "humidity": None, "alarm": None})
    assert post(client, "telemetry", stale).json()["stale"] is True
    assert store.get("Locations", "fridge-a")["last_temp_c"] == 4.5
    assert store.list("Alerts") == []
    assert len(store.list("Readings")) == 2


def test_transaction_conflict_retries_without_duplicate_side_effects(cloud, monkeypatch):
    client, store = cloud
    original = store.transaction
    attempts = 0
    def conflict_once(changes):
        nonlocal attempts
        if any(kind == "Events" for kind, *_ in changes):
            attempts += 1
            if attempts == 1:
                raise ConflictError("Concurrent revision")
        return original(changes)
    monkeypatch.setattr(store, "transaction", conflict_once)
    assert post(client, "doors_open").status_code == 200
    assert attempts == 2
    assert len(store.list("Events")) == len(store.list("Alerts")) == len(store.list("Notifications")) == 1
    assert len(store.list("Timeline")) == 2


def test_missing_config_unknown_device_and_changed_retry_data(cloud, monkeypatch):
    client, store = cloud
    for name in ("COLDCHAIN_DEVICE_FUNCTION_KEY", "COLDCHAIN_DEVICE_KEYS"):
        with monkeypatch.context() as env:
            env.setenv(name, "" if name.endswith("FUNCTION_KEY") else "{}")
            assert post(client, "doors_open").status_code == 401
    with monkeypatch.context() as env:
        env.setenv("COLDCHAIN_DEVICE_KEYS", json.dumps({"unknown": "device-secret"}))
        assert post(client, "doors_open", envelope("doors_open", device_id="unknown")).status_code == 404
    body = envelope("inventory_changed")
    assert post(client, "inventory_changed", body).status_code == 200
    body["data"]["inventory"][0]["quantity"] = 9
    assert post(client, "inventory_changed", body).status_code == 409
    assert len(store.list("DeviceInventory")) == 1


def test_actual_stub_and_watchdog_generated_payloads(cloud, monkeypatch):
    client, _ = cloud
    monkeypatch.setenv("BACKEND_ENABLED", "0")
    monkeypatch.setenv("COLDCHAIN_DEVICE_ID", DEVICE)
    root = Path(__file__).resolve().parents[2] / "device" / "coldchain-watchdog" / "python"
    modules = []
    try:
        for name in ("backend_stub", "logic"):
            spec = importlib.util.spec_from_file_location(f"watchdog_test_{name}", root / f"{name}.py")
            module = importlib.util.module_from_spec(spec)
            monkeypatch.setitem(sys.modules, spec.name, module)
            spec.loader.exec_module(module)
            modules.append(module)
        stub, logic = modules
        watchdog = logic.Watchdog(json.loads((root / "data" / "medicines.json").read_text(encoding="utf-8")),
                                  json.loads((root / "data" / "clinics.json").read_text(encoding="utf-8")))
        seen = set()
        for command in ("unfreeze", "power_outage", "doors_open", "empty", "unfreeze", "fill"):
            for function, data in watchdog.handle(command).stubs:
                payload = stub.STUBS[function](data)
                response = post(client, payload["event"], payload)
                assert response.status_code == 200, response.text
                seen.add(payload["event"])
        for humidity, alarm in ((42.5, "power_outage"), (None, None)):
            payload = stub.send_telemetry({"temp_c": 4.5, "humidity": humidity, "alarm": alarm})
            assert post(client, "telemetry", payload).status_code == 200
            assert client.get("/api/events?limit=1").json()[0]["data"] == payload["data"]
            seen.add("telemetry")
        watchdog.handle("reset")
        watchdog.update_reading(10, 40)
        watchdog.handle("hack_fridge")
        outcomes = [watchdog.check_fridge_tamper(), watchdog.knob_turn(5)]
        watchdog.ack_message_until = 0
        outcomes.append(watchdog.knob_turn(5))
        for outcome in outcomes:
            assert outcome is not None
            for function, data in outcome.stubs:
                payload = stub.STUBS[function](data)
                response = post(client, payload["event"], payload)
                assert response.status_code == 200, response.text
                seen.add(payload["event"])
        assert seen == set(ROUTES)
    finally:
        modules.clear()

def test_fridge_display_telemetry_and_stale_reading(cloud):
    client, _ = cloud
    body = envelope('telemetry', data={'temp_c': 10.0, 'humidity': 42.0, 'fridge_display_temp_c': 4.0, 'alarm': 'fridge_tamper'})
    assert post(client, 'telemetry', body).status_code == 200
    reading = client.get('/api/readings?location_id=fridge-a').json()[-1]
    assert reading['fridge_display_temp_c'] == 4.0
    assert reading['humidity'] == 42.0
    older = envelope('telemetry', ts=stamp(utcnow()-timedelta(minutes=1)), data={'temp_c': 6.0, 'fridge_display_temp_c': 6.3})
    assert post(client, 'telemetry', older).json()['stale']
    location = next(x for x in client.get('/api/clinics').json() if x['id']=='fridge-a')
    assert location['reported_temp_c'] == 4.0


def alarm_state(client):
    return next(x for x in client.get('/api/clinics').json() if x['id']=='fridge-a')['alarm_state']


def test_knob_ack_then_resolve_closes_incident(cloud):
    client, _ = cloud
    assert post(client, 'fridge_tamper').status_code == 200
    assert post(client, 'alarm_acknowledged').status_code == 200
    alert = next(a for a in client.get('/api/alerts').json() if a['type']=='TAMPER')
    assert alert['status'] == 'acknowledged' and alert['device_acknowledged_by'] == 'knob'
    assert alarm_state(client) == 'TAMPER'
    completion = envelope('alarm_resolved')
    assert post(client, 'alarm_resolved', completion).status_code == 200
    assert post(client, 'alarm_resolved', completion).json()['duplicate']
    alert = next(a for a in client.get('/api/alerts').json() if a['type']=='TAMPER')
    assert alert['protocol'] == 'H1'
    assert alert['status'] == 'resolved'
    assert alert['resolved_by'] == alert['device_resolved_by'] == 'knob'
    assert alert['resolved_at'] == alert['recovered_at'] == completion['ts']
    assert alarm_state(client) == 'NORMAL'


def test_reset_resolves_active_incidents(cloud):
    client, _ = cloud
    assert post(client, 'power_outage').status_code == 200
    assert post(client, 'doors_open').status_code == 200
    assert alarm_state(client) == 'POWER_LOSS'
    data = {'alarm_kind': 'power_outage', 'code': 'P1', 'acknowledged_at': None, 'doors': True, 'resolved_by': 'reset'}
    assert post(client, 'alarm_resolved', envelope('alarm_resolved', data=data)).status_code == 200
    alerts = {a['type']: a for a in client.get('/api/alerts').json()}
    assert alerts['POWER_LOSS']['status'] == alerts['DOORS_OPEN']['status'] == 'resolved'
    assert alerts['POWER_LOSS']['resolved_by'] == 'reset'
    assert alarm_state(client) == 'NORMAL'
    assert next(x for x in client.get('/api/clinics').json() if x['id']=='fridge-a')['power_on'] is True


def test_resolve_must_name_something(cloud):
    client, _ = cloud
    data = {'alarm_kind': None, 'code': None, 'acknowledged_at': None, 'doors': False, 'resolved_by': 'reset'}
    assert post(client, 'alarm_resolved', envelope('alarm_resolved', data=data)).status_code == 422


@pytest.mark.parametrize("event,kind", [("fridge_tamper", "TAMPER"), ("power_outage", "POWER_LOSS")])
def test_watchdog_user_resolved_incidents_are_immutable_and_new_reports_create_incident(cloud, event, kind):
    client, store = cloud
    assert post(client, event).status_code == 200
    identifier = next(a["id"] for a in client.get("/api/alerts").json() if a["type"] == kind)
    for item_id in ("inspect", "protect", "verify"):
        assert client.patch(f"/api/alerts/{identifier}/public-checklist/{item_id}", json={"done": True}).status_code == 200
    old = store.get("Alerts", str(identifier))
    alarm_kind = "fridge_tamper" if kind == "TAMPER" else "power_outage"
    for action in ("alarm_acknowledged", "alarm_resolved"):
        data = {**DATA[action], "alarm_kind": alarm_kind}
        assert post(client, action, envelope(action, data=data)).json()["alarm_state"] == "NORMAL"
        assert store.get("Alerts", str(identifier)) == old
    if kind == "POWER_LOSS":
        data = {**DATA[event], "protocol": "P4"}
    else:
        data = {**DATA[event], "fridge_power_w": 100.0}
    assert post(client, event, envelope(event, data=data)).json()["alarm_state"] == kind
    active = [a for a in store.list("Alerts") if a["type"] == kind and a["status"] == "open"]
    assert len(active) == 1 and active[0]["id"] != identifier
    if kind == "POWER_LOSS":
        assert active[0]["device_reported_protocol"] == "P4"
    else:
        assert active[0]["device_reported_assessment"]["fridge_power_w"] == 100.0
    assert store.get("Alerts", str(identifier)) == old
    assert old["recovered_at"] is None


def test_transferred_inventory_remains_device_report(cloud):
    client, store = cloud
    before = store.list('StockItems')
    data={'inventory':[], 'transferred':[{'id':'device-product','quantity':2}]}
    assert post(client, 'inventory_changed', envelope('inventory_changed',data=data)).status_code==200
    snapshot=client.get(f'/api/devices/{DEVICE}/inventory').json()
    assert snapshot['transferred']==data['transferred']
    assert snapshot['stock_present'] is False
    assert snapshot['canonical_stock_updated'] is False
    assert store.list('StockItems')==before


def test_inconsistent_tamper_report_rejected(cloud):
    client, _ = cloud
    body=envelope('fridge_tamper')
    body['data']['mismatch_c']=6.0
    assert post(client,'fridge_tamper',body).status_code==422
