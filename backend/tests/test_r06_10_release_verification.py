"""R06-10 release verification: 0.5-era upgrade, current health 0.7.0, and network boundary."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from _migration_helpers import REVISION, STATEMENT_PREVIOUS_REVISION, revision_rows, run_alembic
from _release_helpers import (
    STARTUP_GUARD_SCRIPT,
    manual_flow_fingerprint,
    position_fingerprint,
    run_isolated_startup_script,
)


def test_pre_06_schema_upgrades_from_05_without_rewriting_owner_rows(tmp_path: Path) -> None:
    database_path = tmp_path / "pre-06.db"
    upgraded = run_alembic(database_path, "upgrade", STATEMENT_PREVIOUS_REVISION)
    assert upgraded.returncode == 0, upgraded.stderr
    assert revision_rows(database_path) == [STATEMENT_PREVIOUS_REVISION]

    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            "INSERT INTO reporting_months "
            "(year, month, period_start, period_end, snapshot_date, status, source, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                2031,
                6,
                "2031-06-01",
                "2031-06-30",
                "2031-06-30",
                "draft",
                "manual",
                "2031-06-30 00:00:00",
                "2031-06-30 00:00:00",
            ),
        )
        connection.execute(
            "INSERT INTO accounts "
            "(name, account_type, status, include_in_capital, include_in_returns) "
            "VALUES (?, ?, ?, ?, ?)",
            ("Synthetic Broker", "brokerage", "active", 1, 1),
        )
        connection.execute(
            "INSERT INTO instruments "
            "(name, instrument_type, currency, is_active, manual_price_allowed) "
            "VALUES (?, ?, ?, ?, ?)",
            ("Synthetic Bond", "bond", "RUB", 1, 1),
        )
        connection.execute(
            "INSERT INTO position_snapshots "
            "(reporting_month_id, account_id, instrument_id, quantity, "
            "average_cost_per_unit_kopecks, market_price_per_unit_kopecks, "
            "market_value_kopecks, cost_basis_kopecks, unrealized_result_kopecks, "
            "price_date, price_source, manual_adjustment, notes, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                1,
                1,
                1,
                "4.000000",
                10_000,
                11_000,
                44_000,
                40_000,
                4_000,
                "2031-06-15",
                "manual",
                0,
                "pre-0.6 snapshot",
                "2031-06-15 00:00:00",
            ),
        )
        connection.execute(
            "INSERT INTO expected_cash_flows "
            "(reporting_month_id, account_id, instrument_id, flow_type, expected_date, "
            "gross_amount_kopecks, expected_tax_amount_kopecks, expected_net_amount_kopecks, "
            "currency, source, source_as_of_date, forecast_version, is_confirmed, "
            "is_approximate, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                1,
                1,
                1,
                "coupon",
                "2031-07-15",
                80_000,
                0,
                80_000,
                "RUB",
                "owner manual",
                "2031-06-30",
                "v1",
                0,
                0,
                "keep this row",
            ),
        )
        connection.commit()
        payout_tables_before = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    finally:
        connection.close()

    assert "applied_provider_payouts" in payout_tables_before
    assert "applied_statement_events" not in payout_tables_before

    before_positions = position_fingerprint(database_path)
    before_flows = manual_flow_fingerprint(database_path)

    migrated = run_alembic(database_path, "upgrade", "head")
    assert migrated.returncode == 0, migrated.stderr
    assert revision_rows(database_path) == [REVISION]
    assert position_fingerprint(database_path) == before_positions
    assert manual_flow_fingerprint(database_path) == before_flows

    connection = sqlite3.connect(database_path)
    try:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert "applied_provider_payouts" in tables
        assert "applied_statement_events" in tables
        assert "applied_statement_event_revisions" in tables
        assert connection.execute("SELECT COUNT(*) FROM applied_provider_payouts").fetchone() == (
            0,
        )
        assert connection.execute("SELECT COUNT(*) FROM applied_statement_events").fetchone() == (
            0,
        )
        assert connection.execute("SELECT COUNT(*) FROM investment_cash_flows").fetchone() == (0,)
    finally:
        connection.close()


def test_startup_health_and_page_reads_stay_offline(tmp_path: Path) -> None:
    database_path = tmp_path / "r06-10-startup.db"
    probed = run_isolated_startup_script("probe", str(database_path))
    assert probed.returncode == 0, probed.stdout + probed.stderr
    assert "ok" in probed.stdout
    assert STARTUP_GUARD_SCRIPT.is_file()
