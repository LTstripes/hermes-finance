#!/usr/bin/env python3
"""Create the launcher's pre-upgrade SQLite backup using SQLite's online API."""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

BACKUP_FILENAME_PREFIX = "finance_backup_"
BACKUP_FILENAME_SUFFIX = ".sqlite3"
BACKUP_TIMESTAMP = "%Y%m%dT%H%M%S%fZ"
BACKUP_FILENAME_RE = re.compile(
    rf"^{re.escape(BACKUP_FILENAME_PREFIX)}"
    rf"\d{{8}}T\d{{12}}Z(?:-\d+)?{re.escape(BACKUP_FILENAME_SUFFIX)}$"
)


def _schema_signature(connection: sqlite3.Connection) -> tuple[tuple[str, str, str | None], ...]:
    rows = connection.execute(
        """
        SELECT type, name, sql
        FROM sqlite_master
        WHERE name NOT LIKE 'sqlite_%'
        ORDER BY type, name
        """
    ).fetchall()
    return tuple((str(row[0]), str(row[1]), row[2]) for row in rows)


def _validate(connection: sqlite3.Connection) -> tuple[tuple[str, str, str | None], ...]:
    integrity = connection.execute("PRAGMA integrity_check").fetchone()
    if integrity != ("ok",):
        raise ValueError("SQLite integrity check failed")
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise ValueError("SQLite foreign key check failed")
    return _schema_signature(connection)


def _reserve_destination(directory: Path) -> Path:
    stem = BACKUP_FILENAME_PREFIX + datetime.now(UTC).strftime(BACKUP_TIMESTAMP)
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


def _read_only_uri(path: Path) -> str:
    return f"{path.as_uri()}?mode=ro"


def create_backup(database: Path, backup_directory: Path) -> dict[str, object]:
    database = Path(database)
    backup_directory = Path(backup_directory)
    if database.is_symlink() or not database.is_file():
        raise ValueError("source database is not a regular file")
    if backup_directory.exists() and (not backup_directory.is_dir() or backup_directory.is_symlink()):
        raise ValueError("backup directory is not a regular directory")
    database = database.resolve()
    backup_directory = backup_directory.resolve()
    backup_directory.mkdir(parents=True, exist_ok=True)

    destination = _reserve_destination(backup_directory)
    temporary: Path | None = None
    source_connection: sqlite3.Connection | None = None
    destination_connection: sqlite3.Connection | None = None
    try:
        source_connection = sqlite3.connect(_read_only_uri(database), uri=True)
        source_schema = _validate(source_connection)

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.stem}.", suffix=".tmp", dir=backup_directory
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        destination_connection = sqlite3.connect(temporary)
        source_connection.backup(destination_connection)
        destination_connection.commit()
        destination_schema = _validate(destination_connection)
        if destination_schema != source_schema:
            raise ValueError("backup schema does not match the source database")
        destination_connection.close()
        destination_connection = None
        os.replace(temporary, destination)
        temporary = None
    except (OSError, sqlite3.Error, ValueError):
        raise
    finally:
        if destination_connection is not None:
            destination_connection.close()
        if source_connection is not None:
            source_connection.close()
        if temporary is not None and temporary.exists():
            temporary.unlink()
        if destination.exists() and destination.stat().st_size == 0:
            destination.unlink()

    if (
        not BACKUP_FILENAME_RE.fullmatch(destination.name)
        or not destination.is_file()
        or destination.is_symlink()
        or destination.stat().st_size <= 0
    ):
        raise ValueError("backup destination could not be verified")

    return {
        "status": "ok",
        "backup_id": destination.stem,
        "backup_name": destination.name,
        "size_bytes": destination.stat().st_size,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--backup-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = create_backup(args.database, args.backup_dir)
    except (OSError, sqlite3.Error, ValueError) as error:
        print(f"launcher production backup failed: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
