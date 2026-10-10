"""
Recommendations router.

GET /recommendations — produce actionable, human-readable recommendations
                       for every asset showing anomalies, PLUS forecast-driven
                       allocation recommendations derived from site-level demand.

Two recommendation classes:

1. Asset anomaly recs (existing, unchanged):
   One consolidated rec per asset with detected issues (no_site, no_operator,
   high_idle, low_utilization, etc.).  EQX1002 hero story lives here.

2. Forecast allocation recs (new):
   One rec per site × equipment-type segment where projected_gap > 0 and
   allocation_candidates exist.  EQX1007 → S003 story lives here.

Both classes are returned in the same list, sorted CRITICAL → HIGH → MEDIUM → LOW.
The shape is the same RecommendationOut — no new schema needed.
"""
from fastapi import APIRouter, Depends
from pathlib import Path
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Alert, Asset
from app.schemas import RecommendationOut
from app.utilization import calculate_utilization

router = APIRouter(prefix="/recommendations", tags=["Recommendations"])

# Telemetry-derived alert types -> (recommended action, human label)
_TELEMETRY_ACTIONS = {
    "engine_overheat": ("inspect the cooling system before continued operation", "engine overheating"),
    "seatbelt_violation": ("notify the operator and deliver seatbelt safety coaching before continued operation", "seatbelt not fastened"),
    "location_mismatch": ("verify the asset's current location and assignment", "location mismatch"),
    "abnormal_fuel": ("check for a fuel leak or inefficiency and inspect the asset", "abnormal fuel consumption"),
}


# ---------------------------------------------------------------------------
# Rule-based recommendation engine (anomaly recs — unchanged)
# ---------------------------------------------------------------------------

PRODUCTIVE_RATIO_CRITICAL = 5.0     # %
PRODUCTIVE_RATIO_LOW = 25.0         # %
SHIFT_UTIL_LOW = 30.0               # %

_SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}


def _highest(severities: list[str]) -> str:
    if not severities:
        return "LOW"
    return min(severities, key=lambda s: _SEVERITY_ORDER.get(s, 99))


def _build_anomaly_recommendations(assets: list[Asset]) -> list[RecommendationOut]:
    recs: list[RecommendationOut] = []

    for asset in assets:
        util = calculate_utilization(
            asset.engine_hrs_per_day,
            asset.idle_hrs_per_day,
            asset.operating_days,
        )

        issues: list[str] = []
        severities: list[str] = []
        evidence_parts: list[str] = []
        rec_parts: list[str] = []

        # ── Condition: No site assigned (only anomalous while actively rented —
        # a returned/available asset has no active site by definition) ────
        if asset.site_id is None and asset.status == "checked_out":
            issues.append("no site assigned")
            severities.append("HIGH")
            evidence_parts.append(
                "no registered deployment site — cannot confirm asset location, "
                "compliance, or utilization"
            )
            rec_parts.append(
                "verify the asset's physical location and assign a site in the system"
            )

        # ── Condition: No operator assigned ──────────────────────────────
        if asset.operator_id is None and asset.status == "checked_out":
            issues.append("no operator assigned")
            severities.append("HIGH")
            evidence_parts.append(
                "no licensed operator on record — untracked operation is a safety "
                "and liability risk"
            )
            rec_parts.append(
                "assign a licensed operator before any operation resumes"
            )

        # ── Condition: Zero productive use / high idle ────────────────────
        if util.productive_ratio_pct == 0 and util.idle_hrs_total > 0:
            issues.append("zero productive engine use")
            severities.append("HIGH")
            evidence_parts.append(
                f"{util.idle_hrs_total:.0f}h cumulative idle with zero engine hours "
                f"over {asset.operating_days} days — asset is powered on but not working"
            )
            rec_parts.append(
                "review the active work order and consider reallocating or returning "
                "the asset to the dealership to avoid unnecessary rental cost and wear"
            )

        # ── Condition: Low productive ratio (some engine use) ─────────────
        elif 0 < util.productive_ratio_pct < PRODUCTIVE_RATIO_LOW:
            issues.append(f"low productive ratio ({util.productive_ratio_pct}%)")
            severities.append("MEDIUM")
            evidence_parts.append(util.label)
            rec_parts.append(
                "investigate cause of high idle time — consider driver coaching, "
                "shift scheduling review, or redeployment to a busier site"
            )

        # ── Condition: Low shift utilization ─────────────────────────────
        if (
            0 < util.shift_utilization_pct < SHIFT_UTIL_LOW
            and util.productive_ratio_pct >= PRODUCTIVE_RATIO_LOW
        ):
            issues.append(f"low shift utilization ({util.shift_utilization_pct}%)")
            severities.append("MEDIUM")
            evidence_parts.append(util.label)
            rec_parts.append(
                "consolidate work to fewer assets and consider returning underused "
                "equipment to the dealership or reallocating to a higher-demand site"
            )

        if not issues:
            continue

        overall_severity = _highest(severities)
        issue_summary = (
            issues[0].capitalize() if len(issues) == 1
            else "; ".join(i.capitalize() for i in issues)
        )
        evidence_text = f"{asset.equipment_type} {asset.id}: " + ". Additionally: ".join(
            part[0].upper() + part[1:] for part in evidence_parts
        ) + "."
        rec_text = (
            rec_parts[0].capitalize() + "."
            if len(rec_parts) == 1
            else " ".join(
                (p.capitalize() if i == 0 else p) + "."
                for i, p in enumerate(rec_parts)
            )
        )

        recs.append(RecommendationOut(
            asset=asset.id,
            issue=issue_summary,
            severity=overall_severity,
            evidence=evidence_text,
            recommendation=rec_text,
        ))

    return recs


