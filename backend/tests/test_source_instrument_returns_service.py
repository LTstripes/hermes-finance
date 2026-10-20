"""Fabricated native statements only; source estimates never write financial rows."""

import calendar
from copy import deepcopy
from datetime import date
from decimal import Decimal, localcontext
from xml.etree import ElementTree as ET

import pytest
from sqlalchemy import select
from test_source_monthly_returns_service import snapshot
from test_statement_import_broker_statement_provisional import _free_database, provisional_xml
from test_statement_import_mybroker import ACCOUNT, ISIN

from hermes_finance.persistence import SourceMoneyClassification
from hermes_finance.services import source_intake
from hermes_finance.services.source_instrument_returns import _attribute, read_instrument_returns
from hermes_finance.services.source_money_classifications import choose_classification
from hermes_finance.statement_import.mybroker import NS, MyBrokerError

BOND = "RU000A000001"


@pytest.fixture
def db(tmp_path):
    database = _free_database(tmp_path)
    yield database
    database.engine.dispose()


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


def test_stock_dividend_bond_coupon_nkd_purchase_sale_and_all_time(db):
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


def test_unattributed_coupon_is_retained_and_prevents_false_complete_total(db):
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


def test_bond_sale_adds_received_nkd_and_subtracts_fees(db):
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


def test_overlaps_deduplicate_trades_and_preserve_income_multiplicity(db):
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


def test_get_api_decimal_strings_integer_money_no_store_and_no_writes(db):
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
