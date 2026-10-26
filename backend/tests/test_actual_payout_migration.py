"""Synthetic whole-0065 preservation, transactional DDL and fail-closed recovery."""

import json
import sqlite3

import pytest
from alembic import command

from hermes_finance import actual_payout_schema as schema
from hermes_finance.services.migrations import _alembic_config

OLD = "0065_source_return_proofs"
NEW = "0066_actual_payout_links"


def insert(c, table, **values):
    c.execute(
        f'INSERT INTO "{table}" ({", ".join(values)}) VALUES ({", ".join("?" for _ in values)})',
        tuple(values.values()),
    )


@pytest.fixture
def populated_0065(tmp_path):
    path = tmp_path / "synthetic-0065.db"
    command.upgrade(_alembic_config(path), OLD)
    with sqlite3.connect(path) as c:
        c.execute("PRAGMA foreign_keys=ON")
        for n, status in ((1, "draft"), (2, "closed")):
            insert(
                c,
                "reporting_months",
                id=n,
                year=2030,
                month=n,
                period_start=f"2030-0{n}-01",
                period_end=f"2030-0{n}-28",
                snapshot_date=f"2030-0{n}-28",
                status=status,
                source="manual",
                created_at="2030-03-01",
                updated_at="2030-03-01",
            )
            insert(
                c,
                "accounts",
                id=n,
                name=f"Synthetic {n}",
                account_type="brokerage",
                status="active",
                include_in_capital=1,
                include_in_returns=1,
            )
            insert(
                c,
                "instruments",
                id=n,
                name=f"Synthetic bond {n}",
                instrument_type="bond",
                currency="RUB",
                is_active=1,
                manual_price_allowed=1,
            )
            insert(
                c,
                "position_snapshots",
                id=n,
                reporting_month_id=n,
                account_id=n,
                instrument_id=n,
                quantity=2,
                average_cost_per_unit_kopecks=100,
                market_price_per_unit_kopecks=110,
                market_value_kopecks=220,
                cost_basis_kopecks=200,
                unrealized_result_kopecks=20,
                price_date=f"2030-0{n}-28",
                price_source="manual",
                manual_adjustment=0,
                updated_at="2030-03-01",
            )
            insert(
                c,
                "expected_cash_flows",
                id=n,
                reporting_month_id=n if n == 1 else None,
                archived_from_period=None if n == 1 else "2030-02",
                account_id=n,
                instrument_id=n,
                flow_type="coupon",
                expected_date="2030-03-01",
                gross_amount_kopecks=113,
                expected_tax_amount_kopecks=13,
                expected_net_amount_kopecks=100,
                source="synthetic",
                source_as_of_date="2030-01-28",
                forecast_version="v1",
            )
            common = dict(
                source_position_snapshot_id=n,
                provider="t_invest",
                provider_instrument_uid=f"synthetic-{n}",
                event_kind="coupon",
                identity_key="n:1",
                lifecycle="active",
                payment_date="2030-03-01",
                quantity=2,
                per_unit_amount="0.565",
                total_amount_kopecks=113,
                currency="RUB",
                amount_basis="provider_announced",
                is_approximate=1,
            )
            insert(
                c,
                "applied_provider_payouts",
                id=n,
                reporting_month_id=n if n == 1 else None,
                archived_from_period=None if n == 1 else "2030-02",
                account_id=n,
                instrument_id=n,
                first_applied_at="2030-03-01",
                **common,
            )
            insert(
                c,
                "applied_payout_revisions",
                id=n,
                applied_payout_id=n,
                revision_kind="apply",
                fetched_at="2030-03-01",
                applied_at="2030-03-01",
                **common,
            )
            insert(
                c,
                "applied_payout_reconciliations",
                id=n,
                applied_payout_id=n,
                expected_cash_flow_id=n,
                counting_decision="keep_both" if n == 1 else "count_manual",
                archived_from_period=None if n == 1 else "2030-02",
                created_at="2030-03-01",
            )
        insert(
            c,
            "mybroker_imports",
            id=1,
            document_sha256="a" * 64,
            covered_from="2030-01-01",
            covered_to="2030-01-28",
            parser_version="synthetic",
            confirmation_digest="b" * 64,
            normalized_json='{"synthetic": "old bytes"}',
            mappings_json="[]",
            accepted_at="2030-03-01",
        )
        for n in (1, 2):
            native = n == 1
            insert(
                c,
                "investment_cash_flows",
                id=n,
                reporting_month_id=n,
                account_id=n,
                instrument_id=n,
                flow_type="coupon",
                event_date=f"2030-0{n}-15",
                gross_amount_kopecks=None if native else 113,
                tax_amount_kopecks=None if native else 13,
                commission_amount_kopecks=None if native else 0,
                net_amount_kopecks=100,
                currency="RUB",
                source="synthetic",
                amount_basis="broker_statement_net_v1" if native else "gross_components",
                source_import_id=1 if native else None,
                source_row_key="c" * 64 if native else None,
            )
        insert(
            c,
            "broker_month_applies",
            request_id="synthetic-money-v1",
            request_fingerprint="d" * 64,
            confirmation_digest="e" * 64,
            reporting_month_id=1,
            account_id=1,
            import_id=1,
            projection_json=json.dumps(
                {
                    "contract_version": "broker_money_v1",
                    "base_request_id": "synthetic-base",
                    "operation": "accept",
                    "targets": [{"role": "coupon", "target_id": 1}],
                    "sources": [],
                    "occurrences": [],
                    "journal_revision": 1,
                }
            ),
            accepted_at="2030-03-01",
        )
        insert(
            c,
            "broker_money_occurrence_owners",
            id=1,
            import_id=1,
            section="money",
            ordinal=0,
            row_fingerprint="f" * 64,
            role="coupon",
            investment_cash_flow_id=1,
            accepted_request_id="synthetic-money-v1",
        )
        insert(
            c,
            "source_intake_originals",
            id=1,
            document_sha256="1" * 64,
            byte_length=1,
            filename_digest="2" * 64,
            provider="synthetic",
            covered_from="2030-01-01",
            covered_to="2030-01-28",
            native_accounts_json='["synthetic"]',
            captured_at="2030-03-01",
        )
        insert(
            c,
            "source_return_proofs",
            id=7,
            source_account="synthetic-account",
            native_account="synthetic",
            request_id="old-source-proof",
            request_fingerprint="3" * 64,
            proof_version="source_return_custody_v1",
            dependency_digest="4" * 64,
            evidence_json='{"synthetic": "byte-for-byte"}',
            confirmed_at="2030-03-01",
        )
        synthetic_generation = "5" * 64
        insert(c, "source_return_proof_dependencies", seq=9, token=synthetic_generation)
        assert c.execute("PRAGMA foreign_key_check").fetchall() == []
    return path


