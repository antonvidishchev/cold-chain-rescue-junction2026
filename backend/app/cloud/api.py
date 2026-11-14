"""Public cloud reads with explicit operator/device authorization on writes."""

import hashlib
import importlib
import io
import warnings
from datetime import timedelta
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.cloud.auth import require_device, require_operator
from app.cloud.service import CloudService, observed, stamp, utcnow
from app.cloud.settings import Settings
from app.cloud.store import ConflictError, get_store
from app.cloud.watchdog import (AlarmAck, AlarmResolved, DoorsOpen, FridgeTamper,
                                InventorySync, PowerOutage, Telemetry,
                                UnfreezeAllowed, UnfreezeCheck, ingest_watchdog)


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class TemperatureIn(Payload):
    device_id: str = Field(min_length=1, max_length=128)
    clinic_id: str | None = Field(default=None, max_length=128)
    location_id: str | None = Field(default=None, max_length=128)
    event_id: str | None = Field(default=None, min_length=1, max_length=128)
    observed_at: str | None = None
    ts: str | None = None
    temp_c: float | None = None
    temperature_c: float | None = None
    seq: int = Field(default=0, ge=0)
    alarm_active: bool = False
    sensor_id: str | None = Field(default=None, max_length=128)
    firmware_version: str | None = Field(default=None, max_length=128)
    battery_percent: float | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def temperature_alias(self):
        if self.temp_c is None and self.temperature_c is None:
            raise ValueError("temp_c or temperature_c is required")
        if self.temp_c is not None and self.temperature_c is not None and self.temp_c != self.temperature_c:
            raise ValueError("Conflicting temperature fields")
        self.temp_c = self.temp_c if self.temp_c is not None else self.temperature_c
        if self.ts and self.observed_at and observed(self.ts) != observed(self.observed_at):
            raise ValueError("Conflicting observed timestamps")
        return self


class StatusIn(Payload):
    device_id: str = Field(min_length=1, max_length=128)
    clinic_id: str | None = Field(default=None, max_length=128)
    location_id: str | None = Field(default=None, max_length=128)
    event_id: str | None = Field(default=None, min_length=1, max_length=128)
    observed_at: str | None = None
    ts: str | None = None
    status: Literal["nominal", "overheat", "power_outage", "failure"]
    message: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def timestamps(self):
        if self.ts and self.observed_at and observed(self.ts) != observed(self.observed_at):
            raise ValueError("Conflicting observed timestamps")
        return self


class ActorIn(Payload):
    by: str = Field(min_length=1, max_length=200)


class CommandIn(Payload):
    command: str
    expires_at: str | None = None


class HeartbeatIn(Payload):
    clinic_id: str | None = Field(default=None, max_length=128)


class ProposeIn(Payload):
    source_location_id: str


class ChecklistIn(ActorIn):
    done: bool


class PowerIn(Payload):
    location_id: str
    on: bool


class FridgeReportIn(Payload):
    location_id: str
    temp_c: float | None


class CameraIn(Payload):
    location_id: str
    stock_present: bool | None


class LazyStore:
    """Expose app.state.store without opening Azure connections during import."""

    def __getattr__(self, name):
        return getattr(get_store(), name)


DEVICE_FIELDS = {"id", "device_id", "location_id", "clinic_id", "last_seen", "last_seq", "silenced", "status", "registered_at", "last_temperature_at", "last_status_at"}
PRIVATE_KEYS = {"key", "device_key", "api_key", "operator_key", "function_key", "connection_string", "password", "secret", "token", "credential", "credentials", "device_keys", "blob_name", "sas_url", "endpoint"}


def public(value):
    if isinstance(value, dict):
        return {key: public(item) for key, item in value.items()
                if key.lower() not in PRIVATE_KEYS and not any(part in key.lower() for part in ("secret", "password", "credential", "token", "connection_string"))
                and not key.lower().endswith("_key")}
    if isinstance(value, list):
        return [public(item) for item in value]
    return value


def _public_device(device):
    return {key: value for key, value in device.items() if key in DEVICE_FIELDS}


