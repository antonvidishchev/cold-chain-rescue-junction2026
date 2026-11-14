# Cloud API contract

Entry point: `app.cloud.api:app` (independent of the legacy SQLite app). All routes below are under `/api`. FastAPI's `/docs` and `/openapi.json` describe the JSON endpoints; the bounded multipart image upload is detailed here because it is parsed manually.

## Authentication and storage

Public GETs require no key. Device GETs and writes require **both** `x-functions-key: <COLDCHAIN_DEVICE_FUNCTION_KEY>` and `x-device-key: <key for that device>`. `COLDCHAIN_DEVICE_KEYS` is a JSON object mapping device IDs to nonempty keys. Operator mutations require `x-functions-key: <COLDCHAIN_OPERATOR_KEY>`. Checks are app-level, use constant-time comparison, and reject missing/empty configured credentials. An anonymous Functions HTTP trigger does **not** authenticate these keys. Operator keys do not substitute for device keys. Do not embed operator/device credentials into a public frontend bundle.

Credentials never come from Table records. Public devices are allowlisted; nested secret-like fields and storage blob names are filtered. Only explicitly synthetic image content/descriptions are public. Do not mark real patient/clinic photographs synthetic.

Production storage uses `STORAGE_ACCOUNT_URL`, the HTTPS **Table** service endpoint, with `DefaultAzureCredential`. `STORAGE_CONNECTION_STRING` is accepted only for local/Azurite endpoints. `COLDCHAIN_TABLE_NAME` defaults to `ColdChain`. There is no in-memory runtime fallback and no SQLite access. Tests must explicitly inject `MemoryStore` through `create_app(store=..., media=...)`.

### Explicit initialization

From `backend`, after configuring environment variables:

```powershell
.venv\Scripts\python.exe -m app.cloud.bootstrap
# Optionally load Values from local.settings.json (existing environment wins):
.venv\Scripts\python.exe -m app.cloud.bootstrap --settings local.settings.json
```

This creates the Table and parent-provided media resources, then calls `bootstrap_demo(store)` (`seed_demo` is an alias). It atomically creates individual seed records and a tiny initialization/revision record, and never overwrites existing domain data. Neither application import nor API requests seed clinics. Provisioning identity needs create permissions; normal runtime identities should have only the necessary data permissions.

Seeds are fictional Helsinki (`fridge-a`), Espoo (`fridge-b`), Tampere (`clinic-c`), Vantaa (`clinic-vantaa`), Oulu (`clinic-oulu`). Device IDs are `unoq-fridge-a`, `unoq-fridge-b`, `unoq-clinic-c`, `unoq-clinic-vantaa`, `unoq-clinic-oulu`; clinic IDs are lowercase city names. Old location/device IDs and four product IDs remain usable. `clinic-c` has a 2–5°C configured range so the legacy PCR stock can be relocated. Four stock lots start at `fridge-a`, one at `fridge-b`.

## Read endpoints

| Method/path | Parameters | Response |
|---|---|---|
| GET `/health` | — | `{ok:true,storage:"azure-tables"}`; process health, not a storage connectivity probe |
| GET `/products` | — | Product array: id, name, min_c, max_c, max_excursion_minutes, notes |
| GET `/inventory`, `/clinics` | — | Location array including stock with embedded products, devices, used/free_units, effective_range, stock_present, live temperature/power/alarm state |
| GET `/devices` | — | Sanitized device array: id, location_id, clinic_id, last_seen, last_seq, silenced, status and observed/registered timestamps |
| GET `/readings` | Optional `location_id`, `device_id`, `limit` (1–1000, default 300), UTC `since`/`until` | Default last 24 hours; explicit window at most seven days. Latest matching readings returned chronologically; fields id, device_id, location_id, clinic_id, ts, observed_at, temp_c, alarm_active, seq, event_id, received_at, stale |
| GET `/alerts` | Optional `status` | Alerts newest first; open/acknowledged/resolved |
| GET `/alerts/{id}` | — | Single alert including protocol, checklist and recovered_at |
| GET `/alerts/{id}/checklist` | — | Checklist item array |
| GET `/alerts/{id}/timeline` | — | Timeline events for that alert |
| GET `/timeline` | Optional location_id, limit (1–1000, default 300) | Newest-first incident/recovery/action/transfer events |
| GET `/transfers` | — | Newest-first proposed/approved transfer plans |
| GET `/images` | Optional device_id | Sanitized image metadata array |
| GET `/images/{id}` | — | id, device_id, status, created_at, updated_at, observed_at, synthetic, description (description null for non-synthetic images) |
| GET `/images/{id}/content` | — | JPEG bytes only when record synthetic=true; 404 for private/unknown images; 503 if blob unavailable |

