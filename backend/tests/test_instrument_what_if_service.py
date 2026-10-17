"""Synthetic source-backed conditional stock HPR, never actual economics."""

import json
from datetime import date
from decimal import Decimal
from xml.etree import ElementTree as ET

import pytest
from _statement_pdf import build_income_report_pdf
from fastapi.testclient import TestClient
from sqlalchemy import event, select, text
from test_instrument_eod_observations_service import FEB_FILE, A, B, eod_xml
from test_statement_import_apply import apply as pdf_apply
from test_statement_import_apply import preview as pdf_preview
from test_statement_import_apply import selection_from_row, sqlite_blob
from test_statement_import_executed_trades import accept_source
from test_statement_import_mybroker import FILENAME, ISIN
from test_statement_import_mybroker import database as database
from test_statement_import_mybroker_endpoints import _broker_month_apply, _broker_month_preview

from hermes_finance.main import create_app
from hermes_finance.persistence import (
    BrokerIdentityMapping,
    InKindMovement,
    Instrument,
    MyBrokerImport,
    PositionSnapshot,
    ReportingMonth,
)
from hermes_finance.services.broker_identity_mappings import revoke_mapping
from hermes_finance.services.instrument_what_if import ASSUMPTIONS, instrument_what_if
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.reporting_months import create_reporting_month

CHOSEN = dict.fromkeys(ASSUMPTIONS, True)


def stock_xml(*, closing=False, quantity="10", closing_value="900.00", mutation=None):
    root = ET.fromstring(eod_xml(closing=closing))
    collection = root.find(".//{MyBroker}rn_Collection")
    for child in list(collection):
        collection.remove(child)
    # Empty Money must reconcile internally. A typed PDF dividend is separate
    # evidence; these source controls do not certify whole-account cash coverage.
    root.find(".//{MyBroker}Details[@active_name='RUB']").set("real_rest", "1000.00")
    for row in root.findall(".//{MyBroker}Details[@ISIN1]"):
        if row.get("ISIN1") == ISIN and closing:
            row.set("real_rest", quantity)
            row.set("forward_rest", quantity)
            row.set("real_volume", closing_value)
    if mutation:
        mutation(root)
    return ET.tostring(root, encoding="utf-8")


def setup_stock(
    database, *, quantity="10", closing_value="900.00", dividend="150,00", closing_mutation=None
):
    with database.session_factory() as session:
        bond = create_instrument(
            session, name="Synthetic bond", instrument_type="bond", isin="RU000A000001"
        )
        opening = create_reporting_month(session, year=2030, month=1, snapshot_date=A)
        closing = create_reporting_month(session, year=2030, month=2, snapshot_date=B)
        bond_id, opening_id, closing_id = bond.id, opening.id, closing.id
    client = TestClient(create_app(database))
    for is_closing, month, filename, request_id in (
        (False, opening_id, FILENAME, "what-if-open"),
        (True, closing_id, FEB_FILE, "what-if-close"),
    ):
        xml = stock_xml(
            closing=is_closing,
            quantity=quantity,
            closing_value=closing_value,
            mutation=closing_mutation if is_closing else None,
        )
        scope = {"account_id": 1, "reporting_month_id": month}
        plan = _broker_month_preview(client, scope, xml, filename=filename)
        response = _broker_month_apply(
            client, scope, plan, xml, filename=filename, request_id=request_id
        )
        assert response.status_code == 200, response.text
    if dividend is not None:
        pdf = build_income_report_pdf(
            [
                {
                    "isin": ISIN,
                    "payment_kind": "выплата дивидендов",
                    "record_date": "15.02.2030",
                    "payment_date": "20.02.2030",
                    "quantity": "10",
                    "per_unit": format(Decimal(dividend.replace(",", ".")) / 10, "f").replace(
                        ".", ","
                    ),
                    "gross": dividend,
                    "net": dividend,
                    "tax": "—",
                    "tax_rate": "—",
                }
            ]
        )
        with database.session_factory() as session:
            row = pdf_preview(session, pdf, 1).rows[0]
            assert pdf_apply(session, pdf, 1, (selection_from_row(row),)).success
    with database.session_factory() as session:
        stock = session.scalar(select(Instrument).where(Instrument.isin == ISIN))
        return client, stock.id, bond_id


def read(session, stock, chosen=None):
    return instrument_what_if(
        session, 1, stock, A, B, CHOSEN if chosen is None else chosen, "test-865"
    )


def assert_null(result):
    assert all(
        result["hypothetical_result"][k] is None
        for k in ("conditional_result", "conditional_period_fraction", "conditional_period_percent")
    )
    assert result["actual_instrument_return"] is None
    assert result["dependency_fingerprint"] is None
    assert result["whole_period_completeness"] == "unknown"


