import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import { StatusPill, SeverityPill } from "../components/StatusPill";
import { UtilizationChart } from "../components/UtilizationChart";
import { AnomalyCard } from "../components/AnomalyCard";
import { TelemetryPanel } from "../components/TelemetryPanel";
import { LifecycleTimeline } from "../components/LifecycleTimeline";
import { CustomerHistory } from "../components/CustomerHistory";
import { RecommendationPanel } from "../components/RecommendationPanel";
import { SafetyCoaching } from "../components/SafetyCoaching";
import { FleetMap } from "../components/FleetMap";
import { CheckInOutModal } from "../components/CheckInOutModal";
import { formatDate, SEVERITY_BORDER, SEVERITY_TEXT } from "../lib/format";
import { IconArrowRight } from "../components/icons";

function Stat({ label, value, tone = "text-ink" }) {
  return (
    <div>
      <div className="text-[11px] font-semibold uppercase tracking-wide text-ink-faint">{label}</div>
      <div className={`mt-1 font-mono text-[17px] font-medium tabular-nums ${tone}`}>{value}</div>
    </div>
  );
}

export function AssetDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [asset, setAsset] = useState(null);
  const [telemetry, setTelemetry] = useState([]);
  const [currentFrame, setCurrentFrame] = useState(null);
  const [modal, setModal] = useState(null);
  const [error, setError] = useState(null);
  const [runToken, setRunToken] = useState(0);

  // Awaitable: callers that need the reload actually finished (handleRunScenario
  // keeps its button/select disabled until this resolves) rely on it, not just
  // on `load()` having been called.
  const load = useCallback(() => {
    const assetLoaded = api.getAsset(id).then(setAsset).catch((e) => setError(e.status === 404 ? `Asset ${id} not found.${e.requestId ? ` (Request ID: ${e.requestId})` : ""}` : e.message || "Failed to load asset."));
    const telemetryLoaded = api.getTelemetry(id).then((r) => setTelemetry(r.frames));
    return Promise.all([assetLoaded, telemetryLoaded]);
  }, [id]);

  useEffect(() => { setAsset(null); setError(null); load(); }, [load]);

  const onFrame = useCallback((f) => setCurrentFrame(f), []);

  if (error) return <div className="p-6 text-sm text-signal-high">{error} <Link to="/" className="underline">Back to dashboard</Link></div>;
  if (!asset) return <div className="p-6 text-sm text-ink-faint">Loading asset…</div>;

  const seatbeltAnomaly = asset.anomalies.find((a) => a.code === "unsafe_seatbelt" || a.code === "seatbelt_violation");
  const overheatAnomaly = asset.anomalies.find((a) => a.code === "engine_overheat");
  const lowUtilAnomaly = asset.anomalies.find((a) => a.code === "low_utilization");

  async function handleCheckout(body) {
    await api.checkout(id, body);
    setModal(null);
    load();
  }
  async function handleCheckin(body) {
    await api.checkin(id, body);
    setModal(null);
    load();
  }
  async function handleRunScenario(scenario) {
    await api.simulate(id, scenario);
    await load();
    setRunToken((t) => t + 1);
  }

  const trace = telemetry.length ? telemetry.map((f) => [f.lat, f.lon]) : null;
  const mapAsset = { ...asset, location: currentFrame ? { lat: currentFrame.lat, lon: currentFrame.lon } : asset.location };
  const utilTone = asset.utilization_pct < 30 ? "text-signal-high" : asset.utilization_pct >= 90 ? "text-signal-healthy" : "text-ink";

  return (
    <div className="mx-auto max-w-[1440px] space-y-5 p-4 sm:p-7">
      <Link to="/" className="inline-flex items-center gap-1 text-[13px] text-ink-faint hover:text-ink-dim">
        ← Fleet Dashboard
      </Link>

      {/* Identity + status + priority + rental state + usage + assignment — one instrument cluster, above the fold. */}
      <div className={`border bg-panel shadow-[var(--shadow-hero)] ${SEVERITY_BORDER[asset.highest_severity] ?? "border-hairline"}`}>
        <div className="flex flex-wrap items-start justify-between gap-4 p-5 sm:p-6">
          <div>
            <div className="flex flex-wrap items-center gap-2.5">
              <h1 className="font-mono text-[32px] font-bold leading-none text-ink">{asset.equipment_id}</h1>
              <StatusPill status={asset.status} size="lg" />
              {asset.highest_severity && <SeverityPill severity={asset.highest_severity} size="lg" />}
            </div>
            <p className="mt-2 text-[14px] text-ink-dim">
              {asset.type} · {asset.anomaly_count} open anomal{asset.anomaly_count === 1 ? "y" : "ies"}
              {asset.days_overdue != null && <span className="text-signal-critical"> · {asset.days_overdue} days overdue</span>}
            </p>
          </div>
          <div className="flex gap-2">
            {asset.raw_status !== "checked_out" ? (
              <button onClick={() => setModal("checkout")} className="border border-hairline-strong px-3.5 py-2 text-[14px] text-ink hover:bg-panel-raised">
                Check Out
              </button>
            ) : (
              <button onClick={() => setModal("checkin")} className="bg-signal-high px-3.5 py-2 text-[14px] font-medium text-signal-high-ink hover:brightness-95">
                Check In
              </button>
            )}
          </div>
        </div>

        <div className="grid grid-cols-2 divide-x divide-y divide-ink-faint border-t border-hairline sm:grid-cols-4 sm:divide-y-0 lg:grid-cols-9">
          <div className="px-4 py-3.5"><Stat label="Utilization" value={`${asset.utilization_pct}%`} tone={utilTone} /></div>
          <div className="px-4 py-3.5"><Stat label="Engine hrs/day" value={asset.engine_hours_per_day} /></div>
          <div className="px-4 py-3.5"><Stat label="Idle hrs/day" value={asset.idle_hours_per_day} tone={asset.idle_hours_per_day >= 10 ? "text-signal-high" : "text-ink"} /></div>
          <div className="px-4 py-3.5"><Stat label="Operating days" value={asset.operating_days} /></div>
          <div className="px-4 py-3.5"><Stat label="Site" value={asset.assignment.site_id ? asset.site_name : "Unassigned"} tone={asset.assignment.site_id ? "text-ink" : "text-signal-high"} /></div>
          <div className="px-4 py-3.5"><Stat label="Operator" value={asset.assignment.operator_id ? asset.operator_name : "Unassigned"} tone={asset.assignment.operator_id ? "text-ink" : "text-signal-high"} /></div>
          <div className="px-4 py-3.5"><Stat label="Customer" value={asset.assignment.customer ?? "Unassigned"} tone={asset.assignment.customer ? "text-ink" : "text-signal-high"} /></div>
          <div className="px-4 py-3.5"><Stat label="Checkout" value={formatDate(asset.checkout_date)} /></div>
          <div className="px-4 py-3.5"><Stat label="Expected Check-In" value={formatDate(asset.assignment.expected_checkin)} tone={asset.days_overdue != null ? SEVERITY_TEXT.CRITICAL : "text-ink"} /></div>
        </div>
      </div>

      {/* Usage: utilization detail alongside operational location context. */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <UtilizationChart engineHoursPerDay={asset.engine_hours_per_day} idleHoursPerDay={asset.idle_hours_per_day} />
        <FleetMap sites={[]} assets={[mapAsset]} trace={trace} />
      </div>

      <TelemetryPanel frames={telemetry} onFrame={onFrame} onRunScenario={handleRunScenario} runToken={runToken} />

      <div>
        <div className="mb-2.5 text-[12px] font-semibold uppercase tracking-wide text-ink-faint">Anomalies</div>
        {asset.anomalies.length === 0 ? (
          <div className="border border-hairline bg-panel p-5 text-sm text-ink-faint">No active anomalies.</div>
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {asset.anomalies.map((a) => <AnomalyCard key={a.code} anomaly={a} />)}
          </div>
        )}
      </div>

      {(seatbeltAnomaly || overheatAnomaly || lowUtilAnomaly) && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {seatbeltAnomaly && <SafetyCoaching code="unsafe_seatbelt" />}
          {overheatAnomaly && <SafetyCoaching code="engine_overheat" />}
          {!seatbeltAnomaly && !overheatAnomaly && lowUtilAnomaly && <SafetyCoaching code="low_utilization" />}
        </div>
      )}

      <div className="grid grid-cols-1 items-start gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
        <RecommendationPanel recommendations={asset.recommendations} />
        <div className="space-y-5">
          <CustomerHistory events={asset.events} />
          <LifecycleTimeline events={asset.events} />
        </div>
      </div>

      {asset.recommendations.length > 0 && (
        <button
          onClick={() => navigate("/")}
          className="flex items-center gap-1 text-[13px] text-signal-high hover:underline"
        >
          View demand forecast and allocation options on the dashboard <IconArrowRight />
        </button>
      )}

      {modal === "checkout" && (
        <CheckInOutModal mode="checkout" assetId={asset.equipment_id} onClose={() => setModal(null)} onSubmit={handleCheckout} />
      )}
      {modal === "checkin" && (
        <CheckInOutModal mode="checkin" assetId={asset.equipment_id} onClose={() => setModal(null)} onSubmit={handleCheckin} />
      )}
    </div>
  );
}
