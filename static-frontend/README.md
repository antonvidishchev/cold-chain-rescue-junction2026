# Coldchain / Rescue — public Finland demo

Independent React + TypeScript + Vite static frontend, scaffolded with the official React TypeScript template. This directory is the entire scope: it does not replace the old frontend or change the backend/device. No deployment or infrastructure is performed.

## Theme

The dark palette matches the original frontend: slate surfaces, sky-blue navigation
and destination markers, emerald monitored-state indicators, amber warnings, and red
alarms. Blue destination dots do not imply verified availability. Only map tiles are
darkened; markers, controls, attribution, and camera images retain their own colours.
Compact spacing and initial main-site map centering are unchanged.

## Run and validate

Node 22.12+ (or a newer supported Node version) and npm are required. In PowerShell:

```powershell
$env:PATH = 'C:\Program Files\nodejs;' + $env:PATH
Set-Location C:\3\cold-chain-rescue-junction2026\static-frontend
npm ci
# Optional: otherwise development uses http://localhost:7071
$env:VITE_API_URL = 'http://localhost:7071'
npm run dev -- --host localhost --port 5173 --strictPort
```

```powershell
npm test
npm run lint
npm run build
npm run preview
```

`dist` is the static build output. Build with `VITE_API_URL` set to the public backend origin (without `/api`); an explicitly empty value means same-origin `/api`. If unset, development defaults to localhost:7071 and production defaults to same-origin. Vite variables are build-time public configuration. `.env.example` contains only the public API origin. Do not put credentials, operator keys, device keys, or AI keys in this application or its environment. Authenticated operator operations are intentionally absent.

For a local backend without CORS, set `$env:DEV_API_PROXY_TARGET = 'http://127.0.0.1:7071'` before `npm run dev`. This optional server-side Vite proxy forwards `/api` and automatically selects same-origin browser requests. Clear it before production builds with `Remove-Item Env:DEV_API_PROXY_TARGET`. It contains only the public backend origin, never credentials.

Without that development proxy, the backend must allow the browser's exact origin through CORS (normally `http://localhost:5173`). A separate backend origin must be HTTPS for a hosted HTTPS frontend. Same-origin production hosting must route `/api` to the cloud backend; this frontend does not configure that routing. Serve at the origin root, not a subdirectory. `public/staticwebapp.config.json` is copied into `dist` with SPA fallback, non-cached service worker, and security headers. Its CSP permits HTTPS API/media origins and OSM tiles; narrow HTTPS hosts to your actual API when hosting. There is no offline API or map caching.

## Data and behavior

Contracts were checked against `backend\\CLOUD_API.md`, `app\\cloud\\api.py`, `service.py`, `notifications.py`, and `app\\domain\\planner.py`.

- Public GET `/api/clinics`, `/alerts`, `/transfers`, location-scoped `/readings`, `/timeline` and `/events?location_id=…&limit=50`, plus device-scoped `/images` and `/devices/{id}/inventory` are the only dashboard sources. No seeded frontend values or fallback fixtures are presented as live data. Test fixtures exist only in test files.
- Sensor temperature and the fridge's reported display are separate observations. The history table also exposes nullable display temperature and humidity. Watchdog reports show H1 fridge mismatch, alarm acknowledgment/completion via the knob, and late-report markers. Numeric, string and absent protocol/code values are supported. Device-unverified assessments are not clinical certification; knob completion never implies power/temperature recovery or sets recovery status.
- Canonical used/free capacity remains sourced from clinics. Device-observed inventory, stock presence and transferred-item snapshots are labeled separately and never overwrite canonical totals or approved transfers. A device inventory 404 means no sync received, not a service failure; an empty accepted snapshot is shown explicitly. Events and inventory use the same abortable selection-scoped polling as history.
- The backend catalogue contains Espoonlahti main (`id: fridge-a`, `clinic_id: espoonlahti-main`) and ten named hospital destinations from the unchanged device catalogue. Names describe real locations; operational values are simulated estimates, not live availability. Only active, explicitly synthetic demo records are shown. Names, cities, counts and coordinates come from the API, never a frontend location dictionary.
- Optional API fields `active`, `monitored`, `address`, `phone`, `lat`, `lon`, `distance_km`, `drive_minutes`, `accepts_after_hours` and `capacity_units` extend the existing contract. Records without `monitored` preserve legacy monitoring behavior; `monitored: true` sorts the main site first. Destinations with `monitored: false` have neutral grey markers and show **Not monitored / demo capacity**, read-only travel/capacity estimates and transfer plans—not offline devices, healthy temperatures or reported power. Destination selection does not poll device observations.
- The map validates finite numeric latitude/longitude and geographic bounds. Missing/invalid positions are omitted with an explanation and no invented fallback, while every site remains selectable in the keyboard-accessible scrollable list. Bounds fit actual valid coordinates only when the coordinate set changes, preserving user zoom/pan across refreshes and selection. OSM standard tiles load through normal interactive viewing with attribution; no bulk downloads.
- A refresh runs every 5 seconds after the preceding request finishes, including events, incidents, and visible detail panels. Requests do not overlap; this increases polling traffic compared with the previous 20-second interval. Selection changes and unmounts abort requests, and late results cannot overwrite another selection. Last successful data remains explicitly marked as potentially outdated when polling fails.
- The frontend's two-minute stale indication is an observation-age heuristic, **not** the server's configurable offline threshold. Heartbeats, measured temperature, latest alarm state, and recovered/unresolved incidents are separate facts. Empty history does not mean safe stock. History displays the latest 300 observations in the backend's default 24-hour window, with an accessible table.
- Incident checklist confirmations are the dashboard's public-write exception: native checkboxes PATCH `/api/alerts/{id}/public-checklist/{item_id}` with `{done: boolean}` and no credentials. The three labels are **Unit is inspected**, **Incident acted upon. Stock transferred to another unit or location**, and **Recovery verified** (stable IDs `inspect`, `protect`, `verify`; legacy labels are overridden). All controls on that incident are disabled during a save. Successful full incident responses remain visible until polling confirms them; errors retain the last persisted state and allow retry. Partial confirmations can be unchecked; a successful third confirmation shows **Resolved by user** and locks further edits. User confirmation does not change measured temperature, power or inventory and is not sensor recovery or clinical certification. Resolved history has neutral styling. Protocol number, sensor recovery, and timeline remain read-only server data. Transfer proposals and approvals are read-only. Inventory editing, photo capture, alarm acknowledgment, commands, and clinical decisions are not available.
- Gallery displays only records explicitly marked `synthetic: true`, via the sanitized configured API origin and encoded image ID. Descriptions are plain React text, generated by the backend's Foundry integration; the browser never invokes AI. Missing images and pending/failed analysis have explicit states. Device-local simulated camera frames appear here only after upload; local JPG or `/camera` paths are never fetched, and no image or Foundry description is fabricated.

