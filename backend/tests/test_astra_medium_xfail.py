"""Strict synthetic regressions for remaining medium/low methodology audit findings.

Fixed findings run as ordinary regressions. Deferred findings retain strict
xfails; all fixtures and observations are synthetic.
"""

from datetime import date
from decimal import ROUND_DOWN, ROUND_UP, Decimal, localcontext
from xml.etree import ElementTree as ET

import pytest
from test_source_monthly_returns_service import read, save_month
from test_statement_import_broker_statement_provisional import _free_database, provisional_xml
from test_statement_import_mybroker import ACCOUNT

from hermes_finance.domain.xirr import XirrCashFlow, calculate_xirr
from hermes_finance.services import source_intake
from hermes_finance.services.source_money_classifications import default_classification

pytestmark = [pytest.mark.service, pytest.mark.network_free]


@pytest.fixture
def db(tmp_path):
    database = _free_database(tmp_path)
    yield database
    database.engine.dispose()


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="deferred: protected mybroker.py discards unclassified position quantities",
)
def test_irrelevant_position_does_not_hide_known_external_flow_totals(db):
    xml = ET.fromstring(provisional_xml(candidate_count=0))
    positions = xml.find(".//{MyBroker}Details_Collection")
    ET.SubElement(
        positions,
        "{MyBroker}Details",
        {
            "acc_code": ACCOUNT,
            "active_type": "Валюта",
            "active_name": "USD",
            "income_rest": "0",
            "real_rest": "0",
        },
    )
    with db.session_factory() as session:
        source_intake.save_intake(
            session,
            document=ET.tostring(xml, encoding="utf-8"),
            filename="Брокерский 1234567 (01.04.30-30.04.30).xml",
            request_id="astra-medium-zero-usd",
        )
    result = read(db)
    # This test requires only the fully parsed Money schedule, not FX valuation.
    totals = [result.months[0].result, result.period, *result.segments]
    assert [(row.contributions_kopecks, row.withdrawals_kopecks) for row in totals] == [
        (0, 0)
    ] * len(totals)


def test_transfer_with_coupon_income_narrative_is_not_coupon_income():
    classification = default_classification(
        "Перевод", "купонный доход Synthetic bond", "unsupported", "10.00"
    )
    # With no supported directed transfer evidence, preserve uncertainty.
    assert classification == "unknown"


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="deferred: classifier under concurrent change",
)
def test_ao_transfer_case_variants_have_the_same_classification():
    narratives = ("в АО Synthetic", "В АО Synthetic", "в ао Synthetic")
    actual = [
        default_classification("Перевод", narrative, "unsupported", "-10.00")
        for narrative in narratives
    ]
    assert actual == ["external_withdrawal"] * len(narratives)


def test_one_day_doubling_has_a_finite_unique_xirr():
    solved = calculate_xirr(
        [XirrCashFlow(date(2030, 1, 1), -100), XirrCashFlow(date(2030, 1, 2), 200)]
    )
    # Direct two-payment identity, independent of the production root scan.
    with localcontext() as context:
        context.prec = 130
        expected = Decimal(2) ** 365 - 1
        assert solved.annualized_rate is not None, solved.reason_codes
        assert abs(solved.annualized_rate / expected - 1) < Decimal("1e-24")


@pytest.mark.parametrize("rounding", [ROUND_DOWN, ROUND_UP])
def test_xirr_is_independent_of_callers_decimal_precision(rounding):
    flows = [
        XirrCashFlow(date(2030, 1, 1), -10_000),
        XirrCashFlow(date(2030, 2, 1), 11_000),
    ]
    with localcontext() as context:
        context.prec = 60
        expected = (Decimal(11) / 10) ** (Decimal(365) / 31) - 1
    with localcontext() as context:
        context.prec = 6
        context.rounding = rounding
        solved = calculate_xirr(flows)
        assert context.prec == 6 and context.rounding == rounding
    assert solved.annualized_rate is not None, solved.reason_codes
    with localcontext() as context:
        context.prec = 60
        assert abs(solved.annualized_rate - expected) < Decimal("1e-24")


def test_missing_statement_month_does_not_claim_zero_coupon_or_dividend_income(db):
    save_month(db, 4, candidate_count=0)
    save_month(db, 6, candidate_count=0)
    result = read(db)
    missing = result.months[1]
    for covered in (result.months[0], result.months[2]):
        assert (covered.coupons_kopecks, covered.dividends_kopecks) == (0, 0)
    assert missing.intake_ids == ()
    assert "flow_coverage_gap" in missing.flags
    assert (missing.coupons_kopecks, missing.dividends_kopecks) == (None, None)

    from fastapi.testclient import TestClient

    from hermes_finance.main import create_app

    response = TestClient(create_app(database=db)).get(
        "/api/source-returns/monthly", params={"source_account": ACCOUNT}
    )
    assert response.status_code == 200, response.text
    payload = response.json()["months"][1]
    assert payload["coupons_kopecks"] is payload["dividends_kopecks"] is None
    assert "flow_coverage_gap" in payload["flags"]


def test_no_source_history_has_unknown_flow_totals(db):
    result = read(db)
    assert result.months == () and result.flows == ()
    assert result.period.growth_kopecks is None
    assert result.period.chain_reason_codes == ("insufficient_boundaries",)
    assert (result.period.contributions_kopecks, result.period.withdrawals_kopecks) == (None, None)


def test_expanded_xirr_bracket_handles_multiple_payments_and_iteration_limit():
    flows = [
        XirrCashFlow(date(2030, 1, 1), -100),
        XirrCashFlow(date(2030, 1, 2), 100),
        XirrCashFlow(date(2030, 1, 3), 200),
    ]
    solved = calculate_xirr(flows)
    with localcontext() as context:
        context.prec = 130
        # Daily growth of two: -100 + 100/2 + 200/4 = 0.
        expected = Decimal(2) ** 365 - 1
        assert solved.annualized_rate is not None, solved.reason_codes
        assert abs(solved.annualized_rate / expected - 1) < Decimal("1e-24")
    limited = calculate_xirr(flows, max_iterations=1)
    assert limited.annualized_rate is None
    assert limited.reason_codes == ("not_computable_xirr_convergence_failed",)


def test_expanded_negative_root_does_not_publish_rounded_minus_one():
    solved = calculate_xirr(
        [XirrCashFlow(date(2030, 1, 1), -200), XirrCashFlow(date(2030, 1, 2), 100)]
    )
    # -1 + 2**-365 is outside the solver context's representable rate precision.
    assert solved.annualized_rate is None
    assert solved.reason_codes == ("not_computable_xirr_convergence_failed",)
