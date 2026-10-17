"""Source-backed synthetic EOD pair; observations never imply performance."""

import json
from datetime import date
from xml.etree import ElementTree as ET

import pytest
from _statement_pdf import build_income_report_pdf
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from test_statement_import_apply import apply as pdf_apply
from test_statement_import_apply import preview as pdf_preview
from test_statement_import_apply import selection_from_row, sqlite_blob
from test_statement_import_mybroker import FILENAME, ISIN
from test_statement_import_mybroker import database as database
from test_statement_import_mybroker_endpoints import (
    _broker_month_apply,
    _broker_month_preview,
    _money_apply,
    _money_decide,
    money_batch_xml,
)

from hermes_finance.domain.broker_money import MoneyIntent
from hermes_finance.main import create_app
from hermes_finance.persistence import (
    BrokerIdentityMapping,
    CashBalance,
    Instrument,
    InvestmentCashFlow,
    MyBrokerImport,
    PositionSnapshot,
    ReportingMonth,
)
from hermes_finance.services.accounts import create_account
from hermes_finance.services.broker_identity_mappings import revoke_mapping
from hermes_finance.services.instrument_eod_observations import (
    compare_observations,
    instrument_eod_observations,
)
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.reporting_months import create_reporting_month

A, B = date(2030, 1, 31), date(2030, 2, 28)
FEB_FILE = FILENAME.replace("01.01.30-31.01.30", "01.02.30-28.02.30")


def eod_xml(*, closing=False, quantity="10", sold=False):
    root = ET.fromstring(money_batch_xml(coupons=("120",)))
    trades = root.find("{MyBroker}Trades/{MyBroker}Report/{MyBroker}Tablix2")
    for child in list(trades):
        trades.remove(child)
    collection = root.find(".//{MyBroker}rn_Collection")
    for child in list(collection):
        comment = child.find("{MyBroker}oper_type/{MyBroker}comment")
        if not closing or "погашение купона" not in comment.get("comment", "").lower():
            collection.remove(child)
    for row in root.findall(".//{MyBroker}Details[@ISIN1]"):
        isin = row.get("ISIN1")
        row.set("income_rest", "10")
        row.set("real_rest", quantity if closing else "10")
        row.set("forward_rest", quantity if closing else "10")
        row.set("income_volume", "1000.00")
        row.set(
            "real_volume",
            ("950.00" if isin == "RU000A000001" else "900.00") if closing else "1000.00",
        )
        if closing and quantity == "0":
            row.set("real_volume", "0.00")
        if closing and sold and isin == "RU000A000001":
            parent = next(p for p in root.iter() if row in list(p))
            parent.remove(row)
    cash = root.find(".//{MyBroker}Details[@active_name='RUB']")
    cash.set("income_rest", "1000.00")
    cash.set("real_rest", "1120.00" if closing else "1000.00")
    xml = ET.tostring(root, encoding="utf-8")
    if closing:
        xml = xml.replace(b".01.2030", b".02.2030").replace(b"2030-01-", b"2030-02-")
    return xml


def make_pair(database, *, quantity="10", sold=False):
    with database.session_factory() as session:
        bond = create_instrument(
            session, name="Synthetic EOD bond", instrument_type="bond", isin="RU000A000001"
        )
        opening = create_reporting_month(session, year=2030, month=1, snapshot_date=A)
        closing = create_reporting_month(session, year=2030, month=2, snapshot_date=B)
        bond_id, opening_id, closing_id = bond.id, opening.id, closing.id
    client = TestClient(create_app(database))
    for closing, month, filename, request_id in (
        (False, opening_id, FILENAME, "eod-open"),
        (True, closing_id, FEB_FILE, "eod-close"),
    ):
        xml = eod_xml(closing=closing, quantity=quantity, sold=sold)
        scope = {"account_id": 1, "reporting_month_id": month}
        plan = _broker_month_preview(client, scope, xml, filename=filename)
        response = _broker_month_apply(
            client, scope, plan, xml, filename=filename, request_id=request_id
        )
        assert response.status_code == 200, response.text
    intent = MoneyIntent(
        contract_version="broker_money_v1",
        base_request_id="eod-close",
        account_id=1,
        reporting_month_id=closing_id,
    )
    originals = [(FEB_FILE, eod_xml(closing=True, quantity=quantity, sold=sold))]
    with database.session_factory() as session:
        _money_apply(
            session, _money_decide(session, intent, originals, bond_id, funding=False), originals
        )
    return client, bond_id, intent, originals


def read(session, instrument_id):
    return instrument_eod_observations(session, 1, instrument_id, A, B)


