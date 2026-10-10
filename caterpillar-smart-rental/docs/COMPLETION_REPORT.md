# FleetSignal completion report

Local implementation and verification: **2026-10-10**, branch `feat/fleetsignal-reliability`.

Mandatory implementation slices and local acceptance checks are complete. Submission regression: **262 passed in 34.38s**. Browser walkthrough and clean-setup commands passed; npm audit now reports zero vulnerabilities. See [SUBMISSION_REVIEW.md](SUBMISSION_REVIEW.md) for the review and three-minute demonstration. Locked frontend install/build, fresh/legacy migration, failure/retry, concurrency and Docker persistence checks passed. Hosted CI has not run.

## Checkout and preserved work

The starting checkout is `93765221e47233c7b60fe2bdf4d3093070ca7a46`. The requested reviewed commit `373050241210d9ad01aa3bbf0e095233b3761e9b` is absent locally; exact git comparison to it was unavailable. Current source was inspected and executed before changes. No AGENTS.md was found.

Current source had hardcoded seed statuses differing from the historical CSV for EQX1002/1004/1007. Those three checked-out overrides remain explicit in the configured CSV loader. The CSV and utilization/forecast calculations were retained.

The pre-existing `frontend/package-lock.json` change removes 78 lines of optional libc metadata. Those removals remain preserved. Before submission review its SHA-256 was `AD674DD93976C5CE030EB7411904F67C674D6D8369C611C615E9485438639DFA`; after the authorized three-field `source-map-js` patch it is `E854E8BBA469719D337A6B0E4163FC4DC45F88FE17CD6BBCE369FA69F1083A67`. All other lock entries were compared and found identical.

The user's original `backend/srts.db` was neither migrated nor modified. Its baseline/final SHA-256 is `CE8D51482A90FEC043C66132C250A72F6313243C7DE1BC234A7DC4CB5A0D9A1B`. Tests did not create the default `.fleetsignal/fleetsignal.db`.

## Delivered changes

| Area | Source changes |
|---|---|
| Configuration | `app/settings.py`, factory in `app/main.py`, app-scoped engine/session dependency in `app/database.py`; absolute SQLite/data defaults, finite timeout, per-connection foreign keys, teardown disposal and explicit demo mode |
| Data isolation | Lazy CSV loading, configured supplement reads, no shared supplement cache; affected forecast/recommendation callers and tests updated |
| Packaging | Root-context Dockerfile, locked synchronized dependencies, packaged data, `.dockerignore`, `.env.example`, persistent Compose volume and readiness health check; no container reload |
| Evolution | Alembic configuration, frozen six-table `0001`, identity/episode `0002`, atomic validated legacy adoption and `python -m app.migrations` CLI |
| Ingestion | Strict schemas, `routers/telemetry.py`, canonical SHA-256 identity, DB uniqueness and UTC occurrence/receipt handling |
| Transactions | `services/transactions.py`, `services/telemetry.py`, `services/alerts.py`; atomic event/simulation/rental effects and stable alert episodes |
| Operations | Health/readiness, bounded request IDs, JSON completion/ingestion logs, safe 503/500/422 responses and server tracebacks |
| Frontend | FleetSignal title/header, correlated errors, three automatic refresh calls removed; existing adapters, charts, maps, forms, playback and explicit mock mode retained |
| Verification | Isolated fixtures and startup/migration/ingestion/reliability/operations tests; original refresh test intentionally changed to stable-episode behavior |
| Demonstration | `backend/scripts/demo_reliability.py`, `backend/scripts/verify_docker.py` |
| CI/docs | Root `.github/workflows/fleetsignal.yml`, root/project READMEs, API/demo/reliability docs and this report; historical spec/plan labeled historical |

App module paths above are under `backend/`. At submission review, changes were uncommitted; no push, merge, repository rename or external deployment had occurred. The subsequent publication is separately authorized.

### Transaction choice

**BEGIN IMMEDIATE acquires SQLite's writer reservation before identity lookup or rental reads.** The service compares identity, inserts/flushes telemetry, reconciles affected alerts and commits once. Failures roll back flushed telemetry, alert and rental effects. Alert reconciliation never begins or commits independently; simulation batches are atomic. No external service call occurs inside the transaction.

Canonical retries return the original row without evaluating alerts or changing episode fields. Unique event and partial unresolved-alert indexes enforce persistence invariants. SQLite is still single-writer; busy-wait exhaustion returns retryable503. WAL was not selected. The guarantee is retry-safe committed database effects, not distributed delivery or external notifications.

Active alert IDs/creation times survive refresh; cleared conditions resolve into history, and recurrence creates a new episode. This intentionally replaces the old deletion/recreation test. Four hazards are independent, each selecting its newest qualifying evidence in the latest 20 rows ordered by event time and ID.

## Exact executed results

