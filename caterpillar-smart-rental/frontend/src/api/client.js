// API client — talks to the real SRTS FastAPI backend by default.
//
// Mode switch: set VITE_API_MODE=mock in .env.local to fall back to the
// in-browser mock engine (useful for frontend-only work with no backend
// running). The real backend contract is frozen — see
// docs/API_CONTRACT.md on the backend branch. No /api prefix: routes are
// mounted at the root (e.g. http://localhost:8000/assets).
import * as engine from "../mock/engine";
import { DEMO_NOW, OFFICIAL_ASSETS } from "../mock/seed";
import { REAL_DEMO_NOW, DISPLAY_THRESHOLDS, SEVERITY_RANK } from "../lib/format";

const USE_MOCK = import.meta.env.VITE_API_MODE === "mock";
const BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";
const RETURN_APPROACHING_DAYS = DISPLAY_THRESHOLDS.return_approaching_days;

async function realFetch(path, opts) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  let body = null;
  try { body = await res.json(); } catch { /* empty body */ }
  if (!res.ok) {
    const requestId = [res.headers.get("X-Request-ID"), body?.request_id]
      .find((value) => typeof value === "string" && /^[A-Za-z0-9._:-]{1,64}$/.test(value));
    const message = typeof body?.detail === "string" ? body.detail : `Request failed (${res.status})`;
    const err = new Error(`${message}${requestId ? ` (Request ID: ${requestId})` : ""}`);
    err.status = res.status;
    err.requestId = requestId ?? null;
    throw err;
  }
  return body;
}

// ---------------------------------------------------------------------------
// Reference-data cache — the backend has no /sites or /operators list
// endpoint. Site/operator objects only ever arrive nested inside
// AssetDetail. We collect the ones we've actually seen from the backend
// (never invented) so the checkout form has real options to offer.
// ---------------------------------------------------------------------------
const knownSites = new Map();
const knownOperators = new Map();

function rememberReferenceData(detail) {
  if (detail?.site?.id) knownSites.set(detail.site.id, detail.site);
  if (detail?.operator?.id) knownOperators.set(detail.operator.id, detail.operator);
}

// ---------------------------------------------------------------------------
// Adapters: backend shape -> the view-model the UI already renders.
// Field renames and derived display buckets only — every value is sourced
// from the backend response, nothing is fabricated or re-detected.
// ---------------------------------------------------------------------------

function productiveRatioPct(engineHrsPerDay, idleHrsPerDay) {
  const total = engineHrsPerDay + idleHrsPerDay;
  return total === 0 ? 0 : Math.round((engineHrsPerDay / total) * 100);
}

function deriveStatus(asset) {
  const overdue =
    asset.status === "checked_out" &&
    asset.expected_return_date &&
    new Date(asset.expected_return_date) < new Date(REAL_DEMO_NOW);
  if (overdue) return "OVERDUE";
  if (asset.status === "checked_out") {
    if (!asset.site_id) return "UNASSIGNED";
    const daysToReturn = asset.expected_return_date
      ? Math.round((new Date(asset.expected_return_date) - new Date(REAL_DEMO_NOW)) / 86400000)
      : null;
    if (daysToReturn != null && daysToReturn >= 0 && daysToReturn <= RETURN_APPROACHING_DAYS) {
      return "APPROACHING_RETURN";
    }
    return "RENTED";
  }
  if (asset.status === "maintenance") return "MAINTENANCE";
  return "RETURNED"; // "available"
}

function adaptAssetSummary(a, alertsByAsset) {
  const assetAlerts = alertsByAsset?.get(a.id) ?? [];
  const topAlert = assetAlerts[0];
  return {
    equipment_id: a.id,
    type: a.equipment_type,
    status: deriveStatus(a),
    raw_status: a.status,
    days_overdue: a.status === "checked_out" && a.expected_return_date && new Date(a.expected_return_date) < new Date(REAL_DEMO_NOW)
      ? Math.round((new Date(REAL_DEMO_NOW) - new Date(a.expected_return_date)) / 86400000)
      : null,
    site_id: a.site_id,
    site_name: a.site?.name ?? null,
    operator_id: a.operator_id,
    operator_name: a.operator?.name ?? null,
    customer: a.customer_name ?? null,
    location: a.site ? { lat: a.site.latitude, lon: a.site.longitude } : null,
    utilization_pct: a.utilization
      ? Math.round(a.utilization.productive_ratio_pct)
      : productiveRatioPct(a.engine_hrs_per_day, a.idle_hrs_per_day),
    engine_hours_per_day: a.engine_hrs_per_day,
    idle_hours_per_day: a.idle_hrs_per_day,
    operating_days: a.operating_days,
    checkout_date: a.checkout_date,
    checkin_date: a.expected_return_date,
    anomaly_count: assetAlerts.length,
    highest_severity: topAlert?.severity ?? null,
    top_anomaly: topAlert ? { code: topAlert.alert_type, severity: topAlert.severity, summary: topAlert.message } : null,
    source: "backend",
  };
}

