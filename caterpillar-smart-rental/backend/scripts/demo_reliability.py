"""Demonstrate rollback/retry and committed effects using a disposable file DB.

Run from backend: uv run --frozen python scripts/demo_reliability.py
This script never uses the normal application database or a crash endpoint.
"""
from datetime import datetime, timezone
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.main import create_app
from app.models import Alert, Telemetry
from app.services import alerts
from app.settings import Settings


def snapshot(application):
    with application.state.session_factory() as db:
        return (db.query(Telemetry).count(), [
            (a.id, a.alert_type, a.created_at, a.last_seen_at, a.resolved_at, a.evidence)
            for a in db.query(Alert).order_by(Alert.id)
        ])


def main():
    with TemporaryDirectory(prefix="fleetsignal-demo-") as directory:
        settings = Settings(database_url=f"sqlite:///{(Path(directory) / 'demo.db').as_posix()}", demo_mode=True)
        application = create_app(settings)
        payload = dict(event_id="failure-retry-demo", asset_id="EQX1001",
                       timestamp=datetime.now(timezone.utc).isoformat(), engine_temp_c=115,
                       seatbelt_on=False)
        with TestClient(application) as client:
            before = snapshot(application)
            reconcile = alerts.reconcile_asset
            def fail_after_flush(db, asset):
                reconcile(db, asset)
                db.flush()
                raise RuntimeError("Local demonstration: injected exception before commit")
            with patch.object(alerts, "reconcile_asset", fail_after_flush):
                failed = client.post("/telemetry/events", json=payload)
            assert failed.status_code == 500 and failed.headers["x-request-id"]
            assert snapshot(application) == before
            print("PASS: injected failure after telemetry/alert flush persisted no effects", flush=True)
            accepted = client.post("/telemetry/events", json=payload)
            assert accepted.status_code == 201
            telemetry_id = accepted.json()["telemetry_id"]
            committed = snapshot(application)
            retry = client.post("/telemetry/events", json=payload)
            assert retry.status_code == 200 and retry.json()["telemetry_id"] == telemetry_id
            assert snapshot(application) == committed
            conflict = client.post("/telemetry/events", json={**payload, "engine_temp_c": 116})
            assert conflict.status_code == 409 and snapshot(application) == committed
            hazards = {a["alert_type"] for a in client.get("/alerts?asset_id=EQX1001").json()}
            assert {"engine_overheat", "seatbelt_violation"} <= hazards
            print("PASS: retry committed one row with simultaneous hazards; duplicate/conflict left effects unchanged", flush=True)
            # Ignore this committed HTTP response, as a client with a lost response would.
            lost_payload = {**payload, "event_id": "lost-response-demo"}
            client.post("/telemetry/events", json=lost_payload)
        with TestClient(create_app(settings)) as client:
            assert client.get("/ready").status_code == 200
            replay = client.post("/telemetry/events", json=lost_payload)
            assert replay.status_code == 200 and replay.json()["duplicate"] is True
            rows = client.get("/assets/EQX1001/telemetry").json()
            assert len(rows) == 2
        print("PASS: application restart retained committed events; lost-response retry reused identity", flush=True)
        print("Verified exception rollback and retry; no process-kill recovery claim.", flush=True)


if __name__ == "__main__":
    main()