Public reads expose fictional demo inventory and status; they are not suitable for sensitive real-world deployments without additional read authorization. Image IDs are opaque strings; legacy alert/stock/command/transfer IDs remain JSON integers.

## Device operations

### Temperature

POST `/telemetry` (legacy) or `/telemetry/temperature` (alias), both with device authentication:

```json
{"device_id":"unoq-fridge-a","clinic_id":"helsinki","event_id":"boot-12-reading-100","observed_at":"2026-11-14T10:00:00Z","temperature_c":4.5,"seq":100,"alarm_active":false}
```

`device_id` and either `temp_c` or `temperature_c` required. `ts` is the legacy alias for `observed_at`; if both are supplied they must agree. Likewise supplied temperature aliases must agree. Optional `location_id`, `sensor_id`, `firmware_version`, `battery_percent` (0–100). Extra fields are rejected. Metadata fields are validated and retained with event deduplication but are not all exposed in readings. IDs and metadata strings are bounded to 128 characters. Temperatures must be finite. Observed times require explicit UTC offset (`Z` or `+00:00`), cannot be more than five minutes in the future; absent time uses server time. Device/clinic/location mismatches are rejected.

Response: `{ok:true,alarm_state:"NORMAL",duplicate:false,stale:false}`. `event_id` is optional for legacy compatibility but strongly recommended: duplicate identical normalized payloads are acknowledged without adding readings or replaying actions; reuse with changed payload returns 409. Event IDs are scoped to a device across temperature/status events. Older/equal observations remain in reading history but do not replace latest values or trigger retrospective incidents. Duplicate delivery does not refresh last_seen.

### Watchdog envelopes (cloud app only)

The merged `device/coldchain-watchdog/python/backend_stub.py` payloads are supported by the current Azure cloud app. **The stub currently sends no authentication headers. The device developer must add both `x-functions-key` and `x-device-key` described above before enabling delivery.** Device files and the legacy `app.main` SQLite application are unchanged; these routes are not added to the legacy app.

Every route below requires device authentication and an envelope:

```json
{"device_id":"unoq-fridge-a","event":"doors_open","ts":"2026-11-14T10:00:00Z","data":{"duration_s":15,"stocked":true}}
```

| POST path | Exact `event` | Required `data` |
|---|---|---|
| `/events/unfreeze-allowed` | `unfreeze_allowed` | `{}` |
| `/notifications/operator` | `unfreeze_check_required` | `{stocked_items:[product IDs],units:integer}` |
| `/events/power-outage` | `power_outage` | `{protocol:"P1".."P4",window_minutes:number,limiting_medicine:product ID,reachable_clinics:[{id,name,phone:null or string,drive_minutes:number}],inventory:[{id,quantity}]}` |
| `/events/doors-open` | `doors_open` | `{duration_s:number,stocked:boolean}` |
| `/inventory/sync` | `inventory_changed` | `{inventory:[{id,quantity}]}` (empty array accepted) |
| `/telemetry` | `telemetry` | `{temp_c:number,humidity?:number or null,alarm?:string or null}` |

The existing flat `/telemetry` and `/telemetry/temperature` contracts remain supported; only `/telemetry` accepts nested envelopes. Optional humidity/alarm, including explicit null values, are retained in journal `data`. Alarm text is a device report, not a substitute for backend temperature assessment.