function adaptAlert(alert) {
  return {
    id: `AL-${alert.id}`,
    asset_id: alert.asset_id,
    code: alert.alert_type,
    severity: alert.severity,
    message: alert.message,
    evidence: alert.evidence,
    created_at: alert.created_at,
  };
}

function adaptAnomaly(alert) {
  return {
    code: alert.alert_type,
    severity: alert.severity,
    condition: alert.message,
    evidence: alert.evidence,
    // No per-condition action from the backend — conditions consolidate
    // into the single recommendation shown alongside (see RecommendationPanel).
    recommended_action: null,
  };
}

function adaptEvent(e) {
  const TITLE = {
    checkout: "Checked out",
    checkin: "Returned to dealership",
    overdue_flagged: "Flagged overdue",
  };
  // A checkout event is the only one carrying rental commercial context —
  // resolved from the same knownSites cache adaptAssetSummary uses, so a site
  // referenced only by a past event (never the asset's current one) can still
  // come back unresolved on a cold deep-link; falls back to the raw id.
  const site = e.site_id ? knownSites.get(e.site_id) : null;
  return {
    id: `EV-${e.id}`,
    asset_id: e.asset_id,
    timestamp: e.timestamp,
    type: e.event_type.toUpperCase(),
    title: TITLE[e.event_type] ?? e.event_type,
    detail: e.notes ?? "",
    actor: e.performed_by ?? "Dealer Desk",
    customer_name: e.customer_name ?? null,
    site_id: e.site_id ?? null,
    site_name: site?.name ?? e.site_id ?? null,
    site_address: site?.address ?? null,
  };
}

function adaptTelemetryFrame(t) {
  return {
    asset_id: t.asset_id,
    timestamp: t.timestamp,
    lat: t.latitude,
    lon: t.longitude,
    engine_on: t.engine_temp_c != null && t.engine_temp_c > 50,
    engine_hours: t.engine_hours,
    idle_minutes: Math.round((t.idle_time_hours ?? 0) * 60),
    fuel_pct: t.fuel_level_pct,
    fuel_rate_lph: t.fuel_consumption_lph,
    engine_temp_c: t.engine_temp_c,
    seatbelt: t.seatbelt_on === false ? "OFF" : "ON",
    fault_code: t.fault_code,
    fault_description: t.fault_description,
  };
}

function adaptRecommendation(r, idx = 0) {
  return {
    id: `REC-${r.asset}-${idx}`,
    asset_id: r.asset,
    severity: r.severity,
    issue: r.issue,
    evidence: r.evidence,
    recommendation: r.recommendation,
  };
}

// Site × equipment-type rows carry supply/gap/candidate fields; equipment-type
// rows have them as null. Pass through as-is so the UI can tell the two apart.
function adaptForecast(f) {
  return {
    equipment_type: f.equipment_type,
    site_id: f.site_id,
    history: f.history,
    forecast: f.forecast,
    expected_returning: f.expected_returning,
    recommended_allocation: f.recommended_allocation,
    allocation_rationale: f.allocation_rationale,
    supply_available: f.supply_available ?? null,
    supply_recoverable: f.supply_recoverable ?? null,
    supply_total_known: f.supply_total_known ?? null,
    peak_forecast_demand: f.peak_forecast_demand ?? null,
    projected_gap: f.projected_gap ?? null,
    allocation_candidates: f.allocation_candidates ?? null,
  };
}