def state(path, columns=None):
    with sqlite3.connect(path) as c:
        inventory = c.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name"
        ).fetchall()
        if columns is None:
            columns = {
                name: [r[1] for r in c.execute(f'PRAGMA table_info("{name}")')]
                for kind, name, _, _ in inventory
                if kind == "table"
            }
        data = {
            name: sorted(
                (tuple(r) for r in c.execute(f'SELECT {", ".join(names)} FROM "{name}"')), key=repr
            )
            for name, names in columns.items()
        }
        return inventory, columns, data


def test_upgrade_preserves_every_old_column_proof_trigger_and_closed_fact(populated_0065):
    before, columns, values = state(populated_0065)
    command.upgrade(_alembic_config(populated_0065), NEW)
    after, _, current = state(populated_0065, columns)
    assert current.pop("alembic_version") == [(NEW,)]
    values.pop("alembic_version")
    current_seq = dict(current.pop("sqlite_sequence"))
    old_seq = dict(values.pop("sqlite_sequence"))
    assert current == values
    assert all(current_seq.get(k) == v for k, v in old_seq.items())
    assert current_seq["expected_cash_flows"] >= 2
    assert [r for r in before if r[0] == "trigger"] == [
        r for r in after if r[0] == "trigger" and not r[1].startswith("payout_")
    ]
    with sqlite3.connect(populated_0065) as c:
        assert c.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert c.execute("PRAGMA foreign_key_check").fetchall() == []
        assert c.execute(
            "SELECT payout_link_revision FROM expected_cash_flows ORDER BY id"
        ).fetchall() == [(0,), (0,)]
    command.downgrade(_alembic_config(populated_0065), OLD)
    _, _, restored = state(populated_0065, columns)
    assert restored["alembic_version"] == [(OLD,)]
    assert dict(restored["sqlite_sequence"]) == old_seq
    assert {
        k: v for k, v in restored.items() if k not in {"alembic_version", "sqlite_sequence"}
    } == values
    with pytest.raises(
        RuntimeError, match="cannot downgrade populated source return proof history"
    ):
        command.downgrade(_alembic_config(populated_0065), "0064_month_template_provenance")


