"""
Forecasts router.

GET /forecasts — demand forecasting by equipment type or site × equipment type.

Two modes, both backward-compatible:

1. Equipment-type-level (existing):
   Called without ?site_id.  Returns one row per equipment type derived from
   the asset rental history (asset-days per month).

2. Site × equipment-type (new):
   When called with ?site_id, returns forecasts derived from the supplementary
   demand history JSON (unit counts per month at the site level) PLUS the
   equipment-type rows, together.  Site-level rows include supply/gap/candidate
   fields that are null on equipment-type rows.

Forecast method: 3-month weighted moving average (weights 1-2-3), then 3
forward periods.  Same inputs always produce the same outputs.

No ML pipeline, no external services, no Redis/Celery.
"""
from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.demand_supplement import all_supplement_segments, get_demand_history
from app.models import Asset
from app.schemas import (
    AllocationCandidate,
    ExpectedReturn,
    ForecastDataPoint,
    ForecastOut,
)

router = APIRouter(prefix="/forecasts", tags=["Forecasts"])


# ---------------------------------------------------------------------------
# Shared forecast math
# ---------------------------------------------------------------------------

def _weighted_moving_avg(values: list[int | float], window: int = 3) -> float:
    """
    3-period weighted moving average (weights oldest→newest: 1,2,3).
    Falls back to simple average when fewer than `window` values.
    Always returns the same result for the same input.
    """
    tail = values[-window:]
    weights = list(range(1, len(tail) + 1))  # [1,2,...,n]
    return sum(v * w for v, w in zip(tail, weights)) / sum(weights)


def _project(values: list[int | float], steps: int = 3) -> list[int]:
    """
    Project `steps` forward periods using WMA, then round to nearest int >= 0.
    Each step feeds back into the next period's window.
    """
    extended = list(values)
    result: list[int] = []
    for _ in range(steps):
        avg = _weighted_moving_avg(extended)
        projected = max(0, round(avg))
        result.append(projected)
        extended.append(projected)
    return result


def _next_periods(last_period: str, count: int) -> list[str]:
    """Return `count` YYYY-MM labels starting one month after last_period."""
    y, m = map(int, last_period.split("-"))
    periods = []
    for _ in range(count):
        m += 1
        if m > 12:
            m = 1
            y += 1
        periods.append(f"{y:04d}-{m:02d}")
    return periods


# ---------------------------------------------------------------------------
# Equipment-type-level forecast (existing behaviour, unchanged)
# ---------------------------------------------------------------------------

def _build_asset_day_history(assets: list[Asset]) -> dict[str, dict[str, float]]:
    """asset-days per month per equipment type, from the seed dataset."""
    history: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for asset in assets:
        period = (
            asset.checkout_date.strftime("%Y-%m") if asset.checkout_date else "2025-01"
        )
        history[asset.equipment_type][period] += asset.operating_days
    return history


def _equipment_type_forecast(
    eq_type: str,
    period_map: dict[str, float],
    returning_assets: list[ExpectedReturn],
    site_id: Optional[str],
) -> ForecastOut:
    sorted_periods = sorted(period_map.keys())
    hist_values = [period_map[p] for p in sorted_periods]

    hist_points = [
        ForecastDataPoint(period=p, demand=period_map[p], is_forecast=False)
        for p in sorted_periods
    ]

    # 3-period WMA projection (asset-days)
    avg = _weighted_moving_avg(hist_values) if hist_values else 0.0
    tail = hist_values[-3:] if len(hist_values) >= 3 else hist_values
    trend_delta = 0.0
    if len(tail) >= 2:
        deltas = [tail[i] - tail[i - 1] for i in range(1, len(tail))]
        trend_delta = round(sum(deltas) / len(deltas), 2)

    last_period = sorted_periods[-1] if sorted_periods else "2025-04"
    next_3 = _next_periods(last_period, 3)
    forecast_points = [
        ForecastDataPoint(
            period=p,
            demand=max(0.0, round(avg + trend_delta * (i + 1), 1)),
            is_forecast=True,
        )
        for i, p in enumerate(next_3)
    ]

    peak_forecast = max((p.demand for p in forecast_points), default=0)
    peak_hist = max(hist_values, default=0)
    peak = max(peak_forecast, peak_hist)
    recommended = math.ceil(peak / 30) if peak > 0 else 1

    if trend_delta > 0:
        trend_txt = f"demand is trending up (+{trend_delta:.1f} days/month)"
    elif trend_delta < 0:
        trend_txt = f"demand is trending down ({trend_delta:.1f} days/month)"
    else:
        trend_txt = "demand is flat"

    rationale = (
        f"3-month moving average: {round(avg,1)} asset-days/month. "
        f"Trend: {trend_txt}. "
        f"Recommended fleet of {recommended} unit(s) covers peak projected demand "
        f"of {peak:.0f} asset-days assuming 30 active days/unit/month."
    )

    return ForecastOut(
        equipment_type=eq_type,
        site_id=site_id,
        history=hist_points,
        forecast=forecast_points,
        expected_returning=returning_assets,
        recommended_allocation=recommended,
        allocation_rationale=rationale,
        # site-level fields: not applicable for equipment-type-level rows
        supply_available=None,
        supply_recoverable=None,
        supply_total_known=None,
        peak_forecast_demand=None,
        projected_gap=None,
        allocation_candidates=None,
    )


