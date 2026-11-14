"""Alarm events must not wait behind a slow telemetry POST."""
import threading
import time
import unittest
from unittest import mock

import backend_stub


class EventsBypassTelemetryTest(unittest.TestCase):
    def test_event_delivered_while_telemetry_in_flight(self):
        box = backend_stub.Outbox()
        telemetry_started = threading.Event()
        release_telemetry = threading.Event()
        event_done = threading.Event()

        def fake_post(path, payload, timeout=backend_stub.HTTP_TIMEOUT):
            if path == "/api/telemetry":
                telemetry_started.set()
                release_telemetry.wait(5)
            else:
                event_done.set()
            return 200, "ok"

        with mock.patch.object(backend_stub, "_outbox", box), mock.patch.object(backend_stub, "_post", fake_post):
            for kind in ("event", "telemetry"):
                threading.Thread(target=backend_stub._worker, args=(kind,), daemon=True).start()
            box.put_telemetry("/api/telemetry", {"event": "telemetry", "data": {}})
            self.assertTrue(telemetry_started.wait(2))
            start = time.monotonic()
            box.put_event("/api/events/alarm-resolved", {"event": "alarm_resolved", "data": {}})
            self.assertTrue(event_done.wait(2), "event blocked behind in-flight telemetry")
            self.assertLess(time.monotonic() - start, 1.0)
            release_telemetry.set()

    def test_first_retry_backoff_is_short(self):
        self.assertLess(backend_stub._backoff(1), 1.1)
        self.assertLessEqual(backend_stub._backoff(20), 30.5)


if __name__ == "__main__":
    unittest.main()