def test_source_backed_stock_api_exact_50_and_5_no_dml(database):
    client, stock, _ = setup_stock(database)
    writes = []

    def inspect(conn, cursor, statement, parameters, context, many):
        if statement.lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE", "REPLACE"}:
            writes.append(statement)

    event.listen(database.engine, "before_cursor_execute", inspect)
    try:
        with database.session_factory() as session:
            before = sqlite_blob(database)
            result = read(session, stock)
            assert result["hard_blockers"] == []
            assert result["hypothetical_result"]["conditional_result"] == "50.00"
            assert result["hypothetical_result"]["conditional_period_fraction"] == "0.05"
            assert result["hypothetical_result"]["conditional_period_percent"] == "5"
            assert result["accepted_known"]["payouts"]["events"][0]["tax"] is None
            assert result["accepted_known"]["trades"]["dependency_fingerprint"] is None
            assert sqlite_blob(database) == before
        response = client.get(
            f"/api/instruments/{stock}/conditional-return",
            params={
                "account_id": 1,
                "t0": str(A),
                "t1": str(B),
                "request_nonce": "test-865",
                **CHOSEN,
            },
        )
        assert response.status_code == 200, response.text
        assert response.json() == result
        assert response.headers["cache-control"] == "no-store"
        assert writes == []
    finally:
        event.remove(database.engine, "before_cursor_execute", inspect)


@pytest.mark.parametrize("omitted", [None, *ASSUMPTIONS])
def test_each_assumption_required_never_defaulted(database, omitted):
    client, stock, _ = setup_stock(database)
    chosen = {} if omitted is None else {**CHOSEN, omitted: False}
    with database.session_factory() as session:
        result = read(session, stock, chosen)
        assert_null(result)
        assert result["missing_assumptions"]
    if omitted is None:
        response = client.get(
            f"/api/instruments/{stock}/conditional-return",
            params={"account_id": 1, "t0": str(A), "t1": str(B), "request_nonce": "unselected"},
        )
        assert response.status_code == 200
        assert_null(response.json())


@pytest.mark.parametrize(
    "closing,dividend,money,fraction,percent",
    [
        ("800.00", "150,00", "-50.00", "-0.05", "-5"),
        ("900.01", "150,02", "50.03", "0.05003", "5.003"),
        ("900.00", "200,00", "100.00", "0.1", "10"),
    ],
)
def test_negative_and_exact_kopecks(database, closing, dividend, money, fraction, percent):
    _, stock, _ = setup_stock(database, closing_value=closing, dividend=dividend)
    with database.session_factory() as session:
        result = read(session, stock)
        assert result["hard_blockers"] == []
        assert [
            result["hypothetical_result"][k]
            for k in (
                "conditional_result",
                "conditional_period_fraction",
                "conditional_period_percent",
            )
        ] == [money, fraction, percent]


@pytest.mark.parametrize("basis", ["unknown", "included", "excluded"])
def test_every_bond_is_blocked_even_forced_included(database, basis):
    _, _, bond = setup_stock(database)
    with database.session_factory() as session:
        for row in session.scalars(
            select(PositionSnapshot).where(PositionSnapshot.instrument_id == bond)
        ):
            row.bond_nkd_basis = basis
        session.commit()
        result = read(session, bond)
        assert_null(result)
        assert "bond_dirty_basis_source_unproven" in result["hard_blockers"]


@pytest.mark.parametrize("quantity", ["9", "0"])
def test_changed_or_zero_units_block(database, quantity):
    _, stock, _ = setup_stock(
        database, quantity=quantity, closing_value="0.00" if quantity == "0" else "900.00"
    )
    with database.session_factory() as session:
        result = read(session, stock)
        assert_null(result)
        assert result["hard_blockers"]


def test_missing_dividend_is_unknown(database):
    _, stock, _ = setup_stock(database, dividend=None)
    with database.session_factory() as session:
        result = read(session, stock)
        assert_null(result)
        assert "proven_net_dividend_required" in result["hard_blockers"]


