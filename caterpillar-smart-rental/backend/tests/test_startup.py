"""Startup contracts: explicit demo mode, isolated storage and lazy input data."""
import csv
import importlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from pydantic import ValidationError

from app.models import Asset


PROJECT_DATA = Path(__file__).resolve().parents[2] / "data"


def make_app(tmp_path, *, demo_mode=False, data_dir=PROJECT_DATA, name="test"):
    main = importlib.import_module("app.main")
    assert callable(getattr(main, "create_app", None)), "App factory is required"
    from app.settings import Settings

    return main.create_app(Settings(
        database_url=f"sqlite:///{(tmp_path / (name + '.db')).as_posix()}",
        data_dir=data_dir,
        demo_mode=demo_mode,
    ))


def copy_data(tmp_path, name):
    target = tmp_path / name
    shutil.copytree(PROJECT_DATA, target)
    return target


def test_normal_startup_is_empty_and_demo_controls_are_absent(tmp_path):
    application = make_app(tmp_path, data_dir=tmp_path / "absent")
    with TestClient(application) as client:
        assert client.get("/assets").json() == []
        paths = client.get("/openapi.json").json()["paths"]
        for path in ("/admin/seed", "/admin/reset", "/assets/{asset_id}/simulate"):
            assert path not in paths
        for path in ("/admin/seed", "/admin/reset", "/assets/EQX1001/simulate"):
            assert client.post(path, json={"scenario": "normal", "readings": 1}).status_code == 404
        assert "/assets/{asset_id}/checkout" in paths
        assert "/assets/{asset_id}/checkin" in paths


def test_demo_startup_seeds_and_preserves_live_demo_statuses(tmp_path):
    application = make_app(tmp_path, demo_mode=True)
    with TestClient(application) as client:
        rows = client.get("/assets").json()
        assert len(rows) == 7
        statuses = {row["id"]: row["status"] for row in rows}
        assert [statuses[key] for key in ("EQX1002", "EQX1004", "EQX1007")] == ["checked_out"] * 3
        assert client.post("/assets/EQX1001/simulate", json={"scenario": "normal", "readings": 1}).status_code == 200
        assert client.post("/admin/reset").status_code == 200
        assert len(client.get("/assets").json()) == 7


def test_test_client_and_service_session_share_database(db_session, client):
    assert client.post("/assets/EQX1002/checkin", json={"performed_by": "Test Desk"}).status_code == 200
    db_session.expire_all()
    assert db_session.get(Asset, "EQX1002").status == "available"


def test_explicit_database_does_not_write_to_configured_normal_database(tmp_path, monkeypatch):
    sentinel = tmp_path / "production.db"
    with sqlite3.connect(sentinel) as connection:
        connection.execute("CREATE TABLE sentinel (value TEXT)")
        connection.execute("INSERT INTO sentinel VALUES ('preserve me')")
    original = sentinel.read_bytes()
    monkeypatch.setenv("FLEETSIGNAL_DATABASE_URL", f"sqlite:///{sentinel.as_posix()}")
    application = make_app(tmp_path, demo_mode=True)
    with TestClient(application) as client:
        assert client.post("/admin/reset").status_code == 200
    assert sentinel.read_bytes() == original


