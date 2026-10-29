import sqlite3
from datetime import date
from pathlib import Path

from _migration_helpers import (
    PREVIOUS_REVISION,
    REVISION,
    STATEMENT_PREVIOUS_REVISION,
    revision_rows,
    run_alembic,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_source_return_proof_upgrade_is_empty_preserves_0064_and_refuses_history_loss(tmp_path):
    from test_source_monthly_returns_service import save_service_month

    from hermes_finance.database import create_database

    path = tmp_path / "synthetic-proof-migration.db"
    previous = "0064_month_template_provenance"
    assert run_alembic(path, "upgrade", previous).returncode == 0
    database = create_database(path)
    save_service_month(database)
    database.engine.dispose()

    def existing_rows():
        with sqlite3.connect(path) as connection:
            return {
                name: connection.execute(f'SELECT * FROM "{name}" ORDER BY rowid').fetchall()
                for (name,) in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT IN ('alembic_version','source_return_proofs','source_return_proof_dependencies')"
                )
            }

    before = existing_rows()
    assert run_alembic(path, "upgrade", "head").returncode == 0
    assert revision_rows(path) == [REVISION]
    assert existing_rows() == before
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM source_return_proofs").fetchone() == (0,)
        assert connection.execute(
            "SELECT COUNT(*) FROM source_return_proof_dependencies"
        ).fetchone() == (0,)
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()
    assert run_alembic(path, "downgrade", previous).returncode == 0
    assert existing_rows() == before
    assert run_alembic(path, "upgrade", "head").returncode == 0
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO source_return_proof_dependencies(token) VALUES (?)", ("1" * 64,)
        )
    assert run_alembic(path, "downgrade", previous).returncode == 0
    assert existing_rows() == before
    assert run_alembic(path, "upgrade", "head").returncode == 0
    from test_source_monthly_returns_service import proof_confirm, proof_preview

    database = create_database(path)
    _, _, preview = proof_preview(database)
    proof_confirm(database, preview)
    database.engine.dispose()
    before_history = existing_rows()
    failed = run_alembic(path, "downgrade", previous)
    assert failed.returncode != 0 and "populated source return proof history" in failed.stderr
    assert revision_rows(path) == [REVISION]
    assert existing_rows() == before_history


def test_month_template_provenance_preserves_unknown_legacy_and_windows_recovery(tmp_path):
    from test_r13_00_release_verification import _backup, _integrity, _snapshot

    from hermes_finance.database import create_database
    from hermes_finance.persistence import ExpenseEntry, IncomeEntry, SavingAllocation
    from hermes_finance.services.close_readiness import build_close_readiness
    from hermes_finance.services.expenses import update_expense_entry, update_saving_allocation
    from hermes_finance.services.incomes import update_income_entry
    from hermes_finance.services.reporting_months import create_reporting_month

    path = tmp_path / "synthetic-provenance.db"
    previous = "0063_intentional_empty_close"
    assert run_alembic(path, "upgrade", previous).returncode == 0
    database = create_database(path)
    with database.session_factory() as session:
        month = create_reporting_month(session, year=2030, month=1, snapshot_date=date(2030, 1, 31))
        month_id = month.id
    database.engine.dispose()
    # Pre-provenance schema cannot prove whether these are actuals or copies.
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO income_entries(reporting_month_id,income_type,name,"
            "gross_amount_kopecks,tax_amount_kopecks,net_amount_kopecks) VALUES (?, 'salary','Zero',0,0,0)",
            (month_id,),
        )
        connection.execute(
            "INSERT INTO expense_entries(reporting_month_id,category,amount_kopecks,expense_type) "
            "VALUES (?, 'Zero',0,'mandatory')",
            (month_id,),
        )
        connection.execute(
            "INSERT INTO saving_allocations(reporting_month_id,destination,amount_kopecks) "
            "VALUES (?, 'Zero',0)",
            (month_id,),
        )
        connection.commit()
        before = _snapshot(connection)
    original = tmp_path / "synthetic-old-backup.db"
    _backup(path, original)
    for _ in range(2):
        upgraded = run_alembic(path, "upgrade", "head")
        assert upgraded.returncode == 0, upgraded.stderr
        with sqlite3.connect(path) as connection:
            _integrity(connection)
            after = _snapshot(connection)
            for table in ("income_entries", "expense_entries", "saving_allocations"):
                assert connection.execute(f"SELECT actual_fact_origin FROM {table}").fetchall() == [
                    (None,)
                ]
            for table, (columns, rows) in before.items():
                current_columns, current_rows = after[table]
                indices = [current_columns.index(column) for column in columns]
                assert [tuple(row[i] for i in indices) for row in current_rows] == rows
        assert run_alembic(path, "downgrade", previous).returncode == 0
        with sqlite3.connect(path) as connection:
            assert _snapshot(connection) == before
    assert run_alembic(path, "upgrade", "head").returncode == 0
    database = create_database(path)
    with database.session_factory() as session:
        assert not build_close_readiness(session, month_id, today=date(2030, 1, 31)).can_close
        for model, update_row, changes in (
            (IncomeEntry, update_income_entry, {"net_amount": "0.00"}),
            (ExpenseEntry, update_expense_entry, {"amount": "0.00"}),
            (SavingAllocation, update_saving_allocation, {"amount": "0.00"}),
        ):
            row = session.query(model).one()
            update_row(session, row.id, **changes)
            assert row.actual_fact_origin == "saved_actual_v1"
        assert build_close_readiness(session, month_id, today=date(2030, 1, 31)).can_close
    database.engine.dispose()
    refused = run_alembic(path, "downgrade", previous)
    assert refused.returncode != 0 and "cannot downgrade populated" in refused.stderr
    assert revision_rows(path) == [REVISION]
    with sqlite3.connect(path) as connection:
        committed = _snapshot(connection)
    backup = tmp_path / "synthetic-provenance-backup.db"
    _backup(path, backup)
    with sqlite3.connect(backup) as connection:
        _integrity(connection)
        assert _snapshot(connection) == committed
    recovered = tmp_path / "synthetic-provenance-forward.db"
    _backup(original, recovered)
    assert run_alembic(recovered, "upgrade", "head").returncode == 0
    with sqlite3.connect(recovered) as connection:
        assert connection.execute("SELECT actual_fact_origin FROM income_entries").fetchall() == [
            (None,)
        ]
    with sqlite3.connect(path) as connection:
        assert _snapshot(connection) == committed


