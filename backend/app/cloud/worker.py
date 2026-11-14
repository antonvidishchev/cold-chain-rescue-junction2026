"""At-least-once image jobs with persisted results and retry recovery."""

import json
import logging
from datetime import datetime, timedelta, timezone

from app.cloud import media

logger = logging.getLogger(__name__)


def now_utc():
    return datetime.now(timezone.utc)


def image_id_from_message(body: bytes) -> str:
    value = json.loads(body.decode("utf-8"))
    image_id = value["image_id"]
    media.blob_name(image_id)
    return image_id


def process_image(image_id: str, store=None, image_io=None) -> None:
    from app.cloud.store import get_store

    store = store if store is not None else get_store()
    image_io = image_io if image_io is not None else media
    record = store.get("ImageAnalyses", image_id)
    if record is None or record.get("status") in {"completed", "dead_letter"}:
        return
    now = now_utc()
    lease = record.get("lease_until")
    if lease and datetime.fromisoformat(lease) > now:
        return
    claimed = {**record, "status": "processing", "lease_until": (now + timedelta(minutes=3)).isoformat(),
               "updated_at": now.isoformat(), "attempts": record.get("attempts", 0) + 1}
    if not store.compare_and_swap("ImageAnalyses", image_id, record, claimed):
        return
    try:
        description = image_io.analyze_image(image_io.read_image(image_id))
    except Exception:
        failed = {**claimed, "status": "failed", "error": "Image analysis failed; retry scheduled",
                  "lease_until": None, "updated_at": now_utc().isoformat()}
        store.compare_and_swap("ImageAnalyses", image_id, claimed, failed)
        logger.warning("Image analysis attempt failed for %s", image_id)
        raise RuntimeError("Image analysis attempt failed") from None
    completed = {**claimed, "status": "completed", "description": description,
                 "error": None, "lease_until": None, "updated_at": now_utc().isoformat()}
    if not store.compare_and_swap("ImageAnalyses", image_id, claimed, completed):
        raise RuntimeError("Image result lost its processing lease")


def mark_poison(image_id: str, store=None) -> None:
    from app.cloud.store import get_store

    store = store if store is not None else get_store()
    record = store.get("ImageAnalyses", image_id)
    if record is not None and record.get("status") != "completed":
        store.compare_and_swap("ImageAnalyses", image_id, record, {
            **record, "status": "dead_letter", "lease_until": None,
            "error": "Image analysis exhausted retries; operator investigation required",
            "updated_at": now_utc().isoformat(),
        })


def recover_images(store=None, image_io=None) -> None:
    from app.cloud.store import get_store

    store = store if store is not None else get_store()
    image_io = image_io if image_io is not None else media
    now = now_utc()
    for record in store.list("ImageAnalyses"):
        if record.get("status") not in {"pending", "processing", "failed"}:
            continue
        updated = datetime.fromisoformat(record["updated_at"])
        if now - updated < timedelta(minutes=5):
            continue
        if record.get("attempts", 0) >= 5:
            mark_poison(record["id"], store)
            continue
        replacement = {**record, "status": "pending", "lease_until": None, "updated_at": now.isoformat()}
        if store.compare_and_swap("ImageAnalyses", record["id"], record, replacement):
            image_io.enqueue_image(record["id"])