def add_stock_dividend(database, bond, intent, originals):
    pdf = build_income_report_pdf(
        [
            {
                "isin": ISIN,
                "payment_kind": "выплата дивидендов",
                "record_date": "15.02.2030",
                "payment_date": "20.02.2030",
                "quantity": "10",
                "per_unit": "12,00",
                "gross": "120,00",
                "net": "120,00",
                "tax": "—",
                "tax_rate": "—",
            }
        ]
    )
    with database.session_factory() as session:
        row = pdf_preview(session, pdf, 1).rows[0]
        assert pdf_apply(session, pdf, 1, (selection_from_row(row),)).success
        reviewed = _money_decide(
            session, intent, originals, bond, funding=False, operation="reaffirm"
        )
        _money_apply(session, reviewed, originals, "eod-payout-reaffirm")


def test_stock_dividend_and_values_remain_separate_without_total_return(database):
    _, bond, intent, originals = make_pair(database)
    add_stock_dividend(database, bond, intent, originals)
    with database.session_factory() as session:
        stock = session.scalar(select(Instrument).where(Instrument.isin == ISIN))
        stock.is_active = False
        session.commit()
        result = read(session, stock.id)
        assert [result[b]["market_value"] for b in ("opening", "closing")] == ["1000.00", "900.00"]
        assert result["known_payouts"]["known_booked_net"]["dividend"] == "120.00"
        assert result["known_payouts"]["events"][0]["tax"] is None
        assert result["observed_position_value_difference"] == "-100.00"
        assert "full_instrument_return_unavailable" in result["reason_codes"]
        assert "economic_result" not in result and "period_return" not in result


def test_source_observed_zero_without_entitlement_proof_is_not_closing_zero(database):
    _, bond, _, _ = make_pair(database, quantity="0")
    with database.session_factory() as session:
        result = read(session, bond)
        assert result["closing"]["quantity"] is result["closing"]["market_value"] is None
        assert result["known_payouts"]["known_booked_net"]["coupon"] == "120.00"


def test_manual_position_and_current_catalogue_do_not_establish_historical_rub_authority(database):
    from hermes_finance.services.positions import create_position_snapshot

    with database.session_factory() as session:
        stock = session.scalar(select(Instrument))
        month = create_reporting_month(session, year=2030, month=1, snapshot_date=A)
        create_position_snapshot(
            session,
            reporting_month_id=month.id,
            account_id=1,
            instrument_id=stock.id,
            quantity="10",
            average_cost_per_unit="100.00",
            market_price_per_unit="100.00",
            price_date=A,
        )
        result = read(session, stock.id)
        assert result["opening"]["market_value"] is None
        assert result["opening"]["historical_identity"] is None
        assert result["dependency_fingerprint"] is None
        assert "native_position_authority_unavailable" in result["opening"]["reason_codes"]


def test_native_bond_exact_pair_and_coupon_are_three_separate_facts_zero_dml_closed_api(database):
    client, bond, intent, _ = make_pair(database)
    with database.session_factory() as session:
        for month in session.scalars(select(ReportingMonth)):
            month.status = "closed"
        session.commit()
        before = sqlite_blob(database)
        result = read(session, bond)
        assert result["opening"]["market_value"] == "1000.00"
        assert result["closing"]["market_value"] == "950.00"
        assert result["opening"]["quantity"] == result["closing"]["quantity"] == "10"
        assert (
            session.get(
                PositionSnapshot, result["closing"]["position_id"]
            ).market_price_per_unit_kopecks
            is None
        )
        assert result["opening"]["historical_identity"] == {
            "isin": "RU000A000001",
            "instrument_type": "bond",
            "denomination": "RUB",
        }
        assert result["opening"]["bond_nkd_basis"] == "unknown"
        assert result["comparable"] is None and result["observed_position_value_difference"] is None
        assert result["known_payouts"]["known_booked_net"]["coupon"] == "120.00"
        assert result["known_payouts"]["events"][0]["tax"] is None
        assert result["dependency_fingerprint"]
        assert not {"economic_result", "profit", "period_return"}.intersection(result)
        params = {"account_id": 1, "t0": str(A), "t1": str(B)}
        response = client.get(f"/api/instruments/{bond}/eod-observations", params=params)
        assert response.status_code == 200, response.text
        assert response.json() == result
        assert (
            client.get(
                f"/api/instruments/{bond}/eod-observations", params={**params, "t0": str(B)}
            ).status_code
            == 422
        )
        assert (
            client.get("/api/instruments/9999/eod-observations", params=params).status_code == 404
        )
        assert (
            client.post(f"/api/instruments/{bond}/eod-observations", json=params).status_code == 405
        )
        assert sqlite_blob(database) == before


