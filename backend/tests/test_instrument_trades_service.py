"""Synthetic canonical inventory / effective Money / query-only GET contract."""

import json
from datetime import date

import pytest
from sqlalchemy import event, select, text
from test_statement_import_apply import sqlite_blob
from test_statement_import_executed_trades import accept_source, identity, mutate, promote
from test_statement_import_mybroker import FILENAME, fixture
from test_statement_import_mybroker import database as database
from test_statement_import_mybroker_endpoints import (
    _money_apply,
    _money_setup,
    _stock_decide,
    _stock_setup,
    _trade_decide,
    stock_fee_xml,
    trade_money_xml,
)

from hermes_finance.persistence import (
    BrokerIdentityMapping,
    ExecutedTrade,
    Instrument,
    ReportingMonth,
)
from hermes_finance.services.accounts import create_account
from hermes_finance.services.broker_identity_mappings import revoke_mapping
from hermes_finance.services.instrument_trades import known_instrument_trades

A, B = date(2029, 12, 31), date(2030, 1, 31)


def setup_stock(database, **kwargs):
    client, xml, intent, _ = _stock_setup(database, stock_fee_xml(**kwargs))
    originals = [(FILENAME, xml)]
    with database.session_factory() as session:
        _money_apply(session, _stock_decide(session, intent, originals), originals)
        instrument = session.scalar(select(ExecutedTrade.instrument_id))
    return client, intent, instrument


def read(session, account=1, instrument=1, t0=A, t1=B):
    return known_instrument_trades(session, account, instrument, t0, t1)


def values(row):
    return {leg["role"]: leg["signed_rub"] for leg in row["cash_legs"]}


def test_stock_two_effective_legs_closed_read_zero_dml_and_strict_api(database):
    client, intent, instrument = setup_stock(database)
    with database.session_factory() as session:
        session.get(ReportingMonth, intent.reporting_month_id).status = "closed"
        session.commit()
        before = sqlite_blob(database)
        statements = []

        def capture(_conn, _cursor, statement, *_args):
            statements.append(statement)

        event.listen(database.engine, "before_cursor_execute", capture)
        try:
            result = read(session, intent.account_id, instrument)
            params = {"account_id": intent.account_id, "t0": str(A), "t1": str(B)}
            response = client.get(f"/api/instruments/{instrument}/known-trades", params=params)
        finally:
            event.remove(database.engine, "before_cursor_execute", capture)
        assert response.status_code == 200, response.text
        assert response.json() == result
        assert not any(
            s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "REPLACE"))
            for s in statements
        )
        assert sqlite_blob(database) == before
        assert result["known_count"] == 1
        row = result["events"][0]
        assert values(row) == {"settlement": "-100.00", "paid_nkd": None, "commission": "-1.25"}
        assert row["side"] == "BUY" and row["signed_quantity"] == "1"
        assert (
            row["currentness"] == "current"
            and row["historical_identity"]["instrument_type"] == "stock"
        )
        assert row["cash_legs"][0]["signed_kopecks"] == "-10000"
        assert row["cash_legs"][0]["proof_class"] == "effective_cash_leg_authority"
        assert row["cash_legs"][0]["occurrences"]
        assert result["dependency_fingerprint"] is None
        assert result["trade_history_completeness"] == result["financial_coverage"] == "unknown"
        assert (
            client.post(f"/api/instruments/{instrument}/known-trades", json=params).status_code
            == 405
        )
        for change, status in [
            ({"t0": str(B)}, 422),
            ({"t1": "oops"}, 422),
            ({"account_id": 999}, 404),
        ]:
            assert (
                client.get(
                    f"/api/instruments/{instrument}/known-trades", params={**params, **change}
                ).status_code
                == status
            )


