"""Synthetic S2-A execution truth, selected-set atomicity and stale dependencies."""

import json
import sqlite3
from copy import deepcopy
from datetime import date
from decimal import localcontext
from uuid import uuid4
from xml.etree import ElementTree as ET

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from test_statement_import_mybroker import (
    ACCOUNT,
    FILENAME,
    apply,
    fixture,
    include_source_account,
    preview,
    repo_fixture,
)
from test_statement_import_mybroker import database as database

from hermes_finance.main import create_app
from hermes_finance.persistence import (
    BrokerIdentityMapping,
    CashBalance,
    ClassNoCrossingCoverage,
    ExecutedTrade,
    ExecutedTradeApply,
    ExecutedTradeOccurrence,
    ExecutedTradeRevision,
    ExternalFlow,
    Instrument,
    InvestmentCashFlow,
    MyBrokerImport,
    PositionSnapshot,
    ReportingMonth,
)
from hermes_finance.services.broker_identity_mappings import revoke_mapping
from hermes_finance.services.class_endpoint_eligibility import class_endpoint_eligibility
from hermes_finance.services.executed_trades import (
    _minor,
    apply_executed_trades,
    preview_executed_trades,
    read_executed_trades,
    unresolved_execution_ids,
)
from hermes_finance.statement_import.mybroker import MyBrokerError, canonical


def accept_source(session, xml=None, filename=FILENAME):
    xml = fixture() if xml is None else xml
    return apply(session, xml, preview(session, xml, filename), filename)


def promote(session, identities, request_id=None, reviewed=None):
    reviewed = reviewed or preview_executed_trades(session, identities)
    return apply_executed_trades(
        session,
        identities=identities,
        confirmation_digest=reviewed["confirmation_digest"],
        request_id=request_id or uuid4().hex,
    )


def identity(source):
    return source["document"]["trades"][0]["identity"]


def mutate(xml, **fields):
    root = ET.fromstring(xml)
    row = root.find(
        ".//{MyBroker}Trades/{MyBroker}Report/{MyBroker}Tablix2/"
        "{MyBroker}Details_Collection/{MyBroker}Details"
    )
    for key, value in fields.items():
        if value is None:
            row.attrib.pop(key, None)
        else:
            row.set(key, value)
    return ET.tostring(root)


def count(session, model):
    return session.scalar(select(func.count()).select_from(model))


def test_b_repo_observations_have_no_s2_identity_or_cash_and_regular_trade_survives(database):
    with database.session_factory() as session:
        source = accept_source(session, repo_fixture(pair=True, mixed=True, duplicate=True))
        rows = source["document"]["trades"]
        key = rows[-1]["identity"]
        assert all(t["identity"] is None for t in rows[:-1])
        assert all(t["cash_legs"] == [] for t in rows[:-1])
        with pytest.raises(MyBrokerError, match="source_trade_not_found"):
            preview_executed_trades(session, ["B1001"])
        trade = promote(session, [key])["trades"][0]
        assert trade["source_identity"] == key
        assert len(trade["evidence"]["cash_legs"]) == 1
        assert count(session, ExecutedTrade) == 1
        assert count(session, ExecutedTradeOccurrence) == 1


