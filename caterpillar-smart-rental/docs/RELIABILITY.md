# FleetSignal reliability

FleetSignal accepts externally identified telemetry and commits each new event together with the affected asset's alert reconciliation. A sender can repeat a request after losing the response: identical validated content returns the original row, while changed content under that event ID is rejected. These guarantees apply to the configured file-backed SQLite database and the transaction paths described below.

## Identity and validation

`POST /telemetry/events` requires a global `event_id`, an existing `asset_id`, a timezone-aware event timestamp, and at least one non-null sensor or fault field. Event IDs contain 1–128 characters and no whitespace; asset IDs contain 1–20 characters. All float values must be finite. Coordinates are paired and bounded, fuel percentage is 0–100, hours and consumption are nonnegative, and fault code/description lengths are limited to 50/200. Extra input fields are rejected.

The server hashes the validated semantic body with SHA-256 over sorted compact JSON. Identity includes event ID, asset, timestamp, and sensor/fault values. Validation normalizes timestamps to UTC and accepted numeric values; omitted optional fields equal null, and negative zero equals zero. Internal database ID, scenario label, stored hash, and receipt time are excluded. Equivalent timezone offsets or accepted numeric representations therefore do not create conflicts.

A unique database index enforces global event identity. New rows store server `received_at`; migrated legacy telemetry retains null identity/hash/receipt fields. Legacy rows are not assigned fabricated device event IDs. Hashing detects conflicting reuse; it does not prove the sender's identity.

Future event timestamps are allowed to support the preserved synthetic scenarios. No production clock-skew, event-expiry, or replay-authentication policy is implemented.

## Transaction ownership

The shared write context starts **`BEGIN IMMEDIATE` before comparison, reads, insert, or reconciliation**. This obtains SQLite's writer reservation before deciding whether an event already exists. The service flushes rows when their IDs/evidence are needed and commits once after all telemetry and alert effects have succeeded. The HTTP handler receives success only after that commit. Exceptions roll back the whole transaction.

| Path | Work committed together |
|---|---|
| External event | Identity comparison, telemetry insert, affected alert reconciliation |
| Simulation | Entire generated telemetry batch and affected asset alerts |
| Checkout/check-in | Rental state, lifecycle event, and affected asset alerts |
| Explicit `/alerts/refresh` | Recovery reconciliation across the fleet |

Alert evaluation and reconciliation helpers never commit. No email or other external service call occurs inside these transactions. A canonical duplicate enters the serialized comparison path, then returns the original telemetry ID without alert evaluation or timestamp changes.

SQLite is a single-writer database. Every connection enables foreign keys and a finite busy timeout (default **5000 ms**, configurable up to 60000). A blocked/unavailable database operation returns a safe **503** with **`Retry-After: 1`**; the sender can repeat the same event ID and semantic payload. WAL is not selected in this implementation. File SQLite is the only supported backend; memory URLs, relative database paths, and other engines are rejected.

## Stable alert episodes

At most one unresolved episode exists for each `(asset_id, alert_type)`, enforced by a partial unique index. Reconciliation:

1. Evaluates each current condition independently.
2. Keeps an existing active ID and `created_at`; changes evidence/message only when needed, and advances internal `last_seen_at` on evaluation.
3. Resolves an episode when its condition clears, recording `resolved_at` and retaining history.
4. Creates a new episode for a later recurrence.

The public alert response remains compatible: `id`, `asset_id`, `alert_type`, `severity`, `message`, `evidence`, `resolved`, `created_at`, and `resolved_at`. Internal `last_seen_at` is not added to that response. Duplicate telemetry does not change any episode time.

Telemetry conditions use the latest **20 rows for that asset**, ordered by **event timestamp descending, then row ID descending**. Each rule chooses its own newest qualifying evidence, so a single reading may independently trigger several hazards:

| Rule | Qualifying evidence |
|---|---|
| Engine overheat | Temperature **≥110 °C** |
| Seatbelt violation | `seatbelt_on=false` |
| Abnormal fuel | Consumption **>24 L/h** (twice the preserved 12 L/h baseline) |
| Location mismatch | Fault code starts with `L` |

Location mismatch uses the synthetic fault signal; the code does not compute geofences from coordinates. A normal reading alone does not clear hazards that still have evidence in the window. There is no time-based expiry without new readings. Late events are persisted, but events outside the newest-20 window cannot replace recent hazard evidence. Equal event timestamps use the larger row ID first.

Assignment, overdue, utilization, forecast, and recommendation business rules retain the original behavior. Rental overdue/forecast decisions use the historical fixed business clock, default **2025-05-12**, with the preserved `SRTS_DEMO_DATE` override. Alert evaluation/receipt times use server time. Sensor ingestion does not rewrite the seeded rental utilization figures.

The frontend reloads state after simulation and rental mutations; it no longer calls the fleet recovery scan afterward. `/alerts/refresh` remains an explicit utility for recovery or investigation. There is no streaming subscription or background expiry worker.

## Startup, isolation, and migrations

Each app owns its engine, session factory, and settings. Importing the app creates no database files and runs no seed/reset work. Lifespan startup validates demo files when requested, runs validated migrations, then optionally seeds that configured database. Shutdown disposes its engine. Tests use temporary file databases and sentinel files to check isolation.

Default paths derive from the source project root, independent of working directory:

- SQLite: `<project>/.fleetsignal/fleetsignal.db`.
- Data: `<project>/data`.