@pytest.mark.parametrize("inclusive", [True, False])
def test_bond_three_effective_legs_and_dates(database, inclusive):
    client, xml, intent, bond, _ = _money_setup(database, trade_money_xml(inclusive=inclusive))
    originals = [(FILENAME, xml)]
    with database.session_factory() as session:
        _money_apply(
            session, _trade_decide(session, intent, originals, inclusive=inclusive), originals
        )
        row = read(session, intent.account_id, bond)["events"][0]
        assert values(row) == {
            "settlement": "-10000.00",
            "paid_nkd": "-125.50",
            "commission": "-10.00",
        }
        assert row["execution_date"] == "2030-01-15"
        assert row["settlement_date"] == row["depository_date"] == "2030-01-17"
        assert all(leg["receipt_id"] for leg in row["cash_legs"])


def test_equal_money_date_distinct_native_ids_remain_two(database):
    _, intent, instrument = setup_stock(database, second=True)
    with database.session_factory() as session:
        result = read(session, intent.account_id, instrument)
        assert result["known_count"] == 2
        assert len({tuple(r["native_ids"]) for r in result["events"]}) == 2
        assert [values(r)["commission"] for r in result["events"]] == ["-1.25"] * 2


def test_overlapping_native_occurrences_one_canonical_execution_no_zero_fee(database):
    with database.session_factory() as session:
        key = identity(accept_source(session, fixture(duplicate=True)))
        promote(session, [key])
        accept_source(session, fixture(), "Брокерский 1234567 (01.01.30-28.02.30).xml")
        stale = read(session)["events"][0]
        assert stale["currentness"] == "unavailable"
        promote(session, [key])
        result = read(session)
        assert result["known_count"] == 1
        assert len(result["events"][0]["source_occurrences"]) == 3
        assert all(v is None for v in values(result["events"][0]).values())


@pytest.mark.parametrize(
    "t0,t1,execution,settlement",
    [
        (date(2030, 1, 14), date(2030, 1, 15), True, False),
        (date(2030, 1, 15), date(2030, 1, 17), False, True),
    ],
)
def test_boundary_crossings_independent_date_placement(database, t0, t1, execution, settlement):
    _, intent, instrument = setup_stock(database)
    with database.session_factory() as session:
        row = read(session, intent.account_id, instrument, t0, t1)["events"][0]
        assert row["execution_in_interval"] is execution
        assert row["settlement_in_interval"] is settlement
        assert row["cash_legs"][0]["in_interval"] is settlement


def test_pending_to_settled_requires_revision_then_same_identity(database):
    with database.session_factory() as session:
        key = identity(accept_source(session, fixture(pending=True)))
        promote(session, [key])
        row = read(session)["events"][0]
        assert row["lifecycle"] == "pending" and row["settlement_date"] is None
        assert row["planned_settlement_date"] == "2030-01-17"
        accept_source(session, fixture(), "Брокерский 1234567 (01.01.30-28.02.30).xml")
        assert read(session)["events"][0]["currentness"] == "unavailable"
        promote(session, [key])
        row = read(session)["events"][0]
        assert row["lifecycle"] == "settled" and row["revision"] == 2


def test_partial_sell_observed_without_cash_or_inferred_nkd_tax_fee(database):
    with database.session_factory() as session:
        key = identity(accept_source(session, fixture(qty="-0.25", money=False)))
        promote(session, [key])
        row = read(session)["events"][0]
        assert row["side"] == "SELL" and row["signed_quantity"] == "-0.25"
        assert all(v is None for v in values(row).values())
        assert "sell_cash_authority_unsupported" in row["cash_legs"][0]["reason_codes"]


def test_inactive_instrument_other_account_instrument_empty_and_cap(database, monkeypatch):
    _, intent, instrument = setup_stock(database)
    with database.session_factory() as session:
        session.get(Instrument, instrument).is_active = False
        session.commit()
        assert read(session, intent.account_id, instrument)["known_count"] == 1
        other = create_account(session, name="Other synthetic", account_type="iis")
        result = read(session, other.id, instrument)
        assert result["known_count"] == 0 and result["events"] == []
        assert "no_known_trades_not_zero_activity" in result["reason_codes"]
        monkeypatch.setattr("hermes_finance.services.instrument_trades.CAPACITY", 0)
        result = read(session, intent.account_id, instrument)
        assert result["status"] == "capacity_exceeded"
        assert result["known_count"] is None and result["events"] == []


