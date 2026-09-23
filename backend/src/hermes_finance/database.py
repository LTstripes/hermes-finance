import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import wraps
from pathlib import Path
from threading import Condition
from typing import Callable, Concatenate, Iterator, ParamSpec, TypeVar

from sqlalchemy import URL, Engine, create_engine, event
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session, sessionmaker

_READ_SNAPSHOT_DEPTH = "hermes_finance_coherent_read_snapshot_depth"
_P = ParamSpec("_P")
_R = TypeVar("_R")


@dataclass(frozen=True, slots=True)
class Database:
    database_path: Path
    engine: Engine
    session_factory: sessionmaker[Session]
    maintenance: "DatabaseMaintenance" = field(default_factory=lambda: DatabaseMaintenance())


class DatabaseMaintenanceError(RuntimeError):
    """Raised when a database operation conflicts with an active restore."""


class ReadSnapshotMutationError(RuntimeError):
    """Raised when a read-only snapshot operation attempts to persist a mutation."""


class ReadSnapshotCleanupError(RuntimeError):
    """Raised when an owned read snapshot cannot restore its connection safely."""


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


def _has_pending_orm_mutations(session: Session) -> bool:
    return bool(session.new or session.dirty or session.deleted)


def _set_sqlite_query_only(connection: sqlite3.Connection, *, enabled: bool) -> None:
    connection.execute(f"PRAGMA query_only={'ON' if enabled else 'OFF'}")


def _begin_sqlite_read_snapshot(connection: Connection) -> None:
    connection.exec_driver_sql("BEGIN")


def _restore_owned_read_state(
    session: Session,
    driver_connection: sqlite3.Connection,
    *,
    commit_guard: Callable[[Session], None],
    commit_guard_installed: bool,
    query_only_may_be_enabled: bool,
) -> None:
    """Best-effort cleanup that never returns an uncertain connection to the pool."""

    errors: list[BaseException] = []
    if commit_guard_installed:
        try:
            event.remove(session, "before_commit", commit_guard)
        except BaseException as error:
            errors.append(error)
    try:
        if driver_connection.in_transaction:
            driver_connection.rollback()
    except BaseException as error:
        errors.append(error)
    if query_only_may_be_enabled:
        try:
            _set_sqlite_query_only(driver_connection, enabled=False)
        except BaseException as error:
            errors.append(error)

    if errors:
        try:
            session.invalidate()
        except BaseException:
            pass
        raise ReadSnapshotCleanupError(
            "coherent read snapshot could not restore its SQLite connection"
        ) from errors[0]

    try:
        if session.in_transaction():
            session.rollback()
    except BaseException as error:
        try:
            session.invalidate()
        except BaseException:
            pass
        raise ReadSnapshotCleanupError(
            "coherent read snapshot could not reset its SQLAlchemy session"
        ) from error


@contextmanager
def coherent_read_snapshot(session: Session) -> Iterator[None]:
    """Pin one committed SQLite snapshot for a composite read operation.

    SQLAlchemy's logical ``Session`` transaction does not start a physical
    sqlite3 transaction for ordinary SELECTs in Python's legacy transaction
    mode. The outermost protected read therefore issues an explicit deferred
    ``BEGIN`` before its first query. Nested builders share the same Session
    and snapshot. A successful read-only transaction is committed so loaded
    ORM attributes remain materialized; failures roll it back.

    A depth-zero caller with an existing physical transaction is rejected:
    such a transaction may contain flushed, uncommitted writes and therefore
    cannot satisfy the committed-snapshot contract.
    """

    depth = int(session.info.get(_READ_SNAPSHOT_DEPTH, 0))
    if depth:
        session.info[_READ_SNAPSHOT_DEPTH] = depth + 1
        try:
            yield
        finally:
            session.info[_READ_SNAPSHOT_DEPTH] = depth
        return

    if _has_pending_orm_mutations(session):
        raise ReadSnapshotMutationError(
            "coherent read snapshot requires a session without pending ORM mutations"
        )

    connection = session.connection()
    if connection.dialect.name != "sqlite":
        yield
        return

    driver_connection = connection.connection.driver_connection
    if driver_connection.in_transaction:
        raise ReadSnapshotMutationError(
            "coherent read snapshot requires no pre-existing SQLite transaction"
        )

    # A reused Session may hold rows materialized before this physical snapshot.
    # Expire only at the outer boundary, after excluding pending/flushed writes,
    # so ORM identity-map hits must reload from the newly pinned SQLite state.
    session.expire_all()

    commit_guard_installed = False
    query_only_may_be_enabled = False
    depth_set = False

    def reject_inner_commit(_session: Session) -> None:
        raise ReadSnapshotMutationError(
            "coherent read snapshot transaction cannot be committed inside the protected operation"
        )

    try:
        query_only_may_be_enabled = True
        _set_sqlite_query_only(driver_connection, enabled=True)
        _begin_sqlite_read_snapshot(connection)
        commit_guard_installed = True
        event.listen(session, "before_commit", reject_inner_commit)
        starting_changes = driver_connection.total_changes
        session.info[_READ_SNAPSHOT_DEPTH] = 1
        depth_set = True

        yield
        if not driver_connection.in_transaction:
            raise ReadSnapshotMutationError(
                "coherent read snapshot transaction ended inside the protected operation"
            )
        if (
            _has_pending_orm_mutations(session)
            or driver_connection.total_changes != starting_changes
        ):
            raise ReadSnapshotMutationError(
                "coherent read snapshot attempted to mutate the database "
                f"(new={len(session.new)}, dirty={len(session.dirty)}, "
                f"deleted={len(session.deleted)}, "
                f"sqlite_changes={driver_connection.total_changes - starting_changes})"
            )

        event.remove(session, "before_commit", reject_inner_commit)
        commit_guard_installed = False
        _set_sqlite_query_only(driver_connection, enabled=False)
        query_only_may_be_enabled = False
        expire_on_commit = session.expire_on_commit
        session.expire_on_commit = False
        try:
            session.commit()
        finally:
            session.expire_on_commit = expire_on_commit
    except BaseException as error:
        try:
            _restore_owned_read_state(
                session,
                driver_connection,
                commit_guard=reject_inner_commit,
                commit_guard_installed=commit_guard_installed,
                query_only_may_be_enabled=query_only_may_be_enabled,
            )
        except BaseException as cleanup_error:
            raise cleanup_error from error
        raise
    finally:
        if depth_set:
            session.info.pop(_READ_SNAPSHOT_DEPTH, None)


def coherent_read_operation(
    function: Callable[Concatenate[Session, _P], _R],
) -> Callable[Concatenate[Session, _P], _R]:
    """Decorate a Session-first composite builder with one coherent snapshot."""

    @wraps(function)
    def wrapped(session: Session, *args: _P.args, **kwargs: _P.kwargs) -> _R:
        with coherent_read_snapshot(session):
            return function(session, *args, **kwargs)

    return wrapped


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
