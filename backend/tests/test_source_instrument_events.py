"""Saved synthetic originals -> dated events -> existing API, with no economic writes."""

import json
import sqlite3
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import date
from decimal import Decimal, localcontext

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_source_instrument_returns_service import BOND, by_isin, read, save
from test_source_instrument_returns_service import db as db
from test_source_money_classifications_service import DIVIDEND_SECURITY, _security_instrument
from test_source_monthly_returns_service import snapshot
from test_statement_import_broker_statement_provisional import _add_money
from test_statement_import_mybroker import ACCOUNT, ISIN

from hermes_finance.database import create_database
from hermes_finance.main import create_app
from hermes_finance.persistence import SourceMoneyClassification
from hermes_finance.services import security_reg_isin_mappings as mappings
from hermes_finance.services import source_intake
from hermes_finance.services.source_bond_valuation import (
    FILE_PATH_KEY,
    FILE_VERSION,
    MAX_FILE_BYTES,
    BondEndpointBinding,
    ReviewedBondValuation,
    SourceRevision,
)
from hermes_finance.services.source_instrument_returns import read_instrument_returns
from hermes_finance.services.source_money_classifications import choose_classification
from hermes_finance.source_proof_file import file_incarnation
from hermes_finance.statement_import.mybroker import NS

CASH_RETURN = "Возврат средств по дог. № 90001 от 01.01.2030. Тестов Иван Иванович. Без НДС"


@pytest.mark.parametrize(
    "amount,text",
    [
        ("50", "Дивиденды и ведение счета"),
        ("-2", "Дивиденды и ведение счета"),
        ("2", "account maintenance"),
        ("-2", "account maintenance погашение облигаций Synthetic"),
    ],
)
def test_contradictory_account_cost_never_hides_cash(db, amount, text):
    save(db, bond=None, trades=(), extra=(("Комиссия", text, amount),))
    before = snapshot(db)
    result = read(db)
    assert by_isin(result)[ISIN].analysis.pnl.value is None
    assert not result.account_reconciliation_events
    assert result.unresolved_events
    assert snapshot(db) == before


@pytest.mark.parametrize("closing_month", [5, 10])
def test_supported_later_period_reaches_overview_card_and_ai(db, closing_month):
    from hermes_finance.services import ai_source_returns, returns_overall

    save(db, bond=("2", "2", "2000", "2100"), trades=(), stock=("10", "10", "", "1100"))
    save(
        db,
        5,
        end_month=closing_month,
        bond=("2", "2", "2100", "2200"),
        trades=(),
        stock=("10", "10", "1100", "1200"),
    )
    closing_date = date(2030, closing_month, 31)
    before = snapshot(db)
    with db.session_factory() as session:
        native = read_instrument_returns(
            session, source_account=ACCOUNT, available_period=True, include_monthly_history=False
        )
        analysis = by_isin(native)[ISIN].analysis
        assert (analysis.opening_date, analysis.closing_date) == (
            date(2030, 4, 30),
            closing_date,
        )
        assert analysis.pnl.value == 10000 and analysis.modified_dietz.value is not None
        overview = returns_overall.read_overall(session, include_instrument_details=True)
        assert {item["isin"] for item in overview["instruments"]} == {ISIN, BOND}
        card = returns_overall.read_instrument_card(session, ISIN, overview=overview)
        (account,) = card["accounts"]
        assert account["detail"]["analysis"].pnl.value == 10000
        assert account["period"] == {"start": date(2030, 4, 30), "end": closing_date}
        section = ai_source_returns.source_returns_section(
            session, as_of_date=closing_date, reporting_period=(2030, closing_month)
        )
        intervals = section["data"]["accounts"][0]["intervals"]
        assert any(
            i["opening_date"] == "2030-04-30"
            and i["closing_date"] == str(closing_date)
            and any(t["isin"] == ISIN for t in i["instruments"])
            for i in intervals
        )
    assert snapshot(db) == before


@pytest.mark.parametrize("quantity", ["10", "11"])
def test_unknown_boundary_value_is_not_a_conflicting_known_value(db, quantity):
    save(db, bond=None, trades=(), marker="known")
    save(db, bond=None, trades=(), stock=(quantity, "10", "", "1100"), marker="unknown")
    analysis = by_isin(read(db))[ISIN].analysis
    if quantity == "10":
        assert analysis.opening.economic_value_kopecks == 100000
        assert analysis.pnl.value == 10000
        assert "overlapping_endpoint_conflict" not in analysis.reason_codes
    else:
        assert analysis.pnl.value is None
        assert "overlapping_endpoint_conflict" in analysis.reason_codes


def test_unallocated_negative_fee_has_separate_before_cost_result(db):
    from hermes_finance.services import returns_overall

    save(db, bond=None, trades=(), extra=(("Комиссия", "unallocated cost", "-2"),))
    before = snapshot(db)
    with db.session_factory() as session:
        result = read_instrument_returns(session, source_account=ACCOUNT, available_period=True)
        analysis = by_isin(result)[ISIN].analysis
        assert analysis.pnl.value is None
        assert analysis.statement_estimate.pnl.value == 10000
        assert analysis.statement_estimate.modified_dietz.value == Decimal("0.1")
        overview = returns_overall.read_overall(session, include_instrument_details=True)
        indexed = overview["instruments"][0]["accounts"][0]
        assert indexed["pnl"]["value"] is None
        assert indexed["conditional_pnl"]["value"] == "10000"
        assert "unallocated_costs_excluded" in indexed["conditional_pnl"]["reason_codes"]
        from hermes_finance.services import ai_source_returns

        refs = {}
        section = ai_source_returns.source_returns_section(
            session,
            as_of_date=date(2030, 4, 30),
            reporting_period=(2030, 4),
            source_account_refs=refs,
        )
        instrument = next(
            item
            for period in section["data"]["accounts"][0]["intervals"]
            for item in period["instruments"]
            if item["isin"] == ISIN and "before_unallocated_costs" in item
        )
        assert instrument["metrics"]["pnl"]["value"] is None
        assert instrument["before_unallocated_costs"]["modified_dietz"]["value"] == "10"
        blocked = read_instrument_returns(
            session,
            source_account=ACCOUNT,
            available_period=True,
            include_monthly_history=False,
            excluded_periods={(date(2030, 3, 31), date(2030, 4, 30))},
        )
        assert by_isin(blocked)[ISIN].analysis.statement_estimate.pnl.value is None
    assert result.unresolved_events
    assert snapshot(db) == before


def test_invalid_subkopeck_boundary_cannot_borrow_other_original_value(db):
    save(db, bond=None, trades=(), marker="valid-value")
    save(db, bond=None, trades=(), stock=("10", "10", "1000.001", "1100"), marker="invalid-value")
    analysis = by_isin(read(db))[ISIN].analysis
    assert analysis.opening.economic_value_kopecks is None
    assert analysis.pnl.value is None


def test_repo_identity_inventory_is_reconstructed_once_per_source_read(db, monkeypatch):
    from hermes_finance.services import source_trade_identity

    save(db, mutate=_repo_source_scope, end_month=6)
    original = source_trade_identity.repo_return_identities
    calls = []

    def counted(view):
        calls.append(view["id"])
        return original(view)

    monkeypatch.setattr(source_trade_identity, "repo_return_identities", counted)
    read(db)
    assert len(calls) == 1


@pytest.mark.parametrize("choice", [None, "unknown"])
def test_contract_return_read_rule_preserves_saved_default_and_manual_choice(db, choice):
    intake = save(db, bond=None, trades=(), extra=(("Перевод", CASH_RETURN, "-50"),))
    with db.session_factory() as session:
        row = session.scalar(
            select(SourceMoneyClassification).where(SourceMoneyClassification.intake_id == intake)
        )
        # An old intake predating this rule; do not rewrite it during a read.
        row.classification, row.origin, row.status = "unknown", "default_rule", "assumed"
        reference = row.source_reference
        session.commit()
        if choice:
            choose_classification(session, intake, reference, choice)
    before = snapshot(db)
    result = read(db)
    analysis = by_isin(result)[ISIN].analysis
    assert analysis.pnl.value == (None if choice else 10000)
    assert ("unrecognized_money" in analysis.reason_codes) == bool(choice)
    with db.session_factory() as session:
        row = session.scalar(
            select(SourceMoneyClassification).where(
                SourceMoneyClassification.source_reference == reference
            )
        )
        assert row.classification == "unknown"
        assert row.origin == ("user_choice" if choice else "default_rule")
    assert snapshot(db) == before


@pytest.mark.parametrize("case", ["exact", "prefix", "ambiguous"])
def test_source_scope_nkd_uses_full_issue_not_shared_stock_name(db, case):
    def mutate(root):
        root.find(".//m:Details[@ISIN1]", NS).set("active_name", "Shared Issuer")
        bond = next(r for r in root.findall(".//m:Details[@ISIN1]", NS) if r.get("ISIN1") == BOND)
        bond.set("active_name", "Shared Issuer Bond 01")
        if case == "ambiguous":
            other = deepcopy(bond)
            other.set("ISIN1", "RU000A000002")
            root.find(
                "m:Positions/m:Report/m:Tablix1/m:active_type_Collection/"
                "m:active_type/m:Details_Collection",
                NS,
            ).append(other)

    label = "Shared Issuer" if case == "prefix" else "Shared Issuer Bond 01"
    save(db, trades=(), extra=(("НКД по сделке", "c " + label, "-20"),), mutate=mutate)
    before = snapshot(db)
    result = read(db)
    stock = by_isin(result)[ISIN].analysis
    assert ("unmatched_trade_money" in stock.reason_codes) == (case != "exact")
    if case == "exact":
        (event,) = by_isin(result)[BOND].analysis.events
        assert event.isin == BOND and event.attribution_basis == "source_issue"
        assert not event.counted and event.effective_isin is None
        assert all(leg.ownership == event.event_key for leg in event.cash_legs)
        assert "unmatched_trade_money" in event.reason_codes
        assert stock.pnl.value == 10000
        assert by_isin(result)[ISIN].months[0].total_kopecks == 10000
    else:
        assert result.unresolved_events and stock.pnl.value is None
    assert result.financial_authority == "none"
    assert snapshot(db) == before


def _repo_source_scope(root, *, duplicate=False):
    rows = root.findall(".//m:Details[@trade_no]", NS)
    for row in rows:
        row.set("trade_no", "B90001")
        row.set("repo_no", "B90002")
        row.set("comment", "репо ч.1")
    if duplicate:
        other = deepcopy(rows[0])
        other.set("isin_reg", "RU000A000002")
        root.find("m:Trades/m:Report/m:Tablix2/m:Details_Collection", NS).append(other)


@pytest.mark.parametrize(
    "damage", [None, "missing_inventory", "partner_digest", "leg_marker", "account"]
)
def test_repo_return_identity_requires_exact_witness_and_account(db, damage):
    from hermes_finance.services.source_trade_identity import repo_return_identities
    from hermes_finance.statement_import.mybroker import digest

    intake = save(db, mutate=_repo_source_scope)
    before = snapshot(db)
    with db.session_factory() as session:
        view = source_intake.read_intake(session, intake)
    original = repo_return_identities(view)
    assert set(original) == {0}
    if damage == "missing_inventory":
        view["observations"] = []
    else:
        observation = next(
            o for o in view["observations"] if "repo_no" in o["facts"].get("native_references", {})
        )
        attributes = observation["facts"]["attributes"]
        if damage == "partner_digest":
            observation["facts"]["native_references"]["repo_no"] = "B90003"
        if damage == "leg_marker":
            next(a for a in attributes if a["name"] == "comment")["value_digest"] = digest(
                "unrecognized"
            )
        if damage == "account":
            account = "SYNTHETIC-SECOND-ACCOUNT"
            view["document"]["trades"][0]["core"]["source_account"] = account
            observation["facts"]["native_references"]["acc_code"] = account
            next(a for a in attributes if a["name"] == "acc_code")["value_digest"] = digest(account)
    projected = repo_return_identities(view)
    if damage == "account":
        assert projected[0][0] != original[0][0]
    else:
        assert projected == (original if damage is None else {})
    assert snapshot(db) == before


def test_repo_identity_collision_across_issues_cannot_choose_first_original(db):
    def mutate(root, target):
        _repo_source_scope(root)
        root.find(".//m:Details[@trade_no]", NS).set("isin_reg", target)
        for position in root.findall(".//m:Details[@ISIN1]", NS):
            position.set("active_type", "Акции")

    for marker, target in (("first-issue", BOND), ("second-issue", ISIN)):
        save(db, bond=("2", "2", "2000", "2100"), marker=marker, mutate=lambda r: mutate(r, target))
    before = snapshot(db)
    result = read(db)
    assert all(row.analysis.pnl.value is None for row in result.instruments)
    (event,) = [e for e in result.unresolved_events if e.kind in {"BUY", "SELL"}]
    assert event.isin is event.effective_isin is None
    assert "overlapping_trade_conflict" in event.reason_codes
    assert not event.counted and len(event.source_references) == 2
    assert snapshot(db) == before


def test_repo_conflicting_dates_remain_visible_in_alternate_date_interval(db):
    def mutate(root, day):
        _repo_source_scope(root)
        trade_date(day)(root)

    save(db, mutate=lambda r: mutate(r, 10), marker="earlier-repo")
    save(db, mutate=lambda r: mutate(r, 20), marker="later-repo")
    before = snapshot(db)
    with db.session_factory() as session:
        result = read_instrument_returns(
            session,
            source_account=ACCOUNT,
            isin=BOND,
            opening_date=date(2030, 4, 19),
            closing_date=date(2030, 4, 20),
        )
    analysis = result.instruments[0].analysis
    assert "overlapping_trade_conflict" in analysis.reason_codes
    assert "repo_trade_unsupported" in analysis.reason_codes
    assert analysis.pnl.value is analysis.modified_dietz.value is None
    (marker,) = analysis.events
    assert marker.event_date == date(2030, 4, 20)
    assert marker.attribution_basis == "conflicting_trade_observation"
    assert not marker.counted and not marker.cash_legs
    assert len(marker.source_references) == 2
    assert snapshot(db) == before


def _closed_native_issue(root, *, ambiguous=False, stock_collision=False):
    row = root.find(".//m:Details[@trade_no]", NS)
    row.set("p_name", "Shared Issuer Bond 01")
    if ambiguous:
        other = deepcopy(row)
        other.set("isin_reg", "RU000A000002")
        other.set("trade_no", "90000000001\n90000000002")
        root.find("m:Trades/m:Report/m:Tablix2/m:Details_Collection", NS).append(other)
    if stock_collision:
        root.find(".//m:Details[@ISIN1]", NS).set("active_name", "Shared Issuer Bond 01")


@pytest.mark.parametrize(
    "case", ["exact", "name_missing", "prefix", "ambiguous", "position_conflict"]
)
def test_native_trade_issue_scope_without_position_is_not_money_ownership(db, case):
    label = "Shared Issuer" if case == "prefix" else "Shared Issuer Bond 01"
    save(
        db,
        bond=None,
        trades=((BOND, "1", "100", "0", "0"),),
        extra=(("НКД по сделке", "c " + label, "-20"),),
        mutate=(
            None
            if case == "name_missing"
            else lambda r: _closed_native_issue(
                r, ambiguous=case == "ambiguous", stock_collision=case == "position_conflict"
            )
        ),
    )
    before = snapshot(db)
    result = read(db)
    stock = by_isin(result)[ISIN].analysis
    if case == "exact":
        (event,) = [e for e in by_isin(result)[BOND].analysis.events if e.kind == "UNRESOLVED"]
        assert event.isin == BOND and event.attribution_basis == "source_issue"
        assert not event.counted and event.effective_isin is None
        assert event.reason_codes == ("unmatched_trade_money",)
        assert event.native_identity is None
        assert all(leg.ownership == event.event_key for leg in event.cash_legs)
        assert stock.pnl.value == 10000
        assert by_isin(result)[ISIN].months[0].total_kopecks == 10000
        assert "unmatched_trade_money" not in stock.reason_codes
    else:
        assert stock.pnl.value is None
        assert any("unmatched_trade_money" in e.reason_codes for e in result.unresolved_events)
    assert snapshot(db) == before and result.financial_authority == "none"


@pytest.mark.parametrize("confirmed_scoped", [False, True])
def test_native_trade_issue_scope_overlap_needs_each_original_proof(db, confirmed_scoped):
    extra = (("НКД по сделке", "c Shared Issuer Bond 01", "-20"),)
    scoped = save(
        db,
        bond=None,
        trades=((BOND, "1", "100", "0", "0"),),
        extra=extra,
        mutate=_closed_native_issue,
    )
    save(db, bond=None, trades=(), extra=extra, marker="missing-closed-issue-proof")
    if confirmed_scoped:
        with db.session_factory() as session:
            row = session.scalar(
                select(SourceMoneyClassification).where(
                    SourceMoneyClassification.intake_id == scoped
                )
            )
            choose_classification(session, scoped, row.source_reference, row.classification)
    before = snapshot(db)
    result = read(db)
    (event,) = [
        e for e in result.unresolved_events if "overlap_flow_choice_conflict" in e.reason_codes
    ]
    assert event.isin is None and not event.counted and len(event.source_references) == 2
    assert by_isin(result)[ISIN].analysis.pnl.value is None
    assert by_isin(result)[ISIN].months[0].total_kopecks is None
    assert snapshot(db) == before


@pytest.mark.parametrize("fault", ["reference_digest", "native_identity", "native_ordinal"])
def test_native_trade_issue_scope_requires_current_reference_chain(db, fault):
    from hermes_finance.services.source_instrument_events import _native_trade_issue_scopes

    intake = save(
        db,
        bond=None,
        trades=((BOND, "1", "100", "0", "0"),),
        mutate=_closed_native_issue,
    )
    before = snapshot(db)
    with db.session_factory() as session:
        view = source_intake.read_intake(session, intake)
    proven = _native_trade_issue_scopes(view)
    assert {target[1] for targets in proven.values() for target in targets if target} == {BOND}
    if fault == "reference_digest":
        row = next(
            o
            for o in view["observations"]
            if o["facts"].get("native_references", {}).get("trade_no")
        )
        row["facts"]["native_references"]["acc_code"] = "9999999-000"
    elif fault == "native_identity":
        view["document"]["trades"][0]["identity"] = "synthetic-stale-native-identity"
    else:
        view["document"]["trades"][0]["ordinal"] = 1
    assert not any(
        target for targets in _native_trade_issue_scopes(view).values() for target in targets
    )
    assert snapshot(db) == before


@pytest.mark.parametrize("case", ["exact", "unknown_id", "ambiguous"])
def test_source_scope_repo_native_reference_is_not_cash_authority(db, case):
    native_id = "B99999" if case == "unknown_id" else "B90001"
    save(
        db,
        trades=((BOND, "1", "100", "0", "0"),),
        extra=(("Расчеты по сделке " + native_id, "репо ч.1 c Synthetic stock", "-100"),),
        mutate=lambda r: _repo_source_scope(r, duplicate=case == "ambiguous"),
    )
    before = snapshot(db)
    result = read(db)
    stock = by_isin(result)[ISIN].analysis
    assert ("unmatched_trade_money" in stock.reason_codes) == (case != "exact")
    if case == "exact":
        (event,) = [
            e
            for e in by_isin(result)[BOND].analysis.events
            if e.attribution_basis == "matched_money"
        ]
        assert event.isin == event.effective_isin == BOND and not event.counted
        assert event.native_ids == ("B90001",)
        assert "repo_trade_unsupported" in event.reason_codes
        assert "unmatched_trade_money" not in event.reason_codes
        assert any(leg.ownership.startswith("money:") for leg in event.cash_legs)
        assert by_isin(result)[BOND].analysis.pnl.value is None
        assert stock.pnl.value == 10000
        assert by_isin(result)[ISIN].months[0].total_kopecks == 10000
        assert all(not e.counted for e in by_isin(result)[BOND].analysis.events)
    else:
        assert stock.pnl.value is None and result.unresolved_events
    assert snapshot(db) == before