def test_mapping_revocation_and_catalogue_aba_drop_cash_authority(database):
    _, intent, instrument = setup_stock(database)
    with database.session_factory() as session:
        before = read(session, intent.account_id, instrument)
        item = session.get(Instrument, instrument)
        item.currency = "USD"
        session.commit()
        item.currency = "RUB"
        session.commit()
        after = read(session, intent.account_id, instrument)
        assert before["dependency_digest"] != after["dependency_digest"]
        assert after["dependency_fingerprint"] is None
        assert all(v is None for v in values(after["events"][0]).values())
        mapping = session.scalar(
            select(BrokerIdentityMapping).where(BrokerIdentityMapping.subject_kind == "instrument")
        )
        revoke_mapping(session, mapping.id)
        result = read(session, intent.account_id, instrument)
        assert result["events"][0]["currentness"] == "unavailable"
        assert all(v is None for v in values(result["events"][0]).values())


def test_missing_native_date_or_side_is_unavailable_never_guessed(database):
    with database.session_factory() as session:
        key = identity(accept_source(session, fixture()))
        promote(session, [key])
        trade = session.scalar(select(ExecutedTrade))
        core = json.loads(trade.core_json)
        core["trade_time"], core["quantity"] = None, "0"
        trade.core_json = json.dumps(core)
        session.commit()
        row = read(session)["events"][0]
        assert row["execution_date"] is None and row["side"] is None
        assert row["signed_quantity"] is None
        assert "execution_date_unavailable" in row["reason_codes"]


def test_missing_money_ownership_blocks_all_legs_without_guessing(database):
    _, intent, instrument = setup_stock(database)
    # Adversarial SQL simulates damaged ownership; production ORM forbids deletion.
    with database.engine.begin() as connection:
        connection.execute(text("DELETE FROM executed_trade_occurrences WHERE section = 'money'"))
    with database.session_factory() as session:
        row = read(session, intent.account_id, instrument)["events"][0]
        assert all(v is None for v in values(row).values())
        assert "money_ownership_changed" in row["cash_legs"][0]["reason_codes"]


def test_one_committed_snapshot_across_inventory_money_and_mapping(database):
    _, intent, instrument = setup_stock(database)
    with database.engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA journal_mode=WAL")
    with database.session_factory() as session:
        before = read(session, intent.account_id, instrument)
        changed = False

        def mutate_after_inventory(_conn, _cursor, statement, *_args):
            nonlocal changed
            if not changed and statement.startswith("SELECT executed_trades"):
                changed = True
                with database.session_factory() as other:
                    row = other.get(Instrument, instrument)
                    row.name = "Synthetic concurrent catalogue edit"
                    other.commit()

        event.listen(database.engine, "after_cursor_execute", mutate_after_inventory)
        try:
            coherent = read(session, intent.account_id, instrument)
        finally:
            event.remove(database.engine, "after_cursor_execute", mutate_after_inventory)
        assert changed and coherent == before
        after = read(session, intent.account_id, instrument)
        assert after["dependency_digest"] != before["dependency_digest"]
        assert all(v is None for v in values(after["events"][0]).values())


def test_stale_source_aba_keeps_money_retired_and_digest_changes(database):
    from hermes_finance.persistence import MyBrokerImport

    _, intent, instrument = setup_stock(database)
    with database.session_factory() as session:
        before = read(session, intent.account_id, instrument)
        source = session.scalar(select(MyBrokerImport))
        original = source.mappings_json
        source.mappings_json = "[]"
        session.commit()
        assert (
            read(session, intent.account_id, instrument)["events"][0]["currentness"]
            == "unavailable"
        )
        source.mappings_json = original
        session.commit()
        after = read(session, intent.account_id, instrument)
        assert before["dependency_digest"] != after["dependency_digest"]
        assert after["dependency_fingerprint"] is None
        assert all(v is None for v in values(after["events"][0]).values())


