from fastapi.testclient import TestClient

from app.main import app


def test_demo_flow():
    with TestClient(app) as client:
        inv = client.get("/api/inventory").json()
        assert {loc["id"] for loc in inv} == {"fridge-a", "fridge-b", "clinic-c"}

        # The hacked fridge claims all is fine
        client.post("/api/sim/fridge-report", json={"location_id": "fridge-a", "temp_c": 4.0})

        # Warm reading with stock present -> excursion alert (grace is 0 in tests)
        client.post("/api/telemetry", json={"device_id": "unoq-fridge-a", "temp_c": 11.0})
        r = client.post("/api/telemetry", json={"device_id": "unoq-fridge-a", "temp_c": 12.3})
        assert r.json()["alarm_state"] == "EXCURSION"
        types = {a["type"] for a in client.get("/api/alerts").json()}
        assert {"EXCURSION", "TAMPER"} <= types  # fridge claims 4.0 C, watchdog sees 12.3 C

        # Acknowledge -> device gets a silence command
        alert_id = client.get("/api/alerts").json()[0]["id"]
        client.post(f"/api/alerts/{alert_id}/ack", json={"by": "Pharmacist on duty"})
        cmds = client.get("/api/devices/unoq-fridge-a/commands").json()
        assert any(c["command"] == "silence" for c in cmds)

        # Power loss -> propose and approve a transfer
        client.post("/api/sim/power", json={"location_id": "fridge-a", "on": False})
        plan = client.post("/api/transfers/propose", json={"source_location_id": "fridge-a"}).json()
        assert plan["moves"] and not plan["unplaced"]
        approved = client.post(f"/api/transfers/{plan['id']}/approve", json={"by": "Pharmacist"}).json()
        assert approved["status"] == "approved"
