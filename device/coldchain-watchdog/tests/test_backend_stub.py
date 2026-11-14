"""The watchdog must keep working when the cloud backend is down, slow or rejecting data."""

import json
import os
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

# Never use the real device keys or reach the real cloud from tests: real env
# vars win over python/.env, so set them before the import.
os.environ["BACKEND_ENABLED"] = "0"
os.environ["COLDCHAIN_API_URL"] = "http://127.0.0.1:9"
os.environ["COLDCHAIN_DEVICE_KEY"] = "test-device-key"
os.environ["COLDCHAIN_DEVICE_FUNCTION_KEY"] = "test-function-key"

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

import backend_stub as b  # noqa: E402


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(b, "_backoff", lambda attempt: 0.0)
    monkeypatch.setattr(b, "HTTP_TIMEOUT", 0.5)
    monkeypatch.setattr(b, "EVENT_HTTP_TIMEOUT", 0.5)
    b._dropped_fields.clear()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class FakeCloud:
    """Local HTTP server answering with a scripted list of status codes."""

    def __init__(self, statuses, delay=0.0):
        self.statuses = list(statuses)
        self.requests = []
        cloud = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                cloud.requests.append((self.path, self.headers, body))
                time.sleep(delay)
                status = cloud.statuses.pop(0) if cloud.statuses else 200
                self.send_response(status)
                self.end_headers()
                self.wfile.write(b'{"ok":true}')

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def cloud(monkeypatch):
    servers = []

    def make(statuses=(), delay=0.0):
        server = FakeCloud(statuses, delay)
        servers.append(server)
        monkeypatch.setattr(b, "API_URL", server.url)
        return server

    yield make
    for server in servers:
        server.close()


def envelope(event="doors_open", **data):
    return {"device_id": "unoq-fridge-a", "event": event, "event_id": "e1", "ts": "2026-11-14T13:00:00+00:00", "data": data}


