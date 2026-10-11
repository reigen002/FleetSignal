"""Live demo proof through the HTTP API. Record once; check after each restart.

Uses only Python's standard library. Creates one telemetry event on EQX1001;
never resets data. Keep the state file on your laptop, outside the EC2 instance.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from urllib.error import URLError
from urllib.request import Request, urlopen
from uuid import uuid4


def request(base, path, payload=None):
    call = Request(base.rstrip('/') + path,
                   data=json.dumps(payload).encode() if payload is not None else None,
                   headers={'Content-Type': 'application/json'})
    with urlopen(call, timeout=15) as response:
        return response.status, json.load(response)


def ready(base):
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            if request(base, '/ready') == (200, {'status': 'ready'}):
                assert request(base, '/health')[1]['status'] == 'ok'
                return
        except (URLError, TimeoutError, ConnectionError):
            pass
        time.sleep(1)
    raise RuntimeError('API did not become healthy and ready within 90 seconds')


def check(base, state):
    payload = state['payload']
    # Read before retrying: a lost database must fail without re-inserting proof data.
    rows = request(base, '/assets/EQX1001/telemetry?limit=500')[1]
    matching = [row for row in rows if row['event_id'] == payload['event_id']]
    assert len(matching) == 1 and matching[0]['id'] == state['telemetry_id'], matching
    assert request(base, '/alerts?asset_id=EQX1001')[1] == state['alerts']
    status, replay = request(base, '/telemetry/events', payload)
    assert status == 200 and replay['duplicate'] is True, (status, replay)
    assert replay['telemetry_id'] == state['telemetry_id'], replay
    assert request(base, '/alerts?asset_id=EQX1001')[1] == state['alerts']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['record', 'check'])
    parser.add_argument('--base-url', default='http://localhost:8080/api')
    parser.add_argument('--state', required=True, type=Path)
    args = parser.parse_args()
    if args.mode == 'record' and args.state.exists():
        parser.error('State already exists; use check or choose a new filename.')
    ready(args.base_url)
    if args.mode == 'record':
        payload = dict(event_id=f'aws-proof-{uuid4().hex}', asset_id='EQX1001',
                       timestamp=datetime.now(timezone.utc).isoformat(),
                       engine_temp_c=115, seatbelt_on=False)
        status, result = request(args.base_url, '/telemetry/events', payload)
        assert status == 201 and result['duplicate'] is False, (status, result)
        alerts = request(args.base_url, '/alerts?asset_id=EQX1001')[1]
        assert {'engine_overheat', 'seatbelt_violation'} <= {a['alert_type'] for a in alerts}
        state = dict(payload=payload, telemetry_id=result['telemetry_id'], alerts=alerts)
        check(args.base_url, state)
        args.state.parent.mkdir(parents=True, exist_ok=True)
        args.state.write_text(json.dumps(state, indent=2) + '\n', encoding='utf-8')
        print('PASS: health, readiness, event 201, duplicate 200, one row, alerts unchanged on replay')
    else:
        check(args.base_url, json.loads(args.state.read_text(encoding='utf-8')))
        print('PASS: saved telemetry ID, single row and alert identity survived; replay returned duplicate 200')


if __name__ == '__main__':
    main()