# ---------------------------------------------------------------------------
# Telemetry-driven maintenance/safety recommendations
# ---------------------------------------------------------------------------

def _build_telemetry_recommendations(db: Session) -> list[RecommendationOut]:
    """
    One consolidated maintenance/safety rec per asset carrying unresolved
    telemetry-based alerts (engine_overheat, seatbelt_violation,
    location_mismatch, abnormal_fuel) — spec §5 "Predictive maintenance".
    """
    alerts = (
        db.query(Alert)
        .filter(Alert.alert_type.in_(_TELEMETRY_ACTIONS.keys()), Alert.resolved.is_(False))
        .order_by(Alert.asset_id, Alert.created_at)
        .all()
    )

    by_asset: dict[str, list[Alert]] = {}
    for a in alerts:
        by_asset.setdefault(a.asset_id, []).append(a)

    recs: list[RecommendationOut] = []
    for asset_id, asset_alerts in by_asset.items():
        severities = [a.severity for a in asset_alerts]
        overall_severity = _highest(severities)
        labels = [_TELEMETRY_ACTIONS[a.alert_type][1] for a in asset_alerts]
        actions = dict.fromkeys(_TELEMETRY_ACTIONS[a.alert_type][0] for a in asset_alerts)

        issue_summary = "; ".join(l.capitalize() for l in dict.fromkeys(labels))
        evidence_text = " ".join(f"{a.message} {a.evidence}".strip() for a in asset_alerts)
        rec_text = " ".join(f"{action.capitalize()}." for action in actions)

        recs.append(RecommendationOut(
            asset=asset_id,
            issue=issue_summary,
            severity=overall_severity,
            evidence=evidence_text,
            recommendation=rec_text,
        ))

    return recs


# ---------------------------------------------------------------------------
# Forecast-driven allocation recommendations (new)
# ---------------------------------------------------------------------------

def _build_allocation_recommendations(
    all_assets: list[Asset],
    data_dir: Path | None = None,
) -> list[RecommendationOut]:
    """
    For each site × equipment-type segment in the demand supplement that has
    projected_gap > 0 and at least one allocation candidate, emit ONE
    consolidated recommendation describing the allocation action and gap.
    """
    from app.routers.forecasts import _site_level_forecast
    from app.demand_supplement import all_supplement_segments
    from app.clock import get_demo_date

    demo_date_str = get_demo_date().isoformat()
    recs: list[RecommendationOut] = []

    for seg in all_supplement_segments(data_dir):
        row = _site_level_forecast(
            seg["site_id"],
            seg["equipment_type"],
            all_assets,
            demo_date_str,
            data_dir,
        )
        if row is None:
            continue
        if (row.projected_gap or 0) <= 0:
            continue
        if not row.allocation_candidates:
            continue

        # Pick best candidate (already ranked in _site_level_forecast)
        best = row.allocation_candidates[0]
        other_candidates = row.allocation_candidates[1:]

        # One rec per forecast segment — references the primary candidate asset
        gap = row.projected_gap or 0
        supply_total = row.supply_total_known or 0
        peak_demand = row.peak_forecast_demand or 0

        candidate_ids = [c.asset_id for c in row.allocation_candidates]
        candidate_list = ", ".join(candidate_ids)

        evidence_parts = [
            f"Forecast demand for {row.equipment_type} at site {row.site_id}: "
            f"{peak_demand} unit(s)/month (weighted moving average over "
            f"{len(row.history)} historical periods).",
            f"Known supply: {row.supply_available} available + "
            f"{row.supply_recoverable} recoverable = {supply_total} total.",
            f"Projected gap after recovery: {gap} unit(s).",
            f"Recovery candidate(s): {candidate_list}.",
        ]
        if best.current_status == "recoverable" or best.current_status == "checked_out":
            evidence_parts.append(best.reason)

        rec_parts = [
            f"Recover and redeploy {best.asset_id} ({best.equipment_type}) "
            f"to site {row.site_id}.",
        ]
        if gap > len(row.allocation_candidates):
            remaining = gap - len(row.allocation_candidates)
            rec_parts.append(
                f"After recovery, {remaining} additional {row.equipment_type.lower()} "
                f"unit(s) may still be required — consider procurement or cross-site transfer."
            )
        elif gap == 1 and supply_total >= 1:
            rec_parts.append(
                f"Forecast demand is {peak_demand} unit(s); known supply after recovery "
                f"is {supply_total}. One additional unit may still be required — "
                f"monitor demand before committing to additional procurement."
            )

        recs.append(RecommendationOut(
            asset=best.asset_id,
            issue=f"Forecast demand gap — {row.equipment_type} at {row.site_id}",
            severity="HIGH",
            evidence=" ".join(evidence_parts),
            recommendation=" ".join(rec_parts),
        ))

    return recs


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@router.get("", response_model=list[RecommendationOut])
def get_recommendations(db: Session = Depends(get_db)):
    """
    Return actionable recommendations:
      1. Asset anomaly recs (EQX1002 hero story) — one per asset.
      2. Telemetry maintenance/safety recs — one per asset with an active
         engine_overheat/seatbelt_violation/location_mismatch/abnormal_fuel alert.
      3. Forecast allocation recs (EQX1007 → S003 story) — one per forecast gap.
    Both are ordered by severity (CRITICAL → LOW).
    """
    assets = db.query(Asset).order_by(Asset.id).all()

    anomaly_recs = _build_anomaly_recommendations(assets)
    telemetry_recs = _build_telemetry_recommendations(db)
    allocation_recs = _build_allocation_recommendations(assets, db.info.get("data_dir"))

    all_recs = anomaly_recs + telemetry_recs + allocation_recs
    all_recs.sort(key=lambda r: _SEVERITY_ORDER.get(r.severity, 99))
    return all_recs

