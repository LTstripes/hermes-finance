"""Synthetic upgrade proof with an existing payout/revision FK graph."""

import sqlite3
from pathlib import Path

import pytest
from _migration_helpers import REVISION, revision_rows, run_alembic


def test_upgrade_preserves_existing_payout_graph(tmp_path: Path) -> None:
    path = tmp_path / "payout-upgrade.db"
    before = run_alembic(path, "upgrade", "0041_debt_linked_account")
    assert before.returncode == 0, before.stderr
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "INSERT INTO reporting_months (id, year, month, period_start, period_end, "
            "snapshot_date, status, source, created_at, updated_at) VALUES "
            "(1, 2030, 5, '2030-05-01', '2030-05-31', '2030-05-12', 'draft', "
            "'manual', '2030-05-12', '2030-05-12')"
        )
        connection.execute(
            "INSERT INTO accounts (id, name, account_type, status, include_in_capital, "
            "include_in_returns) VALUES (1, 'Synthetic Broker', 'brokerage', 'active', 1, 1)"
        )
        connection.execute(
            "INSERT INTO instruments (id, name, instrument_type, currency, is_active, "
            "manual_price_allowed) VALUES (1, 'Synthetic Bond', 'bond', 'RUB', 1, 1)"
        )
        connection.execute(
            "INSERT INTO position_snapshots (id, reporting_month_id, account_id, "
            "instrument_id, quantity, average_cost_per_unit_kopecks, "
            "market_price_per_unit_kopecks, market_value_kopecks, cost_basis_kopecks, "
            "unrealized_result_kopecks, price_date, price_source, manual_adjustment, "
            "updated_at) VALUES (1, 1, 1, 1, 3, 10000, 10100, 30300, 30000, 300, "
            "'2030-05-12', 'manual', 0, '2030-05-12')"
        )
        connection.execute(
            "INSERT INTO applied_provider_payouts (id, reporting_month_id, account_id, "
            "instrument_id, source_position_snapshot_id, provider, provider_instrument_uid, "
            "event_kind, identity_key, lifecycle, payment_date, quantity, per_unit_amount, "
            "total_amount_kopecks, currency, amount_basis, is_approximate, first_applied_at) "
            "VALUES (1, 1, 1, 1, 1, 't_invest', 'synthetic-uid', 'coupon', 'n:1', "
            "'active', '2030-06-15', 3, '35.4', 10620, 'RUB', 'provider_announced', 1, "
            "'2030-05-12')"
        )
        connection.execute(
            "INSERT INTO applied_payout_revisions (id, applied_payout_id, revision_kind, "
            "source_position_snapshot_id, provider, provider_instrument_uid, event_kind, "
            "identity_key, lifecycle, payment_date, quantity, per_unit_amount, "
            "total_amount_kopecks, currency, amount_basis, is_approximate, fetched_at, "
            "applied_at) VALUES (1, 1, 'apply', 1, 't_invest', 'synthetic-uid', "
            "'coupon', 'n:1', 'active', '2030-06-15', 3, '35.4', 10620, 'RUB', "
            "'provider_announced', 1, '2030-05-12', '2030-05-12')"
        )
        connection.commit()
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()

    upgraded = run_alembic(path, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr
    assert revision_rows(path) == [REVISION]
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute(
            "SELECT reporting_month_id, archived_from_period FROM applied_provider_payouts"
        ).fetchone() == (1, None)
        assert connection.execute(
            "SELECT source_position_snapshot_id FROM applied_payout_revisions"
        ).fetchone() == (1,)
    finally:
        connection.close()

    downgraded = run_alembic(path, "downgrade", "0041_debt_linked_account")
    assert downgraded.returncode == 0, downgraded.stderr
    assert revision_rows(path) == ["0041_debt_linked_account"]
    reupgraded = run_alembic(path, "upgrade", "0042_payout_provenance_lifecycle")
    assert reupgraded.returncode == 0, reupgraded.stderr
    assert revision_rows(path) == ["0042_payout_provenance_lifecycle"]

    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "INSERT INTO expected_cash_flows (id, reporting_month_id, account_id, "
            "instrument_id, flow_type, expected_date, gross_amount_kopecks, "
            "expected_tax_amount_kopecks, expected_net_amount_kopecks, source, "
            "source_as_of_date, forecast_version) VALUES "
            "(1, 1, 1, 1, 'coupon', '2030-06-14', 110000, 13000, 97000, "
            "'synthetic calendar', '2030-05-12', 'v1')"
        )
        connection.execute(
            "INSERT INTO applied_payout_reconciliations "
            "(id, applied_payout_id, expected_cash_flow_id, counting_decision, created_at) "
            "VALUES (1, 1, 1, 'count_manual', '2030-05-12')"
        )
        connection.execute(
            "UPDATE applied_provider_payouts SET reporting_month_id=NULL, "
            "archived_from_period='2030-05' WHERE id=1"
        )
        connection.execute(
            "UPDATE position_snapshots SET reporting_month_id=NULL, "
            "archived_from_period='2030-05' WHERE id=1"
        )
        connection.commit()
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()
    migrated = run_alembic(path, "upgrade", "head")
    assert migrated.returncode == 0, migrated.stderr
    assert revision_rows(path) == [REVISION]
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        assert connection.execute(
            "SELECT expected_cash_flow_id, archived_from_period "
            "FROM applied_payout_reconciliations WHERE id=1"
        ).fetchone() == (1, "2030-05")
        assert any(
            row[2] == "expected_cash_flows" and row[6] == "RESTRICT"
            for row in connection.execute("PRAGMA foreign_key_list(applied_payout_reconciliations)")
        )
        connection.execute(
            "INSERT INTO position_snapshots (id, reporting_month_id, account_id, "
            "instrument_id, quantity, average_cost_per_unit_kopecks, "
            "market_price_per_unit_kopecks, market_value_kopecks, cost_basis_kopecks, "
            "unrealized_result_kopecks, price_date, price_source, manual_adjustment, "
            "updated_at) VALUES (2, 1, 1, 1, 2, 10000, 10100, 20200, 20000, 200, "
            "'2030-05-12', 'manual', 0, '2030-05-12')"
        )
        connection.execute(
            "INSERT INTO applied_provider_payouts (id, reporting_month_id, account_id, "
            "instrument_id, source_position_snapshot_id, provider, provider_instrument_uid, "
            "event_kind, identity_key, lifecycle, payment_date, quantity, per_unit_amount, "
            "total_amount_kopecks, currency, amount_basis, is_approximate, first_applied_at) "
            "VALUES (2, 1, 1, 1, 2, 't_invest', 'synthetic-uid', 'coupon', 'n:1', "
            "'active', '2030-06-15', 2, '35.4', 7080, 'RUB', 'provider_announced', 1, "
            "'2030-05-12')"
        )
        connection.execute(
            "INSERT INTO applied_payout_reconciliations "
            "(id, applied_payout_id, expected_cash_flow_id, counting_decision, created_at) "
            "VALUES (2, 2, 1, 'count_manual', '2030-05-12')"
        )
        assert connection.execute(
            "SELECT id, archived_from_period FROM applied_payout_reconciliations ORDER BY id"
        ).fetchall() == [(1, "2030-05"), (2, None)]
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM expected_cash_flows WHERE id=1")
        connection.commit()
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()
    blocked = run_alembic(path, "downgrade", "0042_payout_provenance_lifecycle")
    assert blocked.returncode != 0
    assert "cannot downgrade payout reconciliation with historical links" in blocked.stderr
    assert revision_rows(path) == [REVISION]
