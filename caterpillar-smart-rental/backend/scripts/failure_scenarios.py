"""Six isolated failure contracts, including real socket loss and hard process restart.

From backend/: uv run --frozen python scripts/failure_scenarios.py --output FILE.json
All storage and servers are owned by this invocation, never the user's app.
"""
import argparse
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import socket
import sqlite3
import sys
import time
from unittest.mock import patch

from fastapi.testclient import TestClient
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import create_app
from app.services import alerts
from scripts.performance import BASE, DisposableServer, hardware


def run_failures():
    cases = []
    with DisposableServer(busy_timeout_ms=50) as server:
        payload = dict(event_id='fault-after-insert', asset_id='PERF0000',
                       timestamp=(BASE + timedelta(days=1)).isoformat(),
                       engine_temp_c=115, seatbelt_on=False)
        with TestClient(create_app(server.settings), raise_server_exceptions=False) as client:
            original = alerts.reconcile_asset
            for name, after_reconciliation in [('after_telemetry_insert', False),
                                               ('interrupted_alert_reconciliation', True)]:
                payload['event_id'] = name
                before = server.snapshot()

                def fail(db, asset):
                    if after_reconciliation:
                        original(db, asset)
                        db.flush()
                    raise RuntimeError('Injected isolated processing failure')

                with patch.object(alerts, 'reconcile_asset', fail):
                    response = client.post('/telemetry/events', json=payload,
                                           headers={'X-Request-ID': name})
                assert response.status_code == 500 and response.headers['x-request-id'] == name
                assert response.json() == {'detail': 'Internal server error', 'request_id': name}
                assert server.snapshot() == before
                accepted = client.post('/telemetry/events', json=payload)
                assert accepted.status_code == 201
                after = server.snapshot()
                replay = client.post('/telemetry/events', json=payload)
                assert replay.status_code == 200 and replay.json()['duplicate'] is True
                assert replay.json()['telemetry_id'] == accepted.json()['telemetry_id']
                assert server.snapshot() == after
                cases.append(dict(name=name, passed=True, rollback='full telemetry and alert snapshot unchanged'))

        with httpx.Client(base_url=server.url, trust_env=False, timeout=5) as client:
            payload['event_id'] = 'lock-timeout'
            before = server.snapshot()
            with closing(sqlite3.connect(server.database)) as holder:
                holder.execute('BEGIN IMMEDIATE')
                response = client.post('/telemetry/events', json=payload)
                assert response.status_code == 503 and response.headers['retry-after'] == '1'
                assert response.headers['x-request-id']
                assert client.get('/health').status_code == 200
                assert server.snapshot() == before
                holder.rollback()
            assert client.post('/telemetry/events', json=payload).status_code == 201
            cases.append(dict(name='database_lock_timeout', passed=True, busy_timeout_ms=50, status=503))

            # Send a real request, observe commit independently, and discard all response bytes.
            # This is client acknowledgement loss, not a power/network-partition simulation.
            payload['event_id'] = 'lost-response'
            body = json.dumps(payload).encode()
            with socket.create_connection(('127.0.0.1', server.port), timeout=5) as connection:
                connection.sendall(
                    (f'POST /telemetry/events HTTP/1.1\r\nHost: 127.0.0.1\r\n'
                     f'Content-Type: application/json\r\nContent-Length: {len(body)}\r\n'
                     'Connection: close\r\n\r\n').encode() + body)
                deadline = time.monotonic() + 5
                while not server.read('SELECT id FROM telemetry WHERE event_id=?', (payload['event_id'],)):
                    if time.monotonic() >= deadline:
                        raise AssertionError('Lost-response request did not commit')
                    time.sleep(0.01)
                # No recv() call: the caller never receives the application response.
            before = server.snapshot()
            response = client.post('/telemetry/events', json=payload)
            assert response.status_code == 200 and response.json()['duplicate'] is True
            assert server.snapshot() == before
            cases.append(dict(name='retry_after_lost_response', passed=True, status=200))

            payload['event_id'] = 'survives-process-kill'
            accepted = client.post('/telemetry/events', json=payload)
            assert accepted.status_code == 201
            before = server.snapshot()
        server.stop(hard=True)  # Bypass graceful app shutdown, then reuse the same owned DB.
        # A restart always uses the same owned DB, not a fresh fixture.
        server.start()
        assert server.snapshot() == before
        with httpx.Client(base_url=server.url, trust_env=False, timeout=5) as client:
            replay = client.post('/telemetry/events', json=payload)
            assert replay.status_code == 200 and replay.json()['telemetry_id'] == accepted.json()['telemetry_id']
            assert replay.json()['duplicate'] is True and server.snapshot() == before
            cases.append(dict(name='process_restart_persisted_storage', passed=True, status=200))

            # Deliberately reverse arrival order. Ordering must remain occurrence time then ID.
            for n in reversed(range(100, 120)):
                normal = dict(event_id=f'normal-{n}', asset_id='PERF0000',
                              timestamp=(BASE + timedelta(days=2, seconds=n)).isoformat(),
                              engine_temp_c=85, seatbelt_on=True)
                assert client.post('/telemetry/events', json=normal).status_code == 201
            assert client.get('/alerts?asset_id=PERF0000').json() == []
            alert_before = server.snapshot()[1]
            late = dict(payload, event_id='late-outside', timestamp=(BASE-timedelta(days=10)).isoformat(),
                        engine_temp_c=999)
            assert client.post('/telemetry/events', json=late).status_code == 201
            assert server.read('SELECT count(*) FROM telemetry WHERE event_id=?', ('late-outside',)) == [(1,)]
            assert server.snapshot()[1] == alert_before
            assert client.get('/alerts?asset_id=PERF0000').json() == []
            inside = dict(late, event_id='late-inside',
                          timestamp=(BASE+timedelta(days=2, seconds=110.5)).isoformat())
            assert client.post('/telemetry/events', json=inside).status_code == 201
            assert {'engine_overheat', 'seatbelt_violation'} == {
                a['alert_type'] for a in client.get('/alerts?asset_id=PERF0000').json()}
            cases.append(dict(name='out_of_order_arrival', passed=True,
                              outside_window='stored without replacing alert evidence', inside_window='hazards active'))
    return dict(cases=cases, isolation='owned temporary database and loopback process only')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output already exists; choose a new evidence filename.')
    result = run_failures()
    result['generated_at'] = datetime.now(timezone.utc).isoformat()
    result['failure_script_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    result['hardware'] = hardware()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    for case in result['cases']:
        print('PASS: ' + case['name'])


if __name__ == '__main__':
    main()
