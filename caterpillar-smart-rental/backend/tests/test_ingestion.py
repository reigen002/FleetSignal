"""HTTP contract and durable effects against each app's file-backed SQLite DB."""
import json
import pytest

from app.models import Alert, Asset, Telemetry


def event(event_id="external-1", **changes):
    payload = {
        "event_id": event_id,
        "asset_id": "EQX1001",
        "timestamp": "2026-10-10T06:20:00Z",
        "engine_temp_c": 115.0,
        "seatbelt_on": False,
    }
    payload.update(changes)
    return payload


def alert_snapshot(db):
    db.expire_all()
    return [(a.id, a.created_at, a.resolved_at, a.evidence,
             getattr(a, "last_seen_at", None))
            for a in db.query(Alert).order_by(Alert.id).all()]


def test_event_commits_alerts_and_exact_retry_does_not_mutate(client, db_session):
    before = db_session.query(Telemetry).count()
    response = client.post("/telemetry/events", json=event())
    assert response.status_code == 201, response.text
    result = response.json()
    assert result == {"event_id": "external-1", "telemetry_id": result["telemetry_id"],
                      "asset_id": "EQX1001", "duplicate": False}
    hazards = client.get("/alerts?asset_id=EQX1001").json()
    assert {"engine_overheat", "seatbelt_violation"} <= {a["alert_type"] for a in hazards}
    snapshot = alert_snapshot(db_session)
    retry = client.post("/telemetry/events", json=event())
    assert retry.status_code == 200
    assert retry.json() == dict(result, duplicate=True)
    assert db_session.query(Telemetry).count() == before + 1
    assert alert_snapshot(db_session) == snapshot
    stored = db_session.get(Telemetry, result["telemetry_id"])
    assert stored.received_at is not None
    assert len(stored.payload_hash) == 64
    assert stored.scenario is None
    asset = db_session.get(Asset, "EQX1001")
    assert (asset.engine_hrs_per_day, asset.idle_hrs_per_day) == (1.5, 10.0)


def test_semantically_equivalent_retry(client, db_session):
    first = client.post("/telemetry/events", json=event())
    assert first.status_code == 201
    equivalent = event(timestamp="2026-10-10T11:50:00+05:30", fault_code=None,
                       latitude=None, longitude=None, engine_hours=None)
    snapshot = alert_snapshot(db_session)
    retry = client.post("/telemetry/events", json=equivalent)
    assert retry.status_code == 200
    assert retry.json()["telemetry_id"] == first.json()["telemetry_id"]
    assert alert_snapshot(db_session) == snapshot


@pytest.mark.parametrize("changes", [
    {"asset_id": "EQX1003"}, {"timestamp": "2026-10-10T06:20:01Z"},
    {"engine_temp_c": 116.0}, {"seatbelt_on": True},
])
def test_conflicting_identity_has_no_effects(client, db_session, changes):
    assert client.post("/telemetry/events", json=event()).status_code == 201
    snapshot = alert_snapshot(db_session)
    response = client.post("/telemetry/events", json=event(**changes))
    assert response.status_code == 409
    assert db_session.query(Telemetry).count() == 1
    assert alert_snapshot(db_session) == snapshot


def test_unknown_asset_has_no_effects(client, db_session):
    snapshot = alert_snapshot(db_session)
    response = client.post("/telemetry/events", json=event(asset_id="missing"))
    assert response.status_code == 404
    assert db_session.query(Telemetry).count() == 0
    assert alert_snapshot(db_session) == snapshot


@pytest.mark.parametrize("changes", [
    {"event_id": ""}, {"event_id": "x y"}, {"event_id": "x" * 129},
    {"asset_id": "x" * 21}, {"timestamp": "2026-10-10T06:20:00"},
    {"engine_temp_c": None, "seatbelt_on": None},
    {"latitude": 14.0}, {"longitude": 121.0},
    {"latitude": 91, "longitude": 120}, {"latitude": 14, "longitude": -181},
    {"fuel_level_pct": -1}, {"fuel_level_pct": 101}, {"engine_hours": -0.1},
    {"idle_time_hours": -1}, {"fuel_consumption_lph": -1},
    {"fault_code": "x" * 51}, {"fault_description": "x" * 201},
    {"scenario": "normal"}, {"id": 5}, {"received_at": "2026-10-10T06:20:00Z"},
    {"payload_hash": "x"}, {"surprise": True},
])
def test_invalid_input_cannot_write(client, db_session, changes):
    snapshot = alert_snapshot(db_session)
    response = client.post("/telemetry/events", json=event(**changes))
    assert response.status_code == 422, response.text
    assert db_session.query(Telemetry).count() == 0
    assert alert_snapshot(db_session) == snapshot


@pytest.mark.parametrize("sensor", ["latitude", "longitude", "engine_temp_c", "engine_hours",
                                     "fuel_level_pct", "fuel_consumption_lph", "idle_time_hours"])
@pytest.mark.parametrize("number", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_numbers_cannot_write(client, db_session, sensor, number):
    payload = event(latitude=14.0, longitude=120.0)
    payload[sensor] = number
    response = client.post("/telemetry/events", json=payload)
    assert response.status_code == 422
    assert db_session.query(Telemetry).count() == 0


@pytest.mark.parametrize("sensor", ["latitude", "longitude", "engine_temp_c", "engine_hours",
                                     "fuel_level_pct", "fuel_consumption_lph", "idle_time_hours"])
@pytest.mark.parametrize("number", ["1e999", "-1e999", "NaN", "Infinity", "-Infinity"])
def test_raw_nonfinite_numbers_return_safe_validation_without_effects(client, db_session, sensor, number):
    snapshot = alert_snapshot(db_session)
    payload = event(latitude=14.0, longitude=120.0)
    payload[sensor] = "RAW_NUMBER"
    body = json.dumps(payload).replace('"RAW_NUMBER"', number)
    response = client.post("/telemetry/events", content=body, headers={
        "Content-Type": "application/json", "X-Request-ID": "nonfinite-42",
    })
    assert response.status_code == 422, response.text
    assert response.headers["x-request-id"] == "nonfinite-42"
    detail = response.json()["detail"]
    assert all(set(error) == {"type", "loc", "msg"} for error in detail)
    assert any(error["loc"] == ["body", sensor] and error["type"] == "finite_number"
               for error in detail)
    assert db_session.query(Telemetry).count() == 0
    assert alert_snapshot(db_session) == snapshot


def test_boundary_values_and_future_occurrence_allowed(client):
    payload = event(event_id="x" * 128, timestamp="2030-01-01T00:00:00+00:00",
                    latitude=-90, longitude=180, engine_temp_c=-1000,
                    engine_hours=0, idle_time_hours=0, fuel_consumption_lph=0,
                    fuel_level_pct=100, fault_code="x" * 50, fault_description="x" * 200)
    response = client.post("/telemetry/events", json=payload)
    assert response.status_code == 201


def test_lost_response_retry_returns_original_effects(client, db_session):
    # Deliberately discard the first success body to model a lost acknowledgement.
    client.post("/telemetry/events", json=event())
    stored = db_session.query(Telemetry).one()
    snapshot = alert_snapshot(db_session)
    response = client.post("/telemetry/events", json=event())
    assert response.status_code == 200
    assert response.json()["telemetry_id"] == stored.id
    assert response.json()["duplicate"] is True
    assert db_session.query(Telemetry).count() == 1
    assert alert_snapshot(db_session) == snapshot
