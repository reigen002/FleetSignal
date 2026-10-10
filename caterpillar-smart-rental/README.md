# FleetSignal — Fleet Telemetry and Rental Operations

FleetSignal gives a Caterpillar dealer a fleet dashboard, explainable alerts, rental lifecycle tracking, and demand allocation recommendations. Its backend accepts identified telemetry events, reconciles alerts in the same SQLite transaction, and makes retries safe when a sender loses the response.

The seven-asset demonstration preserves the original SRTS story: recover the idle excavator **EQX1007** for S003, review overdue EQX1002, and inspect live safety telemetry on EQX1004. The dataset and forecast are historical synthetic examples, evaluated at the fixed business clock **2025-05-12**; they are not current fleet observations or validated savings estimates.

## Stack and scope

| Layer | Technology |
|---|---|
| Backend | Python 3.11, FastAPI, SQLAlchemy 2.0, Alembic 1.13.2 |
| Storage | File-backed SQLite; one writer, finite busy timeout |
| Dependency management | uv 0.13.0 and `backend/uv.lock` |
| Frontend | React, Vite, existing charts and maps; Node 22.19.0 |
| Local packaging | Docker Compose with persistent named SQLite volume |

This is a local reliability project. It has synchronous alert evaluation and request-driven UI refresh. Cloud deployment, PostgreSQL, streaming, authentication, machine learning, and production scale are outside this implementation.

## Local backend

From this project directory, enter `backend`. Install uv and Python 3.11 if needed, then use the committed lockfile:

```bash
cd backend
uv sync --frozen --extra dev
uv run --frozen python -m app.migrations
uv run --frozen uvicorn app.main:app --reload
```

Startup runs the same validated migrations automatically. `GET http://localhost:8000/health` returns `{"status":"ok","service":"FleetSignal Backend"}`. `GET /ready` verifies database connectivity and the required schema revision. OpenAPI is at <http://localhost:8000/docs>.

**Default mode has no demo seed.** `/admin/seed`, `/admin/reset`, and `/assets/{asset_id}/simulate` are absent unless `FLEETSIGNAL_DEMO_MODE=true`. An empty default database therefore has no assets. Existing configured database contents remain available.

To run the historical seven-asset demo, set the environment variable before starting the backend:

```bash
# POSIX shell, from backend/
FLEETSIGNAL_DEMO_MODE=true uv run --frozen uvicorn app.main:app --reload
```

```powershell
# PowerShell, from backend/
$env:FLEETSIGNAL_DEMO_MODE = 'true'
uv run --frozen uvicorn app.main:app --reload
```

From the project root, the equivalent server command is:

```bash
uv run --project backend --frozen uvicorn app.main:app --app-dir backend --reload
```

Both working directories resolve the same absolute defaults: `<project>/.fleetsignal/fleetsignal.db` and `<project>/data`. Importing the app does not create or modify the database; startup owns migration and optional seed work. The original `backend/srts.db` is not selected by default.

## Configuration

| Variable | Default / requirement |
|---|---|
| `FLEETSIGNAL_DATABASE_URL` | Absolute file SQLite URL for `<project>/.fleetsignal/fleetsignal.db` |
| `FLEETSIGNAL_DATA_DIR` | Absolute `<project>/data` directory |
| `FLEETSIGNAL_DEMO_MODE` | `false`; opt in to seed/reset/simulation |
| `FLEETSIGNAL_SQLITE_BUSY_TIMEOUT_MS` | `5000`; positive, at most `60000` |
| `FLEETSIGNAL_ALLOWED_ORIGINS` | Explicit localhost/127.0.0.1 origins on 5173 and 4173, JSON list |
| `SRTS_DEMO_DATE` | Preserved business-clock override; default `2025-05-12` |

Example SQLite URLs: `sqlite:///D:/Projects/FleetSignal/caterpillar-smart-rental/.fleetsignal/fleetsignal.db` on Windows, `sqlite:////absolute/path/fleetsignal.db` on POSIX. Relative paths, memory SQLite, and other database engines are rejected. Every SQLite connection enables foreign keys and a finite busy timeout; WAL is not enabled by this project.

`.env.example` documents these values; the backend does not automatically load `.env`. When supplying absolute-path examples, replace them with your own paths. You may copy it to project `.env`, select demo mode there, and explicitly load it from `backend/`:

```bash
uv run --frozen uvicorn app.main:app --reload --env-file ../.env
```

## Frontend

In another terminal, from the project directory:

```bash
cd frontend
npm ci
npm run dev
```

Use Node **22.19.0**. The app opens at <http://localhost:5173> and uses the real API at <http://localhost:8000> by default. Enable backend demo mode for the existing demo controls and fleet story. `frontend/.env.local.example` documents `VITE_API_BASE` and the separately selected `VITE_API_MODE=mock`; errors do not switch to mock data.

