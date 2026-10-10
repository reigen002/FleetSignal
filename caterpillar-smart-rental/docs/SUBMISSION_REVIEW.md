# FleetSignal submission review

Review date: 2026-10-10. Comparison: **93765221e47233c7b60fe2bdf4d3093070ca7a46** to the working tree, including new files. At review, HEAD was that starting commit and changes were uncommitted. No push, merge, repository rename or external deployment had occurred during the review. The subsequent publication is separately authorized.

## Final diff

| Area | Changes |
|---|---|
| Startup | Typed settings, app-owned engines/sessions, absolute paths, isolated tests, demo controls gated off by default, corrected local Docker packaging |
| Persistence | Validated Alembic adoption/upgrades, telemetry identity/hash/receipt fields, deterministic history index, partial unique active-alert index |
| Services | Identified ingestion, canonical duplicate/conflict decisions, one SQLite transaction for telemetry and alert effects, stable episodes, independent hazards, atomic simulation/rental mutations |
| Operations | Readiness, bounded request IDs, structured logs, safe error responses |
| Frontend | FleetSignal branding, automatic backend alert updates, correlated errors, accurate simulation hint; existing charts/maps/forecast/adapters retained |
| Delivery | Integration tests, local reliability/Docker demonstrations, locked CI configuration, current documentation with historical provenance |

No unrelated implementation change was identified. The existing **78-line libc metadata removal** in `frontend/package-lock.json` predates this work and is preserved. The authorized advisory correction changes only the `source-map-js` version, tarball URL and integrity hash; comparison with the pre-review lockfile confirmed every other entry is identical. Forecast/recommendation edits pass the configured data path; historical documents only gain historical labels.

## Standards

No unresolved findings. The review found an unqualified automatic-seeding comment; it now explicitly requires demo mode. No applicable AGENTS.md or repository coding-standard file was found. Code-smell heuristics did not identify a necessary refactor.

## Spec

No unresolved findings. Two UI issues were corrected: rental conflicts discarded their correlation ID, and the simulation hint still described a removed refresh request. A real browser request reproduced the missing ID before the fix and passed afterward.

The ingestion and rental owners issue `BEGIN IMMEDIATE` before identity/asset reads and commit once after reconciliation. The alert service never begins or commits. Exact duplicates return before reconciliation; conflicts precede writes. SQLite enforces global event uniqueness and one unresolved alert per asset/type. Legacy adoption validates the frozen original schema before stamping; duplicate active episodes are deterministically resolved with history retained.

Failure tests assert telemetry counts, asset state, rental events and alert snapshots through sessions separate from request sessions, expiring cached ORM state before rereading. The demonstration additionally uses a fresh observer session for each snapshot and a new app against the retained file after restart. These establish persisted effects, rather than merely asserting helper calls.

## Verified results

| Executed check | Result |
|---|---|
| Backend `uv run --frozen pytest -q -p no:cacheprovider` | **262 passed in 34.38s** |
| Frontend `npm ci`, `npm audit --json`, `npm run build` | Exit 0; **zero reported vulnerabilities**, 660 modules; final edited interface built in 4.59s |
| Browser, installed Chrome **154.0.8037.98** via isolated Playwright tooling | **13 checks passed**: dashboard/detail, checkout/check-in, all six scenarios, simultaneous hazards, real 409 with matching request ID, zero refresh-endpoint calls and zero JavaScript exceptions |
| Clean source copy without virtual environment, node_modules or databases | Locked installs/migration passed; documented reload startup reached readiness in default and demo modes; both working directories used the same project-local file; frontend install/build/audit passed |
| Complete suite in that newly installed clean environment | **262 passed in 37.71s**; its configured normal database byte hash remained unchanged |
| Local Docker from the clean source copy, fresh named volume | Build/startup reached readiness with seven assets; ingestion/retry/conflict passed; a separate connection's write lock returned retryable 503 with no row, then retry succeeded; container recreation retained telemetry ID **1** and alert identity |
| Disposable `scripts/demo_reliability.py` | Flushed telemetry/alert effects rolled back; retry/duplicate/conflict and app restart/lost-response retry passed |