@pytest.mark.parametrize("demo_mode", ["true", "false"])
def test_import_and_factory_do_not_create_database(tmp_path, demo_mode):
    database = tmp_path / "untouched" / "normal.db"
    environment = os.environ.copy()
    environment.update(
        FLEETSIGNAL_DATABASE_URL=f"sqlite:///{database.as_posix()}",
        FLEETSIGNAL_DATA_DIR=str(tmp_path / "missing-data"),
        FLEETSIGNAL_DEMO_MODE=demo_mode,
    )
    result = subprocess.run(
        [sys.executable, "-c", "from app.main import app"],
        cwd=Path(__file__).resolve().parents[1], env=environment,
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert not database.exists()


def test_forecasts_use_each_apps_data_and_database(tmp_path):
    directories = [copy_data(tmp_path, name) for name in ("one", "two")]
    for directory, count in zip(directories, (3, 9)):
        supplement = {"demand_history": [{
            "site_id": "S003", "equipment_type": "Excavator",
            "periods": [{"period": "2025-04", "count": count}],
        }]}
        (directory / "scenarios" / "demand_history_supplement.json").write_text(json.dumps(supplement), encoding="utf-8")
    applications = [make_app(tmp_path, demo_mode=True, data_dir=directory, name=name)
                    for directory, name in zip(directories, ("one", "two"))]
    with TestClient(applications[0]) as first, TestClient(applications[1]) as second:
        assert first.post("/assets/EQX1002/checkin", json={}).status_code == 200
        assert second.get("/assets/EQX1002").json()["status"] == "checked_out"
        for client, expected in ((first, 3), (second, 9), (first, 3)):
            rows = client.get("/forecasts?site_id=S003&equipment_type=Excavator").json()
            site_row = next(row for row in rows if row["peak_forecast_demand"] is not None)
            assert site_row["peak_forecast_demand"] == expected
        assert any("9 unit(s)/month" in row["evidence"] for row in second.get("/recommendations").json())


@pytest.mark.parametrize("relative_path", [
    "seed/official_assets.csv", "scenarios/demand_history_supplement.json",
    "scenarios/telemetry_scenarios.json", "scenarios/forecasts.json",
    "scenarios/anomalies.json", "scenarios/golden_insights.json",
])
def test_demo_startup_reports_missing_input_file(tmp_path, relative_path):
    directory = copy_data(tmp_path, "missing")
    (directory / relative_path).unlink()
    application = make_app(tmp_path, demo_mode=True, data_dir=directory)
    with pytest.raises(ValueError, match=Path(relative_path).name):
        with TestClient(application):
            pass


def test_demo_startup_reports_invalid_scenario_json(tmp_path):
    directory = copy_data(tmp_path, "invalid")
    (directory / "scenarios" / "telemetry_scenarios.json").write_text("{bad json", encoding="utf-8")
    application = make_app(tmp_path, demo_mode=True, data_dir=directory)
    with pytest.raises(ValueError, match="telemetry_scenarios.json"):
        with TestClient(application):
            pass


def test_loader_reports_empty_asset_csv(tmp_path):
    seed = importlib.import_module("app.seed")
    assert callable(getattr(seed, "load_assets", None)), "Lazy CSV loader is required"
    directory = copy_data(tmp_path, "empty")
    csv_path = directory / "seed" / "official_assets.csv"
    csv_path.write_text(csv_path.read_text(encoding="utf-8").splitlines()[0] + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="empty.*official_assets.csv|official_assets.csv.*empty"):
        seed.load_assets(directory)


def test_asset_loader_uses_supplied_csv_and_preserves_null_values(tmp_path):
    seed = importlib.import_module("app.seed")
    assert callable(getattr(seed, "load_assets", None)), "Lazy CSV loader is required"
    directory = copy_data(tmp_path, "custom")
    csv_path = directory / "seed" / "official_assets.csv"
    with csv_path.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        fieldnames = reader.fieldnames
        rows = list(reader)
    rows[0]["customer_name"] = "Configured fixture customer"
    rows[1]["status"] = "available"
    with csv_path.open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    assets = seed.load_assets(directory)
    assert assets[0]["customer_name"] == "Configured fixture customer"
    assert assets[1]["site_id"] is None
    assert assets[1]["operator_id"] is None
    assert assets[1]["status"] == "available"


def test_sqlite_foreign_keys_enforced_on_every_connection(tmp_path):
    application = make_app(tmp_path)
    with TestClient(application):
        # Hold both connections open to require separate underlying connections.
        with application.state.engine.connect() as first, application.state.engine.connect() as second:
            for connection in (first, second):
                assert connection.execute(text("PRAGMA foreign_keys")).scalar() == 1
                assert 0 < connection.execute(text("PRAGMA busy_timeout")).scalar() <= 30000
                with pytest.raises(IntegrityError):
                    connection.execute(text("INSERT INTO assets (id,equipment_type,status,site_id) VALUES ('bad','Excavator','available','missing')"))
                connection.rollback()


def test_settings_paths_are_absolute_and_independent_of_working_directory(tmp_path, monkeypatch):
    from app.settings import Settings

    first = Settings(_env_file=None)
    monkeypatch.chdir(tmp_path)
    second = Settings(_env_file=None)
    assert first.database_url == second.database_url
    assert first.data_dir == second.data_dir == PROJECT_DATA
    assert first.demo_mode is False


def test_cors_accepts_configured_local_origin_without_credentials(tmp_path):
    application = make_app(tmp_path)
    with TestClient(application) as client:
        allowed = client.get("/health", headers={"Origin": "http://localhost:5173"})
        assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
        assert "access-control-allow-credentials" not in allowed.headers
        rejected = client.get("/health", headers={"Origin": "https://untrusted.example"})
        assert "access-control-allow-origin" not in rejected.headers


@pytest.mark.parametrize("values", [
    {"database_url": "sqlite:///relative.db"},
    {"data_dir": "relative-data"},
    {"allowed_origins": ["*"]},
    {"allowed_origins": ["http://localhost:5173/path"]},
    {"allowed_origins": ["not-a-url"]},
    {"allowed_origins": ["http://name:bad-port"]},
    {"allowed_origins": ["http://user:password@localhost:5173"]},
    {"sqlite_busy_timeout_ms": 0},
    {"sqlite_busy_timeout_ms": -1},
])
def test_settings_reject_ambiguous_paths_and_invalid_values(values):
    from app.settings import Settings

    with pytest.raises(ValidationError):
        Settings(**values)


@pytest.mark.parametrize("database_url", [
    "sqlite://", "sqlite:///:memory:",
    "postgresql://localhost/fleetsignal", "mysql://localhost/fleetsignal",
])
def test_settings_reject_memory_and_non_sqlite_database_urls(database_url):
    from app.settings import Settings

    with pytest.raises(ValidationError, match="file-backed SQLite"):
        Settings(database_url=database_url)


def test_environment_settings_are_used_by_app(tmp_path, monkeypatch):
    from app.main import create_app

    monkeypatch.setenv("FLEETSIGNAL_DATABASE_URL", f"sqlite:///{(tmp_path / 'environment.db').as_posix()}")
    monkeypatch.setenv("FLEETSIGNAL_DATA_DIR", str(tmp_path / "environment-data"))
    monkeypatch.setenv("FLEETSIGNAL_DEMO_MODE", "false")
    monkeypatch.setenv("FLEETSIGNAL_ALLOWED_ORIGINS", '["https://fleet.example"]')
    monkeypatch.setenv("FLEETSIGNAL_SQLITE_BUSY_TIMEOUT_MS", "120")
    application = create_app()
    with TestClient(application) as client:
        assert client.get("/assets").json() == []
        response = client.get("/health", headers={"Origin": "https://fleet.example"})
        assert response.headers["access-control-allow-origin"] == "https://fleet.example"
        with application.state.engine.connect() as connection:
            assert connection.execute(text("PRAGMA busy_timeout")).scalar() == 120
    assert (tmp_path / "environment.db").is_file()
