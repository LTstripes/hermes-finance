"""Unit tests for the pure passive-income calculator (no database)."""

import pytest

from hermes_finance.domain import InvestmentCashFlowType, RubleAmount
from hermes_finance.domain.passive_income import (
    PassiveIncomeBreakdown,
    PassiveIncomeInput,
    PassiveIncomeResult,
    PassiveIncomeSource,
    PassiveIncomeSourceBucket,
    calculate_passive_income,
    classify_flow_type,
)

# --- classification helper ---


@pytest.mark.parametrize(
    ("flow_type", "expected_bucket"),
    [
        (InvestmentCashFlowType.INTEREST, PassiveIncomeSourceBucket.DEPOSIT_INTEREST),
        (InvestmentCashFlowType.COUPON, PassiveIncomeSourceBucket.BOND_COUPONS),
        (InvestmentCashFlowType.DIVIDEND, PassiveIncomeSourceBucket.DIVIDENDS),
        (InvestmentCashFlowType.OTHER, PassiveIncomeSourceBucket.OTHER_CAPITAL_INCOME),
    ],
)
def test_classify_passive_flow_types_return_bucket(
    flow_type: InvestmentCashFlowType, expected_bucket: PassiveIncomeSourceBucket
) -> None:
    counts, bucket = classify_flow_type(flow_type)
    assert counts is True
    assert bucket is expected_bucket


def test_classify_passive_flow_type_accepts_string() -> None:
    counts, bucket = classify_flow_type("coupon")
    assert counts is True
    assert bucket is PassiveIncomeSourceBucket.BOND_COUPONS


@pytest.mark.parametrize(
    "flow_type",
    [
        InvestmentCashFlowType.REDEMPTION,
        InvestmentCashFlowType.DEPOSIT,
        InvestmentCashFlowType.WITHDRAWAL,
        InvestmentCashFlowType.COMMISSION,
        InvestmentCashFlowType.TAX,
        InvestmentCashFlowType.REALIZED_PROFIT,
        InvestmentCashFlowType.REALIZED_LOSS,
    ],
)
def test_classify_excluded_flow_types_return_false(
    flow_type: InvestmentCashFlowType,
) -> None:
    counts, bucket = classify_flow_type(flow_type)
    assert counts is False
    assert bucket is None


def test_classify_unknown_string_returns_false() -> None:
    counts, bucket = classify_flow_type("cashback")
    assert counts is False
    assert bucket is None


# --- calculator: zero ---


def test_zero_input_returns_zero_result() -> None:
    result = calculate_passive_income(
        PassiveIncomeInput(
            deposit_interest=RubleAmount(0),
            bond_coupons=RubleAmount(0),
            dividends=RubleAmount(0),
            other_capital_income=RubleAmount(0),
        )
    )
    assert result.total_net_passive_income == RubleAmount(0)
    assert result.breakdown.deposit_interest == RubleAmount(0)
    assert result.breakdown.bond_coupons == RubleAmount(0)
    assert result.breakdown.dividends == RubleAmount(0)
    assert result.breakdown.other_capital_income == RubleAmount(0)
    assert result.sources == ()


# --- calculator: mixed buckets ---


def test_mixed_buckets_sum_correctly() -> None:
    result = calculate_passive_income(
        PassiveIncomeInput(
            deposit_interest=RubleAmount(100_000),
            bond_coupons=RubleAmount(200_000),
            dividends=RubleAmount(50_000),
            other_capital_income=RubleAmount(30_000),
        )
    )
    assert result.total_net_passive_income == RubleAmount(380_000)
    assert result.breakdown.deposit_interest == RubleAmount(100_000)
    assert result.breakdown.bond_coupons == RubleAmount(200_000)
    assert result.breakdown.dividends == RubleAmount(50_000)
    assert result.breakdown.other_capital_income == RubleAmount(30_000)


def test_passive_income_uses_stored_net_without_second_tax_or_commission_deduction() -> None:
    # 1000.00 gross - 100.00 tax - 30.00 commission = 870.00 net.
    # The calculator receives the persisted net amount and must not deduct
    # tax or commission a second time.
    result = calculate_passive_income(
        PassiveIncomeInput(
            deposit_interest=RubleAmount(0),
            bond_coupons=RubleAmount(87_000),
            dividends=RubleAmount(0),
            other_capital_income=RubleAmount(0),
        )
    )

    assert result.total_net_passive_income == RubleAmount(87_000)
    assert result.breakdown.bond_coupons == RubleAmount(87_000)


def test_breakdown_sums_to_total() -> None:
    result = calculate_passive_income(
        PassiveIncomeInput(
            deposit_interest=RubleAmount(10_000),
            bond_coupons=RubleAmount(20_000),
            dividends=RubleAmount(5_000),
            other_capital_income=RubleAmount(3_000),
        )
    )
    breakdown_sum = (
        result.breakdown.deposit_interest.kopecks
        + result.breakdown.bond_coupons.kopecks
        + result.breakdown.dividends.kopecks
        + result.breakdown.other_capital_income.kopecks
    )
    assert breakdown_sum == result.total_net_passive_income.kopecks


def test_per_source_breakdown_present() -> None:
    sources = (
        PassiveIncomeSource(
            bucket=PassiveIncomeSourceBucket.DEPOSIT_INTEREST,
            source_type="deposit_snapshot",
            account_id=1,
            amount=RubleAmount(50_000),
        ),
        PassiveIncomeSource(
            bucket=PassiveIncomeSourceBucket.BOND_COUPONS,
            source_type="investment_cash_flow",
            account_id=2,
            amount=RubleAmount(20_000),
        ),
    )
    result = calculate_passive_income(
        PassiveIncomeInput(
            deposit_interest=RubleAmount(50_000),
            bond_coupons=RubleAmount(20_000),
            dividends=RubleAmount(0),
            other_capital_income=RubleAmount(0),
            sources=sources,
        )
    )
    assert len(result.sources) == 2
    assert result.sources[0].bucket is PassiveIncomeSourceBucket.DEPOSIT_INTEREST
    assert result.sources[1].bucket is PassiveIncomeSourceBucket.BOND_COUPONS


def test_returns_passive_income_result_type() -> None:
    result = calculate_passive_income(
        PassiveIncomeInput(
            deposit_interest=RubleAmount(0),
            bond_coupons=RubleAmount(0),
            dividends=RubleAmount(0),
            other_capital_income=RubleAmount(0),
        )
    )
    assert isinstance(result, PassiveIncomeResult)
    assert isinstance(result.breakdown, PassiveIncomeBreakdown)
