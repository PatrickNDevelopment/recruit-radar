"""Engine and session construction.

Every new SQLite connection gets the same four pragmas. They are set in the ``connect`` event,
i.e. before SQLAlchemy opens a transaction on the connection, because:

* ``foreign_keys`` is per connection and a no-op inside a transaction;
* ``journal_mode=WAL`` is stored in the database file but cannot be changed inside one;
* ``busy_timeout`` is per connection (it makes a writer wait instead of failing at once);
* ``synchronous=NORMAL`` is the documented pairing for WAL.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import URL
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import ConnectionPoolEntry

BUSY_TIMEOUT_MS = 5000


def _apply_pragmas(dbapi_connection: DBAPIConnection, _record: ConnectionPoolEntry) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        cursor.execute("PRAGMA synchronous=NORMAL")
    finally:
        cursor.close()


def create_db_engine(db_path: Path) -> Engine:
    """A SQLAlchemy engine for the SQLite file at ``db_path`` (parent directory is created)."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        URL.create("sqlite+pysqlite", database=str(db_path)),
        # Requests run in a thread pool; connections are never shared concurrently.
        connect_args={"check_same_thread": False, "timeout": BUSY_TIMEOUT_MS / 1000},
    )
    event.listen(engine, "connect", _apply_pragmas)
    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