def test_intentional_empty_close_migration_audit_and_windows_recovery(tmp_path):
    import pytest
    from test_r13_00_release_verification import _backup, _integrity, _snapshot

    from hermes_finance.database import create_database
    from hermes_finance.services.close_readiness import build_close_readiness
    from hermes_finance.services.intentional_empty_close import (
        IntentionalEmptyCloseCommand,
        close_intentionally_empty_month,
    )
    from hermes_finance.services.reporting_months import create_reporting_month

    path = tmp_path / "synthetic-empty-close-migration.db"
    previous = "0062_security_reg_isin_mappings"
    result = run_alembic(path, "upgrade", previous)
    assert result.returncode == 0, result.stderr
    database = create_database(path)
    with database.session_factory() as session:
        month = create_reporting_month(session, year=2030, month=1, snapshot_date=date(2030, 1, 31))
        month_id = month.id
    database.engine.dispose()
    with sqlite3.connect(path) as connection:
        before = _snapshot(connection)
    original_backup = tmp_path / "synthetic-0062-backup.db"
    _backup(path, original_backup)
    for _ in range(2):
        upgraded = run_alembic(path, "upgrade", "0063_intentional_empty_close")
        assert upgraded.returncode == 0, upgraded.stderr
        with sqlite3.connect(path) as connection:
            _integrity(connection)
            after = _snapshot(connection)
            assert {k: after[k] for k in before} == before
            assert set(after) - set(before) == {"intentional_empty_close_receipts"}
            assert after["intentional_empty_close_receipts"][1] == []
        downgraded = run_alembic(path, "downgrade", previous)
        assert downgraded.returncode == 0, downgraded.stderr
        with sqlite3.connect(path) as connection:
            assert _snapshot(connection) == before
    # Current readers require the current schema; the loop above independently
    # probes the unchanged 0063 upgrade/downgrade contract.
    assert run_alembic(path, "upgrade", "head").returncode == 0
    database = create_database(path)
    with database.session_factory() as session:
        option = build_close_readiness(
            session, month_id, today=date(2030, 1, 31)
        ).intentional_empty_close
        command = IntentionalEmptyCloseCommand.model_validate(
            {k: v for k, v in option.items() if k != "eligible"}
            | {"request_id": "migration-close", "reason": "Synthetic intentional empty period"}
        )
        close_intentionally_empty_month(session, month_id, command)
    database.engine.dispose()
    with sqlite3.connect(path) as connection:
        committed = _snapshot(connection)
        for sql in [
            "UPDATE intentional_empty_close_receipts SET reason='changed'",
            "DELETE FROM intentional_empty_close_receipts",
        ]:
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                connection.execute(sql)
            connection.rollback()
    # Origins are all NULL here. Preserve the audit guard for the whole
    # downgrade chain, including every provenance column.
    with sqlite3.connect(path) as connection:
        for table in ("income_entries", "expense_entries", "saving_allocations"):
            assert "actual_fact_origin" in [
                row[1] for row in connection.execute(f"PRAGMA table_info({table})")
            ]
    refused = run_alembic(path, "downgrade", previous)
    assert refused.returncode != 0 and "cannot downgrade populated" in refused.stderr
    assert revision_rows(path) == [REVISION]
    current_backup = tmp_path / "synthetic-current-audit-backup.db"
    _backup(path, current_backup)
    with sqlite3.connect(current_backup) as connection:
        assert _snapshot(connection) == committed
    # Existing 0062 snapshots remain an old code/data pair; forward recovery
    # uses a fresh independent target, never an in-place cross-schema restore.
    recovered = tmp_path / "synthetic-forward-recovery.db"
    _backup(original_backup, recovered)
    assert run_alembic(recovered, "upgrade", "head").returncode == 0
    with sqlite3.connect(recovered) as connection:
        _integrity(connection)
        assert connection.execute("SELECT status FROM reporting_months").fetchall() == [("draft",)]
        assert connection.execute(
            "SELECT count(*) FROM intentional_empty_close_receipts"
        ).fetchone() == (0,)
    with sqlite3.connect(path) as connection:
        assert _snapshot(connection) == committed


def test_security_reg_isin_mapping_upgrade_downgrade_preserves_existing_tables(tmp_path):
    import pytest
    from test_statement_import_mybroker import FILENAME, fixture

    from hermes_finance.database import create_database
    from hermes_finance.services.source_intake import save_intake

    path = tmp_path / "synthetic-reg-isin-migration.db"
    previous = "0061_money_instrument_links"
    result = run_alembic(path, "upgrade", "head")
    assert result.returncode == 0, result.stderr
    database = create_database(path)
    with database.session_factory() as session:
        save_intake(
            session, document=fixture(), filename=FILENAME, request_id="synthetic-crosswalk"
        )
    database.engine.dispose()
    result = run_alembic(path, "downgrade", previous)
    assert result.returncode == 0, result.stderr
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE source_intake_money_classifications SET classification='dividend',"
            "origin='user_choice',status='confirmed',updated_at='2030-01-02' "
            "WHERE id=(SELECT MIN(id) FROM source_intake_money_classifications)"
        )
        connection.commit()
        # Capture all pre-existing tables, including journal and manual choices.
        names = [
            r[0]
            for r in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name != 'alembic_version'"
            )
        ]
        before = {
            name: connection.execute(f'SELECT * FROM "{name}" ORDER BY rowid').fetchall()
            for name in names
        }
    for _ in range(2):
        result = run_alembic(path, "upgrade", "head")
        assert result.returncode == 0, result.stderr
        assert revision_rows(path) == [REVISION]
        with sqlite3.connect(path) as connection:
            assert connection.execute("SELECT * FROM security_reg_isin_mappings").fetchall() == []
            insert = (
                "INSERT INTO security_reg_isin_mappings(reg_number,isin,note,created_at,updated_at) "
                "VALUES (?,?,NULL,'2030-01-01','2030-01-01')"
            )
            for reg, isin in [
                ("1-01-99999-z", "ZZ0000000011"),
                (" 1-01-99999-Z", "ZZ0000000011"),
                ("", "ZZ0000000011"),
                ("1-01-99999-Z", "ZZ000000001Z"),
                ("1-01-99999-Z", "ZZ00000000!1"),
                ("1-01-99999-Z", "Z10000000011"),
                ("1-01-99999-Z", "ZZ123"),
            ]:
                with pytest.raises(sqlite3.IntegrityError):
                    connection.execute(insert, (reg, isin))
            connection.execute(insert, ("1-01-99999-Z", "ZZ0000000011"))
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(insert, ("1-01-99999-Z", "ZZ0000000022"))
            connection.commit()
        result = run_alembic(path, "downgrade", previous)
        assert result.returncode == 0, result.stderr
        assert revision_rows(path) == [previous]
        with sqlite3.connect(path) as connection:
            assert (
                connection.execute(
                    "SELECT name FROM sqlite_master WHERE name='security_reg_isin_mappings'"
                ).fetchall()
                == []
            )
            for name, rows in before.items():
                assert (
                    connection.execute(f'SELECT * FROM "{name}" ORDER BY rowid').fetchall() == rows
                )
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
            assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)