def test_source_scope_repo_inconsistent_overlap_remains_root_gap(db):
    extra = (("Расчеты по сделке B90001", "репо ч.1 c Synthetic stock", "-100"),)
    save(
        db,
        trades=((BOND, "1", "100", "0", "0"),),
        extra=extra,
        mutate=_repo_source_scope,
    )
    save(db, trades=(), extra=extra, marker="missing-native-reference")
    before = snapshot(db)
    result = read(db)
    assert "overlap_flow_choice_conflict" in by_isin(result)[ISIN].analysis.reason_codes
    assert any("overlap_flow_choice_conflict" in e.reason_codes for e in result.unresolved_events)
    assert snapshot(db) == before


@pytest.mark.parametrize("kind", ["nkd", "repo"])
@pytest.mark.parametrize("confirmed_copy", ["scoped", "missing"])
def test_source_scope_overlap_classification_confirmation_cannot_attest_identity(
    db, kind, confirmed_copy
):
    extra = (
        (("НКД по сделке", "c Synthetic bond", "-20"),)
        if kind == "nkd"
        else (("Расчеты по сделке B90001", "репо ч.1 c Synthetic stock", "-100"),)
    )
    scoped = save(
        db,
        trades=() if kind == "nkd" else ((BOND, "1", "100", "0", "0"),),
        extra=extra,
        mutate=None if kind == "nkd" else _repo_source_scope,
    )
    missing = save(db, bond=None, trades=(), extra=extra, marker="no-issue-evidence")
    intake = scoped if confirmed_copy == "scoped" else missing
    with db.session_factory() as session:
        row = session.scalar(
            select(SourceMoneyClassification).where(SourceMoneyClassification.intake_id == intake)
        )
        choose_classification(session, intake, row.source_reference, row.classification)
    before = snapshot(db)
    result = read(db)
    assert "overlap_flow_choice_conflict" in by_isin(result)[ISIN].analysis.reason_codes
    (event,) = [
        e for e in result.unresolved_events if "overlap_flow_choice_conflict" in e.reason_codes
    ]
    assert event.isin is None and not event.counted and event.effective_isin is None
    assert len(event.source_references) == 2
    assert by_isin(result)[ISIN].analysis.pnl.value is None
    assert by_isin(result)[ISIN].months[0].total_kopecks is None
    assert snapshot(db) == before


@pytest.mark.parametrize(
    "reg,isin,issuer",
    [
        ("1-04-33498-E", "RU000A0JPNM1", 'ПАО "Интер РАО"'),
        ("10401000B", "RU000A0JP5V6", "Банк ВТБ (ПАО)"),
        ("1-01-04715-A", "RU0007775219", 'ПАО "МТС"'),
    ],
)
def test_registration_scope_is_identity_only_and_never_accepts_payout(db, reg, isin, issuer):
    narrative = f"Дивиденды за 2029 г. по акциям {issuer} ({reg}). (Удержан налог 13 руб.)."
    save(db, bond=None, trades=(), extra=(("Перевод", narrative, "87"),))
    before = snapshot(db)
    result = read(db)
    assert by_isin(result)[ISIN].analysis.pnl.value == 10000
    scoped = by_isin(result)[isin].analysis
    (event,) = scoped.events
    assert event.isin == isin and event.attribution_basis == "registration_scope"
    assert event.persisted_link_status == "unresolved_no_match"
    assert not event.counted and event.effective_isin is None
    assert all(leg.ownership == event.event_key for leg in event.cash_legs)
    assert "payout_link_unresolved_no_match" in event.reason_codes
    assert scoped.pnl.value is None and scoped.components["dividends"].value is None
    assert by_isin(result)[ISIN].months[0].total_kopecks == 10000
    assert by_isin(result)[isin].months[0].total_kopecks is None
    assert result.income[0].isin is None  # legacy projection is not silently promoted
    assert not result.reconciliation.complete
    assert snapshot(db) == before


def test_registration_scope_conflicting_explicit_crosswalk_stays_unresolved(db):
    narrative = 'Дивиденды за 2029 г. по акциям ПАО "МТС" (1-01-04715-A). (Удержан налог 13 руб.).'
    save(db, bond=None, trades=(), extra=(("Перевод", narrative, "87"),))
    with db.session_factory() as session:
        _security_instrument(session, isin=ISIN)
        session.commit()
        mappings.set_mapping(session, "1-01-04715-A", ISIN)
    before = snapshot(db)
    result = read(db)
    assert result.unresolved_events[0].isin is None
    assert by_isin(result)[ISIN].analysis.pnl.value is None
    assert by_isin(result)[ISIN].months[0].total_kopecks is None
    assert snapshot(db) == before


def test_source_scope_does_not_hide_compensation_or_account_tax(db):
    save(
        db,
        trades=(),
        extra=(
            ("НКД по сделке", "c Synthetic bond", "-20"),
            ("Перевод", "Компенсация утраченных дивидендов FOREIGN_01", "10"),
            ("НДФЛ", "Погашение обязательств по НДФЛ за 2029 год", "-5"),
        ),
    )
    before = snapshot(db)
    result = read(db)
    reasons = set(by_isin(result)[ISIN].analysis.reason_codes)
    assert {
        "unrecognized_money",
        "payout_classification_conflict",
        "unallocated_instrument_cost",
    } <= reasons
    assert "unmatched_trade_money" not in reasons
    assert by_isin(result)[ISIN].analysis.pnl.value is None
    assert "unmatched_trade_money" in by_isin(result)[BOND].analysis.reason_codes
    assert snapshot(db) == before


@pytest.mark.parametrize("change", ["kind", "metadata", "ambiguous", "missing_old_parse"])
def test_registration_scope_never_overrides_contradictory_saved_decisions(db, change):
    narrative = "Дивиденды за 2029 г. по акциям Банк Синтетический (ПАО) (10401000B). (Удержан налог 13 руб.)."
    intake = save(db, bond=None, trades=(), extra=(("Перевод", narrative, "87"),))
    with db.session_factory() as session:
        row = session.scalar(
            select(SourceMoneyClassification).where(SourceMoneyClassification.intake_id == intake)
        )
        if change == "kind":
            row.classification, row.instrument_link_status = "coupon", "not_parsed"
        elif change == "metadata":
            row.instrument_link_status, row.security_reg_number = "not_parsed", "1-01-99999-Z"
        elif change == "ambiguous":
            row.instrument_link_status = "unresolved_ambiguous"
        else:
            row.instrument_link_status = "not_parsed"
            row.security_reg_number = row.security_issuer = None
        session.commit()
    before = snapshot(db)
    result = read(db)
    if change == "missing_old_parse":
        (event,) = by_isin(result)["RU000A0JP5V6"].analysis.events
        assert event.attribution_basis == "registration_scope" and not event.counted
        assert event.reason_codes == ("payout_link_missing",)
        assert by_isin(result)[ISIN].analysis.pnl.value == 10000
    else:
        assert result.unresolved_events and result.unresolved_events[0].isin is None
        assert by_isin(result)[ISIN].analysis.pnl.value is None
    assert by_isin(result)[ISIN].months[0].total_kopecks == (
        10000 if change == "missing_old_parse" else None
    )
    assert snapshot(db) == before


def _reviewed_bond_packet(db, *, sides=("opening", "closing"), intake_id=None):
    """Synthetic trusted-caller decision, not a production acceptance API."""
    from hermes_finance.services.source_monthly_returns import _selected_sources

    with db.session_factory() as session:
        selected, native = _selected_sources(session, ACCOUNT)
        views = [v for _, v, error in selected if not error]
    sources = tuple(
        SourceRevision(
            v["id"],
            v["document_sha256"],
            v["document"]["provider"],
            v["document"]["parser"],
            v["generation"],
            v["head_seq"],
            v["manifest_digest"],
            v["covered_from"],
            v["covered_to"],
        )
        for v in views
    )
    view = next(v for v in views if v["id"] == (intake_id or views[0]["id"]))
    observation = next(
        o
        for o in view["observations"]
        if o["section"] == "positions" and o["facts"]["isin"] == BOND
    )
    return ReviewedBondValuation(
        "synthetic_independent_review",
        sources,
        tuple(
            BondEndpointBinding(
                view["id"],
                next(iter(native)),
                BOND,
                observation["facts"]["ordinal"],
                observation["locator"],
                observation["row_fingerprint"],
                side,
                date(2030, 4, 30) if side == "closing" else date(2030, 3, 31),
            )
            for side in sides
        ),
    )


def _read_reviewed_bond(db, packet):
    with db.session_factory() as session:
        return read_instrument_returns(
            session,
            source_account=ACCOUNT,
            reviewed_bond_valuation=packet,
        )


def _reviewed_bond_file(db, tmp_path):
    packet = _reviewed_bond_packet(db)
    payload = json.loads(json.dumps(asdict(packet), default=date.isoformat))
    payload.update(
        version=FILE_VERSION,
        status="accepted",
        database_incarnation=file_incarnation(db.database_path),
    )
    path = tmp_path / "synthetic-review.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path, payload, packet


def test_reviewed_bond_file_reaches_ordinary_api_and_returns_then_revokes(
    db, tmp_path, monkeypatch
):
    save(db, stock=None, bond=("1", "1", "1000", "1010"), trades=())
    path, payload, _ = _reviewed_bond_file(db, tmp_path)
    # Exercise the actual deployment setting and normal shared request session.
    monkeypatch.setenv("HERMES_FINANCE_REVIEWED_BOND_VALUATION_PATH", str(path))
    client = TestClient(create_app(database=db))
    before = snapshot(db)
    selection = {"scope": "source:" + ACCOUNT, "start": "2030-03-31", "end": "2030-04-30"}
    for accepted in (True, False):
        if not accepted:
            replacement = path.with_suffix(".next")
            replacement.write_text(json.dumps(payload | {"status": "revoked"}), encoding="utf-8")
            replacement.replace(path)
        response = client.get("/api/source-returns/instruments", params={"source_account": ACCOUNT})
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
        result = response.json()
        bond = result["instruments"][0]
        assert bond["analysis"]["closing"]["economic_value_kopecks"] == (
            101000 if accepted else None
        )
        assert result["financial_authority"] == "none"
        assert not result["reconciliation"]["complete"]
        overview = client.get("/api/returns/overview", params=selection)
        detail = client.get("/api/returns/instrument", params=selection | {"isin": BOND})
        assert overview.status_code == detail.status_code == 200
        assert overview.json()["contract_version"] == "returns_source_v2"
        assert detail.json()["contract_version"] == "returns_source_detail_v2"
        assert not overview.json()["instruments"][0]["conditional"]
        assert not detail.json()["conditional"]
        assert overview.json()["instruments"][0]["pnl"] == detail.json()["pnl"]
        if not accepted:
            assert detail.json()["clean"]["closing_value"]["value"] is None
        legacy = selection | {"basis": "legacy"}
        old_overview = client.get("/api/returns/overview", params=legacy)
        old_detail = client.get("/api/returns/instrument", params=legacy | {"isin": BOND})
        assert old_overview.json()["instruments"][0]["conditional"] is not accepted
        assert old_detail.json()["conditional"] is not accepted
        assert overview.headers["cache-control"] == detail.headers["cache-control"] == "no-store"
    assert snapshot(db) == before
    assert json.loads(path.read_text(encoding="utf-8")) == payload | {"status": "revoked"}


@pytest.mark.parametrize(
    "failure",
    [
        "missing",
        "prepared",
        "revoked",
        "malformed",
        "duplicate_key",
        "extra_field",
        "version",
        "database",
        "relative",
        "oversize",
        "boolean_id",
        "head",
        "unreadable",
    ],
)
def test_reviewed_bond_file_failure_never_falls_back_to_packet(db, tmp_path, monkeypatch, failure):
    from pathlib import Path

    save(db, stock=None, bond=("1", "1", "1000", "1010"), trades=())
    path, payload, packet = _reviewed_bond_file(db, tmp_path)
    if failure in {"prepared", "revoked"}:
        payload["status"] = failure
    elif failure == "version":
        payload["version"] = "unknown"
    elif failure == "database":
        payload["database_incarnation"] = "0" * 64
    elif failure == "extra_field":
        payload["automatic_acceptance"] = True
    elif failure == "boolean_id":
        payload["sources"][0]["intake_id"] = True
    elif failure == "head":
        payload["sources"][0]["head_seq"] += 2
    raw = json.dumps(payload)
    if failure == "duplicate_key":
        raw = '{"status":"revoked",' + raw[1:]
    elif failure == "malformed":
        raw = "{"
    elif failure == "oversize":
        raw = " " * (MAX_FILE_BYTES + 1)
    path.write_text(raw, encoding="utf-8")
    if failure == "missing":
        path.unlink()
    elif failure == "relative":
        path = Path(path.name)
    elif failure == "unreadable":
        original_open = Path.open

        def denied(value, *args, **kwargs):
            if value == path:
                raise PermissionError("synthetic review denied")
            return original_open(value, *args, **kwargs)

        monkeypatch.setattr(Path, "open", denied)
    before = snapshot(db)
    with db.session_factory() as session:
        session.info[FILE_PATH_KEY] = path
        result = read_instrument_returns(
            session, source_account=ACCOUNT, reviewed_bond_valuation=packet
        )
    assert result == read(db)
    assert snapshot(db) == before


def test_reviewed_bond_file_identical_database_copy_requires_new_binding(db, tmp_path):
    save(db, stock=None, bond=("1", "1", "1000", "1010"), trades=())
    path, _, _ = _reviewed_bond_file(db, tmp_path)
    copied_path = tmp_path / "synthetic-restored.db"
    with (
        sqlite3.connect(str(db.database_path)) as source,
        sqlite3.connect(str(copied_path)) as target,
    ):
        source.backup(target)
    copied = create_database(copied_path)
    try:
        assert file_incarnation(copied_path) != file_incarnation(db.database_path)
        with copied.session_factory() as session:
            session.info[FILE_PATH_KEY] = path
            result = read_instrument_returns(session, source_account=ACCOUNT)
        assert by_isin(result)[BOND].analysis.closing.economic_value_kopecks is None
    finally:
        copied.engine.dispose()
    # A new application/session on the original physical DB still uses its exact binding.
    with db.session_factory() as session:
        session.info[FILE_PATH_KEY] = path
        result = read_instrument_returns(session, source_account=ACCOUNT)
    assert by_isin(result)[BOND].analysis.closing.economic_value_kopecks == 101000


@pytest.mark.parametrize("failure", ["connection_stamp", "incarnation_unavailable"])
def test_reviewed_bond_file_requires_physical_database_and_connection_stamp(
    db, tmp_path, monkeypatch, failure
):
    from hermes_finance import source_proof_file

    save(db, stock=None, bond=("1", "1", "1000", "1010"), trades=())
    path, _, _ = _reviewed_bond_file(db, tmp_path)
    with db.session_factory() as session:
        session.info[FILE_PATH_KEY] = path
        if failure == "connection_stamp":
            session.connection().info["source_proof_incarnation"] = "0" * 64
        else:
            monkeypatch.setattr(source_proof_file, "file_incarnation", lambda _path: None)
        result = read_instrument_returns(session, source_account=ACCOUNT)
    assert by_isin(result)[BOND].analysis.closing.economic_value_kopecks is None


def test_reviewed_bond_file_cannot_be_selected_by_http_input(db, tmp_path, monkeypatch):
    monkeypatch.delenv("HERMES_FINANCE_REVIEWED_BOND_VALUATION_PATH", raising=False)
    save(db, stock=None, bond=("1", "1", "1000", "1010"), trades=())
    path, _, _ = _reviewed_bond_file(db, tmp_path)
    client = TestClient(create_app(database=db))
    response = client.get(
        "/api/source-returns/instruments",
        params={
            "source_account": ACCOUNT,
            "reviewed_bond_valuation_path": str(path),
            "accepted": "true",
        },
    )
    assert response.status_code == 200
    assert (
        response.json()["instruments"][0]["analysis"]["closing"]["economic_value_kopecks"] is None
    )


def test_reviewed_bond_endpoint_native_once_read_only_and_account_unchanged(db):
    save(db, stock=None, bond=("1", "1", "1000", "1010"), trades=())
    ordinary = read(db)
    packet = _reviewed_bond_packet(db)
    before = snapshot(db)
    result = _read_reviewed_bond(db, packet)
    bond = by_isin(result)[BOND]
    for endpoint, value in ((bond.analysis.opening, 100000), (bond.analysis.closing, 101000)):
        assert endpoint.reported_value_kopecks == endpoint.economic_value_kopecks == value
        assert endpoint.accrued_interest_kopecks is None
        assert endpoint.valuation_basis == "dirty"
        assert endpoint.source_references.count("bond-basis:synthetic_independent_review") == 1
    assert bond.analysis.pnl.value == 1000
    assert bond.analysis.opening.date == date(2030, 3, 31)
    assert bond.analysis.closing.date == date(2030, 4, 30)
    assert "bond_valuation_basis_unknown" not in bond.months[0].flags
    assert result.reconciliation == ordinary.reconciliation
    assert result.authority == "provisional" and result.financial_authority == "none"
    assert snapshot(db) == before
    # Withdrawing the caller's decision supplies no basis; no process cache survives.
    assert read(db) == ordinary


@pytest.mark.parametrize("side", ["opening", "closing"])
def test_reviewed_bond_one_side_does_not_promote_other_side_or_month(db, side):
    save(db, stock=None, bond=("1", "1", "1000", "1010"), trades=())
    bond = by_isin(_read_reviewed_bond(db, _reviewed_bond_packet(db, sides=(side,))))[BOND]
    assert getattr(bond.analysis, side).valuation_basis == "dirty"
    other = "opening" if side == "closing" else "closing"
    assert getattr(bond.analysis, other).economic_value_kopecks is None
    assert bond.analysis.pnl.value is None
    assert "bond_valuation_basis_unknown" in bond.months[0].flags


@pytest.mark.parametrize(
    "field,value",
    [
        ("document_sha256", "0" * 64),
        ("provider", "another_provider"),
        ("parser", "other_parser"),
        ("generation", 99),
        ("head_seq", 99),
        ("manifest_digest", "0" * 64),
        ("covered_from", "2030-04-02"),
        ("covered_to", "2030-04-29"),
        ("intake_id", 99),
    ],
)
def test_reviewed_bond_source_binding_mismatch_stays_unknown(db, field, value):
    save(db, stock=None, bond=("1", "1", "1000", "1010"), trades=())
    packet = _reviewed_bond_packet(db)
    packet = replace(packet, sources=(replace(packet.sources[0], **{field: value}),))
    assert _read_reviewed_bond(db, packet) == read(db)


@pytest.mark.parametrize(
    "field,value",
    [
        ("native_account", "another_native_account"),
        ("isin", ISIN),
        ("ordinal", 999),
        ("locator", "s1/positions/999"),
        ("row_fingerprint", "0" * 64),
        ("side", "other"),
        ("valuation_date", date(2030, 4, 1)),
        ("intake_id", 999),
    ],
)
def test_reviewed_bond_row_binding_mismatch_stays_unknown(db, field, value):
    save(db, stock=None, bond=("1", "1", "1000", "1010"), trades=())
    packet = _reviewed_bond_packet(db)
    packet = replace(packet, endpoints=(replace(packet.endpoints[0], **{field: value}),))
    assert _read_reviewed_bond(db, packet) == read(db)


@pytest.mark.parametrize(
    "change", ["dict", "duplicate_source", "duplicate_endpoint", "empty", "bad_ref"]
)
def test_reviewed_bond_invalid_packet_is_not_acceptance(db, change):
    save(db, stock=None, bond=("1", "1", "1000", "1010"), trades=())
    packet = _reviewed_bond_packet(db)
    if change == "dict":
        packet = {"accepted": True}
    elif change == "duplicate_source":
        packet = replace(packet, sources=packet.sources * 2)
    elif change == "duplicate_endpoint":
        packet = replace(packet, endpoints=packet.endpoints * 2)
    elif change == "empty":
        packet = replace(packet, endpoints=())
    else:
        packet = replace(packet, review_reference="arbitrary/path/to/file")
    assert _read_reviewed_bond(db, packet) == read(db)


