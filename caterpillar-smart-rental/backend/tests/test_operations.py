"""Operational responses and log boundaries exposed to clients and operators."""
import json
import logging
from uuid import UUID

import pytest
from sqlalchemy.exc import OperationalError

from tests.test_ingestion import event


def records(caplog):
    return [json.loads(record.getMessage()) for record in caplog.records
            if record.name == "fleetsignal" and record.getMessage().startswith("{")]


def test_liveness_and_readiness_check_schema(client):
    assert client.get("/health").json() == {"status": "ok", "service": "FleetSignal Backend"}
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_database_failure_keeps_liveness_and_readiness_returns_safe_503(client, test_app, monkeypatch):
    application, _ = test_app
    def unavailable(*args, **kwargs):
        raise OperationalError("private connection path", {}, RuntimeError("private infrastructure detail"))
    monkeypatch.setattr(application.state.engine, "connect", unavailable)
    assert client.get("/health").status_code == 200
    response = client.get("/ready", headers={"X-Request-ID": "ready-failure"})
    assert response.status_code == 503
    assert "private" not in response.text
    assert response.headers["x-request-id"] == "ready-failure"


def test_request_id_propagates_for_success_and_expected_errors(client, caplog):
    caplog.set_level(logging.INFO, logger="fleetsignal")
    for path, payload, expected in (("/telemetry/events", event(), 201),
                                     ("/telemetry/events", event(), 200),
                                     ("/telemetry/events", event(engine_temp_c=116), 409),
                                     ("/telemetry/events", event("missing", asset_id="missing"), 404),
                                     ("/telemetry/events", event("invalid", fuel_level_pct=101), 422)):
        response = client.post(path, json=payload, headers={"X-Request-ID": "client.valid-42"})
        assert response.status_code == expected
        assert response.headers["x-request-id"] == "client.valid-42"
    request_logs = [r for r in records(caplog) if r.get("event") == "request_complete"]
    assert {r["status"] for r in request_logs} == {201, 200, 409, 404, 422}
    assert all(r["request_id"] == "client.valid-42" and r["method"] == "POST"
               and r["route"] == "/telemetry/events" and r["elapsed_ms"] >= 0 for r in request_logs)
    ingestion_logs = [r for r in records(caplog) if r.get("event") == "telemetry_ingestion"]
    assert {r["outcome"] for r in ingestion_logs} >= {"accepted", "duplicate", "conflict", "not_found"}
    assert all("event_id" in r and "asset_id" in r for r in ingestion_logs)


def test_unsafe_or_unbounded_request_ids_are_replaced(client):
    for request_id in ("unsafe id", "x" * 65, "<script>", "", "x\ty"):
        response = client.get("/health", headers={"X-Request-ID": request_id})
        assert response.status_code == 200
        assert response.headers["x-request-id"] != request_id
        UUID(response.headers["x-request-id"])
    UUID(client.get("/health").headers["x-request-id"])


@pytest.mark.parametrize("origin,status", [
    ("http://localhost:5173", 200), ("https://untrusted.example", 400),
])
def test_preflight_responses_are_correlated_and_logged(client, caplog, origin, status):
    caplog.set_level(logging.INFO, logger="fleetsignal")
    response = client.options("/telemetry/events", headers={
        "Origin": origin,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,x-request-id",
        "X-Request-ID": "preflight-42",
    })
    assert response.status_code == status
    assert response.headers["x-request-id"] == "preflight-42"
    completion = [record for record in records(caplog) if record.get("event") == "request_complete"]
    assert len(completion) == 1
    assert completion[0]["request_id"] == "preflight-42"
    assert completion[0]["method"] == "OPTIONS"
    assert completion[0]["status"] == status
    assert completion[0]["elapsed_ms"] >= 0
    if status == 200:
        assert response.headers["access-control-allow-origin"] == origin
    else:
        assert "access-control-allow-origin" not in response.headers


def test_structured_ingestion_logs_omit_sensor_fault_and_contact_payload(client, caplog):
    caplog.set_level(logging.INFO, logger="fleetsignal")
    response = client.post("/telemetry/events", json=event(fault_description="sensor-private-text"))
    assert response.status_code == 201
    response = client.post("/assets/EQX1001/checkout", json={"customer_name": "private-customer-name"})
    assert response.status_code == 200
    text = "\n".join(record.getMessage() for record in caplog.records if record.name == "fleetsignal")
    assert "sensor-private-text" not in text
    assert "private-customer-name" not in text
    assert "engine_temp_c" not in text
    assert "+63" not in text


def test_unexpected_failure_has_request_id_safe_body_and_server_traceback(client, monkeypatch, caplog):
    from app.services import alerts
    def fail(db, asset):
        raise RuntimeError("diagnostic failure")
    monkeypatch.setattr(alerts, "reconcile_asset", fail)
    response = client.post("/telemetry/events", json=event(), headers={
        "X-Request-ID": "trace-42", "Origin": "http://localhost:5173",
    })
    assert response.status_code == 500
    assert "diagnostic" not in response.text
    assert response.headers["x-request-id"] == "trace-42"
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "x-request-id" in response.headers["access-control-expose-headers"].lower()
    errors = [r for r in caplog.records if r.name == "fleetsignal" and r.exc_info]
    assert errors
    assert "trace-42" in errors[-1].getMessage()
    assert any(r.get("event") == "telemetry_ingestion" and r.get("outcome") == "error"
               and r.get("request_id") == "trace-42" for r in records(caplog))