@pytest.mark.parametrize("stage", [*schema.TABLES, "before_commit"])
def test_failure_after_each_rebuild_rolls_back_entire_0065(populated_0065, monkeypatch, stage):
    before = state(populated_0065)

    def fail(_connection, checkpoint):
        if checkpoint == stage:
            raise RuntimeError("synthetic-failure")

    monkeypatch.setattr(schema, "_checkpoint", fail)
    with pytest.raises(RuntimeError, match="synthetic-failure"):
        command.upgrade(_alembic_config(populated_0065), NEW)
    assert state(populated_0065) == before


@pytest.mark.parametrize(
    "ddl",
    [
        "DROP TRIGGER return_proof_reporting_months_update",
        "CREATE INDEX unknown_0065_index ON expected_cash_flows(notes)",
        "ALTER TABLE expected_cash_flows ADD COLUMN unknown_column INTEGER",
        "ALTER TABLE source_return_proofs ADD COLUMN unknown_column INTEGER",
        "ALTER TABLE source_return_proof_dependencies ADD COLUMN unknown_column INTEGER",
    ],
)
def test_schema_drift_aborts_before_first_ddl(populated_0065, ddl):
    with sqlite3.connect(populated_0065) as c:
        c.execute(ddl)
    before = state(populated_0065)
    with pytest.raises(RuntimeError, match="0066_.*schema_drift"):
        command.upgrade(_alembic_config(populated_0065), NEW)
    assert state(populated_0065) == before


def test_ecf_revision_aba_notes_and_counter_validation(populated_0065):
    command.upgrade(_alembic_config(populated_0065), NEW)
    with sqlite3.connect(populated_0065) as c:
        c.execute("UPDATE expected_cash_flows SET notes='nonmaterial' WHERE id=1")
        assert c.execute(
            "SELECT payout_link_revision FROM expected_cash_flows WHERE id=1"
        ).fetchone() == (0,)
        c.execute("UPDATE expected_cash_flows SET expected_net_amount_kopecks=101 WHERE id=1")
        c.execute("UPDATE expected_cash_flows SET expected_net_amount_kopecks=100 WHERE id=1")
        assert c.execute(
            "SELECT payout_link_revision FROM expected_cash_flows WHERE id=1"
        ).fetchone() == (2,)
        for sql in (
            "payout_link_revision=0",
            "payout_link_revision=5",
            "payout_link_revision=2.5",
            "payout_link_revision=3, expected_net_amount_kopecks=102",
        ):
            with pytest.raises(sqlite3.IntegrityError):
                c.execute(f"UPDATE expected_cash_flows SET {sql} WHERE id=1")
    before = state(populated_0065)
    with pytest.raises(RuntimeError, match="0066_cannot_downgrade_payout_history"):
        command.downgrade(_alembic_config(populated_0065), OLD)
    assert state(populated_0065) == before