# ---------------------------------------------------------------------------
# Site × equipment-type forecast (new)
# ---------------------------------------------------------------------------

_ASSET_STATUS_RANK = {
    # Lower rank = preferred candidate for reallocation
    "available": 0,
    "overdue": 1,      # not a DB status; handled via logic
    "checked_out": 2,
}


def _classify_asset(asset: Asset, demo_date_str: str = "2025-05-12") -> str:
    """
    Return the supply classification of an asset relative to a target site:
      "available"   — status is available
      "recoverable" — checked_out but past expected_return_date (overdue);
                      or no active operator/site → candidate for reallocation
    """
    if asset.status == "available":
        return "available"
    # checked_out assets that are overdue or unassigned are recoverable candidates
    if asset.status == "checked_out":
        from datetime import date
        if asset.expected_return_date:
            ret_date = (
                asset.expected_return_date.date()
                if hasattr(asset.expected_return_date, "date")
                else asset.expected_return_date
            )
            demo = date.fromisoformat(demo_date_str)
            if ret_date <= demo:
                return "recoverable"
    return "assigned"


def _site_level_forecast(
    site_id: str,
    equipment_type: str,
    all_assets: list[Asset],
    demo_date_str: str = "2025-05-12",
    data_dir: Path | None = None,
) -> Optional[ForecastOut]:
    """
    Build a site × equipment-type forecast row using supplementary demand data.
    Returns None if no demand history exists for this segment.
    """
    periods = get_demand_history(site_id, equipment_type, data_dir)
    if not periods:
        return None

    sorted_periods = sorted(periods, key=lambda p: p["period"])
    counts = [p["count"] for p in sorted_periods]

    hist_points = [
        ForecastDataPoint(period=p["period"], demand=float(p["count"]), is_forecast=False)
        for p in sorted_periods
    ]

    # 3-period WMA → 3 forward periods
    projected_counts = _project(counts, steps=3)
    last_period = sorted_periods[-1]["period"]
    next_3 = _next_periods(last_period, 3)
    forecast_points = [
        ForecastDataPoint(period=p, demand=float(c), is_forecast=True)
        for p, c in zip(next_3, projected_counts)
    ]
    peak_demand = max(projected_counts) if projected_counts else 0

    # Supply calculation — assets of matching type
    matching = [
        a for a in all_assets
        if a.equipment_type.lower() == equipment_type.lower()
    ]

    available_assets = [a for a in matching if a.status == "available"]
    # Recoverable: either overdue checked-out assets OR assets with no site/operator
    recoverable_assets = [
        a for a in matching
        if _classify_asset(a, demo_date_str) == "recoverable"
        or (a.site_id is None and a.operator_id is None and a.status == "available")
    ]
    # De-duplicate (an asset counted in available_assets shouldn't also be recoverable
    # unless it's already available — in that case it remains in available bucket)
    recoverable_not_available = [
        a for a in recoverable_assets if a.status != "available"
    ]

    supply_available = len(available_assets)
    supply_recoverable = len(recoverable_not_available)
    supply_total = supply_available + supply_recoverable
    gap = max(0, peak_demand - supply_total)

    # Allocation candidates: deterministic ranking
    # Priority: recoverable overdue first, then available with no site/operator, then by ID
    candidates: list[AllocationCandidate] = []

    def _rank_asset(a: Asset) -> tuple:
        cls = _classify_asset(a, demo_date_str)
        rank = 0 if cls == "recoverable" else 1
        return (rank, a.id)

    candidate_pool = sorted(
        recoverable_assets + [
            a for a in available_assets
            if a.site_id is None and a.operator_id is None
        ],
        key=_rank_asset,
    )
    # De-duplicate by ID
    seen_ids: set[str] = set()
    for a in candidate_pool:
        if a.id in seen_ids:
            continue
        seen_ids.add(a.id)
        cls = _classify_asset(a, demo_date_str)
        if cls == "recoverable":
            reason = (
                f"Asset {a.id} is checked out but overdue for return "
                f"(expected {a.expected_return_date.date() if a.expected_return_date else 'unknown'}) "
                f"— candidate for recovery and redeployment."
            )
            action = f"Recover {a.id} and redeploy to {site_id}."
        else:
            reason = (
                f"Asset {a.id} is available with no assigned site or operator "
                f"— candidate for immediate deployment."
            )
            action = f"Deploy {a.id} to {site_id}."
        candidates.append(
            AllocationCandidate(
                asset_id=a.id,
                equipment_type=a.equipment_type,
                current_status=a.status,
                current_site_id=a.site_id,
                destination_site_id=site_id,
                reason=reason,
                action=action,
            )
        )

    # Returning assets — checked_out with future return dates
    from app.clock import get_demo_date
    demo_date = get_demo_date()
    returning: list[ExpectedReturn] = [
        ExpectedReturn(
            asset_id=a.id,
            equipment_type=a.equipment_type,
            expected_return_date=a.expected_return_date,
        )
        for a in matching
        if a.status == "checked_out"
        and a.expected_return_date
        and (
            a.expected_return_date.date()
            if hasattr(a.expected_return_date, "date")
            else a.expected_return_date
        ) > demo_date
    ]

    # WMA value for explanation
    wma_val = round(_weighted_moving_avg(counts), 2)
    rationale = (
        f"Weighted moving average (1-2-3 weights) over {len(counts)} historical periods: "
        f"{wma_val:.1f} units/month. "
        f"Forecast peak: {peak_demand} units for {next_3[0]}. "
        f"Known supply: {supply_available} available + {supply_recoverable} recoverable = {supply_total} total. "
        f"Projected gap: {gap} unit(s) after recovery."
    )

    return ForecastOut(
        equipment_type=equipment_type,
        site_id=site_id,
        history=hist_points,
        forecast=forecast_points,
        expected_returning=returning,
        recommended_allocation=peak_demand,
        allocation_rationale=rationale,
        supply_available=supply_available,
        supply_recoverable=supply_recoverable,
        supply_total_known=supply_total,
        peak_forecast_demand=peak_demand,
        projected_gap=gap,
        allocation_candidates=candidates if candidates else None,
    )


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@router.get("", response_model=list[ForecastOut])
def get_forecasts(
    equipment_type: Optional[str] = Query(None, description="Filter by equipment type"),
    site_id: Optional[str] = Query(None, description="Filter by site (enables site-level forecast)"),
    db: Session = Depends(get_db),
):
    """
    Return demand forecasts.

    Without site_id: one row per equipment type, asset-days from rental history.
    With site_id:    site-level rows (unit counts from supplement data) PLUS
                     equipment-type rows — all in one response.

    The site-level rows include supply/gap/allocation_candidates fields.
    Equipment-type rows have those fields as null (backward-compatible).
    """
    from app.clock import get_demo_date
    demo_date_str = get_demo_date().isoformat()
    data_dir = db.info.get("data_dir")

    # All assets (used for supply calc)
    all_assets = db.query(Asset).all()

    # ── Equipment-type rows (existing behaviour) ──────────────────────────
    eq_query = db.query(Asset)
    if equipment_type:
        eq_query = eq_query.filter(Asset.equipment_type.ilike(f"%{equipment_type}%"))
    if site_id:
        eq_query = eq_query.filter(Asset.site_id == site_id)

    eq_assets = eq_query.all()
    history_map = _build_asset_day_history(eq_assets)

    returning_map: dict[str, list[ExpectedReturn]] = defaultdict(list)
    for asset in eq_assets:
        if asset.status == "checked_out" and asset.expected_return_date:
            returning_map[asset.equipment_type].append(
                ExpectedReturn(
                    asset_id=asset.id,
                    equipment_type=asset.equipment_type,
                    expected_return_date=asset.expected_return_date,
                )
            )

    results: list[ForecastOut] = []
    for eq_type, period_map in history_map.items():
        results.append(
            _equipment_type_forecast(
                eq_type, period_map, returning_map.get(eq_type, []), site_id
            )
        )

    # ── Site-level rows (new, only when supplement data exists) ───────────
    if site_id:
        for seg in all_supplement_segments(data_dir):
            if seg["site_id"] != site_id:
                continue
            if equipment_type and seg["equipment_type"].lower() != equipment_type.lower():
                continue
            row = _site_level_forecast(
                seg["site_id"],
                seg["equipment_type"],
                all_assets,
                demo_date_str,
                data_dir,
            )
            if row is not None:
                results.append(row)
    else:
        # No site_id filter — emit site-level rows for all supplement segments
        # so the frontend can always see them (they have distinct site_id values)
        for seg in all_supplement_segments(data_dir):
            if equipment_type and seg["equipment_type"].lower() != equipment_type.lower():
                continue
            row = _site_level_forecast(
                seg["site_id"],
                seg["equipment_type"],
                all_assets,
                demo_date_str,
                data_dir,
            )
            if row is not None:
                results.append(row)

    results.sort(key=lambda r: (r.site_id or "", r.equipment_type))
    return results
