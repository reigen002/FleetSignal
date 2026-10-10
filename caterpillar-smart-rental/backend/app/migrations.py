"""Upgrade the configured database, adopting only a validated original schema.

SQLite startup uses BEGIN IMMEDIATE before inspecting or stamping: this serializes
concurrent startup and makes DDL, legacy cleanup and revision updates atomic.
No database connections or directory creation happen during import.
"""
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
import sqlalchemy as sa

from app.database import prepare_database_directory


def migration_config(connection):
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.attributes["connection"] = connection
    return config


def _validate_legacy(connection, config):
    """Match frozen columns, type families, nullability, PKs, FKs and indexes."""
    expected = ScriptDirectory.from_config(config).get_revision("0001").module.legacy_metadata()
    inspector = sa.inspect(connection)

    def refuse(detail):
        raise RuntimeError(f"Unrecognized legacy database schema: {detail}. Refusing baseline adoption.")

    if set(inspector.get_table_names()) != set(expected.tables):
        refuse("expected exactly the original six tables")
    if inspector.get_view_names():
        refuse("unexpected views")
    if connection.dialect.name == "sqlite" and connection.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='trigger'"
    ).first():
        refuse("unexpected triggers")
    for name, table in expected.tables.items():
        actual_columns = {column["name"]: column for column in inspector.get_columns(name)}
        if set(actual_columns) != set(table.columns.keys()):
            refuse(f"{name} columns differ")
        for column in table.columns:
            actual = actual_columns[column.name]
            if (actual["type"]._type_affinity != column.type._type_affinity
                or actual["nullable"] != column.nullable
                or actual.get("default") is not None
                or getattr(actual["type"], "length", None) != getattr(column.type, "length", None)):
                refuse(f"{name}.{column.name} type, nullability or default differs")
        if inspector.get_pk_constraint(name)["constrained_columns"] != [column.name for column in table.primary_key]:
            refuse(f"{name} primary key differs")
        actual_fks = {
            (tuple(fk["constrained_columns"]), fk["referred_table"], tuple(fk["referred_columns"]))
            for fk in inspector.get_foreign_keys(name)
            if not fk.get("options")
        }
        expected_fks = {
            (tuple(column.parent.name for column in fk.elements),
             fk.referred_table.name, tuple(column.column.name for column in fk.elements))
            for fk in table.foreign_key_constraints
        }
        if actual_fks != expected_fks or len(inspector.get_foreign_keys(name)) != len(expected_fks):
            refuse(f"{name} foreign keys differ")
        actual_indexes = {(index["name"], tuple(index["column_names"]), bool(index["unique"]))
                          for index in inspector.get_indexes(name) if not index.get("dialect_options")}
        expected_indexes = {(index.name, tuple(column.name for column in index.columns), index.unique)
                            for index in table.indexes}
        if actual_indexes != expected_indexes or len(inspector.get_indexes(name)) != len(expected_indexes):
            refuse(f"{name} indexes differ")
        if inspector.get_unique_constraints(name) or inspector.get_check_constraints(name):
            refuse(f"{name} unexpected constraints")


def run_migrations(engine):
    prepare_database_directory(engine)
    with engine.connect() as connection:
        try:
            if engine.dialect.name == "sqlite":
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            else:
                connection.begin()
            config = migration_config(connection)
            tables = sa.inspect(connection).get_table_names()
            if "alembic_version" in tables and len(tables) > 1 and connection.execute(
                sa.text("SELECT version_num FROM alembic_version")
            ).first() is None:
                raise RuntimeError(
                    "Unrecognized legacy database schema: an empty Alembic revision table "
                    "cannot identify existing tables. Refusing baseline adoption."
                )
            if tables and "alembic_version" not in tables:
                _validate_legacy(connection, config)
                command.stamp(config, "0001")
            command.upgrade(config, "head")
            connection.commit()
        except Exception:
            connection.rollback()
            raise


if __name__ == "__main__":
    from app.database import create_database
    from app.settings import Settings

    engine, _sessions = create_database(Settings())
    try:
        run_migrations(engine)
    finally:
        engine.dispose()
