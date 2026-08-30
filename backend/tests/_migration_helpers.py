"""Shared synthetic Alembic helpers for migration and release tests."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_CONFIG = BACKEND_ROOT / "alembic.ini"
REVISION = "0036_broker_baseline_provenance"
PREVIOUS_REVISION = "0026_t_invest_price_source_and_provenance"
STATEMENT_PREVIOUS_REVISION = "0027_applied_provider_payouts"


def run_alembic(database_path: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["HERMES_FINANCE_DATABASE_PATH"] = str(database_path)
    environment["PYTHONIOENCODING"] = "utf-8"
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)

    return subprocess.run(
        [
            sys.executable,
            "-I",
            "-m",
            "alembic",
            "-c",
            str(ALEMBIC_CONFIG),
            *arguments,
        ],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def revision_rows(database_path: Path) -> list[str]:
    connection = sqlite3.connect(database_path)
    try:
        return [row[0] for row in connection.execute("SELECT version_num FROM alembic_version")]
    finally:
        connection.close()
