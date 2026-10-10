"""Retry-safe event identity and telemetry/alert effects in one transaction."""
from datetime import datetime, timezone
import hashlib
import json

from app.models import Asset, Telemetry
from app.services import alerts
from app.services.transactions import write_transaction


class EventConflict(Exception):
    pass


class AssetNotFound(Exception):
    pass


def payload_hash(payload):
    # Defaults are included, making omitted optional fields equivalent to null.
    semantic = payload.model_dump(mode="json")
    for key, value in semantic.items():
        if isinstance(value, float) and value == 0:
            semantic[key] = 0.0  # normalize negative zero
    canonical = json.dumps(semantic, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _accept(db, payload, scenario=None):
    digest = payload_hash(payload)
    existing = db.query(Telemetry).filter_by(event_id=payload.event_id).one_or_none()
    if existing is not None:
        if existing.payload_hash != digest:
            raise EventConflict("Event ID already belongs to a different payload")
        return existing, True
    if db.get(Asset, payload.asset_id) is None:
        raise AssetNotFound("Asset not found")
    row = Telemetry(**payload.model_dump(), payload_hash=digest,
                    received_at=datetime.now(timezone.utc), scenario=scenario)
    db.add(row)
    db.flush()
    return row, False


def _accept_batch(db, payloads, scenario=None):
    accepted = [_accept(db, payload, scenario) for payload in payloads]
    affected = {row.asset_id for row, duplicate in accepted if not duplicate}
    for asset_id in sorted(affected):
        alerts.reconcile_asset(db, db.get(Asset, asset_id))
    return accepted


def ingest_event(db, payload):
    with write_transaction(db):
        row, duplicate = _accept_batch(db, [payload])[0]
        result = dict(event_id=row.event_id, telemetry_id=row.id, asset_id=row.asset_id, duplicate=duplicate)
    # The context committed successfully before the HTTP handler receives success.
    return result


def ingest_simulation(db, asset_id, scenario, readings):
    from app.simulator import generate_readings
    with write_transaction(db):
        asset = db.get(Asset, asset_id, populate_existing=True)
        if asset is None:
            raise AssetNotFound("Asset not found")
        payloads = generate_readings(asset, scenario, readings)
        accepted = _accept_batch(db, payloads, scenario=scenario)
        rows = [row for row, _duplicate in accepted]
    return rows