def test_stock_quantity_change_is_only_observed_position_value_difference(database):
    _, _, _, _ = make_pair(database, quantity="5")
    with database.session_factory() as session:
        stock = session.scalar(select(Instrument).where(Instrument.isin == ISIN))
        result = read(session, stock.id)
        assert result["opening"]["quantity"] == "10" and result["closing"]["quantity"] == "5"
        assert result["comparable"] is True
        assert result["observed_position_value_difference"] == "-100.00"
        assert "quantity_changed_not_profit" in result["reason_codes"]


@pytest.mark.parametrize("change", ["date", "type", "currency", "value", "row_key", "archived"])
def test_invalid_native_boundary_never_returns_stale_numeric_value(database, change):
    _, bond, _, _ = make_pair(database)
    with database.session_factory() as session:
        row = session.scalar(
            select(PositionSnapshot).where(
                PositionSnapshot.instrument_id == bond, PositionSnapshot.price_date == B
            )
        )
        if change == "date":
            row.price_date = date(2030, 2, 27)
        elif change == "type":
            row.historical_instrument_type = "stock"
            row.bond_nkd_basis = "not_applicable"
        elif change == "currency":
            session.get(Instrument, bond).currency = "USD"
        elif change == "value":
            row.market_value_kopecks += 1
        elif change == "row_key":
            row.source_row_key = "a" * 64
        else:
            row.reporting_month_id = None
            row.archived_from_period = "2030-02"
        session.commit()
        result = read(session, bond)
        assert result["closing"]["market_value"] is None
        assert result["closing"]["availability"] == "unavailable"
        assert result["closing"]["reason_codes"]
        assert result["observed_position_value_difference"] is None


def test_sold_missing_endpoint_is_not_zero_and_coupon_remains_visible(database):
    _, bond, _, _ = make_pair(database, sold=True)
    with database.session_factory() as session:
        result = read(session, bond)
        assert result["opening"]["market_value"] == "1000.00"
        assert result["closing"]["quantity"] is result["closing"]["market_value"] is None
        assert "exact_eod_position_missing" in result["closing"]["reason_codes"]
        assert result["known_payouts"]["known_booked_net"]["coupon"] == "120.00"
        near = instrument_eod_observations(session, 1, bond, A, date(2030, 2, 27))
        assert near["closing"]["market_value"] is None
        assert near["dependency_fingerprint"] is None


def test_source_and_position_aba_invalidate_old_joined_fingerprint(database):
    _, bond, _, _ = make_pair(database)
    with database.session_factory() as session:
        a = read(session, bond)
        row = session.scalar(
            select(PositionSnapshot).where(
                PositionSnapshot.instrument_id == bond, PositionSnapshot.price_date == B
            )
        )
        for value in (94999, 95000):
            row.market_value_kopecks = value
            session.commit()
            got = read(session, bond)
            assert got["dependency_fingerprint"] != a["dependency_fingerprint"]
        assert got["closing"]["market_value"] == "950.00"
        source = session.get(MyBrokerImport, row.source_import_id)
        original = source.normalized_json
        document = json.loads(original)
        document["positions"][0]["ending_value"] = "901"
        source.normalized_json = json.dumps(document)
        session.commit()
        b = read(session, bond)
        source.normalized_json = original
        session.commit()
        again = read(session, bond)
        assert b["closing"]["market_value"] is None
        assert len({r["dependency_fingerprint"] for r in (a, b, again)}) == 3


def test_mapping_revoke_missing_identity_is_not_catalogue_fallback(database):
    _, bond, _, _ = make_pair(database)
    with database.session_factory() as session:
        mapping = session.scalar(
            select(BrokerIdentityMapping).where(
                BrokerIdentityMapping.hermes_instrument_id == bond,
                BrokerIdentityMapping.status == "effective",
            )
        )
        revoke_mapping(session, mapping.id, reason="Synthetic historical revoke")
        result = read(session, bond)
        assert all(result[b]["market_value"] is None for b in ("opening", "closing"))


def test_native_projection_readback_is_bound_even_without_writer_notification(database):
    _, bond, intent, _ = make_pair(database)
    with database.session_factory() as session:
        before = read(session, bond)
        # A diagnostic raw SQL edit is outside supported-writer ABA guarantees,
        # but a changed current projection must still invalidate its readback.
        session.execute(
            CashBalance.__table__.update()
            .where(CashBalance.reporting_month_id == intent.reporting_month_id)
            .values(amount_kopecks=1)
        )
        session.commit()
        after = read(session, bond)
        assert after["closing"]["market_value"] is None
        assert "native_projection_changed" in after["closing"]["reason_codes"]
        assert (
            before["valuation_dependency_fingerprint"] != after["valuation_dependency_fingerprint"]
        )


