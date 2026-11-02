"""Synthetic preparation, ambiguity and the existing guarded financial writer."""

from datetime import UTC, datetime
from xml.etree import ElementTree as ET

import pytest
from sqlalchemy import func, select
from test_statement_import_apply import apply as income_apply
from test_statement_import_apply import preview as income_preview
from test_statement_import_apply import selection_from_row
from test_statement_import_mybroker import FILENAME
from test_statement_import_mybroker import database as database
from test_statement_import_mybroker_endpoints import (
    _money_apply,
    _money_setup,
    money_batch_xml,
    money_coupon_pdf,
)
from test_statement_import_payout_reconciliation import database_bytes, dividend_setup, dividend_xml

from hermes_finance.domain.broker_money import MoneyIntentV2
from hermes_finance.persistence import (
    BrokerMoneyOccurrenceOwner,
    CashBalance,
    Instrument,
    InvestmentCashFlow,
    SecurityRegIsinMapping,
)
from hermes_finance.services.broker_money import apply_money, preview_money
from hermes_finance.services.broker_money_preparation import prepare_money
from hermes_finance.services.statement_import_apply import StatementApplyAction
from hermes_finance.statement_import.mybroker import MyBrokerError

REG = "4B02-09-99999-Z-001P"
COUPON = f'погашение купона {REG} (облигации АО "Synthetic bond") д.ф.15.01.30'


def coupon_xml(narrative=COUPON, amounts=("1000",)):
    root = ET.fromstring(money_batch_xml(coupons=amounts))
    for node in root.findall(".//{MyBroker}comment"):
        if "погашение купона" in node.get("comment", ""):
            node.set("comment", narrative)
    return ET.tostring(root, encoding="utf-8")