`FLEETSIGNAL_DEMO_MODE=false` is the default. Seed/reset/simulation routes are absent in ordinary mode, and startup does not populate assets. The supplied Compose demo explicitly enables them. `.env.example` is documentation; environment files are loaded only when explicitly requested, such as Uvicorn `--env-file ../.env` from `backend/`. Any configured database URL and data path must be absolute.

Run the migration CLI from `backend/`:

```bash
uv run --frozen python -m app.migrations
```

Startup uses the same migration helper. Under a writer reservation, it handles:

| Database | Behavior |
|---|---|
| Fresh empty file | Apply `0001`, then `0002` |
| Recognized unversioned original schema | Validate, stamp `0001`, then upgrade |
| Versioned database | Upgrade through Alembic |
| Unknown unversioned schema | Refuse adoption and roll back without modifying that schema |
| Empty revision table alongside other existing tables | Refuse adoption; empty revision alone may initialize a fresh schema |

Legacy validation compares the frozen original **six tables**, including columns, type families/lengths, nullability, primary/foreign keys, indexes, and unexpected defaults/constraints/views/triggers. It does not guess a baseline from table names alone. Revision `0002` adds telemetry identity/receipt columns and alert `last_seen_at`, then resolves duplicate unresolved `(asset, type)` rows while preserving history. The oldest `created_at`, then lowest ID, remains active before the unique active-episode index is created.

Before explicitly adopting an existing legacy file, make a backup and configure its absolute URL. Never manually stamp an unknown database to bypass validation. The original user's `backend/srts.db` is not the default database and is not automatically migrated. The requested reviewed commit `373050241210d9ad01aa3bbf0e095233b3761e9b` was absent locally; the inspected implementation baseline was `93765221e47233c7b60fe2bdf4d3093070ca7a46`. The historical execution record and final evidence document that provenance.

## Request correlation and operational signals

`GET /health` reports `{"status":"ok","service":"FleetSignal Backend"}`. `GET /ready` queries required telemetry/alert columns and Alembic revision `0002`; connectivity or schema failure returns safe 503 detail. Compose uses `/ready` as its health check.

Every response includes `X-Request-ID`. A supplied value is used only if it matches `[A-Za-z0-9._:-]{1,64}`; invalid input is replaced by a generated UUID. Unexpected exceptions return `{"detail":"Internal server error","request_id":"..."}`. Detailed tracebacks stay in server logs. The frontend validates header/body request IDs before appending them to an error and exposing `error.requestId`, including its asset-not-found presentation.

JSON completion logs contain event name, request ID, route template, method, status, and elapsed milliseconds. Ingestion outcome records also contain event ID, asset ID, and accepted/duplicate/conflict/not-found/unavailable outcome. No full telemetry payload, customer name, or contact information is logged by these records. IDs are correlation aids, not authorization tokens.

Correlation also wraps CORS preflights. Unexpected processing errors record an `error` ingestion outcome and a server traceback. Validation responses expose only error type, location, and message; non-finite raw JSON values are rejected with 422 without echoing invalid inputs.

CORS uses an explicit configured list of local origins, disables credentials, and exposes the correlation/retry headers. Product authentication is outside this project. Use appropriate access controls before placing real operational data in a deployment.

## Reproducible verification

The committed lockfiles drive CI and local dependencies: Python 3.11 with uv **0.13.0**, and Node **22.19.0** with `npm ci`. Alembic **1.13.2** is synchronized across backend dependency declarations and the lockfile. CI configures an absolute temporary SQLite path, keeps default demo mode false, runs migrations and backend tests, and builds the frontend. It requires no external API keys or accounts.

From `backend/`:

```bash
uv sync --frozen --extra dev
uv run --frozen pytest -q -p no:cacheprovider
uv run --frozen python scripts/demo_reliability.py
```

The reliability script uses a temporary file SQLite database. It injects failure after telemetry flush, verifies no partial telemetry/alert effects, retries successfully, checks a canonical duplicate and conflict, and models a committed response lost by the sender. This is exception rollback and retry evidence; it does not perform a process kill.

For the explicitly disposable `fleetsignal-verification` Compose project started using the [README procedure](../README.md), run from `backend/`:

```bash
uv run --frozen python scripts/verify_docker.py --project fleetsignal-verification --base-url http://localhost:8000
```

The Docker script checks readiness, seven assets, external retry/conflict, contention failure, and persistence after recreating the chosen local backend container. Compose mounts `fleetsignal_db` at `/var/lib/fleetsignal`, with the database URL `sqlite:////var/lib/fleetsignal/fleetsignal.db` and packaged data at `/opt/fleetsignal/data`. Container recreation preserves the volume; volume deletion is data deletion.

From `frontend/`, use `npm ci` and `npm run build`. [COMPLETION_REPORT.md](COMPLETION_REPORT.md) records exact final outcomes and limitations; the historical baseline is recorded separately in [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md). Local equivalents do not prove that the hosted CI workflow has executed. The existing frontend build warning above 500 kB remains.

## Limits of the evidence

The implementation demonstrates local transaction atomicity, event retry behavior, stable episodes, controlled contention, validated schema adoption, and named-volume persistence. It does not establish process-crash durability, distributed exactly-once delivery, cloud deployment, PostgreSQL support, multi-writer scale, streaming ingestion, production timestamp policy, model accuracy, or guaranteed financial savings. The original forecast/scenario data remains a historical synthetic demonstration.