def test_overlapping_duplicate_is_one_execution_one_cash_leg_separate_occurrences(database):
    with database.session_factory() as session:
        source = accept_source(session, fixture(duplicate=True))
        key = identity(source)
        result = promote(session, [key])
        trade = result["trades"][0]
        assert trade["evidence"]["fee_basis"] == "zero"
        assert trade["evidence"]["event_c1"] is None
        assert len(trade["evidence"]["occurrences"]) == 2
        assert len(trade["evidence"]["cash_legs"]) == 1
        leg = trade["evidence"]["cash_legs"][0]
        assert (leg["amount_minor"], leg["direction"]) == (100000, "debit")
        assert not trade["financial_ready"]
        # Different document/range adds lineage, never another economic leg.
        accept_source(session, fixture(), "Брокерский 1234567 (01.01.30-28.02.30).xml")
        assert (
            "source_enrichment_not_accepted"
            in read_executed_trades(session)["trades"][0]["conflicts"]
        )
        enriched = promote(session, [key])["trades"][0]
        assert enriched["revision"] == 2
        assert len(enriched["evidence"]["occurrences"]) == 3
        assert len(enriched["evidence"]["cash_legs"]) == 1
        assert len(enriched["evidence"]["cash_legs"][0]["occurrences"]) == 2
        assert count(session, ExecutedTrade) == 1
        assert count(session, ExecutedTradeOccurrence) == 3
        assert promote(session, [key])["trades"][0]["revision"] == 2
        for model in (
            ReportingMonth,
            PositionSnapshot,
            CashBalance,
            ExternalFlow,
            InvestmentCashFlow,
        ):
            assert count(session, model) == 0
    with database.session_factory() as independent:
        reread = read_executed_trades(independent)["trades"][0]
        assert reread == enriched
        assert reread["conflicts"] == []


def test_pending_to_settled_frozen_core_distinct_actual_dates_and_append_only_revision(database):
    with database.session_factory() as session:
        key = identity(accept_source(session, fixture(pending=True)))
        first = promote(session, [key])["trades"][0]
        assert first["evidence"]["lifecycle"] == "pending"
        assert first["evidence"]["settlement_date"] is None
        assert first["evidence"]["planned_dates"]["settlement_date"] == "2030-01-17"
        assert first["evidence"]["cash_legs"] == []
        assert first["evidence"]["fee_basis"] == "unknown"
        before_core = session.get(ExecutedTrade, first["trade_id"]).core_json
        accept_source(session, fixture(), "Брокерский 1234567 (01.01.30-28.02.30).xml")
        second = promote(session, [key])["trades"][0]
        assert second["trade_id"] == first["trade_id"]
        assert second["core"] == first["core"]
        assert session.get(ExecutedTrade, first["trade_id"]).core_json == before_core
        assert second["evidence"]["lifecycle"] == "settled"
        assert second["evidence"]["settlement_date"] == "2030-01-17"
        assert second["revisions"][0] == first["revisions"][0]
        assert second["revision"] == 2
        assert second["evidence"]["planned_dates"] is None


def test_distinct_ordered_native_ids_same_economics_stay_distinct(database):
    with database.session_factory() as session:
        first = accept_source(session, fixture(money=False))
        second = accept_source(session, fixture(secondary="2000000002", money=False))
        result = promote(session, [identity(first), identity(second)])
        assert len(result["trades"]) == 2
        assert result["trades"][0]["core"] == result["trades"][1]["core"]
        assert result["trades"][0]["ids"] != result["trades"][1]["ids"]


def test_primary_id_ambiguity_across_full_union_blocks_selected_set(database):
    with database.session_factory() as session:
        first = accept_source(session)
        # S1 production Apply rejects this new ambiguity. Insert an adversarial
        # accepted-union state solely to prove S2 independently rechecks old links.
        other = preview(session, fixture(secondary="2000000002", money=False))
        assert "money_link_ambiguous" in other["conflicts"]
        row = session.get(MyBrokerImport, first["import_id"])
        document = json.loads(row.normalized_json)
        document["trades"].append(other["document"]["trades"][0])
        row.normalized_json = canonical(document)
        session.commit()
        p = preview_executed_trades(session, [identity(first)])
        assert "money_link_ambiguous" in p["candidates"][0]["conflicts"]
        with pytest.raises(MyBrokerError, match="reconciliation_required"):
            promote(session, [identity(first)], reviewed=p)
        assert count(session, ExecutedTrade) == 0