Envelope `ts` is required and uses the same explicit-UTC/five-minute future tolerance as flat telemetry. Event/route mismatch, extra fields, missing required data, non-finite numbers, nonnumeric/coerced values and duplicate product IDs are rejected (422). IDs are 1–128 characters; names 1–200, phone up to 64, alarm up to 128; arrays up to 100 items; complete envelopes up to 12,000 bytes in UTF-8 and escaped JSON form. Quantities/units are nonnegative integers up to 1 billion. Durations are nonnegative (minutes up to 525,600; seconds up to 31,536,000); temperature −273.15–1000°C and humidity 0–100%. Clinic phone is optional. These are transport bounds, **not clinical safety limits**.

Optional `event_id` is device-scoped. When omitted, a stable SHA-256 ID is derived from device ID, event type, and normalized UTC timestamp. Retry the same envelope/timestamp: identical replay returns `duplicate:true`, with no additional incident, timeline, reading or notification; changed data under the same ID returns 409. Persisted journal and changes commit atomically using the existing repository transaction/outbox. Older/equal observations remain auditable (`stale:true`) but do not replace snapshots/status or trigger retrospective incidents/notifications. Non-telemetry watchdog events each add one timeline entry, including stale reports. Duplicate delivery does not refresh last_seen.

`doors_open` creates a `DOORS_OPEN` alert and notification; `unfreeze_check_required` creates a warning notification; `unfreeze_allowed` records a device-reported timeline event, not backend authorization to unfreeze. Power outage uses backend **Case 25** (`POWER_LOSS`, `protocol:25`). Device P1–P4 is retained separately as `device_reported_protocol` and `device_reported_assessment`, with `assessment_source:device_unverified` and `clinical_safety_certified:false`. Device window/clinic suggestions never certify medicines safe and never cause outbound clinic calls or automatic transfers. Operators must independently assess stock and applicable product guidance.

Public reads:

- GET `/events?device_id=...&location_id=...&limit=300`: newest-first journal array, optional exact filters, limit 1–1000. Includes id, device_id, location_id, clinic_id, event/event_type, ts, received_at, data and result; internal retry payload/fingerprint are omitted and nested secret-like fields sanitized. Older flat retry records without journal metadata may lack these fields.
- GET `/devices/{id}/inventory`: latest accepted `DeviceInventory` snapshot with inventory, observed `stock_present`, ts, received_at, device/location/clinic IDs and `canonical_stock_updated:false`; 404 for unknown devices or no sync. Committed outbox data remains readable during projection recovery.

Device inventories are independent immutable snapshots with an atomically updated latest pointer. Device catalogue IDs only partly overlap backend IDs, and `{id,quantity}` lacks storage constraints and capacity units. Therefore sync **does not change canonical StockItems, capacity, thresholds, transfers, camera observations or canonical config `stock_present`**. Dashboard code should display snapshot `stock_present` as device-observed only. Empty sync is persisted, not silently ignored. Canonical transfer stock remains unchanged until an explicit validated catalogue/storage/capacity mapping exists. Snapshot, journal and pending notification records survive projector restarts via the durable outbox.

### Smart-fridge and knob events (latest device contract)

The authenticated watchdog envelope also supports:

- POST `/events/fridge-tamper`, event `fridge_tamper`: `sensor_temp_c`,
  `fridge_display_temp_c`, signed `mismatch_c` (display minus sensor), `fridge_mode`
  (`normal` or `defrost`), `fridge_power_w`, unique `stocked_items`, and `code:"H1"`.
  Creates/annotates a TAMPER incident with protocol H1; the report is device testimony,
  not proof of a cyberattack.
- POST `/events/alarm-ack`, event `alarm_acknowledged`: nullable `alarm_kind`
  (`power_outage`, `fridge_tamper`, `unfreeze`), nullable `code` (P1–P4/H1), `doors`,
  and `acknowledged_by:"knob"`. Acknowledges matching active incidents at that device's
  location. Door-only gestures may have null kind/code.
- POST `/events/alarm-resolved`, event `alarm_resolved`: non-null `alarm_kind`, nullable
  `code`, `acknowledged_at` (Unix seconds or null), and `resolved_by:"knob"`.
  Records `device_resolved_at/by` on matching incidents and an audit event. **Does not
  set recovered_at, restore power, certify stock safety, or close measured alarms.**
  Unfreeze events without a corresponding incident remain visible in event history.