# ----- configuration --------------------------------------------------------
def test_env_file_does_not_override_real_env(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("# comment\nCOLDCHAIN_TEST_A=from-file\nCOLDCHAIN_TEST_B='quoted'\nnot a pair\n")
    monkeypatch.setenv("COLDCHAIN_TEST_A", "from-env")
    monkeypatch.delenv("COLDCHAIN_TEST_B", raising=False)
    b.load_env_file(env)
    assert os.environ["COLDCHAIN_TEST_A"] == "from-env"
    assert os.environ["COLDCHAIN_TEST_B"] == "quoted"
    monkeypatch.delenv("COLDCHAIN_TEST_B")


@pytest.mark.parametrize("make", [
    lambda p: p / "missing.env",
    lambda p: (p / "dir.env").mkdir() or p / "dir.env",
    lambda p: (p / "bad.env").write_bytes(b"\xff\xfe\x00bad") and p / "bad.env",
])
def test_broken_env_file_does_not_crash(tmp_path, make):
    b.load_env_file(make(tmp_path))  # must not raise


def test_auth_headers_are_sent_but_never_logged(cloud, capsys):
    server = cloud([200])
    assert b._deliver("/api/events/doors-open", envelope(), max_attempts=1)
    _, headers, _ = server.requests[0]
    assert headers["x-device-key"] == "test-device-key"
    assert headers["x-functions-key"] == "test-function-key"
    out = capsys.readouterr().out
    assert "test-device-key" not in out and "test-function-key" not in out


# ----- delivery failures ----------------------------------------------------
def test_unreachable_cloud_returns_false_without_raising(monkeypatch):
    monkeypatch.setattr(b, "API_URL", f"http://127.0.0.1:{free_port()}")
    assert b._deliver("/api/events/doors-open", envelope(), max_attempts=3) is False


def test_invalid_url_is_reported_not_raised(monkeypatch):
    monkeypatch.setattr(b, "API_URL", "not-a-url")
    with pytest.raises(ValueError):
        b._post("/api/telemetry", envelope())  # the sender thread catches this


def test_slow_cloud_times_out(cloud):
    cloud([200], delay=2.0)
    started = time.monotonic()
    assert b._deliver("/api/telemetry", envelope("telemetry", temp_c=4.0), max_attempts=1) is False
    assert time.monotonic() - started < 1.5


def test_transient_errors_are_retried_with_the_same_event_id(cloud):
    server = cloud([503, 429, 200])
    assert b._deliver("/api/events/doors-open", envelope(), max_attempts=4)
    assert len(server.requests) == 3
    assert {body["event_id"] for _, _, body in server.requests} == {"e1"}


def test_client_errors_are_not_retried(cloud):
    server = cloud([401])
    assert b._deliver("/api/events/doors-open", envelope(), max_attempts=4) is False
    assert len(server.requests) == 1


def test_route_missing_on_backend_is_not_retried(cloud):
    server = cloud([404])
    assert b._deliver("/api/events/fridge-tamper", envelope("fridge_tamper"), max_attempts=4) is False
    assert len(server.requests) == 1


def test_rejected_optional_telemetry_field_is_dropped(cloud):
    server = cloud([422, 200])
    payload = envelope("telemetry", temp_c=4.0, fridge_display_temp_c=4.2)
    assert b._deliver("/api/telemetry", payload, max_attempts=1)
    assert "fridge_display_temp_c" not in server.requests[1][2]["data"]
    assert b._dropped_fields == {"fridge_display_temp_c"}


# ----- the watchdog loop is never blocked or broken -------------------------
def test_send_never_raises_on_unserialisable_data(monkeypatch):
    monkeypatch.setattr(b, "BACKEND_ENABLED", True)
    monkeypatch.setattr(b, "_outbox", b.Outbox())
    b.report_doors_open({"duration_s": object()})  # must not raise
    assert b._outbox.pending() == 0


def test_send_does_not_block_when_cloud_is_down(monkeypatch):
    monkeypatch.setattr(b, "BACKEND_ENABLED", True)
    monkeypatch.setattr(b, "_outbox", b.Outbox(max_events=10))
    started = time.monotonic()
    for i in range(1000):  # no sender thread: nothing is ever delivered
        b.send_telemetry({"temp_c": 4.0 + i / 1000, "humidity": None, "alarm": None})
        b.report_doors_open({"duration_s": i, "stocked": True})
    assert time.monotonic() - started < 2.0
    assert b._outbox.pending() == 11  # 10 newest events + only the latest reading


def test_outbox_keeps_events_and_newest_telemetry_apart():
    box = b.Outbox(max_events=2)
    box.put_telemetry("/api/telemetry", {"n": 1})
    box.put_event("/a", {"n": 1})
    box.put_telemetry("/api/telemetry", {"n": 2})
    box.put_event("/b", {"n": 2})
    box.put_event("/c", {"n": 3})  # full: drops the oldest event
    events = [box.get("event", timeout=0) for _ in range(3)]
    assert [(e[0], e[2]) for e in events[:2]] == [("/b", b.EVENT_ATTEMPTS), ("/c", b.EVENT_ATTEMPTS)]
    assert events[2] is None
    telemetry = [box.get("telemetry", timeout=0) for _ in range(2)]
    assert telemetry[0] == ("/api/telemetry", {"n": 2}, 1)  # only the newest reading is kept
    assert telemetry[1] is None
    assert box.dropped == 2


def test_pending_telemetry_does_not_block_events():
    box = b.Outbox()
    box.put_telemetry("/api/telemetry", {"n": 1})
    assert box.get("event", timeout=0) is None
    box.put_event("/ack", {})
    assert box.get("event", timeout=0)[0] == "/ack"


def test_sender_thread_survives_crashes(monkeypatch):
    box = b.Outbox()
    calls = []

    def flaky(path, payload, max_attempts, timeout=None):
        calls.append(path)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return True

    monkeypatch.setattr(b, "_outbox", box)
    monkeypatch.setattr(b, "_deliver", flaky)
    monkeypatch.setattr(b.time, "sleep", lambda s: None)
    threading.Thread(target=b._worker, args=("event",), daemon=True).start()
    box.put_event("/first", {})
    box.put_event("/second", {})
    deadline = time.monotonic() + 2
    while len(calls) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert calls == ["/first", "/second"]
