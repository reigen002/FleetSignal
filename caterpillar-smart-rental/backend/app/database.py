"""Database resources owned by an application, with request-scoped sessions."""
from pathlib import Path

from fastapi import Request
from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.settings import Settings


class Base(DeclarativeBase):
    pass


def create_database(settings: Settings):
    url = make_url(settings.database_url)
    connect_args = {
        "check_same_thread": False, "timeout": settings.sqlite_busy_timeout_ms / 1000,
    } if url.get_backend_name() == "sqlite" else {}
    engine = create_engine(url, connect_args=connect_args, hide_parameters=True)
    if url.get_backend_name() == "sqlite":
        @event.listens_for(engine, "connect")
        def enable_foreign_keys(connection, _record):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    session_factory = sessionmaker(
        bind=engine, autocommit=False, autoflush=False,
        info={"settings": settings, "data_dir": settings.data_dir},
    )
    return engine, session_factory


def prepare_database_directory(engine) -> None:
    """Create SQLite's parent only at startup, never while importing the app."""
    if engine.url.get_backend_name() == "sqlite" and engine.url.database not in (None, "", ":memory:"):
        Path(engine.url.database).parent.mkdir(parents=True, exist_ok=True)


def get_db(request: Request):
    """Use the same application resources as startup and close each session."""
    with request.app.state.session_factory() as db:
        yield db