Nested telemetry accepts optional `fridge_display_temp_c`; readings retain it and
`humidity`. Only fresh telemetry updates the clinic's `reported_temp_c` and
`reported_temp_at`. Inventory sync accepts an optional unique `transferred` item
list and preserves it in the device snapshot; it does not perform canonical stock
transfers or invent a destination. Existing flat telemetry remains supported.

The device's `/camera/fridge_*.jpg` stills are local simulation assets, not uploaded
camera events. They do not appear in the cloud image API until the device developer
uploads JPEG bytes through `/telemetry/images`. The public dashboard does not fetch
local device URLs or fabricate Foundry descriptions.

### Status

POST `/telemetry/status`:

```json
{"device_id":"unoq-fridge-a","clinic_id":"helsinki","event_id":"power-1","observed_at":"2026-11-14T10:00:00Z","status":"power_outage","message":"Supply interrupted"}
```

Required `device_id`, status in `nominal|overheat|power_outage|failure`. Optional clinic_id, location_id, event_id, observed_at/ts, message (max 1000). Same auth, UTC, deduplication and stale-event rules as temperature. Response matches temperature. Explicit power outage creates a `POWER_LOSS` incident with numeric `protocol:25`. Nominal status recovers status incidents; it does not automatically recover measured temperature incidents.

### Config, heartbeat and commands

- GET `/devices/{id}/config`: returns device_id, location_id, clinic_id, min_c, max_c, grace_seconds=0, stock_present, silenced, offline_seconds. Effective product thresholds narrow location thresholds.
- GET `/devices/{id}/commands`: pending, unexpired command array. **Fetching does not consume commands.** Records include integer id, device_id, command, created_at, expires_at, status, delivered, acknowledged_at.
- POST `/devices/{id}/heartbeat`: empty body or `{ "clinic_id":"helsinki" }`; updates last_seen, recovers offline incident, returns `{ok,device_id,last_seen,commands:[...]}`. Heartbeat is not temperature or status recovery evidence.
- POST `/devices/{id}/commands/{command_id}/ack`: no body required; returns acknowledged command. Repeated ACK is idempotent, even after its original expiry. Unacknowledged expired commands return 409. Cross-device command IDs return 404. `silence`/`unsilence` ACK updates device silenced state.

### Images

POST `/telemetry/images`: bounded `multipart/form-data`; both device headers required. Fields:

- `device_id` required, optional `clinic_id` and `location_id` must match.
- Exactly one `image` or `file` part with content type `image/jpeg` and valid JPEG bytes.
- Optional event_id (max 128), observed_at (UTC), synthetic (`true` or `false`, defaults false).

Default JPEG byte limit 5 MiB, pixel limit 12,000,000; multipart overhead capped at 64 KiB. Header, format, dimensions and complete JPEG decoding are checked. Too large/empty returns 413; wrong MIME returns 415; invalid JPEG/time/association returns 422. The function key is verified before parsing; device key checked after the bounded form identifies the device. Request form supports at most one file and ten fields.

Response `{ok:true,id:"...",image_id:"...",status:"pending",duplicate:false}`. Record kind is exactly `ImageAnalyses`; blob_name is id + `.jpg`. Record exists before upload/queue, preventing event ID reassignment to different bytes. Duplicate event IDs with different bytes/synthetic flag/explicit timestamp return 409. Failed upload/enqueue returns 503 and leaves pending for retry/timer recovery; retrying the same event ID safely reattempts upload/enqueue. The parent worker owns processing/completed/failed/terminal retry behavior. Queue is at-least-once; processing uses conditional claims.

## Operator mutations

All endpoints in this section require the **operator** function key.