Simulation, check-in, and checkout return after the backend has committed their alert effects. The UI reloads asset/telemetry state afterward. API error messages include a validated request ID when provided by the backend.

## Docker

From the project directory:

```bash
docker compose up --build -d
```

The supplied Compose configuration explicitly enables demo mode. The backend reads data from `/opt/fleetsignal/data` and stores SQLite at `sqlite:////var/lib/fleetsignal/fleetsignal.db`, mounted on the named `fleetsignal_db` volume. Container recreation retains that file; deleting the volume removes its data. For ordinary operation, change `FLEETSIGNAL_DEMO_MODE` to `false` before starting a fresh deployment.

## External telemetry

Send an event for an existing asset. Keep the same global event ID and semantic payload for retries:

```bash
curl -i -X POST http://localhost:8000/telemetry/events \
  -H 'Content-Type: application/json' \
  -H 'X-Request-ID: demo-ingest-1' \
  -d '{"event_id":"device-EQX1004-0001","asset_id":"EQX1004","timestamp":"2025-05-12T10:00:00Z","engine_temp_c":115,"seatbelt_on":false}'
```

A new event returns **201**; the same validated payload returns **200** with `duplicate=true` and the same telemetry ID. Changed content under that ID returns **409**. Invalid input is **422**, unknown asset **404**, and database contention **503** with `Retry-After: 1`. All responses carry `X-Request-ID`; unexpected errors return a safe **500** response.

One successful transaction stores telemetry and evaluates each alert condition independently. Active episodes retain their ID and creation time. A duplicate does not evaluate alerts or advance their timestamps. `/alerts/refresh` remains an explicit recovery scan; client actions do not depend on it.

## Migrations and existing databases

Use `uv run --frozen python -m app.migrations` from `backend/`. A fresh database upgrades to revision `0002`. An unversioned legacy database is adopted only after validation against the frozen original six-table schema. Revision `0002` preserves legacy telemetry with null event identity/receipt fields and resolves duplicate active alerts while retaining their history; the earliest `created_at`, then lowest ID, remains active.

Back up a legacy file before explicitly configuring its absolute URL for adoption. Unknown schemas are refused without changes; never manually stamp an unknown database to bypass validation. The user's original `backend/srts.db` is not automatically migrated.

## Demonstration and checks

See [the five-minute demo](docs/DEMO_FLOW.md), [API contract](docs/API_CONTRACT.md), and [reliability design and limits](docs/RELIABILITY.md).

From `backend/`:

```bash
uv sync --frozen --extra dev
uv run --frozen pytest -q -p no:cacheprovider
uv run --frozen python scripts/demo_reliability.py
```

The reliability demonstration uses an isolated temporary file database. It shows rollback after an injected exception following a flush, then retry, duplicate, conflict, and retry after a lost response. It does not kill a process or establish process-crash durability.

For an explicitly disposable Docker verification project, start Compose from the project directory, then run the script from `backend/`:

```bash
docker compose -p fleetsignal-verification up --build -d
```

```bash
uv run --frozen python scripts/verify_docker.py --project fleetsignal-verification --base-url http://localhost:8000
```

This verification recreates the named local project's backend container and checks that its data persists. Use that project only for disposable verification.

From `frontend/`, `npm ci` then `npm run build` builds the existing interface. The CI workflow runs locked installs, migrations, backend tests, and the frontend build with Python 3.11 and Node 22.19.0; it needs no external API credentials.

### Verified results

Submission regression: **262 passed in 34.38s**, and **262 in 37.71s** in a clean environment whose configured database hash remained unchanged. The documented setup commands and **13 browser checks** passed. Locked frontend installation and production build passed (660 modules); the targeted dependency fix leaves `npm audit` reporting **zero vulnerabilities**.

The disposable rollback/retry demonstration and fresh Docker ingestion, lock recovery and container recreation checks passed. These establish local operation and named-volume persistence; no cloud deployment was performed.

[SUBMISSION_REVIEW.md](docs/SUBMISSION_REVIEW.md) records the final review, browser/clean-setup results and a three-minute demonstration. [COMPLETION_REPORT.md](docs/COMPLETION_REPORT.md) retains the implementation commands, test counts, Docker evidence and limitations. A workflow file alone does not establish a successful hosted CI run. The existing frontend bundle warning above 500 kB remains.

## Historical documents

[HACKATHON_SPEC.md](docs/HACKATHON_SPEC.md) and [IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) preserve the original hackathon requirements and design. Their original SRTS branding, setup assumptions, and scope are historical; use this README and the active API/reliability documentation for current behavior.

Utilization still reports two explainable measures: productive ratio `engine / (engine + idle) × 100`, and shift utilization `engine / (operating days × 8 hours) × 100`, capped at 100. Telemetry ingestion preserves the existing rental metrics, forecast method, recommendation logic, and business clock.
