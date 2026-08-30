import sqlite3
from pathlib import Path

from _migration_helpers import (
    PREVIOUS_REVISION,
    REVISION,
    STATEMENT_PREVIOUS_REVISION,
    revision_rows,
    run_alembic,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]


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
        assert [
            row[1] for row in connection.execute("PRAGMA table_info(instrument_market_mappings)")
        ] == [
            "instrument_id",
            "provider",
            "provider_instrument_id",
            "provider_venue_id",
            "excluded",
            "updated_at",
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
            "account_id",
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
        assert [
            row[1] for row in connection.execute("PRAGMA table_info(external_transfer_links)")
        ] == [
            "id",
            "transfer_key",
            "status",
            "notes",
            "created_at",
            "updated_at",
        ]
        assert [row[1] for row in connection.execute("PRAGMA table_info(external_flows)")] == [
            "id",
            "reporting_month_id",
            "account_id",
            "event_date",
            "boundary_amount_kopecks",
            "direction",
            "kind",
            "currency",
            "transfer_link_id",
            "source",
            "notes",
            "created_at",
            "updated_at",
            "scope_membership",
        ]
        assert [
            row[1] for row in connection.execute("PRAGMA table_info(external_flow_boundary_groups)")
        ] == [
            "id",
            "reporting_month_id",
            "scope",
            "account_id",
            "boundary_date",
            "created_at",
            "updated_at",
        ]
        assert [
            row[1]
            for row in connection.execute("PRAGMA table_info(external_flow_boundary_group_members)")
        ] == ["boundary_group_id", "external_flow_id"]
        assert [
            row[1] for row in connection.execute("PRAGMA table_info(observed_valuation_points)")
        ] == [
            "id",
            "reporting_month_id",
            "scope",
            "account_id",
            "observed_date",
            "total_value_kopecks",
            "performance_currency",
            "coverage_status",
            "quality",
            "provenance_kind",
            "provenance_reference",
            "relation",
            "external_flow_id",
            "boundary_group_id",
            "notes",
            "created_at",
            "updated_at",
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
        assert [
            row[1] for row in connection.execute("PRAGMA table_info(applied_provider_payouts)")
        ] == [
            "id",
            "reporting_month_id",
            "account_id",
            "instrument_id",
            "source_position_snapshot_id",
            "provider",
            "provider_instrument_uid",
            "event_kind",
            "identity_key",
            "lifecycle",
            "payment_date",
            "quantity",
            "per_unit_amount",
            "total_amount_kopecks",
            "currency",
            "amount_basis",
            "is_approximate",
            "provider_status",
            "first_applied_at",
        ]
        assert [
            row[1] for row in connection.execute("PRAGMA table_info(applied_payout_revisions)")
        ] == [
            "id",
            "applied_payout_id",
            "revision_kind",
            "source_position_snapshot_id",
            "provider",
            "provider_instrument_uid",
            "event_kind",
            "identity_key",
            "lifecycle",
            "payment_date",
            "quantity",
            "per_unit_amount",
            "total_amount_kopecks",
            "currency",
            "amount_basis",
            "is_approximate",
            "provider_status",
            "fetched_at",
            "applied_at",
        ]
        assert [
            row[1]
            for row in connection.execute("PRAGMA table_info(applied_payout_reconciliations)")
        ] == [
            "id",
            "applied_payout_id",
            "expected_cash_flow_id",
            "counting_decision",
            "created_at",
        ]
        assert [
            row[1] for row in connection.execute("PRAGMA table_info(applied_statement_events)")
        ] == [
            "id",
            "provider",
            "account_id",
            "instrument_id",
            "event_kind",
            "isin",
            "record_date",
            "natural_identity",
            "material_fingerprint",
            "investment_cash_flow_id",
            "document_sha256",
            "link_mode",
            "status",
            "retracted_at",
            "created_at",
            "updated_at",
        ]
        assert [
            row[1]
            for row in connection.execute("PRAGMA table_info(applied_statement_event_revisions)")
        ] == [
            "id",
            "applied_statement_event_id",
            "revision_kind",
            "document_sha256",
            "natural_identity",
            "material_fingerprint",
            "account_id",
            "instrument_id",
            "event_kind",
            "isin",
            "record_date",
            "event_date",
            "quantity",
            "per_unit",
            "gross_amount_kopecks",
            "gross_currency",
            "tax_available",
            "tax_amount_kopecks",
            "tax_rate",
            "net_amount_kopecks",
            "net_currency",
            "applied_at",
        ]
    finally:
        connection.close()

    downgraded = run_alembic(database_path, "downgrade", "base")

    assert downgraded.returncode == 0, downgraded.stderr
    assert revision_rows(database_path) == []

    upgraded_again = run_alembic(database_path, "upgrade", "head")

    assert upgraded_again.returncode == 0, upgraded_again.stderr
    assert revision_rows(database_path) == [REVISION]


def test_boundary_migration_downgrade_refuses_observed_data(tmp_path: Path) -> None:
    database_path = tmp_path / "boundary-downgrade.db"

    upgraded = run_alembic(database_path, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr

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
            ("Synthetic Boundary Migration Account", "brokerage", "active", 1, 1),
        )
        connection.execute(
            "INSERT INTO external_flows "
            "(reporting_month_id, account_id, event_date, boundary_amount_kopecks, "
            "direction, kind, currency, transfer_link_id, source, notes, created_at, "
            "updated_at, scope_membership) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                1,
                1,
                "2031-06-15",
                10_000,
                "contribution",
                "external_contribution",
                "RUB",
                None,
                "synthetic_migration",
                None,
                "2031-06-15 00:00:00",
                "2031-06-15 00:00:00",
                "stable_in_scope",
            ),
        )
        connection.execute(
            "INSERT INTO external_flow_boundary_groups "
            "(reporting_month_id, scope, account_id, boundary_date, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                1,
                "account",
                1,
                "2031-06-15",
                "2031-06-15 00:00:00",
                "2031-06-15 00:00:00",
            ),
        )
        connection.execute(
            "INSERT INTO external_flow_boundary_group_members "
            "(boundary_group_id, external_flow_id) VALUES (?, ?)",
            (1, 1),
        )
        connection.execute(
            "INSERT INTO observed_valuation_points "
            "(reporting_month_id, scope, account_id, observed_date, total_value_kopecks, "
            "performance_currency, coverage_status, quality, provenance_kind, "
            "provenance_reference, relation, external_flow_id, boundary_group_id, notes, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                1,
                "account",
                1,
                "2031-06-15",
                100_000,
                "RUB",
                "complete",
                "exact",
                "synthetic_migration",
                "migration-test",
                "pre_external_flow",
                None,
                1,
                "synthetic",
                "2031-06-15 00:00:00",
                "2031-06-15 00:00:00",
            ),
        )
        connection.commit()
    finally:
        connection.close()

    downgraded = run_alembic(database_path, "downgrade", "0033_account_scope_membership_history")

    assert downgraded.returncode != 0
    assert "while boundary evidence exists" in downgraded.stderr
    # 0035 can drop an empty mapping registry; 0034 must refuse while evidence exists.
    assert revision_rows(database_path) == ["0034_observed_valuation_boundaries"]


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