@pytest.mark.parametrize("mutation", ["syntax", "money", "native_buy", "pending", "forward"])
def test_original_contradictions_cannot_be_assumed_away(database, mutation):
    def change(root):
        if mutation == "syntax":
            ET.SubElement(root.find("{MyBroker}Trades/{MyBroker}Report"), "{MyBroker}Details")
        elif mutation == "money":
            original = ET.fromstring(eod_xml(closing=True))
            root.find(".//{MyBroker}rn_Collection").append(original.find(".//{MyBroker}rn"))
        elif mutation in {"native_buy", "pending"}:
            from test_statement_import_mybroker import fixture

            pending = mutation == "pending"
            original = ET.fromstring(fixture(pending=pending))
            trade = original.find(
                f".//{{MyBroker}}{'Details2[@trade_no1]' if pending else 'Details[@trade_no]'}"
            )
            trade.set("db_time2" if pending else "db_time", "15.02.2030 10:00:00")
            trade.set("save_settlement_date3" if pending else "save_settlement_date", "01.03.2030")
            trade.set(
                "save_depo_settlement_date3" if pending else "save_depo_settlement_date",
                "01.03.2030",
            )
            report = root.find("{MyBroker}Trades/{MyBroker}Report")
            name = "Tablix3" if pending else "Tablix2"
            table = report.find("{MyBroker}" + name)
            if table is None:
                table = ET.SubElement(report, "{MyBroker}" + name)
            ET.SubElement(
                table, "{MyBroker}" + ("Details2_Collection" if pending else "Details_Collection")
            ).append(trade)
        else:
            root.find(f".//{{MyBroker}}Details[@ISIN1='{ISIN}']").set("forward_rest", "11")

    _, stock, _ = setup_stock(database)
    with database.session_factory() as session:
        if mutation in {"forward", "pending"}:
            # Adversarial original drift, no production writer is changed.
            source = session.scalar(select(MyBrokerImport).where(MyBrokerImport.covered_to == B))
            doc = json.loads(source.normalized_json)
            if mutation == "forward":
                next(p for p in doc["positions"] if p["isin"] == ISIN)["forward_quantity"] = "11"
            else:
                from hermes_finance.statement_import.mybroker import parse_mybroker

                doc["trades"] = parse_mybroker(stock_xml(closing=True, mutation=change), FEB_FILE)[
                    "trades"
                ]
            session.execute(
                text("UPDATE mybroker_imports SET normalized_json=:doc WHERE id=:id"),
                {"doc": json.dumps(doc), "id": source.id},
            )
            session.commit()
        else:
            # A later S1-only original must be inspected even without accepted S2 trades.
            accept_source(session, stock_xml(closing=True, mutation=change), FEB_FILE)
        result = read(session, stock)
        assert_null(result)
        assert result["hard_blockers"]


def test_revoke_and_source_aba_recomputes_without_reusable_certification(database):
    _, stock, _ = setup_stock(database)
    with database.session_factory() as session:
        assert read(session, stock)["hypothetical_result"]["conditional_result"] == "50.00"
        mapping = session.scalar(
            select(BrokerIdentityMapping).where(
                BrokerIdentityMapping.subject_kind == "instrument",
                BrokerIdentityMapping.hermes_instrument_id == stock,
            )
        )
        revoke_mapping(session, mapping.id)
        assert_null(read(session, stock))


def test_observed_in_kind_and_principal_never_waived(database):
    _, stock, _ = setup_stock(database)
    with database.session_factory() as session:
        month = session.scalar(select(ReportingMonth).where(ReportingMonth.month == 2))
        session.add(
            InKindMovement(
                reporting_month_id=month.id,
                event_date=date(2030, 2, 10),
                destination_account_id=1,
                movement_kind="external_in",
                instrument_id=stock,
                quantity=Decimal(1),
                provenance_kind="owner_attestation",
            )
        )
        session.commit()
        result = read(session, stock)
        assert_null(result)
        assert "observed_in_kind_movement" in result["hard_blockers"]


def test_readers_share_one_snapshot_and_next_request_observes_late_movement(database, monkeypatch):
    import hermes_finance.services.instrument_what_if as service

    _, stock, _ = setup_stock(database)
    original = service.instrument_eod_observations
    with database.engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA journal_mode=WAL").scalar() == "wal"
    inserted = False

    def interleaved(session, *args):
        nonlocal inserted
        eod = original(session, *args)
        assert session.connection().exec_driver_sql("PRAGMA query_only").scalar() == 1
        if not inserted:
            inserted = True
            with database.session_factory() as writer:
                month = writer.scalar(select(ReportingMonth).where(ReportingMonth.month == 2))
                writer.add(
                    InKindMovement(
                        reporting_month_id=month.id,
                        event_date=date(2030, 2, 10),
                        destination_account_id=1,
                        movement_kind="external_in",
                        instrument_id=stock,
                        quantity=Decimal(1),
                        provenance_kind="owner_attestation",
                    )
                )
                writer.commit()
        return eod

    monkeypatch.setattr(service, "instrument_eod_observations", interleaved)
    with database.session_factory() as session:
        first = read(session, stock)
        assert first["hypothetical_result"]["conditional_result"] == "50.00"
        second = read(session, stock)
        assert_null(second)
        assert "observed_in_kind_movement" in second["hard_blockers"]


