# Telemetry performance and failure evidence

Local measurements collected **2026-11-17–18**, based on `da585de1c293ec9e183be1c8b146b66349192332` plus the diagnostics and harness changes in this patch. The raw results identify the baseline commit and measured source fingerprints. No infrastructure was deployed. These are observations of an instrumented local service, not a production capacity or vehicle-count claim. No speedup against an uninstrumented build is claimed.

## Reproduce without touching an existing database

From `backend/`, using the existing locked Python environment:

```bash
uv sync --frozen --extra dev
uv run --frozen pytest -q -p no:cacheprovider
uv run --frozen python scripts/performance.py --matrix --duration 8 --repeats 2 --output ../.tmp/performance-new.json
uv run --frozen python scripts/performance.py --duration 8 --rate 1000 --concurrency 32 --assets 32 --workers 2 --workload mixed --repeats 2 --output ../.tmp/workers2-new.json
uv run --frozen python scripts/failure_scenarios.py --output ../.tmp/failures-new.json
```

Use new output filenames: both tools refuse to overwrite existing files. `--help` lists bounded load settings. There is deliberately no existing database path or external server URL argument. Each case creates a `TemporaryDirectory`, applies the real migrations, inserts deterministic synthetic fixtures, and starts its own loopback Uvicorn process on a free ephemeral port. Child settings override inherited database/demo configuration. No reset endpoint is called. Read-only inspection connections close explicitly, and only the invocation's owned process tree and temporary files are cleaned up. Sentinel regressions verify that an existing database selected in the caller's environment is unchanged with either one or two workers.

The failure tool reuses its temporary database across a child-process restart, then removes it on completion. It never restarts the user's service. Benchmark files contain aggregate measurements and source fingerprints, not raw event IDs, database contents, credentials, or private temporary paths. The measured code's SHA-256 hashes and dependency versions are recorded in the load JSON.

## Hardware and configuration

| Item | Recorded environment |
|---|---|
| CPU | AMD Ryzen 5 4600H, 6 physical cores / 12 logical CPUs |
| Memory | 16 GiB installed; OS reported 16,497,311,744 usable bytes |
| OS | Windows 11 Home Single Language, build 10.0.26200; Python platform string reports Windows-10 for this build |
| Database storage | Local C: temporary directory on NVMe `MTFDHBA256TDV-1AY1AABHA`, approximately 256 GB |
| Runtime | Python 3.11.14, SQLite 3.50.4, FastAPI 0.111.0, SQLAlchemy 2.0.30, Uvicorn 0.30.1, HTTPX 0.27.0 |
| Deployment shape | One loopback server, 1 or 2 Uvicorn workers; load generator on the same machine |
| SQLite | File-backed; journal mode `delete`, synchronous `2` (FULL), foreign keys enabled; WAL unchanged/off |
| Coordination | Existing `BEGIN IMMEDIATE` before identity lookup, insert, reconciliation, and the single commit |
| Connections | Existing QueuePool, size 5 plus 10 overflow connections per worker; no pool tuning |
| Busy timeout | 5000 ms normally; one explicitly labeled 50 ms contention experiment |
| Initial data | 1 or 32 synthetic available assets; exactly 20 healthy telemetry rows per asset, no initial hazards |
| Timing | 8-second arrival window per case, plus drain; two repeats; fixture creation, first-worker startup/readiness, and audits excluded; remaining-worker startup may overlap |

Other desktop processes were not stopped. CPU utilization, disk utilization, and memory pressure were not profiled. Antivirus, Windows scheduling, filesystem caching, client overhead, and colocated logging can influence these short runs. The deadline regression specifically prevents early asyncio timer wakeups from admitting traffic before its scheduled slot.

## Traffic and measurement definitions

| Workload | Offered requests |
|---|---|
| `unique` | New deterministic event IDs; every fifth event has overheat/seatbelt hazards |
| `duplicate` | Identical retries of fixture events, expected 200 with original telemetry ID |
| `conflict` | Same fixture event ID with changed temperature, expected 409 |
| `late` | New hazardous events older than the complete latest-20 window, expected 201 without replacing recent evidence |
| `mixed` | Repeating ten-slot mix: 60% unique, 20% identical duplicate, 10% conflicting, 10% late |