def test_money_instrument_links_additive_populated_upgrade_downgrade(tmp_path):
    from test_statement_import_mybroker import FILENAME, fixture

    from hermes_finance.database import create_database
    from hermes_finance.services.source_intake import save_intake

    path = tmp_path / "synthetic-money-links.db"
    assert run_alembic(path, "upgrade", "head").returncode == 0
    database = create_database(path)
    with database.session_factory() as session:
        save_intake(session, document=fixture(), filename=FILENAME, request_id="links-migration")
    database.engine.dispose()
    old_revision = "0060_source_money_classifications"
    assert run_alembic(path, "downgrade", old_revision).returncode == 0
    table = "source_intake_money_classifications"
    with sqlite3.connect(path) as connection:
        original = connection.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
        assert original
        journal = {
            name: connection.execute(f"SELECT * FROM {name} ORDER BY rowid").fetchall()
            for name in (
                "source_intake_originals",
                "source_intake_observations",
                "source_intake_revisions",
            )
        }
    for cycle in range(2):
        upgraded = run_alembic(path, "upgrade", "head")
        assert upgraded.returncode == 0, upgraded.stderr
        assert revision_rows(path) == [REVISION]
        with sqlite3.connect(path) as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            assert connection.execute(
                "PRAGMA index_info(ix_source_money_instrument_id)"
            ).fetchall() == [(0, 16, "instrument_id")]
            assert connection.execute(f"SELECT * FROM {table} ORDER BY id").fetchall() == [
                (*row, None, None, None, None) for row in original
            ]
            for name, rows in journal.items():
                assert connection.execute(f"SELECT * FROM {name} ORDER BY rowid").fetchall() == rows
            cursor = connection.execute(
                "INSERT INTO instruments(name,instrument_type,isin) VALUES (?,?,?)",
                ("АО Синтетический Ландыш", "bond", f"RU000A09999{cycle}"),
            )
            instrument_id = cursor.lastrowid
            connection.execute(
                f"UPDATE {table} SET security_reg_number=?,security_issuer=?,instrument_id=?,instrument_link_status='linked' WHERE id=?",
                ("4B02-09-99999-Z-001P", "АО Синтетический Ландыш", instrument_id, original[0][0]),
            )
            import pytest

            for issuer in ("", "   "):
                with pytest.raises(sqlite3.IntegrityError, match="ck_source_money_security_issuer"):
                    connection.execute(
                        f"UPDATE {table} SET security_issuer=? WHERE id=?", (issuer, original[0][0])
                    )
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute("DELETE FROM instruments WHERE id=?", (instrument_id,))
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    f"UPDATE {table} SET instrument_id=999999999 WHERE id=?", (original[0][0],)
                )
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    f"UPDATE {table} SET instrument_link_status='guess' WHERE id=?",
                    (original[0][0],),
                )
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    f"UPDATE {table} SET instrument_link_status=NULL WHERE id=?", (original[0][0],)
                )
            connection.execute(
                f"UPDATE {table} SET instrument_id=NULL,security_reg_number=NULL,security_issuer=NULL,"
                "instrument_link_status='kind_mismatch' WHERE id=?",
                (original[0][0],),
            )
            connection.commit()
            # Instrument insertion legitimately appends a dependency revision;
            # migrations must preserve the journal as it stands after that write.
            journal = {
                name: connection.execute(f"SELECT * FROM {name} ORDER BY rowid").fetchall()
                for name in journal
            }
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        downgraded = run_alembic(path, "downgrade", old_revision)
        assert downgraded.returncode == 0, downgraded.stderr
        assert revision_rows(path) == [old_revision]
        with sqlite3.connect(path) as connection:
            assert (
                connection.execute("PRAGMA index_info(ix_source_money_instrument_id)").fetchall()
                == []
            )
            assert connection.execute(f"SELECT * FROM {table} ORDER BY id").fetchall() == original
            for name, rows in journal.items():
                assert connection.execute(f"SELECT * FROM {name} ORDER BY rowid").fetchall() == rows
            assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_source_intake_migration_empty_cycle_and_populated_refusal(tmp_path):
    from test_statement_import_mybroker import FILENAME, fixture

    from hermes_finance.database import create_database
    from hermes_finance.services.source_intake import save_intake

    path = tmp_path / "synthetic-intake.db"
    for _ in range(2):
        upgraded = run_alembic(path, "upgrade", "head")
        assert upgraded.returncode == 0, upgraded.stderr
        assert revision_rows(path) == [REVISION]
        downgraded = run_alembic(path, "downgrade", "0058_broker_money_ownership")
        assert downgraded.returncode == 0, downgraded.stderr
    assert run_alembic(path, "upgrade", "head").returncode == 0
    db = create_database(path)
    with db.session_factory() as session:
        saved = save_intake(
            session, document=fixture(), filename=FILENAME, request_id="migration-save"
        )
    db.engine.dispose()
    blocked = run_alembic(path, "downgrade", "0058_broker_money_ownership")
    assert (
        blocked.returncode != 0
        and "cannot downgrade populated source intake journal" in blocked.stderr
    )
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert (
            connection.execute("SELECT id FROM source_intake_originals").fetchone()[0]
            == saved["intake_id"]
        )


def test_broker_month_receipt_migration_preserves_source_and_refuses_owned_downgrade(tmp_path):
    from fastapi.testclient import TestClient
    from test_statement_import_mybroker import FILENAME, ISIN
    from test_statement_import_mybroker_endpoints import (
        _broker_month_apply,
        _broker_month_preview,
        broker_month_xml,
    )

    from hermes_finance.database import create_database
    from hermes_finance.main import create_app
    from hermes_finance.services.accounts import create_account
    from hermes_finance.services.instruments import create_instrument
    from hermes_finance.services.reporting_months import create_reporting_month

    path = tmp_path / "synthetic-broker-batch.db"
    assert run_alembic(path, "upgrade", "head").returncode == 0
    assert run_alembic(path, "downgrade", "0056_source_native_finance").returncode == 0
    assert run_alembic(path, "upgrade", "head").returncode == 0
    db = create_database(path)
    with db.session_factory() as session:
        account = create_account(session, name="Synthetic", account_type="brokerage")
        create_instrument(session, name="Synthetic", instrument_type="stock", isin=ISIN)
        month = create_reporting_month(session, year=2030, month=1, snapshot_date=date(2030, 1, 31))
        intent = {"reporting_month_id": month.id, "account_id": account.id}
    client = TestClient(create_app(database=db))
    xml = broker_month_xml()
    plan = _broker_month_preview(client, intent, xml, filename=FILENAME)
    assert _broker_month_apply(client, intent, plan, xml).status_code == 200
    db.engine.dispose()
    result = run_alembic(path, "downgrade", "0056_source_native_finance")
    assert (
        result.returncode != 0
        and "cannot downgrade with source-owned broker month receipts" in result.stderr
    )
    assert revision_rows(path) == [REVISION]
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("SELECT COUNT(*) FROM broker_month_applies").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM mybroker_imports").fetchone()[0] == 1


def test_native_migration_refuses_lossy_downgrade_and_fractional_kopecks(tmp_path):
    import pytest
    from test_positions import _native_source, build_environment

    from hermes_finance.database import create_database
    from hermes_finance.domain import RubleAmount
    from hermes_finance.services.source_native import stage_native_payout, stage_native_position

    path = tmp_path / "synthetic-native-owned.db"
    result = run_alembic(path, "upgrade", "head")
    assert result.returncode == 0, result.stderr
    database = create_database(path)
    with database.session_factory() as session:
        month, account, instrument = build_environment(session)
        source = _native_source(session)
        row = stage_native_position(
            session,
            reporting_month_id=month,
            account_id=account,
            instrument_id=instrument,
            quantity="3",
            market_value=RubleAmount(1000001),
            price_date=date(2030, 5, 12),
            source_import_id=source,
            source_row_key="c" * 64,
            asset_kind="bond",
            bond_nkd_basis="unknown",
        )
        flow = stage_native_payout(
            session,
            reporting_month_id=month,
            account_id=account,
            instrument_id=instrument,
            flow_type="coupon",
            event_date=date(2030, 5, 10),
            net_amount=RubleAmount(30001),
            source_import_id=source,
            source_row_key="d" * 64,
        )
        session.commit()
        row_id, flow_id = row.id, flow.id
    database.engine.dispose()
    with sqlite3.connect(path) as c:
        for sql in (
            f"UPDATE position_snapshots SET market_value_kopecks=1.1 WHERE id={row_id}",
            f"UPDATE investment_cash_flows SET net_amount_kopecks=1.1 WHERE id={flow_id}",
        ):
            with pytest.raises(sqlite3.IntegrityError):
                c.execute(sql)
        assert c.execute("PRAGMA foreign_key_check").fetchall() == []
    result = run_alembic(path, "downgrade", "0055_mybroker_corrections")
    assert result.returncode != 0 and "cannot downgrade with source-native" in result.stderr
    assert revision_rows(path) == [REVISION]
    with sqlite3.connect(path) as c:
        assert c.execute(
            "SELECT market_value_kopecks,cost_basis_kopecks FROM position_snapshots"
        ).fetchone() == (1000001, None)
        assert c.execute(
            "SELECT net_amount_kopecks,tax_amount_kopecks FROM investment_cash_flows"
        ).fetchone() == (30001, None)