def test_incomplete_id_money_then_complete_identity_refuses_entire_selected_set(database):
    with database.session_factory() as session:
        xml = fixture(missing_id=True)
        source_preview = preview(session, xml)
        assert "money_link_incomplete_identity" in source_preview["blockers"]
        incomplete = apply(session, xml, source_preview)
        old_money = incomplete["document"]["money"][0]
        assert old_money["trade_identity"] is None
        assert incomplete["document"]["trades"][0]["identity"] is None
        full = identity(accept_source(session, fixture(money=False)))
        clean = identity(accept_source(session, fixture(primary="10000000002", money=False)))
        assert preview_executed_trades(session, [clean])["can_apply"]
        reviewed = preview_executed_trades(session, [full, clean])
        selected = next(t for t in reviewed["candidates"] if t["source_identity"] == full)
        assert "money_link_ambiguous" in selected["conflicts"]
        assert selected["evidence"]["cash_legs"] == []
        assert not reviewed["can_apply"]
        with pytest.raises(MyBrokerError, match="reconciliation_required"):
            promote(session, [full, clean], reviewed=reviewed)
        for model in (
            ExecutedTrade,
            ExecutedTradeRevision,
            ExecutedTradeOccurrence,
            ExecutedTradeApply,
        ):
            assert count(session, model) == 0
        assert session.get(MyBrokerImport, incomplete["import_id"]).normalized_json == canonical(
            incomplete["document"]
        )


def test_unresolved_money_link_is_recomputed_when_full_union_has_one_owner(database):
    root = ET.fromstring(fixture())
    root.find(
        ".//{MyBroker}Trades/{MyBroker}Report/{MyBroker}Tablix2/{MyBroker}Details_Collection"
    ).clear()
    with database.session_factory() as session:
        old = accept_source(session, ET.tostring(root))
        assert not old["document"]["trades"]
        assert old["document"]["money"][0]["trade_identity"] is None
        key = identity(accept_source(session, fixture(money=False)))
        reviewed = preview_executed_trades(session, [key])
        assert reviewed["can_apply"]
        evidence = reviewed["candidates"][0]["evidence"]
        assert evidence["readiness"]["settlement"] == []
        assert evidence["cash_legs"][0]["occurrences"][0]["import_id"] == old["import_id"]
        assert promote(session, [key], reviewed=reviewed)["trades"][0]["evidence"] == evidence
        assert session.get(MyBrokerImport, old["import_id"]).normalized_json == canonical(
            old["document"]
        )


def test_changed_immutable_core_never_overwrites_accepted_trade_and_blocks_reads(database):
    with database.session_factory() as session:
        source = accept_source(session)
        key = identity(source)
        original = promote(session, [key])["trades"][0]
        row = session.get(MyBrokerImport, source["import_id"])
        document = json.loads(row.normalized_json)
        document["trades"][0]["core"]["quantity"] = "11"
        row.normalized_json = canonical(document)
        session.commit()
        p = preview_executed_trades(session, [key])
        assert not p["can_apply"]
        assert "immutable_trade_conflict" in p["candidates"][0]["conflicts"]
        with pytest.raises(MyBrokerError, match="reconciliation_required"):
            promote(session, [key], reviewed=p)
        read = read_executed_trades(session)["trades"][0]
        assert read["core"] == original["core"]
        assert read["revision"] == 1
        assert "immutable_trade_conflict" in read["conflicts"]


@pytest.mark.parametrize(
    "commission,basis", [(None, "unknown"), ("0", "zero"), ("1.25", "unknown")]
)
def test_explicit_zero_nonzero_unknown_fee_basis_and_missing_actual_settlement(
    database, commission, basis
):
    with database.session_factory() as session:
        xml = mutate(
            fixture(money=False),
            bank_tax=commission,
            save_settlement_date=None,
            save_depo_settlement_date=None,
        )
        key = identity(accept_source(session, xml))
        read = promote(session, [key])["trades"][0]
        evidence = read["evidence"]
        assert evidence["lifecycle"] == "settled"
        assert evidence["fee_basis"] == basis
        assert "actual_settlement_missing" in evidence["readiness"]["settlement"]
        assert evidence["settlement_date"] is None
        assert not read["financial_ready"]