// Mock engine still produces one recommendation per detected condition
// (return/assignment/maintenance/allocation). Consolidate to one per asset
// here so both modes honor the same "one recommendation per asset" rule —
// pure presentation grouping of numbers the mock engine already computed,
// not new detection logic.
function consolidateMockRecommendations(list) {
  const byAsset = new Map();
  for (const r of list) {
    if (r.type === "allocation") continue; // allocation belongs to forecast, not recommendations
    const bucket = byAsset.get(r.asset_id) ?? [];
    bucket.push(r);
    byAsset.set(r.asset_id, bucket);
  }
  const order = { HIGH: 0, MEDIUM: 1, LOW: 2 };
  return [...byAsset.entries()].map(([asset_id, recs]) => ({
    id: `REC-${asset_id}`,
    asset_id,
    severity: recs.reduce((s, r) => (order[r.severity] < order[s] ? r.severity : s), recs[0].severity),
    issue: recs.map((r) => r.title.replace(/^(Recover|Update assignment for|Inspect) /, "").trim() || r.title).join("; "),
    evidence: recs.map((r) => r.rationale).join(" "),
    recommendation: recs.map((r) => r.action).join(" "),
  })).sort((a, b) => order[a.severity] - order[b.severity]);
}

// Mock engine's forecast shape (count/method/fillable_by) predates the real
// backend contract. Adapt it to the same {history,forecast,expected_returning,
// recommended_allocation,allocation_rationale} shape so ForecastPanel has one
// rendering path for both modes — reshaping numbers the mock already computed.
function adaptMockForecast(f) {
  return {
    equipment_type: f.equipment_type,
    site_id: f.site_id,
    history: f.history.map((h) => ({ period: h.period, demand: h.count, is_forecast: false })),
    forecast: f.forecast.map((p) => ({ period: p.period, demand: p.count, is_forecast: true })),
    expected_returning: f.fillable_by.map((fb) => ({
      asset_id: fb.equipment_id,
      equipment_type: f.equipment_type,
      expected_return_date: OFFICIAL_ASSETS.find((a) => a.equipment_id === fb.equipment_id)?.checkin_date ?? null,
    })),
    recommended_allocation: Math.round(f.forecast[0]?.count ?? 0),
    allocation_rationale: `${f.method}. ${f.expected_requirement}`,
    supply_available: null,
    supply_recoverable: null,
    supply_total_known: null,
    peak_forecast_demand: null,
    projected_gap: null,
    allocation_candidates: null,
  };
}

async function fetchAlertsByAsset() {
  const alerts = await realFetch("/alerts");
  const map = new Map();
  for (const a of alerts) {
    const sorted = map.get(a.asset_id) ?? [];
    sorted.push(a);
    map.set(a.asset_id, sorted);
  }
  for (const list of map.values()) list.sort((a, b) => SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity]);
  return map;
}