def test_native_migration_preserves_legacy_and_guards_nullable_modes_and_downgrade(tmp_path):
    import pytest

    path = tmp_path / "synthetic-native-migration.db"
    parent = "0055_mybroker_corrections"
    result = run_alembic(path, "upgrade", parent)
    assert result.returncode == 0, result.stderr
    with sqlite3.connect(path) as c:
        c.execute("INSERT INTO accounts(id,name,account_type) VALUES(1,'Synthetic','brokerage')")
        c.execute("INSERT INTO instruments(id,name,instrument_type) VALUES(1,'Synthetic','bond')")
        c.execute(
            "INSERT INTO reporting_months(id,year,month,period_start,period_end,snapshot_date,status,source,created_at,updated_at) VALUES(1,2030,5,'2030-05-01','2030-05-31','2030-05-31','closed','manual','2030-06-01','2030-06-01')"
        )
        c.execute(
            "INSERT INTO position_snapshots(id,reporting_month_id,account_id,instrument_id,quantity,average_cost_per_unit_kopecks,market_price_per_unit_kopecks,market_value_kopecks,cost_basis_kopecks,unrealized_result_kopecks,price_date,updated_at) VALUES(1,1,1,1,3,123,124,373,369,4,'2030-05-31','2030-06-01')"
        )
        c.execute(
            "INSERT INTO investment_cash_flows(id,reporting_month_id,account_id,flow_type,event_date,gross_amount_kopecks,tax_amount_kopecks,commission_amount_kopecks,net_amount_kopecks,source) VALUES(1,1,1,'coupon','2030-05-15',100,13,0,87,'manual')"
        )
        before_position = c.execute("SELECT * FROM position_snapshots").fetchone()
        before_flow = c.execute("SELECT * FROM investment_cash_flows").fetchone()
    result = run_alembic(path, "upgrade", "head")
    assert result.returncode == 0, result.stderr
    with sqlite3.connect(path) as c:
        # All original columns, including deliberately non-price-derived totals, survive.
        columns = [r[1] for r in c.execute("PRAGMA table_info(position_snapshots)")]
        old_columns = [
            name
            for name in columns
            if name
            not in {
                "source_import_id",
                "source_row_key",
                "native_contract_version",
                "bond_nkd_basis",
            }
        ]
        assert (
            c.execute(f"SELECT {','.join(old_columns)} FROM position_snapshots").fetchone()
            == before_position
        )
        columns = [r[1] for r in c.execute("PRAGMA table_info(investment_cash_flows)")]
        old_columns = [
            name
            for name in columns
            if name not in {"source_import_id", "source_row_key", "amount_basis"}
        ]
        assert (
            c.execute(f"SELECT {','.join(old_columns)} FROM investment_cash_flows").fetchone()
            == before_flow
        )
        assert c.execute("SELECT bond_nkd_basis FROM position_snapshots").fetchone() == ("unknown",)
        assert c.execute("SELECT amount_basis FROM investment_cash_flows").fetchone() == (
            "gross_components",
        )
        for sql in (
            "UPDATE position_snapshots SET cost_basis_kopecks=NULL",
            "UPDATE investment_cash_flows SET tax_amount_kopecks=NULL",
            "UPDATE position_snapshots SET price_source='broker_statement_native'",
        ):
            with pytest.raises(sqlite3.IntegrityError):
                c.execute(sql)
        assert c.execute("PRAGMA foreign_key_check").fetchall() == []
    result = run_alembic(path, "downgrade", parent)
    assert result.returncode == 0, result.stderr
    with sqlite3.connect(path) as c:
        assert c.execute("SELECT * FROM position_snapshots").fetchone() == before_position
        assert c.execute("SELECT * FROM investment_cash_flows").fetchone() == before_flow


def test_source_cash_upgrade_empty_preserves_v1_and_legacy_and_guards_identity_history(tmp_path):
    import pytest

    path = tmp_path / "synthetic-source-cash-migration.db"
    parent = "0051_historical_owner_flows"
    assert run_alembic(path, "upgrade", parent).returncode == 0
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO accounts(id,name,account_type) VALUES(1,'Synthetic','brokerage')"
        )
        connection.execute(
            "INSERT INTO cash_boundary_coverages(id,account_id,covered_from,covered_to,coverage_state,provenance_kind,created_at,updated_at) VALUES(1,1,'2030-01-17','2030-01-17','unknown','owner_attestation','2030-02-01','2030-02-01')"
        )
        connection.execute(
            "INSERT INTO historical_owner_flows VALUES('synthetic',1,'2030-01-17','RUB','12.34','contribution',1234)"
        )
        connection.execute(
            "INSERT INTO historical_owner_flow_revisions VALUES(1,'synthetic',1,NULL,'accept','accepted',?, ?,NULL,'2030-02-01')",
            ('{"contract_version":"h2-a1-owner-rub-v1"}', "a" * 64),
        )
    result = run_alembic(path, "upgrade", "head")
    assert result.returncode == 0, result.stderr
    with sqlite3.connect(path) as connection:
        for table in (
            "source_cash_coverage_revisions",
            "source_cash_coverage_applies",
            "reporting_months",
            "external_flows",
        ):
            assert connection.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,)
        assert connection.execute(
            "SELECT evidence_json FROM historical_owner_flow_revisions"
        ).fetchone() == ('{"contract_version":"h2-a1-owner-rub-v1"}',)
        assert connection.execute(
            "SELECT coverage_state,provenance_kind FROM cash_boundary_coverages"
        ).fetchone() == ("unknown", "owner_attestation")
    assert run_alembic(path, "downgrade", parent).returncode == 0
    assert run_alembic(path, "upgrade", "head").returncode == 0
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "INSERT INTO source_cash_coverage_revisions VALUES(1,1,1,NULL,'accept','accepted','{}',?,'null',NULL,'2030-02-01')",
            ("b" * 64,),
        )
        connection.execute(
            "INSERT INTO source_cash_coverage_applies VALUES(1,'synthetic',?,?,1,1,'created','2030-02-01')",
            ("c" * 64, "d" * 64),
        )
        for table in ("source_cash_coverage_revisions", "source_cash_coverage_applies"):
            for operation in (f"UPDATE {table} SET id=id", f"DELETE FROM {table}"):
                with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                    connection.execute(operation)
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute("UPDATE cash_boundary_coverages SET covered_to='2030-01-18'")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM cash_boundary_coverages")
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    result = run_alembic(path, "downgrade", parent)
    assert (
        result.returncode != 0 and "cannot discard source cash coverage acceptance" in result.stderr
    )
    assert revision_rows(path) == [REVISION]


def test_executed_trade_upgrade_empty_preserves_sources_and_guards_loss(tmp_path):
    path = tmp_path / "synthetic-executed-trade-migration.db"
    parent = "0048_mybroker_import_lineage"
    assert run_alembic(path, "upgrade", parent).returncode == 0
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO mybroker_imports "
            "(document_sha256, covered_from, covered_to, parser_version, confirmation_digest, "
            "normalized_json, mappings_json, accepted_at) VALUES "
            "(?, '2030-01-01', '2030-01-31', 'mybroker-s1-v2', ?, '{}', '[]', '2030-02-01')",
            ("a" * 64, "b" * 64),
        )
    result = run_alembic(path, "upgrade", "head")
    assert result.returncode == 0, result.stderr
    with sqlite3.connect(path) as connection:
        for table in (
            "executed_trades",
            "executed_trade_revisions",
            "executed_trade_occurrences",
            "executed_trade_applies",
            "reporting_months",
            "position_snapshots",
            "cash_balances",
            "investment_cash_flows",
            "external_flows",
        ):
            assert connection.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,)
        assert connection.execute("SELECT normalized_json FROM mybroker_imports").fetchone() == (
            "{}",
        )
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert run_alembic(path, "downgrade", parent).returncode == 0
    assert run_alembic(path, "upgrade", "head").returncode == 0
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO executed_trade_applies "
            "(request_id, request_fingerprint, trade_ids_json, accepted_at) "
            "VALUES ('synthetic', ?, '[]', '2030-02-01')",
            ("a" * 64,),
        )
    result = run_alembic(path, "downgrade", parent)
    assert result.returncode != 0
    assert "cannot discard canonical executed-trade truth" in result.stderr
    assert revision_rows(path) == [REVISION]