def test_linked_nonzero_fee_is_evidence_once_not_automatic_separate_basis(database):
    root = ET.fromstring(mutate(fixture(), bank_tax="1.25"))
    collection = root.find(".//{MyBroker}Trades2//{MyBroker}rn_Collection")
    rn = deepcopy(root.find(".//{MyBroker}Trades2//{MyBroker}rn"))
    fee = rn.find(".//{MyBroker}comment")
    fee.set("comment", "Комиссия по сделке 10000000001")
    fee.find(".//{MyBroker}p_code/{MyBroker}p_code").set("volume", "-1.25")
    collection.append(rn)
    with database.session_factory() as session:
        key = identity(accept_source(session, ET.tostring(root)))
        trade = promote(session, [key])["trades"][0]
        assert trade["evidence"]["fee_basis"] == "unknown"
        assert len(trade["evidence"]["cash_legs"]) == 2
        assert [
            leg["amount_minor"]
            for leg in trade["evidence"]["cash_legs"]
            if leg["role"] == "commission"
        ] == [125]
        assert "commission_basis_unresolved" in trade["evidence"]["readiness"]["commission"]


@pytest.mark.parametrize("pending,settlement", [(True, None), (False, "2030-02-17"), (False, None)])
def test_pending_and_actual_settlement_cutoff_block_all_classes_in_historical_universe(
    database, pending, settlement
):
    with database.session_factory() as session:
        account_id = include_source_account(session)
        xml = fixture(pending=pending, money=False)
        if not pending:
            xml = mutate(xml, save_settlement_date="17.02.2030" if settlement else None)
        key = identity(accept_source(session, xml))
        trade_id = promote(session, [key])["trades"][0]["trade_id"]
        assert unresolved_execution_ids(
            session, (account_id,), date(2030, 2, 1), date(2030, 2, 28)
        ) == [trade_id]
        assert unresolved_execution_ids(session, (), date(2030, 2, 1), date(2030, 2, 28)) == []
        for asset_class in ("stock", "bond", "gold"):
            result = class_endpoint_eligibility(
                session,
                asset_class=asset_class,
                start_date=date(2030, 2, 1),
                end_date=date(2030, 2, 28),
            )
            assert "mybroker_class_reconciliation_required" in result["reason_codes"]


def test_accepted_pending_guard_survives_s1_settlement_until_explicit_s2_apply(database):
    start, end = date(2030, 2, 1), date(2030, 2, 28)
    with database.session_factory() as session:
        account_id = include_source_account(session)
        key = identity(
            accept_source(
                session, fixture(pending=True), "Брокерский 1234567 (01.01.30-16.01.30).xml"
            )
        )
        accepted = promote(session, [key])["trades"][0]
        trade_id = accepted["trade_id"]
        assert unresolved_execution_ids(session, (account_id,), start, end) == [trade_id]
        accept_source(session)  # Settled Jan evidence is accepted only by S1.
        reread = read_executed_trades(session)["trades"][0]
        assert reread["revision"] == 1
        assert reread["evidence"]["lifecycle"] == "pending"
        assert "source_enrichment_not_accepted" in reread["conflicts"]
        assert unresolved_execution_ids(session, (account_id,), start, end) == [trade_id]
        for asset_class in ("stock", "bond", "gold"):
            result = class_endpoint_eligibility(
                session, asset_class=asset_class, start_date=start, end_date=end
            )
            assert "mybroker_class_reconciliation_required" in result["reason_codes"]
        enriched = promote(session, [key])["trades"][0]
        assert enriched["revision"] == 2
        assert enriched["evidence"]["lifecycle"] == "settled"
        assert enriched["evidence"]["settlement_date"] == "2030-01-17"
        assert enriched["revisions"][0] == accepted["revisions"][0]
        assert unresolved_execution_ids(session, (account_id,), start, end) == []
        for asset_class in ("stock", "bond", "gold"):
            result = class_endpoint_eligibility(
                session, asset_class=asset_class, start_date=start, end_date=end
            )
            assert "mybroker_class_reconciliation_required" not in result["reason_codes"]
        assert not enriched["financial_ready"]


