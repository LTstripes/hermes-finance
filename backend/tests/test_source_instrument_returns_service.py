"""Fabricated native statements only; source estimates never write financial rows."""

import calendar
import json
from copy import deepcopy
from datetime import UTC, date, datetime
from decimal import Decimal, localcontext
from xml.etree import ElementTree as ET

import pytest
from sqlalchemy import select
from test_source_monthly_returns_service import snapshot
from test_statement_import_broker_statement_provisional import _free_database, provisional_xml
from test_statement_import_mybroker import ACCOUNT, ISIN

from hermes_finance.persistence import Account, ExecutedTrade, Instrument, SourceMoneyClassification
from hermes_finance.services import source_instrument_returns as service
from hermes_finance.services import source_intake
from hermes_finance.services.source_instrument_returns import _attribute, read_instrument_returns
from hermes_finance.services.source_money_classifications import choose_classification
from hermes_finance.statement_import.mybroker import NS, MyBrokerError

BOND = "RU000A000001"
INCOME_FIELDS = (
    "coupons_kopecks",
    "dividends_kopecks",
    "assumed_income_kopecks",
    "confirmed_income_kopecks",
    "income_kopecks",
)


@pytest.fixture
def db(tmp_path):
    database = _free_database(tmp_path)
    yield database
    database.engine.dispose()


@pytest.fixture
def accepted_basis(monkeypatch):
    # Explicit synthetic reviewed proof for tests that exercise other boundaries.
    monkeypatch.setattr(service, "_native_total_basis", lambda session, trade: "excludes_paid_nkd")


def save(
    db,
    month=4,
    *,
    stock=("10", "10", "1000", "1100"),
    bond=("2", "3", "2000", "3150"),
    trades=((BOND, "1", "1000", "20", "5"),),
    extra=(),
    marker=None,
    mutate=None,
    end_month=None,
):
    root = ET.fromstring(provisional_xml(candidate_count=0, extra_money=extra))
    position = root.find(".//m:Details[@ISIN1]", NS)
    collection = root.find(
        "m:Positions/m:Report/m:Tablix1/m:active_type_Collection/"
        "m:active_type/m:Details_Collection",
        NS,
    )
    bond_position = deepcopy(position)
    collection.append(bond_position)
    for row, isin, kind, name, operands in (
        (position, ISIN, "Акции", "Synthetic stock", stock),
        (bond_position, BOND, "Облигации", "Synthetic bond", bond),
    ):
        if operands is None:
            collection.remove(row)
            continue
        q0, q1, v0, v1 = operands
        row.attrib.update(
            ISIN1=isin,
            active_type=kind,
            active_name=name,
            income_rest=q0,
            real_rest=q1,
            forward_rest=q1,
            income_volume=v0,
            real_volume=v1,
        )
    trade_template = root.find(".//m:Details[@trade_no]", NS)
    trade_collection = root.find("m:Trades/m:Report/m:Tablix2/m:Details_Collection", NS)
    for row in list(trade_collection):
        trade_collection.remove(row)
    for index, (isin, qty, amount, nkd, fee) in enumerate(trades):
        row = deepcopy(trade_template)
        row.attrib.update(
            isin_reg=isin,
            qty=qty,
            summ_trade=amount,
            trade_no=f"1000000000{index + 1}\n200000000{index + 1}",
        )
        for key, value in (("summ_nkd", nkd), ("bank_tax", fee)):
            if value is None:
                row.attrib.pop(key, None)
            else:
                row.set(key, value)
        trade_collection.append(row)
    if marker:
        root.set("synthetic_marker", marker)
    if mutate:
        mutate(root)
    xml = (
        ET.tostring(root, encoding="utf-8")
        .decode()
        .replace("2030-04-", f"2030-{month:02d}-")
        .replace(".04.2030", f".{month:02d}.2030")
        .encode()
    )
    end_month = end_month or month
    end = calendar.monthrange(2030, end_month)[1]
    filename = f"Брокерский 1234567 (01.{month:02d}.30-{end}.{end_month:02d}.30).xml"
    with db.session_factory() as session:
        return source_intake.save_intake(
            session, document=xml, filename=filename, request_id=f"save-{month}-{marker}"
        )["intake_id"]


def read(db, source_account=ACCOUNT):
    with db.session_factory() as session:
        return read_instrument_returns(session, source_account=source_account)


def by_isin(result):
    return {row.isin: row for row in result.instruments}