def test_passive_history_migration_from_0022_defaults_null_and_preserves_data(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "passive-history-migration.db"

    previous_head = run_alembic(database_path, "upgrade", "0022_goal_main_selection")
    assert previous_head.returncode == 0, previous_head.stderr

    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            "UPDATE app_settings SET locale = ?, timezone = ?, passive_income_goal_kopecks = ?, "
            "formula_version = ? WHERE id = 1",
            ("en-US", "UTC", 12_345_678, "v2"),
        )
        connection.execute(
            "INSERT INTO reporting_months "
            "(year, month, period_start, period_end, snapshot_date, status, source, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                2031,
                5,
                "2031-05-01",
                "2031-05-31",
                "2031-05-31",
                "closed",
                "manual",
                "2031-05-31 00:00:00",
                "2031-05-31 00:00:00",
            ),
        )
        connection.commit()
    finally:
        connection.close()

    migrated = run_alembic(database_path, "upgrade", "head")
    assert migrated.returncode == 0, migrated.stderr

    connection = sqlite3.connect(database_path)
    try:
        assert connection.execute(
            "SELECT locale, timezone, passive_income_goal_kopecks, formula_version, "
            "passive_income_history_start_month FROM app_settings WHERE id = 1"
        ).fetchone() == ("en-US", "UTC", 12_345_678, "v2", None)
        assert connection.execute(
            "SELECT year, month, status, source FROM reporting_months"
        ).fetchone() == (2031, 5, "closed", "manual")
        assert connection.execute(
            "SELECT target_value_kopecks, is_main FROM goals WHERE id = 1"
        ).fetchone() == (10_000_000, 1)
        assert revision_rows(database_path) == [REVISION]
    finally:
        connection.close()


