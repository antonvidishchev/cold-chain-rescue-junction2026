# ColdChain Rescue

> **The fridge is warming. Who needs to act, and where can the stock go?**

ColdChain Rescue coordinates the response to a failing medicine fridge. An
independent hardware watchdog sits next to the fridge. It detects temperature
excursions, power loss and tampering, sounds a local alarm, escalates to the
right people until someone acknowledges, and proposes a transfer of the stock
to available storage. The transfer respects explicit capacity limits and each
product's storage instructions, and a human approves it.

Built at **Junction 2026** (Espoo). Tracks: **Hardware · Healthcare · Agentic AI**.

---

## Why

- **Cold-chain failures are expensive and dangerous.** Vaccines, insulin,
  biologics and many reagents must stay within a narrow range (often
  +2 °C … +8 °C). A fridge that fails overnight can destroy thousands of euros
  of stock. Worse, the stock may still get used without anyone knowing.
- **Smart fridges get hacked.** Connected fridges in Europe have been reported
  compromised. A fridge that reports "4 °C, all fine" while it is actually
  warming is worse than one with no monitoring at all.
- **Monitoring alone is familiar.** Data loggers already exist. The hard part
  is the *coordinated response*: who is told, who confirms, where the stock
  goes, and whether that place has room and the right conditions.

## What it does

```
detect  ──►  alarm locally  ──►  escalate & acknowledge  ──►  plan transfer  ──►  human approves
```

1. **Detect.** The Uno Q watchdog reads its own temperature sensor every few
   seconds and evaluates it against the **storage range of the products
   actually in the fridge**.
2. **Alarm locally.** If the fridge holds stock and is outside the range for
   longer than the grace period, the on-board buzzer sounds. This works even
   when the network is down.
3. **Escalate & acknowledge.** The backend raises an alert on the dashboard.
   Staff acknowledge it, which silences the buzzer and records who took
   ownership.
4. **Plan a transfer.** If the cooling cannot be restored (for example, the
   power is out and the backup is not holding), ColdChain Rescue proposes
   moving the stock to alternative storage. It checks free capacity and
   whether each product's range is compatible with the target's range.
5. **Human approval.** Nothing moves until a person approves the plan.

### Independent watchdog & tamper detection

The Uno Q does **not** trust the fridge. It has its own sensor and its own
power, and it compares its reading with the temperature the (smart) fridge
reports about itself. If they disagree by more than a tolerance for a
sustained period, ColdChain Rescue raises a **TAMPER** alert in addition to
the normal excursion workflow. A compromised fridge controller cannot hide a
real temperature rise.

### Product instructions govern thresholds

Thresholds are **not** one global number. Every product carries its own
storage instructions (min/max °C, allowed excursion time). The fridge's
effective range is the intersection of the ranges of the products inside it.

> ⚠️ **Temperature readings alone cannot establish whether a medicine is still
> usable.** ColdChain Rescue flags excursions and supports the response. The
> decision to use, quarantine or discard stock stays with a pharmacist or
> other qualified person, following the manufacturer's guidance.

## Who it is for

Pharmacies, laboratories and smaller clinics: places with a few critical
fridges, no 24/7 facilities team, and a real need to know *who acts* when
something goes wrong at 3 a.m.

## Architecture

```mermaid
flowchart LR
  subgraph UnoQ["Arduino Uno Q (watchdog)"]
    T[Modulino Thermo] -->|I²C / Qwiic| MCU[STM32 sketch]
    MCU --> B[Modulino Buzzer]
    MCU <-->|Bridge RPC| PY[Python app on Linux MPU]
  end
  PY -->|HTTP: telemetry, config, commands| API[FastAPI backend]
  API --- DB[(SQLite)]
  API <-->|REST + WebSocket| UI[React dashboard]
  SIM[Simulator panel<br/>power · camera · fridge report] --> API
  UI --- SIM
```

| Part | Tech | Role |
| --- | --- | --- |
| `device/coldchain-watchdog` | Arduino App Lab app for **Uno Q** (sketch + Python) | Reads the sensor, runs the local alarm rule, drives the buzzer, sends telemetry, polls for commands |
| `backend` | Python 3.12+, **FastAPI**, SQLModel/SQLite | Collects telemetry, evaluates thresholds and tamper rules, manages alerts, inventory, capacity and transfer plans, pushes live updates |
| `frontend` | **React + Vite + TypeScript**, Tailwind, Recharts | Dashboard (fridges, live temperature, alerts, transfer plans) and the simulator panel used in the demo |

The detailed data contracts and state machine are in
[docs/architecture.md](docs/architecture.md).

### Alarm states

