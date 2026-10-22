"""Strict synthetic regressions for remaining medium/low methodology audit findings.

Each test asserts the desired behavior.  Run with --runxfail to inspect the
current counterexamples; no product code or private inputs are patched.
"""

from datetime import date
from decimal import Decimal, localcontext
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
    reason="astra-medium-1: a zero USD position must not invalidate known RUB Money totals",
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


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="astra-medium-2: transfer semantics must precede generic coupon-income wording",
)
def test_transfer_with_coupon_income_narrative_is_not_coupon_income():
    classification = default_classification(
        "Перевод", "купонный доход Synthetic bond", "unsupported", "10.00"
    )
    # With no supported directed transfer evidence, preserve uncertainty.
    assert classification == "unknown"


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="astra-medium-3: AO withdrawal recognition must be case insensitive",
)
def test_ao_transfer_case_variants_have_the_same_classification():
    narratives = ("в АО Synthetic", "В АО Synthetic", "в ао Synthetic")
    actual = [
        default_classification("Перевод", narrative, "unsupported", "-10.00")
        for narrative in narratives
    ]
    assert actual == ["external_withdrawal"] * len(narratives)


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="astra-medium-4: the fixed log-rate scan misses a finite unique one-day XIRR",
)
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


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="astra-medium-5: XIRR year fractions must use the solver's local precision",
)
def test_xirr_is_independent_of_callers_decimal_precision():
    flows = [
        XirrCashFlow(date(2030, 1, 1), -10_000),
        XirrCashFlow(date(2030, 2, 1), 11_000),
    ]
    with localcontext() as context:
        context.prec = 60
        expected = (Decimal(11) / 10) ** (Decimal(365) / 31) - 1
    with localcontext() as context:
        context.prec = 6
        solved = calculate_xirr(flows)
        assert context.prec == 6
    assert solved.annualized_rate is not None, solved.reason_codes
    with localcontext() as context:
        context.prec = 60
        assert abs(solved.annualized_rate - expected) < Decimal("1e-24")


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="astra-medium-6: missing statement-month income is unknown rather than zero",
)
def test_missing_statement_month_does_not_claim_zero_coupon_or_dividend_income(db):
    save_month(db, 4, candidate_count=0)
    save_month(db, 6, candidate_count=0)
    missing = read(db).months[1]
    assert missing.intake_ids == ()
    assert "flow_coverage_gap" in missing.flags
    assert (missing.coupons_kopecks, missing.dividends_kopecks) == (None, None)


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="astra-medium-7: no source history cannot establish zero external cash flows",
)
def test_no_source_history_has_unknown_flow_totals(db):
    result = read(db)
    assert result.months == () and result.flows == ()
    assert result.period.growth_kopecks is None
    assert result.period.chain_reason_codes == ("insufficient_boundaries",)
    assert (result.period.contributions_kopecks, result.period.withdrawals_kopecks) == (None, None)
