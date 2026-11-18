"""Bounded open-loop HTTP load against an owned disposable SQLite/Uvicorn server.

From backend/: uv run --frozen python scripts/performance.py --help
No external URL or database argument is accepted. No existing app is contacted.
"""
import argparse
import asyncio
from collections import Counter
from contextlib import closing
from datetime import datetime, timedelta, timezone
import importlib.metadata
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import signal
import socket
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import time

import httpx

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.database import create_database
from app.migrations import run_migrations
from app.models import Asset, Telemetry
from app.schemas import TelemetryEventIn
from app.services.telemetry import payload_hash
from app.settings import Settings

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def workload_event(index, workload, assets):
    kind = (['unique'] * 6 + ['duplicate'] * 2 + ['conflict', 'late'])[index % 10] \
        if workload == 'mixed' else workload
    asset = index % assets
    payload = dict(event_id=f'load-{index}', asset_id=f'PERF{asset:04}',
                   timestamp=(BASE + timedelta(seconds=20 + index)).isoformat(),
                   engine_temp_c=115 if index % 5 == 0 else 85, seatbelt_on=index % 5 != 0)
    if kind in ('duplicate', 'conflict'):
        payload.update(event_id=f'seed-{asset}-19', timestamp=(BASE + timedelta(seconds=19)).isoformat(),
                       engine_temp_c=85 if kind == 'duplicate' else 86, seatbelt_on=True)
    elif kind == 'late':
        payload.update(timestamp=(BASE - timedelta(days=1, seconds=index)).isoformat(),
                       engine_temp_c=999, seatbelt_on=False)
    return kind, payload, {'duplicate': 200, 'conflict': 409}.get(kind, 201)


def percentile(values, percent):
    """Nearest rank; no invented latency for an empty population."""
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(len(ordered) * percent / 100) - 1)], 3) if ordered else None


def quantiles(values):
    return {f'p{p}': percentile(values, p) for p in (50, 95, 99)}


def summarize(samples, offered, offer_seconds, elapsed):
    http = [s for s in samples if s['status'] is not None]
    return dict(
        offered_requests=offered, admitted_requests=len(samples),
        dropped_at_concurrency_limit=offered-len(samples),
        offering_seconds=round(offer_seconds, 4), elapsed_with_drain_seconds=round(elapsed, 4),
        observed_offered_rps=round(offered / offer_seconds, 3),
        admitted_rps=round(len(samples) / offer_seconds, 3),
        completed_http_rps=round(len(http) / elapsed, 3),
        committed_new_events_rps=round(sum(s['status'] == 201 for s in http) / elapsed, 3),
        expected_outcome_rps=round(sum(s['status'] == s['expected'] and s['valid'] for s in samples) / elapsed, 3),
        http_status_counts=dict(sorted(Counter(str(s['status']) for s in http).items())),
        admitted_mix=dict(sorted(Counter(s['kind'] for s in samples).items())),
        transport_errors=len(samples)-len(http),
        unexpected_http_responses=sum(s['status'] not in (s['expected'], 503) or not s['valid'] for s in http),
        http_latency_ms=quantiles([s['http_ms'] for s in http]),
        scheduled_to_completion_ms=quantiles([s['scheduled_ms'] for s in http]),
        dispatch_lag_ms=quantiles([s['lag_ms'] for s in samples]),
    )