def test_instrument_mapping_migration_does_not_infer_legacy_moex_secid(tmp_path: Path) -> None:
    database_path = tmp_path / "legacy-instrument-mapping.db"

    previous = run_alembic(database_path, "upgrade", "0023_passive_income_history_eligibility")
    assert previous.returncode == 0, previous.stderr

    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            "INSERT INTO reporting_months "
            "(year, month, period_start, period_end, snapshot_date, status, source, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                2031,
                4,
                "2031-04-01",
                "2031-04-30",
                "2031-04-30",
                "closed",
                "manual",
                "2031-04-30 00:00:00",
                "2031-04-30 00:00:00",
            ),
        )
        connection.execute(
            "INSERT INTO accounts (name, account_type, status, include_in_capital, include_in_returns) "
            "VALUES (?, ?, ?, ?, ?)",
            ("Synthetic Broker", "brokerage", "active", 1, 1),
        )
        connection.execute(
            "INSERT INTO instruments "
            "(name, instrument_type, isin, ticker, moex_secid, currency, is_active, manual_price_allowed) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "Synthetic With Hint",
                "stock",
                "RU0009029540",
                "SBER",
                "SBER",
                "RUB",
                1,
                1,
            ),
        )
        connection.execute(
            "INSERT INTO instruments "
            "(name, instrument_type, isin, ticker, moex_secid, currency, is_active, manual_price_allowed) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("Synthetic Without Hint", "bond", None, None, None, "RUB", 1, 1),
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
                "3.000000",
                10_000,
                25_000,
                75_000,
                30_000,
                45_000,
                "2031-04-15",
                "moex",
                0,
                "synthetic snapshot",
                "2031-04-15 00:00:00",
            ),
        )
        connection.commit()
    finally:
        connection.close()

    migrated = run_alembic(database_path, "upgrade", "head")
    assert migrated.returncode == 0, migrated.stderr
    assert revision_rows(database_path) == [REVISION]

    connection = sqlite3.connect(database_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM instrument_market_mappings").fetchone() == (
            0,
        )
        assert connection.execute(
            "SELECT id, moex_secid FROM instruments ORDER BY id"
        ).fetchall() == [(1, "SBER"), (2, None)]
        assert connection.execute(
            "SELECT market_price_per_unit_kopecks, price_date, price_source, notes "
            "FROM position_snapshots WHERE id = 1"
        ).fetchone() == (25_000, "2031-04-15", "moex", "synthetic snapshot")

        connection.execute(
            "INSERT INTO instrument_market_mappings "
            "(instrument_id, provider, provider_instrument_id, provider_venue_id, excluded, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (1, "moex_iss", "SBER", "stock/shares/TQBR", 0, "2031-04-16 00:00:00"),
        )
        connection.commit()
    finally:
        connection.close()

    downgraded = run_alembic(database_path, "downgrade", "0023_passive_income_history_eligibility")
    assert downgraded.returncode == 0, downgraded.stderr
    assert revision_rows(database_path) == ["0023_passive_income_history_eligibility"]

    connection = sqlite3.connect(database_path)
    try:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert "instrument_market_mappings" not in tables
        assert connection.execute(
            "SELECT id, moex_secid FROM instruments ORDER BY id"
        ).fetchall() == [(1, "SBER"), (2, None)]
        assert connection.execute(
            "SELECT market_price_per_unit_kopecks, price_date, price_source "
            "FROM position_snapshots WHERE id = 1"
        ).fetchone() == (25_000, "2031-04-15", "moex")
    finally:
        connection.close()

    upgraded_again = run_alembic(database_path, "upgrade", "head")
    assert upgraded_again.returncode == 0, upgraded_again.stderr
    assert revision_rows(database_path) == [REVISION]

    connection = sqlite3.connect(database_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM instrument_market_mappings").fetchone() == (
            0,
        )
        assert connection.execute(
            "SELECT id, moex_secid FROM instruments ORDER BY id"
        ).fetchall() == [(1, "SBER"), (2, None)]
        assert connection.execute(
            "SELECT market_price_per_unit_kopecks, price_date, price_source "
            "FROM position_snapshots WHERE id = 1"
        ).fetchone() == (25_000, "2031-04-15", "moex")
    finally:
        connection.close()


