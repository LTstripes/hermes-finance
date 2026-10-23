"""Synthetic source-intake-bound conditional result; never actual economics."""

import copy
import json
from xml.etree import ElementTree as ET

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select, text
from test_instrument_eod_observations_service import FEB_FILE, eod_xml
from test_instrument_what_if_service import CHOSEN, assert_null, setup_stock, stock_xml
from test_statement_import_apply import sqlite_blob
from test_statement_import_broker_statement_provisional import provisional_xml
from test_statement_import_mybroker import ACCOUNT, ISIN
from test_statement_import_mybroker import database as database

from hermes_finance.main import create_app
from hermes_finance.persistence import Account, Instrument, InvestmentCashFlow, ReportingMonth
from hermes_finance.services import source_intake
from hermes_finance.services.accounts import create_account
from hermes_finance.services.broker_identity_mappings import confirm_mapping
from hermes_finance.services.source_intake_result import (
    ASSUMPTIONS,
    source_intake_instrument_result,
)
from hermes_finance.statement_import.mybroker import PROVIDER, parse_mybroker

BASE = "/api/broker-months/intakes"
BOND = "RU000A000001"


def closing_month_id(database):
    with database.session_factory() as session:
        return session.scalar(select(ReportingMonth.id).where(ReportingMonth.month == 2))


def save_intake(
    client,
    xml,
    *,
    account_id=1,
    month_id=None,
    request_id="result-save",
    filename=FEB_FILE,
):
    intent = {
        "account_id": account_id,
        "reporting_month_id": month_id,
        "request_id": request_id,
    }
    response = client.post(
        BASE,
        files={"file": (filename, xml, "application/xml")},
        data={"intent": json.dumps(intent)},
    )
    assert response.status_code == 200, response.text
    ack = response.json()
    response = client.get(f"{BASE}/{ack['intake_id']}")
    assert response.status_code == 200, response.text
    return response.json()


def setup(
    database,
    *,
    save=True,
    quantity="10",
    closing_value="900.00",
    dividend="150,00",
    closing_mutation=None,
):
    client, stock, bond = setup_stock(
        database,
        quantity=quantity,
        closing_value=closing_value,
        dividend=dividend,
        closing_mutation=closing_mutation,
    )
    view = None
    if save:
        view = save_intake(
            client,
            stock_xml(
                closing=True,
                quantity=quantity,
                closing_value=closing_value,
                mutation=closing_mutation,
            ),
            month_id=closing_month_id(database),
        )
    return client, stock, bond, view


def read(session, view, isin=ISIN, chosen=None):
    return source_intake_instrument_result(
        session, view["id"], isin, CHOSEN if chosen is None else chosen, "test-891"
    )


def api(client, view, isin=ISIN, chosen=None, nonce="test-891"):
    params = {"isin": isin, "request_nonce": nonce, **(CHOSEN if chosen is None else chosen)}
    return client.get(f"{BASE}/{view['id']}/instrument-result", params=params)


def link_intake(client, view, xml, request_id="result-link"):
    requested = {
        "expected_head_seq": view["head_seq"],
        "account_id": view["state"]["account_id"],
        "reporting_month_id": view["state"]["reporting_month_id"],
        "default_enabled": view["state"]["default_enabled"],
        "account_currency": view["state"]["account_currency"],
        "overrides": [{"isin": k, "currency": v} for k, v in view["state"]["overrides"].items()],
        "instrument_decisions": view["state"]["instrument_decisions"],
        "deferred_isins": view["state"]["deferred_isins"],
        "finance_request_id": "what-if-close",
    }
    files = {"file": (FEB_FILE, xml, "application/xml")}
    plan = client.post(
        f"{BASE}/{view['id']}/review-preview", files=files, data={"intent": json.dumps(requested)}
    )
    assert plan.status_code == 200, plan.text
    confirmation = client.post(
        f"{BASE}/{view['id']}/finance-link",
        files=files,
        data={
            "confirmation": json.dumps(
                {
                    **requested,
                    "request_id": request_id,
                    "confirmation_digest": plan.json()["confirmation_digest"],
                }
            )
        },
    )
    assert confirmation.status_code == 200, confirmation.text
    return client.get(f"{BASE}/{view['id']}").json()


