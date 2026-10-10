# Caterpillar Smart Rental Tracking System — Implementation Plan

> **Historical reference:** This is the original SRTS hackathon implementation plan. Its setup and architecture statements describe that phase; use [README](../README.md), [API_CONTRACT.md](API_CONTRACT.md), and [RELIABILITY.md](RELIABILITY.md) for current FleetSignal behavior.

> **For the implementing agents:** This is the handoff document. It is self-contained — you do not need the planning conversation. Read `docs/HACKATHON_SPEC.md` (authoritative product spec) and `docs/API_CONTRACT.md` (frozen FE/BE boundary) alongside it. Build only what is described here; the spec's MVP priority order (§15) governs any cut.

**Goal:** A polished, reliable vertical slice that lets a Caterpillar dealer move **Know → Detect → Explain → Predict → Act** across a rented fleet, backed by the official 7-asset dataset.

**Architecture:** Two local processes — a FastAPI+SQLite backend serving a REST API, and a React+Vite frontend consuming it — plus a set of deterministic seed/scenario data files. All "AI" (anomalies, forecast, recommendations) is explainable rule/statistics code living as ordinary backend services. No Docker, no message bus, no external accounts.

**Tech Stack:** React 18 + Vite + Tailwind + Leaflet/OpenStreetMap (frontend). FastAPI + Uvicorn + SQLite + SQLAlchemy + NumPy (backend). Deterministic CSV/JSON data files (data).

**Spec:** `caterpillar-smart-rental/docs/HACKATHON_SPEC.md`

## Global Constraints

- **Official dataset is read-only.** The 7 rows in HACKATHON_SPEC §8 (transcribed in `data/seed/official_assets.csv`) are never reconstructed, modified, or replaced. `NULL` site/operator are meaningful and stay visible. Preserve `EQX1002.type = "Cater"` exactly.
- **Determinism.** `DEMO_NOW = 2025-05-12T09:00:00` is the fixed "current" clock. No `datetime.now()`, no random seeds without a fixed value, no live external data. Telemetry is pre-generated and played back client-side.
- **No Docker** for the primary path. Everything runs as local processes started by `scripts/dev.sh`.
- **Data-backed only.** Every anomaly/forecast/recommendation carries inspectable evidence (condition → evidence → severity → action). No unexplained "AI detected an issue."
- **One story over many features.** MVP priority order = HACKATHON_SPEC §15. When time is short, cut from the bottom of that list, never the top.
- **Ports:** backend `8000`, frontend `5173`. CORS open to `5173` only.

---

## 1. Current Repository Assessment

Inspected at planning time:

- The repo `reigen002/Edgerunners-SRTS` contains the project under `caterpillar-smart-rental/`.
- **Every file was an empty (0-byte) placeholder** except `HACKATHON_SPEC.md`, which the user has now populated and is authoritative. `README.md`, `docker-compose.yml`, `API_CONTRACT.md`, `DEMO_FLOW.md` were empty; `API_CONTRACT.md` and `DEMO_FLOW.md` are now written by this planning pass.
- `backend/` and `frontend/` exist but are empty. `data/seed`, `data/scenarios`, `scripts/` are effectively empty.
- **Branches already exist and map to the team:** `feature/backend` (Jimmy), `feature/frontend` (Yash), `feature/intelligence-data` (Ms Bean), all off `develop`; `main` is the integration/release branch. Remote `origin` = the GitHub repo.
- **Preserve:** the directory layout, the branch structure, `HACKATHON_SPEC.md`.
- **Change/add:** everything under `backend/`, `frontend/`, `data/`, `scripts/` per this plan. `docker-compose.yml` stays empty/ignored (no Docker).
- **Missing (this plan supplies):** the entire application, the seed/scenario data, the dev runner.

---

## 2. Product Scope

**In:** Fleet dashboard → identify a problem asset → asset detail (rental/site/operator/usage/telemetry) → anomaly with evidence → alert → recommendation → demand forecast → allocation recommendation → check-in/check-out → lifecycle history → map. This is the full vertical slice the spec's "Definition of a Strong Solution" (§17) requires, and no more.

**Explicitly optimized for:** demo reliability, integration simplicity, explainability, visual clarity, fast implementation. **Not** for feature count.

**Out:** see §26.

---