def test_unaccepted_native_and_unknown_money_are_explicit_gaps(database):
    with database.session_factory() as session:
        accept_source(session, fixture(missing_id=True, unsupported=True))
        result = read(session)
        assert result["known_count"] == 0
        assert "unaccepted_native_execution_rows" in result["reason_codes"]
        assert "4_Transfers_unsupported" in result["reason_codes"]


def test_prior_month_buy_identity_requires_effective_narrow_money_proof(database):
    _, intent, instrument = setup_stock(database, prior_month_buy=True)
    with database.session_factory() as session:
        row = read(session, intent.account_id, instrument)["events"][0]
        assert row["execution_in_interval"] is False
        assert row["historical_identity"]["instrument_type"] == "stock"
        assert values(row)["commission"] == "-1.25"
        item = session.get(Instrument, instrument)
        item.name = "Synthetic proof retirement"
        session.commit()
        row = read(session, intent.account_id, instrument)["events"][0]
        assert row["historical_identity"] is None
        assert all(v is None for v in values(row).values())


def test_prior_identity_keeps_later_partial_sale_selectable_without_cash_authority(database):
    _, intent, instrument = setup_stock(database)
    with database.session_factory() as session:
        raw = mutate(
            fixture(qty="-0.25", primary="10000000009", secondary="2000000009", money=False),
            db_time="15.02.2030 9:00:00",
            save_settlement_date="17.02.2030",
            save_depo_settlement_date="17.02.2030",
            settlement_time="17.02.2030 10:00:00",
        )
        key = identity(accept_source(session, raw, "Брокерский 1234567 (01.02.30-28.02.30).xml"))
        promote(session, [key])
        session.get(Instrument, instrument).is_active = False
        session.commit()
        result = read(session, intent.account_id, instrument, date(2030, 1, 31), date(2030, 2, 28))
        assert result["known_count"] == 1
        row = result["events"][0]
        assert row["side"] == "SELL" and row["signed_quantity"] == "-0.25"
        assert row["historical_identity"]["instrument_type"] == "stock"
        assert all(v is None for v in values(row).values())


def test_corrective_mapping_same_transaction_aba_drops_old_execution_revision(database):
    from test_statement_import_mybroker_dispositions import (
        SKIP,
        correction_accept,
        correction_decisions,
        correction_source,
        correction_targets,
    )

    with database.session_factory() as session:
        source = correction_source(session, [SKIP])
        correction_targets(session, [SKIP])
        decisions = correction_decisions(session, [source["import_id"]])
        correction_accept(session, decisions)
        key = next(t["identity"] for t in source["document"]["trades"] if t["core"]["isin"] == SKIP)
        trade = promote(session, [key])["trades"][0]
        before = read(session, trade["account_id"], trade["instrument_id"])
        assert before["events"][0]["currentness"] == "current"
        for status in ("revoked", "effective"):
            session.execute(
                text(
                    "UPDATE broker_identity_mappings SET status=:status, "
                    "revoked_at=CASE WHEN :status='revoked' THEN CURRENT_TIMESTAMP ELSE NULL END WHERE id=:id"
                ),
                {"status": status, "id": decisions[0]["mapping_id"]},
            )
        session.commit()
        retired = read(session, trade["account_id"], trade["instrument_id"])
        assert retired["events"][0]["currentness"] == "unavailable"
        assert retired["dependency_digest"] != before["dependency_digest"]
        correction_accept(
            session, correction_decisions(session, [source["import_id"]]), "synthetic-remap"
        )
        revised = read(session, trade["account_id"], trade["instrument_id"])
        assert revised["events"][0]["currentness"] == "unavailable"
        assert "source_enrichment_not_accepted" in revised["events"][0]["reason_codes"]
        assert revised["dependency_fingerprint"] is None
        assert all(v is None for v in values(revised["events"][0]).values())