def test_stock_dividend_bond_coupon_nkd_purchase_sale_and_all_time(db, accepted_basis):
    intake = save(
        db,
        extra=(("Дивиденды", f"Payment {ISIN}", "25"), ("Купон", "Payment Synthetic bond", "30")),
    )
    with db.session_factory() as session:
        dividend = session.scalar(
            select(SourceMoneyClassification).where(
                SourceMoneyClassification.intake_id == intake,
                SourceMoneyClassification.classification == "dividend",
            )
        )
        choose_classification(session, intake, dividend.source_reference, "dividend")
    save(
        db,
        5,
        stock=("10", "6", "1100", "690"),
        bond=("3", "3", "3150", "3180"),
        trades=((ISIN, "-4", "460", None, "2"),),
    )
    before = snapshot(db)
    result = read(db)
    stock, bond = by_isin(result)[ISIN], by_isin(result)[BOND]
    a, m = stock.months
    assert (a.opening_quantity, a.closing_quantity) == (Decimal(10), Decimal(10))
    assert (a.opening_value_kopecks, a.closing_value_kopecks) == (100_000, 110_000)
    assert a.buys_cost_kopecks == 0 and a.sells_proceeds_kopecks == 0
    assert a.price_effect_kopecks == 10_000 and a.dividends_kopecks == 2_500
    assert a.total_kopecks == 12_500 and a.return_percent == Decimal("12.5")
    assert a.confirmed_income_kopecks == 2_500 and not a.income_assumptions_used
    assert a.flags == ("income_confirmed",) and not a.approximate
    assert m.sells_proceeds_kopecks == 45_800
    assert m.price_effect_kopecks == 4_800 and m.total_kopecks == 4_800
    assert not m.flags and not m.approximate
    b, second = bond.months
    assert b.buys_cost_kopecks == 102_500  # amount + paid NKD + fee
    assert b.price_effect_kopecks == 12_500 and b.coupons_kopecks == 3_000
    assert b.total_kopecks == 15_500 and b.capital_base_kopecks == 302_500
    assert b.assumed_income_kopecks == 3_000 and b.income_assumptions_used
    assert b.approximate and "bond_valuation_basis_unknown" in b.flags
    assert "seam_mismatch" not in b.flags
    assert second.total_kopecks == 3_000
    assert stock.all_time.total_kopecks == 17_300
    assert stock.all_time.price_effect_kopecks == 14_800
    assert stock.all_time.income_kopecks == 2_500
    assert bond.all_time.total_kopecks == 18_500
    assert not stock.all_time.partial and not bond.all_time.partial
    assert stock.all_time.missing_months == ()
    assert result.financial_authority == "none"
    assert snapshot(db) == before


def test_missing_month_is_null_and_all_time_is_explicit_available_sum(db):
    save(db, trades=(), bond=("2", "2", "2000", "2100"))
    save(db, 6, trades=(), stock=("10", "10", "1200", "1300"), bond=("2", "2", "2200", "2300"))
    result = by_isin(read(db))[ISIN]
    a, missing, j = result.months
    assert missing.month == date(2030, 5, 1)
    for field in (
        "opening_quantity",
        "closing_quantity",
        "opening_value_kopecks",
        "closing_value_kopecks",
        "buys_cost_kopecks",
        "sells_proceeds_kopecks",
        "coupons_kopecks",
        "dividends_kopecks",
        "assumed_income_kopecks",
        "confirmed_income_kopecks",
        "income_kopecks",
        "total_kopecks",
        "return_percent",
    ):
        assert getattr(missing, field) is None
    assert "missing_month" in missing.flags and missing.approximate
    assert j.total_kopecks == a.total_kopecks == 10_000
    assert result.all_time.total_kopecks == 20_000
    assert result.all_time.partial and result.all_time.approximate
    assert result.all_time.missing_months == (date(2030, 5, 1),)
    assert result.all_time.available_months == (date(2030, 4, 1), date(2030, 6, 1))
    assert "missing_month" in result.all_time.flags


def test_unattributed_coupon_is_retained_and_prevents_false_complete_total(db, accepted_basis):
    save(db, extra=(("Купон", "No saved instrument identity", "17"),))
    save(db, 5, trades=(), bond=("3", "3", "3150", "3180"))
    result = read(db)
    assert len(result.income) == 1 and result.income[0].isin is None
    assert result.income[0].amount_kopecks == 1_700
    assert result.income[0].source_references
    assert "unattributed_income" in {gap.code for gap in result.gaps}
    for instrument in result.instruments:
        first, second = instrument.months
        assert first.price_effect_kopecks is not None
        assert first.total_kopecks is None and first.return_percent is None
        assert "unattributed_income" in first.flags and first.approximate
        assert second.total_kopecks is not None
        assert instrument.all_time.partial


@pytest.mark.parametrize("missing", ["save_settlement_date", "bank_tax", "summ_nkd"])
def test_bad_trade_only_blocks_its_instrument_month(db, missing):
    def mutate(root):
        root.find(".//m:Details[@trade_no]", NS).attrib.pop(missing, None)

    save(db, mutate=mutate)
    save(db, 5, trades=(), bond=("3", "3", "3150", "3180"))
    result = by_isin(read(db))
    assert result[ISIN].months[0].total_kopecks == 10_000
    first, second = result[BOND].months
    assert first.total_kopecks is None and first.buys_cost_kopecks is None
    flag = (
        "trade_missing_settlement"
        if missing == "save_settlement_date"
        else "trade_components_missing"
    )
    assert flag in first.flags
    assert second.total_kopecks == 3_000


def test_bond_sale_adds_received_nkd_and_subtracts_fees(db, accepted_basis):
    save(db, bond=("2", "1", "2000", "1050"), trades=((BOND, "-1", "1000", "20", "5"),))
    row = by_isin(read(db))[BOND].months[0]
    assert row.sells_proceeds_kopecks == 101_500
    assert row.price_effect_kopecks == 6_500
    assert row.total_kopecks == 6_500 and row.approximate


def test_seams_use_own_valuations_and_quantity_without_trade_is_flagged(db):
    save(db, trades=(), bond=("2", "2", "2000", "2100"))
    save(db, 5, trades=(), stock=("11", "12", "1200", "1300"), bond=("2", "2", "2100", "2200"))
    result = by_isin(read(db))
    row = result[ISIN].months[1]
    assert row.opening_value_kopecks == 120_000 and row.total_kopecks == 10_000
    assert "seam_mismatch" in row.flags and row.approximate
    assert "seam_mismatch" not in result[BOND].months[1].flags


def test_overlaps_deduplicate_trades_and_preserve_income_multiplicity(db, accepted_basis):
    extra = (("Купон", BOND, "30"), ("Купон", BOND, "30"))
    save(db, extra=extra)
    save(db, extra=extra, marker="overlap")
    result = read(db)
    row = by_isin(result)[BOND].months[0]
    assert row.buys_cost_kopecks == 102_500
    assert row.coupons_kopecks == 6_000 and row.total_kopecks == 18_500
    assert len(result.income) == 2
    assert all(len(item.source_references) == 2 for item in result.income)