## 3. Architecture

```
                 data/ (Ms Bean, feature/intelligence-data)
                   seed/*.csv  scenarios/*.json  coaching/*.md
                          │  (read-only inputs, loaded at startup)
                          ▼
  ┌─────────────────────────────────────────┐        ┌──────────────────────────┐
  │ backend/  (Jimmy, feature/backend)        │  HTTP  │ frontend/ (Yash,          │
  │ FastAPI + Uvicorn  :8000                  │◀──────▶│ feature/frontend)         │
  │  seed.py → SQLite (srts.db)               │  /api  │ React + Vite  :5173       │
  │  services: utilization, anomalies,        │  JSON  │ Leaflet map, tables,      │
  │   forecast, recommendations, telemetry_sim│        │ charts, timeline, modals  │
  │  routers: assets/alerts/telemetry/...     │        │ client-side telemetry     │
  └─────────────────────────────────────────┘        │ playback                  │
                                                       └──────────────────────────┘
        scripts/dev.sh starts both processes; no Docker.
```

- SQLite is seeded from CSVs at startup (rebuilt each run → reproducible). Derived intelligence (utilization, anomalies, forecast, recommendations) is **computed on read** from DB rows + threshold config; it is not a separate service or platform.
- Telemetry is generated deterministically at startup from `telemetry_scenarios.json` and served as a full series; the frontend animates it.

---

## 4. Component Responsibilities

| Component | Owner | Responsibility |
|---|---|---|
| `data/seed`, `data/scenarios` | Ms Bean | Official CSV (verbatim), supplementary sites/operators/customers/demand, anomaly thresholds, telemetry scenario params, coaching content, golden validation values. **Files only, no code.** |
| `backend/app` | Jimmy | Seed loader, SQLite, REST API per contract, the 5 intelligence services, lifecycle/check-in-out, telemetry generator. |
| `frontend/src` | Yash | Dashboard, asset detail, map, alerts, telemetry playback, charts, lifecycle timeline, forecast/recommendation panels, check-in/out UI, final demo polish (Impeccable). |
| `scripts/dev.sh` | Jimmy (Yash reviews) | Start both processes locally. |
| `docs/*` | Planning (frozen) | Spec, contract, demo flow, this plan. |

---

## 5. Repository / File Ownership

Each person owns a top-level directory → **no shared-file edits**. Cross-boundary artifacts: `API_CONTRACT.md` (frozen after kickoff) and the `data/` files (Ms Bean writes, Jimmy reads — Jimmy never edits data, Ms Bean never edits code).

```
caterpillar-smart-rental/
├── docs/                         # frozen (planning)
├── backend/                      # JIMMY  (branch: feature/backend)
│   ├── app/
│   │   ├── main.py               # FastAPI app, CORS, router mounting, startup seed
│   │   ├── config.py             # DEMO_NOW, paths, load thresholds.json
│   │   ├── db.py                 # sqlite connect + schema init
│   │   ├── seed.py               # CSV/JSON → tables
│   │   ├── schemas.py            # pydantic response models (contract shapes)
│   │   ├── routers/
│   │   │   ├── assets.py  alerts.py  telemetry.py  sites.py
│   │   │   ├── lifecycle.py       # checkout/checkin/events
│   │   │   ├── forecast.py  recommendations.py  health.py
│   │   └── services/
│   │       ├── utilization.py  anomalies.py  forecast.py
│   │       ├── recommendations.py  telemetry_sim.py  lifecycle.py
│   ├── tests/                    # pytest
│   ├── requirements.txt
│   └── run.sh                    # uvicorn app.main:app --reload --port 8000
├── frontend/                     # YASH  (branch: feature/frontend)
│   ├── index.html  package.json  vite.config.js  tailwind.config.js
│   └── src/
│       ├── main.jsx  App.jsx
│       ├── api/client.js         # fetch wrappers, BASE=http://localhost:8000/api
│       ├── pages/{Dashboard,AssetDetail}.jsx
│       └── components/{FleetTable,FleetMap,AlertsFeed,UtilizationChart,
│           TelemetryPanel,LifecycleTimeline,ForecastPanel,
│           RecommendationPanel,CheckInOutModal,AnomalyCard,SafetyCoaching}.jsx
├── data/                         # MS BEAN  (branch: feature/intelligence-data)
│   ├── seed/{official_assets.csv,sites.csv,operators.csv,customers.csv,demand_history.csv}
│   └── scenarios/{asset_state.csv,telemetry_scenarios.json,anomaly_thresholds.json,
│       golden_insights.json, coaching/{seatbelt.md,overheat.md,low_utilization.md}}
└── scripts/{dev.sh, seed_check.py}
```

