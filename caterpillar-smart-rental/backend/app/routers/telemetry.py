"""HTTP mapping for the externally identified telemetry ingestion contract."""
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import TelemetryEventIn, TelemetryEventResult
from app.services.telemetry import AssetNotFound, EventConflict, ingest_event
from app.services.transactions import DatabaseUnavailable


router = APIRouter(prefix="/telemetry", tags=["Telemetry"])
logger = logging.getLogger("fleetsignal")


@router.post("/events", response_model=TelemetryEventResult, status_code=201)
def accept_event(body: TelemetryEventIn, request: Request, response: Response,
                 db: Session = Depends(get_db)):
    def log(outcome):
        logger.info(json.dumps(dict(event="telemetry_ingestion", request_id=getattr(request.state, "request_id", None),
                                    event_id=body.event_id, asset_id=body.asset_id, outcome=outcome)))
    try:
        result = ingest_event(db, body)
    except EventConflict as error:
        log("conflict")
        raise HTTPException(409, "Event ID already belongs to a different payload") from error
    except AssetNotFound as error:
        log("not_found")
        raise HTTPException(404, "Asset not found") from error
    except DatabaseUnavailable as error:
        log("unavailable")
        raise HTTPException(503, "Database temporarily unavailable; retry the same event ID",
                            headers={"Retry-After": "1"}) from error
    except Exception:
        log("error")
        raise
    log("duplicate" if result["duplicate"] else "accepted")
    response.status_code = 200 if result["duplicate"] else 201
    return result