def test_provider_neutral_identity_migration_preserves_moex_rows(tmp_path: Path) -> None:
    database_path = tmp_path / "provider-neutral-identity.db"

    previous = run_alembic(database_path, "upgrade", "0024_instrument_market_mappings")
    assert previous.returncode == 0, previous.stderr

    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            "INSERT INTO reporting_months "
            "(year, month, period_start, period_end, snapshot_date, status, source, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                2031,
                4,
                "2031-04-01",
                "2031-04-30",
                "2031-04-30",
                "closed",
                "manual",
                "2031-04-30 00:00:00",
                "2031-04-30 00:00:00",
            ),
        )
        connection.execute(
            "INSERT INTO accounts (name, account_type, status, include_in_capital, include_in_returns) "
            "VALUES (?, ?, ?, ?, ?)",
            ("Synthetic Broker", "brokerage", "active", 1, 1),
        )
        connection.executemany(
            "INSERT INTO instruments "
            "(name, instrument_type, isin, ticker, moex_secid, currency, is_active, manual_price_allowed) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("Synthetic Stock", "stock", "RU0009029540", "SBER", "SBER", "RUB", 1, 1),
                ("Synthetic Bond", "bond", None, None, "SU26248", "RUB", 1, 1),
                ("Synthetic Excluded Mapped", "stock", None, None, None, "RUB", 1, 1),
                ("Synthetic Excluded Bare", "stock", None, None, None, "RUB", 1, 1),
                ("Synthetic Hint Only", "stock", None, None, "HINT", "RUB", 1, 1),
            ],
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
                "3.000000",
                10_000,
                25_000,
                75_000,
                30_000,
                45_000,
                "2031-04-15",
                "moex",
                0,
                "synthetic snapshot",
                "2031-04-15 00:00:00",
            ),
        )
        connection.executemany(
            "INSERT INTO instrument_market_mappings "
            "(instrument_id, provider, engine, market, boardid, secid, excluded, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (1, "moex_iss", "stock", "shares", "TQBR", "SBER", 0, "2031-04-16 00:00:00"),
                (2, "moex_iss", "stock", "bonds", "TQOB", "SU26248", 0, "2031-04-16 00:00:00"),
                (3, "moex_iss", "stock", "shares", "TQBR", "SBER", 1, "2031-04-16 00:00:00"),
                (4, None, None, None, None, None, 1, "2031-04-16 00:00:00"),
            ],
        )
        connection.commit()
        snapshot_before = connection.execute(
            "SELECT market_price_per_unit_kopecks, price_date, price_source, notes "
            "FROM position_snapshots WHERE id = 1"
        ).fetchone()
        month_before = connection.execute(
            "SELECT year, month, status, snapshot_date FROM reporting_months WHERE id = 1"
        ).fetchone()
        instruments_before = connection.execute(
            "SELECT id, moex_secid FROM instruments ORDER BY id"
        ).fetchall()
    finally:
        connection.close()

    migrated = run_alembic(database_path, "upgrade", "head")
    assert migrated.returncode == 0, migrated.stderr
    assert revision_rows(database_path) == [REVISION]

    connection = sqlite3.connect(database_path)
    try:
        columns = [
            row[1] for row in connection.execute("PRAGMA table_info(instrument_market_mappings)")
        ]
        assert columns == [
            "instrument_id",
            "provider",
            "provider_instrument_id",
            "provider_venue_id",
            "excluded",
            "updated_at",
        ]
        assert connection.execute(
            "SELECT provider, provider_instrument_id, provider_venue_id, excluded "
            "FROM instrument_market_mappings WHERE instrument_id = 1"
        ).fetchone() == ("moex_iss", "SBER", "stock/shares/TQBR", 0)
        assert connection.execute(
            "SELECT provider, provider_instrument_id, provider_venue_id, excluded "
            "FROM instrument_market_mappings WHERE instrument_id = 2"
        ).fetchone() == ("moex_iss", "SU26248", "stock/bonds/TQOB", 0)
        assert connection.execute(
            "SELECT provider, provider_instrument_id, provider_venue_id, excluded "
            "FROM instrument_market_mappings WHERE instrument_id = 3"
        ).fetchone() == ("moex_iss", "SBER", "stock/shares/TQBR", 1)
        assert connection.execute(
            "SELECT provider, provider_instrument_id, provider_venue_id, excluded "
            "FROM instrument_market_mappings WHERE instrument_id = 4"
        ).fetchone() == (None, None, None, 1)
        assert connection.execute(
            "SELECT COUNT(*) FROM instrument_market_mappings WHERE instrument_id = 5"
        ).fetchone() == (0,)
        assert (
            connection.execute(
                "SELECT market_price_per_unit_kopecks, price_date, price_source, notes "
                "FROM position_snapshots WHERE id = 1"
            ).fetchone()
            == snapshot_before
        )
        assert (
            connection.execute(
                "SELECT year, month, status, snapshot_date FROM reporting_months WHERE id = 1"
            ).fetchone()
            == month_before
        )
        assert (
            connection.execute("SELECT id, moex_secid FROM instruments ORDER BY id").fetchall()
            == instruments_before
        )
    finally:
        connection.close()

    downgraded = run_alembic(database_path, "downgrade", "0024_instrument_market_mappings")
    assert downgraded.returncode == 0, downgraded.stderr
    assert revision_rows(database_path) == ["0024_instrument_market_mappings"]

    connection = sqlite3.connect(database_path)
    try:
        columns = [
            row[1] for row in connection.execute("PRAGMA table_info(instrument_market_mappings)")
        ]
        assert columns == [
            "instrument_id",
            "provider",
            "engine",
            "market",
            "boardid",
            "secid",
            "excluded",
            "updated_at",
        ]
        assert connection.execute(
            "SELECT provider, engine, market, boardid, secid, excluded "
            "FROM instrument_market_mappings WHERE instrument_id = 1"
        ).fetchone() == ("moex_iss", "stock", "shares", "TQBR", "SBER", 0)
        assert connection.execute(
            "SELECT provider, engine, market, boardid, secid, excluded "
            "FROM instrument_market_mappings WHERE instrument_id = 2"
        ).fetchone() == ("moex_iss", "stock", "bonds", "TQOB", "SU26248", 0)
        assert connection.execute(
            "SELECT provider, engine, market, boardid, secid, excluded "
            "FROM instrument_market_mappings WHERE instrument_id = 3"
        ).fetchone() == ("moex_iss", "stock", "shares", "TQBR", "SBER", 1)
        assert connection.execute(
            "SELECT provider, engine, market, boardid, secid, excluded "
            "FROM instrument_market_mappings WHERE instrument_id = 4"
        ).fetchone() == (None, None, None, None, None, 1)
        assert (
            connection.execute(
                "SELECT market_price_per_unit_kopecks, price_date, price_source, notes "
                "FROM position_snapshots WHERE id = 1"
            ).fetchone()
            == snapshot_before
        )
        assert (
            connection.execute("SELECT id, moex_secid FROM instruments ORDER BY id").fetchall()
            == instruments_before
        )
    finally:
        connection.close()

    upgraded_again = run_alembic(database_path, "upgrade", "head")
    assert upgraded_again.returncode == 0, upgraded_again.stderr
    assert revision_rows(database_path) == [REVISION]

    connection = sqlite3.connect(database_path)
    try:
        assert connection.execute(
            "SELECT provider, provider_instrument_id, provider_venue_id, excluded "
            "FROM instrument_market_mappings WHERE instrument_id = 1"
        ).fetchone() == ("moex_iss", "SBER", "stock/shares/TQBR", 0)
        assert connection.execute(
            "SELECT provider, provider_instrument_id, provider_venue_id, excluded "
            "FROM instrument_market_mappings WHERE instrument_id = 2"
        ).fetchone() == ("moex_iss", "SU26248", "stock/bonds/TQOB", 0)
        assert connection.execute(
            "SELECT COUNT(*) FROM instrument_market_mappings WHERE instrument_id = 5"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT market_price_per_unit_kopecks, price_date, price_source "
            "FROM position_snapshots WHERE id = 1"
        ).fetchone() == (25_000, "2031-04-15", "moex")
    finally:
        connection.close()


