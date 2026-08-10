import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from threading import Condition
from typing import Iterator

from sqlalchemy import URL, Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker


@dataclass(frozen=True, slots=True)
class Database:
    database_path: Path
    engine: Engine
    session_factory: sessionmaker[Session]
    maintenance: "DatabaseMaintenance" = field(default_factory=lambda: DatabaseMaintenance())


class DatabaseMaintenanceError(RuntimeError):
    """Raised when a database operation conflicts with an active restore."""


class DatabaseMaintenance:
    """Process-local admission control for database operations and restore."""

    def __init__(self) -> None:
        self._condition = Condition()
        self._active_operations = 0
        self._is_restoring = False

    @property
    def is_restoring(self) -> bool:
        with self._condition:
            return self._is_restoring

    @contextmanager
    def operation(self) -> Iterator[None]:
        with self._condition:
            if self._is_restoring:
                raise DatabaseMaintenanceError("Database restore is in progress")
            self._active_operations += 1
        try:
            yield
        finally:
            with self._condition:
                self._active_operations -= 1
                self._condition.notify_all()

    @contextmanager
    def restore(self) -> Iterator[None]:
        with self._condition:
            if self._is_restoring:
                raise DatabaseMaintenanceError("Database restore is in progress")
            self._is_restoring = True
            while self._active_operations:
                self._condition.wait()
        try:
            yield
        finally:
            with self._condition:
                self._is_restoring = False
                self._condition.notify_all()


def _enable_sqlite_foreign_keys(
    dbapi_connection: sqlite3.Connection, _connection_record: object
) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


def create_database(database_path: Path) -> Database:
    resolved_path = database_path.expanduser().resolve()
    resolved_path.parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(
        URL.create("sqlite+pysqlite", database=resolved_path.as_posix()),
        connect_args={"check_same_thread": False},
    )
    event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    return Database(
        database_path=resolved_path,
        engine=engine,
        session_factory=session_factory,
    )
