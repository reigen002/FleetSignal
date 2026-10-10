# FleetSignal API Contract

Base URL: `http://localhost:8000`

Interactive docs: `http://localhost:8000/docs` (Swagger UI)

---

## Conventions

- All timestamps are ISO 8601 UTC (`2025-04-01T00:00:00Z`)
- Asset/site/operator IDs are strings; telemetry, alert, and rental-event row IDs are integers
- `null` fields in responses are intentional (e.g. unassigned site/operator)
- HTTP 404 → asset not found; 409 → business rule conflict

---

## Assets

### `GET /assets`

List all assets in the fleet.

**Query params:** `equipment_type`, `status`, `site_id`

**Response:** `AssetSummary[]`

```json
[
  {
    "id": "EQX1001",
    "equipment_type": "Excavator",
    "status": "available",
    "site_id": "S003",
    "operator_id": "OP101",
    "checkout_date": "2025-04-01T00:00:00Z",
    "expected_return_date": "2025-04-16T00:00:00Z",
    "engine_hrs_per_day": 1.5,
    "idle_hrs_per_day": 10.0,
    "operating_days": 15,
    "customer_name": "ABC Construction",
    "qr_code": "QR-EQX1001",
    "rfid_tag": "RFID-EQX1001"
  }
]
```

---

### `GET /assets/{asset_id}`

Full asset detail including utilization metrics.

**Response:** `AssetDetail` (extends `AssetSummary`)

```json
{
  "id": "EQX1001",
  "...": "...",
  "site": { "id": "S003", "name": "East Infrastructure Hub", "latitude": 14.676, "longitude": 121.0437 },
  "operator": { "id": "OP101", "name": "Juan dela Cruz", "license_class": "Heavy" },
  "utilization": {
    "engine_hrs_total": 22.5,
    "idle_hrs_total": 150.0,
    "operating_days": 15,
    "productive_ratio_pct": 13.0,
    "shift_utilization_pct": 18.8,
    "label": "22h engine / 150h idle over 15 days — 13.0% productive time, 18.8% of single-shift capacity."
  }
}
```

---

### `GET /assets/{asset_id}/telemetry`

Recent telemetry ordered by event timestamp descending, then row ID descending. Optional `event_id` and `received_at` are null on migrated legacy rows; `scenario` is an internal simulation label, not accepted by external ingestion.

**Query params:** `limit` (default 50, max 500), `scenario`

**Response:** `TelemetryOut[]`

```json
[
  {
    "id": 1,
    "asset_id": "EQX1001",
    "timestamp": "2025-04-10T08:00:00Z",
    "event_id": null,
    "received_at": null,
    "latitude": 14.676,
    "longitude": 121.0437,
    "engine_temp_c": 87.3,
    "engine_hours": 22.5,
    "fuel_level_pct": 72.0,
    "fuel_consumption_lph": 12.1,
    "idle_time_hours": 150.0,
    "seatbelt_on": true,
    "fault_code": null,
    "fault_description": null,
    "scenario": "normal"
  }
]
```

---

### `GET /assets/{asset_id}/events`

Lifecycle events (newest first).

**Query params:** `limit`

**Response:** `RentalEventOut[]`

---

### `POST /assets/{asset_id}/checkout`

Check out an asset. Rental state, lifecycle event, and affected alerts commit in one transaction.

**Body:**

```json
{
  "operator_id": "OP101",
  "site_id": "S003",
  "customer_name": "ABC Construction",
  "expected_return_date": "2025-04-16T00:00:00Z",
  "notes": "Routine rental",
  "performed_by": "Desk Agent",
  "identifier_method": "qr"
}
```

**Response:** `RentalEventOut` (409 if already checked out)

---

### `POST /assets/{asset_id}/checkin`

Return an asset. Rental state, lifecycle event, and affected alerts commit in one transaction.

**Body:**

```json
{
  "notes": "Returned in good condition",
  "performed_by": "Desk Agent",
  "identifier_method": "rfid"
}
```

**Response:** `RentalEventOut` (409 if not checked out)

---

### `POST /assets/{asset_id}/simulate`

Available only with `FLEETSIGNAL_DEMO_MODE=true`. Trigger a deterministic demo telemetry scenario. `readings` must be 1–100; invalid bounds return 422. The entire batch and affected alerts commit together before success.