@pytest.mark.parametrize("conflict", [False, True])
def test_reviewed_bond_overlap_checked_without_inheriting_acceptance(db, conflict):
    first = save(db, stock=None, bond=("1", "1", "1000", "1010"), trades=())
    old_packet = _reviewed_bond_packet(db)
    second = save(
        db,
        stock=None,
        bond=("1", "1", "1000", "1020" if conflict else "1010"),
        trades=(),
        marker="another exact original, same filename",
    )
    assert first != second
    assert _read_reviewed_bond(db, old_packet) == read(db)  # whole current set changed
    packet = _reviewed_bond_packet(db, intake_id=first)
    result = by_isin(_read_reviewed_bond(db, packet))[BOND].analysis
    if conflict:
        assert result.closing.economic_value_kopecks is None
        assert "overlapping_endpoint_conflict" in result.closing.reason_codes
    else:
        assert result.closing.economic_value_kopecks == 101000
        assert result.pnl.value == 1000
        assert len(result.closing.source_references) == 3  # two observations, one review


@pytest.mark.parametrize(
    "change",
    ["head_aba", "missing_bound", "unreadable", "inferred", "missing_row", "duplicate_row"],
)
def test_reviewed_bond_current_selection_failures_do_not_fallback(db, monkeypatch, change):
    from hermes_finance.services import source_instrument_returns as service

    first = save(db, stock=None, bond=("1", "1", "1000", "1010"), trades=())
    save(db, stock=None, bond=("1", "1", "1000", "1010"), trades=(), marker="equal alternative")
    packet = _reviewed_bond_packet(db, intake_id=first)
    select_sources = service._selected_sources

    def changed(session, source_account):
        selected, scope = select_sources(session, source_account)
        original, view, error = selected[0]
        view = deepcopy(view)
        if change == "missing_bound":
            return selected[1:], scope
        if change == "unreadable":
            return [(original, None, "source_reader_unavailable"), *selected[1:]], scope
        if change == "head_aba":
            view["head_seq"] += 2  # identical manifest after two intervening revisions
        elif change == "inferred":
            view["document"]["warnings"] = ["period_inferred_from_content"]
        elif change == "missing_row":
            view["document"]["positions"] = []
        elif change == "duplicate_row":
            view["document"]["positions"] *= 2
        return [(original, view, error), *selected[1:]], scope

    monkeypatch.setattr(service, "_selected_sources", changed)
    result = by_isin(_read_reviewed_bond(db, packet))[BOND].analysis
    assert result.opening.economic_value_kopecks is None
    assert result.closing.economic_value_kopecks is None


@pytest.mark.parametrize("value", ["0", ""])
def test_reviewed_bond_explicit_zero_is_not_missing_value(db, value):
    save(db, stock=None, bond=("0", "0", value, value), trades=())
    result = by_isin(_read_reviewed_bond(db, _reviewed_bond_packet(db)))[BOND].analysis
    if value == "0":
        assert result.opening.economic_value_kopecks == result.closing.economic_value_kopecks == 0
    else:
        assert (
            result.opening.economic_value_kopecks is result.closing.economic_value_kopecks is None
        )


@pytest.mark.parametrize("fee", ["2", None])
def test_reviewed_bond_endpoint_does_not_double_nkd_or_clear_missing_cost(db, fee):
    save(
        db,
        stock=None,
        bond=("0", "1", "0", "1010"),
        trades=((BOND, "1", "1020", "20", fee),),
        mutate=trade_date(15, price="100", money=(("Купон", BOND, "30", 30),)),
    )
    ordinary = read(db)
    before = snapshot(db)
    result = _read_reviewed_bond(db, _reviewed_bond_packet(db))
    analysis = by_isin(result)[BOND].analysis
    assert analysis.closing.economic_value_kopecks == 101000
    assert analysis.closing.accrued_interest_kopecks is None
    assert analysis.events == by_isin(ordinary)[BOND].analysis.events
    if fee is None:
        assert analysis.pnl.value is None
        assert not analysis.coverage["costs"].complete
    else:
        assert analysis.components["buys"].value == 102200
        assert analysis.pnl.value == 1800  # 1010 - (1020 + 2) + 30; NKD only once
    assert result.reconciliation == ordinary.reconciliation
    assert snapshot(db) == before


def trade_date(day=10, *, depo=None, money=(), price="100", currency="RUB"):
    def mutate(root):
        for row in root.findall(".//m:Details[@trade_no]", NS):
            row.set("save_settlement_date", f"{day:02d}.04.2030")
            row.set("save_depo_settlement_date", f"{depo or day:02d}.04.2030")
            row.set("db_time", f"{day:02d}.04.2030 09:00:00")
            row.set("Price", price)
            row.set("curr_calc", currency)
        for operation, text, amount, posting in money:
            _add_money(root, operation, text, amount, day=f"2030-04-{posting:02d}")

    return mutate


@pytest.mark.parametrize(
    "opening,closing,qty,amount,day,expected,capital",
    [
        (("0", "10", "0", "1100"), None, "10", "1000", 10, 10000, 2000000),
        (("10", "15", "1000", "1600"), None, "5", "500", 5, 10000, 4250000),
        (("10", "15", "1000", "1600"), None, "5", "500", 25, 10000, 3250000),
        (("10", "6", "1000", "660"), None, "-4", "440", 15, 10000, 2340000),
        (("10", "0", "1000", "0"), None, "-10", "1100", 20, 10000, 1900000),
        (("0", "10", "0", "1100"), None, "10", "1000", 30, 10000, 0),
    ],
)
def test_saved_trade_contract_vectors(db, opening, closing, qty, amount, day, expected, capital):
    save(
        db,
        stock=opening,
        bond=closing,
        trades=((ISIN, qty, amount, None, "0"),),
        mutate=trade_date(day),
    )
    before = snapshot(db)
    instrument = by_isin(read(db))[ISIN]
    a = instrument.analysis
    assert a.pnl.value == expected, a.reason_codes
    assert a.modified_dietz.capital_days == capital
    if capital:
        with localcontext() as context:
            context.prec = 60
            assert a.modified_dietz.value == Decimal(expected * 30) / Decimal(capital)
    else:
        assert a.modified_dietz.value is None
    assert a.history_complete_since_acquisition == (opening[0] == "0")
    assert a.opening_date == date(2030, 3, 31) and a.closing_date == date(2030, 4, 30)
    assert a.events[0].execution_date == date(2030, 4, day)
    assert a.events[0].cash_settlement_date == date(2030, 4, day)
    assert a.events[0].unit_price == 100
    assert a.events[0].attribution_basis == "native_trade_settlement"
    assert a.coverage["quantity"].complete
    assert a.pnl.status == "supported"
    assert instrument.months[0].analysis.pnl == a.pnl
    assert instrument.months[0].analysis.modified_dietz == a.modified_dietz
    assert snapshot(db) == before


def test_reinvestment_two_visible_events_and_other_isin_keeps_issuer(db):
    save(
        db,
        stock=("10", "11", "1000", "1100"),
        bond=None,
        trades=((ISIN, "1", "100", None, "0"),),
        extra=(("Дивиденды", ISIN, "100"),),
        mutate=trade_date(15),
    )
    a = by_isin(read(db))[ISIN].analysis
    assert {e.kind for e in a.events} == {"DIVIDEND", "BUY"}
    assert a.pnl.value == 10000 and a.modified_dietz.value == Decimal("0.1")
    assert a.events[0].gross_payout_kopecks is None

    # A distinct acquired security gets the BUY but not the issuer's payout.
    def distinct_trade(root):
        trade_date(15, price="10")(root)
        root.find(".//m:Details[@trade_no]", NS).set("trade_no", "10000000002\n2000000002")

    save(
        db,
        5,
        stock=("11", "11", "1100", "1100"),
        bond=("0", "1", "0", "100"),
        trades=((BOND, "1", "100", "0", "0"),),
        extra=(("Дивиденды", ISIN, "100"),),
        mutate=distinct_trade,
    )
    result = by_isin(read(db))
    assert result[ISIN].months[1].analysis.components["dividends"].value == 10000
    assert result[BOND].months[1].analysis.components["dividends"].value == 0


@pytest.mark.parametrize("amount", ["1000"])
def test_bond_nkd_fee_known_components_but_unknown_endpoint_basis_only_estimate(db, amount):
    save(
        db,
        stock=None,
        bond=("0", "1", "0", "1010"),
        trades=((BOND, "1", amount, "20", "2"),),
        mutate=trade_date(15, price="98", money=(("Купон", BOND, "30", 30),)),
    )
    a = by_isin(read(db))[BOND].analysis
    assert a.components["buys"].value == 100200
    assert a.pnl.value is a.modified_dietz.value is None
    assert a.statement_estimate.pnl.value == 3800
    assert a.statement_estimate.pnl.status == "provisional"
    assert a.statement_estimate.modified_dietz.capital_days == 1503000
    assert a.statement_estimate.assumptions == ("bond_valuation_basis_unknown", "income_assumed")
    assert a.opening.economic_value_kopecks is None


@pytest.mark.parametrize("posting", [10, 12])
def test_matched_money_owns_principal_and_fee_once_on_actual_posting_date(db, posting):
    save(
        db,
        stock=("0", "10", "0", "1100"),
        bond=None,
        trades=((ISIN, "10", "1000", None, "2"),),
        mutate=trade_date(
            10,
            money=(
                ("Расчеты по сделке 10000000001", "Synthetic principal", "-1000", posting),
                ("Комиссия по сделке 10000000001", "Synthetic fee", "-2", posting),
            ),
        ),
    )
    a = by_isin(read(db))[ISIN].analysis
    assert a.pnl.value == 9800, a.reason_codes
    (buy,) = a.events
    assert len(buy.cash_legs) == 2
    assert all(leg.ownership.startswith("money:") for leg in buy.cash_legs)
    assert all(leg.date == date(2030, 4, posting) for leg in buy.cash_legs)
    assert a.modified_dietz.capital_days == 100200 * (30 - posting)


@pytest.mark.parametrize(
    "extra,reason",
    [
        ((("Комиссия", "ambiguous commission", "-2"),), "unallocated_instrument_cost"),
        ((("НДФЛ", "Дивиденды НДФЛ", "87"),), "payout_classification_conflict"),
        (
            (("Перевод", "Погашение облигаций Synthetic", "1000"),),
            "redemption_amortization_unsupported",
        ),
        ((("Дивиденды", "unidentified issuer", "87"),), "unattributed_income"),
    ],
)
def test_unallocated_or_misclassified_evidence_is_inspectable_not_zero(db, extra, reason):
    save(db, bond=None, trades=(), extra=extra)
    result = read(db)
    a = by_isin(result)[ISIN].analysis
    assert a.pnl.value is a.modified_dietz.value is None
    assert reason in a.reason_codes
    assert result.unresolved_events
    instrument = by_isin(result)[ISIN]
    assert instrument.months[0].total_kopecks is None
    assert instrument.months[0].return_percent is None
    assert instrument.all_time.total_kopecks is None


def test_explicit_account_only_cost_is_not_allocated_and_tax_is_once(db):
    save(
        db,
        bond=None,
        trades=(),
        stock=("10", "10", "1000", "1000"),
        extra=(
            ("Дивиденды", ISIN, "100"),
            ("НДФЛ", ISIN, "-13"),
            ("Комиссия", "account maintenance", "-2"),
        ),
    )
    result = read(db)
    a = by_isin(result)[ISIN].analysis
    assert a.pnl.value == 8700
    assert by_isin(result)[ISIN].months[0].total_kopecks == 8700
    assert a.components["taxes"].value == 1300
    assert result.account_reconciliation_events[0].cash_legs[0].account_cash_kopecks == -200


@pytest.mark.parametrize(
    "description,account_only", [("account maintenance", True), ("ambiguous commission", False)]
)
def test_overlapping_account_cost_gap_stays_with_account(db, description, account_only):
    save(db, trades=(), extra=(("Комиссия", description, "-2"),), marker="with-cost")
    save(db, trades=(), marker="without-cost")
    before = snapshot(db)
    result = read(db)
    stock = by_isin(result)[ISIN]
    assert stock.analysis.pnl.value == (10000 if account_only else None)
    assert stock.months[0].total_kopecks == (10000 if account_only else None)
    assert ("overlap_money_occurrence_missing" in stock.analysis.reason_codes) != account_only
    # Missing account evidence remains visible and cannot reconcile to zero.
    assert not result.reconciliation.complete
    assert result.reconciliation.residual.value is None
    if account_only:
        (event,) = result.account_reconciliation_events
        assert "overlap_money_occurrence_missing" in event.reason_codes
        assert not stock.analysis.events
    else:
        assert result.unresolved_events
    # Independent missing bond valuation is never promoted to zero/complete.
    assert by_isin(result)[BOND].analysis.pnl.value is None
    assert "bond_valuation_basis_unknown" in by_isin(result)[BOND].analysis.reason_codes
    assert snapshot(db) == before


@pytest.mark.parametrize("paired", [True, False])
@pytest.mark.parametrize("repo_fee", ["0", None])
def test_fifo_reader_same_isin_repo_and_unique_ordinary_trades(db, paired, repo_fee):
    from hermes_finance.services.clean_instrument_return import read_clean_account

    def repo_after_ordinary(root):
        rows = root.findall(".//m:Details[@trade_no]", NS)
        for index, row in enumerate(rows, 9):
            stamp = f"15.04.2030 {index}:00:00"
            row.set("db_time", f"{stamp}\n{stamp}")
            delivery = f"{index + 7}.04.2030"
            row.set("save_settlement_date", delivery)
            row.set("save_depo_settlement_date", delivery)
            if index >= 11:
                row.set("trade_no", f"B9000{index - 10}")
                row.set("repo_no", f"B9000{2 if index == 11 else 1}")
                row.set("comment", f"репо ч.{index - 10}")

    repo = [(ISIN, "5", "500", "0", repo_fee)]
    if paired:
        repo.append((ISIN, "-5", "501", "0", "0"))
    save(
        db,
        stock=("0", "5" if paired else "10", "0", "550" if paired else "1100"),
        bond=None,
        trades=((ISIN, "10", "1000", "0", "0"), (ISIN, "-5", "600", "0", "0"), *repo),
        mutate=repo_after_ordinary,
    )
    analysis = by_isin(read(db))[ISIN].analysis
    with db.session_factory() as session:
        result = read_clean_account(
            session,
            ACCOUNT,
            date(2030, 3, 31),
            date(2030, 4, 30),
            isin=ISIN,
            include_purchases=True,
        )
    rows = result["instruments"][0]["purchases"]
    if paired:
        assert rows is not None, (
            {key: value.reason_codes for key, value in analysis.coverage.items()},
            [(e.kind, e.native_ids, e.native_identity, e.reason_codes) for e in analysis.events],
        )
        assert rows[0]["price_result_kopecks"] == "15000"
        from hermes_finance.services.clean_repo_pairs import without_proven_closed_repo
        from hermes_finance.services.source_monthly_returns import _selected_sources

        with db.session_factory() as session:
            selected, _ = _selected_sources(session, ACCOUNT)
            views = [view for _, view, error in selected if not error]
        assert without_proven_closed_repo(analysis, views, ISIN) is not analysis
        conflict = deepcopy(views)
        pending = deepcopy(
            next(t for t in conflict[0]["document"]["trades"] if t.get("repo_observed"))
        )
        pending["section"] = "pending"
        pending["core"]["isin"] = BOND
        conflict[0]["document"]["trades"].append(pending)
        assert without_proven_closed_repo(analysis, conflict, ISIN) is analysis
        pending["ids"] = ["B99999"]
        assert without_proven_closed_repo(analysis, conflict, ISIN) is not analysis
    else:
        assert rows is None or all(row["price_result_kopecks"] is None for row in rows)


@pytest.mark.parametrize(
    "repo_fee",
    [
        "0",
        None,
        "missing_depo",
        "missing_cash",
        "missing_both_costs",
        "depo_before_execution",
        "foreign_currency",
    ],
)
@pytest.mark.parametrize("extra_missing", [False, True])
def test_fifo_reader_open_repo_after_closed_purchase_preserves_closed_result(
    db, repo_fee, extra_missing
):
    from hermes_finance.services.clean_instrument_return import read_clean_account
    from hermes_finance.services.reporting_months import create_reporting_month

    def mutate(root):
        for index, row in enumerate(root.findall(".//m:Details[@trade_no]", NS), 1):
            stamp = f"{index:02}.04.2030 09:00:00"
            row.set("db_time", f"{stamp}\n{stamp}")
            row.set("save_settlement_date", f"{index:02}.04.2030")
            row.set("save_depo_settlement_date", f"{index:02}.04.2030")
            if index == 3:
                row.set("trade_no", "B90001")
                row.set("repo_no", "B90002")
                row.set("comment", "репо ч.1")
                if repo_fee == "missing_depo":
                    row.attrib.pop("save_depo_settlement_date", None)
                if repo_fee == "missing_cash":
                    row.attrib.pop("save_settlement_date", None)
                if repo_fee == "depo_before_execution":
                    row.set("save_depo_settlement_date", "01.04.2030")
                if repo_fee == "foreign_currency":
                    row.set("curr_calc", "USD")

    save(
        db,
        stock=("0", "2" if extra_missing else "1", "0", "200" if extra_missing else "100"),
        bond=None,
        trades=(
            (ISIN, "1", "100", "0", "0"),
            (ISIN, "-1", "180", "0", "0"),
            (
                ISIN,
                "1",
                "100",
                None if repo_fee == "missing_both_costs" else "0",
                None
                if repo_fee == "missing_both_costs"
                else (
                    "0"
                    if repo_fee
                    in {"missing_depo", "missing_cash", "depo_before_execution", "foreign_currency"}
                    else repo_fee
                ),
            ),
            *(((ISIN, "1", "100", "0", None),) if extra_missing else ()),
        ),
        mutate=mutate,
    )
    with db.session_factory() as session:
        result = read_clean_account(
            session,
            ACCOUNT,
            date(2030, 3, 31),
            date(2030, 4, 30),
            isin=ISIN,
            include_purchases=True,
        )
    rows = result["instruments"][0]["purchases"]
    observed = by_isin(read(db))[ISIN].analysis
    assert rows, (
        observed.coverage,
        [(e.native_identity, e.reason_codes, e.attribution_basis) for e in observed.events],
    )
    if repo_fee in {"missing_depo", "depo_before_execution"}:
        assert rows[0]["price_result_kopecks"] is None and rows[0]["status"] == "partial"
        assert rows[0]["cost_kopecks"] == "10000"
        assert result["instruments"][0]["sells"]["value"] == "18000"
    else:
        assert rows[0]["price_result_kopecks"] == "8000"
        assert rows[0]["remaining_quantity"] == "0"
    with db.session_factory() as session:
        create_reporting_month(session, year=2030, month=4, snapshot_date=date(2030, 4, 30))
    before = snapshot(db)
    with TestClient(create_app(db)) as client:
        card = client.get("/api/returns/instrument-card", params={"isin": ISIN})
        report = client.get(
            "/api/export/ai-financial-review/json", params={"format_version": "3.1.0"}
        )
    assert card.status_code == report.status_code == 200
    account = card.json()["accounts"][0]
    exported = report.json()["sections"]["clean_returns"]["data"]["accounts"][0]
    assert exported["account_ref"] == account["ai_account_ref"]
    assert exported["period"] == account["period"]
    assert [
        {k: v for k, v in row.items() if k != "id"}
        for row in exported["instruments"][0]["purchases"]
    ] == [{k: v for k, v in row.items() if k != "id"} for row in account["purchases"]]
    assert account["purchases"][0]["price_result_kopecks"] == (
        None if repo_fee in {"missing_depo", "depo_before_execution"} else "8000"
    )
    assert snapshot(db) == before


