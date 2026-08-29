"""Regression tests for the Windows launcher's read-only schema probe."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from test_migrations import run_alembic

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_CHECK = BACKEND_ROOT.parent / "scripts" / "launcher-schema-check.py"
KNOWN_BEHIND_REVISION = "0032_cash_balance_account_link"


def test_known_older_revision_is_behind_and_probe_is_read_only(tmp_path: Path) -> None:
    database_path = tmp_path / "known-behind.db"
    migrated = run_alembic(database_path, "upgrade", KNOWN_BEHIND_REVISION)
    assert migrated.returncode == 0, migrated.stderr

    before = database_path.read_bytes()
    checked = subprocess.run(
        [sys.executable, "-I", str(SCHEMA_CHECK), "--database", str(database_path)],
        cwd=BACKEND_ROOT,
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    assert checked.returncode == 0, checked.stderr
    assert json.loads(checked.stdout) == {
        "status": "behind",
        "message": "database schema is behind this checkout and may be upgraded by guarded startup",
    }
    assert database_path.read_bytes() == before
    connection = sqlite3.connect(database_path)
    try:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            KNOWN_BEHIND_REVISION,
        )
    finally:
        connection.close()