Assets are selected round-robin by offered index. Admitted mixes can differ because capacity drops depend on earlier requests; each JSON run records its actual admitted mix. A one-asset case concentrates work on one asset; a 32-asset case spreads offered requests across the fleet. Their initial database sizes differ, so this is not an isolated experiment on asset count alone.

The generator is open-loop with a fixed arrival schedule and a bounded in-flight request cap. It drops an arrival at the cap instead of building an unbounded client queue. A late generator catches up; dispatch lag is recorded. Every admitted task result is collected, including transport failures; programming exceptions fail the run.

- **Target RPS** is the configured arrival schedule, not measured throughput.
- **Observed offered RPS** is arrival slots divided by the measured offering window. **Admitted RPS** counts actual sends over that window. Drops are explicitly separate.
- **Completed HTTP RPS** includes 200, 201, expected 409, and retryable 503 responses, divided by elapsed time including the drain. It is not the rate of committed new events.
- **Committed new events RPS** counts audited 201 responses over that same elapsed time. **Expected-outcome RPS** counts contract-matching responses, including expected conflicts; it is not new-event goodput.
- HTTP p50/p95/p99 use nearest rank over completed HTTP requests and include connection setup, all statuses, and client overhead. Transport failures and dropped slots have no HTTP latency sample. Scheduled-to-completion percentiles additionally include dispatch delay for completed requests.
- These are conditional completion percentiles, not an SLA over all offered arrivals. No synthetic latency or coordinated-omission correction is assigned to dropped arrivals. The raw JSON retains denominators, drain time, dispatch lag, admitted mix, status counts, and observed server transaction signals.

After every case, an independent SQLite inspection checks committed event IDs/row IDs against 201 responses, checks original IDs for duplicates, runs integrity/FK checks, verifies unique active alerts, and compares alert types against the actual newest 20 rows. Conflicts are deliberate test outcomes; retryable 503s are measured failures to accept that offered event. Unexpected HTTP statuses, malformed responses/logs, transport errors, or failed audits fail verification.

## Recorded measurements

Raw evidence: [22-case matrix](performance/local-2026-11-17.json), [two later worker-comparison cases](performance/workers2-2026-11-18.json), and [six fault cases](performance/failures-2026-11-18.json).

All 24 cases passed their telemetry/alert/integrity audits. Source fingerprints matched the measured files; transaction/ingestion log counts matched admitted requests; SQLite busy records matched 503 responses. There were **zero unexpected HTTP responses, zero transport errors, and zero malformed JSON log lines**. Across all cases, status counts were {'201': 10595, '503': 1474, '200': 4801, '409': 4103}; total offered slots were 76,800, admitted/completed requests 20,973, and admission drops 55,827. These totals combine different workloads and are not a single throughput measurement.

The table below is **repeat 1** of the matrix. Both complete repeats are retained in JSON; percentiles are not averaged or pooled. W/C/A means workers / maximum in-flight requests / assets. New/s means audited new committed events per second. Counts include expected 409 conflicts and measured retryable 503s.

