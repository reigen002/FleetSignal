"""Verify a local Compose demo, lock recovery, and persistence after recreation.

Start Compose first. This script recreates its backend container and keeps its
named volume. It does not reset/delete records, remove volumes, or add a crash API.
Run: uv run --frozen python scripts/verify_docker.py --project fleetsignal-verification
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4


def request(base_url, path, payload=None, method=None, extra_headers=None):
    headers = {"X-Request-ID": f"docker-demo-{uuid4().hex}", "Content-Type": "application/json",
               **(extra_headers or {})}
    call = Request(base_url.rstrip("/") + path, data=json.dumps(payload).encode() if payload is not None else None,
                   headers=headers, method=method or ("POST" if payload is not None else "GET"))
    try:
        response = urlopen(call, timeout=15)
    except HTTPError as error:
        response = error
    with response:
        body = (json.load(response) if response.headers.get("Content-Type", "").startswith("application/json")
                else response.read().decode("utf-8"))
        return response.status, body, response.headers


def ready(base_url):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            if request(base_url, "/ready")[0] == 200:
                return
        except (URLError, TimeoutError, ConnectionError):
            pass
        time.sleep(0.5)
    raise RuntimeError("Backend did not become ready within 60 seconds")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="fleetsignal-verification")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", args.project):
        parser.error("Compose project must contain only lowercase letters, digits, _ and -")
    compose = ["docker", "compose", "-f", str(Path(__file__).resolve().parents[2] / "docker-compose.yml"), "-p", args.project]
    ready(args.base_url)
    assert len(request(args.base_url, "/assets")[1]) == 7
    payload = dict(event_id=f"docker-{uuid4().hex}", asset_id="EQX1001",
                   timestamp=datetime.now(timezone.utc).isoformat(), engine_temp_c=115, seatbelt_on=False)
    # Python's JSON encoder emits the raw Infinity token here; the API must
    # reject it with a serializable validation response rather than a 500.
    status, _body, headers = request(args.base_url, "/telemetry/events", {**payload, "engine_temp_c": float("inf")})
    assert status == 422 and headers["X-Request-ID"]
    for origin, expected in (("http://localhost:5173", 200), ("https://untrusted.example", 400)):
        status, _body, headers = request(args.base_url, "/telemetry/events", method="OPTIONS", extra_headers={
            "Origin": origin, "Access-Control-Request-Method": "POST", "X-Request-ID": "docker-preflight-42",
        })
        assert status == expected and headers["X-Request-ID"] == "docker-preflight-42"
    print("PASS: raw non-finite input returned422; allowed/denied preflights retained request IDs", flush=True)
    status, result, headers = request(args.base_url, "/telemetry/events", payload)
    assert status == 201 and result["duplicate"] is False and headers["X-Request-ID"]
    telemetry_id = result["telemetry_id"]
    before = request(args.base_url, "/alerts?asset_id=EQX1001")[1]
    assert {"engine_overheat", "seatbelt_violation"} <= {a["alert_type"] for a in before}
    status, duplicate, _ = request(args.base_url, "/telemetry/events", payload)
    assert status == 200 and duplicate["telemetry_id"] == telemetry_id
    assert request(args.base_url, "/alerts?asset_id=EQX1001")[1] == before
    assert request(args.base_url, "/telemetry/events", {**payload, "engine_temp_c": 116})[0] == 409
    print("PASS: ready, seven demo assets, external ingestion, duplicate, conflict and stable alerts", flush=True)

    # A real separate SQLite connection holds the write lock past the busy timeout.
    lock_code = ("import sqlite3,sys,select; c=sqlite3.connect('/var/lib/fleetsignal/fleetsignal.db'); "
                 "c.execute('BEGIN IMMEDIATE'); print('LOCKED',flush=True); "
                 "select.select([sys.stdin],[],[],45); c.rollback(); c.close()")
    holder = subprocess.Popen(compose + ["exec", "-T", "backend", "python", "-c", lock_code],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "LOCKED"
        blocked_payload = {**payload, "event_id": f"locked-{uuid4().hex}"}
        status, _body, headers = request(args.base_url, "/telemetry/events", blocked_payload)
        assert status == 503 and headers["Retry-After"] and headers["X-Request-ID"], (status, _body)
        assert request(args.base_url, "/health")[0] == 200
    finally:
        # Release only after the blocked request completes, avoiding timing races
        # between host networking/HTTP setup and a fixed-duration lock holder.
        _stdout, stderr = holder.communicate(input="release\n", timeout=20)
    assert holder.returncode == 0, stderr
    rows = request(args.base_url, "/assets/EQX1001/telemetry?limit=500")[1]
    assert not any(r["event_id"] == blocked_payload["event_id"] for r in rows)
    assert request(args.base_url, "/telemetry/events", blocked_payload)[0] == 201
    committed_alerts = request(args.base_url, "/alerts?asset_id=EQX1001")[1]
    print("PASS: held SQLite write lock returned retryable 503 with no partial row; retry succeeded after release", flush=True)

    subprocess.run(compose + ["up", "-d", "--force-recreate", "backend"], check=True, timeout=60)
    ready(args.base_url)
    status, replay, _ = request(args.base_url, "/telemetry/events", payload)
    assert status == 200 and replay["telemetry_id"] == telemetry_id and replay["duplicate"] is True
    rows = request(args.base_url, "/assets/EQX1001/telemetry?limit=500")[1]
    assert sum(r["event_id"] == payload["event_id"] for r in rows) == 1
    assert request(args.base_url, "/alerts?asset_id=EQX1001")[1] == committed_alerts
    print(f"PASS: container recreation retained telemetry_id={telemetry_id} and active alert identity", flush=True)
    print(f"Volume retained for Compose project {args.project}; no reset or volume deletion performed.", flush=True)


if __name__ == "__main__":
    main()