def test_unaccepted_s1_fee_evidence_can_strengthen_accepted_settled_guard(database):
    start, end = date(2030, 2, 1), date(2030, 2, 28)
    root = ET.fromstring(fixture())
    root.find(
        ".//{MyBroker}Trades/{MyBroker}Report/{MyBroker}Tablix2/{MyBroker}Details_Collection"
    ).clear()
    root.find(".//{MyBroker}Trades2//{MyBroker}settlement_date").set(
        "settlement_date", "2030-02-17T00:00:00"
    )
    root.find(".//{MyBroker}Trades2//{MyBroker}rn").set("last_update", "2030-02-17T10:00:00")
    root.find(".//{MyBroker}Trades2//{MyBroker}comment").set(
        "comment", "Комиссия по сделке 10000000001"
    )
    root.find(".//{MyBroker}Trades2//{MyBroker}p_code/{MyBroker}p_code").set("volume", "-1.25")
    with database.session_factory() as session:
        account_id = include_source_account(session)
        key = identity(accept_source(session))
        accepted = promote(session, [key])["trades"][0]
        assert unresolved_execution_ids(session, (account_id,), start, end) == []
        accept_source(session, ET.tostring(root), "Брокерский 1234567 (01.02.30-28.02.30).xml")
        reread = read_executed_trades(session)["trades"][0]
        assert reread["revision"] == 1
        assert reread["evidence"] == accepted["evidence"]
        assert "source_enrichment_not_accepted" in reread["conflicts"]
        assert unresolved_execution_ids(session, (account_id,), start, end) == [
            accepted["trade_id"]
        ]


def test_accepted_no_crossing_contradiction_refuses_even_closed_financial_state(database):
    with database.session_factory() as session:
        include_source_account(session)
        key = identity(accept_source(session))
        # Simulate externally accepted contradictory C2; S1's ordinary guard
        # prevents this ordering too. S2 must neither overwrite nor endorse it.
        session.add(
            ClassNoCrossingCoverage(
                asset_class="stock",
                covered_from=date(2030, 1, 1),
                covered_to=date(2030, 1, 31),
                coverage_state="complete",
                revision=1,
                material_signature="a" * 64,
                provenance_kind="owner_attestation",
            )
        )
        session.commit()
        p = preview_executed_trades(session, [key])
        assert "accepted_class_coverage_requires_reconciliation" in p["candidates"][0]["conflicts"]
        with pytest.raises(MyBrokerError, match="reconciliation_required"):
            promote(session, [key], reviewed=p)
        assert count(session, ExecutedTrade) == 0


def test_exact_replay_idempotency_key_collision_and_fresh_noop(database):
    with database.session_factory() as session:
        key = identity(accept_source(session))
        p = preview_executed_trades(session, [key])
        first = promote(session, [key], "synthetic_request", p)
        replay = promote(session, [key], "synthetic_request", p)
        assert replay["duplicate"]
        assert replay["trades"] == first["trades"]
        assert count(session, ExecutedTradeRevision) == 1
        fresh = preview_executed_trades(session, [key])
        with pytest.raises(MyBrokerError, match="idempotency_conflict"):
            promote(session, [key], "synthetic_request", fresh)
        assert fresh["candidates"][0]["action"] == "noop"
        assert promote(session, [key], reviewed=fresh)["trades"] == first["trades"]


@pytest.mark.parametrize("change", ["mapping", "month", "source", "catalogue", "target_revision"])
def test_stale_mapping_reconciliation_source_or_target_refuses_entire_set(database, change):
    with database.session_factory() as session:
        key = identity(accept_source(session))
        if change == "target_revision":
            promote(session, [key])
        p = preview_executed_trades(session, [key])
        before = count(session, ExecutedTradeRevision)
        if change == "mapping":
            mapping = session.scalar(
                select(BrokerIdentityMapping).where(
                    BrokerIdentityMapping.provider_identity == ACCOUNT
                )
            )
            revoke_mapping(session, mapping.id)
        elif change == "catalogue":
            session.scalar(select(Instrument)).isin = "RU000A000001"
            session.commit()
        elif change == "month":
            from hermes_finance.services.reporting_months import create_reporting_month

            create_reporting_month(session, year=2030, month=1, snapshot_date=date(2030, 1, 31))
        elif change == "target_revision":
            row = session.scalar(select(ExecutedTradeRevision))
            row.acceptance_state = "retracted"
            session.commit()
        else:
            row = session.scalar(select(MyBrokerImport))
            document = json.loads(row.normalized_json)
            document["trades"][0]["depo_settlement_date"] = None
            row.normalized_json = canonical(document)
            session.commit()
        with pytest.raises(MyBrokerError, match="preview_stale"):
            promote(session, [key], reviewed=p)
        assert count(session, ExecutedTradeRevision) == before