def test_mybroker_lineage_upgrade_is_empty_preserves_facts_and_guards_downgrade(tmp_path):
    path = tmp_path / "synthetic-mybroker-migration.db"
    parent = "0047_class_endpoint_inventory"
    assert run_alembic(path, "upgrade", parent).returncode == 0
    result = run_alembic(path, "upgrade", "head")
    assert result.returncode == 0, result.stderr
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT count(*) FROM mybroker_imports").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM reporting_months").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM investment_cash_flows").fetchone() == (0,)
    assert run_alembic(path, "downgrade", parent).returncode == 0
    assert run_alembic(path, "upgrade", "head").returncode == 0
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO mybroker_imports "
            "(document_sha256, covered_from, covered_to, parser_version, confirmation_digest, "
            "normalized_json, mappings_json, accepted_at) VALUES "
            "(?, '2030-01-01', '2030-01-31', 'mybroker-s1-v1', ?, '{}', '[]', '2030-02-01')",
            ("a" * 64, "b" * 64),
        )
    result = run_alembic(path, "downgrade", parent)
    assert result.returncode != 0
    assert "cannot discard MyBroker import lineage" in result.stderr
    assert revision_rows(path) == [REVISION]


def test_class_coverage_migration_has_no_backfill_and_refuses_loss(tmp_path: Path) -> None:
    path = tmp_path / "synthetic-class-coverage.db"
    parent = "0045_position_historical_instrument_type"
    c2_revision = "0046_class_no_crossing_coverage"
    assert run_alembic(path, "upgrade", parent).returncode == 0
    result = run_alembic(path, "upgrade", c2_revision)
    assert result.returncode == 0, result.stderr
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT count(*) FROM class_no_crossing_coverages"
        ).fetchone() == (0,)
    assert run_alembic(path, "downgrade", parent).returncode == 0
    assert run_alembic(path, "upgrade", c2_revision).returncode == 0
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO class_no_crossing_coverages "
            "(asset_class, covered_from, covered_to, coverage_state, provenance_kind, revision) "
            "VALUES ('stock', '2030-01-31', '2030-02-28', 'revoked', 'owner_attestation', 1)"
        )
        for sql in (
            "UPDATE class_no_crossing_coverages SET asset_class = 'fund'",
            "UPDATE class_no_crossing_coverages SET coverage_state = 'complete'",
            "UPDATE class_no_crossing_coverages SET provenance_kind = 'statement_verified'",
            "UPDATE class_no_crossing_coverages SET revision = 0",
        ):
            try:
                connection.execute(sql)
            except sqlite3.IntegrityError:
                pass
            else:
                raise AssertionError("invalid class assertion accepted")
    result = run_alembic(path, "downgrade", parent)
    assert result.returncode != 0
    assert "cannot discard class no-crossing evidence" in result.stderr
    assert revision_rows(path) == [c2_revision]


def test_endpoint_inventory_upgrade_does_not_attest_existing_c2_and_guards_loss(tmp_path):
    path = tmp_path / "synthetic-inventory-coverage.db"
    parent = "0046_class_no_crossing_coverage"
    assert run_alembic(path, "upgrade", parent).returncode == 0
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO class_no_crossing_coverages "
            "(asset_class, covered_from, covered_to, coverage_state, provenance_kind, "
            "material_signature, revision) VALUES "
            "('stock', '2030-01-31', '2030-02-28', 'complete', 'owner_attestation', ?, 1)",
            ("a" * 64,),
        )
    result = run_alembic(path, "upgrade", "head")
    assert result.returncode == 0, result.stderr
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT coverage_state, opening_inventory_complete, closing_inventory_complete, "
            "material_signature, revision FROM class_no_crossing_coverages"
        ).fetchone() == ("complete", 0, 0, "a" * 64, 1)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert run_alembic(path, "downgrade", parent).returncode == 0
    assert run_alembic(path, "upgrade", "head").returncode == 0
    for column in ("opening_inventory_complete", "closing_inventory_complete"):
        with sqlite3.connect(path) as connection:
            connection.execute(f"UPDATE class_no_crossing_coverages SET {column} = 1")
        result = run_alembic(path, "downgrade", parent)
        assert result.returncode != 0
        assert "cannot discard class endpoint inventory evidence" in result.stderr
        assert revision_rows(path) == [REVISION]
        with sqlite3.connect(path) as connection:
            connection.execute(f"UPDATE class_no_crossing_coverages SET {column} = 0")


# Immediate parent of REVISION: used to prove the #336 add-on is additive.
FINANCIAL_CONTEXT_PARENT_REVISION = "0036_broker_baseline_provenance"


def test_position_class_migration_leaves_closed_legacy_unknown_and_guards_loss(
    tmp_path: Path,
) -> None:
    path = tmp_path / "class-migration.db"
    parent = "0044_observed_valuation_material_signature"
    c1_revision = "0045_position_historical_instrument_type"
    result = run_alembic(path, "upgrade", parent)
    assert result.returncode == 0, result.stderr
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO reporting_months (id, year, month, period_start, period_end, "
            "snapshot_date, status, source, created_at, updated_at) VALUES "
            "(1, 2031, 1, '2031-01-01', '2031-01-31', '2031-01-31', 'closed', "
            "'manual', '2031-01-31', '2031-01-31')"
        )
        connection.execute(
            "INSERT INTO accounts (id, name, account_type, status, include_in_capital, "
            "include_in_returns) VALUES (1, 'Synthetic', 'brokerage', 'active', 1, 1)"
        )
        connection.execute(
            "INSERT INTO instruments (id, name, instrument_type, currency, is_active, "
            "manual_price_allowed) VALUES (1, 'Synthetic', 'stock', 'RUB', 1, 1)"
        )
        connection.execute(
            "INSERT INTO position_snapshots (id, reporting_month_id, account_id, "
            "instrument_id, quantity, average_cost_per_unit_kopecks, "
            "market_price_per_unit_kopecks, market_value_kopecks, cost_basis_kopecks, "
            "unrealized_result_kopecks, price_date, price_source, manual_adjustment, "
            "updated_at) VALUES (1, 1, 1, 1, 1, 10000, 11000, 11000, 10000, 1000, "
            "'2031-01-31', 'manual', 0, '2031-01-31')"
        )
    result = run_alembic(path, "upgrade", c1_revision)
    assert result.returncode == 0, result.stderr
    assert revision_rows(path) == [c1_revision]
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT historical_instrument_type, market_value_kopecks FROM position_snapshots"
        ).fetchall() == [(None, 11000)]
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    result = run_alembic(path, "downgrade", parent)
    assert result.returncode == 0, result.stderr
    assert revision_rows(path) == [parent]
    result = run_alembic(path, "upgrade", c1_revision)
    assert result.returncode == 0, result.stderr
    with sqlite3.connect(path) as connection:
        for invalid in ("other", "equity", "BOND", "bond ", ""):
            try:
                connection.execute(
                    "UPDATE position_snapshots SET historical_instrument_type = ?", (invalid,)
                )
            except sqlite3.IntegrityError:
                connection.rollback()
            else:
                raise AssertionError(f"invalid class evidence accepted: {invalid!r}")
        connection.execute("UPDATE position_snapshots SET historical_instrument_type = 'bond'")
    result = run_alembic(path, "downgrade", parent)
    assert result.returncode != 0
    assert "while evidence exists" in result.stderr
    assert revision_rows(path) == [c1_revision]
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT historical_instrument_type FROM position_snapshots"
        ).fetchall() == [("bond",)]


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
        assert [
            row[1]
            for row in connection.execute("PRAGMA table_info(source_intake_money_classifications)")
        ] == [
            "id",
            "intake_id",
            "observation_id",
            "source_reference",
            "date",
            "amount_kopecks",
            "currency",
            "operation",
            "narrative",
            "classification",
            "origin",
            "status",
            "created_at",
            "updated_at",
            "security_reg_number",
            "security_issuer",
            "instrument_id",
            "instrument_link_status",
        ]
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
            "archived_from_period",
            "historical_instrument_type",
            "source_import_id",
            "source_row_key",
            "native_contract_version",
            "bond_nkd_basis",
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
            "actual_fact_origin",
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
            "amount_basis",
            "source_import_id",
            "source_row_key",
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
            "material_signature",
        ]
        assert [
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(external_transfer_reconciliation_evidence)"
            )
        ] == [
            "id",
            "transfer_link_id",
            "kind",
            "amount_kopecks",
            "currency",
            "source",
            "evidence_reference",
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
            "archived_from_period",
            "payout_link_revision",
        ]
        assert [row[1] for row in connection.execute("PRAGMA table_info(expense_entries)")] == [
            "id",
            "reporting_month_id",
            "category",
            "amount_kopecks",
            "expense_type",
            "is_recurring",
            "notes",
            "actual_fact_origin",
        ]
        assert [row[1] for row in connection.execute("PRAGMA table_info(saving_allocations)")] == [
            "id",
            "reporting_month_id",
            "destination",
            "amount_kopecks",
            "notes",
            "actual_fact_origin",
        ]
        assert [
            row[1] for row in connection.execute("PRAGMA table_info(planned_budget_lines)")
        ] == [
            "id",
            "reporting_month_id",
            "category",
            "planned_amount_kopecks",
            "expense_type",
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
            "annual_rate_basis_points",
            "next_due_date",
            "contract_end_date",
            "linked_account_id",
        ]
        assert [row[1] for row in connection.execute("PRAGMA table_info(property_snapshots)")] == [
            "id",
            "reporting_month_id",
            "name",
            "estimated_value_kopecks",
            "mortgage_balance_kopecks",
            "monthly_payment_kopecks",
            "notes",
            "mortgage_annual_rate_basis_points",
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
            "archived_from_period",
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
            "archived_from_period",
            "investment_cash_flow_id",
            "applied_payout_revision_id",
            "money_proof_request_id",
            "accepted_request_id",
            "retired_request_id",
            "supersedes_id",
            "provider_event_key",
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
    assert "while evidence exists" in downgraded.stderr
    # The entire downgrade rolls back, including the newer nullable C1 column.
    assert revision_rows(database_path) == [REVISION]
    connection = sqlite3.connect(database_path)
    try:
        assert connection.execute(
            "SELECT material_signature FROM observed_valuation_points"
        ).fetchone() == (None,)
    finally:
        connection.close()


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
    assert revision_rows(database_path) == [REVISION]


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
        assert reconciliation_fk_actions["expected_cash_flow_id"] == "RESTRICT"
        active_link_index = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index' "
            "AND name = 'uq_applied_payout_reconciliations_active_manual_flow'"
        ).fetchone()
        assert active_link_index is not None
        assert "WHERE archived_from_period IS NULL" in active_link_index[0]
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