def test_provider_neutral_downgrade_rejects_identity_without_venue(tmp_path: Path) -> None:
    database_path = tmp_path / "non-moex-downgrade.db"

    upgraded = run_alembic(database_path, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr

    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            "INSERT INTO instruments "
            "(name, instrument_type, isin, ticker, moex_secid, currency, is_active, manual_price_allowed) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("Synthetic Opaque", "stock", None, None, None, "RUB", 1, 1),
        )
        connection.execute(
            "INSERT INTO instrument_market_mappings "
            "(instrument_id, provider, provider_instrument_id, provider_venue_id, excluded, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (1, "synthetic_provider", "opaque-security-id", None, 0, "2031-04-16 00:00:00"),
        )
        connection.commit()
    finally:
        connection.close()

    downgraded = run_alembic(database_path, "downgrade", "0024_instrument_market_mappings")
    assert downgraded.returncode != 0
    assert "provider_venue_id" in downgraded.stderr
    assert revision_rows(database_path) == ["0025_provider_neutral_market_identity"]


def test_applied_payout_migration_is_additive_and_preserves_manual_rows(tmp_path: Path) -> None:
    database_path = tmp_path / "applied-payout-migration.db"

    previous = run_alembic(database_path, "upgrade", PREVIOUS_REVISION)
    assert previous.returncode == 0, previous.stderr

    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            "INSERT INTO reporting_months "
            "(year, month, period_start, period_end, snapshot_date, status, source, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                2031,
                5,
                "2031-05-01",
                "2031-05-31",
                "2031-05-31",
                "draft",
                "manual",
                "2031-05-31 00:00:00",
                "2031-05-31 00:00:00",
            ),
        )
        connection.execute(
            "INSERT INTO accounts (name, account_type, status, include_in_capital, include_in_returns) "
            "VALUES (?, ?, ?, ?, ?)",
            ("Synthetic Broker", "brokerage", "active", 1, 1),
        )
        connection.execute(
            "INSERT INTO instruments "
            "(name, instrument_type, isin, ticker, moex_secid, currency, is_active, manual_price_allowed) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("Synthetic Bond", "bond", None, None, None, "RUB", 1, 1),
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
                "3.125000",
                10_000,
                25_000,
                78_125,
                31_250,
                46_875,
                "2031-05-15",
                "manual",
                0,
                "synthetic snapshot",
                "2031-05-15 00:00:00",
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
                "2031-06-15",
                110_000,
                13_000,
                97_000,
                "RUB",
                "synthetic calendar",
                "2031-05-31",
                "v1",
                0,
                0,
                "owner entered",
            ),
        )
        connection.commit()
        month_before = connection.execute(
            "SELECT year, month, status, snapshot_date FROM reporting_months WHERE id = 1"
        ).fetchone()
        snapshot_before = connection.execute(
            "SELECT quantity, market_price_per_unit_kopecks, notes FROM position_snapshots WHERE id = 1"
        ).fetchone()
        flow_before = connection.execute(
            "SELECT flow_type, expected_date, gross_amount_kopecks, expected_tax_amount_kopecks, "
            "expected_net_amount_kopecks, source, notes FROM expected_cash_flows WHERE id = 1"
        ).fetchone()
    finally:
        connection.close()

    migrated = run_alembic(database_path, "upgrade", "head")
    assert migrated.returncode == 0, migrated.stderr
    assert revision_rows(database_path) == [REVISION]

    connection = sqlite3.connect(database_path)
    try:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert "applied_provider_payouts" in tables
        assert "applied_payout_revisions" in tables
        assert "applied_payout_reconciliations" in tables
        assert connection.execute("SELECT COUNT(*) FROM applied_provider_payouts").fetchone() == (
            0,
        )
        assert connection.execute("SELECT COUNT(*) FROM applied_payout_revisions").fetchone() == (
            0,
        )
        assert connection.execute(
            "SELECT COUNT(*) FROM applied_payout_reconciliations"
        ).fetchone() == (0,)
        assert (
            connection.execute(
                "SELECT year, month, status, snapshot_date FROM reporting_months WHERE id = 1"
            ).fetchone()
            == month_before
        )
        assert (
            connection.execute(
                "SELECT quantity, market_price_per_unit_kopecks, notes FROM position_snapshots WHERE id = 1"
            ).fetchone()
            == snapshot_before
        )
        assert (
            connection.execute(
                "SELECT flow_type, expected_date, gross_amount_kopecks, expected_tax_amount_kopecks, "
                "expected_net_amount_kopecks, source, notes FROM expected_cash_flows WHERE id = 1"
            ).fetchone()
            == flow_before
        )
        payout_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'applied_provider_payouts'"
        ).fetchone()[0]
        revision_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'applied_payout_revisions'"
        ).fetchone()[0]
        for blob in (payout_sql, revision_sql):
            assert "raw_payload" not in blob
            assert "token" not in blob
            assert "response_body" not in blob
        indexes = list(connection.execute("PRAGMA index_list(applied_provider_payouts)"))
        index_names = {row[1] for row in indexes}
        assert "ix_applied_provider_payouts_month" in index_names
        assert any(row[2] for row in indexes)
        revision_fk_actions = {
            row[3]: row[6]
            for row in connection.execute("PRAGMA foreign_key_list(applied_payout_revisions)")
        }
        assert revision_fk_actions["applied_payout_id"] == "RESTRICT"
        reconciliation_fk_actions = {
            row[3]: row[6]
            for row in connection.execute("PRAGMA foreign_key_list(applied_payout_reconciliations)")
        }
        assert reconciliation_fk_actions["expected_cash_flow_id"] == "CASCADE"
    finally:
        connection.close()

    downgraded = run_alembic(database_path, "downgrade", PREVIOUS_REVISION)
    assert downgraded.returncode == 0, downgraded.stderr
    assert revision_rows(database_path) == [PREVIOUS_REVISION]

    connection = sqlite3.connect(database_path)
    try:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert "applied_provider_payouts" not in tables
        assert "applied_payout_revisions" not in tables
        assert "applied_payout_reconciliations" not in tables
        assert (
            connection.execute(
                "SELECT flow_type, expected_date, gross_amount_kopecks, expected_tax_amount_kopecks, "
                "expected_net_amount_kopecks, source, notes FROM expected_cash_flows WHERE id = 1"
            ).fetchone()
            == flow_before
        )
        assert (
            connection.execute(
                "SELECT quantity, market_price_per_unit_kopecks, notes FROM position_snapshots WHERE id = 1"
            ).fetchone()
            == snapshot_before
        )
    finally:
        connection.close()