def test_selected_set_failure_rolls_back_partial_trade_and_receipt(database):
    with database.session_factory() as session:
        one = identity(accept_source(session, fixture(money=False)))
        two = identity(accept_source(session, fixture(primary="10000000002", money=False)))

        def fail_second(_mapper, _connection, target):
            if target.source_identity == sorted([one, two])[1]:
                raise RuntimeError("synthetic_failure")

        event.listen(ExecutedTrade, "before_insert", fail_second)
        try:
            with pytest.raises(RuntimeError, match="synthetic_failure"):
                promote(session, [one, two])
        finally:
            event.remove(ExecutedTrade, "before_insert", fail_second)
        for model in (
            ExecutedTrade,
            ExecutedTradeRevision,
            ExecutedTradeOccurrence,
            ExecutedTradeApply,
        ):
            assert count(session, model) == 0


def test_http_preview_apply_independent_get_and_no_browser_normalized_rows(database):
    with database.session_factory() as session:
        key = identity(accept_source(session))
    with TestClient(create_app(database=database)) as client:
        p = client.post("/api/executed-trades/preview", json={"identities": [key]})
        assert p.status_code == 200
        request = {
            "identities": [key],
            "confirmation_digest": p.json()["confirmation_digest"],
            "request_id": "http_synthetic",
        }
        assert (
            client.post("/api/executed-trades/apply", json={**request, "rows": []}).status_code
            == 422
        )
        a = client.post("/api/executed-trades/apply", json=request)
        assert a.status_code == 200, a.text
        trade = a.json()["trades"][0]
        assert client.get(f"/api/executed-trades/{trade['trade_id']}").json() == trade
        assert client.get("/api/executed-trades").json()["trades"] == [trade]
        assert client.post("/api/executed-trades/apply", json=request).json()["duplicate"]
        assert client.get("/api/executed-trades/9999").status_code == 404


def test_incomplete_native_ids_do_not_promote_and_source_v2_endpoints_unchanged(database):
    with database.session_factory() as session:
        source = accept_source(session, fixture(missing_id=True))
        original = session.get(MyBrokerImport, source["import_id"]).normalized_json
        with pytest.raises(MyBrokerError, match="source_trade_not_found"):
            preview_executed_trades(session, ["0" * 64])
        assert session.get(MyBrokerImport, source["import_id"]).normalized_json == original
        assert source["document"]["parser"] == "mybroker-s1-v2"
        assert count(session, ExecutedTrade) == 0


def test_decimal_minor_conversion_preserves_source_precision_half_up_and_range():
    with localcontext() as context:
        context.prec = 3
        assert _minor("123456789012.345") == 12345678901235
        assert _minor("-1.005") == -101
    with pytest.raises(MyBrokerError, match="money_out_of_range"):
        _minor("92233720368547758.08")


def test_writer_reservation_is_physical_before_authoritative_plan(database, monkeypatch):
    import hermes_finance.services.executed_trades as service

    with database.session_factory() as session:
        key = identity(accept_source(session))
        reviewed = preview_executed_trades(session, [key])
        original = service._plan

        def reserved_plan(current, identities):
            driver = current.connection().connection.driver_connection
            assert driver.in_transaction
            with sqlite3.connect(database.database_path, timeout=0.01) as competitor:
                with pytest.raises(sqlite3.OperationalError, match="locked"):
                    competitor.execute("UPDATE broker_identity_mappings SET id=id")
            return original(current, identities)

        monkeypatch.setattr(service, "_plan", reserved_plan)
        assert promote(session, [key], reviewed=reviewed)["trades"][0]["revision"] == 1