def test_financial_context_migration_is_additive_and_leaves_unknown_null(
    tmp_path: Path,
) -> None:
    """#336: new debt terms, mortgage rate and planned budget must not backfill guesses."""
    database_path = tmp_path / "financial-context.db"

    previous = run_alembic(database_path, "upgrade", FINANCIAL_CONTEXT_PARENT_REVISION)
    assert previous.returncode == 0, previous.stderr
    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            "INSERT INTO reporting_months "
            "(id, year, month, period_start, period_end, snapshot_date, status, source, "
            "created_at, updated_at) VALUES "
            "(1, 2032, 1, '2032-01-01', '2032-01-31', '2032-01-31', 'draft', 'manual', "
            "'2032-01-31T00:00:00', '2032-01-31T00:00:00')"
        )
        connection.execute(
            "INSERT INTO debts "
            "(id, reporting_month_id, debt_type, name, current_balance_kopecks, "
            "include_in_liquid_capital, notes) VALUES "
            "(1, 1, 'credit_card', 'Legacy Card', 100000, 1, NULL)"
        )
        connection.execute(
            "INSERT INTO property_snapshots "
            "(id, reporting_month_id, name, estimated_value_kopecks, "
            "mortgage_balance_kopecks, monthly_payment_kopecks, notes) VALUES "
            "(1, 1, 'Legacy Flat', 700000000, 300000000, 5000000, NULL)"
        )
        connection.commit()
    finally:
        connection.close()

    upgraded = run_alembic(database_path, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr
    assert revision_rows(database_path) == [REVISION]

    connection = sqlite3.connect(database_path)
    try:
        assert connection.execute(
            "SELECT annual_rate_basis_points, next_due_date, contract_end_date "
            "FROM debts WHERE id = 1"
        ).fetchone() == (None, None, None)
        assert connection.execute(
            "SELECT mortgage_annual_rate_basis_points FROM property_snapshots WHERE id = 1"
        ).fetchone() == (None,)
        assert connection.execute("SELECT COUNT(*) FROM planned_budget_lines").fetchone() == (0,)
        planned_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'planned_budget_lines'"
        ).fetchone()[0]
        assert "REFERENCES reporting_months" in planned_sql
        # Nothing may be inferred from the persisted mortgage payment or balance.
        assert "5000000" not in planned_sql
        for table in ("debts", "property_snapshots"):
            table_sql = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table,),
            ).fetchone()[0]
            assert "CHECK" in table_sql.upper()
    finally:
        connection.close()

    downgraded = run_alembic(database_path, "downgrade", FINANCIAL_CONTEXT_PARENT_REVISION)
    assert downgraded.returncode == 0, downgraded.stderr
    connection = sqlite3.connect(database_path)
    try:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert "planned_budget_lines" not in tables
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
        assert connection.execute("SELECT COUNT(*) FROM debts").fetchone() == (1,)
    finally:
        connection.close()


def test_cash_boundary_coverage_is_absent_before_migration(tmp_path: Path) -> None:
    database_path = tmp_path / "cash-boundary-coverage.db"
    previous = run_alembic(database_path, "upgrade", "0037_336_financial_context")
    assert previous.returncode == 0, previous.stderr

    connection = sqlite3.connect(database_path)
    try:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert "cash_boundary_coverages" not in tables
    finally:
        connection.close()


def test_in_kind_boundary_coverage_migration_is_additive_and_amount_free(tmp_path: Path) -> None:
    database_path = tmp_path / "in-kind-boundary-coverage.db"
    previous = run_alembic(database_path, "upgrade", "0039_transfer_reconciliation_evidence")
    assert previous.returncode == 0, previous.stderr

    upgraded = run_alembic(database_path, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr
    assert revision_rows(database_path) == [REVISION]
    connection = sqlite3.connect(database_path)
    try:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert "in_kind_boundary_coverages" in tables
        assert "in_kind_movements" in tables
        assert connection.execute("SELECT COUNT(*) FROM in_kind_boundary_coverages").fetchone() == (
            0,
        )
        assert connection.execute("SELECT COUNT(*) FROM in_kind_movements").fetchone() == (0,)
        coverage_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' "
            "AND name = 'in_kind_boundary_coverages'"
        ).fetchone()[0]
        movement_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'in_kind_movements'"
        ).fetchone()[0]
        assert "amount" not in coverage_sql.lower()
        assert "amount" not in movement_sql.lower()
        assert "valuation" not in movement_sql.lower()
        assert "coverage_state IN ('complete', 'unknown')" in coverage_sql
        indexes = list(connection.execute("PRAGMA index_list(in_kind_movements)"))
        assert any(row[1] == "ix_in_kind_movements_event_date" for row in indexes)
        foreign_keys = list(connection.execute("PRAGMA foreign_key_list(in_kind_movements)"))
        assert {row[2] for row in foreign_keys} == {
            "reporting_months",
            "accounts",
            "instruments",
        }
    finally:
        connection.close()

    downgraded = run_alembic(database_path, "downgrade", "0039_transfer_reconciliation_evidence")
    assert downgraded.returncode == 0, downgraded.stderr
    connection = sqlite3.connect(database_path)
    try:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert "in_kind_boundary_coverages" not in tables
        assert "in_kind_movements" not in tables
    finally:
        connection.close()