| Method/path | JSON body | Response/behavior |
|---|---|---|
| POST `/devices/{id}/commands` | `{command:"silence\|unsilence\|test_alarm\|capture_image",expires_at?:"UTC timestamp"}` | Queues and returns command. Default expiry 300 seconds. Unknown command 400; nonfuture/non-UTC expiry 422 |
| POST `/alerts/{id}/ack` | `{by:"Pharmacist"}` | Records acknowledgement, queues silence at location, returns alert. Repeat does not queue again |
| POST `/alerts/{id}/resolve` | none | Requires observed recovery or returns 409; sets resolved; repeat idempotent |
| PATCH or POST `/alerts/{id}/checklist/{item_id}` | `{by:"Pharmacist",done:true}` | Updates checklist and timeline; returns alert. Item IDs inspect/protect/verify |
| POST `/transfers/propose` | `{source_location_id:"fridge-a"}` | Deterministic plan with moves/unplaced/rationale; no inventory mutation yet |
| POST `/transfers/{id}/approve` | `{by:"Pharmacist"}` | Revalidates stock, target power, capacity and product range, then atomically moves all proposed stock immediately. Sets approved_by/at/status; repeat returns 409 |
| POST `/sim/power` | `{location_id:"fridge-a",on:false}` | Sets power, evaluates protocol 25 and returns location |
| POST `/sim/fridge-report` | `{location_id:"fridge-a",temp_c:4.0}` (nullable) | Sets claimed temperature, evaluates discrepancy, returns location |
| POST `/sim/camera` | `{location_id:"fridge-a",stock_present:false}` (nullable) | Sets synthetic stock signal (null derives from inventory), returns location |

Actor strings have length 1–200. Transfer approval is immediate **simulated** inventory movement, not a claim that physical shipping completed. It does not automatically recover temperature or power incidents. There is no cloud stock CRUD endpoint beyond transfer movement, matching the existing inventory read contract.

## Incident rules and outbox

Defaults: location +2 to +8°C, stricter stocked product intersection applies (initial fridge-a is +2 to +6°C due to PCR reagent). Two distinct consecutive out-of-range observations produce EXCURSION. A safe reading marks recovery without changing acknowledgement/status. Rise >=2°C over a covered 300-second window produces RAPID_RISE; interpolation at the boundary is permitted, but a sampling gap greater than the window rejects coverage. An explicit reported-vs-measured discrepancy >=2°C with stock present produces TAMPER. Status messages produce POWER_LOSS/OVERHEAT/FAILURE. `check_offline(store, now=None)` checks last_seen or initial registered_at against 90 seconds; heartbeat/telemetry recover OFFLINE. No previous heartbeat is not equivalent to permanent health: never-seen devices age from registration.

Open/acknowledged incidents are deduplicated until recovery. Acknowledgement is ownership, not proof of recovery. Repeated readings/statuses do not emit duplicate incident notifications. Alarm states prioritize POWER_LOSS, FAILURE, OFFLINE, OVERHEAT, EXCURSION, RAPID_RISE, TAMPER, then NORMAL. These extend the legacy uppercase states.

New incidents atomically append a domain outbox entry. It is projected create-only into `Notifications` records: id, alert_id, location_id, type, message, created_at, status=pending. Each mutation and timer check retries projection; `CloudService(store).flush_notifications()` can explicitly reconcile after a crash. Parent notifications router/worker owns `/api/push` delivery and subscriptions, independently of the operator/device mutation credentials above.

Configurable positive limits: COLDCHAIN_RISE_C, COLDCHAIN_RISE_WINDOW_SECONDS, COLDCHAIN_OFFLINE_SECONDS, COLDCHAIN_CONSECUTIVE_READINGS, COLDCHAIN_IMAGE_MAX_BYTES, COLDCHAIN_IMAGE_MAX_PIXELS, COLDCHAIN_COMMAND_TTL_SECONDS. COLDCHAIN_MIN_C/MAX_C control bootstrap location ranges; changing them does not rewrite already-bootstrapped locations. These cloud settings ignore legacy COLDCHAIN_GRACE_SECONDS/SQLite environment settings.

## Concurrency, limits and compatibility caveats