**Body:**

```json
{
  "scenario": "engine_overheat",
  "readings": 10
}
```

**Scenarios:** `normal` | `engine_overheat` | `location_mismatch` | `seatbelt_violation` | `high_idle` | `abnormal_fuel`

**Response:** `TelemetryOut[]`

---

## Alerts

### `GET /alerts`

List alerts.

**Query params:** `asset_id`, `alert_type`, `severity`, `resolved` (default `false`)

**Alert types:** `overdue` | `no_operator` | `no_site` | `high_idle` | `engine_overheat` | `location_mismatch` | `seatbelt_violation` | `abnormal_fuel` | `low_utilization`

**Severity:** `LOW` | `MEDIUM` | `HIGH` | `CRITICAL`

**Response:**

```json
[
  {
    "id": 1,
    "asset_id": "EQX1002",
    "alert_type": "no_site",
    "severity": "HIGH",
    "message": "Asset EQX1002 has no assigned site.",
    "evidence": "site_id is NULL — asset cannot be located or dispatched.",
    "resolved": false,
    "created_at": "2025-09-01T10:00:00Z",
    "resolved_at": null
  }
]
```

---

### `POST /alerts/refresh`

Explicit recovery utility: reconcile all assets in one transaction and return the active alerts. Stable active IDs and creation times are retained, cleared conditions are resolved, and recurring conditions create new episodes. Normal ingestion, simulation, checkout, and check-in already reconcile their affected asset before returning; the frontend does not need this scan.

---

## Recommendations

### `GET /recommendations`

Return actionable recommendations for all assets with detected issues, ordered by severity.

**Response:**

```json
[
  {
    "asset": "EQX1002",
    "issue": "Underutilized / unassigned",
    "severity": "HIGH",
    "evidence": "220h cumulative idle time over 20 days with zero engine hours. Asset is powered on but not working.",
    "recommendation": "Review rental requirement and consider reallocating the asset. If there is no active work order, return the asset to the dealership to avoid unnecessary rental cost and wear."
  }
]
```

---

## Forecasts

### `GET /forecasts`

Demand forecasts by equipment type.

**Query params:** `equipment_type`, `site_id`

**Response:**

```json
[
  {
    "equipment_type": "Excavator",
    "site_id": null,
    "history": [
      { "period": "2025-03", "demand": 12.0, "is_forecast": false },
      { "period": "2025-04", "demand": 15.0, "is_forecast": false }
    ],
    "forecast": [
      { "period": "2025-05", "demand": 14.5, "is_forecast": true },
      { "period": "2025-06", "demand": 14.7, "is_forecast": true },
      { "period": "2025-07", "demand": 14.9, "is_forecast": true }
    ],
    "expected_returning": [],
    "recommended_allocation": 1,
    "allocation_rationale": "3-month moving average: 13.5 asset-days/month. Trend: demand is trending up (+1.5 days/month). Recommended fleet of 1 unit(s) covers peak projected demand of 15 asset-days assuming 30 active days/unit/month."
  }
]
```

---

## Admin

### `POST /admin/seed`

Demo mode only; the route is absent by default. Insert seed data if missing. Idempotent.

### `POST /admin/reset`

Demo mode only; the route is absent by default. Delete all configured database data and re-seed. Use only on the selected demo database between runs.

---

## Health

### `GET /health`

```json
{ "status": "ok", "service": "FleetSignal Backend" }
```

### `GET /ready`

Returns `200 {"status":"ready"}` only when the configured database is reachable, telemetry identity and alert episode columns are queryable, and Alembic revision is `0002`. Otherwise returns `503 {"detail":"Database not ready"}` without exposing connection details. `/health` reports process liveness; it does not establish database readiness.

## External telemetry ingestion

### `POST /telemetry/events`

Accept one validated, externally identified event for an existing asset:

```json
{
  "event_id": "device-EQX1004-0001",
  "asset_id": "EQX1004",
  "timestamp": "2025-05-12T10:00:00Z",
  "engine_temp_c": 115,
  "seatbelt_on": false
}
```

Response:

```json
{
  "event_id": "device-EQX1004-0001",
  "telemetry_id": 101,
  "asset_id": "EQX1004",
  "duplicate": false
}
```

