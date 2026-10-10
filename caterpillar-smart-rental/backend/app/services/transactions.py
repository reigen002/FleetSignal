"""SQLite write ownership shared by ingestion and lifecycle mutations."""
from contextlib import contextmanager

from sqlalchemy.exc import OperationalError


class DatabaseUnavailable(Exception):
    """A dependency operation failed; a caller may retry without partial writes."""


@contextmanager
def write_transaction(db):
    """Obtain the write lock before reading, then commit once or roll back all work.

    SQLite's Python 3.11 legacy driver does not begin on SELECT. The explicit
    statement starts the real transaction even after SQLAlchemy autobegins a
    logical session for a read. Callers must not enter with uncommitted writes.
    """
    try:
        db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        yield
        db.commit()
    except OperationalError as error:
        db.rollback()
        raise DatabaseUnavailable("Database temporarily unavailable") from error
    except BaseException:
        db.rollback()
        raise
