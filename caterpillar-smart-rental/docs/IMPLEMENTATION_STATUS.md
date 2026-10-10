# FleetSignal execution record

Started 2026-10-10 on `feat/fleetsignal-reliability`, checkout `93765221e47233c7b60fe2bdf4d3093070ca7a46`.
The requested reviewed commit `373050241210d9ad01aa3bbf0e095233b3761e9b` is absent from local git history. Current source is the implementation baseline. No AGENTS.md was found in the project or parent directories.

Existing user change: `frontend/package-lock.json` removes optional package libc metadata. Preserve it.
Current source contains hardcoded seed assets, including checked-out status for EQX1002/1004/1007; CSV still marks those available. Preserve the current rental demo when moving loading to configured files.

## Baseline

- `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider` from backend: initially blocked by missing pytest. `uv sync --frozen --extra dev` resolved dependencies; rerun **95 passed in 5.44s** on Python 3.11.14.
- `npm run build` from frontend: initially blocked by missing Node executable. With local checksum-verified Node 22.19.0, rerun passed: Vite 8.2.2, 660 modules, 5.62s. Existing bundle-size warning (>500 kB) remains.
- `docker version`: installed client 29.2.1; Docker Desktop Linux daemon was initially unavailable; starting the installed daemon enabled actual fresh/legacy startup and persistence verification.
- Original backend/srts.db SHA-256: `CE8D51482A90FEC043C66132C250A72F6313243C7DE1BC234A7DC4CB5A0D9A1B`; unchanged by baseline suite.

## Completed gates

1. Configuration, app factory, isolation, demo gating and packaging: first scoped regression 124 passed in 14.96s; expanded startup33 passed in 4.40s. Sentinel protection, separate app/database/data resources and actual Docker persistence verified.
2. Schema and ingestion: frozen Alembic0001/0002, validated legacy adoption, canonical hashes, global unique IDs, UTC occurrence/receipt and external endpoint implemented. Migration gate 20 passed in 3.78s. Actual old Docker row ID1 retained null event/hash/receipt and revision 0002.
3. Transactions and alerts: BEGIN IMMEDIATE before reads; telemetry/simulation/rental effects atomic with stable independent alert episodes. File-backed concurrency, rollback/retry, lost responses, late/tied events, simulation external retries and rental failures pass.
4. Operations/frontend/CI/docs: liveness/readiness, bounded IDs, JSON logs, safe errors including raw non-finite JSON and CORS preflights; frontend automatic refresh dependency removed, FleetSignal title, locked CI configuration, reproducible demos and active documentation delivered.

## Review findings and verification

- Empty Alembic revision plus unrelated tables bypassed schema validation. Reproduced and fixed; refusal leaves rows/schema/version unchanged. Empty revision alone can initialize fresh schema.
- Raw numeric overflow/NaN validation could return 500 instead of 422; preflight 200/400 skipped correlation. Red 37 failed/1 passed; green 38 targeted passed; operation+ingestion 95 passed in 11.16s. Final scoped review found both fixed.
- First Docker lock demo used timed release and raced request setup. Synchronized release now verifies 503, no partial row, then retry 201.
- First extra refresh-failure test patched the wrong imported symbol. Correct injection target verifies complete state rollback.
- First npm ci was blocked by sandbox cache access. Approved rerun passed; lockfile SHA256 remains AD674DD93976C5CE030EB7411904F67C674D6D8369C611C615E9485438639DFA.

## Final executed checks

- uv sync --frozen --extra dev, uv lock --check and uv run --frozen python -m app.migrations: exit 0, explicit separate absolute SQLite path/demo=false.
- uv run --frozen pytest -q -p no:cacheprovider: **262 passed in 47.01s**, normal configured CI database byte hash unchanged. Original srts.db hash unchanged; default .fleetsignal/fleetsignal.db not created.
- Linux container with pinned uv 0.13.0/Python 3.11.17: locked install, migration and complete suite **262 passed in 33.52s** against separate /tmp database. Docker was restarted after becoming unavailable during interruption; retained volume restored.
- npm ci and npm run build: exit 0, Node 22.19.0/Vite 8.2.2, 660 modules, 727ms final build. Existing bundle warning and source-map-js audit advisory remain; npm audit exits 1.
- Six focused frontend realFetch checks passed.
- Documented isolated reliability script: injected failure after telemetry/alert flush rolled back; retry, duplicate/conflict, app restart and lost-response retry passed.
- Actual fresh and legacy Docker startup/readiness, global event retries/conflicts, write-lock 503/retry 201 and container recreation persistence passed. Both named verification volumes retained.
- Whole-change review and fixes/scoped re-review completed; git diff --check exit 0.

## Rulings

- The supplied plan is approved design/execution authority; work stays on the requested feature branch and preserves unrelated changes.
- File SQLite only, finite busy timeout, per-connection foreign keys and BEGIN IMMEDIATE; no WAL selected. Memory/non-SQLite URLs are rejected.
- Correlation wraps CORS; safe error handling runs inside it so preflights and generated 500 keep IDs/CORS behavior.
- Validation errors project type/loc/msg only, avoiding non-JSON float serialization and invalid input echoing.
- Optional architectures/dependency upgrades remain deferred. Hosted CI and full interactive browser walkthrough were not executed.

Host uv is 0.9.18; Docker and CI pin 0.13.0. At implementation review, source was reviewable and uncommitted, with no push, merge, repository rename or external deployment. [COMPLETION_REPORT.md](COMPLETION_REPORT.md) records the acceptance matrix, exact results and limitations. Subsequent publication is separately authorized.

## Subsequent submission review

The final submission review supersedes the earlier advisory and unexecuted-browser entries above: source-map-js is patched to 1.2.2, npm audit reports zero vulnerabilities, 13 real-browser checks passed, and clean README installs/startups/builds passed. Pre-existing lock metadata removals remain intact. Backend regression passed again: 262 tests in 34.38s; the clean environment passed 262 in 37.71s with its normal database hash unchanged. Docker Desktop was restored; a fresh local project passed ingestion, lock exhaustion/retry and container recreation with its named volume retained. See [SUBMISSION_REVIEW.md](SUBMISSION_REVIEW.md) for current evidence and the three-minute demonstration.

## Subsequent publication

Publication was authorized after review. The branch was committed and pushed, current upstream main was integrated with its CSV/intelligence document preserved, and [PR #1](https://github.com/reigen002/FleetSignal/pull/1) opened. The first hosted run failed workflow validation before any jobs; a one-line database environment correction fixed it. Hosted branch and PR runs then passed, including **262 tests in 22.95s**, migrations, locked installation and the frontend build. See [COMPLETION_REPORT.md](COMPLETION_REPORT.md#publication-and-hosted-verification) for run links and exact evidence. No cloud deployment or repository rename was performed.
