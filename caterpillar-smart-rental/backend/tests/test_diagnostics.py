"""Operational signals describe real transactions without changing their contract."""
import json
import logging

from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings
from tests.test_ingestion import event


def signals(caplog, kind):
    return [data for record in caplog.records if record.name == 'fleetsignal'
            and record.getMessage().startswith('{')
            if (data := json.loads(record.getMessage())).get('event') == kind]


def test_transaction_signals_correlate_success_duplicate_conflict(client, caplog):
    caplog.set_level(logging.INFO, logger='fleetsignal')
    for request_id, change, status in [('new', {}, 201), ('retry', {}, 200),
                                        ('conflict', {'engine_temp_c': 116}, 409)]:
        assert client.post('/telemetry/events', json=event(**change),
                           headers={'X-Request-ID': request_id}).status_code == status
    transactions = signals(caplog, 'write_transaction')
    assert [r['request_id'] for r in transactions] == ['new', 'retry', 'conflict']
    assert [r['outcome'] for r in transactions] == ['committed', 'committed', 'rolled_back']
    for record in transactions:
        assert record['elapsed_ms'] >= record['lock_acquire_ms'] >= 0
        assert 'event_id' not in record and 'asset_id' not in record
    assert all(r['elapsed_ms'] >= 0 for r in signals(caplog, 'telemetry_ingestion'))


def test_busy_signal_is_expected_and_correlated(tmp_path, caplog):
    application = create_app(Settings(database_url=f"sqlite:///{(tmp_path / 'busy.db').as_posix()}",
                                      demo_mode=True, sqlite_busy_timeout_ms=30))
    with TestClient(application) as client:
        caplog.clear()
        with application.state.engine.connect() as holder:
            holder.exec_driver_sql('BEGIN IMMEDIATE')
            response = client.post('/telemetry/events', json=event(), headers={'X-Request-ID': 'busy-proof'})
            holder.rollback()
        assert response.status_code == 503 and response.headers['retry-after'] == '1'
        record, = signals(caplog, 'write_transaction')
        assert record['outcome'] == 'busy' and record['phase'] == 'acquire'
        assert record['sqlite_error'] in ('SQLITE_BUSY', 'SQLITE_LOCKED')
        assert record['request_id'] == 'busy-proof' and record['lock_acquire_ms'] >= 0
        assert not any(r.exc_info for r in caplog.records)
        assert client.post('/telemetry/events', json=event()).status_code == 201
