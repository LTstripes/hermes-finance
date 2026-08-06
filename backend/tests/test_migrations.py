import os
import sqlite3
import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_CONFIG = BACKEND_ROOT / "alembic.ini"
REVISION = "0017_comments"


def run_alembic(database_path: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["HERMES_FINANCE_DATABASE_PATH"] = str(database_path)
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
            "SELECT base_currency, locale, timezone, passive_income_goal_kopecks, formula_version "
            "FROM app_settings WHERE id = 1"
        ).fetchone() == ("RUB", "ru-RU", "Europe/Moscow", 10_000_000, "v1")
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
        ]
        assert [row[1] for row in connection.execute("PRAGMA table_info(monthly_comments)")] == [
            "id",
            "reporting_month_id",
            "position",
            "text",
        ]
    finally:
        connection.close()

    downgraded = run_alembic(database_path, "downgrade", "base")

    assert downgraded.returncode == 0, downgraded.stderr
    assert revision_rows(database_path) == []

    upgraded_again = run_alembic(database_path, "upgrade", "head")

    assert upgraded_again.returncode == 0, upgraded_again.stderr
    assert revision_rows(database_path) == [REVISION]