class DisposableServer:
    """Own the DB, port, process tree, and logs; never accept a caller's DB path."""
    def __init__(self, assets=1, workers=1, busy_timeout_ms=5000):
        self.temporary = TemporaryDirectory(prefix='fleetsignal-performance-')
        self.directory = Path(self.temporary.name)
        self.database = self.directory / 'disposable.db'
        self.log = self.directory / 'server.log'
        self.assets, self.workers = assets, workers
        self.settings = Settings(database_url=f'sqlite:///{self.database.as_posix()}',
                                 demo_mode=False, sqlite_busy_timeout_ms=busy_timeout_ms,
                                 allowed_origins=[])
        self.process = self.stream = None
        with socket.socket() as port:
            port.bind(('127.0.0.1', 0))
            self.port = port.getsockname()[1]
        self.url = f'http://127.0.0.1:{self.port}'

    def __enter__(self):
        try:
            engine, sessions = create_database(self.settings)
            try:
                run_migrations(engine)
                with sessions() as db:
                    for asset in range(self.assets):
                        db.add(Asset(id=f'PERF{asset:04}', equipment_type='Excavator', status='available',
                                     engine_hrs_per_day=8, idle_hrs_per_day=0, operating_days=1))
                    db.flush()
                    for asset in range(self.assets):
                        for n in range(20):
                            payload = TelemetryEventIn(event_id=f'seed-{asset}-{n}', asset_id=f'PERF{asset:04}',
                                                       timestamp=BASE + timedelta(seconds=n),
                                                       engine_temp_c=85, seatbelt_on=True)
                            db.add(Telemetry(**payload.model_dump(), payload_hash=payload_hash(payload),
                                             received_at=BASE))
                    db.commit()
                with engine.connect() as connection:
                    self.database_config = {name: connection.exec_driver_sql(f'PRAGMA {name}').scalar()
                                            for name in ('journal_mode', 'synchronous', 'foreign_keys', 'busy_timeout')}
                    self.query_plan = [row[3] for row in connection.exec_driver_sql(
                        "EXPLAIN QUERY PLAN SELECT * FROM telemetry WHERE asset_id='PERF0000' "
                        "ORDER BY timestamp DESC, id DESC LIMIT 20")]
                self.database_config.update(pool_class=type(engine.pool).__name__,
                                            pool_size=engine.pool.size(), max_overflow=engine.pool._max_overflow)
            finally:
                engine.dispose()
            self.start()
            return self
        except BaseException:
            self.__exit__(*sys.exc_info())
            raise

    def start(self):
        environment = {**os.environ, 'FLEETSIGNAL_DATABASE_URL': self.settings.database_url,
                       'FLEETSIGNAL_DEMO_MODE': 'false', 'FLEETSIGNAL_ALLOWED_ORIGINS': '[]',
                       'FLEETSIGNAL_DATA_DIR': str(BACKEND.parent / 'data'),
                       'FLEETSIGNAL_SQLITE_BUSY_TIMEOUT_MS': str(self.settings.sqlite_busy_timeout_ms)}
        self.stream = self.log.open('ab', buffering=0)
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
        self.process = subprocess.Popen(
            [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1',
             '--port', str(self.port), '--workers', str(self.workers), '--no-access-log'],
            cwd=BACKEND, env=environment, stdin=subprocess.DEVNULL,
            stdout=self.stream, stderr=subprocess.STDOUT, creationflags=flags, start_new_session=os.name != 'nt',
        )
        deadline = time.monotonic() + 30
        with httpx.Client(trust_env=False, timeout=1) as client:
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise RuntimeError(f'Disposable server exited: {self.log.read_text(errors="replace")[-3000:]}')
                try:
                    if client.get(self.url + '/ready').status_code == 200:
                        # Warm each path/connection without adding measured events.
                        client.get(self.url + '/health')
                        return
                except httpx.HTTPError:
                    pass
                time.sleep(0.05)
        raise RuntimeError('Disposable server readiness timed out')

    def stop(self, hard=False):
        if self.process and self.process.poll() is None:
            if os.name == 'nt':
                # Only the process tree created by this object, including Uvicorn workers.
                subprocess.run(['taskkill', '/PID', str(self.process.pid), '/T', '/F'],
                               capture_output=True, check=True)
            else:
                os.killpg(self.process.pid, signal.SIGKILL if hard else signal.SIGTERM)
            self.process.wait(timeout=15)
        if self.stream:
            self.stream.close()
            self.stream = None

    def __exit__(self, *_args):
        try:
            self.stop()
        finally:
            # Windows can acknowledge taskkill before worker stdio handles finish closing.
            # Retry only this object's generated directory; never delete a supplied path.
            deadline = time.monotonic() + 5
            while True:
                try:
                    self.temporary.cleanup()
                    break
                except PermissionError as error:
                    if os.name != 'nt' or error.winerror not in (5, 32) or time.monotonic() >= deadline:
                        raise
                    time.sleep(0.05)

    def read(self, sql, parameters=()):
        with closing(sqlite3.connect(self.database.as_uri() + '?mode=ro', uri=True)) as db:
            return db.execute(sql, parameters).fetchall()

    def snapshot(self):
        return tuple(self.read(f'SELECT * FROM {table} ORDER BY id') for table in ('telemetry', 'alerts'))

    def signals(self, offset):
        with self.log.open('rb') as stream:
            stream.seek(offset)
            lines = stream.read().decode('utf-8', errors='replace').splitlines()
        records, malformed = [], 0
        for line in lines:
            if line.startswith('{'):
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    malformed += 1
        transactions = [r for r in records if r.get('event') == 'write_transaction']
        return dict(
            transaction_outcomes=dict(Counter(r['outcome'] for r in transactions)),
            ingestion_outcomes=dict(Counter(r['outcome'] for r in records if r.get('event') == 'telemetry_ingestion')),
            acquisition_ms=quantiles([r['lock_acquire_ms'] for r in transactions]),
            transaction_ms=quantiles([r['elapsed_ms'] for r in transactions]),
            commit_ms=quantiles([r['commit_ms'] for r in transactions if r.get('commit_ms') is not None]),
            sqlite_busy=sum(r['outcome'] == 'busy' for r in transactions),
            malformed_json_lines=malformed,
        )