def test_pair_nkd_basis_comparison_never_repairs_unknown_or_mismatch():
    base = {
        "availability": "available",
        "historical_identity": {
            "isin": "synthetic",
            "instrument_type": "bond",
            "denomination": "RUB",
        },
        "quantity": "10",
        "market_value": "1000.00",
        "bond_nkd_basis": "included",
    }
    close = {**base, "market_value": "950.00"}
    assert compare_observations(base, close)[:2] == (True, "-50.00")
    assert compare_observations(base, {**close, "bond_nkd_basis": "excluded"})[:2] == (False, None)
    assert compare_observations(base, {**close, "bond_nkd_basis": "unknown"})[:2] == (None, None)


def test_unrelated_account_icf_does_not_enter_eod_fingerprint(database):
    _, bond, intent, _ = make_pair(database)
    with database.session_factory() as session:
        other = create_account(session, name="Other synthetic account", account_type="iis")
        a = read(session, bond)
        session.add(
            InvestmentCashFlow(
                account_id=other.id,
                reporting_month_id=intent.reporting_month_id,
                event_date=date(2030, 2, 20),
                flow_type="dividend",
                source="manual",
                net_amount_kopecks=100,
                gross_amount_kopecks=100,
                tax_amount_kopecks=0,
                commission_amount_kopecks=0,
            )
        )
        session.commit()
        b = read(session, bond)
        assert a["valuation_dependency_fingerprint"] == b["valuation_dependency_fingerprint"]
        wrong = instrument_eod_observations(session, other.id, bond, A, B)
        assert wrong["opening"]["market_value"] is wrong["closing"]["market_value"] is None


def test_later_conflicting_source_retracts_native_boundary_availability(database):
    _, bond, _, _ = make_pair(database)
    with database.session_factory() as session:
        before = read(session, bond)
        source = session.scalar(select(MyBrokerImport).order_by(MyBrokerImport.id.desc()))
        data = {c.name: getattr(source, c.name) for c in source.__table__.columns if c.name != "id"}
        data["document_sha256"] = "b" * 64
        doc = json.loads(source.normalized_json)
        doc["document_sha256"] = data["document_sha256"]
        doc["positions"][0]["ending_value"] = "901"
        data["normalized_json"] = json.dumps(doc)
        session.add(MyBrokerImport(**data))
        session.commit()
        after = read(session, bond)
        assert before["closing"]["market_value"] == "950.00"
        assert after["closing"]["market_value"] is None
        assert "overlapping_endpoint_conflict" in after["closing"]["reason_codes"]


def test_whole_response_fingerprint_propagates_unjournaled_payout_null(database):
    _, bond, intent, _ = make_pair(database)
    with database.session_factory() as session:
        session.add(
            InvestmentCashFlow(
                account_id=1,
                reporting_month_id=intent.reporting_month_id,
                instrument_id=bond,
                event_date=date(2030, 2, 21),
                flow_type="coupon",
                source="manual",
                net_amount_kopecks=1,
                gross_amount_kopecks=1,
                tax_amount_kopecks=0,
                commission_amount_kopecks=0,
            )
        )
        session.commit()
        result = read(session, bond)
        assert result["valuation_dependency_fingerprint"] is not None
        assert result["known_payouts"]["dependency_fingerprint"] is None
        assert result["dependency_fingerprint"] is None


def test_concurrent_mutation_is_outside_committed_pair_snapshot(database):
    _, bond, _, _ = make_pair(database)
    with database.engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA journal_mode=WAL")
    with database.session_factory() as session:
        before = read(session, bond)
        mutated = False

        def mutate(conn, cursor, statement, params, context, many):
            nonlocal mutated
            if not mutated and statement.startswith("SELECT position_snapshots"):
                mutated = True
                with database.session_factory() as other:
                    source = other.scalar(select(MyBrokerImport).order_by(MyBrokerImport.id.desc()))
                    source.normalized_json += " "
                    other.commit()

        event.listen(database.engine, "after_cursor_execute", mutate)
        try:
            assert read(session, bond) == before
        finally:
            event.remove(database.engine, "after_cursor_execute", mutate)
        assert mutated
        assert read(session, bond)["closing"]["market_value"] is None
