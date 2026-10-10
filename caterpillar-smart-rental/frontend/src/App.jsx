import { useEffect, useState } from "react";
import { Routes, Route, Link } from "react-router-dom";
import { Dashboard } from "./pages/Dashboard";
import { AssetDetail } from "./pages/AssetDetail";
import { api } from "./api/client";
import { IconTruck, IconClock } from "./components/icons";

export default function App() {
  const [demoNow, setDemoNow] = useState(null);
  const [resetting, setResetting] = useState(false);

  useEffect(() => {
    api.getHealth().then((h) => setDemoNow(h.demo_now)).catch(() => {});
  }, []);

  async function handleReset() {
    if (resetting) return;
    setResetting(true);
    try {
      await api.reset();
      window.location.href = "/";
    } catch {
      setResetting(false);
    }
  }

  return (
    <div className="min-h-screen bg-ground">
      <header className="sticky top-0 z-[1100] flex items-center justify-between border-b border-hairline bg-ground/95 px-4 py-2.5 shadow-[var(--shadow-panel)] backdrop-blur sm:px-6">
        <Link to="/" className="flex items-center gap-2.5">
          <span className="flex h-6 w-6 items-center justify-center bg-signal-high text-signal-high-ink">
            <IconTruck className="text-[13px]" />
          </span>
          <span className="text-sm font-bold tracking-wide text-ink">FleetSignal</span>
          <span className="hidden text-[13px] text-ink-faint sm:inline">Fleet Telemetry and Rental Operations</span>
        </Link>
        <div className="flex items-center gap-2">
          {demoNow && (
            <div className="flex items-center gap-1.5 border border-hairline bg-panel px-2 py-1 font-mono text-[12px] tabular-nums text-ink-dim" title="Fixed demo clock — not the real system date">
              <IconClock className="text-ink-faint" />
              {demoNow.replace("T", " ").replace("Z", "")} <span className="text-ink-faint">(demo)</span>
            </div>
          )}
          <button
            onClick={handleReset}
            disabled={resetting}
            className="border border-hairline-strong px-2.5 py-1.5 text-[12px] text-ink-dim hover:border-signal-high/50 hover:text-signal-high disabled:opacity-60"
            title="Restore official seed state — clears telemetry, alerts, and lifecycle mutations"
          >
            {resetting ? "Resetting…" : "Reset Demo"}
          </button>
        </div>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/asset/:id" element={<AssetDetail />} />
        </Routes>
      </main>
    </div>
  );
}