def test_missing_source_support_stays_disputed_and_cannot_restore_no_crossing(database):
    with database.session_factory() as session:
        account_id = include_source_account(session)
        source = accept_source(session)
        key = identity(source)
        accepted = promote(session, [key])["trades"][0]
        row = session.get(MyBrokerImport, source["import_id"])
        document = json.loads(row.normalized_json)
        document["trades"] = []
        row.normalized_json = canonical(document)
        session.commit()
        reread = read_executed_trades(session)["trades"][0]
        assert reread["core"] == accepted["core"]
        assert "source_trade_not_found" in reread["conflicts"]
        assert unresolved_execution_ids(
            session, (account_id,), date(2030, 2, 1), date(2030, 2, 28)
        ) == [accepted["trade_id"]]


def test_closed_month_source_only_promotion_does_not_change_month_or_catalogue_c1(database):
    from hermes_finance.services.reporting_months import create_reporting_month

    with database.session_factory() as session:
        key = identity(accept_source(session))
        month = create_reporting_month(session, year=2030, month=1, snapshot_date=date(2030, 1, 31))
        month.status = "closed"
        session.scalar(select(Instrument)).instrument_type = "bond"
        session.commit()
        before = [
            (row.id, row.status, row.snapshot_date)
            for row in session.scalars(select(ReportingMonth))
        ]
        trade = promote(session, [key])["trades"][0]
        after = [
            (row.id, row.status, row.snapshot_date)
            for row in session.scalars(select(ReportingMonth))
        ]
        assert after == before
        assert trade["evidence"]["event_c1"] is None
        assert trade["evidence"]["readiness"]["c1"] == ["event_c1_missing"]


def test_sell_credit_actual_cash_and_unsupported_currency_evidence(database):
    root = ET.fromstring(mutate(fixture(qty="-10"), curr_calc="USD"))
    money = root.find(".//{MyBroker}Trades2//{MyBroker}p_code/{MyBroker}p_code")
    money.set("volume", "1000")
    money.set("p_code", "USD")
    with database.session_factory() as session:
        key = identity(accept_source(session, ET.tostring(root)))
        trade = promote(session, [key])["trades"][0]
        assert trade["core"]["currency"] == "USD"
        assert trade["evidence"]["trade_amount_minor"] is None
        assert trade["evidence"]["cash_legs"][0]["direction"] == "credit"
        assert trade["evidence"]["cash_legs"][0]["amount_minor"] is None
        assert trade["evidence"]["cash_legs"][0]["source_amount"] == "1000"
        assert trade["evidence"]["readiness"]["unsupported"] == ["currency_unsupported"]


@pytest.mark.parametrize("amount", ["-1.00000000000000000000000000001", "0"])
def test_exact_cash_consistency_and_zero_do_not_infer_direction(database, amount):
    root = ET.fromstring(mutate(fixture(), summ_trade="1"))
    root.find(".//{MyBroker}Trades2//{MyBroker}p_code/{MyBroker}p_code").set("volume", amount)
    with database.session_factory() as session:
        key = identity(accept_source(session, ET.tostring(root)))
        evidence = promote(session, [key])["trades"][0]["evidence"]
        assert "settlement_principal_unresolved" in evidence["readiness"]["settlement"]
        if amount == "0":
            assert evidence["cash_legs"][0]["direction"] is None
            assert "trade_cash_direction_conflict" in evidence["readiness"]["settlement"]


def test_identical_money_rows_within_one_document_do_not_prove_one_settlement(database):
    root = ET.fromstring(fixture())
    collection = root.find(".//{MyBroker}Trades2//{MyBroker}rn_Collection")
    collection.append(deepcopy(collection.find("{MyBroker}rn")))
    with database.session_factory() as session:
        key = identity(accept_source(session, ET.tostring(root)))
        evidence = promote(session, [key])["trades"][0]["evidence"]
        assert evidence["cash_legs"][0]["observed_multiplicity"] == 2
        assert len(evidence["cash_legs"][0]["occurrences"]) == 2
        assert "settlement_cash_missing_or_ambiguous" in evidence["readiness"]["settlement"]
        assert evidence["readiness"]["cash_ownership"] == ["cash_leg_multiplicity_unresolved"]