def test_overlap_conflicting_valuations_and_trades_are_not_selected(db):
    save(db)
    save(
        db,
        marker="conflict",
        bond=("2", "3", "2000", "3200"),
        trades=((BOND, "1", "1050", "20", "5"),),
    )
    result = by_isin(read(db))
    assert result[ISIN].months[0].total_kopecks == 10_000
    row = result[BOND].months[0]
    assert row.closing_value_kopecks is None and row.total_kopecks is None
    assert {"overlapping_endpoint_conflict", "overlapping_trade_conflict"} <= set(row.flags)


def test_bad_position_does_not_suppress_other_instrument(db):
    def mutate(root):
        root.find(f".//m:Details[@ISIN1='{BOND}']", NS).attrib.pop("real_volume")

    save(db, mutate=mutate)
    result = by_isin(read(db))
    assert result[ISIN].months[0].total_kopecks == 10_000
    assert result[BOND].months[0].closing_value_kopecks is None
    assert result[BOND].months[0].closing_quantity == Decimal(3)
    assert result[BOND].months[0].total_kopecks is None
    assert "missing_endpoint" in result[BOND].months[0].flags


def test_long_report_never_invents_intermediate_values(db):
    save(db, end_month=6, trades=(), bond=("2", "2", "2000", "2100"))
    row = by_isin(read(db))[ISIN]
    assert len(row.months) == 3
    assert row.months[0].opening_value_kopecks == 100_000
    assert row.months[0].closing_value_kopecks is None
    assert row.months[1].opening_value_kopecks is None
    assert row.months[1].closing_value_kopecks is None
    assert row.months[2].closing_value_kopecks == 110_000
    assert row.all_time.total_kopecks is None and row.all_time.partial


def test_unreadable_overlap_blocks_only_its_covered_months(db, monkeypatch):
    failed = save(db)
    save(db, marker="readable-overlap")
    save(db, 5, trades=(), bond=("3", "3", "3150", "3180"))
    reader = source_intake.read_intake

    def broken(session, intake_id):
        if intake_id == failed:
            raise MyBrokerError("synthetic unreadable source")
        return reader(session, intake_id)

    monkeypatch.setattr(source_intake, "read_intake", broken)
    before = snapshot(db)
    for instrument in read(db).instruments:
        assert instrument.months[0].total_kopecks is None
        assert "source_reader_unavailable" in instrument.months[0].flags
        for field in INCOME_FIELDS:
            assert getattr(instrument.months[0], field) is None
        assert instrument.months[1].total_kopecks is not None
    assert snapshot(db) == before


