"""Schema upgrades exercise temporary file databases and persisted legacy rows."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.database import create_database
from app.settings import Settings


@pytest.fixture
def database(tmp_path):
    engine, sessions = create_database(Settings(
        database_url=f"sqlite:///{(tmp_path / 'nested' / 'migration.db').as_posix()}",
    ))
    yield engine, sessions
    engine.dispose()


def migrate(engine):
    from app.migrations import run_migrations
    run_migrations(engine)


def legacy(engine):
    from alembic import command
    from app.database import prepare_database_directory
    from app.migrations import migration_config
    prepare_database_directory(engine)
    with engine.begin() as connection:
        command.upgrade(migration_config(connection), "0001")
        connection.execute(text("DROP TABLE alembic_version"))
        connection.execute(text("INSERT INTO sites (id, name) VALUES ('S1', 'Yard')"))
        connection.execute(text("INSERT INTO operators (id, name) VALUES ('O1', 'Operator')"))
        connection.execute(text("""INSERT INTO assets
            (id,equipment_type,status,site_id,operator_id,engine_hrs_per_day,
             idle_hrs_per_day,operating_days,created_at,updated_at)
            VALUES ('A1','Excavator','available','S1','O1',8,1,2,
                    '2026-01-01 00:00:00','2026-01-01 00:00:00')"""))
        connection.execute(text("""INSERT INTO rental_events (id,asset_id,event_type,timestamp)
            VALUES (7,'A1','checkout','2026-01-01 00:00:00')"""))
        connection.execute(text("""INSERT INTO telemetry (id,asset_id,timestamp,engine_hours)
            VALUES (9,'A1','2026-01-01 01:00:00',16)"""))
        connection.execute(text("""INSERT INTO alerts
            (id,asset_id,alert_type,severity,message,resolved,created_at,resolved_at)
            VALUES (1,'A1','overdue','HIGH','later',0,'2026-01-02 00:00:00',NULL),
                   (2,'A1','overdue','HIGH','first',0,'2026-01-01 00:00:00',NULL),
                   (3,'A1','overdue','HIGH','tie',0,'2026-01-01 00:00:00',NULL),
                   (4,'A1','overdue','HIGH','history',1,'2025-01-01 00:00:00','2025-01-02 00:00:00')"""))


def test_fresh_migration_and_repeat_startup(database):
    engine, _ = database
    migrate(engine)
    migrate(engine)
    assert set(inspect(engine).get_table_names()) == {
        "assets", "sites", "operators", "rental_events", "telemetry", "alerts", "alembic_version",
    }
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0002"
    columns = {column["name"]: column for column in inspect(engine).get_columns("telemetry")}
    for name in ("event_id", "payload_hash", "received_at"):
        assert columns[name]["nullable"]
    indexes = {index["name"]: index for index in inspect(engine).get_indexes("telemetry")}
    assert indexes["ix_telemetry_asset_timestamp_id"]["column_names"] == ["asset_id", "timestamp", "id"]
    assert indexes["uq_telemetry_event_id"]["unique"]


def test_legacy_rows_survive_with_no_fabricated_identity(database):
    engine, _ = database
    legacy(engine)
    migrate(engine)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT site_id,operator_id FROM assets WHERE id='A1'")).one() == ("S1", "O1")
        assert connection.execute(text("SELECT id FROM rental_events")).scalar_one() == 7
        assert connection.execute(text("SELECT id,engine_hours,event_id,payload_hash,received_at FROM telemetry")).one() == (9, 16, None, None, None)
        assert connection.execute(text("SELECT id FROM alerts WHERE resolved=0")).scalars().all() == [2]
        assert connection.execute(text("SELECT count(*) FROM alerts")).scalar_one() == 4
        assert connection.execute(text("SELECT resolved_at FROM alerts WHERE id=4")).scalar_one() == "2025-01-02 00:00:00"
        assert all(row[0] for row in connection.execute(text("SELECT resolved_at FROM alerts WHERE id IN (1,3)")))
        assert connection.execute(text("SELECT count(*) FROM alerts WHERE last_seen_at IS NOT NULL")).scalar_one() == 0


def test_schema_enforces_event_identity_fk_and_one_active_episode(database):
    engine, _ = database
    legacy(engine)
    migrate(engine)
    with engine.begin() as connection:
        connection.execute(text("""INSERT INTO assets
            (id,equipment_type,status,engine_hrs_per_day,idle_hrs_per_day,operating_days,created_at,updated_at)
            VALUES ('A2','Excavator','available',0,0,0,'2026-01-02','2026-01-02')"""))
        connection.execute(text("INSERT INTO telemetry (asset_id,timestamp,event_id) VALUES ('A1','2026-01-02','event')"))
        connection.execute(text("INSERT INTO telemetry (asset_id,timestamp) VALUES ('A1','2026-01-02'),('A1','2026-01-02')"))
        connection.execute(text("INSERT INTO alerts (asset_id,alert_type,severity,message,resolved,created_at) VALUES ('A1','overdue','LOW','history',1,'2026-01-02')"))
    for statement in (
        "INSERT INTO telemetry (asset_id,timestamp,event_id) VALUES ('A1','2026-01-02','event')",
        "INSERT INTO telemetry (asset_id,timestamp,event_id) VALUES ('A2','2026-01-02','event')",
        "INSERT INTO telemetry (asset_id,timestamp) VALUES ('missing','2026-01-02')",
        "INSERT INTO alerts (asset_id,alert_type,severity,message,resolved,created_at) VALUES ('A1','overdue','LOW','duplicate',0,'2026-01-02')",
    ):
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(text(statement))


@pytest.mark.parametrize("alter", [
    "ALTER TABLE telemetry ADD COLUMN mystery TEXT",
    "DROP INDEX ix_telemetry_timestamp",
    "CREATE TABLE mystery (id INTEGER PRIMARY KEY)",
    "ALTER TABLE telemetry RENAME COLUMN timestamp TO occurrence",
    "CREATE TRIGGER mystery AFTER UPDATE ON alerts BEGIN UPDATE alerts SET message='changed'; END",
])
def test_unknown_legacy_schema_is_refused_without_row_changes(database, alter):
    engine, _ = database
    legacy(engine)
    with engine.begin() as connection:
        connection.execute(text(alter))
    with pytest.raises(RuntimeError, match="Unrecognized legacy database schema"):
        migrate(engine)
    assert "alembic_version" not in inspect(engine).get_table_names()
    with engine.connect() as connection:
        assert connection.execute(text("SELECT id,resolved,resolved_at FROM alerts ORDER BY id")).all() == [
            (1, 0, None), (2, 0, None), (3, 0, None), (4, 1, "2025-01-02 00:00:00"),
        ]


def test_telemetry_utc_and_deterministic_relationship(database):
    from app.models import Asset, Telemetry
    engine, sessions = database
    legacy(engine)
    migrate(engine)
    with sessions() as session:
        session.add_all([
            Telemetry(asset_id="A1", timestamp=datetime(2026, 1, 2, 5, 30, tzinfo=timezone(timedelta(hours=5, minutes=30)))),
            Telemetry(asset_id="A1", timestamp=datetime(2026, 1, 2), received_at=datetime(2026, 1, 2, tzinfo=timezone.utc)),
        ])
        session.commit()
        readings = session.get(Asset, "A1").telemetry
        assert [row.id for row in readings] == [11, 10, 9]
        assert readings[0].timestamp == readings[1].timestamp == datetime(2026, 1, 2, tzinfo=timezone.utc)
        assert readings[0].received_at.tzinfo == timezone.utc


@pytest.mark.parametrize("old,new", [
    ("timestamp DATETIME NOT NULL", "timestamp TEXT NOT NULL"),
    ("timestamp DATETIME NOT NULL", "timestamp DATETIME"),
    ("asset_id VARCHAR(20) NOT NULL", "asset_id VARCHAR(21) NOT NULL"),
    ("PRIMARY KEY (id)", "UNIQUE (id)"),
    ("FOREIGN KEY(asset_id) REFERENCES assets (id)", "CHECK (asset_id IS NOT NULL)"),
])
def test_legacy_type_nullable_primary_and_foreign_key_validation(database, old, new):
    engine, _ = database
    legacy(engine)
    with engine.begin() as connection:
        schema = connection.execute(text("SELECT sql FROM sqlite_master WHERE name='telemetry'")).scalar_one()
        assert old in schema
        connection.execute(text("DROP TABLE telemetry"))
        connection.exec_driver_sql(schema.replace(old, new))
        connection.execute(text("CREATE INDEX ix_telemetry_timestamp ON telemetry (timestamp)"))
        connection.execute(text("INSERT INTO telemetry (id,asset_id,timestamp,engine_hours) VALUES (9,'A1','2026-01-01 01:00:00',16)"))
    with pytest.raises(RuntimeError, match="Unrecognized legacy database schema"):
        migrate(engine)
    assert "alembic_version" not in inspect(engine).get_table_names()
    with engine.connect() as connection:
        assert connection.execute(text("SELECT id,engine_hours FROM telemetry")).one() == (9, 16)
        assert connection.execute(text("SELECT count(*) FROM alerts WHERE resolved=0")).scalar_one() == 3


def test_sqlite_migration_failure_rolls_back_ddl_and_version(database, monkeypatch):
    from alembic.script import ScriptDirectory
    from app.migrations import migration_config
    engine, _ = database
    legacy(engine)
    with engine.connect() as connection:
        # Patch the frozen revision in Alembic's cache to fail after its real DDL.
        script = ScriptDirectory.from_config(migration_config(connection))
        revision = script.get_revision("0002")
        real_upgrade = revision.module.upgrade

        def fail_after_upgrade():
            real_upgrade()
            raise RuntimeError("forced upgrade failure")

        monkeypatch.setattr(revision.module, "upgrade", fail_after_upgrade)
        monkeypatch.setattr(ScriptDirectory, "from_config", classmethod(lambda cls, config: script))
    with pytest.raises(RuntimeError, match="forced upgrade failure"):
        migrate(engine)
    assert "alembic_version" not in inspect(engine).get_table_names()
    assert "event_id" not in {column["name"] for column in inspect(engine).get_columns("telemetry")}
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM alerts WHERE resolved=0")).scalar_one() == 3


def test_concurrent_sqlite_startups_are_serialized(database):
    from concurrent.futures import ThreadPoolExecutor
    engine, _ = database
    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(migrate, [engine, engine]))
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0002"


def test_unknown_version_is_not_stamped_or_upgraded(database):
    from alembic.util import CommandError
    engine, _ = database
    migrate(engine)
    with engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num='unknown'"))
    with pytest.raises(CommandError, match="unknown"):
        migrate(engine)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "unknown"


def test_migration_cli_uses_environment_settings(tmp_path):
    import os
    from pathlib import Path
    import subprocess
    import sys
    from sqlalchemy import create_engine

    database_path = tmp_path / "cli" / "configured.db"
    environment = os.environ.copy()
    environment["FLEETSIGNAL_DATABASE_URL"] = f"sqlite:///{database_path.as_posix()}"
    result = subprocess.run(
        [sys.executable, "-m", "app.migrations"],
        cwd=Path(__file__).resolve().parents[1], env=environment,
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    engine = create_engine(environment["FLEETSIGNAL_DATABASE_URL"])
    try:
        with engine.connect() as connection:
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0002"
    finally:
        engine.dispose()


def test_empty_version_table_does_not_admit_unknown_database(database):
    from app.database import prepare_database_directory
    engine, _ = database
    prepare_database_directory(engine)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE sentinel (id INTEGER PRIMARY KEY, value TEXT NOT NULL)"))
        connection.execute(text("INSERT INTO sentinel VALUES (1,'preserve')"))
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"))
    with pytest.raises(RuntimeError, match="Unrecognized legacy database schema"):
        migrate(engine)
    assert set(inspect(engine).get_table_names()) == {"sentinel", "alembic_version"}
    with engine.connect() as connection:
        assert connection.execute(text("SELECT * FROM sentinel")).all() == [(1, "preserve")]
        assert connection.execute(text("SELECT count(*) FROM alembic_version")).scalar_one() == 0


def test_only_empty_version_table_can_recover_to_head(database):
    from app.database import prepare_database_directory
    engine, _ = database
    prepare_database_directory(engine)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"))
    migrate(engine)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0002"
