# FleetSignal Demo Flow — One 5-Minute Story

For the current submission, use the [three-minute demonstration and verified results](SUBMISSION_REVIEW.md#three-minute-demonstration). The original historical five-minute story remains below.

> **Narrative spine:** *Spot → Explain → Act → Predict → Prove* (official demo narrative), mapped onto the underlying spine *Know → Detect → Explain → Predict → Act* (HACKATHON_SPEC §13). One dealer, one afternoon, one fleet — not a feature tour. Everything below uses the **official** dataset (§8) at the fixed clock `DEMO_NOW = 2025-05-12`.

> **Current setup:** Enable `FLEETSIGNAL_DEMO_MODE=true` before backend startup. The original official seven-asset handout and supplementary forecast/sensor data are historical synthetic demo material, with business clock `2025-05-12` (`SRTS_DEMO_DATE` preserved). The dates and forecast numbers below intentionally retain that story. See [README](../README.md) for commands and configuration.

## Cast (chosen from the historical demo data)

| Asset | Role in story | Why |
|---|---|---|
| **EQX1007** | **Primary hero** | Idle, unassigned **excavator** — 0 engine hrs/day, 12 idle hrs/day, 0% productive utilization, overdue. It's the one anomaly that also feeds a forecasted allocation decision, so it carries the full Spot→Explain→Act→Predict arc alone. |
| **EQX1002** | Secondary overdue-alert story | Stacks NULL site + NULL operator + 0 engine hrs + 11 idle + 20 days + **43 days overdue**. Strongest explicit CRITICAL/overdue example; equipment type "Cater" so it doesn't compete for the excavator allocation story. |
| **EQX1004** | Live/safety asset | Only row still "out" at DEMO_NOW (checkin 2025-05-15) → coherent live telemetry + overheat + seatbelt scene + check-in. |
| **EQX1003 / EQX1005** | Healthy contrast | 94% / 100% utilization → proves the system isn't crying wolf. |

---

## The 5 minutes, scene by scene

**0:00 — SPOT (Dashboard).** "This is a Caterpillar dealer's rented fleet — 7 machines out in the field." Point at KPIs: fleet size, **assets needing attention**, HIGH alerts, avg utilization. The hero panel leads with **EQX1007**, not the loudest alarm — it's the anomaly with a business decision attached. The fleet table still shows EQX1002 CRITICAL/red at the top by severity, and the alerts feed carries both. *One glance = the dealer knows something's wrong, and which asset is the actionable story.*

**0:45 — EXPLAIN (EQX1007 detail).** Click EQX1007. Header: **Unassigned · Overdue**. Assignment card: Site *Unassigned*, Operator *Unassigned*. Utilization chart: **0% productive, 12 idle hrs/day**. Anomaly cards read like a human wrote them:
> "EQX1007 has no assigned site or operator and recorded 0 engine hours/day with 12 idle hours/day across 12 operating days (0% utilization). It was due back 2025-04-01 — **overdue**."

Each card shows **condition → evidence → severity → action**. *No black box — every number is on screen.*

**1:45 — ACT (recommendation + lifecycle).** Recommendation panel: **"Verify the asset's physical location and assign a site; assign a licensed operator; review the active work order and consider reallocating or returning the asset."** Open its lifecycle timeline: CHECKOUT 2025-03-20 → **OVERDUE_FLAG 2025-04-01** → …nothing. "It left the yard, and 12 idle hours a day since then never turned into productive work." Land the operational-impact line surfaced on the hero panel: **"12 idle hrs/day identified as recoverable utilization opportunity."**

**2:45 — PREDICT (forecast).** Open the forecast panel for **S003 / Excavator**: history 2→2→2→3→3→3, forecast **3** (weighted moving average), known supply **1 available + 1 recoverable = 2**, projected gap **1**. "S003 keeps needing excavators — and the fleet is one unit short even after recovery."

**3:15 — ALLOCATE (backend-derived recommendation).** Recommended action, computed by the backend (not the frontend): **"Recover EQX1007 and redeploy to S003."** with the caveat that one additional excavator unit may still be required. "The forecast just told us where the idle excavator should go. Investigation became a business decision — without overstating what it solves."

**3:45 — ALERT (EQX1002 overdue).** Switch to EQX1002 — the explicit overdue/critical example: no site, no operator, 0 engine hrs/day, 11 idle hrs/day, **43 days overdue**, CRITICAL. "This is what an alert with no forecast payoff still looks like — still visible, still actionable, just not the asset leading the dashboard today."

**4:15 — LIVE INTELLIGENCE (EQX1004).** Switch to EQX1004 — the one machine actually working today. Run a telemetry scenario: **engine temp reaches the ≥110 °C threshold** and/or **seatbelt reads OFF** → HIGH/CRITICAL alerts fire from backend telemetry (not faked in the frontend) → **predictive-maintenance recommendation** ("inspect the cooling system before continued operation") + **operator coaching** opens (seatbelt checklist). *Simulate → Telemetry → Alert → Recommendation, backend as source of truth.*

**4:45 — CLOSE (lifecycle + value).** Show Check In on EQX1004 (or EQX1006): status flips to **Returned**, a CHECKIN event lands on the timeline, no new alerts fire. Back to dashboard: "One screen took this dealer from *I don't know where my fleet is* to *recover EQX1007 for S003, review EQX1002, service EQX1004* — every decision backed by data." Land on the value line: **visibility, utilization, allocation, safety** — framed as identified operational opportunities, not guaranteed savings.

---

## Demo checklist

- [ ] Backend (:8000) starts with `FLEETSIGNAL_DEMO_MODE=true`; frontend (:5173) uses real API mode. Default backend mode has no seed/reset/simulation routes.
- [ ] `GET /health` → `{"status":"ok","service":"FleetSignal Backend"}`.
- [ ] Reset Demo → 7 assets; EQX1007 is the dashboard hero (CRITICAL/overdue, unassigned, 0% utilization, 12 idle hrs/day); EQX1002 remains CRITICAL/overdue at the top of the fleet table and alerts feed.
- [ ] EQX1007 detail: NULLs shown as *Unassigned*; 0% utilization; anomaly cards with evidence + actions; recommendation panel present.
- [ ] EQX1002 detail: 43 days overdue; 0% utilization; ≥4 anomalies with evidence + actions.
- [ ] Forecast S003/Excavator: history 2,2,2,3,3,3 → forecast 3; supply 1 available + 1 recoverable = 2; projected gap 1; allocation candidate EQX1007 → S003 (backend-derived, not computed in React).
- [ ] Recommendations panel visually distinguishes anomaly recs ("what went wrong") from the allocation rec ("what to do with the fleet").
- [ ] EQX1004 telemetry: run `engine_overheat` and `seatbelt_violation` scenarios → alerts + recommendation appear; coaching opens.
- [ ] Check-in EQX1004 or EQX1006 → Returned, timeline event added, no new alerts.
- [ ] Reset Demo again → fleet returns to the exact original seeded state (determinism holds).
- [ ] No console errors during the full walkthrough.
- [ ] Backup screen recording captured.

## Fallbacks (if something breaks live)

- Telemetry won't play → screenshot the overheat frame + read the alert; the anomaly still exists in `/alerts`.
- Map tiles slow → static site markers still render; narrate from the table.
- Any live action fails → the backup recording covers the full Spot–Prove arc.

## Reliability extension (after the business story)

Reset the disposable demo dataset before this extension to clear scenario readings from the business story. The historical example event below will then belong to the latest-20 window. Without a reset, use an occurrence time inside that window; simulator frames can have future timestamps and rank ahead of a current reading.

With demo mode enabled, use an existing asset such as EQX1004 and send a unique event to `POST /telemetry/events` with temperature 115 °C and `seatbelt_on=false`. Both hazards are evaluated independently in the same committed transaction; no `/alerts/refresh` call is needed. Check the event and active alerts through the existing reads, then reload the asset view.

1. Send `{"event_id":"demo-retry-EQX1004-1","asset_id":"EQX1004","timestamp":"2025-05-12T10:00:00Z","engine_temp_c":115,"seatbelt_on":false}`. Expect 201 with `duplicate=false`.
2. Resend it exactly. Expect 200, `duplicate=true`, and the same telemetry ID; the active alert IDs and creation times stay stable.
3. Reuse the ID with temperature 116. Expect 409 and no new telemetry or alert changes. Use the returned `X-Request-ID` to correlate the request with structured logs.
4. Demonstrate the isolated rollback/retry flow from `backend/`:

   ```bash
   uv run --frozen python scripts/demo_reliability.py
   ```

   The script uses a temporary file database and injects an exception after telemetry flush. It checks that telemetry and alert effects roll back, that retry succeeds, and that retry after a lost response returns the committed event. This shows exception rollback; it does not kill a process.
5. For the disposable local Docker project described in the [README](../README.md), run:

   ```bash
   uv run --frozen python scripts/verify_docker.py --project fleetsignal-verification --base-url http://localhost:8000
   ```

   This checks readiness, the seven-asset seed, ingestion retry/conflict, contention failure, and data retention after explicitly recreating that local project's backend container.

A single normal event does not necessarily clear a hazard: the newest 20 readings may still contain qualifying evidence. An episode resolves when the condition leaves that window; a later recurrence creates a new ID while retaining resolved history. The application updates after actions/reloads; there is no live streaming.

## Verification evidence

Use [COMPLETION_REPORT.md](COMPLETION_REPORT.md) for recorded backend tests, frontend build, and Docker results. The checklist is a demonstration procedure, not evidence that every browser interaction was automatically tested. The existing bundle warning above 500 kB remains; hosted CI execution is tracked separately from local equivalents.
