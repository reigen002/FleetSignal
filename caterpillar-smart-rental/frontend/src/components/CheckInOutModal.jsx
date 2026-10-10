import { useEffect, useState } from "react";
import { IconClose } from "./icons";
import { api } from "../api/client";

export function CheckInOutModal({ mode, assetId, onClose, onSubmit }) {
  const isCheckout = mode === "checkout";
  const [sites, setSites] = useState([]);
  const [operators, setOperators] = useState([]);
  const [siteId, setSiteId] = useState("");
  const [operatorId, setOperatorId] = useState("");
  const [customer, setCustomer] = useState("");
  const [expectedCheckin, setExpectedCheckin] = useState("");
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!isCheckout) return;
    api.getSites().then((r) => setSites(r.sites));
    api.getOperators().then((r) => setOperators(r.operators));
  }, [isCheckout]);

  async function submit(e) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      if (isCheckout) {
        await onSubmit({ site_id: siteId, operator_id: operatorId, customer, expected_checkin: expectedCheckin });
      } else {
        await onSubmit({ notes });
      }
    } catch (err) {
      setError(err.status === 409
        ? `This asset's state changed — reload and try again.${err.requestId ? ` (Request ID: ${err.requestId})` : ""}`
        : err.message || "Request failed.");
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-[1200] flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <form
        onClick={(e) => e.stopPropagation()}
        onSubmit={submit}
        className="w-full max-w-md border border-hairline-strong bg-panel p-4 shadow-[var(--shadow-hero)]"
      >
        <div className="flex items-center justify-between border-b border-hairline pb-3">
          <h2 className="text-sm font-medium text-ink">
            {isCheckout ? `Check Out ${assetId}` : `Check In ${assetId}`}
          </h2>
          <button type="button" onClick={onClose} className="text-ink-faint hover:text-ink" aria-label="Close">
            <IconClose />
          </button>
        </div>

        <div className="space-y-3 py-3">
          <div>
            <label className="text-[11px] uppercase tracking-wide text-ink-faint">Equipment ID (scan or type)</label>
            <input value={assetId} readOnly className="mt-1 w-full border border-hairline-strong bg-panel-raised px-2.5 py-1.5 font-mono text-sm text-ink-dim" />
          </div>

          {isCheckout ? (
            <>
              <div>
                <label className="text-[11px] uppercase tracking-wide text-ink-faint">Site</label>
                <select required value={siteId} onChange={(e) => setSiteId(e.target.value)} className="mt-1 w-full border border-hairline-strong bg-panel-raised px-2.5 py-1.5 text-sm text-ink">
                  <option value="" disabled>{sites.length ? "Select a site" : "Loading sites…"}</option>
                  {sites.map((s) => (
                    <option key={s.site_id} value={s.site_id}>{s.name}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-[11px] uppercase tracking-wide text-ink-faint">Operator</label>
                <select required value={operatorId} onChange={(e) => setOperatorId(e.target.value)} className="mt-1 w-full border border-hairline-strong bg-panel-raised px-2.5 py-1.5 text-sm text-ink">
                  <option value="" disabled>{operators.length ? "Select an operator" : "Loading operators…"}</option>
                  {operators.map((o) => (
                    <option key={o.operator_id} value={o.operator_id}>{o.name}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-[11px] uppercase tracking-wide text-ink-faint">Customer</label>
                <input required value={customer} onChange={(e) => setCustomer(e.target.value)} placeholder="Customer name" className="mt-1 w-full border border-hairline-strong bg-panel-raised px-2.5 py-1.5 text-sm text-ink" />
              </div>
              <div>
                <label className="text-[11px] uppercase tracking-wide text-ink-faint">Expected Check-In</label>
                <input required type="date" value={expectedCheckin} onChange={(e) => setExpectedCheckin(e.target.value)} className="mt-1 w-full border border-hairline-strong bg-panel-raised px-2.5 py-1.5 text-sm text-ink" />
              </div>
            </>
          ) : (
            <div>
              <label className="text-[11px] uppercase tracking-wide text-ink-faint">Notes</label>
              <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} className="mt-1 w-full border border-hairline-strong bg-panel-raised px-2.5 py-1.5 text-sm text-ink" placeholder="Condition, hours, anything the desk should know…" />
            </div>
          )}

          {error && <p className="border border-signal-high/40 bg-signal-high/[0.06] px-2.5 py-1.5 text-[13px] text-signal-high">{error}</p>}
        </div>

        <div className="flex justify-end gap-2 border-t border-hairline pt-3">
          <button type="button" onClick={onClose} className="border border-hairline-strong px-3 py-1.5 text-sm text-ink-dim hover:bg-panel-raised">
            Cancel
          </button>
          <button type="submit" disabled={submitting} className="bg-signal-high px-3 py-1.5 text-sm font-medium text-signal-high-ink hover:brightness-95 disabled:opacity-60">
            {submitting ? "Saving…" : isCheckout ? "Check Out" : "Check In"}
          </button>
        </div>
      </form>
    </div>
  );
}