@pytest.mark.parametrize("same_day_delivery", [False, True])
def test_fifo_reader_repo_checks_intermediate_custody_under_all_day_orders(db, same_day_delivery):
    from hermes_finance.services.clean_instrument_return import read_clean_account

    def mutate(root):
        for index, row in enumerate(root.findall(".//m:Details[@trade_no]", NS), 1):
            stamp = f"{index:02}.04.2030 09:00:00"
            row.set("db_time", f"{stamp}\n{stamp}")
            day = 4 if same_day_delivery and index in (3, 4) else index
            row.set("save_settlement_date", f"{day:02}.04.2030")
            row.set("save_depo_settlement_date", f"{day:02}.04.2030")
            if index in (2, 4):
                row.set("trade_no", "B90001" if index == 2 else "B90002")
                row.set("repo_no", "B90002" if index == 2 else "B90001")
                row.set("comment", "репо ч.1" if index == 2 else "репо ч.2")

    save(
        db,
        stock=("0", "0", "0", "0"),
        bond=None,
        trades=(
            (ISIN, "1", "100", "0", "0"),
            (ISIN, "-1", "100", "0", "0"),
            (ISIN, "-1", "180", "0", "0"),
            (ISIN, "1", "101", "0", "0"),
        ),
        mutate=mutate,
    )
    with db.session_factory() as session:
        result = read_clean_account(
            session,
            ACCOUNT,
            date(2030, 3, 31),
            date(2030, 4, 30),
            isin=ISIN,
            include_purchases=True,
        )
    rows = result["instruments"][0]["purchases"]
    assert rows is None or all(row["price_result_kopecks"] is None for row in rows)


@pytest.mark.parametrize("closed", [True, False])
@pytest.mark.parametrize("overlap", [None, "identical", "missing", "changed", "duplicate"])
def test_fifo_reader_closed_repo_before_selected_period_does_not_hide_later_purchase(
    db, closed, overlap
):
    from hermes_finance.services.clean_instrument_return import read_clean_account

    def repo(root):
        for i, row in enumerate(root.findall(".//m:Details[@trade_no]", NS), 1):
            row.set("trade_no", f"B9000{i}")
            row.set("repo_no", f"B9000{3 - i}")
            row.set("comment", f"репо ч.{i}")
            stamp = f"{i:02}.04.2030 09:00:00"
            row.set("db_time", f"{stamp}\n{stamp}")
            row.set("save_settlement_date", f"{i:02}.04.2030")
            row.set("save_depo_settlement_date", f"{i:02}.04.2030")

    def ordinary(root):
        for i, row in enumerate(root.findall(".//m:Details[@trade_no]", NS), 1):
            stamp = f"{i:02}.04.2030 09:00:00"
            row.set("db_time", f"{stamp}\n{stamp}")
            row.set("save_settlement_date", f"{i:02}.04.2030")
            row.set("save_depo_settlement_date", f"{i:02}.04.2030")

    save(
        db,
        4,
        stock=("0", "0" if closed else "1", "0", "0" if closed else "100"),
        bond=None,
        trades=(
            (ISIN, "1", "100", "0", "0"),
            *(((ISIN, "-1", "101", "0", "0"),) if closed else ()),
        ),
        mutate=repo,
    )
    if overlap:

        def overlap_repo(root):
            repo(root)
            collection = root.find(".//m:Tablix2/m:Details_Collection", NS)
            if overlap == "missing" and closed:
                collection.remove(collection[-1])
            elif overlap == "changed":
                collection[0].set("qty", "2")
            elif overlap == "duplicate":
                collection.append(deepcopy(collection[0]))

        save(
            db,
            4,
            stock=("0", "0" if closed else "1", "0", "0" if closed else "100"),
            bond=None,
            trades=(
                (ISIN, "1", "100", "0", "0"),
                *(((ISIN, "-1", "101", "0", "0"),) if closed else ()),
            ),
            mutate=overlap_repo,
            marker="overlap",
        )
    save(
        db,
        5,
        stock=(
            "0" if closed else "1",
            "0" if closed else "1",
            "0" if closed else "100",
            "0" if closed else "100",
        ),
        bond=None,
        trades=((ISIN, "1", "100", "0", "0"), (ISIN, "-1", "180", "0", "0")),
        mutate=ordinary,
    )
    with db.session_factory() as session:
        data = read_clean_account(
            session,
            ACCOUNT,
            date(2030, 4, 30),
            date(2030, 5, 31),
            isin=ISIN,
            include_purchases=True,
        )
    rows = data["instruments"][0]["purchases"]
    if closed and overlap in (None, "identical"):
        assert rows and rows[0]["price_result_kopecks"] == "8000"
    else:
        assert rows is None or all(row["price_result_kopecks"] is None for row in rows)


def test_pending_b_identifier_is_rejected_by_existing_parser():
    from xml.etree import ElementTree

    from test_statement_import_mybroker import FILENAME, fixture

    from hermes_finance.statement_import.mybroker import MyBrokerError, parse_mybroker

    root = ElementTree.fromstring(fixture(pending=True, money=False))
    root.find(".//{MyBroker}Details2").set("trade_no1", "B90001")
    with pytest.raises(MyBrokerError, match="trade_ids_ambiguous"):
        parse_mybroker(ElementTree.tostring(root), FILENAME)


def test_unexplained_closing_quantity_prevents_false_closed_purchase(db):
    from hermes_finance.services.clean_instrument_return import read_clean_account

    def mutate(root):
        for index, row in enumerate(root.findall(".//m:Details[@trade_no]", NS), 1):
            stamp = f"{index:02}.04.2030 09:00:00"
            row.set("db_time", f"{stamp}\n{stamp}")
            row.set("save_settlement_date", f"{index:02}.04.2030")
            row.set("save_depo_settlement_date", f"{index:02}.04.2030")
            if index == 3:
                row.set("trade_no", "B90001")
                row.set("repo_no", "B90002")
                row.set("comment", "репо ч.1")

    save(
        db,
        stock=("0", "2", "0", "200"),
        bond=None,
        trades=(
            (ISIN, "1", "100", "0", "0"),
            (ISIN, "-1", "180", "0", "0"),
            (ISIN, "1", "100", "0", "0"),
        ),
        mutate=mutate,
    )
    with db.session_factory() as session:
        result = read_clean_account(
            session,
            ACCOUNT,
            date(2030, 3, 31),
            date(2030, 4, 30),
            isin=ISIN,
            include_purchases=True,
        )
    instrument = result["instruments"][0]
    assert instrument["sells"]["value"] == "18000"
    rows = instrument["purchases"]
    assert rows and rows[0]["cost_kopecks"] == "10000"
    assert rows[0]["price_result_kopecks"] is None and rows[0]["status"] == "partial"
    from hermes_finance.services.reporting_months import create_reporting_month

    with db.session_factory() as session:
        create_reporting_month(session, year=2030, month=4, snapshot_date=date(2030, 4, 30))
    before = snapshot(db)
    with TestClient(create_app(db)) as client:
        card = client.get("/api/returns/instrument-card", params={"isin": ISIN})
        ai = client.get("/api/export/ai-financial-review/json", params={"format_version": "3.1.0"})
    assert card.status_code == ai.status_code == 200
    account = card.json()["accounts"][0]
    exported = ai.json()["sections"]["clean_returns"]["data"]["accounts"][0]
    assert (
        account["ai_account_ref"] == exported["account_ref"]
        and account["period"] == exported["period"]
    )
    assert account["purchases"][0]["price_result_kopecks"] is None
    assert exported["instruments"][0]["purchases"][0]["price_result_kopecks"] is None
    assert snapshot(db) == before


def test_unclassified_money_preserves_independent_purchase_facts(db):
    from hermes_finance.services.clean_instrument_return import read_clean_account
    from hermes_finance.services.reporting_months import create_reporting_month

    def mutate(root):
        for index, row in enumerate(root.findall(".//m:Details[@trade_no]", NS), 1):
            stamp = f"{index:02}.04.2030 09:00:00"
            row.set("db_time", f"{stamp}\n{stamp}")
            row.set("save_settlement_date", f"{index:02}.04.2030")
            row.set("save_depo_settlement_date", f"{index:02}.04.2030")

    save(
        db,
        stock=("0", "0", "0", "0"),
        bond=None,
        trades=((ISIN, "1", "100", "0", "0"), (ISIN, "-1", "180", "0", "0")),
        extra=(("НЕИЗВЕСТНАЯ ОПЕРАЦИЯ", "unparsed synthetic", "-1"),),
        mutate=mutate,
    )
    with db.session_factory() as session:
        result = read_clean_account(
            session,
            ACCOUNT,
            date(2030, 3, 31),
            date(2030, 4, 30),
            isin=ISIN,
            include_purchases=True,
        )
        create_reporting_month(session, year=2030, month=4, snapshot_date=date(2030, 4, 30))
    instrument = result["instruments"][0]
    assert instrument["sells"]["value"] == "18000"
    rows = instrument["purchases"]
    assert rows and rows[0]["cost_kopecks"] == "10000"
    assert rows[0]["price_result_kopecks"] is None and rows[0]["status"] == "partial"
    assert rows[0]["sale_proceeds_kopecks"] is None and rows[0]["remaining_quantity"] is None
    before = snapshot(db)
    with TestClient(create_app(db)) as client:
        card = client.get("/api/returns/instrument-card", params={"isin": ISIN})
        ai = client.get("/api/export/ai-financial-review/json", params={"format_version": "3.1.0"})
    assert card.status_code == ai.status_code == 200
    account = card.json()["accounts"][0]
    exported = ai.json()["sections"]["clean_returns"]["data"]["accounts"][0]
    assert (
        account["ai_account_ref"] == exported["account_ref"]
        and account["period"] == exported["period"]
    )
    card_rows, ai_rows = account["purchases"], exported["instruments"][0]["purchases"]
    assert card_rows[0]["cost_kopecks"] == ai_rows[0]["cost_kopecks"] == "10000"
    assert (
        card_rows[0]["price_result_kopecks"] is None and ai_rows[0]["price_result_kopecks"] is None
    )
    assert snapshot(db) == before


@pytest.mark.parametrize("inside", [True, False])
def test_purchase_facts_keep_execution_before_period_when_settled_inside(db, inside):
    from hermes_finance.services.clean_instrument_return import read_clean_account
    from hermes_finance.services.reporting_months import create_reporting_month

    def mutate(root):
        row = root.find(".//m:Details[@trade_no]", NS)
        row.set("db_time", "31.03.2030 09:00:00\n31.03.2030 09:00:00")
        day = "01.04.2030" if inside else "31.03.2030"
        row.set("save_settlement_date", day)
        row.set("save_depo_settlement_date", day)

    save(
        db,
        stock=("0" if inside else "1", "1", "0" if inside else "100", "100"),
        bond=None,
        trades=((ISIN, "1", "100", "0", "0"),),
        extra=(("НЕИЗВЕСТНАЯ ОПЕРАЦИЯ", "unparsed synthetic", "-1"),),
        mutate=mutate,
    )
    with db.session_factory() as session:
        result = read_clean_account(
            session,
            ACCOUNT,
            date(2030, 3, 31),
            date(2030, 4, 30),
            isin=ISIN,
            include_purchases=True,
        )
        create_reporting_month(session, year=2030, month=4, snapshot_date=date(2030, 4, 30))
    rows = result["instruments"][0]["purchases"]
    if inside:
        assert rows and rows[0]["date"] == date(2030, 3, 31)
        assert rows[0]["cost_kopecks"] == "10000" and rows[0]["status"] == "partial"
        assert rows[0]["remaining_quantity"] is None and rows[0]["price_result_kopecks"] is None
    else:
        assert rows is None
    before = snapshot(db)
    with TestClient(create_app(db)) as client:
        card = client.get("/api/returns/instrument-card", params={"isin": ISIN})
        ai = client.get("/api/export/ai-financial-review/json", params={"format_version": "3.1.0"})
    assert card.status_code == ai.status_code == 200
    account = card.json()["accounts"][0]
    exported = ai.json()["sections"]["clean_returns"]["data"]["accounts"][0]
    assert (
        account["ai_account_ref"] == exported["account_ref"]
        and account["period"] == exported["period"]
    )
    ui_rows, ai_rows = account.get("purchases"), exported["instruments"][0]["purchases"]
    if inside:
        assert ui_rows[0]["date"] == ai_rows[0]["date"] == "2030-03-31"
        assert ui_rows[0]["cost_kopecks"] == ai_rows[0]["cost_kopecks"] == "10000"
        assert (
            ui_rows[0]["price_result_kopecks"] is None
            and ai_rows[0]["price_result_kopecks"] is None
        )
    else:
        assert ui_rows is None and ai_rows is None
    assert snapshot(db) == before


def test_missing_repo_overlap_preserves_independent_purchase_facts(db):
    from hermes_finance.services.clean_instrument_return import read_clean_account
    from hermes_finance.services.reporting_months import create_reporting_month

    def mutate(root):
        for index, row in enumerate(root.findall(".//m:Details[@trade_no]", NS), 1):
            stamp = f"{index:02}.04.2030 09:00:00"
            row.set("db_time", f"{stamp}\n{stamp}")
            row.set("save_settlement_date", f"{index:02}.04.2030")
            row.set("save_depo_settlement_date", f"{index:02}.04.2030")
            if index == 3:
                row.set("trade_no", "B90001")
                row.set("repo_no", "B90002")
                row.set("comment", "репо ч.1")

    ordinary = ((ISIN, "1", "100", "0", "0"), (ISIN, "-1", "180", "0", "0"))
    common = dict(stock=("0", "1", "0", "100"), bond=None)
    save(
        db,
        **common,
        trades=(*ordinary, (ISIN, "1", "100", "0", "0")),
        mutate=mutate,
        marker="first",
    )
    save(db, **common, trades=ordinary, mutate=mutate, marker="second")
    with db.session_factory() as session:
        result = read_clean_account(
            session,
            ACCOUNT,
            date(2030, 3, 31),
            date(2030, 4, 30),
            isin=ISIN,
            include_purchases=True,
        )
        create_reporting_month(session, year=2030, month=4, snapshot_date=date(2030, 4, 30))
    instrument = result["instruments"][0]
    assert instrument["sells"]["value"] == "18000"
    rows = instrument["purchases"]
    assert rows and rows[0]["cost_kopecks"] == "10000"
    assert rows[0]["price_result_kopecks"] is None and rows[0]["status"] == "partial"
    before = snapshot(db)
    with TestClient(create_app(db)) as client:
        card = client.get("/api/returns/instrument-card", params={"isin": ISIN})
        ai = client.get("/api/export/ai-financial-review/json", params={"format_version": "3.1.0"})
    assert card.status_code == ai.status_code == 200
    account = card.json()["accounts"][0]
    exported = ai.json()["sections"]["clean_returns"]["data"]["accounts"][0]
    assert (
        account["ai_account_ref"] == exported["account_ref"]
        and account["period"] == exported["period"]
    )
    card_rows, ai_rows = account["purchases"], exported["instruments"][0]["purchases"]
    assert card_rows[0]["cost_kopecks"] == ai_rows[0]["cost_kopecks"] == "10000"
    assert (
        card_rows[0]["price_result_kopecks"] is None and ai_rows[0]["price_result_kopecks"] is None
    )
    assert snapshot(db) == before


@pytest.mark.parametrize("sale_delivery", [2, 3, 4])
def test_repo_boundary_considers_ordinary_delivery_after_execution(db, sale_delivery):
    from hermes_finance.services.clean_instrument_return import read_clean_account

    def mutate(root):
        for index, row in enumerate(root.findall(".//m:Details[@trade_no]", NS), 1):
            stamp = f"{index:02}.04.2030 09:00:00"
            row.set("db_time", f"{stamp}\n{stamp}")
            row.set("save_settlement_date", f"{index:02}.04.2030")
            row.set(
                "save_depo_settlement_date", f"{sale_delivery if index == 2 else index:02}.04.2030"
            )
            if index == 3:
                row.set("trade_no", "B90001")
                row.set("repo_no", "B90002")
                row.set("comment", "репо ч.1")

    save(
        db,
        stock=("0", "1", "0", "100"),
        bond=None,
        trades=(
            (ISIN, "1", "100", "0", "0"),
            (ISIN, "-1", "180", "0", "0"),
            (ISIN, "1", "100", "0", "0"),
        ),
        mutate=mutate,
    )
    with db.session_factory() as session:
        result = read_clean_account(
            session,
            ACCOUNT,
            date(2030, 3, 31),
            date(2030, 4, 30),
            isin=ISIN,
            include_purchases=True,
        )
    rows = result["instruments"][0]["purchases"]
    assert rows and rows[0]["cost_kopecks"] == "10000"
    if sale_delivery == 2:
        assert rows[0]["price_result_kopecks"] == "8000"
    else:
        assert rows[0]["price_result_kopecks"] is None and rows[0]["status"] == "partial"


@pytest.mark.parametrize(
    "conflict", ["late", "early_delivery", "missing_delivery", "different_qty", "ordinary"]
)
def test_late_repo_conflict_preserves_only_proven_closed_prefix(db, conflict):
    from hermes_finance.services.clean_instrument_return import read_clean_account

    def make(changed):
        def mutate(root):
            for index, row in enumerate(root.findall(".//m:Details[@trade_no]", NS), 1):
                stamp = f"{index:02}.04.2030 09:00:00"
                row.set("db_time", f"{stamp}\n{stamp}")
                row.set("save_settlement_date", f"{index:02}.04.2030")
                row.set("save_depo_settlement_date", f"{index:02}.04.2030")
                if index == 3:
                    row.set("trade_no", "B90001")
                    row.set("repo_no", "B90002")
                    row.set("comment", "репо ч.1")
                    if changed:
                        row.set("summ_trade", "110")
                        if conflict == "early_delivery":
                            row.set("save_depo_settlement_date", "01.04.2030")
                        if conflict == "missing_delivery":
                            row.attrib.pop("save_depo_settlement_date", None)
                        if conflict == "different_qty":
                            row.set("qty", "2")
                if index == 1 and changed and conflict == "ordinary":
                    row.set("summ_trade", "101")

        return mutate

    args = dict(
        stock=("0", "1", "0", "100"),
        bond=None,
        trades=(
            (ISIN, "1", "100", "0", "0"),
            (ISIN, "-1", "180", "0", "0"),
            (ISIN, "1", "100", "0", "0"),
        ),
    )
    save(db, **args, mutate=make(False), marker="first")
    save(db, **args, mutate=make(True), marker="second")
    with db.session_factory() as session:
        result = read_clean_account(
            session,
            ACCOUNT,
            date(2030, 3, 31),
            date(2030, 4, 30),
            isin=ISIN,
            include_purchases=True,
        )
    rows = result["instruments"][0]["purchases"]
    if conflict == "late":
        observed = by_isin(read(db))[ISIN].analysis
        assert rows and rows[0]["price_result_kopecks"] == "8000", (
            observed.coverage,
            [
                (e.event_key, e.native_identity, e.reason_codes, e.source_references)
                for e in observed.events
            ],
        )
    else:
        assert rows is None or all(row["price_result_kopecks"] is None for row in rows)
    from hermes_finance.services.reporting_months import create_reporting_month

    with db.session_factory() as session:
        create_reporting_month(session, year=2030, month=4, snapshot_date=date(2030, 4, 30))
    before = snapshot(db)
    with TestClient(create_app(db)) as client:
        card = client.get("/api/returns/instrument-card", params={"isin": ISIN})
        ai = client.get("/api/export/ai-financial-review/json", params={"format_version": "3.1.0"})
    assert card.status_code == ai.status_code == 200
    account = card.json()["accounts"][0]
    exported = ai.json()["sections"]["clean_returns"]["data"]["accounts"][0]
    assert account["ai_account_ref"] == exported["account_ref"]
    assert account["period"] == exported["period"]
    exported_rows = exported["instruments"][0]["purchases"]
    card_rows = account["purchases"]
    if card_rows is None:
        assert exported_rows is None
    else:
        assert [{k: v for k, v in row.items() if k != "id"} for row in card_rows] == [
            {k: v for k, v in row.items() if k != "id"} for row in exported_rows
        ]
        assert (card_rows[0]["price_result_kopecks"] == "8000") == (conflict == "late")
    assert snapshot(db) == before


