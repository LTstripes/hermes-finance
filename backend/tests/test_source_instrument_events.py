"""Saved synthetic originals -> dated events -> existing API, with no economic writes."""

from copy import deepcopy
from dataclasses import replace
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

from hermes_finance.main import create_app
from hermes_finance.persistence import SourceMoneyClassification
from hermes_finance.services import security_reg_isin_mappings as mappings
from hermes_finance.services import source_intake
from hermes_finance.services.source_bond_valuation import (
    BondEndpointBinding,
    ReviewedBondValuation,
    SourceRevision,
)
from hermes_finance.services.source_instrument_returns import read_instrument_returns
from hermes_finance.services.source_money_classifications import choose_classification
from hermes_finance.statement_import.mybroker import NS


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
    save(
        db,
        5,
        stock=("11", "11", "1100", "1100"),
        bond=("0", "1", "0", "100"),
        trades=((BOND, "1", "100", "0", "0"),),
        extra=(("Дивиденды", ISIN, "100"),),
        mutate=trade_date(15, price="10"),
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
    assert a.components["taxes"].value == 1300
    assert result.account_reconciliation_events[0].cash_legs[0].account_cash_kopecks == -200


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