def test_cash_boundary_coverage_migration_schema_and_downgrade(tmp_path: Path) -> None:
    database_path = tmp_path / "cash-boundary-coverage-schema.db"
    previous = run_alembic(database_path, "upgrade", "0037_336_financial_context")
    assert previous.returncode == 0, previous.stderr
    upgraded = run_alembic(database_path, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr
    assert revision_rows(database_path) == [REVISION]
    connection = sqlite3.connect(database_path)
    try:
        assert [
            row[1] for row in connection.execute("PRAGMA table_info(cash_boundary_coverages)")
        ] == [
            "id",
            "account_id",
            "covered_from",
            "covered_to",
            "coverage_state",
            "provenance_kind",
            "provenance_reference",
            "notes",
            "created_at",
            "updated_at",
        ]
        assert connection.execute("SELECT COUNT(*) FROM cash_boundary_coverages").fetchone() == (0,)
        table_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' "
            "AND name = 'cash_boundary_coverages'"
        ).fetchone()[0]
        assert "amount" not in table_sql.lower()
        assert "coverage_state IN ('complete', 'unknown')" in table_sql
        assert "uq_cash_boundary_coverages_account_interval" in table_sql
        indexes = list(connection.execute("PRAGMA index_list(cash_boundary_coverages)"))
        assert any(row[1] == "ix_cash_boundary_coverages_account_interval" for row in indexes)
        assert any(row[2] for row in indexes)
        foreign_keys = list(connection.execute("PRAGMA foreign_key_list(cash_boundary_coverages)"))
        assert {row[2] for row in foreign_keys} == {"accounts"}
    finally:
        connection.close()

    downgraded = run_alembic(database_path, "downgrade", "0037_336_financial_context")
    assert downgraded.returncode == 0, downgraded.stderr
    connection = sqlite3.connect(database_path)
    try:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert "cash_boundary_coverages" not in tables
    finally:
        connection.close()


def test_debt_link_migration_is_additive_and_downgrade_is_fail_closed(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "debt-linked-account.db"
    previous = run_alembic(database_path, "upgrade", "0040_in_kind_boundary_coverage")
    assert previous.returncode == 0, previous.stderr

    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            "INSERT INTO reporting_months "
            "(id, year, month, period_start, period_end, snapshot_date, status, source, "
            "created_at, updated_at) VALUES "
            "(1, 2032, 2, '2032-02-01', '2032-02-29', '2032-02-29', 'draft', 'manual', "
            "'2032-02-29T00:00:00', '2032-02-29T00:00:00')"
        )
        connection.execute(
            "INSERT INTO accounts "
            "(id, name, account_type, status, include_in_capital, include_in_returns) "
            "VALUES (1, 'Synthetic Linked Cash', 'cash', 'active', 1, 1)"
        )
        connection.execute(
            "INSERT INTO debts "
            "(id, reporting_month_id, debt_type, name, current_balance_kopecks, "
            "include_in_liquid_capital, notes) VALUES "
            "(1, 1, 'credit_card', 'Synthetic Legacy Card', 100000, 1, NULL)"
        )
        connection.commit()
    finally:
        connection.close()

    upgraded = run_alembic(database_path, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr
    assert revision_rows(database_path) == [REVISION]

    connection = sqlite3.connect(database_path)
    try:
        assert connection.execute(
            "SELECT linked_account_id FROM debts WHERE id = 1"
        ).fetchone() == (None,)
        assert [row[1] for row in connection.execute("PRAGMA table_info(debts)")][-1] == (
            "linked_account_id"
        )
        foreign_keys = list(connection.execute("PRAGMA foreign_key_list(debts)"))
        assert any(row[2] == "accounts" and row[3] == "linked_account_id" for row in foreign_keys)
        table_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'debts'"
        ).fetchone()[0]
        assert "ck_debts_linked_account_eligibility" in table_sql
        assert "uq_debts_reporting_month_linked_account" in table_sql

        connection.execute("UPDATE debts SET linked_account_id = 1 WHERE id = 1")
        connection.commit()
    finally:
        connection.close()

    blocked = run_alembic(database_path, "downgrade", "0040_in_kind_boundary_coverage")
    assert blocked.returncode != 0
    assert "while debt-account links exist" in blocked.stderr
    assert revision_rows(database_path) == [REVISION]

    connection = sqlite3.connect(database_path)
    try:
        connection.execute("UPDATE debts SET linked_account_id = NULL WHERE id = 1")
        connection.commit()
    finally:
        connection.close()

    downgraded = run_alembic(database_path, "downgrade", "0040_in_kind_boundary_coverage")
    assert downgraded.returncode == 0, downgraded.stderr
    assert revision_rows(database_path) == ["0040_in_kind_boundary_coverage"]
    connection = sqlite3.connect(database_path)
    try:
        assert "linked_account_id" not in {
            row[1] for row in connection.execute("PRAGMA table_info(debts)")
        }
    finally:
        connection.close()


def test_money_ownership_migration_keeps_v1_bytes_and_refuses_populated_downgrade(tmp_path):
    from test_statement_import_mybroker import ACCOUNT, FILENAME, ISIN
    from test_statement_import_mybroker_endpoints import _money_apply, _money_decide, _money_setup

    from hermes_finance.database import create_database
    from hermes_finance.services.accounts import create_account
    from hermes_finance.services.broker_identity_mappings import confirm_mapping
    from hermes_finance.services.instruments import create_instrument
    from hermes_finance.statement_import.mybroker import PROVIDER

    path = tmp_path / "synthetic-money-migration.db"
    assert run_alembic(path, "upgrade", "head").returncode == 0
    db = create_database(path)
    with db.session_factory() as session:
        account = create_account(session, name="Synthetic account", account_type="brokerage")
        instrument = create_instrument(
            session, name="Synthetic stock", instrument_type="stock", isin=ISIN
        )
        for alias in ("1234567", ACCOUNT):
            confirm_mapping(
                session,
                provider=PROVIDER,
                subject_kind="account",
                provider_identity=alias,
                hermes_target_id=account.id,
            )
        confirm_mapping(
            session,
            provider=PROVIDER,
            subject_kind="instrument",
            provider_identity=ISIN,
            hermes_target_id=instrument.id,
        )
    _, xml, intent, bond, _ = _money_setup(db)
    db.engine.dispose()
    with sqlite3.connect(path) as connection:
        old = connection.execute(
            "SELECT normalized_json, mappings_json, confirmation_digest FROM mybroker_imports"
        ).fetchall()
        receipts = connection.execute("SELECT projection_json FROM broker_month_applies").fetchall()
    assert run_alembic(path, "downgrade", "0057_broker_month_batch").returncode == 0
    assert run_alembic(path, "upgrade", "head").returncode == 0
    with sqlite3.connect(path) as connection:
        assert (
            connection.execute(
                "SELECT normalized_json, mappings_json, confirmation_digest FROM mybroker_imports"
            ).fetchall()
            == old
        )
        assert (
            connection.execute("SELECT projection_json FROM broker_month_applies").fetchall()
            == receipts
        )
        assert (
            connection.execute("SELECT COUNT(*) FROM broker_money_occurrence_owners").fetchone()[0]
            == 0
        )
    from sqlalchemy import select

    from hermes_finance.persistence import CashBalance

    with db.session_factory() as session:
        cash = session.scalar(select(CashBalance))
        cash.amount_kopecks += 1
        session.commit()
        cash.amount_kopecks -= 1
        session.commit()
    db.engine.dispose()
    # Even with no ownership links yet, downgrading must retain the monotonic
    # dependency evidence; the old implementation cannot read its version.
    blocked = run_alembic(path, "downgrade", "0057_broker_month_batch")
    assert blocked.returncode != 0 and "cannot downgrade permanent Money" in blocked.stderr
    with db.session_factory() as session:
        requested = _money_decide(session, intent, [(FILENAME, xml)], bond)
        _money_apply(session, requested, [(FILENAME, xml)])
    db.engine.dispose()
    from test_r13_00_release_verification import _snapshot

    with sqlite3.connect(path) as connection:
        before = _snapshot(connection)
        schema = connection.execute(
            "SELECT type,name,sql FROM sqlite_master ORDER BY type,name"
        ).fetchall()
    blocked = run_alembic(path, "downgrade", "0057_broker_month_batch")
    # Current writers also retain payout dependency generations. The new 0066
    # guard must stop the chain before any such history can be discarded.
    assert blocked.returncode != 0 and "0066_cannot_downgrade_payout_history" in blocked.stderr
    assert revision_rows(path) == [REVISION]
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert (
            connection.execute("SELECT COUNT(*) FROM broker_money_occurrence_owners").fetchone()[0]
            == 3
        )
        assert _snapshot(connection) == before
        assert (
            connection.execute(
                "SELECT type,name,sql FROM sqlite_master ORDER BY type,name"
            ).fetchall()
            == schema
        )
    # Independently retain the original 0058 populated-ownership refusal proof:
    # invoke the unchanged guard on this valid synthetic graph. It raises before
    # DDL; no downgrade is stamped and no new receipt or owner is removed.
    import pytest
    from alembic.config import Config
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from alembic.script import ScriptDirectory

    scripts = ScriptDirectory.from_config(Config(str(BACKEND_ROOT / "alembic.ini")))
    legacy = scripts.get_revision("0058_broker_money_ownership").module
    with db.engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            with pytest.raises(RuntimeError, match="cannot downgrade permanent Money ownership"):
                legacy.downgrade()
    db.engine.dispose()
    with sqlite3.connect(path) as connection:
        assert _snapshot(connection) == before
        assert (
            connection.execute(
                "SELECT type,name,sql FROM sqlite_master ORDER BY type,name"
            ).fetchall()
            == schema
        )
    assert revision_rows(path) == [REVISION]