```
NORMAL ──out of range──► WARNING ──grace period elapsed & stock present──► EXCURSION
   ▲                                                                          │
   └──────────────── back in range (alert stays until acknowledged) ◄─────────┘

POWER_LOSS : fridge power reported down (simulated); escalates faster, triggers transfer planning
TAMPER     : |device reading − fridge-reported reading| > tolerance for a sustained period
```

## Demo script (peer demo)

Full version: [docs/demo-script.md](docs/demo-script.md).

1. The dashboard shows **Pharmacy Fridge A** holding insulin and vaccines
   (2–8 °C), plus two backup storage locations with explicit free capacity.
2. **Warm the sensor** (hold the Modulino Thermo in your hand). The temperature
   rises, WARNING appears, and then EXCURSION: **the buzzer sounds** and an
   alert pops up.
3. A staff member **acknowledges** the alert. The buzzer silences and the
   owner is recorded.
4. In the simulator, **cut the fridge power**. The state becomes POWER_LOSS
   and a **transfer plan** is proposed: what goes where, with capacity checked.
5. A pharmacist **approves** the plan.
6. **Tamper scenario:** the simulated smart fridge keeps reporting "4.0 °C"
   while the watchdog measures 12 °C. A **TAMPER** alert is raised.

## Repository layout

```
device/coldchain-watchdog/   Arduino App Lab app for the Uno Q
  app.yaml                   App Lab manifest
  sketch/                    STM32 sketch: Modulino Thermo + Buzzer, Bridge RPC
  python/                    Linux-side app: alarm rule, telemetry, command polling
backend/                     FastAPI service
  app/api/                   HTTP + WebSocket routes
  app/domain/                thresholds, tamper check, alarm state machine, transfer planner
  app/agent/                 (planned) agentic escalation & planning
  seed/                      demo products, storage locations, stock
  tests/
frontend/                    React dashboard + simulator
docs/                        architecture, demo script
scripts/dev.sh               run backend + frontend together
```

## Quick start

### Prerequisites

- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- Node.js 20+ and npm
- For the device: an Arduino **Uno Q**, Modulino Thermo and Modulino Buzzer
  (chained over Qwiic), and [Arduino App Lab](https://docs.arduino.cc/software/app-lab/)
  or `arduino-app-cli` on the board

### Backend

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

API docs: <http://localhost:8000/docs>. The demo data in `seed/` loads on
first start.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Dashboard: <http://localhost:5173>. Set `VITE_API_URL` if the backend is not
on `http://localhost:8000`.

### Both at once

```bash
./scripts/dev.sh
```

### Device (Arduino Uno Q)

1. Plug the Modulino Thermo and Buzzer into the Uno Q's Qwiic connector.
2. Copy `device/coldchain-watchdog` into your App Lab apps folder on the
   board (or open it in App Lab).
3. Set the backend URL and device id in `app.yaml` / environment
   (`COLDCHAIN_API_URL`, `COLDCHAIN_DEVICE_ID`). The board and the laptop
   running the backend must be on the same network.
4. Run the app from App Lab, or with
   `arduino-app-cli app start ~/ArduinoApps/coldchain-watchdog`.

No board? The simulator panel can post readings too, so the dashboard runs
without hardware.

### Configuration

| Variable | Where | Default | Meaning |
| --- | --- | --- | --- |
| `COLDCHAIN_DB_URL` | backend | `sqlite:///./coldchain.db` | Database |
| `COLDCHAIN_CORS_ORIGINS` | backend | `http://localhost:5173` | Allowed dashboard origins |
| `COLDCHAIN_TAMPER_TOLERANCE_C` | backend | `2.0` | Allowed device-vs-fridge difference |
| `VITE_API_URL` | frontend | `http://localhost:8000` | Backend URL |
| `COLDCHAIN_API_URL` | device | `http://192.168.1.10:8000` | Backend URL as seen from the board |
| `COLDCHAIN_DEVICE_ID` | device | `unoq-fridge-a` | Device identity |

## Weekend scope

- One sensor, one monitored fridge, two alternative storage locations
- Explicit capacity constraints and per-product storage ranges
- Local buzzer + dashboard alerts with acknowledgement
- Simulated power loss, simulated camera ("stock present") and simulated
  smart-fridge self-reports
- Transfer proposal with mandatory human approval

**Not in scope:** real fridge integration, real camera vision, regulatory-grade
logging, SMS/phone escalation.

## Roadmap

- **Agentic escalation & planning** (Claude with tools): run the escalation
  ladder, draft and explain transfer plans and coordinate couriers. A
  deterministic constraint checker stays authoritative.
- Camera-based stock detection on the Uno Q
- Signed telemetry (HMAC) so spoofed readings are rejected
- Telegram / SMS / email escalation channels
- Battery-backed watchdog with a power-loss sensor on the fridge's mains

## Team

Junction 2026. See the commit history.

## License

[MIT](LICENSE)
