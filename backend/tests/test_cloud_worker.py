from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from app.cloud import media, worker


class Store:
    def __init__(self):
        self.rows = {}

    def get(self, kind, key):
        return deepcopy(self.rows.get((kind, key)))

    def put(self, kind, key, value):
        self.rows[kind, key] = deepcopy(value)

    def list(self, kind):
        return [deepcopy(v) for (k, _), v in self.rows.items() if k == kind]

    def compare_and_swap(self, kind, key, expected, replacement):
        if self.get(kind, key) != expected:
            return False
        self.put(kind, key, replacement)
        return True


class Images:
    def __init__(self):
        self.calls = 0
        self.fail = False
        self.queued = []

    def read_image(self, image_id):
        return b"synthetic-image"

    def analyze_image(self, data):
        self.calls += 1
        if self.fail:
            raise ValueError("sensitive response must not be stored")
        return "The fridge door appears open."

    def enqueue_image(self, image_id):
        self.queued.append(image_id)


def pending(store):
    store.put("ImageAnalyses", "image1", {"id": "image1", "status": "pending",
              "updated_at": datetime.now(timezone.utc).isoformat()})


def test_analysis_persisted_and_duplicate_delivery_is_noop():
    store, images = Store(), Images()
    pending(store)
    worker.process_image("image1", store, images)
    worker.process_image("image1", store, images)
    assert images.calls == 1
    assert store.get("ImageAnalyses", "image1")["description"] == "The fridge door appears open."
    assert store.get("ImageAnalyses", "image1")["status"] == "completed"


def test_failure_retries_and_poison_does_not_overwrite_success():
    store, images = Store(), Images()
    pending(store)
    images.fail = True
    with pytest.raises(RuntimeError, match="attempt failed"):
        worker.process_image("image1", store, images)
    result = store.get("ImageAnalyses", "image1")
    assert result["status"] == "failed"
    assert "sensitive" not in result["error"]
    images.fail = False
    worker.process_image("image1", store, images)
    worker.mark_poison("image1", store)
    assert store.get("ImageAnalyses", "image1")["status"] == "completed"


def test_poison_is_terminal():
    store, images = Store(), Images()
    pending(store)
    worker.mark_poison("image1", store)
    worker.process_image("image1", store, images)
    assert images.calls == 0
    assert store.get("ImageAnalyses", "image1")["status"] == "dead_letter"


def test_stale_upload_requeued_but_fresh_and_finished_not_requeued():
    store, images = Store(), Images()
    pending(store)
    worker.recover_images(store, images)
    assert not images.queued
    row = store.get("ImageAnalyses", "image1")
    row["updated_at"] = (datetime.now(timezone.utc) - timedelta(minutes=6)).isoformat()
    store.put("ImageAnalyses", "image1", row)
    worker.recover_images(store, images)
    worker.recover_images(store, images)
    assert images.queued == ["image1"]


def test_active_lease_skips_duplicate_and_expired_lease_recovers():
    store, images = Store(), Images()
    pending(store)
    row = store.get("ImageAnalyses", "image1")
    row.update(status="processing", lease_until=(datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat())
    store.put("ImageAnalyses", "image1", row)
    worker.process_image("image1", store, images)
    assert images.calls == 0
    row["lease_until"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    store.put("ImageAnalyses", "image1", row)
    worker.process_image("image1", store, images)
    assert images.calls == 1


def test_recovery_stops_after_five_failed_attempts():
    store, images = Store(), Images()
    pending(store)
    row = store.get("ImageAnalyses", "image1")
    row.update(status="failed", attempts=5,
               updated_at=(datetime.now(timezone.utc) - timedelta(minutes=6)).isoformat())
    store.put("ImageAnalyses", "image1", row)
    worker.recover_images(store, images)
    assert not images.queued
    assert store.get("ImageAnalyses", "image1")["status"] == "dead_letter"


def test_message_rejects_paths():
    with pytest.raises(ValueError):
        worker.image_id_from_message(b'{"image_id":"../../secret"}')


def test_foundry_requires_explicit_deployment(monkeypatch):
    monkeypatch.delenv("FOUNDRY_VISION_DEPLOYMENT", raising=False)
    with pytest.raises(RuntimeError, match="Configure"):
        media.analyze_image(b"jpeg")


def test_foundry_request_uses_image_and_identity(monkeypatch):
    from types import SimpleNamespace

    captured = {}

    class Client:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.chat = SimpleNamespace(completions=self)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="Visible bottles."))])

    monkeypatch.setenv("FOUNDRY_ENDPOINT", "https://example.openai.azure.com")
    monkeypatch.setenv("FOUNDRY_VISION_DEPLOYMENT", "vision-deployment")
    monkeypatch.setattr(media, "OpenAI", Client)
    monkeypatch.setattr(media, "credential", lambda: object())
    monkeypatch.setattr(media, "get_bearer_token_provider", lambda *args: "test-token-provider")
    assert media.analyze_image(b"jpeg") == "Visible bottles."
    assert captured["base_url"] == "https://example.openai.azure.com/openai/v1/"
    assert captured["model"] == "vision-deployment"
    assert captured["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