def test_closed_month_read_is_unchanged_and_manual_unproven_payout_blocks(database):
    from hermes_finance.persistence import InvestmentCashFlow

    _, stock, _ = setup_stock(database)
    with database.session_factory() as session:
        month = session.scalar(select(ReportingMonth).where(ReportingMonth.month == 2))
        session.execute(
            text("UPDATE reporting_months SET status='closed' WHERE id=:id"), {"id": month.id}
        )
        session.commit()
        before = sqlite_blob(database)
        assert read(session, stock)["hypothetical_result"]["conditional_result"] == "50.00"
        assert sqlite_blob(database) == before
        # Synthetic damaged canonical cash fact, never a production writer change.
        flow = session.scalar(select(InvestmentCashFlow))
        session.execute(
            text(
                "UPDATE investment_cash_flows SET net_amount_kopecks=net_amount_kopecks+1 WHERE id=:id"
            ),
            {"id": flow.id},
        )
        session.commit()
        result = read(session, stock)
        assert_null(result)
        assert "typed_statement_conflict" in result["hard_blockers"]


@pytest.mark.parametrize(
    "case",
    [
        "currency",
        "zero_value",
        "missing_endpoint",
        "account_retired",
        "source_date",
        "calendar_gap",
    ],
)
def test_scope_value_source_and_calendar_fail_closed(database, case):
    _, stock, _ = setup_stock(database)
    with database.session_factory() as session:
        if case == "currency":
            session.get(Instrument, stock).currency = "USD"
        elif case == "account_retired":
            from hermes_finance.persistence import Account

            session.get(Account, 1).status = "closed"
        elif case in {"zero_value", "missing_endpoint"}:
            row = session.scalar(
                select(PositionSnapshot).where(
                    PositionSnapshot.instrument_id == stock, PositionSnapshot.price_date == A
                )
            )
            if case == "zero_value":
                row.market_value_kopecks = 0
            else:
                row.price_date = date(2030, 1, 30)
        else:
            # Corrupted source interval is not repaired from endpoint values.
            source = session.scalar(select(MyBrokerImport).where(MyBrokerImport.covered_to == B))
            session.execute(
                text("UPDATE mybroker_imports SET covered_from=:start WHERE id=:id"),
                {
                    "start": "2030-02-03" if case == "calendar_gap" else "2030-02-02",
                    "id": source.id,
                },
            )
        session.commit()
        assert_null(read(session, stock))


@pytest.mark.parametrize("part", ["method", "payout_scope", "boundary_date", "trade_fingerprint"])
def test_reader_binding_is_checked_before_any_number(database, monkeypatch, part):
    import hermes_finance.services.instrument_what_if as service

    _, stock, _ = setup_stock(database)
    original = (
        service.known_instrument_trades
        if part == "trade_fingerprint"
        else service.instrument_eod_observations
    )

    def forged(*args):
        data = original(*args)
        if part == "method":
            data["version"] = 999
        elif part == "payout_scope":
            data["known_payouts"]["account"]["id"] = 99
        elif part == "boundary_date":
            data["opening"]["date"] = "2029-12-31"
        else:
            data["dependency_fingerprint"] = "forged-full-inventory-certification"
        return data

    monkeypatch.setattr(
        service,
        "known_instrument_trades" if part == "trade_fingerprint" else "instrument_eod_observations",
        forged,
    )
    with database.session_factory() as session:
        result = read(session, stock)
        assert_null(result)
        assert "reader_context_mismatch" in result["hard_blockers"]


@pytest.mark.parametrize("kind", ["opening_cash", "opening_quantity"])
def test_late_s1_original_derived_controls_cannot_be_assumed_away(database, kind):
    _, stock, _ = setup_stock(database)
    with database.session_factory() as session:
        assert read(session, stock)["hypothetical_result"]["conditional_result"] == "50.00"

        def change(root):
            if kind == "opening_cash":
                root.find(".//{MyBroker}Details[@active_name='RUB']").set("income_rest", "900.00")
            else:
                root.find(f".//{{MyBroker}}Details[@ISIN1='{ISIN}']").set("income_rest", "9")

        accept_source(session, stock_xml(closing=True, mutation=change), FEB_FILE)
        result = read(session, stock)
        assert_null(result)
        expected = (
            "cash_control_mismatch" if kind == "opening_cash" else "quantity_control_mismatch"
        )
        assert expected in result["hard_blockers"]