async def wait_until(deadline):
    # asyncio timers may fire early by their clock resolution, notably on Windows.
    while (remaining := deadline - time.perf_counter()) > 0:
        await asyncio.sleep(remaining)


async def drive(server, duration, rate, concurrency, workload):
    """Fixed-rate arrival slots; discard at capacity instead of hiding a queue."""
    samples, pending = [], set()
    total = int(duration * rate)
    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
    async with httpx.AsyncClient(base_url=server.url, limits=limits, trust_env=False, timeout=35) as client:
        started = time.perf_counter()

        async def send(index, scheduled):
            kind, payload, expected = workload_event(index, workload, server.assets)
            begin = time.perf_counter()
            status, valid, telemetry_id = None, True, None
            try:
                response = await client.post('/telemetry/events', json=payload,
                                             headers={'X-Request-ID': f'load-{index}'})
                status = response.status_code
                data = response.json()
                valid = response.headers.get('x-request-id') == f'load-{index}'
                if status in (200, 201):
                    telemetry_id = data.get('telemetry_id')
                    valid &= (data.get('event_id') == payload['event_id']
                              and data.get('asset_id') == payload['asset_id']
                              and data.get('duplicate') is (status == 200)
                              and isinstance(telemetry_id, int))
                elif status == 503:
                    valid &= response.headers.get('retry-after') == '1'
            except httpx.HTTPError:
                pass
            except (ValueError, TypeError):
                valid = False
            finished = time.perf_counter()
            samples.append(dict(kind=kind, status=status, expected=expected, valid=valid,
                                event_id=payload['event_id'], telemetry_id=telemetry_id,
                                http_ms=(finished-begin)*1000, scheduled_ms=(finished-scheduled)*1000,
                                lag_ms=(begin-scheduled)*1000))

        for index in range(total):
            scheduled = started + index / rate
            await wait_until(scheduled)
            await asyncio.sleep(0)  # Let completed sends release admission slots even when catching up.
            done = {task for task in pending if task.done()}
            for task in done:
                task.result()  # A client programming error must not disappear as a dropped arrival.
            pending -= done
            if len(pending) < concurrency:
                task = asyncio.create_task(send(index, scheduled))
                pending.add(task)
        await wait_until(started + duration)
        offered_elapsed = time.perf_counter()-started
        if pending:
            await asyncio.gather(*pending)
        return samples, offered_elapsed, time.perf_counter()-started


def audit(server, samples):
    """Independently inspect durable identity, FK integrity, and the latest-20 rules."""
    stored = dict(server.read("SELECT event_id,id FROM telemetry WHERE event_id LIKE 'load-%'"))
    confirmed = {r['event_id']: r['telemetry_id'] for r in samples if r['status'] == 201}
    assert all(stored.get(key) == value for key, value in confirmed.items())
    if not any(s['status'] is None for s in samples):
        assert stored == confirmed, (len(stored), len(confirmed))
    for sample in samples:
        if sample['status'] == 200:
            assert server.read('SELECT id FROM telemetry WHERE event_id=?', (sample['event_id'],)) \
                == [(sample['telemetry_id'],)]
    assert not server.read('PRAGMA foreign_key_check')
    assert server.read('PRAGMA integrity_check') == [('ok',)]
    for asset in range(server.assets):
        asset_id = f'PERF{asset:04}'
        recent = server.read('SELECT engine_temp_c,seatbelt_on FROM telemetry WHERE asset_id=? '
                             'ORDER BY timestamp DESC,id DESC LIMIT 20', (asset_id,))
        expected = set()
        if any(temp is not None and temp >= 110 for temp, _ in recent):
            expected.add('engine_overheat')
        if any(belt == 0 for _, belt in recent):
            expected.add('seatbelt_violation')
        active = [row[0] for row in server.read('SELECT alert_type FROM alerts WHERE asset_id=? AND resolved=0',
                                               (asset_id,))]
        assert len(active) == len(set(active)) and set(active) == expected
    return dict(passed=True, committed_new_rows=len(stored), confirmed_201=len(confirmed),
                foreign_keys='ok', integrity='ok', latest_20_alerts='ok')


def run_case(duration=10, rate=200, concurrency=16, assets=32, workers=1,
             busy_timeout_ms=5000, workload='mixed'):
    with DisposableServer(assets, workers, busy_timeout_ms) as server:
        offset = server.log.stat().st_size
        samples, offer_seconds, elapsed = asyncio.run(drive(server, duration, rate, concurrency, workload))
        result = summarize(samples, int(duration*rate), offer_seconds, elapsed)
        result.update(config=dict(duration_seconds=duration, target_rps=rate, concurrency=concurrency,
                                  assets=assets, workers=workers, busy_timeout_ms=busy_timeout_ms,
                                  workload=workload, initial_rows_per_asset=20),
                      database=server.database_config, recent_query_plan=server.query_plan,
                      audit=audit(server, samples), signals=server.signals(offset))
        return result


