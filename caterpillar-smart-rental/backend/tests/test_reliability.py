"""Durable failure, locking and alert episode guarantees on multiple connections."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import event as sa_event

from app.main import create_app
from app.models import Alert, Asset, RentalEvent, Telemetry
from app.settings import Settings
from tests.test_ingestion import alert_snapshot, event


def submit(client, event_id, timestamp, **sensors):
    values = dict(engine_temp_c=85, seatbelt_on=True)
    values.update(sensors)
    return client.post("/telemetry/events", json=event(
        event_id, timestamp=timestamp, **values))


def test_concurrent_identical_events_use_separate_connections(client, test_app, db_session):
    application, _ = test_app
    connections = set()
    def record(connection, _record, _proxy):
        connections.add(id(connection))
    sa_event.listen(application.state.engine, "checkout", record)
    barrier = Barrier(6)
    def send(_):
        barrier.wait(timeout=10)
        return client.post("/telemetry/events", json=event())
    try:
        with ThreadPoolExecutor(max_workers=6) as pool:
            responses = list(pool.map(send, range(6)))
    finally:
        sa_event.remove(application.state.engine, "checkout", record)
    assert sorted(r.status_code for r in responses) == [200] * 5 + [201]
    assert len({r.json()["telemetry_id"] for r in responses}) == 1
    assert len(connections) >= 2
    assert db_session.query(Telemetry).count() == 1
    active = db_session.query(Alert).filter_by(asset_id="EQX1001", resolved=False).all()
    assert len({a.alert_type for a in active}) == len(active)


def test_concurrent_conflicting_events_have_one_winner(client, db_session):
    barrier = Barrier(2)
    payloads = [event(engine_temp_c=115), event(engine_temp_c=85, seatbelt_on=True)]
    def send(payload):
        barrier.wait(timeout=10)
        return payload, client.post("/telemetry/events", json=payload)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(send, payloads))
    assert sorted(response.status_code for _, response in results) == [201, 409]
    winner = next(payload for payload, response in results if response.status_code == 201)
    stored = db_session.query(Telemetry).one()
    assert stored.engine_temp_c == winner["engine_temp_c"]
    types = {a.alert_type for a in db_session.query(Alert).filter_by(asset_id="EQX1001", resolved=False)}
    assert ("engine_overheat" in types) == (winner["engine_temp_c"] >= 110)
    assert ("seatbelt_violation" in types) == (winner["seatbelt_on"] is False)


def test_failure_after_telemetry_and_alert_flush_rolls_back_then_retry_succeeds(client, db_session, monkeypatch):
    from app.services import alerts
    original = alerts.reconcile_asset
    snapshot = alert_snapshot(db_session)
    def fail_after_writes(db, asset):
        original(db, asset)
        db.flush()
        raise RuntimeError("injected processing failure with private details")
    with monkeypatch.context() as patch:
        patch.setattr(alerts, "reconcile_asset", fail_after_writes)
        failed = client.post("/telemetry/events", json=event())
    assert failed.status_code == 500
    assert "private details" not in failed.text
    assert failed.headers["x-request-id"]
    assert db_session.query(Telemetry).count() == 0
    assert alert_snapshot(db_session) == snapshot
    response = client.post("/telemetry/events", json=event())
    assert response.status_code == 201
    assert db_session.query(Telemetry).count() == 1
    assert {"engine_overheat", "seatbelt_violation"} <= {
        a["alert_type"] for a in client.get("/alerts?asset_id=EQX1001").json()}


def test_lock_exhaustion_returns_retryable_503_without_writes(tmp_path):
    application = create_app(Settings(database_url=f"sqlite:///{(tmp_path / 'lock.db').as_posix()}",
                                      demo_mode=True, sqlite_busy_timeout_ms=50))
    with TestClient(application) as client:
        with application.state.engine.connect() as holder:
            holder.exec_driver_sql("BEGIN IMMEDIATE")
            response = client.post("/telemetry/events", json=event())
            assert response.status_code == 503
            assert response.headers["retry-after"]
            assert response.headers["x-request-id"]
            assert client.get("/health").status_code == 200
            holder.rollback()
        with application.state.session_factory() as db:
            assert db.query(Telemetry).count() == 0
        assert client.post("/telemetry/events", json=event()).status_code == 201


def test_all_four_hazards_coexist_and_refresh_preserves_episode(client, db_session):
    response = client.post("/telemetry/events", json=event(
        fuel_consumption_lph=30, fault_code="L001", fault_description="Synthetic location mismatch"))
    assert response.status_code == 201
    before = client.get("/alerts?asset_id=EQX1001").json()
    assert {"engine_overheat", "seatbelt_violation", "abnormal_fuel", "location_mismatch"} <= {
        a["alert_type"] for a in before}
    for _ in range(2):
        assert client.post("/alerts/refresh").status_code == 200
    after = client.get("/alerts?asset_id=EQX1001").json()
    assert {(a["id"], a["created_at"], a["alert_type"]) for a in after} == {
        (a["id"], a["created_at"], a["alert_type"]) for a in before}
    active = db_session.query(Alert).filter_by(asset_id="EQX1001", resolved=False).all()
    assert len({a.alert_type for a in active}) == len(active)
    assert all(a.last_seen_at is not None for a in active)


def test_hazard_resolution_and_recurrence_preserve_history(client, db_session):
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert client.post("/telemetry/events", json=event(timestamp=base.isoformat())).status_code == 201
    first = next(a for a in client.get("/alerts?asset_id=EQX1001").json() if a["alert_type"] == "engine_overheat")
    for i in range(1, 21):
        assert submit(client, f"normal-{i}", (base + timedelta(seconds=i)).isoformat()).status_code == 201
    active = client.get("/alerts?asset_id=EQX1001").json()
    assert "engine_overheat" not in {a["alert_type"] for a in active}
    old = db_session.get(Alert, first["id"])
    db_session.refresh(old)
    assert old.resolved and old.resolved_at is not None
    assert client.post("/telemetry/events", json=event("recurrence", timestamp=(base + timedelta(seconds=21)).isoformat())).status_code == 201
    new = next(a for a in client.get("/alerts?asset_id=EQX1001").json() if a["alert_type"] == "engine_overheat")
    assert new["id"] != first["id"]
    db_session.expire_all()
    assert db_session.get(Alert, first["id"]).resolved is True


def test_late_event_inside_window_contributes_outside_keeps_evidence(client, db_session):
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(10, 30):
        assert submit(client, f"normal-{i}", (base + timedelta(seconds=i)).isoformat()).status_code == 201
    inside = event("late-inside", timestamp=(base + timedelta(seconds=25)).isoformat())
    assert client.post("/telemetry/events", json=inside).status_code == 201
    before = client.get("/alerts?asset_id=EQX1001&alert_type=engine_overheat").json()
    assert len(before) == 1
    outside = event("late-outside", timestamp=base.isoformat(), engine_temp_c=999)
    assert client.post("/telemetry/events", json=outside).status_code == 201
    after = client.get("/alerts?asset_id=EQX1001&alert_type=engine_overheat").json()
    assert after[0]["id"] == before[0]["id"]
    assert after[0]["evidence"] == before[0]["evidence"]
    assert after[0]["message"] == before[0]["message"]
    assert db_session.query(Telemetry).count() == 22


def test_equal_timestamps_select_latest_id_as_evidence(client):
    for name, temp in (("tie-first", 115), ("tie-second", 119)):
        assert client.post("/telemetry/events", json=event(name, engine_temp_c=temp)).status_code == 201
    alert = client.get("/alerts?asset_id=EQX1001&alert_type=engine_overheat").json()[0]
    assert "119.0" in alert["message"]
    history = client.get("/assets/EQX1001/telemetry").json()
    assert history[0]["id"] > history[1]["id"]
    for i in range(20):
        assert submit(client, f"same-time-{i}", "2026-10-10T06:20:00Z").status_code == 201
    assert client.get("/alerts?asset_id=EQX1001&alert_type=engine_overheat").json() == []


@pytest.mark.parametrize("action,asset_id", [("checkin", "EQX1002"), ("checkout", "EQX1001")])
def test_rental_failure_rolls_back_state_event_and_alerts(client, db_session, monkeypatch, action, asset_id):
    from app.services import alerts
    original = alerts.reconcile_asset
    before_status = db_session.get(Asset, asset_id).status
    before_events = db_session.query(RentalEvent).count()
    snapshot = alert_snapshot(db_session)
    def fail_after_writes(db, asset):
        original(db, asset)
        db.flush()
        raise RuntimeError("injected rental failure")
    with monkeypatch.context() as patch:
        patch.setattr(alerts, "reconcile_asset", fail_after_writes)
        assert client.post(f"/assets/{asset_id}/{action}", json={}).status_code == 500
    db_session.expire_all()
    assert db_session.get(Asset, asset_id).status == before_status
    assert db_session.query(RentalEvent).count() == before_events
    assert alert_snapshot(db_session) == snapshot
    assert client.post(f"/assets/{asset_id}/{action}", json={}).status_code == 200
    db_session.expire_all()
    assert db_session.query(RentalEvent).count() == before_events + 1
    if action == "checkin":
        assert not {"no_site", "no_operator", "overdue"} & {
            a["alert_type"] for a in client.get(f"/alerts?asset_id={asset_id}").json()}


@pytest.mark.parametrize("readings", [0, -1, 101])
def test_simulation_reading_count_bounds(client, db_session, readings):
    assert client.post("/assets/EQX1001/simulate", json={"readings": readings}).status_code == 422
    assert db_session.query(Telemetry).count() == 0


def test_simulation_batch_rolls_back_every_reading(client, db_session, monkeypatch):
    from app.services import alerts
    snapshot = alert_snapshot(db_session)
    def fail(db, asset):
        raise RuntimeError("injected batch failure")
    with monkeypatch.context() as patch:
        patch.setattr(alerts, "reconcile_asset", fail)
        assert client.post("/assets/EQX1001/simulate", json={"scenario": "engine_overheat", "readings": 10}).status_code == 500
    assert db_session.query(Telemetry).count() == 0
    assert alert_snapshot(db_session) == snapshot
    success = client.post("/assets/EQX1001/simulate", json={"scenario": "engine_overheat", "readings": 10})
    assert success.status_code == 200 and len(success.json()) == 10
    assert client.get("/alerts?asset_id=EQX1001&alert_type=engine_overheat").json()
    assert db_session.query(Telemetry).count() == 10


@pytest.mark.parametrize("readings", [1, 100])
def test_simulation_valid_boundaries_have_fresh_ids_and_external_retries(client, db_session, readings):
    first = client.post("/assets/EQX1001/simulate", json={"readings": readings})
    second = client.post("/assets/EQX1001/simulate", json={"readings": readings})
    assert first.status_code == second.status_code == 200
    assert len(first.json()) == len(second.json()) == readings
    assert not {r["event_id"] for r in first.json()} & {r["event_id"] for r in second.json()}
    reading = first.json()[0]
    payload = {key: value for key, value in reading.items() if key not in {"id", "received_at", "scenario"}}
    before = alert_snapshot(db_session)
    retry = client.post("/telemetry/events", json=payload)
    assert retry.status_code == 200
    assert retry.json()["telemetry_id"] == reading["id"]
    assert retry.json()["duplicate"] is True
    assert db_session.query(Telemetry).count() == readings * 2
    assert alert_snapshot(db_session) == before


def test_simulation_default_is_ten(client):
    response = client.post("/assets/EQX1001/simulate", json={})
    assert response.status_code == 200
    assert len(response.json()) == 10


def test_business_clock_does_not_rewrite_event_or_acceptance_time(client, db_session, monkeypatch):
    monkeypatch.setenv("SRTS_DEMO_DATE", "2000-01-01")
    payload = event(timestamp="2026-10-10T11:50:00+05:30")
    before = datetime.now(timezone.utc)
    assert client.post("/telemetry/events", json=payload).status_code == 201
    after = datetime.now(timezone.utc)
    row = db_session.query(Telemetry).one()
    assert row.timestamp == datetime(2026, 10, 10, 6, 20, tzinfo=timezone.utc)
    assert before <= row.received_at <= after


def test_explicit_refresh_failure_rolls_back_evaluation_changes(client, db_session, monkeypatch):
    from app.routers import alerts
    before = alert_snapshot(db_session)
    original = alerts.reconcile_asset
    def fail_after_evaluation(db, asset):
        original(db, asset)
        db.flush()
        raise RuntimeError("injected refresh failure")
    monkeypatch.setattr(alerts, "reconcile_asset", fail_after_evaluation)
    assert client.post("/alerts/refresh").status_code == 500
    assert alert_snapshot(db_session) == before