The real failed browser request displayed `142eb467-bb40-4c90-936d-4188e46139dd`, matching its response header. Map tiles and markers rendered. Browser screenshots, request records and clean-command logs are retained locally under ignored `.tmp/submission-review/`; browser tooling was not added to application dependencies or CI.

Docker Desktop was initially unavailable, then restored. The local verification used project `fleetsignal-submission-verification` and retained volume `fleetsignal-submission-verification_fleetsignal_db`; it did not publish or deploy anything remotely. Original `backend/srts.db` remains unchanged (SHA-256 `CE8D51482A90FEC043C66132C250A72F6313243C7DE1BC234A7DC4CB5A0D9A1B`); tests did not create the working project's default `.fleetsignal/fleetsignal.db`.

The advisory [GHSA-68fv-2mgg-jv7q](https://github.com/advisories/GHSA-68fv-2mgg-jv7q) affects `source-map-js >=1.0.0 <1.2.2`. Installed 1.2.1 was affected. Both PostCSS and Tailwind declare `^1.2.1`, accepting patched **1.2.2**. The registry integrity was verified before the targeted lock edit; reinstall and audit confirmed the fix.

## Remaining limits

SQLite remains single-writer; reconciliation is synchronous and the latest-20 alert window has no time expiry. Location mismatch uses synthetic fault labels, rather than implemented GPS geofencing. The interface reloads state; no streaming or continuous device integration was added. Demo mode is not authentication. The existing bundle warning above 500 kB remains.

At submission review, hosted GitHub Actions had not executed. Publication subsequently ran the hosted tests/builds successfully; see [the publication evidence](COMPLETION_REPORT.md#publication-and-hosted-verification). Cloud deployment, load testing and process-kill recovery remain unexecuted. The Docker work concerns local containers and named-volume persistence. Installation used available registry/cache resources; an offline setup was not tested.

## Three-minute demonstration

Prepare a disposable demo database, the backend with `FLEETSIGNAL_DEMO_MODE=true`, and the real frontend using the README commands. Reset only that disposable demo before starting. Open two tabs on available **EQX1001**; use synthetic customer data and a return date after the fixed business clock `2025-05-12`.

| Time | Action and narration |
|---|---|
| 0:00–0:25 | Show seven assets, EQX1007's recovery recommendation, utilization and weighted-moving-average demand chart. “This is historical synthetic fleet data, with a fixed rental/forecast business date.” |
| 0:25–1:00 | Open EQX1001. In both tabs prepare checkout; submit tab A, then submit stale tab B. Show the real 409 and its request ID. Check in through A, then reload B. “Asset state, lifecycle record and affected alerts commit together; a conflict gives a correlation ID.” |
| 1:00–1:50 | Run Normal, High Idle, Location Mismatch, Abnormal Fuel, Engine Overheat and Seatbelt Violation. Show telemetry playback and the automatically updated anomaly cards, including simultaneous overheat/seatbelt alerts. “Each condition is evaluated independently in the latest 20 readings; location evidence here is synthetic.” |
| 1:50–2:35 | In a terminal from `backend/`, run the disposable failure/retry script below. Read its PASS lines: failed flush leaves no effects; retry inserts once; duplicate/conflict preserve state; app restart preserves committed identity. “The script uses its own temporary SQLite file.” |
| 2:35–3:00 | Show `/ready` and the test/build evidence. “Local Docker retains SQLite in a named volume. This submission demonstrates synchronous transactional reliability; SQLite is single-writer, the UI reloads, and no cloud, scale or process-crash result is claimed.” |

```bash
uv run --frozen python scripts/demo_reliability.py 2> demo-reliability.log
```

The redirected server traceback is expected failure-injection evidence. There is no exposed crash endpoint. Keep setup/build time outside the three-minute presentation; the timings above are a presentation script, not a performance benchmark.

Review summary: Standards **0 unresolved** (one P3 corrected); Spec **0 unresolved** (one P2 and one P3 corrected). No remaining local verification blocker. Hosted CI subsequently passed during publication; the explicitly deferred checks remain unexecuted.
