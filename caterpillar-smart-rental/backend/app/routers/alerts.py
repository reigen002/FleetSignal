"""Compatible alert reads and explicit transactional recovery refresh."""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Alert, Asset
from app.schemas import AlertOut
from app.services.alerts import reconcile_asset
from app.services.transactions import write_transaction

router = APIRouter(prefix="/alerts", tags=["Alerts"])


def refresh_alerts(db: Session) -> list[Alert]:
    """Recovery scan owns its transaction; reconciliation never commits."""
    with write_transaction(db):
        for asset in db.query(Asset).order_by(Asset.id).all():
            reconcile_asset(db, asset)
    return db.query(Alert).filter_by(resolved=False).order_by(Alert.created_at.desc(), Alert.id.desc()).all()


@router.get("", response_model=list[AlertOut])
def list_alerts(
    asset_id: Optional[str] = Query(None),
    alert_type: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    resolved: Optional[bool] = Query(False),
    db: Session = Depends(get_db),
):
    query = db.query(Alert)
    if asset_id:
        query = query.filter_by(asset_id=asset_id)
    if alert_type:
        query = query.filter_by(alert_type=alert_type)
    if severity:
        query = query.filter_by(severity=severity)
    if resolved is not None:
        query = query.filter_by(resolved=resolved)
    return query.order_by(Alert.created_at.desc(), Alert.id.desc()).all()


@router.post("/refresh", response_model=list[AlertOut])
def trigger_alert_refresh(db: Session = Depends(get_db)):
    return refresh_alerts(db)