def settlement_target(predecessor, retired=None):
    return {
        "investment_cash_flow_id": 1,
        "money_proof_request_id": "synthetic-money-v1",
        "applied_payout_id": 1,
        "expected_cash_flow_id": 1,
        "applied_payout_revision_id": 1,
        "provider_event_key": "a" * 64,
        "predecessor_id": predecessor,
        "predecessor_retirement_request_id": retired,
    }


def settlement_receipt(c, request, operation, revision, target, **overrides):
    proof = {
        "contract_version": "broker_payout_reconciliation_v1",
        "operation": operation,
        "base_request_id": "synthetic-base",
        "journal_revision": revision,
        "targets": [target],
    }
    proof.update(overrides)
    insert(
        c,
        "broker_month_applies",
        request_id=request,
        request_fingerprint="d" * 64,
        confirmation_digest="e" * 64,
        reporting_month_id=1,
        account_id=1,
        import_id=1,
        projection_json=json.dumps(proof),
        accepted_at="2030-03-01",
    )


def settlement_row(c, ident, request, predecessor):
    values = settlement_target(predecessor)
    values.pop("predecessor_id")
    values.pop("predecessor_retirement_request_id")
    insert(
        c,
        "applied_payout_reconciliations",
        id=ident,
        accepted_request_id=request,
        supersedes_id=predecessor,
        counting_decision="count_actual",
        created_at="2030-03-01",
        **values,
    )


@pytest.fixture
def accepted_actual(populated_0065):
    command.upgrade(_alembic_config(populated_0065), NEW)
    with sqlite3.connect(populated_0065) as c:
        c.execute("PRAGMA foreign_keys=ON")
        settlement_receipt(c, "R1", "link", 2, settlement_target(1))
        c.execute("UPDATE applied_payout_reconciliations SET retired_request_id='R1' WHERE id=1")
        settlement_row(c, 3, "R1", 1)
    return populated_0065


def retire(c, request, revision, relation):
    settlement_receipt(
        c, request, "retire", revision, {"investment_cash_flow_id": 1, "relation_id": relation}
    )
    c.execute(
        "UPDATE applied_payout_reconciliations SET retired_request_id=? WHERE id=?",
        (request, relation),
    )


def test_separate_retirement_reaffirmation_and_terminal_five_receipt_chain(accepted_actual):
    old = state(accepted_actual)[2]
    with sqlite3.connect(accepted_actual) as c:
        c.execute("PRAGMA foreign_keys=ON")
        retire(c, "R2", 3, 3)
        r1 = c.execute("SELECT * FROM applied_payout_reconciliations WHERE id=3").fetchone()
        settlement_receipt(c, "R3", "reaffirm", 4, settlement_target(3, "R2"))
        settlement_row(c, 4, "R3", 3)
        assert c.execute("SELECT * FROM applied_payout_reconciliations WHERE id=3").fetchone() == r1
        retire(c, "R4", 5, 4)
        settlement_receipt(c, "R5", "reaffirm", 6, settlement_target(4, "R4"))
        settlement_row(c, 5, "R5", 4)
        assert c.execute(
            "SELECT id,accepted_request_id,retired_request_id,supersedes_id FROM applied_payout_reconciliations WHERE investment_cash_flow_id=1 ORDER BY id"
        ).fetchall() == [(3, "R1", "R2", 1), (4, "R3", "R4", 3), (5, "R5", None, 4)]
        assert c.execute("PRAGMA foreign_key_check").fetchall() == []
    current = state(accepted_actual)[2]
    for table in (
        "investment_cash_flows",
        "broker_money_occurrence_owners",
        "reporting_months",
        "source_return_proofs",
        "source_return_proof_dependencies",
        "expected_cash_flows",
        "applied_provider_payouts",
    ):
        assert current[table] == old[table]
    assert set(old["broker_month_applies"]).issubset(current["broker_month_applies"])