def test_fifo_repo_custody_cannot_ignore_unavailable_intermediate_inventory(db):
    from hermes_finance.services.clean_instrument_return import read_clean_account

    def sequential(root):
        rows = root.findall(".//m:Details[@trade_no]", NS)
        for index, row in enumerate(rows, 1):
            stamp = f"{index:02}.04.2030 9:00:00"
            row.set("db_time", f"{stamp}\n{stamp}")
            row.set("save_settlement_date", f"{index:02}.04.2030")
            row.set("save_depo_settlement_date", f"{index:02}.04.2030")
        for index, partner, leg in ((1, "B90002", "репо ч.1"), (3, "B90001", "репо ч.2")):
            rows[index].set("trade_no", "B90001" if index == 1 else "B90002")
            rows[index].set("repo_no", partner)
            rows[index].set("comment", leg)

    save(
        db,
        stock=("0", "0", "0", "0"),
        bond=None,
        trades=(
            (ISIN, "1", "100", "0", "0"),
            (ISIN, "-1", "100", "0", "0"),
            (ISIN, "-1", "180", "0", "0"),
            (ISIN, "1", "101", "0", "0"),
        ),
        mutate=sequential,
    )
    with db.session_factory() as session:
        result = read_clean_account(
            session,
            ACCOUNT,
            date(2030, 3, 31),
            date(2030, 4, 30),
            isin=ISIN,
            include_purchases=True,
        )
    rows = result["instruments"][0]["purchases"]
    assert rows is None or all(row["price_result_kopecks"] is None for row in rows)


@pytest.mark.parametrize("paired", [True, False])
def test_fifo_reader_keeps_ordinary_stock_separate_from_repo_issue(db, paired):
    from hermes_finance.services.clean_instrument_return import project_clean_analysis
    from hermes_finance.services.clean_purchase_returns import clean_purchase_price_contributions

    def repo_bond_only(root):
        ordinary = [
            row
            for row in root.findall(".//m:Details[@trade_no]", NS)
            if row.get("isin_reg") == ISIN
        ]
        for index, row in enumerate(ordinary, 9):
            stamp = f"15.04.2030 {index}:00:00"
            row.set("db_time", f"{stamp}\n{stamp}")
        rows = [
            row
            for row in root.findall(".//m:Details[@trade_no]", NS)
            if row.get("isin_reg") == BOND
        ]
        for index, row in enumerate(rows):
            row.set("trade_no", f"B9000{index + 1}")
            row.set("repo_no", f"B9000{2 if index == 0 else 1}")
            row.set("comment", f"репо ч.{index + 1}")

    bond_trades = [(BOND, "1", "100", "0", "0")]
    if paired:
        bond_trades.append((BOND, "-1", "101", "0", "0"))
    save(
        db,
        stock=("0", "0", "0", "0"),
        bond=("2", "2" if paired else "3", "2000", "2100"),
        trades=((ISIN, "1", "1000", "0", "0"), (ISIN, "-1", "1100", "0", "0"), *bond_trades),
        mutate=repo_bond_only,
    )
    source = by_isin(read(db))
    stock = source[ISIN].analysis
    stock_clean = project_clean_analysis(stock, ISIN, instrument_type="stock")
    rows = clean_purchase_price_contributions(stock, stock_clean, ISIN, instrument_type="stock")
    assert rows[0]["price_result_kopecks"] == "10000"
    repo = source[BOND].analysis
    repo_clean = project_clean_analysis(repo, BOND, instrument_type="bond")
    assert (
        clean_purchase_price_contributions(repo, repo_clean, BOND, instrument_type="bond") is None
    )


@pytest.mark.parametrize(
    "fault", [None, "missing_leg", "partner_conflict", "duplicate_b_id", "cross_isin_b_id"]
)
def test_fifo_proven_repo_overlap_does_not_silently_collapse_faults(db, fault):
    from hermes_finance.services.clean_instrument_return import read_clean_account

    base = [
        (ISIN, "10", "1000", "0", "0"),
        (ISIN, "-5", "600", "0", "0"),
        (ISIN, "5", "500", "0", "0"),
        (ISIN, "-5", "501", "0", "0"),
    ]

    def transform(root, *, changed=False):
        rows = root.findall(".//m:Details[@trade_no]", NS)
        for index, row in enumerate(rows, 9):
            stamp = f"15.04.2030 {index}:00:00"
            row.set("db_time", f"{stamp}\n{stamp}")
            row.set("save_settlement_date", f"{index + 7}.04.2030")
            row.set("save_depo_settlement_date", f"{index + 7}.04.2030")
            if index >= 11:
                row.set("trade_no", f"B9000{index - 10}")
                row.set("repo_no", f"B9000{2 if index == 11 else 1}")
                row.set("comment", f"репо ч.{index - 10}")
        if changed and fault == "partner_conflict":
            rows[-1].set("repo_no", "B99999")
        if changed and fault == "duplicate_b_id":
            rows[-1].set("trade_no", "B90001")
            rows[-1].set("repo_no", "B90002")
        if changed and fault == "cross_isin_b_id":
            rows[-1].set("trade_no", "B90001")
            rows[-1].set("repo_no", "B90002")
            rows[-1].set("comment", "репо ч.1")

    save(db, stock=("0", "5", "0", "550"), bond=None, trades=base, marker="first", mutate=transform)
    second_trades = base[:-1] if fault == "missing_leg" else base
    if fault == "cross_isin_b_id":
        second_trades = [*second_trades, (BOND, "1", "1000", "0", "0")]
    save(
        db,
        stock=("0", "5", "0", "550"),
        bond=("0", "1", "0", "1000") if fault == "cross_isin_b_id" else None,
        trades=second_trades,
        marker="second",
        mutate=lambda root: transform(root, changed=True),
    )
    before = snapshot(db)
    with db.session_factory() as session:
        result = read_clean_account(
            session,
            ACCOUNT,
            date(2030, 3, 31),
            date(2030, 4, 30),
            isin=ISIN,
            include_purchases=True,
        )
    rows = result["instruments"][0]["purchases"]
    if fault is None:
        assert len(rows) == 1 and rows[0]["price_result_kopecks"] == "15000"
    else:
        assert rows is None or all(row["price_result_kopecks"] is None for row in rows)
    assert snapshot(db) == before


@pytest.mark.parametrize(
    "fault", [None, "partner", "leg", "missing", "duplicate", "duplicate_same_issue"]
)
def test_repo_overlap_identity_preserves_references_and_unsupported_economics(db, fault):
    from hermes_finance.services.clean_instrument_return import project_clean_analysis

    money = (
        ("Расчеты по сделке B90001", "репо ч.1", "-1000"),
        ("Комиссия по сделке B90001", "репо ч.1", "-5"),
    )
    save(db, mutate=_repo_source_scope, extra=money, marker="first-repo")

    def second(root):
        _repo_source_scope(root, duplicate=fault in {"duplicate", "duplicate_same_issue"})
        if fault == "duplicate_same_issue":
            for row in root.findall(".//m:Details[@trade_no]", NS):
                row.set("isin_reg", BOND)
        row = root.find(".//m:Details[@trade_no]", NS)
        if fault == "partner":
            row.set("repo_no", "B90003")
        if fault == "leg":
            row.set("comment", "репо ч.2")

    save(
        db,
        mutate=second,
        trades=() if fault == "missing" else ((BOND, "1", "1020", "20", "5"),),
        extra=money,
        marker="second-repo",
    )
    before = snapshot(db)
    result = read(db)
    repo = by_isin(result)[BOND].analysis
    trades = [e for e in repo.events if e.kind in {"BUY", "SELL"}]
    assert all(not e.counted and "repo_trade_unsupported" in e.reason_codes for e in trades)
    assert repo.pnl.value is repo.modified_dietz.value is None
    clean_repo = project_clean_analysis(repo, BOND)
    assert clean_repo.pnl.value is None
    if fault is None:
        stock = by_isin(result)[ISIN].analysis
        assert project_clean_analysis(stock, ISIN, instrument_type="stock").pnl.value == 10000
    if fault in (None, "partner", "leg", "missing"):
        (trade,) = trades
        assert trade.native_identity.startswith("repo:")
        assert trade.native_ids == ("B90001",)
        assert len(trade.source_references) == (1 if fault == "missing" else 2)
        assert "trade_identity_unresolved" not in trade.reason_codes
        assert ("overlapping_trade_conflict" in trade.reason_codes) == (fault in {"partner", "leg"})
        assert ("overlap_trade_occurrence_missing" in trade.reason_codes) == (fault == "missing")
        # The exact B Money references join the single projected event, without
        # granting it cash authority or borrowing the partner as native ID #2.
        assert trade.attribution_basis == (
            "native_trade_settlement" if fault == "missing" else "matched_money"
        )
        assert any("unmatched_trade_money" in e.reason_codes for e in repo.events) == (
            fault == "missing"
        )
        if fault != "missing":
            assert "trade_money_cash_conflict" not in trade.reason_codes
            assert {leg.role for leg in trade.cash_legs} == {"principal", "commission", "nkd"}
    else:
        assert any("trade_identity_unresolved" in e.reason_codes for e in trades)
        assert all(e.attribution_basis != "matched_money" for e in trades)
        assert any("money_ownership_ambiguous" in e.reason_codes for e in repo.events)
    assert by_isin(result)[ISIN].analysis.pnl.value == (
        None if fault in {"missing", "duplicate"} else 10000
    )
    assert snapshot(db) == before


def setup_link(db):
    with db.session_factory() as session:
        instrument = _security_instrument(session, isin=ISIN)
        instrument_id = instrument.id
        session.commit()
        mappings.set_mapping(session, "1-01-99999-Z", ISIN)
    intake = save(db, bond=None, trades=(), extra=(("Перевод", DIVIDEND_SECURITY, "87"),))
    return intake, instrument_id


def test_persisted_link_revalidation_and_no_get_relink(db):
    intake, target = setup_link(db)
    before = snapshot(db)
    result = read(db)
    a = by_isin(result)[ISIN].analysis
    (payout,) = a.events
    assert payout.persisted_link_status == "linked" and payout.effective_isin == ISIN
    assert payout.gross_payout_kopecks == 18700 and payout.withheld_tax_kopecks == 10000
    assert a.pnl.value == 18700  # 100 valuation + 87 net, informational tax not subtracted
    assert a.source_references[0].parser_version != "unknown"
    assert snapshot(db) == before
    dependencies = a.source_references[0].link_dependencies
    with db.session_factory() as session:
        mappings.remove_mapping(session, "1-01-99999-Z")
    before = snapshot(db)
    result = read(db)
    assert by_isin(result)[ISIN].analysis.pnl.value is None
    assert result.unresolved_events[0].effective_isin is None
    assert "payout_link_stale" in result.unresolved_events[0].reason_codes
    assert snapshot(db) == before
    with db.session_factory() as session:
        mappings.set_mapping(session, "1-01-99999-Z", ISIN)
    # Current read interpretation may recover; it never revives an accepted proof/receipt.
    result = read(db)
    assert by_isin(result)[ISIN].analysis.pnl.value == 18700
    assert by_isin(result)[ISIN].analysis.source_references[0].link_dependencies == dependencies
    assert result.financial_authority == "none"


def test_unresolved_saved_link_is_not_promoted_by_new_crosswalk(db):
    save(db, bond=None, trades=(), extra=(("Перевод", DIVIDEND_SECURITY, "87"),))
    with db.session_factory() as session:
        _security_instrument(session, isin=ISIN)
        session.commit()
        mappings.set_mapping(session, "1-01-99999-Z", ISIN)
    result = read(db)
    assert by_isin(result)[ISIN].analysis.pnl.value is None
    assert result.unresolved_events[0].persisted_link_status == "unresolved_no_match"


def test_payout_only_isin_has_missing_positions_and_manual_choice_preserved(db):
    with db.session_factory() as session:
        _security_instrument(session, isin="ZZ0000000011")
        session.commit()
        mappings.set_mapping(session, "1-01-99999-Z", "ZZ0000000011")
    intake = save(db, bond=None, trades=(), extra=(("Перевод", DIVIDEND_SECURITY, "87"),))
    a = by_isin(read(db))["ZZ0000000011"].analysis
    assert a.pnl.value is None and a.components["dividends"].value == 8700
    assert a.opening.quantity is a.closing.quantity is None
    with db.session_factory() as session:
        row = session.scalar(
            select(SourceMoneyClassification).where(SourceMoneyClassification.intake_id == intake)
        )
        choose_classification(session, intake, row.source_reference, "external_deposit")
    before = snapshot(db)
    result = read(db)
    assert "payout_classification_conflict" in by_isin(result)[ISIN].analysis.reason_codes
    assert snapshot(db) == before


def test_overlap_occurrence_multiplicity_missing_conflict_and_unrelated_account(db):
    extra = (("Дивиденды", ISIN, "10"),) * 2
    save(db, bond=None, trades=(), extra=extra)
    save(
        db,
        bond=None,
        trades=(),
        extra=extra,
        marker="second",
        mutate=lambda r: r.find(".//m:Details[@ISIN1]", NS).set("active_name", "Synthetic alias"),
    )
    a = by_isin(read(db))[ISIN].analysis
    assert a.components["dividends"].value == 2000
    assert len(a.events) == 2
    save(
        db,
        bond=None,
        trades=(),
        extra=extra[:1],
        marker="third",
        mutate=lambda r: r.find(".//m:Details[@ISIN1]", NS).set("active_name", "Third alias"),
    )
    a = by_isin(read(db))[ISIN].analysis
    assert a.pnl.value is None and "overlap_money_occurrence_missing" in a.reason_codes


def test_current_receipt_does_not_override_duplicate_unbound_original(db, monkeypatch):
    from hermes_finance.services import source_return_evidence

    extra = (("Дивиденды", "Synthetic unidentified payout", "10"),)
    save(db, bond=None, trades=(), extra=extra)
    before = snapshot(db)
    calls = []

    def accepted(*args, **_kwargs):
        calls.append(1)
        return (ISIN, f"synthetic-{args[1]['id']}", "dividend", 1, frozenset())

    monkeypatch.setattr(source_return_evidence, "effective_payout_match", accepted)
    single = by_isin(read(db))[ISIN].analysis
    assert calls
    assert single.components["dividends"].value == 1000
    assert snapshot(db) == before
    save(db, bond=None, trades=(), extra=extra, marker="overlap")
    before = snapshot(db)
    calls.clear()
    overlap = by_isin(read(db))[ISIN].analysis
    assert calls
    assert overlap.components["dividends"].value is None
    assert "unattributed_income" in overlap.reason_codes
    assert snapshot(db) == before


def test_one_exact_receipt_is_counted_once_across_identical_originals(db, monkeypatch):
    from hermes_finance.services import source_return_evidence

    extra = (("Дивиденды", "Synthetic unidentified payout", "10"),)
    save(db, bond=None, trades=(), extra=extra)
    save(db, bond=None, trades=(), extra=extra, marker="overlap")
    before = snapshot(db)
    accepted_source = []

    def accepted(_session, view, *_args, **_kwargs):
        if not accepted_source:
            accepted_source.append(view["id"])
        return (
            (ISIN, "synthetic", "dividend", 1, frozenset())
            if view["id"] == accepted_source[0]
            else None
        )

    monkeypatch.setattr(source_return_evidence, "effective_payout_match", accepted)
    result = by_isin(read(db))[ISIN].analysis
    assert result.components["dividends"].value == 1000
    assert "overlap_flow_choice_conflict" not in result.reason_codes
    payouts = [event for event in result.events if event.kind == "DIVIDEND" and event.counted]
    assert len(payouts) == 1
    assert payouts[0].classification_status == "confirmed"
    assert "income_assumed" not in payouts[0].assumptions
    assert snapshot(db) == before


def test_same_isin_different_native_accounts_never_share_events(db):
    save(db, bond=None, trades=(), extra=(("Дивиденды", ISIN, "10"),))

    def other(root):
        for row in root.iter():
            for key in ("acc_code", "acc_code2"):
                if key in row.attrib:
                    row.set(key, "7654321-001")

    save(db, bond=None, trades=(), marker="other", extra=(("Дивиденды", ISIN, "20"),), mutate=other)
    assert by_isin(read(db, ACCOUNT))[ISIN].analysis.components["dividends"].value == 1000
    assert by_isin(read(db, "7654321-001"))[ISIN].analysis.components["dividends"].value == 2000
    assert read(db, "1234567").native_source_account is None


@pytest.mark.parametrize(
    "missing", ["save_settlement_date", "save_depo_settlement_date", "bank_tax"]
)
def test_missing_settlement_or_cost_remains_unknown(db, missing):
    def mutate(root):
        trade_date(10)(root)
        root.find(".//m:Details[@trade_no]", NS).attrib.pop(missing, None)

    save(
        db,
        bond=None,
        stock=("0", "10", "0", "1100"),
        trades=((ISIN, "10", "1000", None, "0"),),
        mutate=mutate,
    )
    a = by_isin(read(db))[ISIN].analysis
    assert a.pnl.value is a.modified_dietz.value is None
    assert len(a.events) == 1 and not a.events[0].counted


def test_outer_interval_supported_without_monthly_boundaries_and_selected_endpoint_validation(db):
    save(db, bond=None, trades=(), end_month=5)
    instrument = by_isin(read(db))[ISIN]
    a = instrument.analysis
    assert a.pnl.value == 10000 and a.modified_dietz.value == Decimal("0.1")
    assert a.chained_monthly.value is None
    assert not a.history_complete_since_acquisition
    assert all(row.analysis.pnl.value is None for row in instrument.months)
    with db.session_factory() as session:
        result = read_instrument_returns(
            session,
            source_account=ACCOUNT,
            isin=ISIN,
            opening_date=date(2030, 4, 1),
            closing_date=date(2030, 5, 30),
        )
    assert result.instruments[0].analysis.pnl.value is None


def test_v2_api_minor_units_decimal_fraction_legacy_and_queries(db):
    save(db, bond=None, trades=())
    before = snapshot(db)
    client = TestClient(create_app(database=db))
    query = dict(
        source_account=ACCOUNT, isin=ISIN, opening_date="2030-03-31", closing_date="2030-04-30"
    )
    response = client.get("/api/source-returns/instruments", params=query)
    assert response.status_code == 200, response.text
    row = response.json()["instruments"][0]
    assert row["analysis"]["pnl"]["value"] == 10000
    assert row["analysis"]["modified_dietz"]["value"] == "0.1"
    assert row["months"][0]["return_percent"] == "10"
    assert row["all_time"]["return_percent"] is None
    assert response.headers["cache-control"] == "no-store"
    for changes in ({"closing_date": "2030-03-31"}, {"opening_date": "bad"}, {"isin": "bad"}):
        assert (
            client.get("/api/source-returns/instruments", params=query | changes).status_code == 422
        )
    del query["opening_date"]
    assert client.get("/api/source-returns/instruments", params=query).status_code == 422
    assert snapshot(db) == before


@pytest.mark.parametrize(
    "narrative", ["НКД по сделке 10000000001", "Накопленный купонный доход по сделке 10000000001"]
)
def test_matched_bond_money_principal_nkd_and_fee_each_have_one_owner(db, narrative):
    save(
        db,
        stock=None,
        bond=("0", "1", "0", "1010"),
        trades=((BOND, "1", "1000", "20", "2"),),
        mutate=trade_date(
            15,
            price="98",
            money=(
                ("Расчеты по сделке 10000000001", "Principal", "-980", 15),
                ("Перевод", narrative, "-20", 15),
                ("Комиссия по сделке 10000000001", "Fee", "-2", 15),
                ("Купон", BOND, "30", 30),
            ),
        ),
    )
    a = by_isin(read(db))[BOND].analysis
    assert a.statement_estimate.pnl.value == 3800, a.reason_codes
    buy = next(e for e in a.events if e.kind == "BUY")
    assert {leg.role for leg in buy.cash_legs} == {"principal", "nkd", "commission"}
    assert len({leg.ownership for leg in buy.cash_legs}) == 3