def hardware():
    cpu, memory = platform.processor(), None
    if os.name == 'nt':
        import ctypes
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'HARDWARE\DESCRIPTION\System\CentralProcessor\0') as key:
            cpu = winreg.QueryValueEx(key, 'ProcessorNameString')[0].strip()
        kilobytes = ctypes.c_ulonglong()
        if ctypes.windll.kernel32.GetPhysicallyInstalledSystemMemory(ctypes.byref(kilobytes)):
            memory = kilobytes.value * 1024
    return dict(os=platform.platform(), cpu=cpu, logical_cpus=os.cpu_count(), installed_ram_bytes=memory,
                python=platform.python_version(), sqlite=sqlite3.sqlite_version,
                versions={name: importlib.metadata.version(name) for name in ('fastapi', 'sqlalchemy', 'uvicorn', 'httpx')})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--duration', type=float, default=10)
    parser.add_argument('--rate', type=float, default=200)
    parser.add_argument('--concurrency', type=int, default=16)
    parser.add_argument('--assets', type=int, default=32)
    parser.add_argument('--workers', type=int, choices=(1, 2), default=1)
    parser.add_argument('--busy-timeout-ms', type=int, default=5000)
    parser.add_argument('--workload', choices=('unique', 'duplicate', 'conflict', 'late', 'mixed'), default='mixed')
    parser.add_argument('--matrix', action='store_true')
    parser.add_argument('--repeats', type=int, default=1)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if (not math.isfinite(args.duration) or not math.isfinite(args.rate)
            or not 0 < args.duration <= 120 or not 1 <= args.duration*args.rate <= 100000
            or not 1 <= args.concurrency <= 128 or not 1 <= args.assets <= 128
            or not 1 <= args.busy_timeout_ms <= 60000 or not 1 <= args.repeats <= 10):
        parser.error('Use bounded positive settings: duration<=120, 1..100000 arrivals, concurrency/assets<=128, repeats<=10.')
    configs = [dict(rate=args.rate, concurrency=args.concurrency, assets=args.assets, workers=args.workers,
                    busy_timeout_ms=args.busy_timeout_ms, workload=args.workload)]
    if args.matrix:
        if args.duration * 1000 > 100000:
            parser.error('Matrix duration must be <=100 seconds (at most 100000 arrival slots per case).')
        configs = [
            dict(workload='unique', concurrency=c, assets=1, rate=200, workers=1, busy_timeout_ms=5000)
            for c in (1, 8, 32)
        ] + [
            dict(workload=w, concurrency=16, assets=a, rate=200, workers=n, busy_timeout_ms=5000)
            for w, a, n in [('mixed', 1, 1), ('mixed', 32, 1), ('duplicate', 32, 1),
                            ('conflict', 32, 1), ('late', 32, 1), ('mixed', 32, 2)]
        ] + [dict(workload='mixed', concurrency=32, assets=32, rate=1000, workers=1, busy_timeout_ms=t)
             for t in (5000, 50)]
    report = dict(schema_version=1, generated_at=datetime.now(timezone.utc).isoformat(),
                  hardware=hardware(), isolation='fresh TemporaryDirectory DB and owned loopback subprocess per run',
                  sampling='nearest-rank completed-HTTP percentiles; open-loop slots drop at concurrency cap',
                  source=dict(base_commit=subprocess.check_output(
                      ['git', 'rev-parse', 'HEAD'], cwd=BACKEND, text=True).strip(),
                      measured_files_sha256={name: hashlib.sha256((BACKEND / name).read_bytes()).hexdigest()
                          for name in ('app/database.py', 'app/routers/telemetry.py', 'app/services/transactions.py',
                                       'scripts/performance.py')}),
                  runs=[])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Refuse to overwrite saved evidence, including any accidentally selected existing file.
    if args.output.exists():
        parser.error('Output already exists; choose a new evidence filename.')
    for repeat in range(args.repeats):
        for config in configs:
            result = run_case(duration=args.duration, **config)
            result['repeat'] = repeat + 1
            report['runs'].append(result)
            args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
            print(json.dumps(dict(repeat=repeat+1, config=result['config'], rps=result['completed_http_rps'],
                                  p95_ms=result['http_latency_ms']['p95'], statuses=result['http_status_counts'],
                                  dropped=result['dropped_at_concurrency_limit'])), flush=True)
    if any(r['unexpected_http_responses'] or r['transport_errors'] or r['signals']['malformed_json_lines']
           for r in report['runs']):
        raise SystemExit('Unexpected HTTP/transport/log errors; inspect the saved report.')


if __name__ == '__main__':
    main()
