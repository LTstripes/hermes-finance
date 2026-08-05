import sqlite3
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import URL, Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker


@dataclass(frozen=True, slots=True)
class Database:
    engine: Engine
    session_factory: sessionmaker[Session]


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

    return Database(engine=engine, session_factory=session_factory)
