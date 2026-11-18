"""SQLite write ownership shared by ingestion and lifecycle mutations."""
from contextlib import contextmanager
import json
import logging
import sqlite3
from time import perf_counter

from sqlalchemy.exc import OperationalError


logger = logging.getLogger("fleetsignal")


class DatabaseUnavailable(Exception):
    """A dependency operation failed; a caller may retry without partial writes."""


@contextmanager
def write_transaction(db):
    """Obtain the write lock before reading, then commit once or roll back all work.

    SQLite's Python 3.11 legacy driver does not begin on SELECT. The explicit
    statement starts the real transaction even after SQLAlchemy autobegins a
    logical session for a read. Callers must not enter with uncommitted writes.
    """
    started = perf_counter()
    acquired = None
    commit_ms = None
    phase, outcome, sqlite_error = "acquire", "rolled_back", None
    try:
        db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        acquired = perf_counter()
        phase = "work"
        yield
        phase = "commit"
        commit_started = perf_counter()
        try:
            db.commit()
        finally:
            commit_ms = round((perf_counter() - commit_started) * 1000, 3)
        outcome = "committed"
    except OperationalError as error:
        code = getattr(error.orig, "sqlite_errorcode", 0) or 0
        sqlite_error = {sqlite3.SQLITE_BUSY: "SQLITE_BUSY", sqlite3.SQLITE_LOCKED: "SQLITE_LOCKED"}.get(code & 255)
        outcome = "busy" if sqlite_error else "unavailable"
        db.rollback()
        raise DatabaseUnavailable("Database temporarily unavailable") from error
    except BaseException:
        db.rollback()
        raise
    finally:
        finished = perf_counter()
        # Acquisition includes SQLAlchemy connection-pool checkout, not just SQLite waiting.
        logger.log(logging.WARNING if outcome in ("busy", "unavailable") else logging.INFO,
                   json.dumps(dict(event="write_transaction", request_id=db.info.get("request_id"),
                                   outcome=outcome, phase=phase, sqlite_error=sqlite_error,
                                   lock_acquire_ms=round(((acquired or finished) - started) * 1000, 3),
                                   commit_ms=commit_ms, elapsed_ms=round((finished - started) * 1000, 3))))