def test_applied_payout_migration_module_has_no_network_imports() -> None:
    source = (
        BACKEND_ROOT / "migrations" / "versions" / "0027_applied_provider_payouts.py"
    ).read_text(encoding="utf-8")
    assert "httpx" not in source
    assert "urllib" not in source
    assert "socket" not in source
    assert "TInvestClient" not in source
    assert "fetch_payouts" not in source


def test_applied_statement_migration_is_additive_and_preserves_cash_flows(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "applied-statement-migration.db"

    previous = run_alembic(database_path, "upgrade", STATEMENT_PREVIOUS_REVISION)
    assert previous.returncode == 0, previous.stderr

    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            "INSERT INTO reporting_months "
            "(year, month, period_start, period_end, snapshot_date, status, source, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                2026,
                1,
                "2026-01-01",
                "2026-01-31",
                "2026-01-31",
                "draft",
                "manual",
                "2026-01-31 00:00:00",
                "2026-01-31 00:00:00",
            ),
        )
        connection.execute(
            "INSERT INTO accounts (name, account_type, status, include_in_capital, include_in_returns) "
            "VALUES (?, ?, ?, ?, ?)",
            ("Synthetic Broker", "brokerage", "active", 1, 1),
        )
        connection.execute(
            "INSERT INTO instruments "
            "(name, instrument_type, isin, ticker, moex_secid, currency, is_active, manual_price_allowed) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("Synthetic Equity", "stock", "RU000SYN00001", None, None, "RUB", 1, 1),
        )
        connection.execute(
            "INSERT INTO investment_cash_flows "
            "(reporting_month_id, account_id, instrument_id, flow_type, event_date, "
            "gross_amount_kopecks, tax_amount_kopecks, commission_amount_kopecks, "
            "net_amount_kopecks, currency, source, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                1,
                1,
                1,
                "dividend",
                "2026-01-20",
                1150,
                150,
                0,
                1000,
                "RUB",
                "manual",
                "owner entered",
            ),
        )
        connection.commit()
        flow_before = connection.execute(
            "SELECT flow_type, event_date, gross_amount_kopecks, tax_amount_kopecks, "
            "commission_amount_kopecks, net_amount_kopecks, source, notes "
            "FROM investment_cash_flows WHERE id = 1"
        ).fetchone()
    finally:
        connection.close()

    migrated = run_alembic(database_path, "upgrade", "head")
    assert migrated.returncode == 0, migrated.stderr
    assert revision_rows(database_path) == [REVISION]

    connection = sqlite3.connect(database_path)
    try:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert "applied_statement_events" in tables
        assert "applied_statement_event_revisions" in tables
        assert connection.execute("SELECT COUNT(*) FROM applied_statement_events").fetchone() == (
            0,
        )
        assert connection.execute(
            "SELECT COUNT(*) FROM applied_statement_event_revisions"
        ).fetchone() == (0,)
        assert (
            connection.execute(
                "SELECT flow_type, event_date, gross_amount_kopecks, tax_amount_kopecks, "
                "commission_amount_kopecks, net_amount_kopecks, source, notes "
                "FROM investment_cash_flows WHERE id = 1"
            ).fetchone()
            == flow_before
        )
        event_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'applied_statement_events'"
        ).fetchone()[0]
        revision_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' "
            "AND name = 'applied_statement_event_revisions'"
        ).fetchone()[0]
        for blob in (event_sql, revision_sql):
            lowered = blob.lower()
            assert "raw_payload" not in lowered
            assert "pdf_bytes" not in lowered
            assert "beneficiary" not in lowered
            assert "provider_account" not in lowered
            assert "extracted_text" not in lowered
            assert "depo_account" not in lowered
        indexes = list(connection.execute("PRAGMA index_list(applied_statement_events)"))
        index_names = {row[1] for row in indexes}
        assert "ix_applied_statement_events_account" in index_names
        assert any(row[2] for row in indexes)
        revision_fk_actions = {
            row[3]: row[6]
            for row in connection.execute(
                "PRAGMA foreign_key_list(applied_statement_event_revisions)"
            )
        }
        assert revision_fk_actions["applied_statement_event_id"] == "RESTRICT"
    finally:
        connection.close()

    downgraded = run_alembic(database_path, "downgrade", STATEMENT_PREVIOUS_REVISION)
    assert downgraded.returncode == 0, downgraded.stderr
    assert revision_rows(database_path) == [STATEMENT_PREVIOUS_REVISION]

    connection = sqlite3.connect(database_path)
    try:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert "applied_statement_events" not in tables
        assert "applied_statement_event_revisions" not in tables
        assert (
            connection.execute(
                "SELECT flow_type, event_date, gross_amount_kopecks, tax_amount_kopecks, "
                "commission_amount_kopecks, net_amount_kopecks, source, notes "
                "FROM investment_cash_flows WHERE id = 1"
            ).fetchone()
            == flow_before
        )
    finally:
        connection.close()