def test_source_intake_stock_exact_result_separate_axes_and_no_dml(database):
    client, stock, _, view = setup(database)
    writes = []

    def inspect(conn, cursor, statement, parameters, context, many):
        if statement.lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE", "REPLACE"}:
            writes.append(statement)

    event.listen(database.engine, "before_cursor_execute", inspect)
    try:
        with database.session_factory() as session:
            before = sqlite_blob(database)
            result = read(session, view)
            assert result["hard_blockers"] == []
            assert result["hypothetical_result"]["conditional_result"] == "50.00"
            assert result["hypothetical_result"]["conditional_period_fraction"] == "0.05"
            assert result["hypothetical_result"]["conditional_period_percent"] == "5"
            assert result["observed"]["availability"] == "available"
            assert result["observed"]["quantity"] == "10"
            assert result["observed"]["beginning_value"] == "1000.00"
            assert result["observed"]["ending_value"] == "900.00"
            assert result["observed"]["value_change"] == "-100.00"
            assert result["observed"]["value_change_fraction"] == "-0.1"
            assert result["observed"]["value_change_percent"] == "-10"
            assert result["observed"]["bond_nkd_basis"] == "not_applicable"
            assert result["observed"]["source_row"]["ordinal"] == 0
            assert result["known"]["net_distributions"] == "150.00"
            assert result["known"]["payouts"]["events"][0]["tax"] is None
            assert result["known"]["trades"]["dependency_fingerprint"] is None
            assert result["known"]["confirmed_cost_legs"] == []
            assert result["intake"]["finance_link"] == "absent"
            assert source_intake.PENDING in result["intake"]["exceptions"]
            assert result["account"]["id"] == 1
            assert result["instrument"]["hermes_id"] == stock
            assert result["actual_instrument_return"] is None
            assert result["dependency_fingerprint"] is None
            assert sqlite_blob(database) == before
        response = api(client, view)
        assert response.status_code == 200, response.text
        assert response.json() == result
        assert response.headers["cache-control"] == "no-store"
        assert writes == []
    finally:
        event.remove(database.engine, "before_cursor_execute", inspect)


@pytest.mark.parametrize(
    "month,statement_filename,actual_start,actual_end",
    [
        (2, "Брокерский 1234567 (01.01.30-31.03.30).xml", "2030-01-01", "2030-03-31"),
        (1, "Брокерский 1234567 (16.01.30-31.01.30).xml", "2030-01-16", "2030-01-31"),
    ],
)
def test_renamed_long_and_partial_intake_periods_with_coupon_are_withheld(
    database, month, statement_filename, actual_start, actual_end
):
    raw = (
        provisional_xml(
            candidate_count=0,
            beginning_quantity="9",
            extra_money=(("Купон", f"Coupon {ISIN}", "7"),),
        )
        .decode()
        .replace(".04.2030", f".{month:02d}.2030")
        .replace("2030-04-", f"2030-{month:02d}-")
        .replace(f"15.{month:02d}.2030", f"17.{month:02d}.2030")
        .encode()
    )
    actual = parse_mybroker(raw, statement_filename)
    assert (actual["covered_from"], actual["covered_to"]) == (actual_start, actual_end)
    assert "period_inferred_from_content" not in actual.get("warnings", [])
    client = TestClient(create_app(database))
    view = save_intake(client, raw, filename="renamed.xml", account_id=None)
    assert view["document"]["warnings"] == ["period_inferred_from_content"]
    assert view["document"]["money"]  # A coupon must not restore the result.
    before = sqlite_blob(database)
    with database.session_factory() as session:
        result = read(session, view)
    assert result["observed"]["availability"] == "unavailable"
    assert "source_period_inferred" in result["observed"]["reason_codes"]
    assert "source_period_inferred" in result["hard_blockers"]
    for field in (
        "beginning_value",
        "ending_value",
        "value_change",
        "value_change_fraction",
        "value_change_percent",
    ):
        assert result["observed"][field] is None
    assert result["known"]["payouts"] is result["known"]["trades"] is None
    assert_null(result)
    response = api(client, view)
    assert response.status_code == 200, response.text
    assert response.json() == result
    assert sqlite_blob(database) == before


def test_inferred_period_blocks_otherwise_available_intake_return(database, monkeypatch):
    client, _, _, view = setup(database)
    with database.session_factory() as session:
        assert read(session, view)["hypothetical_result"]["conditional_result"] == "50.00"
    real_read = source_intake.read_intake

    def inferred_period(session, intake_id):
        result = real_read(session, intake_id)
        result["document"]["warnings"] = ["period_inferred_from_content"]
        return result

    monkeypatch.setattr(source_intake, "read_intake", inferred_period)
    before = sqlite_blob(database)
    with database.session_factory() as session:
        result = read(session, view)
    assert result["hard_blockers"] == ["source_period_inferred"]
    assert result["observed"]["availability"] == "unavailable"
    assert result["observed"]["value_change"] is None
    assert result["observed"]["value_change_percent"] is None
    assert_null(result)
    response = api(client, view)
    assert response.status_code == 200, response.text
    assert response.json() == result
    assert sqlite_blob(database) == before