The table below records the preceding implementation pass. The subsequent submission review reran the suite (262 passed in 34.38s, and 262 in 37.71s in a clean environment), fixed the advisory, completed 13 browser checks, and repeated local Docker failure/persistence checks. See [SUBMISSION_REVIEW.md](SUBMISSION_REVIEW.md) for those current results.

Commands omit the sandbox wrapper. Backend commands ran in `backend/`, frontend commands in `frontend/`, Compose commands in the project directory.

| Command/check | Observed outcome |
|---|---|
| Baseline `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider` |95 passed in 5.44s after locked dependency setup restored pytest |
| Baseline `npm run build` |Passed, Vite 8.2.2, 660 modules, 5.62s after restoring checksum-verified Node 22.19.0 |
| Final `uv sync --frozen --extra dev` |Exit 0 |
| Final `uv lock --check` |Exit 0 |
| Final `uv run --frozen python -m app.migrations` |Exit 0, explicit separate SQLite DB, revision 0002 |
| Final `uv run --frozen pytest -q -p no:cacheprovider` |**262 passed in 47.01s**, exit 0; configured normal CI DB hash unchanged |
| Linux CI runtime: same locked install, migration and test commands via Compose exec |**262 passed in 33.52s**, exit 0; Python 3.11.17/uv 0.13.0 with separate `/tmp/fleetsignal-ci.db` |
| Migration gate: `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider tests/test_migrations.py` |20 passed in 3.78s, including CLI, invalid schemas, empty version, rollback and concurrent startup |
| Error-path gate: `.venv/Scripts/python.exe -m pytest tests/test_operations.py tests/test_ingestion.py -q -p no:cacheprovider` |95 passed in 11.16s |
| Initial implementation `npm ci` |Exit 0, 87 packages installed; pre-existing lockfile work preserved; advisory subsequently fixed below |
| Final `npm run build` |Exit 0, Vite 8.2.2, 660 modules, 727ms reported; JS811.90kB/gzip239.47kB; existing bundle warning |
| Focused Node client check |Six cases passed: success, header/body IDs, unsafe IDs/fallback and safe validation message |
| `uv run --frozen python scripts/demo_reliability.py` |All assertions passed: flushed effects roll back, retry succeeds, duplicate/conflict unchanged, app restart and lost-response retry retain identity |
| `git diff --check` |Exit 0 |

Final backend verification set `FLEETSIGNAL_DATABASE_URL=sqlite:///D:/Projects/FleetSignal/caterpillar-smart-rental/.tmp/ci-final.db` and `FLEETSIGNAL_DEMO_MODE=false`. Migrations initialized that separate DB before tests; its before/after byte hash matched. Tests use temporary app resources and sentinel files. Host Python 3.11.14, container Python 3.11.17, Node 22.19.0 and Docker Engine29.2.1 were used. Durations are command observations, not application latency/throughput measurements.

Host uv is 0.9.18; Docker and the hosted workflow pin 0.13.0. The hosted workflow itself has not been executed.

The Linux command was `docker compose -p fleetsignal-fresh-verification exec -T -e FLEETSIGNAL_DATABASE_URL=sqlite:////tmp/fleetsignal-ci.db -e FLEETSIGNAL_DEMO_MODE=false backend sh -c "uv sync --frozen --extra dev && uv run --frozen python -m app.migrations && uv run --frozen pytest -q -p no:cacheprovider"`. It used the existing disposable container and a separate database; it did not run tests against the demonstration volume. Docker briefly became unavailable during an interruption; restarting it restored the retained service before this check.

### Docker evidence

1. `docker compose -p fleetsignal-verification up --build -d --wait` rebuilt and adopted the retained pre-migration verification DB; service became healthy. Inspection confirmed legacy telemetry ID 1 retained null identity/hash/receipt and revision 0002.
2. `.venv/Scripts/python.exe scripts/verify_docker.py --project fleetsignal-verification --base-url http://127.0.0.1:8000` passed ingestion/retry/conflict/stable alerts, an actual separate-connection write lock 503 followed by retry 201, and recreation retaining telemetry ID 4 and alert identity.
3. The first project was stopped, retaining its volume. `docker compose -p fleetsignal-fresh-verification up --build -d --wait` created a fresh named volume and became healthy. Inspection before any writes confirmed revision 0002, seven assets and zero telemetry.
4. The script against the fresh project passed ingestion/lock/recreation retaining ID 1. After final error-path fixes the image was rebuilt. The final script run passed raw non-finite 422, allowed/denied preflight IDs, ingestion/retry/conflict, lock 503/retry 201, and recreation retaining telemetry ID 3.

Volumes retained: `fleetsignal-verification_fleetsignal_db` and `fleetsignal-fresh-verification_fleetsignal_db`. The fresh-project service was last verified locally at `http://127.0.0.1:8000`; the first project is stopped. They contain synthetic data. `docker compose -p fleetsignal-fresh-verification stop` stops the remaining service while preserving its volume.