## Optional browser push

Only an explicit **Enable notifications** click requests permission. Push requires a secure context, supported browser, configured backend VAPID keys, and permission. Alongside the public incident checklist exception above, notification opt-in uses POST `/api/push/subscriptions` and removal uses authenticated DELETE `/api/push/subscriptions/{id}`. Browser subscription keys use unpadded base64url. The initial backend removal token is saved in browser localStorage, scoped to the API origin, reused on renewal, and passed as a Bearer token on DELETE. It is not an operator credential and is never bundled. Do not clear site storage before disabling notifications; losing that token requires resetting the browser subscription. All-clinic subscription uses an empty `clinic_ids` list (avoiding ambiguity with backend location IDs). Renewal is an explicit click; automatic browser subscription rotation is not implemented.

The service worker renders text, deduplicates visible notifications by ID tag, creates clinic deep links, and validates same-origin navigation on click. No background subscriptions, analytics, third-party fonts, AI calls, or offline caching are used. Browser/OS/backend push delivery is best effort and must not be used as an emergency alarm system.

## Tests

Vitest + Testing Library cover contract errors, clinic selection, late aborted history/event/inventory responses, H1 and nullable/legacy protocols, nullable codes and readings, knob reports without recovery claims, canonical versus observed stock, no-sync 404 versus service failures, synthetic-image filtering, plain-text descriptions, URL sanitization, public checklist completion/unchecking, pending/resolved locks, failed saves, stale-poll protection, legacy labels, nullable resolution evidence, read-only API use elsewhere, and push unsupported/denied/error/token-renewal/removal behavior. Leaflet is mocked in jsdom; dedicated map tests verify every catalogue coordinate, invalid/missing coordinate rejection with no fallback, neutral destinations, and viewport preservation across polls and selection. Dashboard tests cover all eleven sites, archived record filtering and no destination monitoring requests or false connectivity states. Service-worker tests execute the actual worker and verify safe text/deep links.

`npm run test:browser` runs a real-browser smoke against a running frontend (default `http://localhost:5173`, override `SMOKE_URL`) and the updated catalogue backend. Set `$env:SMOKE_FIXTURES = '1'` to intercept API reads using a test fixture built from the unchanged device catalogue instead; this also tests coordinates becoming unavailable. It verifies all catalogue markers, neutral destinations, preserved zoom after refresh, keyboard selection of every partner on mobile, and absence of runtime errors/operator writes. Fixture mode explicitly clicks all three checklist confirmations and permits only their three public-checklist PATCH requests during those actions; all other API mutations remain forbidden. `@playwright/test` uses installed Microsoft Edge (`channel: 'msedge'`); no browser download is required. This app does not require Playwright to run.

Validated locally with the catalogue-backed browser fixture: eleven sites/markers, all ten destination selections, no horizontal overflow at 1440px or 390px, no invented positions after coordinates are removed, no page errors and no unauthorized API mutations (only the three explicitly exercised public-checklist PATCH requests). This fixture validates frontend behavior, not live backend availability.

**Demo scenario using named locations; capacities/travel estimates are simulated, not live availability. Public media remains synthetic-only. This is not a medical device, operational alarm system, or substitute for product instructions and authenticated clinical procedures.**