@pytest.mark.parametrize("mismatch", [False, True])
def test_valid_filename_intake_period_retains_observed_change_with_coupon(database, mismatch):
    raw = provisional_xml(
        candidate_count=0,
        beginning_quantity="9",
        extra_money=(("Купон", f"Coupon {ISIN}", "7"),),
    )
    if mismatch:
        raw = raw.replace(b".04.2030", b".05.2030").replace(b"2030-04-", b"2030-05-")
    client = TestClient(create_app(database))
    view = save_intake(
        client,
        raw,
        account_id=None,
        filename="Брокерский 1234567 (01.04.30-30.04.30).xml",
    )
    assert view["document"].get("warnings", []) == (
        ["filename_period_mismatch"] if mismatch else []
    )
    before = sqlite_blob(database)
    with database.session_factory() as session:
        result = read(session, view)
    assert (result["t0"], result["t1"]) == ("2030-03-31", "2030-04-30")
    assert result["observed"]["availability"] == "available"
    assert result["observed"]["beginning_value"] == "9000.00"
    assert result["observed"]["ending_value"] == "10211.00"
    assert result["observed"]["value_change"] == "1211.00"
    assert result["observed"]["value_change_percent"] is not None
    assert "source_period_inferred" not in result["hard_blockers"]
    response = api(client, view)
    assert response.status_code == 200, response.text
    assert response.json() == result
    assert sqlite_blob(database) == before


def test_linked_intake_is_bound_provenance_not_a_new_ledger(database):
    client, stock, _, view = setup(database)
    linked = link_intake(client, view, stock_xml(closing=True))
    assert linked["finance_link"]["request_id"] == "what-if-close"
    assert source_intake.PENDING not in linked["exceptions"]
    with database.session_factory() as session:
        result = read(session, linked)
        assert result["intake"]["finance_link"] == "present"
        assert result["hypothetical_result"]["conditional_result"] == "50.00"


@pytest.mark.parametrize("omitted", [None, *ASSUMPTIONS])
def test_each_assumption_required_never_defaulted(database, omitted):
    client, _, _, view = setup(database)
    chosen = {} if omitted is None else {**CHOSEN, omitted: False}
    with database.session_factory() as session:
        result = read(session, view, chosen=chosen)
        assert_null(result)
        assert result["missing_assumptions"]
        assert result["observed"]["value_change"] == "-100.00"
    if omitted is None:
        response = api(client, view, chosen={})
        assert response.status_code == 200, response.text
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
    _, _, _, view = setup(database, closing_value=closing, dividend=dividend)
    with database.session_factory() as session:
        result = read(session, view)
        assert result["hard_blockers"] == []
        assert [
            result["hypothetical_result"][key]
            for key in (
                "conditional_result",
                "conditional_period_fraction",
                "conditional_period_percent",
            )
        ] == [money, fraction, percent]


def test_bond_is_blocked_with_unknown_nkd_basis_and_null_result(database):
    client, _, _, view = setup(database)
    with database.session_factory() as session:
        result = read(session, view, isin=BOND)
        assert_null(result)
        assert "bond_dirty_basis_source_unproven" in result["hard_blockers"]
        assert result["observed"]["bond_nkd_basis"] == "unknown"
        assert result["known"]["payouts"]["event_count"] == 0
        assert result["known"]["net_distributions"] is None
    response = api(client, view, isin=BOND)
    assert response.status_code == 200, response.text
    assert response.json()["hypothetical_result"]["conditional_result"] is None


def test_changed_quantity_blocks_total_and_keeps_observed_facts(database):
    _, _, _, view = setup(database, quantity="9")
    with database.session_factory() as session:
        result = read(session, view)
        assert_null(result)
        assert "quantity_changed_not_profit" in result["observed"]["reason_codes"]
        assert "changing_quantity_result_unavailable" in result["hard_blockers"]
        assert "quantity_control_mismatch" in result["hard_blockers"]
        assert result["observed"]["value_change"] == "-100.00"
        assert result["observed"]["value_change_percent"] == "-10"