def create_app(store=None, media=None) -> FastAPI:
    application = FastAPI(title="ColdChain Cloud API", version="1.0.0")
    application.state.store = store if store is not None else LazyStore()
    application.state.media = media

    def service() -> CloudService:
        return CloudService(application.state.store)

    def media_service():
        return application.state.media if application.state.media is not None else importlib.import_module("app.cloud.media")

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        # Echoing rejected input can leak secrets or fail JSON encoding on NaN/Infinity.
        errors = [{key: error[key] for key in ("type", "loc", "msg")} for error in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": errors})

    @application.exception_handler(ConflictError)
    async def concurrency_error(request: Request, exc: ConflictError):
        return JSONResponse(status_code=409, content={"detail": "Concurrent update; retry request"})

    @application.get("/api/health")
    def health():
        return {"ok": True, "storage": "azure-tables"}

    @application.get("/api/products")
    def products():
        return public(list(service().state()["products"].values()))

    @application.get("/api/inventory")
    @application.get("/api/clinics")
    def inventory():
        rows = service().inventory()
        for row in rows:
            row["devices"] = [_public_device(d) for d in row["devices"]]
        return public(rows)

    @application.get("/api/devices")
    def devices():
        return [_public_device(device) for device in service().state()["devices"].values() if device.get("active", True)]

    @application.get("/api/devices/{device_id}/config")
    def config(device_id: str, request: Request):
        require_device(request, device_id)
        return service().config(device_id)

    @application.get("/api/events")
    def events(device_id: Annotated[str | None, Query(max_length=128)] = None,
               location_id: Annotated[str | None, Query(max_length=128)] = None,
               limit: Annotated[int, Query(ge=1, le=1000)] = 300):
        rows = application.state.store.query("Events", device_id=device_id, location_id=location_id)
        # The retry payload is private implementation detail, not the public journal.
        fields = {"id", "device_id", "location_id", "clinic_id", "event", "event_type", "ts",
                  "received_at", "data", "result"}
        return public([{key: value for key, value in row.items() if key in fields}
                       for row in sorted(rows, key=lambda row: row.get("ts", ""), reverse=True)[:limit]])

    @application.get("/api/devices/{device_id}/inventory")
    def device_inventory(device_id: str):
        return public(service().device_inventory(device_id))

    @application.post("/api/events/unfreeze-allowed")
    def unfreeze_allowed(body: UnfreezeAllowed, request: Request):
        require_device(request, body.device_id)
        return ingest_watchdog(service(), body)

    @application.post("/api/notifications/operator")
    def unfreeze_check(body: UnfreezeCheck, request: Request):
        require_device(request, body.device_id)
        return ingest_watchdog(service(), body)

    @application.post("/api/events/power-outage")
    def power_outage(body: PowerOutage, request: Request):
        require_device(request, body.device_id)
        return ingest_watchdog(service(), body)

    @application.post("/api/events/doors-open")
    def doors_open(body: DoorsOpen, request: Request):
        require_device(request, body.device_id)
        return ingest_watchdog(service(), body)

    @application.post("/api/events/fridge-tamper")
    def fridge_tamper(body: FridgeTamper, request: Request):
        require_device(request, body.device_id)
        return ingest_watchdog(service(), body)

    @application.post("/api/events/alarm-ack")
    def alarm_ack(body: AlarmAck, request: Request):
        require_device(request, body.device_id)
        return ingest_watchdog(service(), body)

    @application.post("/api/events/alarm-resolved")
    def alarm_resolved(body: AlarmResolved, request: Request):
        require_device(request, body.device_id)
        return ingest_watchdog(service(), body)

    @application.post("/api/inventory/sync")
    def inventory_sync(body: InventorySync, request: Request):
        require_device(request, body.device_id)
        return ingest_watchdog(service(), body)

    @application.post("/api/telemetry")
    def telemetry(body: TemperatureIn | Telemetry, request: Request):
        require_device(request, body.device_id)
        if isinstance(body, Telemetry):
            return ingest_watchdog(service(), body)
        return service().ingest(body.model_dump(mode="json", exclude_none=True), "temperature")

    @application.post("/api/telemetry/temperature")
    def temperature(body: TemperatureIn, request: Request):
        require_device(request, body.device_id)
        return service().ingest(body.model_dump(mode="json", exclude_none=True), "temperature")

    @application.post("/api/telemetry/status")
    def status(body: StatusIn, request: Request):
        require_device(request, body.device_id)
        return service().ingest(body.model_dump(mode="json", exclude_none=True), "status")

    @application.get("/api/readings")
    def readings(location_id: str | None = None, device_id: str | None = None,
                 limit: Annotated[int, Query(ge=1, le=1000)] = 300,
                 since: str | None = None, until: str | None = None):
        end = observed(until) if until else utcnow() + timedelta(minutes=5)
        start = observed(since) if since else end - timedelta(days=1, minutes=5)
        if end <= start or end - start > timedelta(days=7):
            raise HTTPException(422, "Reading query window must be positive and at most seven days")
        rows = application.state.store.query("Readings", device_id=device_id, location_id=location_id,
                                             since=stamp(start), until=stamp(end))
        return public(sorted(rows, key=lambda row: row["ts"])[-limit:])

    @application.get("/api/devices/{device_id}/commands")
    def commands(device_id: str, request: Request):
        require_device(request, device_id)
        return service().pending(device_id)

    @application.post("/api/devices/{device_id}/commands", dependencies=[Depends(require_operator)])
    def queue(device_id: str, body: CommandIn):
        return service().queue(device_id, body.command, body.expires_at)

    @application.post("/api/devices/{device_id}/commands/{command_id}/ack")
    def acknowledge_command(device_id: str, command_id: str, request: Request):
        require_device(request, device_id)
        return service().ack_command(device_id, command_id)

    @application.post("/api/devices/{device_id}/heartbeat")
    def heartbeat(device_id: str, request: Request, body: HeartbeatIn | None = None):
        require_device(request, device_id)
        return service().heartbeat(device_id, body.clinic_id if body else None)

    @application.get("/api/alerts")
    def alerts(status: str | None = None):
        rows = [a for a in service().state()["alerts"].values() if status is None or a["status"] == status]
        return public(sorted(rows, key=lambda row: row["created_at"], reverse=True))

    @application.get("/api/alerts/{alert_id}")
    def alert(alert_id: str):
        record = service().state()["alerts"].get(alert_id)
        if record is None:
            raise HTTPException(404, "Alert not found")
        return public(record)

    @application.post("/api/alerts/{alert_id}/ack", dependencies=[Depends(require_operator)])
    def acknowledge(alert_id: str, body: ActorIn):
        return service().alert_action(alert_id, "ack", body.by)

    @application.post("/api/alerts/{alert_id}/resolve", dependencies=[Depends(require_operator)])
    def resolve(alert_id: str):
        return service().alert_action(alert_id, "resolve")

    @application.get("/api/alerts/{alert_id}/checklist")
    def get_checklist(alert_id: str):
        return alert(alert_id)["checklist"]

    @application.patch("/api/alerts/{alert_id}/checklist/{item_id}", dependencies=[Depends(require_operator)])
    @application.post("/api/alerts/{alert_id}/checklist/{item_id}", dependencies=[Depends(require_operator)])
    def update_checklist(alert_id: str, item_id: str, body: ChecklistIn):
        return service().checklist(alert_id, item_id, body.done, body.by)

    @application.get("/api/timeline")
    def timeline(location_id: str | None = None, limit: Annotated[int, Query(ge=1, le=1000)] = 300):
        rows = [row for row in service().state()["timeline"].values() if location_id is None or row["location_id"] == location_id]
        return public(sorted(rows, key=lambda row: row["created_at"], reverse=True)[:limit])

    @application.get("/api/alerts/{alert_id}/timeline")
    def alert_timeline(alert_id: str):
        alert(alert_id)
        return public([row for row in service().state()["timeline"].values() if str(row.get("alert_id")) == alert_id])

    @application.get("/api/transfers")
    def transfers():
        return public(sorted(service().state()["transfers"].values(), key=lambda row: row["created_at"], reverse=True))

    @application.post("/api/transfers/propose", dependencies=[Depends(require_operator)])
    def propose(body: ProposeIn):
        return service().propose(body.source_location_id)

    @application.post("/api/transfers/{plan_id}/approve", dependencies=[Depends(require_operator)])
    def approve(plan_id: str, body: ActorIn):
        return service().approve(plan_id, body.by)

    @application.post("/api/sim/power", dependencies=[Depends(require_operator)])
    def sim_power(body: PowerIn):
        return service().simulate("power", body.model_dump())

    @application.post("/api/sim/fridge-report", dependencies=[Depends(require_operator)])
    def sim_fridge(body: FridgeReportIn):
        return service().simulate("fridge-report", body.model_dump())

    @application.post("/api/sim/camera", dependencies=[Depends(require_operator)])
    def sim_camera(body: CameraIn):
        return service().simulate("camera", body.model_dump())

    @application.post("/api/telemetry/images")
    async def upload(request: Request):
        settings = Settings.load()
        # Authenticate the function key before reading or parsing a multipart body.
        from app.cloud.auth import _matches
        if not _matches(request.headers.get("x-functions-key"), settings.device_function_key):
            raise HTTPException(401, "Valid device function key required")
        if not request.headers.get("content-type", "").lower().startswith("multipart/form-data"):
            raise HTTPException(415, "Expected multipart/form-data")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > settings.image_max_bytes + 65536:
                raise HTTPException(413, "Image request too large")
        request._body = bytes(body)
        async with request.form(max_files=1, max_fields=10, max_part_size=65536) as form:
            device_id = str(form.get("device_id", ""))
            require_device(request, device_id)
            clinic_id = form.get("clinic_id")
            location_id = form.get("location_id")
            service()._location_for(service().state(), device_id, str(clinic_id) if clinic_id else None,
                                    str(location_id) if location_id else None)
            image = form.get("image") or form.get("file")
            if image is None or not hasattr(image, "read") or image.content_type != "image/jpeg":
                raise HTTPException(415, "A JPEG image/file part is required")
            data = await image.read(settings.image_max_bytes + 1)
            if not data or len(data) > settings.image_max_bytes:
                raise HTTPException(413, "JPEG is empty or too large")
            from PIL import Image, UnidentifiedImageError
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("error", Image.DecompressionBombWarning)
                    with Image.open(io.BytesIO(data)) as candidate:
                        if candidate.format != "JPEG" or candidate.width * candidate.height > settings.image_max_pixels:
                            raise ValueError("Invalid JPEG dimensions")
                        candidate.verify()
                    with Image.open(io.BytesIO(data)) as candidate:
                        candidate.load()
            except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
                raise HTTPException(422, "Invalid or oversized JPEG") from exc
            event_id = str(form.get("event_id", ""))
            if len(event_id) > 128:
                raise HTTPException(422, "event_id too long")
            when = stamp(observed(str(form["observed_at"]) if form.get("observed_at") else None))
            synthetic_text = str(form.get("synthetic", "false")).lower()
            if synthetic_text not in {"true", "false"}:
                raise HTTPException(422, "synthetic must be true or false")
            synthetic = synthetic_text == "true"
            identifier = hashlib.sha256(f"{device_id}:{event_id}".encode()).hexdigest() if event_id else uuid4().hex
            digest = hashlib.sha256(data).hexdigest()
            record = {"id": identifier, "device_id": device_id, "status": "pending", "blob_name": identifier + ".jpg",
                "description": None, "created_at": stamp(), "updated_at": stamp(), "observed_at": when,
                "event_id": event_id or None, "synthetic": synthetic, "sha256": digest}
            storage = application.state.store
            created = storage.create("ImageAnalyses", identifier, record)
            if not created:
                record = storage.get("ImageAnalyses", identifier)
                if record["sha256"] != digest or record["synthetic"] != synthetic:
                    raise HTTPException(409, "event_id already used for a different image")
                if form.get("observed_at") and record["observed_at"] != when:
                    raise HTTPException(409, "event_id already used for a different observation")
            if record["status"] == "pending":
                try:
                    media_service().upload_image(identifier, data, "image/jpeg")
                    media_service().enqueue_image(identifier)
                except Exception as exc:
                    # Keep pending state for the timer and idempotent client retry.
                    raise HTTPException(503, "Image saved as pending; retry upload/queue later") from exc
            return {"ok": True, "id": identifier, "image_id": identifier, "status": record["status"], "duplicate": not created}

    def image_record(image_id: str):
        row = application.state.store.get("ImageAnalyses", image_id)
        if row is None:
            raise HTTPException(404, "Image not found")
        return row

    def image_metadata(row):
        fields = {"id", "device_id", "status", "created_at", "updated_at", "observed_at", "synthetic"}
        result = {key: row[key] for key in fields if key in row}
        result["description"] = row.get("description") if row.get("synthetic") is True else None
        return result

    @application.get("/api/images")
    def images(device_id: str | None = None):
        return [image_metadata(row) for row in application.state.store.list("ImageAnalyses")
                if device_id is None or row["device_id"] == device_id]

    @application.get("/api/images/{image_id}")
    def image_analysis(image_id: str):
        return image_metadata(image_record(image_id))

    @application.get("/api/images/{image_id}/content")
    def image_content(image_id: str):
        row = image_record(image_id)
        if row.get("synthetic") is not True:
            raise HTTPException(404, "Public synthetic image not found")
        try:
            data = media_service().read_image(image_id)
        except Exception as exc:
            raise HTTPException(503, "Image content unavailable") from exc
        return Response(data, media_type="image/jpeg", headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "public, max-age=300"})

    from app.cloud.notifications import router as notifications_router
    application.include_router(notifications_router)
    return application


app = create_app()
