import { useEffect, useRef, useState } from "react";
import { IconGauge } from "./icons";

const FRAME_MS = 350;

const SCENARIOS = [
  { value: "normal", label: "Normal" },
  { value: "engine_overheat", label: "Engine Overheat" },
  { value: "location_mismatch", label: "Location Mismatch" },
  { value: "seatbelt_violation", label: "Seatbelt Violation" },
  { value: "high_idle", label: "High Idle" },
  { value: "abnormal_fuel", label: "Abnormal Fuel" },
];

function ScenarioRunner({ onRun }) {
  const [scenario, setScenario] = useState("engine_overheat");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);

  async function run() {
    setRunning(true);
    setResult(null);
    try {
      await onRun(scenario);
      setResult({ ok: true, text: "Scenario complete — readings and alerts updated." });
    } catch (e) {
      setResult({ ok: false, text: e.message || "Simulation failed." });
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="mb-3 flex flex-wrap items-center gap-2 border-b border-hairline pb-3">
      <select value={scenario} onChange={(e) => setScenario(e.target.value)} className="border border-hairline-strong bg-panel-raised px-2 py-1.5 text-[13px] text-ink">
        {SCENARIOS.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
      </select>
      <button onClick={run} disabled={running} className="border border-hairline-strong px-2.5 py-1.5 text-[13px] text-ink hover:bg-panel-raised disabled:opacity-60">
        {running ? "Running…" : "Run Scenario"}
      </button>
      <span className="text-[11px] text-ink-faint">Generates demo readings and updates this asset's alerts.</span>
      {result && <span className={`text-[12px] ${result.ok ? "text-signal-healthy" : "text-signal-high"}`}>{result.text}</span>}
    </div>
  );
}

function Gauge({ label, value, unit, warn }) {
  return (
    <div className={`border px-3.5 py-2.5 ${warn ? "border-signal-high/40 bg-signal-high/[0.06]" : "border-hairline bg-panel-raised"}`}>
      <div className="text-[11px] font-medium uppercase tracking-wide text-ink-faint">{label}</div>
      <div className={`mt-1 font-mono text-[22px] font-semibold tabular-nums ${warn ? "text-signal-high" : "text-ink"}`}>
        {value}{unit}
      </div>
    </div>
  );
}

export function TelemetryPanel({ frames, onFrame, onRunScenario, runToken }) {
  const [i, setI] = useState(frames.length ? frames.length - 1 : 0);
  const [playing, setPlaying] = useState(false);
  const timer = useRef(null);
  const framesRef = useRef(frames);
  framesRef.current = frames;

  useEffect(() => {
    setI(frames.length ? frames.length - 1 : 0);
  }, [frames]);

  // A scenario just ran (runToken bumped only after the reload landed, so
  // framesRef is already the fresh set) — replay it from the start instead of
  // sitting on the last frame, so "Run Scenario" visibly does something.
  useEffect(() => {
    if (runToken && framesRef.current.length > 0) {
      setI(0);
      setPlaying(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runToken]);

  useEffect(() => {
    if (!playing) return;
    timer.current = setInterval(() => {
      setI((prev) => {
        if (prev >= frames.length - 1) {
          setPlaying(false);
          return prev;
        }
        return prev + 1;
      });
    }, FRAME_MS);
    return () => clearInterval(timer.current);
  }, [playing, frames.length]);

  const frame = frames[i];
  useEffect(() => { onFrame?.(frame); }, [frame, onFrame]);

  if (!frames.length) {
    return (
      <div className="border border-hairline bg-panel p-3 shadow-[var(--shadow-panel)]">
        <div className="mb-3 flex items-center gap-1.5 text-[12px] font-semibold uppercase tracking-wide text-ink-faint">
          <IconGauge /> Live Telemetry Playback
        </div>
        {onRunScenario && <ScenarioRunner onRun={onRunScenario} />}
        <p className="text-[14px] text-ink-faint">No telemetry recorded for this asset yet. Run a scenario above to generate readings.</p>
      </div>
    );
  }

  return (
    <div className="border border-hairline bg-panel p-4 shadow-[var(--shadow-panel)]">
      {onRunScenario && <ScenarioRunner onRun={onRunScenario} />}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-[12px] font-semibold uppercase tracking-wide text-ink-faint">
          <IconGauge /> Live Telemetry Playback
        </div>
        <div className="flex items-center gap-2.5">
          <button
            onClick={() => { if (i >= frames.length - 1) setI(0); setPlaying((p) => !p); }}
            className="border border-hairline-strong px-3 py-1.5 text-[13px] text-ink hover:bg-panel-raised"
          >
            {playing ? "Pause" : "Play"}
          </button>
          <span className="font-mono text-[13px] text-ink-faint">
            frame {i + 1}/{frames.length}
          </span>
        </div>
      </div>

      <input
        type="range"
        min={0}
        max={frames.length - 1}
        value={i}
        onChange={(e) => { setPlaying(false); setI(Number(e.target.value)); }}
        className="mt-3.5 w-full accent-signal-high"
      />

      <div className="mt-3.5 grid grid-cols-2 gap-2.5 sm:grid-cols-4">
        <Gauge label="Engine Temp" value={frame.engine_temp_c} unit="°C" warn={frame.engine_temp_c > 105} />
        <Gauge label="Fuel" value={frame.fuel_pct} unit="%" />
        <Gauge label="Fuel Rate" value={frame.fuel_rate_lph} unit=" L/h" />
        <Gauge label="Seatbelt" value={frame.seatbelt} unit="" warn={frame.seatbelt === "OFF"} />
      </div>
      {frame.fault_code && (
        <div className="mt-2.5 flex items-center gap-2 border border-signal-high/50 bg-signal-high/[0.08] px-3.5 py-2.5 font-mono text-[13px] font-semibold tracking-wide text-signal-high">
          <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-signal-high" />
          FAULT: {frame.fault_code}
        </div>
      )}
    </div>
  );
}