def test_scoped_money_rows_block_without_double_counting(database):
    client, _, _, _ = setup(database, save=False)

    def add_money(root):
        original = ET.fromstring(eod_xml(closing=True))
        root.find(".//{MyBroker}rn_Collection").append(original.find(".//{MyBroker}rn"))

    view = save_intake(
        client,
        stock_xml(closing=True, mutation=add_money),
        month_id=closing_month_id(database),
        request_id="result-money",
    )
    with database.session_factory() as session:
        result = read(session, view)
        assert_null(result)
        assert "money_economic_effect_unproven" in result["hard_blockers"]
        assert "cash_control_mismatch" in result["hard_blockers"]
        # The supported dividend stays visible once; it is never added to a total
        # that an unattributed Money row could double.
        assert result["known"]["net_distributions"] == "150.00"


def test_missing_dividend_is_unknown_never_zero(database):
    _, _, _, view = setup(database, dividend=None)
    with database.session_factory() as session:
        result = read(session, view)
        assert_null(result)
        assert "proven_net_dividend_required" in result["hard_blockers"]
        assert result["known"]["payouts"]["event_count"] == 0
        assert result["known"]["net_distributions"] is None
        assert result["observed"]["value_change"] == "-100.00"


def test_conflicting_payout_evidence_blocks_without_fake_net(database):
    _, _, _, view = setup(database)
    with database.session_factory() as session:
        flow = session.scalar(select(InvestmentCashFlow))
        session.execute(
            text(
                "UPDATE investment_cash_flows SET net_amount_kopecks=net_amount_kopecks+1 WHERE id=:id"
            ),
            {"id": flow.id},
        )
        session.commit()
        result = read(session, view)
        assert_null(result)
        assert "typed_statement_conflict" in result["hard_blockers"]
        assert result["known"]["net_distributions"] is None


def test_unbound_intake_is_explicit_and_keeps_source_observed_facts(database):
    client, _, _, _ = setup(database, save=False)
    view = save_intake(
        client,
        stock_xml(closing=True, closing_value="850.00"),
        account_id=None,
        month_id=None,
        request_id="result-unbound",
    )
    with database.session_factory() as session:
        result = read(session, view)
        assert_null(result)
        assert "source_intake_not_bound" in result["hard_blockers"]
        assert result["account"] is None
        assert result["observed"]["availability"] == "available"
        assert result["observed"]["value_change"] == "-150.00"


def test_overlapping_same_account_original_must_agree(database):
    client, _, _, view = setup(database)
    save_intake(
        client,
        stock_xml(closing=True, closing_value="950.00"),
        month_id=closing_month_id(database),
        request_id="result-overlap",
    )
    with database.session_factory() as session:
        result = read(session, view)
        assert_null(result)
        assert "ambiguous_overlapping_originals" in result["hard_blockers"]


def test_overlapping_identical_instrument_economics_do_not_block(database):
    client, _, _, view = setup(database)

    def move_cash(root):
        row = root.find(".//{MyBroker}Details[@active_name='RUB']")
        row.set("income_rest", "1234.00")
        row.set("real_rest", "1234.00")

    save_intake(
        client,
        stock_xml(closing=True, mutation=move_cash),
        month_id=closing_month_id(database),
        request_id="result-agree",
    )
    with database.session_factory() as session:
        result = read(session, view)
        assert "ambiguous_overlapping_originals" not in result["hard_blockers"]
        assert result["hypothetical_result"]["conditional_result"] == "50.00"


def test_inactive_account_blocks_result(database):
    _, _, _, view = setup(database)
    with database.session_factory() as session:
        session.get(Account, 1).status = "closed"
        session.commit()
        result = read(session, view)
        assert_null(result)
        assert "account_inactive" in result["hard_blockers"]


def test_replay_is_stable_and_new_journal_head_is_visible(database):
    client, _, _, view = setup(database)
    with database.session_factory() as session:
        first = read(session, view)
        second = read(session, view)
        assert first == second
        assert first["request_nonce"] == "test-891"
    requested = {
        "expected_head_seq": view["head_seq"],
        "account_id": view["state"]["account_id"],
        "reporting_month_id": view["state"]["reporting_month_id"],
        "default_enabled": view["state"]["default_enabled"],
        "account_currency": view["state"]["account_currency"],
        "overrides": [],
        "instrument_decisions": view["state"]["instrument_decisions"],
        "deferred_isins": view["state"]["deferred_isins"],
    }
    files = {"file": (FEB_FILE, stock_xml(closing=True), "application/xml")}
    plan = client.post(
        f"{BASE}/{view['id']}/review-preview", files=files, data={"intent": json.dumps(requested)}
    )
    assert plan.status_code == 200, plan.text
    decided = client.post(
        f"{BASE}/{view['id']}/decisions",
        files=files,
        data={
            "confirmation": json.dumps(
                {
                    **requested,
                    "request_id": "result-decision",
                    "confirmation_digest": plan.json()["confirmation_digest"],
                }
            )
        },
    )
    assert decided.status_code == 200, decided.text
    with database.session_factory() as session:
        refreshed = read(session, view)
        assert refreshed["intake"]["head_seq"] > view["head_seq"]
        assert refreshed["hypothetical_result"]["conditional_result"] == "50.00"


