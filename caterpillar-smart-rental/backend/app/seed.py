"""
Seed data — the official dataset from the hackathon spec.
In explicit demo mode: POST /admin/seed or automatic seeding on first startup.

NULL site/operator values are intentional anomalies and preserved exactly.
"""
import csv
import json
from datetime import datetime
from pathlib import Path
from sqlalchemy.orm import Session
from app.models import Alert, Asset, Site, Operator, RentalEvent, Telemetry
from app.settings import Settings


SITES = [
    {"id": "S001", "name": "North Construction Zone",   "latitude": 14.5995, "longitude": 120.9842, "address": "Quezon City"},
    {"id": "S002", "name": "South Mining Site",          "latitude": 14.4422, "longitude": 121.0394, "address": "Taguig"},
    {"id": "S003", "name": "East Infrastructure Hub",   "latitude": 14.6760, "longitude": 121.0437, "address": "Marikina"},
    {"id": "S004", "name": "West Roadworks Depot",      "latitude": 14.5547, "longitude": 120.9830, "address": "Pasay"},
    {"id": "S006", "name": "Central Earthworks Base",   "latitude": 14.5995, "longitude": 121.0244, "address": "Mandaluyong"},
]

OPERATORS = [
    {"id": "OP101", "name": "Juan dela Cruz",    "license_class": "Heavy",  "contact": "+63-917-0001"},
    {"id": "OP203", "name": "Maria Santos",      "license_class": "Heavy",  "contact": "+63-918-0002"},
    {"id": "OP106", "name": "Pedro Reyes",       "license_class": "Medium", "contact": "+63-919-0003"},
    {"id": "OP301", "name": "Ana Gomez",         "license_class": "Heavy",  "contact": "+63-920-0004"},
    {"id": "OP114", "name": "Carlos Mendoza",    "license_class": "Medium", "contact": "+63-921-0005"},
]

# Historical CSV status differs from the live demo rental scenario.
# Keep the official CSV unchanged while preserving the three active rentals.
DEMO_STATUS_OVERRIDES = {"EQX1002": "checked_out", "EQX1004": "checked_out", "EQX1007": "checked_out"}
REQUIRED_SCENARIO_FILES = (
    "demand_history_supplement.json", "telemetry_scenarios.json",
    "golden_insights.json", "forecasts.json", "anomalies.json",
)


def load_assets(data_dir: Path | None = None) -> list[dict]:
    """Read the official CSV only when explicitly loading or seeding demo data."""
    directory = Path(data_dir) if data_dir is not None else Settings().data_dir
    path = directory / "seed" / "official_assets.csv"
    try:
        with path.open(newline="", encoding="utf-8-sig") as source:
            rows = list(csv.DictReader(source))
    except OSError as error:
        raise ValueError(f"Demo asset CSV is missing or unreadable: {path}") from error
    if not rows:
        raise ValueError(f"Demo asset CSV is empty: {path}")

    records = []
    for number, row in enumerate(rows, start=2):
        try:
            record = {
                key: row[key] or None
                for key in ("id", "equipment_type", "status", "site_id", "operator_id",
                            "customer_name", "qr_code", "rfid_tag")
            }
            if not record["id"] or not record["equipment_type"] or not record["status"]:
                raise ValueError("id, equipment_type and status are required")
            for key in ("checkout_date", "expected_return_date"):
                record[key] = datetime.fromisoformat(row[key].replace("Z", "+00:00")) if row[key] else None
            for key in ("engine_hrs_per_day", "idle_hrs_per_day"):
                record[key] = float(row[key])
            record["operating_days"] = int(row["operating_days"])
            record["status"] = DEMO_STATUS_OVERRIDES.get(record["id"], record["status"])
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise ValueError(f"Invalid demo asset CSV {path}, row {number}: {error}") from error
        records.append(record)
    return records


def validate_demo_data(data_dir: Path) -> None:
    """Fail startup with the named input instead of silently missing demo data."""
    load_assets(data_dir)
    for filename in REQUIRED_SCENARIO_FILES:
        path = data_dir / "scenarios" / filename
        try:
            with path.open(encoding="utf-8") as source:
                payload = json.load(source)
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"Missing or invalid demo scenario JSON: {path}") from error
        if not isinstance(payload, (dict, list)) or not payload:
            raise ValueError(f"Empty or invalid demo scenario JSON: {path}")


def _seed_lifecycle_events(db: Session, assets: list[dict]) -> None:
    """
    Generate CHECKOUT/CHECKIN/OVERDUE_FLAG events from each asset's official
    checkout/return dates, so the lifecycle timeline isn't empty until a live
    checkout/checkin happens. Skips any asset that already has events (e.g.
    one already mutated by a live checkout/checkin) to stay idempotent.
    """
    from app.clock import get_demo_now
    demo_now = get_demo_now()

    for a in assets:
        asset_id = a["id"]
        if db.query(RentalEvent).filter(RentalEvent.asset_id == asset_id).first():
            continue

        checkout_date = a["checkout_date"]
        return_date = a["expected_return_date"]

        if checkout_date:
            db.add(RentalEvent(
                asset_id=asset_id, event_type="checkout", timestamp=checkout_date,
                operator_id=a.get("operator_id"), site_id=a.get("site_id"),
                customer_name=a.get("customer_name"), expected_return_date=return_date,
                performed_by="Dealer Desk", identifier_method="manual",
            ))

        if a["status"] == "available" and return_date:
            db.add(RentalEvent(
                asset_id=asset_id, event_type="checkin", timestamp=return_date,
                performed_by="Dealer Desk", identifier_method="manual",
            ))
        elif a["status"] == "checked_out" and return_date and return_date < demo_now:
            db.add(RentalEvent(
                asset_id=asset_id, event_type="overdue_flagged", timestamp=return_date,
                expected_return_date=return_date, performed_by="System",
            ))

    db.commit()


def seed_database(db: Session) -> dict:
    """
    Insert all reference data if the database is empty.
    Idempotent — safe to call multiple times.
    Returns counts of inserted records.
    """
    assets = load_assets(db.info.get("data_dir"))
    counts = {"sites": 0, "operators": 0, "assets": 0}

    for s in SITES:
        if not db.get(Site, s["id"]):
            db.add(Site(**s))
            counts["sites"] += 1

    for o in OPERATORS:
        if not db.get(Operator, o["id"]):
            db.add(Operator(**o))
            counts["operators"] += 1

    db.flush()  # ensure FKs exist before asset insert

    for a in assets:
        if not db.get(Asset, a["id"]):
            db.add(Asset(**a))
            counts["assets"] += 1

    db.commit()
    _seed_lifecycle_events(db, assets)
    return counts


def reset_database(db: Session) -> dict:
    """
    Delete all data and re-seed from scratch.
    Called by POST /admin/reset.
    """
    for model in [Alert, Telemetry, RentalEvent, Asset, Operator, Site]:
        db.query(model).delete()
    db.commit()
    return seed_database(db)