def test_applied_statement_migration_module_has_no_network_or_pdf_imports() -> None:
    source = (
        BACKEND_ROOT / "migrations" / "versions" / "0028_applied_statement_events.py"
    ).read_text(encoding="utf-8")
    assert "httpx" not in source
    assert "urllib" not in source
    assert "socket" not in source
    assert "pypdf" not in source
    assert "preview_income_report" not in source
    assert "ClientOperationEntity" not in source


def test_statement_retract_migration_module_has_no_network_or_pdf_imports() -> None:
    source = (
        BACKEND_ROOT / "migrations" / "versions" / "0029_statement_event_retract.py"
    ).read_text(encoding="utf-8")
    assert "httpx" not in source
    assert "urllib" not in source
    assert "socket" not in source
    assert "pypdf" not in source
    assert "preview_income_report" not in source
    assert "ClientOperationEntity" not in source


def test_statement_retract_migration_preserves_v061_active_events(tmp_path: Path) -> None:
    database_path = tmp_path / "statement-retract-upgrade.db"
    digest = "a" * 64
    previous = run_alembic(database_path, "upgrade", "0028_applied_statement_events")
    assert previous.returncode == 0, previous.stderr

    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            "INSERT INTO reporting_months "
            "(year, month, period_start, period_end, snapshot_date, status, source, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                2026,
                1,
                "2026-01-01",
                "2026-01-31",
                "2026-01-31",
                "draft",
                "manual",
                "2026-01-31 00:00:00",
                "2026-01-31 00:00:00",
            ),
        )
        connection.execute(
            "INSERT INTO accounts (name, account_type, status, include_in_capital, "
            "include_in_returns) VALUES (?, ?, ?, ?, ?)",
            ("Synthetic Broker", "brokerage", "active", 1, 1),
        )
        connection.execute(
            "INSERT INTO instruments "
            "(name, instrument_type, isin, ticker, moex_secid, currency, is_active, "
            "manual_price_allowed) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("Synthetic Equity", "stock", "RU000SYN00001", None, None, "RUB", 1, 1),
        )
        connection.execute(
            "INSERT INTO investment_cash_flows "
            "(reporting_month_id, account_id, instrument_id, flow_type, event_date, "
            "gross_amount_kopecks, tax_amount_kopecks, commission_amount_kopecks, "
            "net_amount_kopecks, currency, source, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                1,
                1,
                1,
                "dividend",
                "2026-01-20",
                1150,
                150,
                0,
                1000,
                "RUB",
                "alfa_depository_income_report",
                None,
            ),
        )
        connection.execute(
            "INSERT INTO applied_statement_events "
            "(provider, account_id, instrument_id, event_kind, isin, record_date, "
            "natural_identity, material_fingerprint, investment_cash_flow_id, "
            "document_sha256, link_mode, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "alfa_depository_income_report",
                1,
                1,
                "dividend",
                "RU000SYN00001",
                "2026-01-15",
                "1|dividend|RU000SYN00001|2026-01-15",
                digest,
                1,
                digest,
                "statement_created",
                "2026-01-20 00:00:00",
                "2026-01-20 00:00:00",
            ),
        )
        connection.execute(
            "INSERT INTO applied_statement_event_revisions "
            "(applied_statement_event_id, revision_kind, document_sha256, "
            "natural_identity, material_fingerprint, account_id, instrument_id, "
            "event_kind, isin, record_date, event_date, quantity, per_unit, "
            "gross_amount_kopecks, gross_currency, tax_available, tax_amount_kopecks, "
            "tax_rate, net_amount_kopecks, net_currency, applied_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                1,
                "apply",
                digest,
                "1|dividend|RU000SYN00001|2026-01-15",
                digest,
                1,
                1,
                "dividend",
                "RU000SYN00001",
                "2026-01-15",
                "2026-01-20",
                "1.00000000",
                "11.50000000",
                1150,
                "RUB",
                1,
                150,
                "0.13000000",
                1000,
                "RUB",
                "2026-01-20 00:00:00",
            ),
        )
        connection.commit()
        event_before = connection.execute(
            "SELECT provider, account_id, instrument_id, event_kind, isin, record_date, "
            "natural_identity, material_fingerprint, investment_cash_flow_id, "
            "document_sha256, link_mode FROM applied_statement_events WHERE id = 1"
        ).fetchone()
        revision_before = connection.execute(
            "SELECT revision_kind, natural_identity, gross_amount_kopecks, "
            "net_amount_kopecks FROM applied_statement_event_revisions WHERE id = 1"
        ).fetchone()
        flow_before = connection.execute(
            "SELECT net_amount_kopecks, source FROM investment_cash_flows WHERE id = 1"
        ).fetchone()
    finally:
        connection.close()

    migrated = run_alembic(database_path, "upgrade", "head")
    assert migrated.returncode == 0, migrated.stderr
    assert revision_rows(database_path) == [REVISION]

    connection = sqlite3.connect(database_path)
    try:
        event_columns = {
            row[1]: row for row in connection.execute("PRAGMA table_info(applied_statement_events)")
        }
        assert event_columns["status"][3] == 1
        assert event_columns["investment_cash_flow_id"][3] == 0
        assert event_columns["retracted_at"][3] == 0
        event_after = connection.execute(
            "SELECT provider, account_id, instrument_id, event_kind, isin, record_date, "
            "natural_identity, material_fingerprint, investment_cash_flow_id, "
            "document_sha256, link_mode, status, retracted_at "
            "FROM applied_statement_events WHERE id = 1"
        ).fetchone()
        assert event_after[:11] == event_before
        assert event_after[11] == "active"
        assert event_after[12] is None
        assert (
            connection.execute(
                "SELECT revision_kind, natural_identity, gross_amount_kopecks, "
                "net_amount_kopecks FROM applied_statement_event_revisions WHERE id = 1"
            ).fetchone()
            == revision_before
        )
        assert (
            connection.execute(
                "SELECT net_amount_kopecks, source FROM investment_cash_flows WHERE id = 1"
            ).fetchone()
            == flow_before
        )
        index_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'uq_applied_statement_events_active_identity'"
        ).fetchone()
        assert index_sql is not None
        assert "status = 'active'" in index_sql[0]
        revision_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' "
            "AND name = 'applied_statement_event_revisions'"
        ).fetchone()[0]
        assert "retract" in revision_sql
    finally:
        connection.close()