def test_api_contract_errors_and_input_validation(database):
    client, _, _, view = setup(database)
    missing = client.get(
        f"{BASE}/999999/instrument-result",
        params={"isin": ISIN, "request_nonce": "missing"},
    )
    assert missing.status_code == 404
    invalid = api(client, view, isin="not-an-isin")
    assert invalid.status_code == 422
    bad_nonce = client.get(
        f"{BASE}/{view['id']}/instrument-result",
        params={"isin": ISIN, "request_nonce": "spaces not allowed"},
    )
    assert bad_nonce.status_code == 422


def defer_identity(client, view, xml, isin, request_id="result-defer"):
    requested = {
        "expected_head_seq": view["head_seq"],
        "account_id": view["state"]["account_id"],
        "reporting_month_id": view["state"]["reporting_month_id"],
        "default_enabled": view["state"]["default_enabled"],
        "account_currency": view["state"]["account_currency"],
        "overrides": [],
        "instrument_decisions": view["state"]["instrument_decisions"],
        "deferred_isins": [isin],
    }
    files = {"file": (FEB_FILE, xml, "application/xml")}
    plan = client.post(
        f"{BASE}/{view['id']}/review-preview", files=files, data={"intent": json.dumps(requested)}
    )
    assert plan.status_code == 200, plan.text
    decided = client.post(
        f"{BASE}/{view['id']}/decisions",
        files=files,
        data={
            "confirmation": json.dumps(
                {
                    **requested,
                    "request_id": request_id,
                    "confirmation_digest": plan.json()["confirmation_digest"],
                }
            )
        },
    )
    assert decided.status_code == 200, decided.text
    return client.get(f"{BASE}/{view['id']}").json()


def test_deferred_identity_is_not_a_number(database):
    client, _, _, view = setup(database)
    deferred = defer_identity(client, view, stock_xml(closing=True), ISIN)
    assert "source_intake_identity_deferred" in deferred["exceptions"]
    with database.session_factory() as session:
        result = read(session, deferred)
        assert_null(result)
        assert "source_intake_identity_deferred" in result["hard_blockers"]


def duplicate_position(root):
    for row in root.findall(".//{MyBroker}Details[@ISIN1]"):
        if row.get("ISIN1") == ISIN:
            duplicate = copy.deepcopy(row)
            del duplicate.attrib["income_volume"]
            parent = next(p for p in root.iter() if row in list(p))
            parent.append(duplicate)


def test_duplicate_position_row_is_null_not_an_error(database):
    client, _, _, _ = setup(database, save=False)
    view = save_intake(
        client,
        stock_xml(closing=True, mutation=duplicate_position),
        month_id=closing_month_id(database),
        request_id="result-duplicate",
    )
    with database.session_factory() as session:
        result = read(session, view)
        assert_null(result)
        assert "source_fixed_holding_unproven" in result["hard_blockers"]
        assert "source_reader_unavailable" not in result["hard_blockers"]


def test_overlapping_malformed_original_does_not_break_the_clean_one(database):
    client, _, _, view = setup(database)
    save_intake(
        client,
        stock_xml(closing=True, mutation=duplicate_position),
        month_id=closing_month_id(database),
        request_id="result-malformed",
    )
    with database.session_factory() as session:
        result = read(session, view)
        assert_null(result)
        assert "ambiguous_overlapping_originals" in result["hard_blockers"]
        assert "source_reader_unavailable" not in result["hard_blockers"]


def add_trade(root):
    from test_statement_import_mybroker import fixture

    original = ET.fromstring(fixture(pending=False))
    trade = original.find(".//{MyBroker}Details[@trade_no]")
    trade.set("db_time", "15.02.2030 10:00:00")
    trade.set("save_settlement_date", "01.03.2030")
    trade.set("save_depo_settlement_date", "01.03.2030")
    report = root.find("{MyBroker}Trades/{MyBroker}Report")
    table = report.find("{MyBroker}Tablix2")
    if table is None:
        table = ET.SubElement(report, "{MyBroker}Tablix2")
    ET.SubElement(table, "{MyBroker}Details_Collection").append(trade)