---

## 6. Data Model (SQLite — `backend/srts.db`, rebuilt each startup)

```sql
assets(equipment_id PK, type, site_id NULL, checkout_date, checkin_date,
       engine_hours_per_day REAL, idle_hours_per_day REAL, operating_days INT,
       last_operator_id NULL, source DEFAULT 'official')   -- from official_assets.csv
sites(site_id PK, name, lat REAL, lon REAL, region)         -- sites.csv (+depot)
operators(operator_id PK, name, safety_score INT)           -- operators.csv
customers(customer_id PK, name)                             -- customers.csv
assignments(equipment_id PK FK, site_id NULL, operator_id NULL, customer_id NULL,
            expected_checkin NULL, current_state)           -- from asset_state.csv, mutated by check-in/out
telemetry(id PK, asset_id FK, ts, lat, lon, engine_on, engine_hours, idle_minutes,
          fuel_pct, fuel_rate_lph, engine_temp_c, seatbelt, fault_code)  -- generated
events(id PK, asset_id FK, ts, type, title, detail, actor)  -- lifecycle timeline
demand_history(site_id, equipment_type, period, count)      -- demand_history.csv
```

- **Derived, never stored:** utilization %, anomalies, alerts, forecasts, recommendations, status. Computed on read so they always reflect current assignment/check-in state.
- `assignments.current_state` seeds from `asset_state.csv` and is the only table mutated at runtime (by check-in/out). Official `assets` rows are never mutated.

---

## 7. API / Data Contracts

Fully specified in **`docs/API_CONTRACT.md`** (frozen). Summary of endpoints: `GET /api/assets`, `/assets/{id}`, `/assets/{id}/telemetry`, `/assets/{id}/events`, `/api/alerts`, `/api/sites`, `/api/operators`, `POST /assets/{id}/checkout`, `POST /assets/{id}/checkin`, `GET /api/forecast`, `/api/recommendations`, `/api/health`. Object shapes: AssetSummary, AssetDetail, Anomaly, Alert, TelemetryFrame, LifecycleEvent, Recommendation, Forecast. **Mock-first rule** (contract §4): Jimmy ships hardcoded-but-correct-shape responses in hour 1 so Yash is never blocked.

---

## 8. Frontend Structure

**Two pages, component-driven, all data from the API client.**