@pytest.mark.parametrize("nkd,fee", [("20", "2"), ("0", "2"), ("20", "0")])
def test_bond_buy_money_principal_keeps_native_nkd_once(db, nkd, fee):
    amount = str(Decimal("1000") + Decimal(nkd))
    save(
        db,
        stock=None,
        bond=("0", "1", "0", "1100"),
        trades=((BOND, "1", amount, nkd, fee),),
        mutate=trade_date(
            15,
            money=(
                ("Расчеты по сделке 10000000001", "Principal", "-1000", 16),
                ("Комиссия по сделке 10000000001", "Fee", str(-Decimal(fee)), 17),
            ),
        ),
    )
    before = snapshot(db)
    result = read(db)
    instrument = by_isin(result)[BOND]
    analysis = instrument.analysis
    (buy,) = analysis.events
    assert buy.counted, buy.reason_codes
    assert buy.native_total_basis == "includes_paid_nkd"
    assert buy.proof_dependency is None
    legs = {leg.role: leg for leg in buy.cash_legs}
    assert len(legs) == len(buy.cash_legs) == 3
    assert legs["principal"].account_cash_kopecks == -100000
    assert legs["nkd"].account_cash_kopecks == -int(Decimal(nkd) * 100)
    assert legs["commission"].account_cash_kopecks == -int(Decimal(fee) * 100)
    assert legs["principal"].date == date(2030, 4, 16)
    assert legs["commission"].date == date(2030, 4, 17)
    assert legs["nkd"].date == buy.cash_settlement_date == date(2030, 4, 15)
    assert legs["nkd"].ownership == buy.event_key + ":nkd"
    assert legs["nkd"].source_references == buy.source_references
    assert all(legs[role].ownership.startswith("money:") for role in ("principal", "commission"))
    cost = int((Decimal(amount) + Decimal(fee)) * 100)
    assert -sum(leg.account_cash_kopecks for leg in buy.cash_legs) == cost
    assert analysis.components["buys"].value == instrument.months[0].buys_cost_kopecks == cost
    assert analysis.statement_estimate.pnl.value == 110000 - cost
    assert analysis.statement_estimate.modified_dietz.capital_days == (
        100000 * 14 + int(Decimal(nkd) * 100) * 15 + int(Decimal(fee) * 100) * 13
    )
    assert analysis.pnl.value is analysis.modified_dietz.value is None
    assert "bond_valuation_basis_unknown" in analysis.reason_codes
    assert result.financial_authority == "none"
    assert snapshot(db) == before


@pytest.mark.parametrize("principal,fee", [("-1020", "-2"), ("-1000", "-3")])
def test_bond_buy_money_component_conflict_stays_uncounted(db, principal, fee):
    save(
        db,
        stock=None,
        bond=("0", "1", "0", "1100"),
        trades=((BOND, "1", "1020", "20", "2"),),
        mutate=trade_date(
            15,
            money=(
                ("Расчеты по сделке 10000000001", "Principal", principal, 15),
                ("Комиссия по сделке 10000000001", "Fee", fee, 15),
            ),
        ),
    )
    before = snapshot(db)
    analysis = by_isin(read(db))[BOND].analysis
    (buy,) = analysis.events
    assert not buy.counted
    assert "trade_money_cash_conflict" in buy.reason_codes
    assert analysis.pnl.value is analysis.modified_dietz.value is None
    assert analysis.statement_estimate.pnl.value is None
    assert snapshot(db) == before


@pytest.mark.parametrize("count", [1, 2])
def test_bond_buy_native_nkd_never_claims_anonymous_money(db, count):
    money = tuple(
        row
        for index in range(1, count + 1)
        for row in (
            (f"Расчеты по сделке 1000000000{index}", "Principal", "-1000", 15),
            (f"Комиссия по сделке 1000000000{index}", "Fee", "-2", 15),
        )
    ) + (("НКД по сделке", BOND, str(-20 * count), 15),)
    save(
        db,
        stock=None,
        bond=("0", str(count), "0", str(1100 * count)),
        trades=((BOND, "1", "1020", "20", "2"),) * count,
        mutate=trade_date(15, money=money),
    )
    before = snapshot(db)
    analysis = by_isin(read(db))[BOND].analysis
    buys = [event for event in analysis.events if event.kind == "BUY"]
    (orphan,) = [event for event in analysis.events if event.kind == "UNRESOLVED"]
    assert len(buys) == count and all(event.counted for event in buys)
    assert analysis.components["buys"].value == 102200 * count
    assert not orphan.counted and orphan.effective_isin is None
    assert "unmatched_trade_money" in orphan.reason_codes
    for buy in buys:
        (nkd,) = [leg for leg in buy.cash_legs if leg.role == "nkd"]
        assert nkd.ownership == buy.event_key + ":nkd"
        assert set(nkd.source_references).isdisjoint(orphan.source_references)
        assert all(leg.ownership != orphan.event_key for leg in buy.cash_legs)
    assert analysis.pnl.value is analysis.modified_dietz.value is None
    assert analysis.statement_estimate.pnl.value is None
    assert snapshot(db) == before


@pytest.mark.parametrize("missing", ["summ_nkd", "bank_tax"])
def test_bond_buy_money_does_not_fill_missing_native_components(db, missing):
    def mutate(root):
        trade_date(
            15,
            money=(
                ("Расчеты по сделке 10000000001", "Principal", "-1000", 15),
                ("Комиссия по сделке 10000000001", "Fee", "-2", 15),
            ),
        )(root)
        root.find(".//m:Details[@trade_no]", NS).attrib.pop(missing)

    save(db, stock=None, trades=((BOND, "1", "1020", "20", "2"),), mutate=mutate)
    before = snapshot(db)
    analysis = by_isin(read(db))[BOND].analysis
    (buy,) = analysis.events
    assert not buy.counted
    assert {leg.role for leg in buy.cash_legs} == {"principal", "commission"}
    assert "trade_components_missing" in buy.reason_codes
    assert analysis.pnl.value is analysis.modified_dietz.value is None
    assert snapshot(db) == before


def test_bond_buy_mixed_legs_replay_overlap_and_current_classification(db):
    money = (
        ("Расчеты по сделке 10000000001", "Principal", "-1000", 15),
        ("Комиссия по сделке 10000000001", "Fee", "-2", 15),
    )
    options = dict(
        stock=None,
        bond=("0", "1", "0", "1100"),
        trades=((BOND, "1", "1020", "20", "2"),),
        mutate=trade_date(15, money=money),
    )
    intake = save(db, **options)
    assert save(db, **options) == intake
    save(db, **options, marker="overlap")

    def checked_read():
        before = snapshot(db)
        result = read(db)
        assert snapshot(db) == before
        return by_isin(result)[BOND].analysis

    analysis = checked_read()
    assert checked_read() == analysis
    (buy,) = analysis.events
    assert buy.counted and len(buy.source_references) == 2
    assert sum(leg.account_cash_kopecks for leg in buy.cash_legs) == -102200
    assert all(len(leg.source_references) == 2 for leg in buy.cash_legs)
    assert len({leg.ownership for leg in buy.cash_legs}) == 3
    with db.session_factory() as session:
        fee = session.scalar(
            select(SourceMoneyClassification).where(
                SourceMoneyClassification.intake_id == intake,
                SourceMoneyClassification.classification == "fee",
            )
        )
        reference = fee.source_reference
        choose_classification(session, intake, reference, "external_withdrawal")
    changed = checked_read()
    assert not changed.events[0].counted
    assert "trade_money_classification_conflict" in changed.events[0].reason_codes
    assert changed.source_references != analysis.source_references
    with db.session_factory() as session:
        choose_classification(session, intake, reference, "fee")
    assert checked_read().events[0].counted
    options["mutate"] = trade_date(15, money=money[1:])
    save(db, **options, marker="missing-principal-observation")
    incomplete = checked_read()
    assert not incomplete.events[0].counted
    assert "overlap_money_occurrence_missing" in incomplete.events[0].reason_codes
    assert incomplete.pnl.value is incomplete.modified_dietz.value is None


def test_conflicting_money_never_added_to_native_trade_total(db):
    save(
        db,
        stock=("0", "10", "0", "1100"),
        bond=None,
        trades=((ISIN, "10", "1000", None, "0"),),
        mutate=trade_date(10, money=(("Расчеты по сделке 10000000001", "Principal", "-999", 10),)),
    )
    a = by_isin(read(db))[ISIN].analysis
    assert a.pnl.value is None and "trade_money_cash_conflict" in a.reason_codes
    assert a.events[0].native_trade_amount_kopecks == 100000


@pytest.mark.parametrize(
    "principal,fee,expected",
    [("-1000", "-3", 100000), ("-999", "-2", None), ("-999", "-3", None)],
)
def test_clean_stock_trade_ignores_fee_mismatch_in_saved_source(db, principal, fee, expected):
    from hermes_finance.services.clean_instrument_return import project_clean_analysis

    save(
        db,
        stock=("0", "10", "0", "1100"),
        bond=None,
        trades=((ISIN, "10", "1000", None, "2"),),
        mutate=trade_date(
            10,
            money=(
                ("Расчеты по сделке 10000000001", "Principal", principal, 10),
                ("Комиссия по сделке 10000000001", "Fee", fee, 10),
            ),
        ),
    )
    analysis = by_isin(read(db))[ISIN].analysis
    (buy,) = analysis.events
    assert not buy.counted and buy.reason_codes == ("trade_money_cash_conflict",)
    clean = project_clean_analysis(analysis, ISIN, instrument_type="stock")
    assert clean.buys.value == expected
    assert clean.known_result.value == (10000 if expected is not None else None)


@pytest.mark.parametrize("principal", ["-2000", "-1000"])
def test_clean_missing_fee_checks_linked_principal_and_posting_date(db, principal):
    from hermes_finance.services.clean_instrument_return import project_clean_analysis

    save(
        db,
        stock=("0", "10", "0", "1100"),
        bond=None,
        trades=((ISIN, "10", "1000", None, None),),
        mutate=trade_date(
            16, money=(("Расчеты по сделке 10000000001", "Principal", principal, 6),)
        ),
    )
    analysis = by_isin(read(db))[ISIN].analysis
    (buy,) = analysis.events
    assert "trade_components_missing" in buy.reason_codes
    assert any(leg.role == "principal" and leg.date.day == 6 for leg in buy.cash_legs)
    clean = project_clean_analysis(analysis, ISIN, instrument_type="stock")
    if principal == "-2000":
        assert clean.buys.value is None
        assert clean.known_result.value is None
        assert clean.modified_dietz.value is None
    else:
        assert clean.buys.value == 100000
        assert clean.pnl.value == 10000
        with localcontext() as context:
            context.prec = 60
            assert clean.modified_dietz.value == Decimal(10000) / (Decimal(100000) * 24 / 30)


@pytest.mark.parametrize(
    "change,reason",
    [
        ("inferred", "source_period_inferred"),
        ("depo", "cross_boundary_settlement"),
        ("pending", "trade_missing_settlement"),
        ("currency", "source_intake_currency_conflict"),
    ],
)
def test_inferred_pending_cross_boundary_and_currency_fail_closed(db, monkeypatch, change, reason):
    intake = save(
        db,
        stock=("0", "10", "0", "1100"),
        bond=None,
        trades=((ISIN, "10", "1000", None, "0"),),
        mutate=trade_date(10),
    )
    original = source_intake.read_intake

    def modified(session, intake_id):
        view = deepcopy(original(session, intake_id))
        assert intake_id == intake
        if change == "inferred":
            view["document"]["warnings"] = ["period_inferred_from_content"]
        elif change == "depo":
            view["document"]["trades"][0]["depo_settlement_date"] = "2030-05-01"
        elif change == "pending":
            view["document"]["trades"][0]["state"] = "pending"
        else:
            view["proposals"][0]["currency_assessment"]["reasons"] = [
                "source_intake_currency_conflict"
            ]
        return view

    monkeypatch.setattr(source_intake, "read_intake", modified)
    a = by_isin(read(db))[ISIN].analysis
    assert a.pnl.value is a.statement_estimate.pnl.value is None
    assert reason in a.reason_codes
    assert len(a.events) == 1


def test_broken_mapping_kind_and_classification_mutation_are_current_read_gaps(db):
    intake, instrument_id = setup_link(db)
    with db.session_factory() as session:
        from hermes_finance.persistence import Instrument

        instrument = session.get(Instrument, instrument_id)
        instrument.instrument_type = "bond"
        session.commit()
    result = read(db)
    assert result.unresolved_events[0].effective_isin is None
    assert "payout_link_stale" in result.unresolved_events[0].reason_codes
    with db.session_factory() as session:
        row = session.scalar(
            select(SourceMoneyClassification).where(SourceMoneyClassification.intake_id == intake)
        )
        row.amount_kopecks += 1
        session.commit()
    result = read(db)
    assert any("invalid_money_row" in e.reason_codes for e in result.unresolved_events)


@pytest.mark.parametrize("balance,residual", [("1085", 0), ("1086", 100)])
def test_account_reconciliation_counts_payout_once_and_excludes_promo(db, balance, residual):
    def mutate(root):
        row = root.find(".//m:Details[@active_type='Валюта']", NS)
        row.set("income_rest", "1000")
        row.set("real_rest", balance)

    save(
        db,
        bond=None,
        trades=(),
        stock=("10", "10", "1000", "1100"),
        mutate=mutate,
        extra=(("Дивиденды", ISIN, "87"), ("Комиссия", "account maintenance", "-2")),
    )
    r = read(db).reconciliation
    assert r.account_growth.value == 18500 + residual
    assert r.instrument_pnl.value == 18700
    assert r.account_only_result.value == -200
    assert r.residual.value == residual
    assert r.complete == (residual == 0)


def test_sold_out_missing_row_not_zero_and_trade_unknown_price_known_total(db, monkeypatch):
    save(
        db,
        stock=("10", "0", "1000", "0"),
        bond=None,
        trades=((ISIN, "-10", "1100", None, "0"),),
        mutate=trade_date(20),
    )
    original = source_intake.read_intake

    def missing_price(session, intake):
        view = deepcopy(original(session, intake))
        view["document"]["trades"][0]["core"]["price"] = None
        return view

    monkeypatch.setattr(source_intake, "read_intake", missing_price)
    a = by_isin(read(db))[ISIN].analysis
    assert a.pnl.value == 10000 and a.events[0].unit_price is None

    def missing_holding(session, intake):
        view = missing_price(session, intake)
        view["document"]["positions"] = []
        return view

    monkeypatch.setattr(source_intake, "read_intake", missing_holding)
    a = by_isin(read(db))[ISIN].analysis
    assert a.pnl.value is None and a.closing.quantity is None


def test_known_other_instrument_unrecognized_money_does_not_block_stock(db):
    save(
        db,
        trades=(),
        bond=("1", "1", "1000", "1000"),
        extra=(("Unsupported operation", BOND, "9"),),
    )
    instruments = by_isin(read(db))
    assert instruments[ISIN].analysis.pnl.value == 10000
    assert instruments[ISIN].months[0].total_kopecks == 10000
    assert instruments[BOND].months[0].total_kopecks is None
    assert instruments[BOND].analysis.statement_estimate.pnl.value is None
    assert "unrecognized_money" in instruments[BOND].analysis.reason_codes


@pytest.mark.parametrize("qty,expected", [("1", 102200), ("-1", 101800)])
@pytest.mark.parametrize("face", [None, "1000", "500", "invalid"])
def test_mybroker_native_total_once_in_monthly_and_dated_read(db, qty, expected, face):
    def mutate(root):
        trade_date(15)(root)
        row = root.find(".//m:Details[@trade_no]", NS)
        row.attrib.pop("nominal")
        if face is not None:
            row.set("nominal", face)

    options = dict(
        stock=None,
        bond=("0", "1", "0", "1020") if qty == "1" else ("1", "0", "1020", "0"),
        trades=((BOND, qty, "1020", "20", "2"),),
        mutate=mutate,
    )
    intake = save(db, **options)
    # Equivalent overlapping observations and exact replay are still one event.
    assert save(db, **options) == intake
    save(db, **options, marker="equivalent-source")
    before = snapshot(db)
    result = read(db)
    row = by_isin(result)[BOND].months[0]
    analysis = by_isin(result)[BOND].analysis
    (event,) = [e for e in analysis.events if e.kind in {"BUY", "SELL"}]
    if face in (None, "1000"):
        assert (row.buys_cost_kopecks if qty == "1" else row.sells_proceeds_kopecks) == expected
        assert sum(leg.account_cash_kopecks for leg in event.cash_legs) == (
            -expected if qty == "1" else expected
        )
        assert event.native_total_basis == "includes_paid_nkd"
        assert ("trade_face_value_missing" in row.flags) == (face is None)
        assert ("trade_face_value_missing" in event.assumptions) == (face is None)
    else:
        assert row.buys_cost_kopecks is row.sells_proceeds_kopecks is None
        assert "trade_nkd_basis_unknown" in event.reason_codes
        assert not event.cash_legs
        if face == "500":
            assert "trade_nkd_basis_conflict" in event.reason_codes
    assert analysis.opening.valuation_basis == "reported_unknown"
    assert analysis.opening.economic_value_kopecks is None
    assert "bond_valuation_basis_unknown" in row.flags
    assert result.financial_authority == "none"
    assert snapshot(db) == before


@pytest.mark.parametrize("missing_face", ["both", "buy", "sell", "none"])
def test_bond_purchase_reports_face_value_assumption_in_card_and_ai(db, missing_face):
    from hermes_finance.services.clean_instrument_return import read_clean_account
    from hermes_finance.services.reporting_months import create_reporting_month

    def mutate(root):
        for index, row in enumerate(root.findall(".//m:Details[@trade_no]", NS), 1):
            stamp = f"{index:02}.04.2030 09:00:00"
            row.set("db_time", f"{stamp}\n{stamp}")
            row.set("save_settlement_date", f"{index:02}.04.2030")
            row.set("save_depo_settlement_date", f"{index:02}.04.2030")
            row.set("Price", "100" if index == 1 else "101")
            if missing_face == "both" or missing_face == ("buy" if index == 1 else "sell"):
                row.attrib.pop("nominal", None)

    save(
        db,
        stock=None,
        bond=("0", "0", "0", "0"),
        trades=((BOND, "1", "1020", "20", "2"), (BOND, "-1", "1030", "20", "2")),
        mutate=mutate,
    )
    native = by_isin(read(db))[BOND].analysis
    assert ("trade_face_value_missing" in native.events[0].assumptions) == (
        missing_face in {"both", "buy"}
    )
    with db.session_factory() as session:
        result = read_clean_account(
            session,
            ACCOUNT,
            date(2030, 3, 31),
            date(2030, 4, 30),
            isin=BOND,
            include_purchases=True,
        )
        create_reporting_month(session, year=2030, month=4, snapshot_date=date(2030, 4, 30))
    item = result["instruments"][0]
    assert item["valuation_and_trades"]["status"] == (
        "supported" if missing_face == "none" else "provisional"
    )
    assert ("trade_face_value_missing" in item["valuation_and_trades"]["assumptions"]) == (
        missing_face != "none"
    )
    rows = item["purchases"]
    assert (
        rows and rows[0]["cost_kopecks"] == "100000" and rows[0]["price_result_kopecks"] == "1000"
    )
    assert rows[0]["status"] == ("supported" if missing_face == "none" else "partial")
    assert ("trade_face_value_missing" in rows[0]["reason_codes"]) == (missing_face != "none")
    before = snapshot(db)
    with TestClient(create_app(db)) as client:
        card = client.get("/api/returns/instrument-card", params={"isin": BOND})
        ai = client.get("/api/export/ai-financial-review/json", params={"format_version": "3.1.0"})
    assert card.status_code == ai.status_code == 200
    account = card.json()["accounts"][0]
    exported = ai.json()["sections"]["clean_returns"]["data"]["accounts"][0]
    assert (
        account["ai_account_ref"] == exported["account_ref"]
        and account["period"] == exported["period"]
    )
    card_row, ai_row = account["purchases"][0], exported["instruments"][0]["purchases"][0]
    assert card_row["status"] == ai_row["status"] == rows[0]["status"]
    assert card_row["reason_codes"] == ai_row["reason_codes"] == rows[0]["reason_codes"]
    assert snapshot(db) == before