def test_live_actual_atomic_replacement_does_not_rewrite_old_receipt(accepted_actual):
    original = state(accepted_actual)[2]["broker_month_applies"]
    with sqlite3.connect(accepted_actual) as c:
        c.execute("PRAGMA foreign_keys=ON")
        settlement_receipt(c, "R3", "reaffirm", 4, settlement_target(3))
        c.execute("UPDATE applied_payout_reconciliations SET retired_request_id='R3' WHERE id=3")
        settlement_row(c, 4, "R3", 3)
        assert c.execute(
            "SELECT id FROM applied_payout_reconciliations WHERE investment_cash_flow_id=1 AND retired_request_id IS NULL"
        ).fetchall() == [(4,)]
        assert c.execute(
            "SELECT retired_request_id FROM applied_payout_reconciliations WHERE id=3"
        ).fetchone() == ("R3",)
        assert c.execute("PRAGMA foreign_key_check").fetchall() == []
    assert set(original).issubset(state(accepted_actual)[2]["broker_month_applies"])


@pytest.mark.parametrize(
    "mutation",
    [
        {"operation": "distinct"},
        {"base_request_id": "other-source"},
        {"contract_version": "broker_money_v1"},
        {"journal_revision": 2},
        {"targets": [{"investment_cash_flow_id": 2, "relation_id": 3}]},
        {"targets": [{"investment_cash_flow_id": 1, "relation_id": 1}]},
    ],
)
def test_invalid_retirement_receipt_rolls_back_every_effect(accepted_actual, mutation):
    before = state(accepted_actual)
    with pytest.raises(sqlite3.IntegrityError, match="actual_payout_history_is_immutable"):
        with sqlite3.connect(accepted_actual) as c:
            c.execute("PRAGMA foreign_keys=ON")
            proof = {
                "operation": "retire",
                "journal_revision": 3,
                "targets": [{"investment_cash_flow_id": 1, "relation_id": 3}],
                **mutation,
            }
            settlement_receipt(
                c,
                "bad-R2",
                proof.pop("operation"),
                proof.pop("journal_revision"),
                proof.pop("targets")[0],
                **proof,
            )
            c.execute(
                "UPDATE applied_payout_reconciliations SET retired_request_id='bad-R2' WHERE id=3"
            )
    assert state(accepted_actual) == before


@pytest.mark.parametrize("live", [False, True])
@pytest.mark.parametrize("checkpoint", ["receipt", "retirement", "new_row"])
def test_reaffirm_failure_full_transaction_rollback(accepted_actual, live, checkpoint):
    if not live:
        with sqlite3.connect(accepted_actual) as c:
            retire(c, "R2", 3, 3)
    before = state(accepted_actual)
    with pytest.raises(RuntimeError, match="synthetic-stop"):
        with sqlite3.connect(accepted_actual) as c:
            c.execute("PRAGMA foreign_keys=ON")
            settlement_receipt(c, "R3", "reaffirm", 4, settlement_target(3, None if live else "R2"))
            if checkpoint == "receipt":
                raise RuntimeError("synthetic-stop")
            if live:
                c.execute(
                    "UPDATE applied_payout_reconciliations SET retired_request_id='R3' WHERE id=3"
                )
            if checkpoint == "retirement":
                raise RuntimeError("synthetic-stop")
            settlement_row(c, 4, "R3", 3)
            raise RuntimeError("synthetic-stop")
    assert state(accepted_actual) == before