- **Dashboard** (`/`): header KPIs (fleet size, # assets needing attention, # HIGH alerts, avg utilization) · `FleetTable` (sortable, color-coded by highest severity, EQX1002 visibly red) · `FleetMap` (Leaflet, site + asset markers) · `AlertsFeed` (severity-sorted). Clicking a row/marker → Asset Detail.
- **Asset Detail** (`/asset/:id`): identity + status header · assignment (site/operator/customer/expected return, NULLs shown as "Unassigned") · `UtilizationChart` (engine vs idle) · `AnomalyCard[]` (condition/evidence/severity/action) · `TelemetryPanel` (live playback + map trace + gauges) · `SafetyCoaching` (opens coaching content on a safety anomaly) · `LifecycleTimeline` · `RecommendationPanel` · `CheckInOutModal` trigger.
- **Forecast/Recommendation**: a panel on the dashboard (or a third tab) showing `ForecastPanel` (history + forecast bars) feeding `RecommendationPanel` (allocation).
- `api/client.js` centralizes `fetch`; a single `BASE` constant. No state library needed — `useEffect` + local state is enough for 2 pages (YAGNI on Redux).
- Design via the Impeccable skill; keep it clean, high-contrast, dealer-ops feel.

---

## 9. Backend Structure

FastAPI app; routers thin, services hold logic. Startup: `db.init()` → `seed.load_all()` → `telemetry_sim.generate_all()`. Services are pure functions over DB rows + `anomaly_thresholds.json`, returning contract shapes. `config.DEMO_NOW` injected everywhere a "now" is needed. `requirements.txt`: `fastapi uvicorn[standard] sqlalchemy pydantic numpy` (pandas was considered but skipped — stdlib `csv`/NumPy proved enough).

---

## 10. Telemetry Simulation Design

**Feature — Telemetry simulation**
- **Purpose:** Demonstrate live machine data (location, engine, fuel, temp, seatbelt, faults) without real IoT.
- **Owner:** Jimmy (generator) + Ms Bean (scenario parameters).
- **Inputs:** `data/scenarios/telemetry_scenarios.json` — per asset: `{ waypoints:[[lat,lon],...], frame_count, base_temp_c, temp_ramp_at_frame, seatbelt_off_frames:[...], base_fuel_pct, fuel_rate_lph, fault_at_frame:{frame,code} }`. Only assets that are "out" at DEMO_NOW get a scenario (primarily **EQX1004**; optionally EQX1002/EQX1007 as stationary/idle traces).
- **Outputs:** deterministic `telemetry` rows (a fixed series per asset), served by `GET /assets/{id}/telemetry`.
- **Dependencies:** sites.csv (for site coords / mismatch), anomaly thresholds (temp/fuel/seatbelt limits).
- **Implementation boundary:** pure function `generate(asset, scenario) -> [TelemetryFrame]`; no wall-clock, no randomness (interpolate along waypoints, ramp temperature linearly from `temp_ramp_at_frame`). Frontend plays frames on a `setInterval`; the overheat/seatbelt event lands at a known frame index → fires on cue.
- **Acceptance:** EQX1004's series interpolates a route; at the scripted frame `engine_temp_c` crosses the overheat threshold and `seatbelt` reads `OFF` and `fault_code` = `E-OVERHEAT`. Re-running the backend produces byte-identical series.

---

## 11. Usage / Utilization Calculations

**Feature — Utilization**
- **Purpose:** Quantify whether an asset is productively used vs idle.
- **Owner:** Jimmy.
- **Inputs:** `engine_hours_per_day`, `idle_hours_per_day`, `operating_days` from official row.
- **Outputs:** `utilization_pct = round(engine / (engine + idle) * 100)` (both zero → `0`); `productive_hours_total = engine * operating_days`; `idle_hours_total = idle * operating_days`.
- **Dependencies:** none.
- **Boundary:** pure function in `utilization.py`.
- **Acceptance (from official data):** EQX1002 → 0%, EQX1007 → 0%, EQX1001 → 13%, EQX1004 → 18%, EQX1006 → 33%, EQX1003 → 94%, EQX1005 → 100%. These exact values are asserted in tests and stored in `golden_insights.json`.

---

## 12. Anomaly Detection Logic

**Feature — Anomaly engine** (explainable, rule-based)
- **Purpose:** Detect and *explain* problem conditions; never a black box.
- **Owner:** Jimmy (engine) + Ms Bean (threshold values in `anomaly_thresholds.json`).
- **Inputs:** asset row + assignment + latest telemetry frame + thresholds + `DEMO_NOW`.
- **Outputs:** `Anomaly[]` (contract §2.2), each with `condition / evidence / severity / recommended_action`.
- **Dependencies:** utilization, telemetry, lifecycle status.
- **Rules (thresholds live in the config file, values below are defaults):**

| code | condition | severity | recommended_action |
|---|---|---|---|
| `missing_site` | `site_id` is null | HIGH | Review asset assignment; update rental records. |
| `missing_operator` | operator is null | HIGH | Assign/record an operator. |
| `zero_productive` | engine_hours/day == 0 | HIGH | Verify the asset is needed; consider recall. |
| `low_utilization` | utilization < 30% | HIGH if <10 else MEDIUM | Review requirement; consider early return/reallocation. |
| `excessive_idle` | idle_hours/day ≥ 6 | HIGH if ≥10 else MEDIUM | Investigate why the machine sits idle. |
| `overdue_return` | DEMO_NOW > checkin_date and state ≠ RETURNED | HIGH | Recover the asset; update records. |
| `return_approaching` | 0 ≤ (checkin_date − DEMO_NOW) ≤ 5 days | MEDIUM | Prepare for return/renewal. |
| `engine_overheat` | telemetry engine_temp_c > 105 | HIGH | Inspect cooling system before continued operation. |
| `unsafe_seatbelt` | seatbelt == OFF while engine_on | HIGH | Notify operator; deliver safety coaching. |
| `location_mismatch` | haversine(telemetry, assigned site) > 5 km | HIGH | Verify current location and assignment. |
| `abnormal_fuel` | fuel_rate_lph > threshold (e.g. 25) | MEDIUM | Check for leak/inefficiency; inspect. |

- **Boundary:** `anomalies.py: detect(asset_ctx) -> Anomaly[]`. Evidence strings are built from real values (e.g. the spec's §14 EQX1002 wording).
- **Acceptance:** EQX1002 yields at least `missing_site, missing_operator, zero_productive, low_utilization, excessive_idle, overdue_return` (all HIGH except idle/util per thresholds); EQX1003 and EQX1005 yield **no** utilization/idle anomalies. Matches `golden_insights.json`.

---

## 13. Alert Model

**Feature — Alerts feed**
- **Purpose:** Fleet-wide, actionable, prioritized surfacing of anomalies (spec §4.4: what happened → why it matters → what to do).
- **Owner:** Jimmy (feed) + Yash (UI).
- **Inputs:** all assets' anomalies.
- **Outputs:** `Alert[]` (contract §2.3), sorted severity desc then asset_id, filterable by `severity`/`asset_id`.
- **Dependencies:** anomaly engine.
- **Boundary:** `GET /api/alerts` flattens anomalies into alerts with a stable `id` and `created_at = DEMO_NOW`. No external email/SMS (in-app only; see §26).
- **Acceptance:** EQX1002 and EQX1007 appear with HIGH alerts at the top; each alert shows message + recommended_action.

---

## 14. Forecasting Approach

**Feature — Demand forecast**
- **Purpose:** Predict near-term equipment demand by site+type and connect it to allocation (spec §4.5).
- **Owner:** Ms Bean (historical demand data) + Jimmy (math).
- **Inputs:** `data/seed/demand_history.csv` (site_id, equipment_type, period `YYYY-MM`, count) — synthetic, deterministic, ≥6 months, with a clear rising trend for **S003 / Excavator** to power the demo.
- **Outputs:** `Forecast` (contract §2.7): history + 1–2 month forecast via **3-month weighted moving average (weights 1-2-3), rounded**, a plain-language `expected_requirement`, and `fillable_by` (returning/available assets of the right type).
- **Dependencies:** assets (to compute availability), lifecycle status.
- **Boundary:** `forecast.py` — no ML, no external libs; the method string is shown in the UI for explainability.
- **Acceptance:** `GET /api/forecast?site_id=S003&type=Excavator` returns a rising history and a forecast of ~3, with `EQX1007` (and/or EQX1002) listed in `fillable_by`.

---

## 15. Recommendation Logic

**Feature — Recommendations**
- **Purpose:** Turn anomalies + forecast into concrete dealer actions (spec §5), each with rationale.
- **Owner:** Jimmy (engine) + Ms Bean (recommendation phrasing/definitions).
- **Inputs:** anomalies, forecast, assignment/availability.
- **Outputs:** `Recommendation[]` (contract §2.6). Mappings: underutilization/zero_productive/overdue → `return`/`reallocation`; missing_site/operator → `assignment`; engine_overheat/abnormal_fuel → `maintenance`; forecast gap + available asset → `allocation`.
- **Dependencies:** §12, §14.
- **Boundary:** `recommendations.py` — deterministic mapping; the headline allocation ("recover EQX1007 → S003") is derived from forecast + availability, not hardcoded.
- **Acceptance:** `GET /api/recommendations` includes the EQX1007→S003 allocation (HIGH) and an EQX1004 maintenance recommendation once its overheat frame is reached; each has a data-backed `rationale`.

---

## 16. Check-in / Check-out Lifecycle

**Feature — Check-in/out**
- **Purpose:** Traceable custody: Dealership → Checkout → Site/Operator → Operation → Return (spec §4.2).
- **Owner:** Jimmy (API) + Yash (UI modal).
- **Inputs:** POST bodies (contract §3); asset id.
- **Outputs:** mutates `assignments.current_state`, appends `events`, recomputes status. Status precedence: `UNASSIGNED` (no site) > `OVERDUE` > `APPROACHING_RETURN` > `RENTED` > `RETURNED`.
- **Dependencies:** events, anomaly engine (overdue).
- **Boundary:** `lifecycle.py`. "QR scan" = paste/scan the equipment_id string into the same checkout form; no camera required (a static QR image per asset is optional polish).
- **Acceptance:** Checking out EQX1002 to a site+operator clears `missing_site`/`missing_operator` and adds CHECKOUT/SITE_ASSIGNED/OPERATOR_ASSIGNED events live. Checking in EQX1004 sets RETURNED and clears its overdue/approaching alerts.

---

## 17. Event / History Model

**Feature — Lifecycle timeline**
- **Purpose:** Visible, ordered history answering "what happened to this asset?" (spec §4.2, Scenario E).
- **Owner:** Jimmy (events) + Ms Bean (seed events per asset via `asset_state.csv`) + Yash (timeline UI).
- **Inputs:** seeded events from checkout/checkin dates + assignment state; runtime events from check-in/out and telemetry alerts.
- **Outputs:** `events` rows; `GET /assets/{id}/events` ascending.
- **Dependencies:** §16, telemetry.
- **Boundary:** events are generated at seed time from official dates (CHECKOUT at checkout_date; CHECKIN at checkin_date **only if** `asset_state` says returned; OVERDUE_FLAG at checkin_date if still out) and appended at runtime.
- **Acceptance:** EQX1002 timeline shows CHECKOUT 2025-03-01, an OVERDUE_FLAG at 2025-03-30, and **no** CHECKIN. EQX1003/EQX1005 show a clean CHECKOUT→CHECKIN pair.

---

## 18. Map / Location Model

**Feature — Map**
- **Purpose:** Spatial fleet view + location-mismatch evidence (spec §12 secondary).
- **Owner:** Yash (Leaflet) + Ms Bean (site coords).
- **Inputs:** `sites.csv` (lat/lon per S001–S006 + a dealership depot), telemetry positions.
- **Outputs:** map with site markers (asset counts) and active-asset markers; a polyline trace for the playing telemetry asset.
- **Dependencies:** sites, telemetry.
- **Boundary:** Leaflet + OpenStreetMap tiles (no API key). Coordinates are a deterministic, plausible cluster (one region) chosen by Ms Bean — realism > geographic accuracy.
- **Acceptance:** all sites render; EQX1004 shows a moving marker; if a `location_mismatch` scenario is enabled, its marker sits visibly away from its assigned site.

---

## 19. Synthetic Data Requirements (Ms Bean)

All files deterministic, reproducible, internally consistent, and clearly **supplementary** to the official data (never overwriting it).

- `sites.csv` — S001–S006 + `DEPOT` with name, lat, lon, region (fixed coords, one cluster).
- `operators.csv` — OP101, OP106, OP114, OP203, OP301 (+ spares) with realistic names + `safety_score` (0–100; give OP106 a lower score to motivate the EQX1004 safety scene).
- `customers.csv` — a handful of realistic customer names.
- `asset_state.csv` — per equipment_id: `current_state` (RENTED/RETURNED), effective site/operator/customer, `expected_checkin`, notes. **Drives which assets are "still out."** Make EQX1002 & EQX1007 still-out (→ overdue), EQX1004 still-out (approaching return, active telemetry), EQX1003/EQX1005/EQX1001/EQX1006 returned.
- `demand_history.csv` — ≥6 months of site×type counts with a rising S003/Excavator trend.
- `telemetry_scenarios.json` — parameters per active asset (§10). EQX1004: route + overheat ramp + seatbelt-off frames + fault.
- `anomaly_thresholds.json` — all threshold values from §12.
- `coaching/*.md` — seatbelt, overheat, low-utilization coaching (short instructions + checklist).
- `golden_insights.json` — expected utilization %, expected anomaly codes, and forecast headline per asset → the validation oracle for Jimmy's tests and Ms Bean's manual checks.

**Ms Bean's authoring aids:** she works in CSV/JSON/Markdown with ChatGPT/Gemini; `scripts/seed_check.py` (Jimmy provides) validates her files load and match `golden_insights.json`, so she can self-check without running the app.

---

## 20. Exact Demo Scenarios

Grounded in real rows; full narration in `docs/DEMO_FLOW.md`.

- **A — Unassigned/underutilized asset:** EQX1002 (hero). Dashboard flags it red → detail shows NULL site/operator, 0 engine hrs, 11 idle, 0% utilization, 43 days overdue → evidence → recommendation (recover/reallocate).
- **B — Machine/telemetry anomaly:** EQX1004 (only asset genuinely out at DEMO_NOW). Live telemetry playback → engine temp ramps past 105 °C + seatbelt OFF → HIGH alert → predictive-maintenance recommendation + operator coaching (seatbelt).
- **C — Forecast demand:** S003 / Excavator rising history → forecast ~3 for June.
- **D — Allocation:** forecast gap at S003 + EQX1007 (idle, unassigned, recoverable excavator) → recommendation "recover EQX1007 → S003." Ties D back to the A-class asset.
- **E — Lifecycle trace:** EQX1002 timeline (CHECKOUT → OVERDUE_FLAG, no CHECKIN) vs a clean EQX1003/EQX1005 pair; then live check-in of EQX1004.

**Hero justification:** EQX1002 uniquely stacks *five* HIGH conditions from the official data + overdue, making one asset carry Know→Detect→Explain→Act. EQX1007 (excavator) links the anomaly story to the forecast/allocation payoff. EQX1004 is the only row whose dates make it plausibly "live" at DEMO_NOW, so telemetry is coherent.

---

## 21. Parallel Team Work Allocation

Three independent lanes, one shared contract, one shared data folder (write-once by Ms Bean).

- **Yash (feature/frontend):** app shell → dashboard (table+KPIs) → asset detail → map → alerts feed → telemetry playback + charts → lifecycle timeline → forecast/recommendation panels → check-in/out modal → Impeccable polish → demo.
- **Jimmy (feature/backend):** scaffold + **mock API (hour 1)** → SQLite + seed loader → assets/alerts/sites/operators → utilization + anomaly engine → telemetry generator → events + check-in/out → forecast + recommendations → `dev.sh` + `seed_check.py`.
- **Ms Bean (feature/intelligence-data):** official CSV (verbatim, verified) → sites/operators/customers → asset_state → anomaly_thresholds → demand_history → telemetry_scenarios → coaching content → golden_insights → validation clickthrough.

**Conflict avoidance:** disjoint directories; `API_CONTRACT.md` frozen at kickoff; data files write-once by Ms Bean and read-only for Jimmy.

---

## 22. Integration Sequence

1. **Kickoff (all):** read spec + contract + this plan; confirm ports, DEMO_NOW, ownership; create/confirm branches.
2. **Jimmy** ships mock API (correct shapes) → Yash unblocked immediately.
3. **Ms Bean** commits `official_assets.csv` + sites/operators/customers early → Jimmy seeds real reads.
4. **Jimmy** replaces mocks with DB-backed reads behind the identical contract; **Yash** flips from mock to live (no shape change).
5. **Ms Bean** delivers thresholds/demand/telemetry_scenarios → Jimmy wires anomalies/forecast/telemetry.
6. **Checkpoint merges** to `develop` at each half-day boundary; run `dev.sh` and walk scenarios A–E.
7. **Feature freeze** end of Day 1; Day 2 = fixes on the demo path + polish + rehearsal only.

---

## 23. Testing Strategy

- **Jimmy (pytest):** `test_utilization.py` (exact §11 values), `test_anomalies.py` (EQX1002 anomaly set, EQX1003/1005 clean — asserted against `golden_insights.json`), `test_forecast.py` (moving-average math + fillable_by). Small, no fixtures/frameworks beyond pytest.
- **Ms Bean:** `scripts/seed_check.py` validates every data file loads and matches golden values; then a manual clickthrough of scenarios A–E against acceptance criteria.
- **Yash:** manual demo-path smoke each integration; optional render check per page.
- **Integration:** a `DEMO_CHECKLIST` in DEMO_FLOW.md walked end-to-end from `dev.sh` before freeze and again Day 2.

---

## 24. Hackathon Timeline / Checkpoints

**Day 1 (11:30–19:00, ~7.5h)**
- 11:30–12:00 Kickoff, contract freeze, scaffolds, branches.
- 12:00–13:00 Jimmy mock API · Yash app shell + dashboard layout · Ms Bean official CSV + sites/operators/customers.
- 13:00–14:30 Jimmy DB+seed+assets/alerts live · Yash dashboard live + asset detail · Ms Bean asset_state + thresholds.
- 14:30–16:00 Jimmy anomaly engine + events + check-in/out · Yash map + alerts + telemetry/charts · Ms Bean demand_history + telemetry_scenarios + coaching.
- 16:00–17:30 Jimmy forecast + recommendations · Yash forecast/recommendation panels + check-in/out modal · Ms Bean golden_insights + validation.
- 17:30–18:00 **Feature freeze.** Full `dev.sh` run, walk A–E.
- 18:00–19:00 Bug bash on demo path, Impeccable polish, write demo script.

**Day 2 (9:00–12:00, ~3h)**
- 9:00–10:00 Final integration; fix demo-path bugs only.
- 10:00–11:00 Polish + rehearse the 5-min story; record a backup screen capture.
- 11:00–12:00 Buffer + final rehearsal + submission.

**Checkpoints:** end of each Day-1 block = merge to `develop` + green `dev.sh`. Hard gate: **feature freeze 18:00 Day 1**.

---

## 25. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| FE/BE drift | Med | High | Frozen `API_CONTRACT.md` + mock-first; shapes never change silently. |
| Ms Bean blocked (little vibe-coding) | Med | Med | Her deliverables are **files only**, with templates + `seed_check.py`; no app code. |
| Telemetry sim eats time | Med | Med | Deterministic pre-gen + client playback; single scripted event (EQX1004). Cut extra telemetry assets first. |
| Non-deterministic demo | Low | High | Fixed `DEMO_NOW`, no RNG, playback not live. |
| Map/tiles fail | Low | Med | Leaflet+OSM (no key); fallback to static site markers if tiles are slow. |
| Scope creep (chatbot etc.) | Med | Med | §26 out-of-scope enforced; chatbot is lowest priority, skip. |
| Integration crunch late Day 1 | Med | High | Half-day checkpoint merges; feature freeze 18:00; Day 2 is fixes only. |
| Official data misread | Low | High | CSV is verbatim + `golden_insights.json` asserts derived values in tests. |

---

## 26. Explicitly Out of Scope

Real RFID/QR camera hardware · real Caterpillar IoT integration · Docker/containers for the primary path · real email/SMS/push infrastructure (in-app alerts only) · ML pipelines / model training · authentication / multi-user / roles · AI chatbot & maintenance-chat assistant (lowest priority — skip unless everything else is done and polished) · production databases (SQLite only) · mobile app · geographic accuracy of coordinates · historical data beyond what forecasting needs.

---

## 27. Definition of Done

The 11 "strong solution" criteria (HACKATHON_SPEC §17) are demonstrable from `scripts/dev.sh` on the demo path:

1. Fleet + status shown (Dashboard). 2. Every asset traceable (lifecycle timeline). 3. Meaningful usage shown (utilization). 4. Under-utilized/misassigned identified (EQX1002/1007). 5. ≥1 anomaly detected. 6. Evidence provided. 7. Actionable alert generated. 8. Demand forecast produced (S003/Excavator). 9. Forecast → allocation decision (EQX1007→S003). 10. Check-in/out demonstrated (EQX1004). 11. Decisions visibly data-backed.

Plus: the **5-minute demo (scenarios A–E) runs reliably twice in a row** from `dev.sh`; a backup recording exists; feature freeze met at 18:00 Day 1.

---

## Self-Review (spec coverage)

- Required capabilities §4.1–4.6 → §8/§11/§12/§13/§14 + endpoints. ✔
- Smart recommendations §5 → §15. ✔
- Operator safety/coaching §6 → §12 (`unsafe_seatbelt`) + §19 coaching + `SafetyCoaching` UI. ✔
- Telemetry simulation §7 → §10. ✔
- Official data + NULL semantics §8 → §6/§11/§12, contract §1. ✔
- Scenarios A–E §11 → §20 + DEMO_FLOW.md. ✔
- MVP priorities §15 → task ordering §24 + out-of-scope §26. ✔
- Constraints §16 (local processes, no Docker, determinism) → Global Constraints + §3. ✔
- Strong-solution criteria §17 → §27. ✔

No placeholders; types/shapes match `API_CONTRACT.md`.