export const api = {
  async getAssets() {
    if (USE_MOCK) return ok({ assets: engine.allAssetIds().map(engine.assetSummary) });
    const [list, alertsByAsset] = await Promise.all([realFetch("/assets"), fetchAlertsByAsset()]);
    // N+1 detail fetch: AssetSummary omits utilization/site-name/operator-name,
    // and there is no /sites or /operators list endpoint — detail is the only
    // source for real names. Fine at 7 assets.
    const details = await Promise.all(list.map((a) => realFetch(`/assets/${a.id}`)));
    details.forEach(rememberReferenceData);
    return { assets: details.map((d) => adaptAssetSummary(d, alertsByAsset)) };
  },

  async getAsset(id) {
    if (USE_MOCK) {
      const detail = engine.assetDetail(id);
      return ok({ ...detail, recommendations: consolidateMockRecommendations(detail.recommendations) });
    }
    const [detail, alerts, recommendations] = await Promise.all([
      realFetch(`/assets/${id}`),
      realFetch(`/alerts?asset_id=${id}`),
      realFetch("/recommendations"),
    ]);
    rememberReferenceData(detail);
    const alertsByAsset = new Map([[id, [...alerts].sort((a, b) => SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity])]]);
    // An asset can carry more than one recommendation now (its own anomaly
    // recommendation plus a forecast-driven allocation recommendation) — keep
    // all of them, not just the first match.
    const assetRecs = recommendations.filter((r) => r.asset === id);
    const events = await realFetch(`/assets/${id}/events`);
    return {
      ...adaptAssetSummary(detail, alertsByAsset),
      anomalies: alertsByAsset.get(id).map(adaptAnomaly),
      recommendations: assetRecs.map((r, i) => adaptRecommendation(r, i)),
      events: events.map(adaptEvent).sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp)),
      telemetry_current: null,
      assignment: {
        site_id: detail.site_id,
        operator_id: detail.operator_id,
        customer: detail.customer_name ?? null,
        expected_checkin: detail.expected_return_date,
      },
    };
  },

  async getTelemetry(id) {
    if (USE_MOCK) return ok({ asset_id: id, frames: engine.telemetryFrames(id) });
    const rows = await realFetch(`/assets/${id}/telemetry?limit=50`);
    const frames = rows.map(adaptTelemetryFrame).sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));
    return { asset_id: id, frames };
  },

  async getEvents(id) {
    if (USE_MOCK) return ok({ asset_id: id, events: engine.events(id) });
    const rows = await realFetch(`/assets/${id}/events`);
    return { asset_id: id, events: rows.map(adaptEvent) };
  },

  async getAlerts(params = {}) {
    if (USE_MOCK) return ok({ alerts: engine.allAlerts(params) });
    const qs = new URLSearchParams(params).toString();
    const rows = await realFetch(`/alerts${qs ? `?${qs}` : ""}`);
    const sorted = [...rows].sort((a, b) => SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity] || a.asset_id.localeCompare(b.asset_id));
    return { alerts: sorted.map(adaptAlert) };
  },

  async refreshAlerts() {
    if (USE_MOCK) return ok({ alerts: [] });
    const rows = await realFetch("/alerts/refresh", { method: "POST" });
    return { alerts: rows.map(adaptAlert) };
  },

  async simulate(id, scenario, readings = 10) {
    if (USE_MOCK) return ok({ frames: [] });
    const rows = await realFetch(`/assets/${id}/simulate`, {
      method: "POST",
      body: JSON.stringify({ scenario, readings }),
    });
    return { frames: rows.map(adaptTelemetryFrame) };
  },

  async getSites() {
    if (USE_MOCK) return ok({ sites: engine.sitesWithCounts() });
    // No backend list endpoint. The cache is normally warmed by getAssets(),
    // but a deep link straight to an asset detail page (no Dashboard visit
    // yet) or an asset whose own site is null (EQX1002/1007) leaves it
    // empty — self-populate by walking every asset's detail once.
    if (knownSites.size === 0) await api.getAssets();
    return ok({ sites: [...knownSites.values()].map((s) => ({ site_id: s.id, name: s.name, lat: s.latitude, lon: s.longitude })) });
  },

  async getOperators() {
    if (USE_MOCK) return ok({ operators: engine.operatorsList() });
    if (knownOperators.size === 0) await api.getAssets();
    return ok({ operators: [...knownOperators.values()].map((o) => ({ operator_id: o.id, name: o.name })) });
  },

  async checkout(id, body) {
    if (USE_MOCK) return ok(engine.checkout(id, body));
    await realFetch(`/assets/${id}/checkout`, {
      method: "POST",
      body: JSON.stringify({
        site_id: body.site_id || undefined,
        operator_id: body.operator_id || undefined,
        customer_name: body.customer || undefined,
        expected_return_date: body.expected_checkin ? `${body.expected_checkin}T00:00:00Z` : undefined,
      }),
    });
    return api.getAsset(id);
  },

  async checkin(id, body) {
    if (USE_MOCK) return ok(engine.checkin(id, body));
    await realFetch(`/assets/${id}/checkin`, {
      method: "POST",
      body: JSON.stringify({ notes: body?.notes || undefined }),
    });
    return api.getAsset(id);
  },

  async getForecast(params = {}) {
    if (USE_MOCK) {
      if (params.site_id && params.type) return ok({ forecasts: [adaptMockForecast(engine.forecastFor(params.site_id, params.type))] });
      return ok({ forecasts: engine.allForecasts().map(adaptMockForecast) });
    }
    const rows = await realFetch("/forecasts");
    return { forecasts: rows.map(adaptForecast) };
  },

  async getRecommendations() {
    if (USE_MOCK) return ok({ recommendations: consolidateMockRecommendations(engine.allRecommendations()) });
    const rows = await realFetch("/recommendations");
    return { recommendations: rows.map((r, i) => adaptRecommendation(r, i)) };
  },

  async getHealth() {
    if (USE_MOCK) return ok({ status: "ok", demo_now: DEMO_NOW, asset_count: engine.allAssetIds().length });
    const body = await realFetch("/health");
    return { ...body, demo_now: REAL_DEMO_NOW };
  },

  async reset() {
    if (USE_MOCK) return ok({ status: "mock_reset" });
    // backend/app/seed.py now seeds EQX1002/1004/1007 as checked_out
    // directly, so /admin/reset alone (which also refreshes alerts
    // server-side) restores the correct deterministic demo state.
    return realFetch("/admin/reset", { method: "POST" });
  },
};

function ok(data) {
  return Promise.resolve(data);
}