def test_missing_legacy_classifications_never_backfilled(db, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(source_intake, "persist_money_classifications", lambda *args: None)
        save(db, extra=(("Купон", BOND, "30"),))
    before = snapshot(db)
    result = read(db)
    assert not result.income
    assert "classification_missing_legacy_intake" in {gap.code for gap in result.gaps}
    assert all(row.months[0].total_kopecks is None for row in result.instruments)
    assert snapshot(db) == before


def test_attribution_requires_unique_whole_identifier_or_name():
    identities = {
        ISIN: {"identifiers": {ISIN, "1-01-SYNTH"}, "names": {"Synthetic stock"}},
        BOND: {"identifiers": {BOND}, "names": {"Synthetic bond"}},
    }
    assert _attribute("Paid 1-01-SYNTH", identities) == ISIN
    assert _attribute("Payment SYNTHETIC STOCK.", identities) == ISIN
    assert _attribute(f"Coupon {BOND}; Synthetic stock", identities) == BOND
    assert _attribute(f"{ISIN} and {BOND}", identities) is None
    assert _attribute(f"prefix{ISIN}", identities) is None
    assert _attribute("Synthetic stockholder", identities) is None
    identities[BOND]["names"].add("Synthetic stock")
    assert _attribute("Synthetic stock", identities) is None


def test_unknown_account_empty_and_read_precision_independent(db):
    save(db)
    assert read(db, "other-native-account").instruments == ()
    before = read(db)
    with localcontext() as context:
        context.prec = 6
        assert read(db) == before


def test_zero_base_leaves_percentage_null(db):
    save(db, stock=("0", "0", "0", "0"))
    row = by_isin(read(db))[ISIN].months[0]
    assert row.total_kopecks == 0 and row.capital_base_kopecks == 0
    assert row.return_percent is None
    assert "nonpositive_capital_base" in row.flags


def test_get_api_decimal_strings_integer_money_no_store_and_no_writes(db, accepted_basis):
    from fastapi.testclient import TestClient

    from hermes_finance.main import create_app

    save(db, extra=(("Дивиденды", ISIN, "25"), ("Купон", BOND, "30")))
    before = snapshot(db)
    client = TestClient(create_app(database=db))
    response = client.get("/api/source-returns/instruments", params={"source_account": ACCOUNT})
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["authority"] == "provisional" and body["financial_authority"] == "none"
    assert body["currency"] == "RUB" and body["source_account"] == ACCOUNT
    stock = next(row for row in body["instruments"] if row["isin"] == ISIN)
    row = stock["months"][0]
    assert row["month"] == "2030-04-01"
    assert type(row["opening_value_kopecks"]) is int
    assert type(row["total_kopecks"]) is int
    assert row["opening_quantity"] == "10"
    assert row["return_percent"] == "12.5"
    assert stock["all_time"]["return_percent"] is None
    assert stock["all_time"]["capital_base_kopecks"] is None
    bond = next(row for row in body["instruments"] if row["isin"] == BOND)
    assert bond["months"][0]["approximate"]
    assert isinstance(bond["months"][0]["return_percent"], str)
    assert row["approximate"] and stock["all_time"]["approximate"]
    assert snapshot(db) == before
    assert client.get("/api/source-returns/instruments").status_code == 422
    for value in ("", "has whitespace", "x" * 257):
        assert (
            client.get(
                "/api/source-returns/instruments", params={"source_account": value}
            ).status_code
            == 422
        )
    empty = client.get("/api/source-returns/instruments", params={"source_account": "other"})
    assert empty.status_code == 200 and empty.json()["instruments"] == []
    assert snapshot(db) == before


def test_api_missing_month_and_unattributed_income_remain_explicit(db):
    from fastapi.testclient import TestClient

    from hermes_finance.main import create_app

    save(db, extra=(("Купон", "Unknown security", "17"),))
    save(db, 6, trades=(), bond=("3", "3", "3150", "3180"))
    client = TestClient(create_app(database=db))
    response = client.get("/api/source-returns/instruments", params={"source_account": ACCOUNT})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["income"][0]["isin"] is None
    assert body["income"][0]["amount_kopecks"] == 1_700
    assert "unattributed_income" in {gap["code"] for gap in body["gaps"]}
    for instrument in body["instruments"]:
        assert instrument["months"][0]["total_kopecks"] is None
        assert instrument["months"][1]["total_kopecks"] is None
        assert instrument["months"][1]["return_percent"] is None
        for field in INCOME_FIELDS:
            assert instrument["months"][1][field] is None
        assert instrument["all_time"]["partial"]
        assert "missing_month" in instrument["all_time"]["flags"]
        assert instrument["all_time"]["available_months"] == ["2030-06-01"]


def test_pending_trade_with_future_settlement_is_not_zero_activity(db, monkeypatch):
    intake = save(db)
    save(db, 5, trades=(), bond=("3", "3", "3150", "3180"))
    reader = source_intake.read_intake

    def pending(session, intake_id):
        view = reader(session, intake_id)
        if intake_id == intake:
            view = deepcopy(view)
            trade = view["document"]["trades"][0]
            trade["state"] = "pending"
            trade["settlement_date"] = "2030-05-02"
        return view

    monkeypatch.setattr(source_intake, "read_intake", pending)
    result = by_isin(read(db))
    for row in result[BOND].months:
        assert "trade_missing_settlement" in row.flags
        assert row.buys_cost_kopecks is None and row.total_kopecks is None
    assert all(row.total_kopecks is not None for row in result[ISIN].months)


def test_native_account_ambiguity_is_local_to_source_month(db, monkeypatch):
    intake = save(db)
    save(db, 5, trades=(), bond=("3", "3", "3150", "3180"))
    reader = source_intake.read_intake

    def ambiguous(session, intake_id):
        view = reader(session, intake_id)
        if intake_id == intake:
            view = deepcopy(view)
            view["document"]["trades"][0]["core"]["source_account"] = "other-native-account"
        return view

    monkeypatch.setattr(source_intake, "read_intake", ambiguous)
    result = read(db)
    assert "native_source_scope_ambiguous" in {gap.code for gap in result.gaps}
    for row in result.instruments:
        assert row.months[0].total_kopecks is None
        assert not row.months[0].income_complete
        assert row.months[1].total_kopecks is not None


def test_confirmed_overlap_choice_overrides_default_income_without_double_count(db):
    extra = (("Купон", BOND, "30"),)
    save(db, extra=extra)
    second = save(db, extra=extra, marker="confirmed")
    with db.session_factory() as session:
        row = session.scalar(
            select(SourceMoneyClassification).where(SourceMoneyClassification.intake_id == second)
        )
        choose_classification(session, second, row.source_reference, "coupon")
    result = read(db)
    paid = result.income[0]
    assert paid.status == "confirmed" and len(paid.source_references) == 2
    row = by_isin(result)[BOND].months[0]
    assert row.coupons_kopecks == row.confirmed_income_kopecks == 3_000
    assert not row.income_assumptions_used and row.income_complete


def test_foreign_income_is_a_gap_and_never_rub_zero(db):
    def mutate(root):
        root.find(".//m:p_code[@volume]", NS).set("p_code", "USD")

    save(db, extra=(("Купон", BOND, "30"),), mutate=mutate)
    result = read(db)
    assert "currency_unsupported" in {gap.code for gap in result.gaps}
    assert all(not row.months[0].income_complete for row in result.instruments)
    assert all(row.months[0].total_kopecks is None for row in result.instruments)


def test_unparsed_source_rows_withhold_costs_and_keep_other_months(db):
    def mutate(root):
        ET.SubElement(root.find("m:Trades/m:Report", NS), "{MyBroker}UnknownTradeShape")

    save(db, mutate=mutate)
    save(db, 5, trades=(), bond=("3", "3", "3150", "3180"))
    result = read(db)
    assert "unparsed_source_rows" in {gap.code for gap in result.gaps}
    for instrument in result.instruments:
        first, second = instrument.months
        assert first.opening_value_kopecks is not None
        assert first.buys_cost_kopecks is None and first.total_kopecks is None
        assert not first.income_complete
        assert second.total_kopecks is not None


def test_one_money_reader_failure_does_not_fail_response_or_other_months(db, monkeypatch):
    from hermes_finance.services import source_instrument_returns as service

    failed = save(db, extra=(("Купон", BOND, "30"),))
    save(db, 5, trades=(), bond=("3", "3", "3150", "3180"))
    money_reader = service._money

    def broken(session, view, choices, gaps):
        if view["id"] == failed:
            raise ValueError("synthetic malformed saved money row")
        return money_reader(session, view, choices, gaps)

    monkeypatch.setattr(service, "_money", broken)
    before = snapshot(db)
    result = read(db)
    assert "source_reader_unavailable" in {gap.code for gap in result.gaps}
    for instrument in result.instruments:
        assert instrument.months[0].total_kopecks is None
        assert instrument.months[1].total_kopecks is not None
    assert snapshot(db) == before


@pytest.mark.parametrize(
    "basis,amount",
    [
        ("includes_paid_nkd", "1020"),
        ("excludes_paid_nkd", "1000"),
    ],
)
@pytest.mark.parametrize("quantity", ["1", "-1"])
def test_bond_native_total_basis_counts_nkd_once(db, monkeypatch, basis, amount, quantity):
    monkeypatch.setattr(service, "_native_total_basis", lambda session, trade: basis)
    bond = ("2", "3", "2000", "3150") if quantity == "1" else ("2", "1", "2000", "1050")
    save(db, bond=bond, trades=((BOND, quantity, amount, "20", "5"),))
    before = snapshot(db)
    row = by_isin(read(db))[BOND].months[0]
    if quantity == "1":
        assert row.buys_cost_kopecks == 102_500
        assert row.sells_proceeds_kopecks == 0
        assert row.price_effect_kopecks == row.total_kopecks == 12_500
        assert row.capital_base_kopecks == 302_500
    else:
        assert row.buys_cost_kopecks == 0
        assert row.sells_proceeds_kopecks == 101_500
        assert row.price_effect_kopecks == row.total_kopecks == 6_500
        assert row.capital_base_kopecks == 200_000
    assert row.return_percent == service._percent(row.total_kopecks, row.capital_base_kopecks)
    assert "trade_nkd_basis_unknown" not in row.flags
    assert snapshot(db) == before


@pytest.mark.parametrize("quantity", ["1", "-1"])
def test_unknown_native_bond_basis_withholds_costs_without_guessing(db, quantity):
    save(db, trades=((BOND, quantity, "520", "20", "5"),))
    save(db, 5, trades=(), bond=("3", "3", "3150", "3180"))
    result = by_isin(read(db))
    first, second = result[BOND].months
    assert first.buys_cost_kopecks is None and first.sells_proceeds_kopecks is None
    assert first.price_effect_kopecks is None and first.total_kopecks is None
    assert first.return_percent is None and "trade_nkd_basis_unknown" in first.flags
    assert second.total_kopecks == 3_000
    assert result[BOND].all_time.partial_months == (date(2030, 4, 1),)
    assert result[BOND].all_time.missing_months == ()
    assert result[ISIN].months[0].total_kopecks == 10_000


@pytest.mark.parametrize(
    "section,code",
    [
        ("Trades3", "4_Transfers_unsupported"),
        ("Trades4", "5_UFSR_unsupported"),
        ("Positions", "position_row_unclassified"),
    ],
)
def test_opaque_source_structure_is_a_month_local_gap(db, section, code):
    def mutate(root):
        if section == "Positions":
            position = deepcopy(root.find(".//m:Details[@ISIN1]", NS))
            position.set("ISIN1", "")
            position.set("active_type", "Unknown synthetic position")
            root.find(".//m:Details_Collection", NS).append(position)
        else:
            ET.SubElement(
                root.find("m:" + section + "/m:Report", NS), "{MyBroker}OpaqueSyntheticSection"
            )

    save(db, trades=(), stock=("10", "12", "1000", "1300"), mutate=mutate)
    save(db, 5, trades=(), stock=("12", "12", "1300", "1400"), bond=("3", "3", "3150", "3180"))
    result = read(db)
    assert code in {gap.code for gap in result.gaps}
    for instrument in result.instruments:
        first, second = instrument.months
        assert code in first.flags
        assert first.buys_cost_kopecks is None and first.sells_proceeds_kopecks is None
        assert first.price_effect_kopecks is None and first.total_kopecks is None
        assert not first.income_complete
        assert all(getattr(first, field) is None for field in INCOME_FIELDS)
        assert second.total_kopecks is not None and second.income_complete
        assert code not in second.flags


@pytest.mark.parametrize("overlap", [False, True])
def test_one_part_trade_identity_is_unresolved_even_in_overlaps(db, overlap):
    def mutate(root):
        root.find(".//m:Details[@trade_no]", NS).set("trade_no", "10000000001")

    save(db, mutate=mutate)
    if overlap:
        save(db, mutate=mutate, marker="same-one-part-trade")
    save(db, 5, trades=(), bond=("3", "3", "3150", "3180"))
    result = by_isin(read(db))
    first, second = result[BOND].months
    assert "trade_identity_unresolved" in first.flags
    assert first.buys_cost_kopecks is None and first.sells_proceeds_kopecks is None
    assert first.total_kopecks is None and first.return_percent is None
    assert second.total_kopecks == 3_000
    assert result[ISIN].months[0].total_kopecks == 10_000


@pytest.mark.parametrize("gap", ["unparsed", "unreadable", "unknown_money"])
def test_unknown_income_without_observations_is_null_in_month_and_all_time(db, monkeypatch, gap):
    def mutate(root):
        if gap == "unparsed":
            ET.SubElement(root.find("m:Trades/m:Report", NS), "{MyBroker}UnknownTradeShape")

    failed = save(
        db,
        trades=(),
        mutate=mutate,
        extra=(("Unknown", "Synthetic unknown income", "17"),) if gap == "unknown_money" else (),
    )
    if gap == "unreadable":
        # A long readable intake supplies identities but not monthly income coverage.
        save(db, end_month=5, trades=(), marker="identity-only")
        reader = source_intake.read_intake

        def broken(session, intake_id):
            if intake_id == failed:
                raise MyBrokerError("synthetic unavailable intake")
            view = deepcopy(reader(session, intake_id))
            view["document"]["money"] = []
            return view

        monkeypatch.setattr(source_intake, "read_intake", broken)
    result = read(db)
    for instrument in result.instruments:
        first = instrument.months[0]
        assert not first.income_complete and first.total_kopecks is None
        for field in INCOME_FIELDS:
            assert getattr(first, field) is None
            # For unreadable April, the covered May confirms zero; otherwise no
            # month supplies even an observed subtotal.
            assert getattr(instrument.all_time, field) == (0 if gap == "unreadable" else None)


def test_all_time_separates_covered_partial_total_from_missing_coverage(db):
    save(db, trades=(), extra=(("Купон", "Unknown security", "17"),))
    save(db, 5, trades=(), stock=("10", "10", "1100", "1150"), extra=(("Дивиденды", ISIN, "10"),))
    instrument = by_isin(read(db))[ISIN]
    first, second = instrument.months
    assert first.price_effect_kopecks == 10_000 and first.total_kopecks is None
    assert first.income_kopecks is None
    assert second.price_effect_kopecks == 5_000 and second.income_kopecks == 1_000
    total = instrument.all_time
    assert total.price_effect_kopecks == 15_000 and total.income_kopecks == 1_000
    assert total.total_kopecks == 6_000  # Available monthly totals, not component sums.
    assert total.available_months == (date(2030, 5, 1),)
    assert total.partial_months == (date(2030, 4, 1),)
    assert total.missing_months == () and "missing_month" not in total.flags
    assert total.partial and not total.income_complete


def test_partial_income_keeps_only_observed_subtotals(db):
    save(db, trades=(), extra=(("Купон", "Unknown security", "17"), ("Дивиденды", ISIN, "10")))
    instrument = by_isin(read(db))[ISIN]
    row = instrument.months[0]
    assert row.dividends_kopecks == row.income_kopecks == row.assumed_income_kopecks == 1_000
    assert row.coupons_kopecks is None and row.confirmed_income_kopecks is None
    assert instrument.all_time.income_kopecks == 1_000
    assert not row.income_complete and row.total_kopecks is None


def test_assumed_stock_income_is_approximate(db):
    save(db, trades=(), extra=(("Дивиденды", ISIN, "25"),))
    instrument = by_isin(read(db))[ISIN]
    row = instrument.months[0]
    assert row.approximate and instrument.all_time.approximate
    assert row.income_assumptions_used and "income_assumed" in row.flags
    assert row.total_kopecks == 12_500 and row.income_complete


@pytest.mark.parametrize("kind", ["Паи", "Synthetic other instrument"])
def test_unsupported_instrument_trade_with_omitted_nkd_is_not_assumed_zero(db, kind):
    def mutate(root):
        root.find(f".//m:Details[@ISIN1='{ISIN}']", NS).set("active_type", kind)

    save(db, trades=((ISIN, "1", "100", None, "1"),), mutate=mutate)
    row = by_isin(read(db))[ISIN].months[0]
    assert "instrument_type_unknown" in row.flags and "trade_components_missing" in row.flags
    assert row.buys_cost_kopecks is None and row.total_kopecks is None


@pytest.mark.parametrize("currency", ["RUR", " rur ", " RuB "])
def test_ruble_currency_aliases_match_rub_for_instrument_income_and_trades(db, currency):
    def mutate(root):
        for row in root.findall(".//m:p_code[@volume]", NS):
            row.set("p_code", currency)
        root.find(".//m:Details[@trade_no]", NS).set("curr_calc", currency)

    save(
        db,
        stock=("10", "11", "1000", "1210"),
        trades=((ISIN, "1", "100", None, "1"),),
        extra=(("Дивиденды", ISIN, "25"),),
        mutate=mutate,
    )
    result = read(db)
    row = by_isin(result)[ISIN].months[0]
    assert row.buys_cost_kopecks == 10_100
    assert row.dividends_kopecks == 2_500 and row.total_kopecks == 13_400
    assert row.income_complete
    assert not {"currency_unsupported", "trade_currency_unsupported"}.intersection(row.flags)
    assert "currency_unsupported" not in {gap.code for gap in result.gaps}


@pytest.mark.parametrize("basis", ["includes_paid_nkd", "excludes_paid_nkd"])
@pytest.mark.parametrize("inference", ["agrees", "unknown", "conflicts"])
def test_accepted_basis_is_bound_to_exact_trade_components(db, monkeypatch, basis, inference):
    amount = "1020" if basis == "includes_paid_nkd" else "1000"
    price = {
        "agrees": "100",
        "unknown": "50",
        "conflicts": "102" if basis == "includes_paid_nkd" else "98",
    }[inference]

    def mutate(root):
        root.find(".//m:Details[@trade_no]", NS).set("Price", price)

    intake = save(db, trades=((BOND, "1", amount, "20", "5"),), mutate=mutate)
    with db.session_factory() as session:
        trade = source_intake.read_intake(session, intake)["document"]["trades"][0]
        account = Account(name="Synthetic", account_type="brokerage")
        instrument = Instrument(name="Synthetic bond", instrument_type="bond", isin=BOND)
        session.add_all([account, instrument])
        session.flush()
        session.add(
            ExecutedTrade(
                provider="mybroker",
                source_account=ACCOUNT,
                primary_id=trade["ids"][0],
                secondary_id=trade["ids"][1],
                source_identity=trade["identity"],
                account_id=account.id,
                instrument_id=instrument.id,
                core_json=json.dumps(trade["core"]),
                bindings_json="[]",
                accepted_at=datetime.now(UTC),
            )
        )
        session.commit()
        proof = {
            "source_identity": trade["identity"],
            "native_ids": trade["ids"],
            "claims": {
                "native_total_basis": basis,
                "exact_row_settled_buy_link": True,
                "complete_occurrence_set_is_one_event": True,
                "nkd_separately_posted": True,
                "fee_separately_charged": True,
                "native_total_basis_independently_proved": True,
            },
            "signed_minor": {
                "settlement": "-100000",
                "paid_nkd": "-2000",
                "commission": "-500",
                "native_total": str(int(amount) * 100),
            },
            "nkd_leg": {"effective_date": trade["settlement_date"], "currency": "RUB"},
        }
        monkeypatch.setattr(
            service.broker_trade_money, "effective_proof", lambda session, identity: proof
        )
        assert service._native_total_basis(session, trade) == basis
        legacy = deepcopy(trade)
        legacy["core"]["currency"] = " rur "
        assert service._native_total_basis(session, legacy) == basis
        with localcontext() as context:
            context.prec = 6
            assert service._native_total_basis(session, trade) == basis
        before = snapshot(db)
        result = by_isin(read_instrument_returns(session, source_account=ACCOUNT))[BOND].months[0]
        assert snapshot(db) == before
        if inference == "conflicts":
            assert result.buys_cost_kopecks is None and result.total_kopecks is None
            assert {"trade_nkd_basis_unknown", "trade_nkd_basis_conflict"} <= set(result.flags)
        else:
            assert result.buys_cost_kopecks == 102_500 and result.total_kopecks == 12_500
            assert "trade_nkd_basis_unknown" not in result.flags
        for field in ("trade_amount", "quantity", "trade_time", "isin"):
            changed = deepcopy(trade)
            changed["core"][field] = {
                "trade_amount": "999",
                "quantity": "2",
                "trade_time": "2030-04-01T10:00:00",
                "isin": ISIN,
            }[field]
            assert service._native_total_basis(session, changed) is None
        changed = deepcopy(trade)
        changed["ids"] = ["999", "888"]
        assert service._native_total_basis(session, changed) is None
        changed = deepcopy(trade)
        changed["settlement_date"] = "2030-04-30"
        assert service._native_total_basis(session, changed) is None
        proof["claims"]["native_total_basis_independently_proved"] = False
        assert service._native_total_basis(session, trade) is None


def test_overlapping_rur_and_rub_trades_and_income_are_counted_once(db):
    def legacy_currency(root):
        root.find(".//m:Details[@trade_no]", NS).set("curr_calc", " rur ")
        for row in root.findall(".//m:p_code[@volume]", NS):
            row.set("p_code", " rur ")

    options = dict(
        stock=("10", "11", "1000", "1210"),
        trades=((ISIN, "1", "100", None, "1"),),
        extra=(("Дивиденды", ISIN, "25"),),
    )
    save(db, **options)
    save(db, **options, mutate=legacy_currency, marker="legacy-currency-copy")
    result = read(db)
    row = by_isin(result)[ISIN].months[0]
    assert row.buys_cost_kopecks == 10_100 and row.dividends_kopecks == 2_500
    assert row.total_kopecks == 13_400 and row.income_complete
    assert "overlapping_trade_conflict" not in row.flags
    assert len(result.income) == 1 and len(result.income[0].source_references) == 2


@pytest.mark.parametrize("quantity", ["2", "-2"])
@pytest.mark.parametrize("amount", ["2070.00", "2030.00"])
def test_details_bond_arithmetic_counts_nkd_once_without_proof(db, quantity, amount):
    def mutate(root):
        row = root.find(".//m:Details[@trade_no]", NS)
        row.attrib.update(
            Price="101.5",
            place_name="Synthetic exchange",
            p_name="Synthetic bond",
            Textbox14="",
            repo_no="",
        )

    bond = ("2", "4", "2000", "4200") if quantity == "2" else ("4", "2", "4000", "2100")
    intake = save(db, bond=bond, trades=((BOND, quantity, amount, "40.00", "3"),), mutate=mutate)
    with db.session_factory() as session:
        trade = source_intake.read_intake(session, intake)["document"]["trades"][0]
        assert trade["core"]["price"] == "101.5" and trade["core"]["quantity"] == quantity
        assert service._native_total_basis(session, trade) is None
    before = snapshot(db)
    row = by_isin(read(db))[BOND].months[0]
    if quantity == "2":
        assert row.buys_cost_kopecks == 207_300  # T + fee, or T + NKD + fee.
        assert row.sells_proceeds_kopecks == 0
        assert row.total_kopecks == 12_700
    else:
        assert row.buys_cost_kopecks == 0
        assert row.sells_proceeds_kopecks == 206_700
        assert row.total_kopecks == 16_700
    assert "trade_nkd_basis_unknown" not in row.flags
    assert row.approximate and "bond_valuation_basis_unknown" in row.flags
    with localcontext() as context:
        context.prec = 6
        assert by_isin(read(db))[BOND].months[0] == row
    assert snapshot(db) == before


@pytest.mark.parametrize(
    "amount,nkd,expected",
    [
        ("2070.01", "40", 207_301),
        ("2069.99", "40", 207_299),
        ("2030.01", "40", 207_301),
        ("2029.99", "40", 207_299),
        ("2070.02", "40", None),
        ("2069.98", "40", None),
        ("2030.02", "40", None),
        ("2029.98", "40", None),
        ("1055", "40", None),  # Face 500: neither 1000-face equation matches.
        ("2030.00", "0.01", None),  # Both equations are within tolerance.
        ("2030.00", "0", 203_300),  # Exclusive predicate requires nonzero NKD.
    ],
)
def test_details_bond_basis_uses_exact_per_row_kopeck_tolerance(db, amount, nkd, expected):
    def mutate(root):
        root.find(".//m:Details[@trade_no]", NS).set("Price", "101.5")

    save(
        db, bond=("2", "4", "2000", "4200"), trades=((BOND, "2", amount, nkd, "3"),), mutate=mutate
    )
    result = by_isin(read(db))
    row = result[BOND].months[0]
    assert row.buys_cost_kopecks == expected
    assert ("trade_nkd_basis_unknown" in row.flags) == (expected is None)
    if expected is None:
        assert row.sells_proceeds_kopecks is None
        assert row.price_effect_kopecks is None and row.total_kopecks is None
        assert row.return_percent is None
    assert result[ISIN].months[0].total_kopecks == 10_000


@pytest.mark.parametrize(
    "amounts,expected", [(("2070", "2030"), 414_600), (("2070.02", "2069.98"), None)]
)
def test_bond_basis_is_inferred_for_each_trade_before_summing(db, amounts, expected):
    def mutate(root):
        for row in root.findall(".//m:Details[@trade_no]", NS):
            row.set("Price", "101.5")

    save(
        db,
        bond=("2", "6", "2000", "6300"),
        trades=tuple((BOND, "2", amount, "40", "3") for amount in amounts),
        mutate=mutate,
    )
    row = by_isin(read(db))[BOND].months[0]
    assert row.buys_cost_kopecks == expected
    assert ("trade_nkd_basis_unknown" in row.flags) == (expected is None)


def test_arithmetic_bond_inference_requires_known_bond_type(db):
    def mutate(root):
        root.find(f".//m:Details[@ISIN1='{BOND}']", NS).set("active_type", "Unknown synthetic type")
        root.find(".//m:Details[@trade_no]", NS).set("Price", "101.5")

    save(db, trades=((BOND, "2", "2070", "40", "3"),), mutate=mutate)
    row = by_isin(read(db))[BOND].months[0]
    assert {"instrument_type_unknown", "trade_nkd_basis_unknown"} <= set(row.flags)
    assert row.buys_cost_kopecks is None and row.total_kopecks is None


@pytest.mark.parametrize("observed_income", [False, True])
def test_non_rub_money_preserves_known_price_components(db, accepted_basis, observed_income):
    def mutate(root):
        root.findall(".//m:p_code[@volume]", NS)[-1].set("p_code", "USD")

    known = (("Дивиденды", ISIN, "25"), ("Купон", BOND, "30")) if observed_income else ()
    save(db, extra=(*known, ("Дивиденды", ISIN, "17")), mutate=mutate)
    before = snapshot(db)
    result = read(db)
    instruments = by_isin(result)
    stock, bond = instruments[ISIN].months[0], instruments[BOND].months[0]
    assert (stock.buys_cost_kopecks, stock.sells_proceeds_kopecks) == (0, 0)
    assert stock.price_effect_kopecks == 10_000
    assert (bond.buys_cost_kopecks, bond.sells_proceeds_kopecks) == (102_500, 0)
    assert bond.price_effect_kopecks == 12_500
    assert "currency_unsupported" in {gap.code for gap in result.gaps}
    for instrument, amount in ((instruments[ISIN], 2_500), (instruments[BOND], 3_000)):
        row = instrument.months[0]
        assert "currency_unsupported" in row.flags
        assert not row.income_complete and not instrument.all_time.income_complete
        assert row.total_kopecks is None and row.return_percent is None
        assert row.income_kopecks == (amount if observed_income else None)
        assert instrument.all_time.price_effect_kopecks == row.price_effect_kopecks
        assert instrument.all_time.total_kopecks is None and instrument.all_time.partial
        if not observed_income:
            assert all(getattr(row, field) is None for field in INCOME_FIELDS)
    assert snapshot(db) == before


@pytest.mark.parametrize(
    "attribute,value,code",
    [
        ("curr_calc", "USD", "trade_currency_unsupported"),
        ("repo_no", "99999999999", "repo_trade_unsupported"),
    ],
)
@pytest.mark.parametrize("observed_income", [False, True])
def test_unsupported_trade_preserves_covered_income(db, attribute, value, code, observed_income):
    def mutate(root):
        root.find(".//m:Details[@trade_no]", NS).set(attribute, value)

    extra = (("Дивиденды", ISIN, "25"), ("Купон", BOND, "30")) if observed_income else ()
    save(db, extra=extra, mutate=mutate)
    before = snapshot(db)
    result = by_isin(read(db))
    stock, bond = result[ISIN].months[0], result[BOND].months[0]
    assert code in bond.flags and code not in stock.flags
    assert bond.buys_cost_kopecks is None and bond.sells_proceeds_kopecks is None
    assert bond.price_effect_kopecks is None and bond.total_kopecks is None
    assert bond.return_percent is None
    assert bond.income_complete and result[BOND].all_time.income_complete
    assert bond.coupons_kopecks == bond.income_kopecks == (3_000 if observed_income else 0)
    assert stock.income_complete
    assert stock.dividends_kopecks == (2_500 if observed_income else 0)
    assert stock.price_effect_kopecks == 10_000
    assert stock.total_kopecks == (12_500 if observed_income else 10_000)
    assert snapshot(db) == before
