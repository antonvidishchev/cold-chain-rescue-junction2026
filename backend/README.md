# Cloud backend

The Azure entry point is `function_app.py`, which hosts `app.cloud.api:app` through
Azure Functions' ASGI adapter. The existing `app.main:app` remains the unchanged
SQLite/WebSocket prototype. Neither frontend nor the device application is modified.
Use the cloud entry point for the new APIs; running the old entry point does not
activate Table Storage or the new authentication rules.

## Local development (PowerShell)

Prerequisites: Python 3.13, Functions Core Tools v4, uv, and Azurite. Node.js is only
needed to run the npm-installed Azurite/frontend tools. No Docker is required.

```powershell
Set-Location backend
uv sync --locked
Copy-Item local.settings.example.json local.settings.json
```

Edit the ignored `local.settings.json`. Set nonempty random values for
`COLDCHAIN_DEVICE_FUNCTION_KEY` and `COLDCHAIN_OPERATOR_KEY`, plus a JSON object
mapping registered device IDs to independent random keys in `COLDCHAIN_DEVICE_KEYS`.
Do not copy these keys into a frontend environment variable or commit them.
The example deliberately contains no functional credentials; writes fail closed.
Functions Core Tools loads `local.settings.json`; plain Python/uvicorn does not.

Start Azurite in another terminal, storing emulator data outside source control:

```powershell
azurite --location "$env:TEMP\coldchain-azurite"
```

With Azurite running, explicitly create application storage and fictional clinic/device
data (settings are loaded only by this command):

```powershell
uv run python -m app.cloud.bootstrap --settings local.settings.json
```

Then activate the environment and start Functions:

```powershell
.\.venv\Scripts\Activate.ps1
$env:PY_PYTHON = "3.13"
$env:languageWorkers__python__defaultExecutablePath = "$PWD\.venv\Scripts\python.exe"
func start
```

`GET http://localhost:7071/api/health` is public. The Functions adapter exposes the
existing `/api` prefix; `host.json` sets the host route prefix to empty to avoid
`/api/api`. The hosted HTTP function is anonymous because selected reads are public.
**Protected requests are checked by application middleware/dependencies**, not by
Functions host authentication. Set header values to match the configured application
keys; creating a host key alone does not configure these checks. Local Functions
hosting also does not enforce host-level keys by default.

## Access boundaries

- Synthetic demo clinic data, temperature history, incidents, transfer plans, and
  image descriptions/content are publicly readable. Do not upload patient data.
- Device ingestion and configuration/command retrieval require both `x-device-key`
  and `x-functions-key` matching the configured device key and device function key.
- Operator writes require `x-functions-key` matching `COLDCHAIN_OPERATOR_KEY`.
  A device credential cannot approve a transfer or change simulator state.
- Browser-push opt-in is public but grants no operator access.
- Keep Blob Storage private; only validated image IDs are served by the public
  image API. Public image content is still public data, despite private storage.
- Preserve operator acknowledgement separately from incident resolution. The
  protocol rules are simulation defaults, not medical storage guidance.

The old SQLite prototype is not secured by these new checks and must not be
published as the production/cloud entry point.

## Storage and managed identity

Local: `STORAGE_CONNECTION_STRING=UseDevelopmentStorage=true` with Azurite.
Cloud: omit that connection string and configure service URLs:

- `STORAGE_ACCOUNT_URL`: Table endpoint, e.g. `https://<account>.table.core.windows.net`
- `STORAGE_BLOB_URL`: Blob endpoint
- `STORAGE_QUEUE_URL`: Queue endpoint
- `IMAGE_CONTAINER=images`, `IMAGE_QUEUE_NAME=image-analysis`
- `ImageStorage__queueServiceUri`: queue endpoint for the Functions queue trigger
- `ImageStorage__credential=managedidentity` in Azure