## Observable acceptance matrix

Each row passed locally through the tests or actual demonstrations. Hosted CI remains unexecuted. The subsequent submission browser walkthrough passed, as recorded in [SUBMISSION_REVIEW.md](SUBMISSION_REVIEW.md).

| Required check | Observable evidence |
|---|---|
| Baseline regression |Original95 cases passed before source changes; missing setup restored |
| Fresh Docker startup |New named volume,ready200,schema 0002,seven assets |
| Restart persistence |Accepted events/alert identity survived recreated containers on both projects |
| Existing SQLite migration |Representative legacy assets/events/telemetry/alerts retained; actual old Docker row retained; unique/FK indexes enforced |
| Test isolation |Sentinel and configured CI DB unchanged; original srts.db unchanged; no default DB created |
| Working directories/data cache |Absolute paths independent of cwd; two apps use distinct DB/data and forecast outputs |
| Demo gating |Routes omitted from ordinary-mode OpenAPI, 404; explicit demo controls work |
| Valid ingestion |201,one row,hazards available without refresh; utilization rates unchanged |
| Exact retry |200,same ID,row count and complete alert timestamps unchanged |
| Semantic equivalence |Omitted/null and equivalent UTC offsets return duplicates |
| Conflicting reuse |Changed asset/time/sensor409 with unchanged state |
| Unknown/invalid body |404/422,no writes; coordinate/numeric/length/extra/timestamp boundaries covered, including raw non-finite JSON |
| Concurrent identical requests |Six requests on separate connections: one 201,five 200,same ID,one row |
| Concurrent conflicts |One201,one 409; stored reading/alerts match the winner |
| Failure after flush |Injected exception after telemetry and alert writes:500,complete state snapshots unchanged |
| Retry after rollback |Same event subsequently201 once with correct hazards |
| Lost response |Discarded committed response then duplicate200; app/file restart also demonstrated |
| Simultaneous hazards |All four telemetry hazards coexist |
| Alert stability |Refresh preserves IDs/created_at and unique active keys; evaluation advances last_seen |
| Resolution/recurrence |Twenty healthy newer readings resolve history; later hazard creates new ID |
| Late events |Inside-window hazard participates; outside persists without evidence replacement |
| Timestamp ties |Descending row ID controls deterministic history/evidence/window membership |
| Simulation |Six scenarios; invalid counts rejected;1/100/default10,fresh IDs,external retries and batch rollback verified |
| Rental changes |Original conflicts retained; state/event/alert failure atomic; successful check-in clears assignment/overdue conditions |
| Readiness failure |Safe503 while liveness remains200 |
| Logs/correlation |IDs on success/errors/preflights; selected JSON fields/tracebacks; no full sensor/contact/customer logging |
| Final regression/build |262 executed cases passed; locked frontend build passed |

## Resolved blockers and scope limits

Review found unknown-schema admission through an empty revision table; its regression now refuses unchanged. Final review found raw numeric validation turning into 500 and preflights bypassing correlation. Both were reproduced with 37 failing regressions, fixed and scoped re-reviewed. The first extra refresh rollback test patched the wrong import; its injection target was corrected and durable rollback verified.

Missing pytest/Node, a stopped Docker daemon and sandbox npm-cache access were resolved locally. A fixed-duration Docker lock demo raced host request setup; synchronized release now verifies503/no-write/retry. Failed attempts were not counted as passing checks.

The initial audit reported one high advisory in transitive development dependency **source-map-js 1.2.1**: [GHSA-68fv-2mgg-jv7q](https://github.com/advisories/GHSA-68fv-2mgg-jv7q), affecting `>=1.0.0 <1.2.2`. Submission review verified both parents accept `^1.2.1` and updated only the lock entry to patched **1.2.2**, preserving all pre-existing metadata removals. Reinstalled dependencies, `npm audit --json` and the frontend build passed; audit reports **zero vulnerabilities**. The existing frontend >500 kB bundle warning remains.

Deferred: PostgreSQL, workers/queues, cloud deployment, streaming, full authentication/authorization, notifications, forecasting/ML changes, load tests and extensive metrics. Hosted GitHub Actions was not executed; local workflow commands, clean setup and the complete browser walkthrough were executed.

SQLite remains single-writer. Alert work is synchronous; the last 20 count window has no time expiry without new readings. L-prefixed faults indicate location mismatch, not GPS geofencing. Future occurrences are allowed for synthetic scenarios. The UI reloads rather than streams. Demo gating is not authentication; real-data deployment needs additional access controls. Exception rollback and app/container restarts were demonstrated; no process-kill recovery, enterprise-scale or distributed exactly-once claim is made.

## Demonstrated resume bullets

- Implemented idempotent telemetry ingestion and transactional alert reconciliation using FastAPI, SQLAlchemy, and SQLite.
- Added integration tests covering duplicate/conflicting events, rollback and retry, concurrent submissions, and late telemetry.