| Workload | W/C/A | Target/s | Sent/s | HTTP/s | New/s | p50 / p95 / p99 ms | Dropped | 200 / 201 / 409 / 503 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| unique | 1/1/1 | 200 | 48.05 | 48.05 | 48.05 | 13.17 / 27.07 / 30.23 | 1215 | 0 / 385 / 0 / 0 |
| unique | 1/8/1 | 200 | 61.12 | 59.83 | 59.83 | 45.71 / 569.52 / 1615.05 | 1111 | 0 / 489 / 0 / 0 |
| unique | 1/32/1 | 200 | 76.99 | 66.62 | 65.75 | 229.16 / 795.75 / 5920.69 | 984 | 0 / 608 / 0 / 8 |
| mixed | 1/16/1 | 200 | 78.42 | 73.66 | 53.37 | 28.10 / 971.38 / 3479.28 | 972 | 111 / 455 / 62 / 0 |
| mixed | 1/16/32 | 200 | 98.18 | 93.41 | 65.72 | 21.59 / 727.66 / 3125.07 | 814 | 148 / 553 / 83 / 2 |
| duplicate | 1/16/32 | 200 | 199.95 | 199.88 | 0.00 | 10.00 / 54.15 / 202.59 | 0 | 1600 / 0 / 0 / 0 |
| conflict | 1/16/32 | 200 | 199.93 | 199.85 | 0.00 | 6.87 / 45.40 / 117.91 | 0 | 0 / 0 / 1600 / 0 |
| late | 1/16/32 | 200 | 91.07 | 85.69 | 85.46 | 21.40 / 834.68 / 3973.96 | 871 | 0 / 727 / 0 / 2 |
| mixed | 2/16/32 | 200 | 80.09 | 75.05 | 53.63 | 22.05 / 1060.91 / 4005.03 | 959 | 109 / 458 / 74 / 0 |
| mixed | 1/32/32 | 1000 | 124.97 | 109.52 | 75.79 | 146.38 / 306.02 / 4846.82 | 7000 | 193 / 692 / 108 / 7 |
| mixed (50 ms busy) | 1/32/32 | 1000 | 146.68 | 143.16 | 45.81 | 226.79 / 389.71 / 447.46 | 6825 | 104 / 376 / 38 / 657 |

The matching two-worker overload configuration was measured in a **later batch on November 18**. These are separate short observations, not randomized paired trials; host/storage conditions may have changed. Their timestamp and full configuration are retained in the separate JSON.

| Repeat | Workload | W/C/A | Target/s | Sent/s | HTTP/s | New/s | p50 / p95 / p99 ms | Dropped | 200 / 201 / 409 / 503 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | mixed | 2/32/32 | 1000 | 82.61 | 66.12 | 45.52 | 93.34 / 2810.89 / 6288.57 | 7339 | 127 / 455 / 62 / 17 |
| 2 | mixed | 2/32/32 | 1000 | 75.93 | 61.29 | 42.64 | 56.77 / 3600.63 / 6043.85 | 7392 | 120 / 423 / 49 / 16 |


## Operational diagnostics

Existing request-completion logs still contain validated request correlation, route template, HTTP status, and request duration. Ingestion logs retain their existing accepted/duplicate/conflict/not-found/unavailable/error outcomes and add service duration. The request-scoped SQLAlchemy session carries the same request ID into a new `write_transaction` JSON record:

- Bounded fields: `outcome` (`committed`, `rolled_back`, `busy`, `unavailable`), `phase` (`acquire`, `work`, `commit`), and `sqlite_error` (null, `SQLITE_BUSY`, or `SQLITE_LOCKED`).
- Timing: `lock_acquire_ms`, `commit_ms` when commit was attempted, and total `elapsed_ms`. Acquisition includes connection-pool checkout; on failed acquisition it includes rollback cleanup. It is not a pure SQLite lock-wait histogram.
- Expected busy/unavailable failures log at warning without a traceback. Unexpected failures retain the existing correlated error traceback and safe HTTP 500 contract.

Aggregate counts/histograms by bounded outcome, phase, and HTTP status. Existing request/event/asset IDs remain log correlation fields and must not become metric labels. No in-memory process-global counter, metrics endpoint, or monitoring infrastructure was added; counts from all workers can be aggregated from structured logs. A killed process cannot emit a final transaction record, so absence of a log record is not proof of no commit.

All measurements include this instrumentation. Logging overhead is part of the measured service; it was not profiled separately. No dependency, database model, index, migration, response body, event identity rule, busy-timeout default, alert rule, or deployment worker default changed.

## Failure injection and regression evidence

The executable failure suite uses the actual transaction/service code and real HTTP where relevant. Exception patches are confined to a local TestClient app; no fault switch or crash endpoint is installed in the application.