@pytest.mark.parametrize("field,value", [("provider", "other"), ("parser", "mybroker-s1-v99")])
def test_mybroker_definition_requires_supported_frozen_source_scope(db, monkeypatch, field, value):
    save(db)
    original = source_intake.read_intake

    def modified(session, intake_id):
        view = deepcopy(original(session, intake_id))
        view["document"][field] = value
        return view

    monkeypatch.setattr(source_intake, "read_intake", modified)
    before = snapshot(db)
    instrument = by_isin(read(db))[BOND]
    assert instrument.months[0].buys_cost_kopecks is None
    assert "trade_nkd_basis_unknown" in instrument.months[0].flags
    (event,) = [e for e in instrument.analysis.events if e.kind == "BUY"]
    assert "trade_nkd_basis_unknown" in event.reason_codes
    assert not event.cash_legs
    assert snapshot(db) == before


@pytest.mark.parametrize("fee", [None, "2"])
def test_same_day_bonds_do_not_acquire_orphan_money_nkd_ownership(db, fee):
    save(
        db,
        stock=None,
        bond=("0", "2", "0", "2040"),
        trades=((BOND, "1", "1020", "20", fee), (BOND, "1", "1020", "20", fee)),
        mutate=trade_date(15, money=(("НКД по сделке", BOND, "-40", 15),)),
    )
    before = snapshot(db)
    result = read(db)
    instrument = by_isin(result)[BOND]
    buys = [e for e in instrument.analysis.events if e.kind == "BUY"]
    assert len(buys) == 2 and len({e.native_identity for e in buys}) == 2
    assert all(e.attribution_basis == "native_trade_settlement" for e in buys)
    assert all(not any(leg.role == "nkd" for leg in e.cash_legs) for e in buys)
    if fee is None:
        assert instrument.months[0].buys_cost_kopecks is None
        assert all("trade_components_missing" in e.reason_codes for e in buys)
    else:
        assert instrument.months[0].buys_cost_kopecks == 204400
    assert instrument.analysis.pnl.value is None  # EOD/ownership guards survive.
    assert snapshot(db) == before


def test_overlapping_ambiguous_payout_components_agree_with_dated_events(db):
    for marker, narrative in (("first", BOND), ("second", BOND + " revised")):
        save(db, trades=(), extra=(("Купон", narrative, "30"),), marker=marker)
    result = by_isin(read(db))[BOND]
    assert result.months[0].coupons_kopecks is None
    assert result.months[0].income_kopecks is None
    assert result.months[0].total_kopecks is None
    assert result.analysis.components["coupons"].value is None
    assert "overlap_money_occurrence_missing" in result.analysis.reason_codes


def test_verified_redemption_quantity_participates_in_dated_reconciliation():
    from unittest.mock import patch

    from hermes_finance.domain.instrument_return import CashLeg, Endpoint, InstrumentEvent
    from hermes_finance.services import source_instrument_events as reader

    start, end, day = date(2030, 4, 1), date(2030, 4, 30), date(2030, 4, 15)
    event = InstrumentEvent(
        event_key="synthetic-redemption",
        provider="synthetic",
        native_source_account="synthetic",
        isin=BOND,
        kind="REDEMPTION",
        event_date=day,
        depository_settlement_date=day,
        quantity_delta=Decimal("-2"),
        source_references=("synthetic",),
        cash_legs=(CashLeg("redemption", day, 200000, -200000, ("synthetic",), "synthetic"),),
    )

    def endpoint(_views, _isin, at, _kind, **_kwargs):
        return Endpoint(
            at,
            Decimal("2") if at == start else Decimal("0"),
            200000 if at == start else 0,
            200000 if at == start else 0,
            0,
            "dirty",
        )

    views = [{"covered_from": "2030-04-01", "covered_to": "2030-04-30", "document": {}}]
    with patch.object(reader, "endpoint", endpoint):
        result = reader.analyse(views, BOND, "bond", start, end, (event,), (), ())
    assert result.coverage["quantity"].complete
    assert result.components["redemption"].value == 200000
    assert result.pnl.value == 0


@pytest.mark.parametrize("conflicting", [False, True])
def test_current_receipt_and_matching_persisted_link_share_one_payout(db, monkeypatch, conflicting):
    from hermes_finance.services import source_return_evidence as evidence
    from hermes_finance.services.source_instrument_events import read_events
    from hermes_finance.services.source_instrument_returns import _identities
    from hermes_finance.services.source_monthly_returns import _selected_sources

    first, _ = setup_link(db)
    save(db, bond=None, trades=(), extra=(("Перевод", DIVIDEND_SECURITY, "87"),), marker="second")
    with db.session_factory() as session:
        selected, native = _selected_sources(session, ACCOUNT)
        views = [deepcopy(view) for _, view, _ in selected]
        row = views[0]["money_classifications"][0]
        row.update(instrument_link_status="unresolved_no_match", instrument_id=None)
        if conflicting:
            views[1]["money_classifications"][0]["instrument_id"] = 999999
        monkeypatch.setattr(
            evidence,
            "effective_payout_match",
            lambda _s, v, *a, **k: (
                (ISIN, "synthetic-receipt", "dividend", 1, frozenset())
                if v["id"] == first
                else None
            ),
        )
        monkeypatch.setattr(evidence, "bound_import", lambda *a: None)
        events, _ = read_events(session, views, _identities(views), next(iter(native)), [])
    counted = [e for e in events if e.kind == "DIVIDEND" and e.counted]
    assert len(counted) == (0 if conflicting else 1)
    if counted:
        assert counted[0].net_payout_kopecks == 8700
        assert not counted[0].reason_codes


def test_month_component_counts_redemption_principal_and_quantity_once(db):
    from hermes_finance.domain.instrument_return import CashLeg, InstrumentEvent
    from hermes_finance.services.source_instrument_returns import _month
    from hermes_finance.services.source_monthly_returns import _selected_sources

    save(db, stock=None, bond=("2", "0", "2000", "0"), trades=())
    day = date(2030, 4, 15)
    event = InstrumentEvent(
        event_key="synthetic-redemption",
        provider="synthetic",
        native_source_account=ACCOUNT,
        isin=BOND,
        kind="REDEMPTION",
        source_references=("synthetic",),
        event_date=day,
        quantity_delta=Decimal("-2"),
        depository_settlement_date=day,
        cash_legs=(CashLeg("redemption", day, 200000, -200000, ("synthetic",), "synthetic"),),
    )
    with db.session_factory() as session:
        selected, _ = _selected_sources(session, ACCOUNT)
        result = _month(
            session,
            [v for _, v, _ in selected],
            BOND,
            "bond",
            date(2030, 4, 1),
            (),
            (),
            None,
            events=(event,),
        )
    assert result.price_effect_kopecks == result.total_kopecks == 0
    assert result.coupons_kopecks == 0
    assert result.sells_proceeds_kopecks == 0
    assert "seam_mismatch" not in result.flags


def test_unallocated_cost_preserves_known_monthly_payout_components(db):
    save(
        db,
        bond=None,
        trades=(),
        extra=(("Дивиденды", ISIN, "87"), ("Комиссия", "unallocated cost", "-2")),
    )
    before = snapshot(db)
    instrument = by_isin(read(db))[ISIN]
    row = instrument.months[0]
    assert row.dividends_kopecks == row.income_kopecks == 8700
    assert row.price_effect_kopecks == 10000
    assert row.total_kopecks is row.return_percent is None
    assert instrument.analysis.pnl.value is None
    assert snapshot(db) == before


@pytest.mark.parametrize(
    "fault",
    [
        "none",
        "stale",
        "identity_issue",
        "account_period",
        "other_scope_conflict",
        "bad_ref",
        "amount",
        "date",
        "account",
        "unconfirmed",
        "cost_gap",
        "valuation_gap",
    ],
)
def test_historical_payout_index_checks_current_exact_original(db, monkeypatch, fault):
    from types import SimpleNamespace

    from hermes_finance.domain.instrument_return import CashLeg, InstrumentEvent
    from hermes_finance.services import source_investment_proofs as proofs
    from hermes_finance.services import source_return_evidence as evidence
    from hermes_finance.services.source_money_classifications import source_reference
    from hermes_finance.services.source_monthly_returns import _selected_sources

    save(db, bond=None, trades=(), extra=(("Перевод", DIVIDEND_SECURITY, "87"),))
    with db.session_factory() as session:
        selected, native = _selected_sources(session, ACCOUNT)
        view = selected[0][1]
        raw = view["document"]["money"][0]
        ref = view["document_sha256"] + ":money:" + str(raw["ordinal"])
        day = date.fromisoformat(raw["date"])
        amount = 8700
        event = InstrumentEvent(
            event_key=ref,
            provider="alfa_mybroker",
            native_source_account=next(iter(native)),
            isin=ISIN,
            effective_isin=ISIN,
            kind="DIVIDEND",
            source_references=(ref,),
            event_date=day,
            net_payout_kopecks=amount,
            classification="dividend",
            classification_status="confirmed",
            cash_legs=(CashLeg("dividend", day, amount, -amount, (ref,), ref),),
        )
        changes = {
            "bad_ref": {"source_references": ("other:money:1",)},
            "amount": {"net_payout_kopecks": 8701},
            "date": {"event_date": date(2030, 4, 1)},
            "account": {"native_source_account": "7654321-000"},
            "unconfirmed": {"classification_status": "assumed"},
        }
        event = replace(event, **changes.get(fault, {}))
        reasons = {
            "identity_issue": ("pdf_xml_payout_mismatch",),
            "account_period": ("pdf_account_period_invalid",),
            "cost_gap": ("unresolved_account_cash_attribution",),
            "valuation_gap": ("economic_endpoint_unavailable",),
        }.get(fault, ())

        def reports(session, *, analyses, **kwargs):
            analyses[1] = {ISIN: SimpleNamespace(events=(event,), reason_codes=reasons)}
            result = [{"proof_id": 1, "status": "stale" if fault == "stale" else "current"}]
            if fault == "other_scope_conflict":
                other = replace(event, isin="RU000A000001", effective_isin="RU000A000001")
                analyses[2] = {other.isin: SimpleNamespace(events=(other,), reason_codes=())}
                result.append({"proof_id": 2, "status": "current"})
            return result

        monkeypatch.setattr(proofs, "read_reports", reports)
        monkeypatch.setattr(
            proofs,
            "_report_rows",
            lambda *_: [
                (SimpleNamespace(id=i), {"source_sha256": view["document_sha256"]})
                for i in ([1, 2] if fault == "other_scope_conflict" else [1])
            ],
        )
        result = evidence.historical_payout_evidence(session, ACCOUNT, selected, native)
        key = source_reference(view["id"], raw)
        if fault in {"none", "cost_gap", "valuation_gap"}:
            assert result[key][0] == ISIN
        elif fault in {"identity_issue", "account_period", "other_scope_conflict"}:
            assert result[key] is None
        else:
            assert not result


@pytest.mark.parametrize(
    "case",
    [
        "single",
        "overlap",
        "missing",
        "duplicate",
        "changed_narrative",
        "changed_timestamp",
        "conflicting_proofs",
        "money_conflict",
        "money_same_isin_distinct_targets",
        "money_extra_cohort",
        "changed_choice",
    ],
)
def test_historical_payout_projection_preserves_overlap_and_conflict_guards(db, monkeypatch, case):
    from hermes_finance.services import source_return_evidence as evidence
    from hermes_finance.services.source_money_classifications import source_reference
    from hermes_finance.services.source_monthly_returns import _selected_sources

    extra = (("Перевод", DIVIDEND_SECURITY, "87"), ("Комиссия", "unallocated cost", "-2"))
    first = save(db, bond=None, trades=(), extra=extra)
    if case not in {"single", "money_conflict", "changed_choice", "conflicting_proofs"}:
        second_extra = extra
        if case == "missing":
            second_extra = extra[1:]
        if case == "duplicate":
            second_extra = (extra[0], extra[0], extra[1])
        if case == "changed_narrative":
            second_extra = (("Перевод", DIVIDEND_SECURITY + " changed", "87"), extra[1])

        def mutate(root):
            if case == "changed_timestamp":
                for row in root.findall(".//{MyBroker}rn"):
                    for node in row.iter():
                        if "last_update" in node.attrib:
                            node.set("last_update", "2030-04-18T00:00:00")

        save(db, bond=None, trades=(), extra=second_extra, marker="overlap", mutate=mutate)
    with db.session_factory() as session:
        selected, native = _selected_sources(session, ACCOUNT)
        view = next(v for o, v, e in selected if o.id == first)
        raw = next(r for r in view["document"]["money"] if r["amount"] == "87")
        key = source_reference(first, raw)
        values = {key: (ISIN, "dividend", raw["date"], 8700, next(iter(native)))}
    if case == "conflicting_proofs":
        values[key] = None
    monkeypatch.setattr(evidence, "historical_payout_evidence", lambda *_: values)
    if case == "money_conflict":
        monkeypatch.setattr(
            evidence,
            "effective_payout_match",
            lambda *a, **k: ("RU000A000001", "receipt", "dividend", "target", frozenset()),
        )
    if case == "money_same_isin_distinct_targets":
        monkeypatch.setattr(
            evidence,
            "effective_payout_match",
            lambda s, v, *a, **k: (ISIN, "receipt", "dividend", str(v["id"]), frozenset()),
        )
    if case == "money_extra_cohort":
        monkeypatch.setattr(
            evidence,
            "effective_payout_match",
            lambda *a, **k: (
                ISIN,
                "receipt",
                "dividend",
                "target",
                frozenset({(999, "money", 1, "outside")}),
            ),
        )
    if case == "changed_choice":
        from hermes_finance.services.source_money_classifications import choose_classification

        with db.session_factory() as session:
            choose_classification(session, first, key, "fee")
    before = snapshot(db)
    result = read(db)
    instrument = by_isin(result)[ISIN]
    row = instrument.months[0]
    if case in {"single", "overlap"}:
        payouts = [e for e in instrument.analysis.events if e.kind == "DIVIDEND"]
        assert len(payouts) == 1 and payouts[0].counted
        assert payouts[0].attribution_basis == "current_source_proof"
        assert row.dividends_kopecks == row.confirmed_income_kopecks == 8700
        assert row.total_kopecks is None
        assert instrument.analysis.components["dividends"].value == 8700
    else:
        assert row.total_kopecks is None
        assert not any(e.counted for e in instrument.analysis.events if e.kind == "DIVIDEND")
    assert result.financial_authority == "none"
    assert snapshot(db) == before


@pytest.mark.parametrize("face_present", [True, False])
@pytest.mark.parametrize("overlap", [False, True])
def test_clean_bond_price_uses_dated_trade_nominal_without_nkd(db, face_present, overlap):
    from hermes_finance.services.clean_instrument_return import read_clean_account

    def prices(root):
        for index, row in enumerate(root.findall(".//m:Details[@trade_no]", NS), 1):
            stamp = f"{index:02}.04.2030 09:00:00"
            row.set("db_time", stamp)
            row.set("save_settlement_date", f"{index:02}.04.2030")
            row.set("save_depo_settlement_date", f"{index:02}.04.2030")
            row.set("Price", "100" if index == 1 else "101")
            if not face_present:
                row.attrib.pop("nominal", None)

    save(
        db,
        stock=None,
        bond=("0", "0", "0", "0"),
        trades=((BOND, "1", "1020", None, "2"), (BOND, "-1", "1030", None, "2")),
        mutate=prices,
    )
    if overlap:
        save(
            db,
            stock=None,
            bond=("0", "0", "0", "0"),
            trades=((BOND, "1", "1020", None, "3"), (BOND, "-1", "1030", None, "3")),
            mutate=prices,
            marker="overlap",
        )
    before = snapshot(db)
    with db.session_factory() as session:
        result = read_clean_account(
            session,
            ACCOUNT,
            date(2030, 3, 31),
            date(2030, 4, 30),
            isin=BOND,
            include_purchases=True,
        )["instruments"][0]
    if face_present:
        assert result["buys"]["value"] == "100000"
        assert result["sells"]["value"] == "101000"
        assert result["valuation_and_trades"]["value"] == result["pnl"]["value"] == "1000"
        assert result["purchases"][0]["price_result_kopecks"] == "1000"
    else:
        assert result["buys"]["value"] is None
        assert result["valuation_and_trades"]["value"] is None
    assert snapshot(db) == before


@pytest.mark.parametrize(
    "buy_amount,expected", [("900", None), ("900.001", None), ("999.98", None), ("999.99", "1000")]
)
def test_clean_bond_rejects_source_total_below_price_principal(db, buy_amount, expected):
    from hermes_finance.services.clean_instrument_return import read_clean_account

    def prices(root):
        for index, row in enumerate(root.findall(".//m:Details[@trade_no]", NS), 1):
            row.set("db_time", f"{index:02}.04.2030 09:00:00")
            row.set("save_settlement_date", f"{index:02}.04.2030")
            row.set("save_depo_settlement_date", f"{index:02}.04.2030")
            row.set("Price", "100" if index == 1 else "101")

    save(
        db,
        stock=None,
        bond=("0", "0", "0", "0"),
        trades=((BOND, "1", buy_amount, None, "2"), (BOND, "-1", "1030", None, "2")),
        mutate=prices,
    )
    before = snapshot(db)
    with db.session_factory() as session:
        result = read_clean_account(
            session,
            ACCOUNT,
            date(2030, 3, 31),
            date(2030, 4, 30),
            isin=BOND,
            include_purchases=True,
        )["instruments"][0]
    assert result["pnl"]["value"] == expected
    if expected is None:
        assert result["buys"]["value"] is None
        assert result["purchases"] is None or result["purchases"][0]["price_result_kopecks"] is None
    assert snapshot(db) == before


@pytest.mark.parametrize(
    "case",
    [
        "nkd_leg_conflict",
        "nkd_leg_fee_conflict",
        "negative_nkd",
        "missing_face",
        "buy_reversed_leg",
        "sell_reversed_leg",
        "negative_holding",
    ],
)
def test_clean_bond_retains_only_independently_proved_principal(db, case):
    from hermes_finance.services.clean_instrument_return import read_clean_account

    def prices_and_money(root):
        rows = root.findall(".//m:Details[@trade_no]", NS)
        for index, row in enumerate(rows, 1):
            day = 3 - index if case == "negative_holding" else index
            row.set("db_time", f"{day:02}.04.2030 09:00:00")
            row.set("save_settlement_date", f"{day:02}.04.2030")
            row.set("save_depo_settlement_date", f"{day:02}.04.2030")
            row.set("Price", "100" if index == 1 else "101")
        if case == "missing_face":
            rows[0].attrib.pop("nominal", None)
        if case in {"nkd_leg_conflict", "nkd_leg_fee_conflict", "missing_face"}:
            _add_money(
                root, "Расчеты по сделке 10000000001", "principal", "-1000", day="2030-04-01"
            )
            _add_money(root, "Расчеты по сделке 10000000001", "НКД", "-5", day="2030-04-01")
        if case == "buy_reversed_leg":
            _add_money(
                root, "Расчеты по сделке 10000000001", "principal", "-2000", day="2030-04-01"
            )
            _add_money(root, "Расчеты по сделке 10000000001", "principal", "1000", day="2030-04-01")
        if case == "sell_reversed_leg":
            _add_money(root, "Расчеты по сделке 10000000002", "principal", "2000", day="2030-04-02")
            _add_money(root, "Расчеты по сделке 10000000002", "principal", "-990", day="2030-04-02")

    nkd = "-20" if case in {"negative_nkd", "negative_holding"} else "20"
    fee = "2" if case == "nkd_leg_fee_conflict" else None
    save(
        db,
        stock=None,
        bond=("0", "0", "0", "0"),
        trades=((BOND, "1", "1020", nkd, fee), (BOND, "-1", "1030", nkd, fee)),
        mutate=prices_and_money,
    )
    if case == "nkd_leg_conflict":
        from hermes_finance.services.reporting_months import create_reporting_month

        with db.session_factory() as session:
            create_reporting_month(session, year=2030, month=4, snapshot_date=date(2030, 4, 30))
    before = snapshot(db)
    with db.session_factory() as session:
        result = read_clean_account(
            session,
            ACCOUNT,
            date(2030, 3, 31),
            date(2030, 4, 30),
            isin=BOND,
            include_purchases=True,
        )["instruments"][0]
    if case in {"nkd_leg_conflict", "nkd_leg_fee_conflict", "negative_nkd"}:
        assert result["pnl"]["value"] == "1000"
        assert result["pnl"]["status"] == "partial"
        assert "source_nkd_conflict" in result["pnl"]["assumptions"]
        assert result["purchases"][0]["price_result_kopecks"] == "1000"
        assert result["purchases"][0]["status"] == "partial"
        assert "source_nkd_conflict" in result["purchases"][0]["reason_codes"]
        if case == "nkd_leg_conflict":
            with TestClient(create_app(database=db)) as client:
                card = client.get("/api/returns/instrument-card", params={"isin": BOND})
                ai = client.get(
                    "/api/export/ai-financial-review/json", params={"format_version": "3.1.0"}
                )
            assert card.status_code == ai.status_code == 200
            account = card.json()["accounts"][0]
            export = ai.json()["sections"]["clean_returns"]["data"]["accounts"][0]
            ai_row = next(row for row in export["instruments"] if row["isin"] == BOND)
            assert account["clean"]["pnl"] == ai_row["pnl"]
            assert ai_row["pnl"]["status"] == "partial"
            assert account["purchases"][0]["reason_codes"] == ai_row["purchases"][0]["reason_codes"]
    else:
        assert result["pnl"]["value"] is None
        assert result["purchases"] is None or result["purchases"][0]["price_result_kopecks"] is None
    assert snapshot(db) == before


