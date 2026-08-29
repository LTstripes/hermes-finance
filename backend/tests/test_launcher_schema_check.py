"""Regression tests for the Windows launcher's read-only schema probe."""

from __future__ import annotations

import json
import shutil
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


def test_probe_uses_selected_legacy_checkout_graph_without_legacy_probe(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "stable-v063.db"
    migrated = run_alembic(database_path, "upgrade", "0029_statement_event_retract")
    assert migrated.returncode == 0, migrated.stderr

    legacy_checkout = tmp_path / "stable-v063"
    legacy_backend = legacy_checkout / "backend"
    legacy_backend.mkdir(parents=True)
    shutil.copy2(BACKEND_ROOT / "alembic.ini", legacy_backend / "alembic.ini")
    shutil.copytree(BACKEND_ROOT / "migrations", legacy_backend / "migrations")
    for migration in (legacy_backend / "migrations" / "versions").glob("*.py"):
        if migration.name[:4].isdigit() and int(migration.name[:4]) > 29:
            migration.unlink()
    (legacy_checkout / "scripts").mkdir()

    assert not (legacy_checkout / "scripts" / "launcher-schema-check.py").exists()
    before = database_path.read_bytes()
    checked = subprocess.run(
        [
            sys.executable,
            "-I",
            str(SCHEMA_CHECK),
            "--database",
            str(database_path),
            "--checkout",
            str(legacy_checkout),
        ],
        cwd=BACKEND_ROOT,
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    assert checked.returncode == 0, checked.stderr
    assert json.loads(checked.stdout) == {
        "status": "at_head",
        "message": "database schema is at this checkout's Alembic head",
    }
    assert database_path.read_bytes() == before

    current_graph_checked = subprocess.run(
        [sys.executable, "-I", str(SCHEMA_CHECK), "--database", str(database_path)],
        cwd=BACKEND_ROOT,
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert current_graph_checked.returncode == 0, current_graph_checked.stderr
    assert json.loads(current_graph_checked.stdout)["status"] == "behind"
