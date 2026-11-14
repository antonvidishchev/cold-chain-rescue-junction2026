"""Opt-in integration tests against an isolated Azurite instance, never real Azure."""

import json
import os
from uuid import uuid4

import pytest

from app.cloud import media

pytestmark = pytest.mark.skipif(
    not os.environ.get("COLDCHAIN_TEST_AZURITE"), reason="Set COLDCHAIN_TEST_AZURITE for emulator checks"
)


@pytest.fixture
def emulator(monkeypatch):
    connection = os.environ["COLDCHAIN_TEST_AZURITE"]
    if "127.0.0.1" not in connection or "AccountName=devstoreaccount1;" not in connection:
        pytest.fail("Integration tests only support local Azurite")
    monkeypatch.setenv("STORAGE_CONNECTION_STRING", connection)
    monkeypatch.setenv("IMAGE_CONTAINER", "test-images-" + uuid4().hex)
    monkeypatch.setenv("IMAGE_QUEUE_NAME", "test-analysis-" + uuid4().hex)
    media.blob_service.cache_clear()
    media.queue_client.cache_clear()
    media.initialize_media()
    try:
        yield
    finally:
        media.blob_service().delete_container(os.environ["IMAGE_CONTAINER"])
        media.queue_client().delete_queue()
        media.blob_service.cache_clear()
        media.queue_client.cache_clear()


def test_blob_roundtrip_queue_encoding_and_private_container(emulator):
    image_id = uuid4().hex
    media.upload_image(image_id, b"test-jpeg", "image/jpeg")
    media.upload_image(image_id, b"must-not-overwrite", "image/jpeg")
    assert media.read_image(image_id) == b"test-jpeg"
    props = media.blob_service().get_container_client(os.environ["IMAGE_CONTAINER"]).get_container_properties()
    assert not props.get("public_access")
    media.enqueue_image(image_id)
    message = next(iter(media.queue_client().receive_messages()))
    import base64

    assert json.loads(base64.b64decode(message.content)) == {"image_id": image_id}


def test_table_records_and_optimistic_concurrency(emulator):
    from azure.data.tables import TableServiceClient
    from app.cloud.store import AzureTableStore

    service = TableServiceClient.from_connection_string(os.environ["COLDCHAIN_TEST_AZURITE"])
    name = "Test" + uuid4().hex
    client = service.create_table(name)
    try:
        store = AzureTableStore(client)
        first = {"id": "device/unsafe:key", "temperature": 5.0, "nested": {"ok": True}}
        assert store.create("Readings", first["id"], first)
        assert not store.create("Readings", first["id"], first)
        record = store.get("Readings", first["id"])
        assert record["nested"] == {"ok": True}
        changed = {**record, "temperature": 6.0}
        assert store.compare_and_swap("Readings", first["id"], record, changed)
        assert not store.compare_and_swap("Readings", first["id"], record, changed)
        assert len(store.list("Readings")) == 1
        store.delete("Readings", first["id"])
        assert store.get("Readings", first["id"]) is None
        from datetime import datetime, timezone
        from app.cloud.worker import process_image

        class Inference:
            def read_image(self, image_id):
                return b"synthetic-jpeg"

            def analyze_image(self, data):
                return "Visible demo fridge."

        store.put("ImageAnalyses", "image1", {
            "id": "image1", "status": "pending", "updated_at": datetime.now(timezone.utc).isoformat()
        })
        process_image("image1", store, Inference())
        assert store.get("ImageAnalyses", "image1")["status"] == "completed"
        for index in range(20):
            store.create("Readings", f"reading-{index}", {"id": f"reading-{index}", "temp_c": 5.0})
        assert len(list(client.list_entities())) >= 20, "Telemetry must use independent Table entities"
    finally:
        service.delete_table(name)
        service.close()