def test_fork_revival_reuse_wrong_retirement_and_nonincreasing_sequence_block(accepted_actual):
    with sqlite3.connect(accepted_actual) as c:
        retire(c, "R2", 3, 3)
    before = state(accepted_actual)
    for retired, revision in ((None, 4), ("R1", 4), ("missing", 4), ("R2", 3), ("R2", 2)):
        with pytest.raises(sqlite3.IntegrityError, match="actual_payout_proof_scope_invalid"):
            with sqlite3.connect(accepted_actual) as c:
                c.execute("PRAGMA foreign_keys=ON")
                settlement_receipt(c, "bad-R3", "reaffirm", revision, settlement_target(3, retired))
                settlement_row(c, 4, "bad-R3", 3)
        assert state(accepted_actual) == before

    with sqlite3.connect(accepted_actual) as c:
        settlement_receipt(c, "R3", "reaffirm", 4, settlement_target(3, "R2"))
        settlement_row(c, 4, "R3", 3)
        retire(c, "R4", 5, 4)
    before = state(accepted_actual)
    with pytest.raises(sqlite3.IntegrityError, match="actual_payout_proof_scope_invalid"):
        with sqlite3.connect(accepted_actual) as c:
            settlement_receipt(c, "bad-R5", "reaffirm", 6, settlement_target(3, "R2"))
            settlement_row(c, 5, "bad-R5", 3)
    assert state(accepted_actual) == before
    for assignment in ("NULL", "'R3'", "'R2'"):
        with pytest.raises(sqlite3.IntegrityError, match="actual_payout_history_is_immutable"):
            with sqlite3.connect(accepted_actual) as c:
                c.execute(
                    f"UPDATE applied_payout_reconciliations SET retired_request_id={assignment} WHERE id=3"
                )
        assert state(accepted_actual) == before


def test_fresh_metadata_matches_migrated_constraints_indices_guards_and_is_idempotent(
    populated_0065, tmp_path
):
    from hermes_finance.database import create_database
    from hermes_finance.persistence import Base

    command.upgrade(_alembic_config(populated_0065), NEW)
    fresh = create_database(tmp_path / "fresh.db")
    try:
        Base.metadata.create_all(fresh.engine)
        Base.metadata.create_all(fresh.engine)
        with sqlite3.connect(populated_0065) as migrated, fresh.engine.connect() as connection:
            for table in schema.TABLES:
                expected = migrated.execute(
                    "SELECT sql FROM sqlite_schema WHERE type='table' AND name=?", (table,)
                ).fetchone()[0]
                observed = connection.exec_driver_sql(
                    "SELECT sql FROM sqlite_schema WHERE type='table' AND name=?", (table,)
                ).scalar_one()

                def checks(sql):
                    return sorted(
                        part.replace(" (", "(")
                        for part in schema._signature(sql)
                        if part.startswith("CONSTRAINT ck_")
                    )

                assert checks(observed) == checks(expected)

                def columns(rows):
                    return sorted(tuple(row)[1:] for row in rows)

                assert columns(
                    connection.exec_driver_sql(f"PRAGMA table_info({table})")
                ) == columns(migrated.execute(f"PRAGMA table_info({table})"))
                assert ("AUTOINCREMENT" in observed) == ("AUTOINCREMENT" in expected)
                assert sorted(
                    tuple(r)[2:]
                    for r in connection.exec_driver_sql(f"PRAGMA foreign_key_list({table})")
                ) == sorted(
                    tuple(r)[2:] for r in migrated.execute(f"PRAGMA foreign_key_list({table})")
                )
            for name, body in schema.guard_sql().items():
                observed = connection.exec_driver_sql(
                    "SELECT sql FROM sqlite_schema WHERE type='trigger' AND name=?", (name,)
                ).scalar_one()
                assert schema._signature(observed) == schema._signature(
                    f"CREATE TRIGGER {name} {body}"
                )
            expected_indices = [schema._signature(sql) for sql in schema.index_sql()]
            actual_indices = [
                schema._signature(sql)
                for (sql,) in connection.exec_driver_sql(
                    "SELECT sql FROM sqlite_schema WHERE type='index' AND tbl_name='applied_payout_reconciliations' AND sql IS NOT NULL"
                )
            ]

            def compact(sql):
                return sql.replace(" (", "(").replace(", ", ",")

            assert sorted(map(compact, actual_indices)) == sorted(map(compact, expected_indices))
    finally:
        fresh.engine.dispose()


