"""Evaluate independent conditions and reconcile stable alert episodes.

This module never starts or commits a transaction. Its caller owns all writes.
"""
from datetime import datetime, timezone

from app.clock import get_demo_now
from app.models import Alert, Telemetry
from app.utilization import calculate_utilization


OVERHEAT_THRESHOLD_C = 110.0
PRODUCTIVE_RATIO_LOW_THRESHOLD = 10.0
SHIFT_UTILIZATION_LOW_THRESHOLD = 30.0
FUEL_SPIKE_MULTIPLIER = 2.0


def evaluate_conditions(asset, recent):
    """Return one condition per type, using newest qualifying evidence in order."""
    conditions = {}
    def add(kind, severity, message, evidence=""):
        conditions[kind] = dict(severity=severity, message=message, evidence=evidence)

    if asset.status == "checked_out":
        if asset.site_id is None:
            add("no_site", "HIGH", f"Asset {asset.id} has no assigned site.",
                "site_id is NULL — asset cannot be located or dispatched.")
        if asset.operator_id is None:
            add("no_operator", "HIGH", f"Asset {asset.id} has no assigned operator.",
                "operator_id is NULL — asset may be operating unsupervised.")
        if asset.expected_return_date:
            returned = asset.expected_return_date
            if returned.tzinfo is None:
                returned = returned.replace(tzinfo=timezone.utc)
            if returned < get_demo_now():
                add("overdue", "CRITICAL", f"Asset {asset.id} is overdue for return.",
                    f"Expected return: {asset.expected_return_date.isoformat()}")

    util = calculate_utilization(asset.engine_hrs_per_day, asset.idle_hrs_per_day, asset.operating_days)
    if util.productive_ratio_pct == 0 and util.idle_hrs_total > 0:
        add("high_idle", "HIGH", f"Asset {asset.id} shows zero productive engine use with "
            f"{util.idle_hrs_total:.0f}h cumulative idle time.",
            f"engine_hrs_per_day={asset.engine_hrs_per_day}, idle_hrs_per_day={asset.idle_hrs_per_day}, "
            f"operating_days={asset.operating_days}. Likely stationary / unassigned.")
    elif util.productive_ratio_pct < PRODUCTIVE_RATIO_LOW_THRESHOLD:
        add("high_idle", "MEDIUM", f"Asset {asset.id} productive ratio only {util.productive_ratio_pct}%.", util.label)
    if 0 < util.shift_utilization_pct < SHIFT_UTILIZATION_LOW_THRESHOLD:
        add("low_utilization", "MEDIUM", f"Asset {asset.id} shift utilization is low at {util.shift_utilization_pct}%.", util.label)

    for reading in recent:
        timestamp = reading.timestamp.isoformat()
        if ("engine_overheat" not in conditions and reading.engine_temp_c is not None
                and reading.engine_temp_c >= OVERHEAT_THRESHOLD_C):
            add("engine_overheat", "CRITICAL", f"Asset {asset.id} engine temperature "
                f"{reading.engine_temp_c:.1f}°C — overheating.",
                f"Timestamp: {timestamp}, fault: {reading.fault_code}")
        if "seatbelt_violation" not in conditions and reading.seatbelt_on is False:
            add("seatbelt_violation", "HIGH", f"Asset {asset.id} operator seatbelt not fastened.",
                f"Timestamp: {timestamp}")
        if ("abnormal_fuel" not in conditions and reading.fuel_consumption_lph is not None
                and reading.fuel_consumption_lph > 12.0 * FUEL_SPIKE_MULTIPLIER):
            add("abnormal_fuel", "MEDIUM", f"Asset {asset.id} fuel consumption "
                f"{reading.fuel_consumption_lph:.1f} L/h — abnormally high.",
                f"Baseline ~12 L/h. Timestamp: {timestamp}")
        if ("location_mismatch" not in conditions and reading.fault_code
                and reading.fault_code.startswith("L")):
            add("location_mismatch", "HIGH", f"Asset {asset.id} outside registered site boundary.",
                reading.fault_description or reading.fault_code)
    return conditions


def reconcile_asset(db, asset):
    """Persist evaluation in the caller's transaction, preserving active identity."""
    recent = (db.query(Telemetry).filter_by(asset_id=asset.id)
              .order_by(Telemetry.timestamp.desc(), Telemetry.id.desc()).limit(20).all())
    conditions = evaluate_conditions(asset, recent)
    active = {alert.alert_type: alert for alert in db.query(Alert)
              .filter_by(asset_id=asset.id, resolved=False).all()}
    now = datetime.now(timezone.utc)
    for kind, fields in conditions.items():
        alert = active.get(kind)
        if alert is None:
            alert = Alert(asset_id=asset.id, alert_type=kind, resolved=False, created_at=now, **fields)
            db.add(alert)
        else:
            for name, value in fields.items():
                if getattr(alert, name) != value:
                    setattr(alert, name, value)
        alert.last_seen_at = now
    for kind, alert in active.items():
        if kind not in conditions:
            alert.resolved = True
            alert.resolved_at = now
    db.flush()
    return conditions
