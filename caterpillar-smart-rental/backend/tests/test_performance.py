"""Regression checks for workload semantics and honest load accounting."""
import pytest


def test_arrival_pacing_rechecks_deadline_after_early_timer_wakeup(monkeypatch):
    import asyncio
    from scripts import performance
    clock = iter([0, 0.5, 1])
    sleeps = []
    monkeypatch.setattr(performance.time, 'perf_counter', lambda: next(clock))

    async def early_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(performance.asyncio, 'sleep', early_sleep)
    asyncio.run(performance.wait_until(1))
    assert sleeps == [1, 0.5]


def test_nearest_rank_percentiles_and_empty_samples():
    from scripts.performance import percentile
    assert percentile([], 95) is None
    assert percentile([42], 99) == 42
    assert percentile(list(range(1, 101)), 50) == 50
    assert percentile(list(range(1, 101)), 95) == 95
    assert percentile(list(range(1, 101)), 99) == 99


def test_mixed_workload_is_deterministic_and_conflicts_share_identity():
    from scripts.performance import workload_event
    rows = [workload_event(i, 'mixed', 8) for i in range(10)]
    assert [kind for kind, _, _ in rows].count('unique') == 6
    assert [kind for kind, _, _ in rows].count('duplicate') == 2
    assert [kind for kind, _, _ in rows].count('conflict') == 1
    assert [kind for kind, _, _ in rows].count('late') == 1
    duplicate = workload_event(2, 'duplicate', 8)[1]
    conflict = workload_event(2, 'conflict', 8)[1]
    assert duplicate['event_id'] == conflict['event_id']
    assert duplicate != conflict
    assert rows == [workload_event(i, 'mixed', 8) for i in range(10)]


def test_accounting_separates_offered_completed_goodput_and_expected_conflicts():
    from scripts.performance import summarize
    samples = [dict(status=s, expected=e, http_ms=t, scheduled_ms=t+2, lag_ms=2,
                    kind='unique', valid=True) for s, e, t in
               [(201, 201, 10), (409, 409, 20), (503, 201, 30), (None, 201, 40)]]
    result = summarize(samples, offered=8, offer_seconds=1, elapsed=2)
    assert result['offered_requests'] == 8 and result['admitted_requests'] == 4
    assert result['dropped_at_concurrency_limit'] == 4
    assert result['completed_http_rps'] == 1.5
    assert result['expected_outcome_rps'] == 1
    assert result['http_status_counts'] == {'201': 1, '409': 1, '503': 1}
    assert result['transport_errors'] == 1
    assert result['http_latency_ms']['p50'] == 20


@pytest.mark.parametrize('workers', [1, 2])
def test_real_http_smoke_is_disposable_and_audited(workers, tmp_path, monkeypatch):
    from scripts.performance import run_case
    sentinel = tmp_path / 'user-database.db'
    sentinel.write_bytes(b'Never use this existing database')
    monkeypatch.setenv('FLEETSIGNAL_DATABASE_URL', f'sqlite:///{sentinel.as_posix()}')
    monkeypatch.setenv('FLEETSIGNAL_DEMO_MODE', 'true')
    result = run_case(duration=0.5, rate=20, concurrency=4, assets=4,
                      workers=workers, busy_timeout_ms=5000, workload='mixed')
    assert result['offered_requests'] == 10
    assert result['audit']['passed'] is True
    assert result['unexpected_http_responses'] == result['transport_errors'] == 0
    assert result['signals']['transaction_outcomes']
    assert sum(result['signals']['transaction_outcomes'].values()) == result['admitted_requests']
    assert sum(result['signals']['ingestion_outcomes'].values()) == result['admitted_requests']
    assert result['dispatch_lag_ms']['p50'] >= 0
    assert sentinel.read_bytes() == b'Never use this existing database'


def test_failure_suite_preserves_every_asserted_invariant():
    from scripts.failure_scenarios import run_failures
    result = run_failures()
    assert len(result['cases']) == 6
    assert all(case['passed'] for case in result['cases'])