| Scenario | Injection and asserted contract |
|---|---|
| After telemetry insertion | Raise at reconciliation entry after telemetry flush; safe correlated 500, full telemetry/alert snapshot unchanged; same-event retry 201, subsequent duplicate 200 with unchanged effects |
| Interrupted reconciliation | Execute reconciliation and flush alert writes, then raise before commit; same full rollback/retry/duplicate assertions |
| Lock timeout | Hold a real separate-connection `BEGIN IMMEDIATE`; request returns 503 with `Retry-After: 1`, liveness remains 200, no writes; release and retry returns 201 |
| Lost response | Send a real HTTP request over a socket, independently observe its commit, close without reading response bytes; retry returns 200/original identity with unchanged complete snapshots |
| Process restart | Receive 201, hard-terminate the owned Windows process tree (SIGKILL on POSIX), restart against the same file, read before replay, then require 200/original identity and unchanged telemetry/alerts |
| Out-of-order arrival | Reverse normal event arrival order; an older outside-window hazard persists without changing alerts, while an inside-window late hazard activates both independent rules |

Acknowledgement loss is a deliberately discarded response, not a simulated network partition. Exceptions before commit are not hard kills during an uncommitted transaction. The restart result demonstrates survival of acknowledged local commits across this process interruption; it does not prove power-loss, disk failure, EC2/EBS persistence, or distributed exactly-once delivery.

Exact command evidence (commands ran from backend/ unless noted):

| Command | Observed result |
|---|---|
| Before changes: uv run --frozen --extra dev pytest -q -p no:cacheprovider | 262 passed in 38.97s |
| New diagnostics/load/failure regressions: uv run --frozen pytest -q -p no:cacheprovider --tb=short tests/test_diagnostics.py tests/test_performance.py | 9 passed in 12.66s before the final full-suite run |
| Final: uv run --frozen pytest -q -p no:cacheprovider --tb=short | 271 passed in 50.28s; all 262 existing tests retained |
| Project root: docker compose -f docker-compose.yml config --quiet | Exit 0 |
| Project root: docker compose -f deploy/aws/compose.yaml config --quiet | Exit 0 |
| Project root: uvx --from cfn-lint==1.57.2 cfn-lint deploy/aws/cloudformation.yaml | Exit 0; local schema lint only |
| Project root: git diff --check, plus separate checks for all eight untracked files | Exit 0 for tracked check; no whitespace diagnostics in new files |
| Documentation/artifact review | Exact 14-file scope and empty index verified; local links, report Bash syntax, JSON accounting, and source fingerprints passed |
| Project root: python deploy/aws/test_deployment.py | Exit 1: 27 CIDR cases passed, but the 14 Docker-based storage cases could not start because Docker Desktop's Linux daemon was stopped; deployment files were not changed |
| uv run --frozen python scripts/performance.py --matrix --duration 8 --repeats 2 --output ../docs/performance/local-2026-11-17.json | 22 completed and independently audited cases; saved records and source fingerprints validated after continuation |
| uv run --frozen python scripts/performance.py --duration 8 --rate 1000 --concurrency 32 --assets 32 --workers 2 --workload mixed --repeats 2 --output ../docs/performance/workers2-2026-11-18.json | Exit 0; two audited cases |
| uv run --frozen python scripts/failure_scenarios.py --output ../docs/performance/failures-2026-11-18.json | Exit 0; all six named scenarios passed |

All nine new regression cases are also part of the 271-test total. During development, tests exposed missing signals, Windows SQLite inspection connections that were not closed, a worker-handle cleanup race, and early timer wakeups. These were corrected before the final dataset; exploratory measurements remain in ignored review artifacts and are not used above. Read-only inspection now closes its connections, cleanup retries only the owned temporary directory for bounded Windows sharing violations, and an early-wakeup regression protects arrival pacing.