- **One Table entity per logical record. No whole-dataset aggregate.** Locations, Devices, Products, Stock, Alerts, Commands, Transfers, Events, Timeline, Outbox and the tiny DomainMeta revision row share a transactional partition. Row keys combine hashed kind prefix and hashed logical key; kind-prefix range queries avoid scanning unrelated transactional records. Readings, ImageAnalyses and Notifications each use separate kind partitions. Arbitrary logical keys remain safe.
- Core changes commit through Azure `submit_transaction`: at most 100 entity operations and a conservative 3.5-MB serialized payload budget below the service's 4-MiB batch limit. Every existing record is ETag-conditional. The tiny revision row serializes decisions involving multiple records; it contains only id, revision and numeric ID counter, never dataset arrays. Transfer approval updates the plan and every moved stock entity in one batch, so retries cannot partially move stock. Eight collision retries then 409. Oversized batches fail explicitly rather than partially apply.
- Telemetry inserts an individual event-deduplication record and a durable Outbox row in the same transaction as device/location/incident updates. Projection creates the individual Readings row in its own partition and removes the outbox row only after success. Notifications use the same pattern. A crash between operations is recovered create-only on retry/timer; histories are not lost or appended twice. Clients should retry with the same event_id after transient projection errors.
- Each device keeps a bounded recent rule-evaluation window (at most 1024 samples under default settings), not full history. Coverage is retained for the five-minute rise rule and prior boundary sample; exceptionally dense streams that evict coverage do not falsely trigger the rise rule. Raw history and deduplication events stay in individual entities. Tests ingest 21,600 readings: three days at 7,200 readings/day across five devices, preserving first-day deduplication while device/meta record sizes remain bounded.
- Individual records, not datasets, have a defensive 420,000-serialized-ASCII-character cap (840,000 UTF-16 bytes plus entity overhead). Each property chunk is at most 30,000 ASCII characters/60,000 UTF-16 bytes, below Azure's 64-KiB string property limit. Ordinary telemetry rows are far smaller. No silent retention eviction is implemented; storage consumption grows by individual rows and requires an operational lifecycle policy for long-term production use.
- No application-level per-client rate limiter is implemented. Apply authenticated gateway/body/abuse limits before public deployment. Readings use server-side device/location/time predicates, a 24-hour default window and a seven-day maximum explicit window. Table secondary-property queries may still scan the reading partition; date-sharded partitions/indexes are a future high-volume optimization. Other lists are currently unpaginated. The shared transactional revision row favors correctness at demo-scale throughput rather than claiming unlimited write scaling.
- `MemoryStore` and `AzureTableStore` expose get/list/create/put/delete; get/list return versioned dicts. Existing `put` requires the versioned dict read from the store, not a newly constructed plain dict. Re-read after a successful put. `compare_and_swap(kind,key,expected,replacement)` supports atomic cross-worker claims; expected may be a dict snapshot or versioned record. Direct create is create-if-absent. Azure keys are SHA-256 encoded, so arbitrary logical IDs never become invalid Table keys.
- IDs remain stable for the legacy demo locations, but the clinic count is now five, addresses/names are fictional, command polling no longer consumes commands, alert resolution requires recovery, and older readings no longer overwrite latest state. There is no WebSocket broadcast endpoint in this cloud app; poll public reads. No API is added to register arbitrary devices or modify credentials.
- Legacy REST paths already include `/api`; no unprefixed aliases are introduced. Error convention: 401 authentication, 404 unknown record/private content, 409 conflict/state precondition, 413 size, 415 format, 422 payload, 503 media dependency failure. Infrastructure/individual-record/batch-capacity failures can surface as 500 and require operator investigation.

## Validation

Run without the legacy test conftest (which otherwise configures SQLite and creates external temporary files):

```powershell
.venv\Scripts\python.exe -m pytest --noconftest -p no:cacheprovider tests\test_cloud_api.py tests\test_cloud_store.py -q
```

Tests cover explicit seeding, default thresholds, both key layers, operator protection, public sanitization, event replay, late observations, covered rise windows, recovery versus acknowledgement, command expiry/non-consuming polls/idempotent ACK, atomic concurrent deduplication, transfer revalidation/rollback, bounded image validation, queue retries, safe Table keys/property chunks and ETag conflicts. The 21,600-reading test verifies three days across five devices without dataset/entity growth limits. Store tests also prove all-or-nothing multi-record conflicts and crash-replayable projections. Set `COLDCHAIN_TEST_AZURITE` to an isolated local emulator connection to run the opt-in actual Table transaction/bootstrap/ingestion/transfer test; parent-owned integration tests additionally cover Blob/Queue and worker operations. No live Azure resources are required.

Azure reference: [TableClient Python API](https://learn.microsoft.com/python/api/azure-data-tables/azure.data.tables.tableclient), including conditional ETag update semantics.