Use a separately configured `AzureWebJobsStorage` host account. For identity-based
host storage set its documented service URIs and required host-storage roles.
Grant the Function App identity Storage Table Data Contributor, Storage Blob Data
Contributor, Storage Queue Data Contributor on application storage and the appropriate
Foundry inference role on the existing resource. Host storage roles differ from
application data roles. No role assignments are performed by application code.

Tables and containers are not provisioned silently on startup. Empty or missing
storage is not a signal to seed real cloud data. Run explicit bootstrap for demo data.
Table Storage is used by the cloud app, not a SQLite copy serialized into a blob.
Queries and consistency boundaries are MVP-oriented, not an unlimited telemetry
warehouse; review partitioning and retention before expanding beyond this demo.

## Image analysis

The API persists validated JPEG uploads privately, records an `ImageAnalyses` job,
then submits its ID to a queue. The HTTP response is `202`; it does not wait for AI.
A Functions queue trigger calls Foundry and stores a short description. The worker
uses a processing lease and skips completed messages. Failed jobs retry and eventually
enter `dead_letter`; a recovery timer requeues stale jobs after interrupted uploads
or queue publication failures. As with all external side effects, a crash after
Foundry responds but before the result is committed can cause another billed call.

Configure `FOUNDRY_ENDPOINT` with the existing resource's Azure OpenAI endpoint
(not its project URL) and `FOUNDRY_VISION_DEPLOYMENT` with a verified image-capable
deployment name. Authentication uses DefaultAzureCredential: Azure CLI locally,
managed identity in Azure. No Foundry key is required. The existing Global Standard
deployments may process globally; use synthetic images only.

The output is advisory. It never supplies measured temperatures, certifies medicines,
or approves transfers. No live Foundry call is performed in the default test suite.
The deployment variable is intentionally blank until vision capability is verified.

## Browser push

Configure VAPID keys and subject for the scheduled notification sender. The private
key belongs in an ignored local setting/Key Vault reference, never the frontend.
The public key may be returned to browsers. A service worker and user permission
must still be implemented in the new frontend; backend support alone cannot show
browser notifications. WebSocket updates in the legacy app are not browser push.

Public subscriptions are limited and validated against supported push-service hosts.
Notifications contain minimal incident information. Delivery is best-effort, with
bounded retries and removal of expired subscriptions; the incident API remains the
source of truth. Browser push is not suitable as a sole safety-critical alarm channel.

## Validation

```powershell
uv run pytest -q
```

The suite includes legacy regression tests, cloud API authentication/domain tests,
worker tests, and Functions binding-discovery tests. Storage integration tests are
opt-in: set `COLDCHAIN_TEST_AZURITE` to a connection string containing explicit
`127.0.0.1` endpoints and the standard `devstoreaccount1` account, then run:

```powershell
uv run pytest tests\test_cloud_storage_integration.py -q
```

Integration tests create uniquely named local containers/queues and clean them up.
They reject non-emulator credentials. They never invoke a model or send browser push.

After dependency changes, regenerate the Functions deployment manifest:

```powershell
uv lock
uv export --locked --no-dev --no-emit-project --no-hashes --format requirements-txt --output-file requirements.txt
```

## Deployment boundary

No Azure resources are created by this implementation. Hosting, RBAC, budget alerts,
retention policies, operator-key provisioning, vision-deployment verification, and
public endpoint smoke tests are separate deployment work. The expected resource
group and existing Foundry resource are configured privately at deployment time.
Do not publish before configuring secrets and verifying protected-route rejection.

Keep the real Foundry endpoint and deployment name in ignored `local.settings.json`
for local development, and Azure Function App settings for hosting. Secret values
should use Key Vault references where appropriate; Foundry authentication remains
managed identity. Public examples deliberately leave these settings empty.

The device developer only needs the backend API URL, their device ID and device key,
and the device function key. Share these through an approved secure channel in a
Git-ignored `.env` file. Do not share Foundry settings, operator keys or cloud
credentials with the device app: image analysis runs on the backend.