SHA-256 checks of the existing project database and legacy backend/srts.db matched before and after final regression/fault verification. This supplements the sentinel tests; it is not a claim about filesystem changes outside that verification interval. No frontend files changed, and no new frontend build was needed for this backend-only patch. These local results were recorded before publication; subsequent hosted execution of the existing backend test discovery is separate evidence in [GitHub Actions](https://github.com/reigen002/FleetSignal/actions). Authenticated AWS API validation and live deployment remain unverified.


## Bottlenecks, worker count, and limits

The observations support a local serialization/queueing limit, rather than linear gains from concurrency:

- With one worker and one asset at 200 target arrivals/s, one in-flight request completed **48.05–56.45 new events/s**, with p95 **15.48–27.07 ms**. Eight in-flight requests completed **59.83–60.56/s**, but p95 rose to **569.52–597.37 ms**. At 32 in-flight, total HTTP throughput was **66.62–79.85/s**, including **8/11 busy responses**, while p99 reached **5920.69/6090.05 ms**. Concurrency increased waiting much more than durable new-event throughput.
- In the first 32-concurrency unique run, acquisition p95 was **763.561 ms** and commit p95 **4.753 ms**. Those are separate percentile distributions, not values to subtract. The signal is consistent with contention/pool queueing before work; real SQLITE_BUSY records confirm reservation failures. The latest-20 query used the existing **ix_telemetry_asset_timestamp_id** index, according to EXPLAIN QUERY PLAN.
- Pure duplicate traffic reached **194.12–199.88 HTTP responses/s**, and pure conflicts about **199.85–199.88/s**, but both committed **zero new events**. These faster paths still obtain the reservation, then skip insertion/reconciliation. Their rates must not be presented as durable ingest capacity.
- For mixed traffic across 32 assets at 200 target arrivals/s and concurrency 16, one worker completed **89.72–93.41 HTTP/s** and **63.53–65.72 new events/s**; two workers completed **74.03–75.05 HTTP/s** and **51.84–53.63 new events/s**. Both same-matrix repeats showed no gain from the second worker. The later overload results also showed no gain, but their different collection time and higher commit timings are additional confounders. This does not establish that two workers are always slower.
- At 1000 target arrivals/s, 32 in-flight requests, and one worker, the default 5000 ms timeout produced **109.52–112.14 HTTP/s**, **73.82–75.79 new events/s**, and **7/10 busy responses**. Reducing the timeout to 50 ms produced **143.16–163.34 HTTP/s**, but only **45.81–50.42 new events/s**, with **657/734 busy responses**. Faster rejection inflated response throughput; it did not improve successful ingestion. The application default was not changed.
- The 50 ms experiment still had HTTP p95 **305.48–389.71 ms**. SQLite's per-operation busy timeout is not an end-to-end request deadline: connection checkout, thread scheduling, application work, and HTTP overhead remain. The generator's own admission drops and the colocated host must also be considered before assigning a latency cause.


SQLite permits one writer for the entire database, including traffic for different assets. Duplicates also acquire the existing writer reservation before identity comparison. [SQLite isolation](https://www.sqlite.org/isolation.html) and [transaction documentation](https://www.sqlite.org/lang_transaction.html) describe this constraint and possible busy failures at BEGIN/COMMIT. The partial unresolved-alert and global event-ID uniqueness indexes continue to enforce correctness.

Increasing worker count provides additional Python processes, request execution capacity, and connection pools. [Uvicorn uses spawned worker processes](https://www.uvicorn.org/deployment/), including on Windows. It does not create additional SQLite writers, remove synchronous reconciliation/commit work, or bypass storage latency. More contenders can increase waiting and busy responses. Acquisition metrics also include [SQLAlchemy pool checkout](https://docs.sqlalchemy.org/en/20/core/pooling.html), so they cannot by themselves separate pool pressure from SQLite reservation waiting. No CPU/flamegraph evidence was collected to assign every latency component to one subsystem.

These results describe a small deterministic fleet, short local runs, synthetic payloads, one host, and the stated admission policy. They do not establish production scale, high availability, 100,000 vehicles, internet/TLS latency, sustained capacity over hours, backups, failover, or machine restart durability. No PostgreSQL/Kafka migration or future architecture is implemented or proposed as part of this patch. A change to storage or asynchronous ingestion needs a separate workload-driven design, explicit authorization, and preservation or renegotiation of the current commit/alert/identity contract.

## Defensible resume bullets

- Built a reproducible HTTP load and six-scenario failure-injection suite for a FastAPI/SQLAlchemy telemetry service, measuring offered versus completed throughput and p50/p95/p99 latency on disposable SQLite databases.
- Added correlated transaction-duration and SQLite contention diagnostics while preserving idempotent ingestion, atomic alert reconciliation, and safe retry/error contracts.

Use the actual measurements and limitations above in an interview. These bullets do not claim an AWS deployment or an improvement against an unmeasured baseline.
