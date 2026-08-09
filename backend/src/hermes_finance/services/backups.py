"""Safe SQLite online backups for the local database (F04)."""

from __future__ import annotations

import os
import re
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from hermes_finance.database import Database

BACKUP_DIRECTORY_NAME = "backups"
BACKUP_FILENAME_PREFIX = "finance_backup_"
BACKUP_FILENAME_SUFFIX = ".sqlite3"
_BACKUP_TIMESTAMP = "%Y%m%dT%H%M%S%fZ"
_BACKUP_FILENAME_RE = re.compile(
    rf"^{re.escape(BACKUP_FILENAME_PREFIX)}"
    rf"(?P<timestamp>\d{{8}}T\d{{12}}Z)"
    rf"(?:-(?P<sequence>\d+))?{re.escape(BACKUP_FILENAME_SUFFIX)}$"
)


class BackupStorageError(RuntimeError):
    """The configured local backup directory cannot be used."""


@dataclass(frozen=True, slots=True)
class BackupSourceMetadata:
    name: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class BackupMetadata:
    id: str
    name: str
    created_at: datetime
    size_bytes: int
    source_database: BackupSourceMetadata


def backup_directory(database: Database) -> Path:
    """Return the ignored backup directory next to the configured database."""
    return database.database_path.parent / BACKUP_DIRECTORY_NAME


def _usable_backup_directory(database: Database, *, create: bool) -> Path:
    directory = backup_directory(database)
    if directory.exists():
        if not directory.is_dir():
            raise BackupStorageError("Backup directory is not a directory")
    elif create:
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise BackupStorageError("Backup directory is not available") from error
    return directory


def _source_metadata(database: Database) -> BackupSourceMetadata:
    source = database.database_path
    try:
        size_bytes = source.stat().st_size
    except OSError:
        size_bytes = 0
    return BackupSourceMetadata(name=source.name, size_bytes=size_bytes)


def _backup_stem(created_at: datetime) -> str:
    timestamp = created_at.astimezone(UTC).strftime(_BACKUP_TIMESTAMP)
    return f"{BACKUP_FILENAME_PREFIX}{timestamp}"


def _reserve_destination(created_at: datetime, directory: Path) -> Path:
    """Reserve a unique final name atomically across processes."""
    stem = _backup_stem(created_at)
    sequence = 0
    while True:
        suffix = "" if sequence == 0 else f"-{sequence}"
        candidate = directory / f"{stem}{suffix}{BACKUP_FILENAME_SUFFIX}"
        try:
            descriptor = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            sequence += 1
            continue
        os.close(descriptor)
        return candidate


def _normalized_now(now: datetime | None) -> datetime:
    value = now or datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _metadata_for_path(database: Database, path: Path, *, created_at: datetime) -> BackupMetadata:
    return BackupMetadata(
        id=path.stem,
        name=path.name,
        created_at=created_at,
        size_bytes=path.stat().st_size,
        source_database=_source_metadata(database),
    )


def create_backup(database: Database, *, now: datetime | None = None) -> BackupMetadata:
    """Create an atomic snapshot using SQLite's online backup API."""
    directory = _usable_backup_directory(database, create=True)
    created_at = _normalized_now(now)
    destination = _reserve_destination(created_at, directory)
    temporary: Path | None = None
    source_connection = None
    destination_connection: sqlite3.Connection | None = None
    try:
        temporary_descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.stem}.", suffix=".tmp", dir=directory
        )
        os.close(temporary_descriptor)
        temporary = Path(temporary_name)
        source_connection = database.engine.raw_connection()
        destination_connection = sqlite3.connect(temporary)
        source_connection.driver_connection.backup(destination_connection)
        destination_connection.commit()
        destination_connection.close()
        destination_connection = None
        os.replace(temporary, destination)
    except (OSError, sqlite3.Error) as error:
        raise BackupStorageError("Could not create database backup") from error
    finally:
        if destination_connection is not None:
            destination_connection.close()
        if source_connection is not None:
            source_connection.close()
        if temporary is not None and temporary.exists():
            temporary.unlink()
        if destination.exists() and destination.stat().st_size == 0:
            destination.unlink()

    return _metadata_for_path(database, destination, created_at=created_at)


def _created_at_from_path(path: Path) -> datetime:
    match = _BACKUP_FILENAME_RE.match(path.name)
    if match is not None:
        return datetime.strptime(match.group("timestamp"), _BACKUP_TIMESTAMP).replace(tzinfo=UTC)
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)


def _sequence_from_path(path: Path) -> int:
    match = _BACKUP_FILENAME_RE.match(path.name)
    return int(match.group("sequence") or 0) if match is not None else 0


def list_backups(database: Database) -> list[BackupMetadata]:
    """List valid local backups newest first; a missing directory is empty."""
    directory = _usable_backup_directory(database, create=False)
    if not directory.exists():
        return []
    try:
        paths = list(directory.iterdir())
    except OSError as error:
        raise BackupStorageError("Backup directory is not available") from error
    backups = [
        path
        for path in paths
        if path.is_file() and _BACKUP_FILENAME_RE.match(path.name) is not None
    ]
    return [
        _metadata_for_path(database, path, created_at=_created_at_from_path(path))
        for path in sorted(
            backups,
            key=lambda path: (_created_at_from_path(path), _sequence_from_path(path)),
            reverse=True,
        )
    ]
