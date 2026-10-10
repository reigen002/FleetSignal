"""
Asset and rental lifecycle router.

GET  /assets
GET  /assets/{asset_id}
GET  /assets/{asset_id}/telemetry
GET  /assets/{asset_id}/events

POST /assets/{asset_id}/checkout
POST /assets/{asset_id}/checkin
POST /assets/{asset_id}/simulate      ← demo telemetry trigger
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Asset, RentalEvent, Telemetry
from app.schemas import (
    AssetDetail,
    AssetSummary,
    CheckinRequest,
    CheckoutRequest,
    RentalEventOut,
    SimulateRequest,
    TelemetryOut,
)
from app.utilization import calculate_utilization
from app.services import alerts as alert_service
from app.services.telemetry import AssetNotFound, ingest_simulation
from app.services.transactions import write_transaction

router = APIRouter(prefix="/assets", tags=["Assets"])


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _get_asset_or_404(asset_id: str, db: Session) -> Asset:
    asset = db.get(Asset, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail=f"Asset '{asset_id}' not found.")
    return asset


# ---------------------------------------------------------------------------
# GET /assets
# ---------------------------------------------------------------------------

@router.get("", response_model=list[AssetSummary])
def list_assets(
    equipment_type: Optional[str] = Query(None, description="Filter by equipment type"),
    status: Optional[str] = Query(None, description="Filter by status"),
    site_id: Optional[str] = Query(None, description="Filter by site"),
    db: Session = Depends(get_db),
):
    """Return the full asset list with optional filters."""
    q = db.query(Asset)
    if equipment_type:
        q = q.filter(Asset.equipment_type.ilike(f"%{equipment_type}%"))
    if status:
        q = q.filter(Asset.status == status)
    if site_id:
        q = q.filter(Asset.site_id == site_id)
    return q.order_by(Asset.id).all()


# ---------------------------------------------------------------------------
# GET /assets/{asset_id}
# ---------------------------------------------------------------------------

@router.get("/{asset_id}", response_model=AssetDetail)
def get_asset(asset_id: str, db: Session = Depends(get_db)):
    """Return full asset detail including utilization metrics."""
    asset = _get_asset_or_404(asset_id, db)
    util = calculate_utilization(
        asset.engine_hrs_per_day,
        asset.idle_hrs_per_day,
        asset.operating_days,
    )
    detail = AssetDetail.model_validate(asset)
    detail.utilization = util
    return detail


# ---------------------------------------------------------------------------
# GET /assets/{asset_id}/telemetry
# ---------------------------------------------------------------------------

@router.get("/{asset_id}/telemetry", response_model=list[TelemetryOut])
def get_telemetry(
    asset_id: str,
    limit: int = Query(50, ge=1, le=500),
    scenario: Optional[str] = Query(None, description="Filter by scenario tag"),
    db: Session = Depends(get_db),
):
    """Return recent telemetry readings for an asset (newest first)."""
    _get_asset_or_404(asset_id, db)
    q = db.query(Telemetry).filter(Telemetry.asset_id == asset_id)
    if scenario:
        q = q.filter(Telemetry.scenario == scenario)
    return q.order_by(Telemetry.timestamp.desc(), Telemetry.id.desc()).limit(limit).all()


# ---------------------------------------------------------------------------
# GET /assets/{asset_id}/events
# ---------------------------------------------------------------------------

@router.get("/{asset_id}/events", response_model=list[RentalEventOut])
def get_events(
    asset_id: str,
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Return rental lifecycle events for an asset (newest first)."""
    _get_asset_or_404(asset_id, db)
    return (
        db.query(RentalEvent)
        .filter(RentalEvent.asset_id == asset_id)
        .order_by(RentalEvent.timestamp.desc())
        .limit(limit)
        .all()
    )


# ---------------------------------------------------------------------------
# POST /assets/{asset_id}/checkout
# ---------------------------------------------------------------------------

@router.post("/{asset_id}/checkout", response_model=RentalEventOut)
def checkout_asset(
    asset_id: str,
    body: CheckoutRequest,
    db: Session = Depends(get_db),
):
    """
    Check out an asset.
    Accepts QR code, RFID tag, or manual entry (set identifier_method accordingly).
    """
    with write_transaction(db):
        asset = _get_asset_or_404(asset_id, db)

        if asset.status == "checked_out":
            raise HTTPException(
                status_code=409,
                detail=f"Asset '{asset_id}' is already checked out.",
            )

        # Update asset state
        asset.status = "checked_out"
        asset.operator_id = body.operator_id or asset.operator_id
        asset.site_id = body.site_id or asset.site_id
        asset.customer_name = body.customer_name or asset.customer_name
        asset.checkout_date = datetime.now(tz=timezone.utc)
        if body.expected_return_date:
            asset.expected_return_date = body.expected_return_date

        # Record the event
        event = RentalEvent(
            asset_id=asset_id,
            event_type="checkout",
            timestamp=datetime.now(tz=timezone.utc),
            operator_id=body.operator_id,
            site_id=body.site_id,
            customer_name=body.customer_name,
            expected_return_date=body.expected_return_date,
            notes=body.notes,
            performed_by=body.performed_by,
            identifier_method=body.identifier_method,
        )
        db.add(event)
        db.flush()
        alert_service.reconcile_asset(db, asset)
    db.refresh(event)
    return event


# ---------------------------------------------------------------------------
# POST /assets/{asset_id}/checkin
# ---------------------------------------------------------------------------

@router.post("/{asset_id}/checkin", response_model=RentalEventOut)
def checkin_asset(
    asset_id: str,
    body: CheckinRequest,
    db: Session = Depends(get_db),
):
    """Return an asset to the dealership."""
    with write_transaction(db):
        asset = _get_asset_or_404(asset_id, db)

        if asset.status not in ("checked_out", "overdue"):
            raise HTTPException(
                status_code=409,
                detail=f"Asset '{asset_id}' is not currently checked out.",
            )

        asset.status = "available"
        asset.checkout_date = None
        asset.expected_return_date = None
        asset.operator_id = None
        asset.site_id = None

        event = RentalEvent(
            asset_id=asset_id,
            event_type="checkin",
            timestamp=datetime.now(tz=timezone.utc),
            notes=body.notes,
            performed_by=body.performed_by,
            identifier_method=body.identifier_method,
        )
        db.add(event)
        db.flush()
        alert_service.reconcile_asset(db, asset)
    db.refresh(event)
    return event


# ---------------------------------------------------------------------------
# POST /assets/{asset_id}/simulate
# ---------------------------------------------------------------------------

@router.post("/{asset_id}/simulate", response_model=list[TelemetryOut])
def simulate_telemetry(
    asset_id: str,
    body: SimulateRequest,
    db: Session = Depends(get_db),
):
    """
    Run a deterministic telemetry scenario for demo/testing.

    Scenarios: normal | engine_overheat | location_mismatch
               seatbelt_violation | high_idle | abnormal_fuel
    """
    valid_scenarios = {
        "normal", "engine_overheat", "location_mismatch",
        "seatbelt_violation", "high_idle", "abnormal_fuel",
    }
    if body.scenario not in valid_scenarios:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown scenario '{body.scenario}'. Choose from: {sorted(valid_scenarios)}",
        )
    try:
        return ingest_simulation(db, asset_id, scenario=body.scenario, readings=body.readings)
    except AssetNotFound as error:
        raise HTTPException(404, f"Asset '{asset_id}' not found.") from error