def test_observed_trade_blocks_with_specific_reasons_not_a_reader_failure(database):
    client, _, _, _ = setup(database, save=False)
    view = save_intake(
        client,
        stock_xml(closing=True, mutation=add_trade),
        month_id=closing_month_id(database),
        request_id="result-trade",
    )
    with database.session_factory() as session:
        result = read(session, view)
        assert_null(result)
        assert "observed_native_movement_or_crossing" in result["hard_blockers"]
        assert "changing_quantity_result_unavailable" in result["hard_blockers"]
        assert "source_reader_unavailable" not in result["hard_blockers"]


def test_non_rub_catalogue_card_blocks(database):
    client, stock, _, view = setup(database)
    with database.session_factory() as session:
        session.get(Instrument, stock).currency = "USD"
        session.commit()
        result = read(session, view)
        assert_null(result)
        assert result["hard_blockers"]
    response = api(client, view)
    assert response.status_code == 200, response.text
    assert response.json()["hypothetical_result"]["conditional_result"] is None


def rename_native_account(root, alias):
    for node in root.iter():
        if node.get("acc_code") == ACCOUNT:
            node.set("acc_code", alias)


def test_unbound_overlapping_same_account_original_blocks_number(database):
    """RED on the parent: an unbound same-native-account overlap was skipped."""
    client, _, _, view = setup(database)
    save_intake(
        client,
        stock_xml(closing=True, closing_value="950.00"),
        account_id=None,
        month_id=None,
        request_id="result-unbound-overlap",
    )
    with database.session_factory() as session:
        result = read(session, view)
        assert_null(result)
        assert "ambiguous_overlapping_originals" in result["hard_blockers"]
        assert result["hypothetical_result"]["conditional_result"] is None
        assert result["hypothetical_result"]["conditional_period_fraction"] is None
        assert result["hypothetical_result"]["conditional_period_percent"] is None


def test_unrelated_unbound_original_does_not_block(database):
    client, _, _, view = setup(database)
    with database.session_factory() as session:
        other = create_account(session, name="Other synthetic account", account_type="brokerage")
        confirm_mapping(
            session,
            provider=PROVIDER,
            subject_kind="account",
            provider_identity="7654321",
            hermes_target_id=other.id,
        )
    save_intake(
        client,
        stock_xml(
            closing=True,
            closing_value="950.00",
            mutation=lambda root: rename_native_account(root, "7654321"),
        ),
        account_id=None,
        month_id=None,
        request_id="result-unrelated",
        filename=FEB_FILE.replace("1234567", "7654321"),
    )
    with database.session_factory() as session:
        result = read(session, view)
        assert "ambiguous_overlapping_originals" not in result["hard_blockers"]
        assert "overlapping_native_account_unproven" not in result["hard_blockers"]
        assert result["hypothetical_result"]["conditional_result"] == "50.00"


def test_unmapped_unbound_original_stays_unproven_not_irrelevant(database):
    client, _, _, view = setup(database)
    save_intake(
        client,
        stock_xml(
            closing=True,
            closing_value="950.00",
            mutation=lambda root: rename_native_account(root, "9999999"),
        ),
        account_id=None,
        month_id=None,
        request_id="result-unmapped",
        filename=FEB_FILE.replace("1234567", "9999999"),
    )
    with database.session_factory() as session:
        result = read(session, view)
        assert_null(result)
        assert "overlapping_native_account_unproven" in result["hard_blockers"]


def test_unbound_identical_same_account_re_report_corroborates_once(database):
    client, _, _, view = setup(database)

    def move_cash(root):
        row = root.find(".//{MyBroker}Details[@active_name='RUB']")
        row.set("income_rest", "1234.00")
        row.set("real_rest", "1234.00")

    save_intake(
        client,
        stock_xml(closing=True, mutation=move_cash),
        account_id=None,
        month_id=None,
        request_id="result-unbound-identical",
    )
    with database.session_factory() as session:
        result = read(session, view)
        assert result["hard_blockers"] == []
        assert result["hypothetical_result"]["conditional_result"] == "50.00"
        assert result["known"]["payouts"]["event_count"] == 1
        assert result["known"]["net_distributions"] == "150.00"
