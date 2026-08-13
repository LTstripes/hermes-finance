import os
import sqlite3
import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_CONFIG = BACKEND_ROOT / "alembic.ini"
REVISION = "0023_passive_income_history_eligibility"


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


def test_alembic_upgrades_and_downgrades_a_temporary_database(tmp_path: Path) -> None:
    database_path = tmp_path / "nested" / "migration-smoke.db"

    upgraded = run_alembic(database_path, "upgrade", "head")

    assert upgraded.returncode == 0, upgraded.stderr
    assert revision_rows(database_path) == [REVISION]
    connection = sqlite3.connect(database_path)
    try:
        assert connection.execute(
            "SELECT base_currency, locale, timezone, passive_income_goal_kopecks, formula_version, "
            "passive_income_history_start_month "
            "FROM app_settings WHERE id = 1"
        ).fetchone() == ("RUB", "ru-RU", "Europe/Moscow", 10_000_000, "v1", None)
        assert [row[1] for row in connection.execute("PRAGMA table_info(reporting_months)")] == [
            "id",
            "year",
            "month",
            "period_start",
            "period_end",
            "snapshot_date",
            "status",
            "source",
            "created_at",
            "updated_at",
        ]
        assert [row[1] for row in connection.execute("PRAGMA table_info(accounts)")] == [
            "id",
            "name",
            "account_type",
            "external_code",
            "status",
            "include_in_capital",
            "include_in_returns",
            "notes",
        ]
        assert [row[1] for row in connection.execute("PRAGMA table_info(iis_profiles)")] == [
            "id",
            "account_id",
            "iis_type",
            "opened_at",
            "eligible_close_at",
            "notes",
        ]
        assert [row[1] for row in connection.execute("PRAGMA table_info(iis_contributions)")] == [
            "id",
            "account_id",
            "tax_year",
            "amount_kopecks",
            "is_target_reached",
            "notes",
        ]
        assert [row[1] for row in connection.execute("PRAGMA table_info(tax_benefits)")] == [
            "id",
            "account_id",
            "tax_year",
            "benefit_type",
            "status",
            "amount_kopecks",
            "received_at",
            "notes",
        ]
        assert [row[1] for row in connection.execute("PRAGMA table_info(instruments)")] == [
            "id",
            "name",
            "instrument_type",
            "isin",
            "ticker",
            "moex_secid",
            "currency",
            "nominal_value_kopecks",
            "is_active",
            "manual_price_allowed",
            "notes",
        ]
        assert [row[1] for row in connection.execute("PRAGMA table_info(position_snapshots)")] == [
            "id",
            "reporting_month_id",
            "account_id",
            "instrument_id",
            "quantity",
            "average_cost_per_unit_kopecks",
            "market_price_per_unit_kopecks",
            "accrued_interest_kopecks",
            "market_value_kopecks",
            "cost_basis_kopecks",
            "unrealized_result_kopecks",
            "price_date",
            "price_source",
            "manual_adjustment",
            "notes",
            "updated_at",
        ]
        assert [row[1] for row in connection.execute("PRAGMA table_info(deposit_snapshots)")] == [
            "id",
            "reporting_month_id",
            "account_id",
            "name",
            "deposit_type",
            "balance_kopecks",
            "annual_rate_basis_points",
            "expected_monthly_interest_kopecks",
            "actual_interest_received_kopecks",
            "notes",
            "updated_at",
        ]
        assert [row[1] for row in connection.execute("PRAGMA table_info(cash_balances)")] == [
            "id",
            "reporting_month_id",
            "name",
            "amount_kopecks",
            "currency",
            "include_in_capital",
            "notes",
        ]
        assert [row[1] for row in connection.execute("PRAGMA table_info(income_entries)")] == [
            "id",
            "reporting_month_id",
            "income_type",
            "name",
            "gross_amount_kopecks",
            "tax_amount_kopecks",
            "net_amount_kopecks",
            "received_at",
            "is_recurring",
            "include_in_cash_flow",
            "include_in_passive_income",
            "notes",
        ]
        assert [
            row[1] for row in connection.execute("PRAGMA table_info(investment_cash_flows)")
        ] == [
            "id",
            "reporting_month_id",
            "account_id",
            "instrument_id",
            "flow_type",
            "event_date",
            "gross_amount_kopecks",
            "tax_amount_kopecks",
            "commission_amount_kopecks",
            "net_amount_kopecks",
            "currency",
            "source",
            "notes",
        ]
        assert [row[1] for row in connection.execute("PRAGMA table_info(expected_cash_flows)")] == [
            "id",
            "reporting_month_id",
            "account_id",
            "instrument_id",
            "flow_type",
            "expected_date",
            "gross_amount_kopecks",
            "expected_tax_amount_kopecks",
            "expected_net_amount_kopecks",
            "currency",
            "source",
            "source_as_of_date",
            "forecast_version",
            "is_confirmed",
            "is_approximate",
            "notes",
        ]
        assert [row[1] for row in connection.execute("PRAGMA table_info(expense_entries)")] == [
            "id",
            "reporting_month_id",
            "category",
            "amount_kopecks",
            "expense_type",
            "is_recurring",
            "notes",
        ]
        assert [row[1] for row in connection.execute("PRAGMA table_info(saving_allocations)")] == [
            "id",
            "reporting_month_id",
            "destination",
            "amount_kopecks",
            "notes",
        ]
        assert [row[1] for row in connection.execute("PRAGMA table_info(debts)")] == [
            "id",
            "reporting_month_id",
            "debt_type",
            "name",
            "current_balance_kopecks",
            "include_in_liquid_capital",
            "notes",
        ]
        assert [row[1] for row in connection.execute("PRAGMA table_info(property_snapshots)")] == [
            "id",
            "reporting_month_id",
            "name",
            "estimated_value_kopecks",
            "mortgage_balance_kopecks",
            "monthly_payment_kopecks",
            "notes",
        ]
        assert [row[1] for row in connection.execute("PRAGMA table_info(goals)")] == [
            "id",
            "name",
            "goal_type",
            "target_value_kopecks",
            "target_date",
            "is_active",
            "calculation_mode",
            "notes",
            "is_main",
        ]
        assert [row[1] for row in connection.execute("PRAGMA table_info(monthly_comments)")] == [
            "id",
            "reporting_month_id",
            "position",
            "text",
        ]
        assert [
            row[1] for row in connection.execute("PRAGMA table_info(legacy_migration_runs)")
        ] == [
            "id",
            "source_sha256",
            "source_file",
            "policy",
            "backup_id",
            "month_count",
            "summary_json",
            "applied_at",
        ]
        assert [row[1] for row in connection.execute("PRAGMA table_info(tax_brackets)")] == [
            "id",
            "year",
            "threshold_from_kopecks",
            "threshold_to_kopecks",
            "rate_bps",
        ]
        assert [
            row[1] for row in connection.execute("PRAGMA table_info(salary_tax_year_contexts)")
        ] == [
            "tax_year",
            "effective_from_month",
            "opening_taxable_gross_kopecks",
            "created_at",
            "updated_at",
        ]
    finally:
        connection.close()

    downgraded = run_alembic(database_path, "downgrade", "base")

    assert downgraded.returncode == 0, downgraded.stderr
    assert revision_rows(database_path) == []

    upgraded_again = run_alembic(database_path, "upgrade", "head")

    assert upgraded_again.returncode == 0, upgraded_again.stderr
    assert revision_rows(database_path) == [REVISION]