def test_broker_identity_mappings_migration_is_additive_and_empty(tmp_path: Path) -> None:
    database_path = tmp_path / "broker-identity-mappings.db"
    previous = run_alembic(database_path, "upgrade", "0034_observed_valuation_boundaries")
    assert previous.returncode == 0, previous.stderr
    connection = sqlite3.connect(database_path)
    try:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert "broker_identity_mappings" not in tables
    finally:
        connection.close()

    upgraded = run_alembic(database_path, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr
    assert revision_rows(database_path) == [REVISION]
    connection = sqlite3.connect(database_path)
    try:
        assert [
            row[1] for row in connection.execute("PRAGMA table_info(broker_identity_mappings)")
        ] == [
            "id",
            "provider",
            "subject_kind",
            "provider_identity",
            "hermes_account_id",
            "hermes_instrument_id",
            "status",
            "observed_isin",
            "confirmed_at",
            "source_as_of",
            "captured_at",
            "predecessor_mapping_id",
            "successor_mapping_id",
            "revoked_at",
            "revoke_reason",
        ]
        assert connection.execute("SELECT COUNT(*) FROM broker_identity_mappings").fetchone() == (
            0,
        )
        index_sql = " ".join(
            row[0]
            for row in connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'index' "
                "AND tbl_name = 'broker_identity_mappings' AND sql IS NOT NULL"
            )
        )
        assert "uq_broker_identity_mappings_effective_forward" in index_sql
        assert "uq_broker_identity_mappings_effective_instrument_reverse" in index_sql
        assert "status = 'effective'" in index_sql
    finally:
        connection.close()

    downgraded = run_alembic(database_path, "downgrade", "0034_observed_valuation_boundaries")
    assert downgraded.returncode == 0, downgraded.stderr
    connection = sqlite3.connect(database_path)
    try:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert "broker_identity_mappings" not in tables
    finally:
        connection.close()


def test_broker_baseline_provenance_migration_is_additive_and_empty(tmp_path: Path) -> None:
    database_path = tmp_path / "broker-baseline-provenance.db"
    previous = run_alembic(database_path, "upgrade", "0035_broker_identity_mappings")
    assert previous.returncode == 0, previous.stderr
    connection = sqlite3.connect(database_path)
    try:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert "broker_baseline_applies" not in tables
        assert "broker_baseline_apply_items" not in tables
    finally:
        connection.close()

    upgraded = run_alembic(database_path, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr
    assert revision_rows(database_path) == [REVISION]
    connection = sqlite3.connect(database_path)
    try:
        assert [
            row[1] for row in connection.execute("PRAGMA table_info(broker_baseline_applies)")
        ] == [
            "id",
            "provider",
            "reporting_month_id",
            "baseline_date",
            "source_as_of",
            "captured_at",
            "confirmed_at",
            "compatibility_fingerprint",
            "apply_fingerprint",
        ]
        assert [
            row[1] for row in connection.execute("PRAGMA table_info(broker_baseline_apply_items)")
        ] == [
            "id",
            "reporting_month_id",
            "baseline_apply_id",
            "position_snapshot_id",
            "action",
            "quantity",
        ]
        assert connection.execute("SELECT COUNT(*) FROM broker_baseline_applies").fetchone() == (0,)
        assert connection.execute(
            "SELECT COUNT(*) FROM broker_baseline_apply_items"
        ).fetchone() == (0,)
        apply_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'broker_baseline_applies'"
        ).fetchone()[0]
        item_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' "
            "AND name = 'broker_baseline_apply_items'"
        ).fetchone()[0]
        assert "Price" not in apply_sql
        assert "UchPrice" not in apply_sql
        assert "NKD" not in apply_sql
        assert "ticker" not in item_sql.lower()
        assert "REFERENCES position_snapshots" not in item_sql
        item_fks = list(connection.execute("PRAGMA foreign_key_list(broker_baseline_apply_items)"))
        assert {row[2] for row in item_fks} == {"reporting_months", "broker_baseline_applies"}
    finally:
        connection.close()

    downgraded = run_alembic(database_path, "downgrade", "0035_broker_identity_mappings")
    assert downgraded.returncode == 0, downgraded.stderr
    connection = sqlite3.connect(database_path)
    try:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert "broker_baseline_applies" not in tables
        assert "broker_baseline_apply_items" not in tables
        assert "broker_identity_mappings" in tables
    finally:
        connection.close()