def setup_coupon(database, xml=None):
    client, xml, legacy, bond, _ = _money_setup(database, xml or coupon_xml())
    with database.session_factory() as session:
        instrument = session.get(Instrument, bond)
        session.add(
            SecurityRegIsinMapping(
                reg_number=REG,
                isin=instrument.isin,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        session.commit()
    intent = MoneyIntentV2.model_validate(
        {**legacy.model_dump(), "contract_version": "broker_money_v2"}
    )
    return client, xml, intent, bond


def review_prepared(session, prepared, originals, target=None):
    # Explicit synthetic review, never performed by production preparation.
    decisions = [
        d for d in prepared["intent"]["money_decisions"] if d["role"] in {"coupon", "dividend"}
    ]
    for decision in decisions:
        if target is not None:
            decision["investment_cash_flow_id"] = target
    intent = MoneyIntentV2.model_validate({**prepared["intent"], "money_decisions": decisions})
    plan = preview_money(session, intent, originals)
    for decision, proposed in zip(decisions, plan["decisions"], strict=True):
        common = {
            "reference": "synthetic-explicit-original-review",
            "review_context_digest": proposed["review_context_digest"],
            "complete_occurrence_set_is_one_event": True,
            "existing_target_is_same_payment": True,
        }
        if decision["role"] == "coupon":
            decision["coupon_claims"] = {
                **common,
                "actual_coupon_payment": True,
                "exact_row_instrument_link": True,
            }
        else:
            decision["dividend_claims"] = {
                **common,
                "independent_net_basis_reference": "synthetic-net-basis",
                "actual_ordinary_stock_dividend": True,
                "exact_row_stock_link": True,
                "posted_amount_is_final_net_credit": True,
                "withholding_is_embedded_not_additional_cash_leg": True,
            }
    return MoneyIntentV2.model_validate({**intent.model_dump(), "money_decisions": decisions})


@pytest.mark.parametrize("role", ["coupon", "dividend"])
def test_prepare_exact_income_zero_write_then_guarded_apply(database, role):
    if role == "coupon":
        client, xml, intent, instrument = setup_coupon(database)
    else:
        xml = dividend_xml(
            narrative='Дивиденды за 2029 год по акциям ПАО "Synthetic stock" (1-01-00000-A). (Удержан налог 130.00 руб.).'
        )
        client, intent, instrument, _ = dividend_setup(database, xml)
    originals = [(FILENAME, xml)]
    before = database_bytes(database)
    response = client.post(
        "/api/broker-months/money-prepare",
        files={"file": (FILENAME, xml, "application/xml")},
        data={"intent": intent.model_dump_json()},
    )
    assert response.status_code == 200, response.text
    prepared = response.json()
    assert not prepared["can_apply"]
    assert prepared["intent"]["money_decisions"], prepared["rows"]
    decision = next(d for d in prepared["intent"]["money_decisions"] if d["role"] == role)
    assert decision["instrument_id"] == instrument
    assert not decision.get("coupon_claims") and not decision.get("dividend_claims")
    assert all(row["requires_confirmation"] for row in prepared["rows"])
    assert database_bytes(database) == before
    with database.session_factory() as session:
        requested = review_prepared(session, prepared, originals)
        saved = _money_apply(session, requested, originals)
        assert saved["targets"][0]["effective"]
        flow = session.scalar(select(InvestmentCashFlow))
        assert flow.flow_type == role
        assert flow.net_amount_kopecks == 100000
        assert flow.tax_amount_kopecks is None
        assert flow.gross_amount_kopecks is None


@pytest.mark.parametrize(
    "narrative,expected",
    [
        (COUPON, "coupon"),
        (
            'Дивиденды за 2029 год по акциям ПАО "Synthetic stock" (1-01-00000-A). (Удержан налог 130.00 руб.).',
            "dividend",
        ),
        ("назначение не определено", "unknown"),
    ],
)
def test_same_operation_name_different_purpose_different_preparation(database, narrative, expected):
    _, xml, intent, _ = setup_coupon(database, coupon_xml(narrative))
    before = database_bytes(database)
    with database.session_factory() as session:
        prepared = prepare_money(session, intent, [(FILENAME, xml)])
    row = next(r for r in prepared["rows"] if r["occurrence"]["ordinal"] == 1)
    assert row["classification"] == expected
    if expected == "unknown":
        assert row["status"] == "needs_confirmation"
        assert "decision" not in row
    assert database_bytes(database) == before


@pytest.mark.parametrize("pdf_first", [False, True])
def test_prepared_coupon_xml_pdf_one_payment_in_both_orders(database, pdf_first):
    _, xml, intent, _ = setup_coupon(database)
    originals = [(FILENAME, xml)]
    pdf = money_coupon_pdf()
    with database.session_factory() as session:
        flow_id = None
        if pdf_first:
            row = income_preview(session, pdf, intent.account_id).rows[0]
            result = income_apply(session, pdf, intent.account_id, (selection_from_row(row),))
            assert result.success, result
            flow_id = result.items[0].investment_cash_flow_id
        prepared = prepare_money(session, intent, originals)
        if pdf_first:
            coupon = next(r for r in prepared["rows"] if r["classification"] == "coupon")
            assert coupon["existing_payout_candidate_ids"] == [flow_id]
            assert not prepared["can_apply"]  # Equal facts do not attest one event.
        requested = review_prepared(session, prepared, originals, target=flow_id)
        saved = _money_apply(session, requested, originals)
        flow_id = saved["targets"][0]["target_id"]
        if not pdf_first:
            row = income_preview(session, pdf, intent.account_id).rows[0]
            result = income_apply(
                session,
                pdf,
                intent.account_id,
                (
                    selection_from_row(
                        row,
                        action=StatementApplyAction.LINK_EXISTING,
                        existing_cash_flow_id=flow_id,
                        expected_candidate_ids=(flow_id,),
                    ),
                ),
            )
            assert result.success, result
        assert session.scalar(select(func.count()).select_from(InvestmentCashFlow)) == 1
        assert session.scalar(select(func.count()).select_from(BrokerMoneyOccurrenceOwner)) == 1
        assert session.get(InvestmentCashFlow, flow_id).net_amount_kopecks == 100000
    with database.session_factory() as fresh:
        from hermes_finance.services.broker_money import read_money

        assert read_money(fresh, "money-accepted")["targets"][0]["effective"]


@pytest.mark.parametrize("amounts", [("0",), ("-1000",), ("1000", "1000")])
def test_ambiguous_or_wrong_direction_never_prepares_income(database, amounts):
    _, xml, intent, _ = setup_coupon(database, coupon_xml(amounts=amounts))
    with database.session_factory() as session:
        result = prepare_money(session, intent, [(FILENAME, xml)])
    coupon_rows = [r for r in result["rows"] if r["occurrence"]["ordinal"] <= len(amounts)]
    assert all(r["status"] == "needs_confirmation" for r in coupon_rows)
    assert not any(d["role"] == "coupon" for d in result["intent"]["money_decisions"])
    assert not result["can_apply"]


def test_prepared_choice_cannot_bypass_changed_reconciliation(database):
    _, xml, intent, _ = setup_coupon(database)
    originals = [(FILENAME, xml)]
    with database.session_factory() as session:
        prepared = prepare_money(session, intent, originals)
        requested = review_prepared(session, prepared, originals)
        plan = preview_money(session, requested, originals)
        assert plan["can_apply"], plan["blockers"]
        session.scalar(select(CashBalance)).amount_kopecks += 1
        session.commit()
        before = database_bytes(database)
        with pytest.raises(MyBrokerError):
            apply_money(
                session,
                requested,
                originals,
                request_id="stale-prepared",
                confirmation_digest=plan["confirmation_digest"],
            )
        assert not preview_money(session, requested, originals)["can_apply"]
        assert session.scalar(select(func.count()).select_from(InvestmentCashFlow)) == 0
    assert database_bytes(database) == before


@pytest.mark.parametrize(
    "narrative,amount,expected",
    [
        ("с другого счета 7654321-000 внутри брокера", "1000", "internal_transfer"),
        ("с другого счета 7654321-000 внутри брокера", "-1000", "unknown"),
        ("с 7654321-000 на 9999999-000 внутри брокера", "1000", "unknown"),
    ],
)
def test_own_transfer_uses_participants_and_direction(database, narrative, amount, expected):
    from hermes_finance.services.accounts import create_account
    from hermes_finance.services.broker_identity_mappings import confirm_mapping
    from hermes_finance.statement_import.mybroker import PROVIDER

    _, xml, intent, _ = setup_coupon(database, coupon_xml(narrative, amounts=(amount,)))
    with database.session_factory() as session:
        other = create_account(session, name="Synthetic other account", account_type="brokerage")
        confirm_mapping(
            session,
            provider=PROVIDER,
            subject_kind="account",
            provider_identity="7654321-000",
            hermes_target_id=other.id,
        )
        prepared = prepare_money(session, intent, [(FILENAME, xml)])
        transfer = next(r for r in prepared["rows"] if r["occurrence"]["ordinal"] == 1)
        assert transfer["classification"] == expected
        assert transfer["status"] == "needs_confirmation"
        if expected == "internal_transfer":
            assert "explicit_transfer_link_required" in transfer["reason_codes"]
        assert not any(d["seed"]["ordinal"] == 1 for d in prepared["intent"]["money_decisions"])


@pytest.mark.parametrize(
    "failure", ["closed", "missing_original", "wrong_original", "manual_choice"]
)
def test_preparation_does_not_change_blocked_sources_or_manual_choices(database, failure):
    from hermes_finance.persistence import ReportingMonth

    _, xml, intent, _ = setup_coupon(database)
    originals = [(FILENAME, xml)]
    with database.session_factory() as session:
        if failure == "closed":
            session.get(ReportingMonth, intent.reporting_month_id).status = "closed"
            session.commit()
        elif failure == "missing_original":
            originals = []
        elif failure == "wrong_original":
            originals = [(FILENAME, xml + b" ")]
        else:
            intent = MoneyIntentV2.model_validate(
                {
                    **intent.model_dump(),
                    "money_decisions": [
                        {
                            "role": "coupon",
                            "seed": {"import_id": 1, "section": "money", "ordinal": 1},
                        }
                    ],
                }
            )
        before = database_bytes(database)
        if failure == "manual_choice":
            with pytest.raises(MyBrokerError, match="money_preparation_requires_empty_decisions"):
                prepare_money(session, intent, originals)
        else:
            prepared = prepare_money(session, intent, originals)
            assert not prepared["can_apply"]
            assert not prepared["intent"]["money_decisions"]
    assert database_bytes(database) == before