@pytest.mark.parametrize(
    "contract",
    ["broker_money_v2", "broker_payout_reconciliation_v1", "broker_payout_dependency_v1"],
)
def test_each_new_receipt_forbids_downgrade_before_ddl(populated_0065, contract):
    command.upgrade(_alembic_config(populated_0065), NEW)
    with sqlite3.connect(populated_0065) as c:
        settlement_receipt(
            c, "new-history", "retire", 2, {"investment_cash_flow_id": 1}, contract_version=contract
        )
    before = state(populated_0065)
    with pytest.raises(RuntimeError, match="0066_cannot_downgrade_payout_history"):
        command.downgrade(_alembic_config(populated_0065), OLD)
    assert state(populated_0065) == before


@pytest.mark.parametrize(
    "table,clause",
    [
        ("investment_cash_flows", "id=1"),
        ("expected_cash_flows", "id=1"),
        ("applied_provider_payouts", "id=1"),
        ("applied_payout_revisions", "id=1"),
        ("broker_month_applies", "request_id='R1'"),
        ("broker_month_applies", "request_id='synthetic-money-v1'"),
        ("applied_payout_reconciliations", "id=1"),
        ("applied_payout_reconciliations", "id=3"),
    ],
)
def test_retained_parent_and_history_delete_never_cascade(accepted_actual, table, clause):
    before = state(accepted_actual)
    with pytest.raises(sqlite3.IntegrityError):
        with sqlite3.connect(accepted_actual) as c:
            c.execute("PRAGMA foreign_keys=ON")
            c.execute(f"DELETE FROM {table} WHERE {clause}")
    assert state(accepted_actual) == before


def test_counter_exhaustion_and_delete_reinsert_do_not_reuse_revision_identity(populated_0065):
    command.upgrade(_alembic_config(populated_0065), NEW)
    with sqlite3.connect(populated_0065) as c:
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("DELETE FROM applied_payout_reconciliations WHERE id=1")
        c.execute("DELETE FROM expected_cash_flows WHERE id=1")
        c.execute("""INSERT INTO expected_cash_flows (reporting_month_id,account_id,instrument_id,flow_type,expected_date,gross_amount_kopecks,expected_net_amount_kopecks,source,source_as_of_date,forecast_version)
                     VALUES (1,1,1,'coupon','2030-03-01',113,100,'synthetic','2030-01-28','new')""")
        assert c.execute("SELECT max(id) FROM expected_cash_flows").fetchone()[0] > 2
        # Counter manipulation itself is blocked, including integer overflow/REAL.
        for value in ("9223372036854775807", "9223372036854775808", "-1", "NULL", "'bad'"):
            with pytest.raises(sqlite3.IntegrityError):
                c.execute(f"UPDATE expected_cash_flows SET payout_link_revision={value} WHERE id=3")


def test_historical_correction_guard_is_required_before_first_ddl(populated_0065):
    with sqlite3.connect(populated_0065) as connection:
        connection.execute("DROP TRIGGER mybroker_correction_revisions_update")
    _assert_preflight_zero_write_stop(populated_0065)


def _assert_preflight_zero_write_stop(populated_0065):
    from sqlalchemy import Engine, event

    before = state(populated_0065)
    raw = populated_0065.read_bytes()
    ddl = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().split()[0].upper() in {"CREATE", "ALTER", "DROP"}:
            ddl.append(statement)

    event.listen(Engine, "before_cursor_execute", capture)
    try:
        with pytest.raises(RuntimeError, match="0066_.*schema_drift"):
            command.upgrade(_alembic_config(populated_0065), NEW)
    finally:
        event.remove(Engine, "before_cursor_execute", capture)
    assert ddl == []
    assert state(populated_0065) == before
    assert populated_0065.read_bytes() == raw