@pytest.mark.parametrize(
    "difference",
    [
        "fee",
        "fee_missing_first",
        "fee_missing_second",
        "linked_fee",
        "principal",
        "linked_principal",
        "settlement_time",
        "settlement_time_only",
        "settlement_time_absent",
    ],
)
def test_clean_overlap_ignores_only_commission_difference(db, difference):
    from hermes_finance.services.clean_instrument_return import read_clean_account

    first_fee = None if difference == "fee_missing_first" else "2"
    second_fee = (
        None
        if difference == "fee_missing_second"
        else "2"
        if difference == "settlement_time_only"
        else "3"
    )
    money = ()
    if difference in {"linked_fee", "linked_principal"}:
        money = (
            (
                "Расчеты по сделке 10000000001",
                "Principal",
                "-999" if difference == "linked_principal" else "-1000",
                10,
            ),
            ("Комиссия по сделке 10000000001", "Fee", "-4", 10),
        )
    for marker, fee, amount in (
        ("a", first_fee, "1000"),
        ("b", second_fee, "1001" if difference == "principal" else "1000"),
    ):

        def source(root):
            trade_date(10, price="1000", money=money)(root)
            if difference in {"settlement_time", "settlement_time_only", "settlement_time_absent"}:
                trade = root.find(".//m:Details[@trade_no]", NS)
                if difference == "settlement_time_absent" and marker == "b":
                    trade.attrib.pop("settlement_time", None)
                else:
                    hour = "13" if marker == "b" else "10"
                    trade.set("settlement_time", f"10.04.2030 {hour}:00:00")

        save(
            db,
            stock=("0", "1", "0", "1100"),
            bond=None,
            trades=((ISIN, "1", amount, None, fee),),
            marker=marker,
            mutate=source,
        )
    before = snapshot(db)
    with db.session_factory() as session:
        result = read_clean_account(
            session,
            ACCOUNT,
            date(2030, 3, 31),
            date(2030, 4, 30),
            isin=ISIN,
            include_purchases=True,
        )["instruments"][0]
    if difference not in {
        "principal",
        "linked_principal",
        "settlement_time",
        "settlement_time_only",
    }:
        assert result["buys"]["value"] == "100000"
        assert result["pnl"]["value"] == "10000"
        assert result["purchases"][0]["cost_kopecks"] == "100000"
    else:
        assert result["pnl"]["value"] is None
    assert snapshot(db) == before


@pytest.mark.parametrize("pending_repo", [False, True])
def test_clean_fee_overlap_does_not_ignore_pending_conflict(db, pending_repo):
    from xml.etree import ElementTree as ET

    from hermes_finance.services.clean_instrument_return import read_clean_account

    def prices_and_repo(include_pending):
        def mutate(root):
            rows = root.findall(".//m:Details[@trade_no]", NS)
            for index, row in enumerate(rows, 1):
                row.set("db_time", f"{index:02}.04.2030 09:00:00")
                row.set("save_settlement_date", f"{index:02}.04.2030")
                row.set("save_depo_settlement_date", f"{index:02}.04.2030")
                row.set("Price", "1000" if index == 1 else "1100")
            if not include_pending:
                return
            report = root.find("m:Trades/m:Report", NS)
            table = ET.SubElement(report, "{MyBroker}Tablix3")
            collection = ET.SubElement(table, "{MyBroker}Details2_Collection")
            pending = deepcopy(rows[0])
            for old, new in (
                ("trade_no", "trade_no1"),
                ("db_time", "db_time2"),
                ("qty", "qty2"),
                ("Price", "Price2"),
                ("summ_trade", "summ_trade2"),
                ("curr_calc", "curr_calc2"),
                ("acc_code", "acc_code2"),
                ("isin_reg", "isin_reg1"),
                ("save_settlement_date", "save_settlement_date3"),
                ("save_depo_settlement_date", "save_depo_settlement_date3"),
                ("settlement_time", "settlement_time2"),
                ("bank_tax", "bank_tax2"),
                ("summ_nkd", "summ_nkd2"),
            ):
                if old in pending.attrib:
                    pending.set(new, pending.attrib.pop(old))
            if pending_repo:
                pending.set("repo_no1", "B90002")
            pending.tag = "{MyBroker}Details2"
            collection.append(pending)

        return mutate

    for marker, fee, repo in (("a", "2", True), ("b", "3", False)):
        save(
            db,
            stock=("0", "0", "0", "0"),
            bond=None,
            trades=((ISIN, "1", "1000", None, fee), (ISIN, "-1", "1100", None, fee)),
            marker=marker,
            mutate=prices_and_repo(repo),
        )
    before = snapshot(db)
    with db.session_factory() as session:
        result = read_clean_account(
            session,
            ACCOUNT,
            date(2030, 3, 31),
            date(2030, 4, 30),
            isin=ISIN,
            include_purchases=True,
        )["instruments"][0]
    assert result["pnl"]["value"] is None
    assert snapshot(db) == before


@pytest.mark.parametrize(
    "first_state,first_end,first_time,second_state,second_end,second_time,conflict",
    [
        ("pending", "2030-04-15", None, "settled", "2030-04-30", None, False),
        ("pending", "2030-04-30", None, "settled", "2030-04-30", None, True),
        ("pending", "2030-05-01", None, "settled", "2030-04-30", None, True),
        ("settled", "2030-04-30", "10", "settled", "2030-04-30", "13", True),
        ("settled", "2030-04-30", None, "settled", "2030-04-30", "13", False),
        ("pending", "2030-04-15", "10", "settled", "2030-04-30", "13", False),
    ],
)
def test_trade_overlap_respects_lifecycle_and_present_settlement_times(
    first_state, first_end, first_time, second_state, second_end, second_time, conflict
):
    from hermes_finance.services.source_trade_identity import trade_observation_conflict

    observations = [
        ({"covered_to": first_end}, {"state": first_state, "settlement_time": first_time}),
        ({"covered_to": second_end}, {"state": second_state, "settlement_time": second_time}),
    ]
    assert trade_observation_conflict(observations) is conflict


@pytest.mark.parametrize(
    "overlap",
    [
        "single",
        "same",
        "duplicates",
        "missing",
        "fewer_duplicates",
        "changed_timestamp",
        "unmapped",
        "ambiguous",
        "revoked",
    ],
)
def test_clean_old_coupon_uses_unique_current_mapping_without_writes(db, overlap):
    from test_source_money_classifications_service import COUPON_SECURITY, _security_mapping

    from hermes_finance.persistence import Instrument
    from hermes_finance.services.clean_instrument_return import read_clean_account

    one = (("Перевод", COUPON_SECURITY, "30"),)
    first = one * (2 if overlap in {"duplicates", "fewer_duplicates"} else 1)
    save(db, trades=(), extra=first, marker="a")
    if overlap not in {"single", "unmapped", "ambiguous", "revoked"}:
        second = () if overlap == "missing" else one if overlap == "fewer_duplicates" else first

        def change_timestamp(root):
            if overlap == "changed_timestamp":
                for node in root.findall(".//m:rn", NS):
                    node.set("last_update", "2030-04-18T00:00:00")

        save(db, trades=(), extra=second, marker="b", mutate=change_timestamp)
    with db.session_factory() as session:
        target = Instrument(name="Synthetic bond", instrument_type="bond", isin=BOND)
        session.add(target)
        session.commit()
        if overlap != "unmapped":
            mappings.set_mapping(session, "4B02-09-99999-Z-001P", BOND)
        if overlap == "ambiguous":
            other = Instrument(
                name="Other synthetic bond", instrument_type="bond", isin="RU000A000002"
            )
            session.add(other)
            session.flush()
            _security_mapping(session, other, alias="4B02-09-99999-Z-001P", isin=other.isin)
            session.commit()
        if overlap == "revoked":
            _security_mapping(
                session, target, alias="4B02-09-99999-Z-001P", isin=target.isin, status="revoked"
            )
            session.commit()
        statuses = [
            row.instrument_link_status
            for row in session.scalars(select(SourceMoneyClassification))
            if row.classification == "coupon"
        ]
    assert statuses and set(statuses) == {"unresolved_no_match"}
    before = snapshot(db)
    with db.session_factory() as session:
        row = read_clean_account(
            session,
            ACCOUNT,
            date(2030, 3, 31),
            date(2030, 4, 30),
            isin=BOND,
        )["instruments"][0]
    if overlap in {
        "missing",
        "fewer_duplicates",
        "changed_timestamp",
        "unmapped",
        "ambiguous",
        "revoked",
    }:
        assert row["coupons"]["value"] is None
    else:
        assert row["coupons"]["value"] == ("6000" if overlap == "duplicates" else "3000")
    assert snapshot(db) == before


@pytest.mark.parametrize("cost_difference", ["commission", "nkd"])
def test_clean_combined_sources_reach_overview_card_income_and_ai(db, cost_difference):
    from test_source_money_classifications_service import COUPON_SECURITY

    from hermes_finance.persistence import Instrument
    from hermes_finance.services.reporting_months import create_reporting_month

    def prices(root):
        for index, row in enumerate(root.findall(".//m:Details[@trade_no]", NS), 1):
            stamp = f"{index:02}.04.2030 09:00:00"
            row.set("db_time", stamp)
            row.set("save_settlement_date", f"{index:02}.04.2030")
            row.set("save_depo_settlement_date", f"{index:02}.04.2030")
            row.set("Price", "100" if index == 1 else "101")

    for marker, fee in (("a", "2"), ("b", "3")):
        save(
            db,
            stock=None,
            bond=("0", "0", "0", "0"),
            trades=(
                (
                    BOND,
                    "1",
                    "1025" if marker == "b" and cost_difference == "nkd" else "1020",
                    "25" if marker == "b" else "20",
                    fee,
                ),
                (
                    BOND,
                    "-1",
                    "1035" if marker == "b" and cost_difference == "nkd" else "1030",
                    "25" if marker == "b" else "20",
                    fee,
                ),
            )
            if cost_difference == "nkd"
            else ((BOND, "1", "1020", None, fee), (BOND, "-1", "1030", None, fee)),
            extra=(("Перевод", COUPON_SECURITY, "30"),),
            mutate=prices,
            marker=marker,
        )
    with db.session_factory() as session:
        session.add(Instrument(name="Synthetic bond", instrument_type="bond", isin=BOND))
        session.commit()
        mappings.set_mapping(session, "4B02-09-99999-Z-001P", BOND)
        create_reporting_month(session, year=2030, month=4, snapshot_date=date(2030, 4, 30))
    before = snapshot(db)
    with TestClient(create_app(database=db)) as client:
        overview = client.get("/api/returns/overall?include_instrument_summaries=true")
        card = client.get("/api/returns/instrument-card", params={"isin": BOND})
        income = client.get("/api/returns/income", params={"kind": "coupon"})
        ai = client.get("/api/export/ai-financial-review/json", params={"format_version": "3.1.0"})
    assert overview.status_code == card.status_code == income.status_code == ai.status_code == 200
    summary = next(row for row in overview.json()["instruments"] if row["isin"] == BOND)
    account = card.json()["accounts"][0]
    exported = ai.json()["sections"]["clean_returns"]["data"]["accounts"][0]
    ai_row = next(row for row in exported["instruments"] if row["isin"] == BOND)
    assert account["period"] == exported["period"] == summary["accounts"][0]["period"]
    assert account["clean"]["pnl"]["value"] == ai_row["pnl"]["value"] == "4000"
    assert summary["accounts"][0]["pnl"]["value"] == "4000"
    assert account["clean"]["coupons"]["value"] == ai_row["coupons"]["value"] == "3000"
    assert [row["amount"]["value"] for row in income.json()["events"] if row["isin"] == BOND] == [
        "3000"
    ]
    assert (
        account["purchases"][0]["price_result_kopecks"]
        == ai_row["purchases"][0]["price_result_kopecks"]
        == "1000"
    )
    assert snapshot(db) == before


def test_analytical_coupon_mapping_keeps_native_accounts_separate(db):
    from test_source_money_classifications_service import COUPON_SECURITY

    from hermes_finance.persistence import Instrument
    from hermes_finance.services.clean_instrument_return import read_clean_account

    def other_account(root):
        for row in root.iter():
            for key in ("acc_code", "acc_code2"):
                if key in row.attrib:
                    row.set(key, "7654321-001")

    save(db, trades=(), extra=(("Перевод", COUPON_SECURITY, "30"),), marker="a")
    save(
        db,
        trades=(),
        extra=(("Перевод", COUPON_SECURITY, "70"),),
        marker="b",
        mutate=other_account,
    )
    with db.session_factory() as session:
        session.add(Instrument(name="Synthetic bond", instrument_type="bond", isin=BOND))
        session.commit()
        mappings.set_mapping(session, "4B02-09-99999-Z-001P", BOND)
    before = snapshot(db)
    with db.session_factory() as session:
        results = [
            read_clean_account(session, account, date(2030, 3, 31), date(2030, 4, 30), isin=BOND)[
                "instruments"
            ][0]["coupons"]["value"]
            for account in (ACCOUNT, "7654321-001")
        ]
    assert results == ["3000", "7000"]
    assert snapshot(db) == before


def test_analytical_coupon_never_overrides_conflicting_historical_evidence(db, monkeypatch):
    from test_source_money_classifications_service import COUPON_SECURITY

    from hermes_finance.persistence import Instrument
    from hermes_finance.services import source_return_evidence
    from hermes_finance.services.clean_instrument_return import read_clean_account
    from hermes_finance.services.source_money_classifications import source_reference
    from hermes_finance.services.source_monthly_returns import _selected_sources

    coupons = (("Перевод", COUPON_SECURITY, "30"),) * 2
    for marker in ("a", "b"):
        save(db, trades=(), extra=coupons, marker=marker)
    with db.session_factory() as session:
        session.add(Instrument(name="Synthetic bond", instrument_type="bond", isin=BOND))
        session.commit()
        mappings.set_mapping(session, "4B02-09-99999-Z-001P", BOND)
        selected, _ = _selected_sources(session, ACCOUNT)
        view = selected[0][1]
        ref = source_reference(view["id"], view["document"]["money"][0])
    # None is the existing current-proof conflict tombstone, not missing proof.
    monkeypatch.setattr(
        source_return_evidence, "historical_payout_evidence", lambda *_: {ref: None}
    )
    before = snapshot(db)
    with db.session_factory() as session:
        result = read_clean_account(
            session, ACCOUNT, date(2030, 3, 31), date(2030, 4, 30), isin=BOND
        )["instruments"][0]
    assert result["coupons"]["value"] is None
    assert snapshot(db) == before


def test_analytical_coupon_does_not_override_existing_money_ownership(db, monkeypatch):
    from types import SimpleNamespace

    from test_source_money_classifications_service import COUPON_SECURITY

    from hermes_finance.persistence import Instrument
    from hermes_finance.services import broker_money_ownership, source_return_evidence
    from hermes_finance.services.source_monthly_returns import _selected_sources

    save(db, trades=(), extra=(("Перевод", COUPON_SECURITY, "30"),))
    with db.session_factory() as session:
        session.add(Instrument(name="Synthetic bond", instrument_type="bond", isin=BOND))
        session.commit()
        mappings.set_mapping(session, "4B02-09-99999-Z-001P", BOND)
        selected, native_scope = _selected_sources(session, ACCOUNT)
        monkeypatch.setattr(
            source_return_evidence, "bound_import", lambda *_: SimpleNamespace(id=1)
        )
        monkeypatch.setattr(source_return_evidence, "_source_allows_payout", lambda *_: True)
        monkeypatch.setattr(source_return_evidence, "effective_payout_match", lambda *a, **k: None)
        monkeypatch.setattr(broker_money_ownership, "owners", lambda *_: [])
        assert list(
            source_return_evidence.analytical_coupon_links(session, selected, native_scope).values()
        ) == [BOND]
        monkeypatch.setattr(broker_money_ownership, "owners", lambda *_: [{"role": "fee"}])
        assert not source_return_evidence.analytical_coupon_links(session, selected, native_scope)


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize(
    "difference", ["nkd", "dirty_total", "missing_nkd", "price", "face", "small_total", "principal"]
)
def test_clean_bond_overlap_uses_same_proved_principal_despite_costs(db, difference, reverse):
    from hermes_finance.services.clean_instrument_return import read_clean_account

    sources = ["a", "b"]
    if reverse:
        sources.reverse()
    for marker in sources:

        def mutate(root):
            for index, row in enumerate(root.findall(".//m:Details[@trade_no]", NS), 1):
                row.set("db_time", f"{index:02}.04.2030 09:00:00")
                row.set("save_settlement_date", f"{index:02}.04.2030")
                row.set("save_depo_settlement_date", f"{index:02}.04.2030")
                row.set("Price", "100" if index == 1 else "101")
                if marker == "b" and index == 1 and difference == "price":
                    row.set("Price", "100.1")
                if marker == "b" and index == 1 and difference == "face":
                    row.set("nominal", "2000")
            if difference == "principal":
                _add_money(
                    root, "Расчеты по сделке 10000000001", "principal", "-999", day="2030-04-01"
                )

        nkd = (
            None
            if marker == "b" and difference == "missing_nkd"
            else "25"
            if marker == "b"
            else "20"
        )
        amount = (
            "999"
            if marker == "b" and difference == "small_total"
            else "1025"
            if marker == "b" and difference == "dirty_total"
            else "1020"
        )
        sale = "1035" if marker == "b" and difference == "dirty_total" else "1030"
        save(
            db,
            stock=None,
            bond=("0", "0", "0", "0"),
            trades=((BOND, "1", amount, nkd, "2"), (BOND, "-1", sale, nkd, "2")),
            marker=marker,
            mutate=mutate,
        )
    before = snapshot(db)
    with db.session_factory() as session:
        for _ in range(2):
            row = read_clean_account(
                session,
                ACCOUNT,
                date(2030, 3, 31),
                date(2030, 4, 30),
                isin=BOND,
                include_purchases=True,
            )["instruments"][0]
            if difference in {"nkd", "dirty_total", "missing_nkd"}:
                assert row["buys"]["value"] == "100000"
                assert row["sells"]["value"] == "101000"
                assert row["pnl"]["value"] == "1000"
                assert row["purchases"][0]["price_result_kopecks"] == "1000"
            else:
                assert row["pnl"]["value"] is None
    assert snapshot(db) == before
