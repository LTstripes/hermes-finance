"""Shared synthetic helpers for release verification tests."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
STARTUP_GUARD_SCRIPT = Path(__file__).resolve().parent / "startup_network_guard.py"


def run_isolated_startup_script(*arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "utf-8"
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    environment.pop("HERMES_FINANCE_T_INVEST_READ_ONLY_TOKEN", None)
    return subprocess.run(
        [sys.executable, "-I", str(STARTUP_GUARD_SCRIPT), *arguments],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _fetch_rows(database_path: Path, query: str) -> list[tuple[object, ...]]:
    connection = sqlite3.connect(database_path)
    try:
        return connection.execute(query).fetchall()
    finally:
        connection.close()


def position_fingerprint(database_path: Path) -> list[tuple[object, ...]]:
    return _fetch_rows(
        database_path,
        "SELECT id, reporting_month_id, quantity, market_price_per_unit_kopecks, "
        "price_source, notes FROM position_snapshots ORDER BY id",
    )


def manual_flow_fingerprint(database_path: Path) -> list[tuple[object, ...]]:
    return _fetch_rows(
        database_path,
        "SELECT id, reporting_month_id, account_id, instrument_id, flow_type, "
        "expected_date, gross_amount_kopecks, expected_tax_amount_kopecks, "
        "expected_net_amount_kopecks, source, notes FROM expected_cash_flows ORDER BY id",
    )