@pytest.mark.parametrize("change", ["missing", "modified"])
def test_every_released_trigger_and_explicit_index_is_mandatory(populated_0065, change):
    from sqlalchemy import create_engine, event

    raw = populated_0065.read_bytes()
    engine = create_engine("sqlite:///" + str(populated_0065))
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            schema._check_released_guard_graph(connection, upgrade=True)
            objects = connection.exec_driver_sql(
                "SELECT type,name,tbl_name,sql FROM sqlite_schema "
                "WHERE type IN ('trigger','index') AND sql IS NOT NULL ORDER BY type,name"
            ).all()
            assert sum(row[0] == "trigger" for row in objects) == 136
            ddl = []

            def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
                if statement.lstrip().split()[0].upper() in {"CREATE", "ALTER", "DROP"}:
                    ddl.append(statement)

            event.listen(connection, "before_cursor_execute", capture)
            for kind, name, table, _ in objects:
                connection.exec_driver_sql("SAVEPOINT damaged_guard")
                connection.exec_driver_sql(f'DROP {kind.upper()} "{name}"')
                if change == "modified":
                    if kind == "trigger":
                        replacement = (
                            f'CREATE TRIGGER "{name}" BEFORE UPDATE ON "{table}" '
                            "BEGIN SELECT 1; END"
                        )
                    else:
                        column = connection.exec_driver_sql(
                            f'PRAGMA table_info("{table}")'
                        ).first()[1]
                        replacement = f'CREATE INDEX "{name}" ON "{table}" ("{column}")'
                    connection.exec_driver_sql(replacement)
                before = schema._inventory(connection)
                columns = {
                    row[1]: [
                        c[1] for c in connection.exec_driver_sql(f'PRAGMA table_info("{row[1]}")')
                    ]
                    for row in before
                    if row[0] == "table"
                }
                values = schema._snapshot(connection, columns)
                ddl.clear()
                with pytest.raises(RuntimeError, match="0066_.*schema_drift"):
                    schema.migrate(connection, upgrade=True)
                assert ddl == [], (change, kind, name)
                assert schema._inventory(connection) == before, (change, kind, name)
                assert schema._snapshot(connection, columns) == values, (change, kind, name)
                connection.exec_driver_sql("ROLLBACK TO damaged_guard")
                connection.exec_driver_sql("RELEASE damaged_guard")
            connection.rollback()
    finally:
        engine.dispose()
    assert populated_0065.read_bytes() == raw


def test_implicit_unique_index_key_drift_is_not_hidden_by_null_sql(populated_0065):
    table = "mybroker_disposition_revisions"
    with sqlite3.connect(populated_0065) as connection:
        graph_sql = "SELECT type,name,tbl_name,sql FROM sqlite_schema WHERE type IN ('index','trigger') ORDER BY type,name"
        before_graph = connection.execute(graph_sql).fetchall()
        sql = connection.execute("SELECT sql FROM sqlite_schema WHERE name=?", (table,)).fetchone()[
            0
        ]
        assert "UNIQUE (import_id, isin, revision)" in sql
        triggers = connection.execute(
            "SELECT sql FROM sqlite_schema WHERE type='trigger' AND tbl_name=?", (table,)
        ).fetchall()
        assert connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone() == (0,)
        connection.execute(f'DROP TABLE "{table}"')
        connection.execute(
            sql.replace("UNIQUE (import_id, isin, revision)", "UNIQUE (revision, isin, import_id)")
        )
        for (guard,) in triggers:
            connection.execute(guard)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute(graph_sql).fetchall() == before_graph
    _assert_preflight_zero_write_stop(populated_0065)