def test_goal_main_selection_migration_backfills_legacy_settings_goal(tmp_path: Path) -> None:
    database_path = tmp_path / "legacy-goal-migration.db"

    upgraded = run_alembic(database_path, "upgrade", "0021_salary_tax_year_contexts")
    assert upgraded.returncode == 0, upgraded.stderr

    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            "INSERT INTO goals "
            "(name, goal_type, target_value_kopecks, target_date, is_active, calculation_mode, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "Legacy passive target",
                "passive_income",
                12_345_678,
                None,
                1,
                "monthly_net_passive_income",
                None,
            ),
        )
        connection.commit()
    finally:
        connection.close()

    migrated = run_alembic(database_path, "upgrade", "head")
    assert migrated.returncode == 0, migrated.stderr

    connection = sqlite3.connect(database_path)
    try:
        assert connection.execute("SELECT target_value_kopecks, is_main FROM goals").fetchone() == (
            12_345_678,
            1,
        )
        assert connection.execute("SELECT COUNT(*) FROM goals WHERE is_main = 1").fetchone() == (1,)
    finally:
        connection.close()


def test_goal_main_selection_migration_fails_closed_for_multiple_legacy_goals(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "ambiguous-goal-migration.db"

    upgraded = run_alembic(database_path, "upgrade", "0021_salary_tax_year_contexts")
    assert upgraded.returncode == 0, upgraded.stderr

    connection = sqlite3.connect(database_path)
    try:
        connection.executemany(
            "INSERT INTO goals "
            "(name, goal_type, target_value_kopecks, target_date, is_active, calculation_mode, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "Legacy passive A",
                    "passive_income",
                    10_000_000,
                    None,
                    1,
                    "monthly_net_passive_income",
                    None,
                ),
                (
                    "Legacy passive B",
                    "passive_income",
                    20_000_000,
                    None,
                    1,
                    "monthly_net_passive_income",
                    None,
                ),
            ],
        )
        connection.commit()
    finally:
        connection.close()

    migrated = run_alembic(database_path, "upgrade", "head")

    assert migrated.returncode != 0
    assert "multiple active passive-income goals" in migrated.stderr

    connection = sqlite3.connect(database_path)
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM goals WHERE goal_type = 'passive_income'"
        ).fetchone() == (2,)
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "0021_salary_tax_year_contexts",
        )
    finally:
        connection.close()