The telemetry ID above is illustrative. A canonical duplicate returns that event's original ID with `duplicate=true`; it inserts no row and does not reconcile alerts or change their timestamps.

| Status | Meaning |
|---|---|
| 201 | New event and alert effects committed together |
| 200 | Existing event with identical validated semantic payload |
| 409 | Global event ID already belongs to different content, including a different asset |
| 422 | Validation failure |
| 404 | Asset not found |
| 503 | Database operation unavailable; `Retry-After: 1` |
| 500 | Unexpected failure; safe detail and correlated request ID |

For a lost response or transient failure, resend the **same event ID and payload**. Do not generate a fresh ID for the same reading. A 409 requires the sender to resolve the conflicting identity rather than repeating the altered event.

### Validation and canonical identity

Required: `event_id` (1–128 characters, no whitespace), `asset_id` (1–20 characters), and a timezone-aware timestamp. At least one non-null sensor or fault field is required. Extra fields are rejected, including `scenario`, `id`, `payload_hash`, and `received_at`.

Optional sensor/fault fields:

| Fields | Bounds |
|---|---|
| `latitude`, `longitude` | Both together; latitude −90…90, longitude −180…180 |
| `engine_temp_c` | Finite number |
| `engine_hours`, `idle_time_hours`, `fuel_consumption_lph` | Finite, nonnegative |
| `fuel_level_pct` | Finite, 0…100 |
| `seatbelt_on` | Boolean after schema validation |
| `fault_code`, `fault_description` | At most 50 / 200 characters |

All float fields reject NaN and infinity. Timestamps normalize to UTC; future timestamps remain permitted for synthetic scenarios. There is no production clock-skew policy.

Validation errors return a `detail` list containing `type`, `loc`, and `msg`. Invalid input values and validation context are omitted, including non-finite raw JSON numbers, so rejection remains a safe 422 response.

SHA-256 identity covers the validated semantic body, including `event_id`, `asset_id`, and timestamp. Sorted compact JSON normalizes timezone offsets, omitted optional fields to null, accepted numeric coercions, and negative zero. Internal row ID, scenario, stored hash, and server receipt time do not participate. This is payload identity, not authentication.

### Alert episode semantics

New ingestion evaluates the affected asset's latest **20** telemetry rows, ordered by timestamp descending then ID descending. The newest qualifying evidence is chosen independently for each rule: engine temperature **≥110 °C**, seatbelt **false**, fuel consumption **>24 L/h**, and an `L`-prefixed location fault. Coordinates are validated and stored; this implementation does not compute GPS geofences.

An active `(asset_id, alert_type)` retains its ID and `created_at`. Evaluation updates evidence when needed and advances internal `last_seen_at`. A cleared condition sets `resolved`/`resolved_at`, preserving history; recurrence creates a new episode. `last_seen_at` is internal: the public `AlertOut` fields above remain unchanged.

The window is row-based, not an expiry timer. A normal reading does not resolve a hazard while qualifying evidence remains in the latest 20. Without new readings, telemetry hazards do not expire. A late event is stored but cannot replace recent evidence when it falls outside that window. Rental, utilization, recommendation, forecast, and fixed business-clock rules are preserved.

## Request correlation and errors

All responses include `X-Request-ID`, including validation, conflict, unavailable, and unexpected-error responses. A supplied ID is accepted only when it matches `[A-Za-z0-9._:-]{1,64}`; otherwise the server assigns a UUID. Unexpected failures return:

```json
{"detail":"Internal server error","request_id":"server-assigned-or-validated-id"}
```

Stack traces stay in server logs. The frontend appends a validated header/body request ID to API error messages and exposes it as `error.requestId`. Structured server records contain route, method, status, elapsed milliseconds, and request ID; ingestion records also include event ID, asset ID, and outcome. They do not log full payloads or customer/contact data. IDs correlate requests; they do not authorize access.

CORS allows explicit configured local origins, exposes `X-Request-ID` and `Retry-After`, and disables credentials. Product authentication and broader access controls are outside this scope. See [RELIABILITY.md](RELIABILITY.md) for transaction behavior and operational limits. Examples in this contract use the historical demo dataset; default startup does not seed it.