def test_investment_proof_migration_preserves_rows_sequence_and_legacy_guard_profile(tmp_path):
    import pytest

    path = tmp_path / "synthetic-investment-proof.db"
    upgraded = run_alembic(path, "upgrade", "0066_actual_payout_links")
    assert upgraded.returncode == 0, upgraded.stderr
    with sqlite3.connect(path) as connection:
        old_guards = connection.execute(
            "SELECT name,sql FROM sqlite_master WHERE type='trigger' AND name LIKE 'return_proof_%' ORDER BY name"
        ).fetchall()
        connection.execute(
            "INSERT INTO source_return_proofs (source_account,native_account,request_id,request_fingerprint,proof_version,dependency_digest,evidence_json,confirmed_at) VALUES ('synthetic','synthetic','legacy',?, 'source_return_custody_v1',?, '{}','2030-01-01')",
            ("a" * 64, "b" * 64),
        )
        connection.execute("UPDATE sqlite_sequence SET seq=100 WHERE name='source_return_proofs'")
        previous = connection.execute("SELECT * FROM source_return_proofs").fetchall()
    upgraded = run_alembic(path, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT * FROM source_return_proofs").fetchall() == previous
        assert connection.execute(
            "SELECT seq FROM sqlite_sequence WHERE name='source_return_proofs'"
        ).fetchone() == (100,)
        assert (
            "AUTOINCREMENT"
            in connection.execute(
                "SELECT sql FROM sqlite_master WHERE name='source_return_proofs'"
            ).fetchone()[0]
        )
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("UPDATE source_return_proofs SET source_account='other'")
    downgraded = run_alembic(path, "downgrade", "0066_actual_payout_links")
    assert downgraded.returncode == 0, downgraded.stderr
    with sqlite3.connect(path) as connection:
        assert (
            connection.execute(
                "SELECT name,sql FROM sqlite_master WHERE type='trigger' AND name LIKE 'return_proof_%' ORDER BY name"
            ).fetchall()
            == old_guards
        )
        assert connection.execute("SELECT * FROM source_return_proofs").fetchall() == previous
        assert connection.execute(
            "SELECT seq FROM sqlite_sequence WHERE name='source_return_proofs'"
        ).fetchone() == (100,)
    upgraded = run_alembic(path, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO source_return_proofs (source_account,native_account,request_id,request_fingerprint,proof_version,dependency_digest,evidence_json,confirmed_at) VALUES ('synthetic','synthetic','investment',?, 'source_return_investment_v1',?, '{}','2030-01-01')",
            ("c" * 64, "d" * 64),
        )
        assert connection.execute(
            "SELECT id FROM source_return_proofs WHERE request_id='investment'"
        ).fetchone() == (101,)
        before = connection.execute(
            "SELECT type,name,sql FROM sqlite_master ORDER BY type,name"
        ).fetchall()
    blocked = run_alembic(path, "downgrade", "0066_actual_payout_links")
    assert (
        blocked.returncode != 0
        and "cannot downgrade populated investment report proof history" in blocked.stderr
    )
    with sqlite3.connect(path) as connection:
        assert (
            connection.execute(
                "SELECT type,name,sql FROM sqlite_master ORDER BY type,name"
            ).fetchall()
            == before
        )


def test_source_money_classification_migration_populated_downgrade_and_reupgrade(tmp_path):
    from datetime import UTC, datetime

    from sqlalchemy import select
    from test_statement_import_mybroker import FILENAME, fixture

    from hermes_finance.database import create_database
    from hermes_finance.persistence import SourceIntakeObservation, SourceMoneyClassification
    from hermes_finance.services.source_intake import save_intake

    path = tmp_path / "synthetic-classification.db"
    assert run_alembic(path, "upgrade", "head").returncode == 0
    database = create_database(path)
    with database.session_factory() as session:
        saved = save_intake(session, document=fixture(), filename=FILENAME, request_id="legacy")
    database.engine.dispose()
    assert run_alembic(path, "downgrade", "0059_source_intake").returncode == 0
    with sqlite3.connect(path) as connection:
        before = {
            table: connection.execute(f"SELECT * FROM {table}").fetchall()
            for table in (
                "source_intake_originals",
                "source_intake_observations",
                "source_intake_revisions",
            )
        }
    for _ in range(2):
        upgraded = run_alembic(path, "upgrade", "head")
        assert upgraded.returncode == 0, upgraded.stderr
        assert revision_rows(path) == [REVISION]
        with sqlite3.connect(path) as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM source_intake_money_classifications"
            ).fetchone() == (0,)
        database = create_database(path)
        with database.session_factory() as session:
            observation = session.scalar(
                select(SourceIntakeObservation).where(SourceIntakeObservation.section == "money")
            )
            session.add(
                SourceMoneyClassification(
                    intake_id=saved["intake_id"],
                    observation_id=observation.id,
                    source_reference="synthetic-reference",
                    date=date(2030, 1, 17),
                    amount_kopecks=-123,
                    currency="RUB",
                    operation="Synthetic operation",
                    narrative="Synthetic narrative",
                    classification="unknown",
                    origin="default_rule",
                    status="assumed",
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            )
            session.commit()
        database.engine.dispose()
        downgraded = run_alembic(path, "downgrade", "0059_source_intake")
        assert downgraded.returncode == 0, downgraded.stderr
        with sqlite3.connect(path) as connection:
            assert (
                connection.execute(
                    "SELECT name FROM sqlite_master WHERE name='source_intake_money_classifications'"
                ).fetchall()
                == []
            )
            for table, rows in before.items():
                assert connection.execute(f"SELECT * FROM {table}").fetchall() == rows
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
            assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
