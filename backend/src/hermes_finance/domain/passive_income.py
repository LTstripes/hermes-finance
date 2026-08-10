"""Pure domain passive-income calculator (framework-independent).

Implements MASTER_SPEC §10.4:

    actual_net_passive_income =
        deposit_interest_net
      + bond_coupons_net
      + dividends_net
      + other_capital_income_net

Commissions and taxes are counted exactly once: ``net_amount`` from stored
events already includes them, so the calculator never subtracts tax/commission
a second time.

Deposit actual interest comes ONLY from ``deposit_snapshots.actual_interest_received``
(wiki invariant).  The ORM assembler is responsible for that source; the pure
calculator receives the already-separated amounts.

Cashback is never passive income (wiki invariant; also ``IncomeType.CASHBACK``
excluded at the ORM layer).  Generic investment interest is capital income,
not deposit interest; the ORM layer excludes legacy deposit/savings interest
flows because deposit snapshots are the canonical source for that bucket.

All money values use :class:`~hermes_finance.domain.values.RubleAmount`
(integer kopecks); binary ``float`` is never used.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from hermes_finance.domain.cash_flows import InvestmentCashFlowType
from hermes_finance.domain.values import RubleAmount


class PassiveIncomeSourceBucket(StrEnum):
    """The four income buckets from MASTER_SPEC §10.4."""

    DEPOSIT_INTEREST = "deposit_interest"
    BOND_COUPONS = "bond_coupons"
    DIVIDENDS = "dividends"
    OTHER_CAPITAL_INCOME = "other_capital_income"


@dataclass(frozen=True, slots=True)
class PassiveIncomeSource:
    """A single item contributing to a passive-income bucket."""

    bucket: PassiveIncomeSourceBucket
    source_type: str
    account_id: int | None = None
    instrument_id: int | None = None
    amount: RubleAmount = RubleAmount(0)


@dataclass(frozen=True, slots=True)
class PassiveIncomeBreakdown:
    """Breakdown of actual net passive income by source bucket."""

    deposit_interest: RubleAmount
    bond_coupons: RubleAmount
    dividends: RubleAmount
    other_capital_income: RubleAmount


@dataclass(frozen=True, slots=True)
class PassiveIncomeInput:
    """Pure-domain input for the passive-income calculator.

    All amounts are integer kopecks via :class:`RubleAmount`.
    Deposit interest must come from ``deposit_snapshots.actual_interest_received``
    at the ORM layer; the calculator simply sums what it is given.
    """

    deposit_interest: RubleAmount
    bond_coupons: RubleAmount
    dividends: RubleAmount
    other_capital_income: RubleAmount
    sources: tuple[PassiveIncomeSource, ...] = ()


@dataclass(frozen=True, slots=True)
class PassiveIncomeResult:
    """Pure-domain output of the passive-income calculator."""

    total_net_passive_income: RubleAmount
    breakdown: PassiveIncomeBreakdown
    sources: tuple[PassiveIncomeSource, ...] = ()


# Mapping from cash-flow types to passive-income buckets.
_FLOW_TYPE_TO_BUCKET: dict[InvestmentCashFlowType, PassiveIncomeSourceBucket] = {
    InvestmentCashFlowType.INTEREST: PassiveIncomeSourceBucket.OTHER_CAPITAL_INCOME,
    InvestmentCashFlowType.COUPON: PassiveIncomeSourceBucket.BOND_COUPONS,
    InvestmentCashFlowType.DIVIDEND: PassiveIncomeSourceBucket.DIVIDENDS,
    InvestmentCashFlowType.OTHER: PassiveIncomeSourceBucket.OTHER_CAPITAL_INCOME,
}


def classify_flow_type(
    flow_type: InvestmentCashFlowType | str,
) -> tuple[bool, PassiveIncomeSourceBucket | None]:
    """Classify an investment cash-flow type.

    Returns ``(counts_as_passive, bucket)``:
    INTEREST/COUPON/DIVIDEND/OTHER -> ``(True, <bucket>)``;
    REDEMPTION/DEPOSIT/WITHDRAWAL/COMMISSION/TAX/REALIZED_PROFIT/REALIZED_LOSS
    and any unknown string (including ``"cashback"``) -> ``(False, None)``.
    """
    if isinstance(flow_type, str):
        try:
            flow_type = InvestmentCashFlowType(flow_type)
        except ValueError:
            return False, None
    bucket = _FLOW_TYPE_TO_BUCKET.get(flow_type)
    return (bucket is not None, bucket)


def calculate_passive_income(input_data: PassiveIncomeInput) -> PassiveIncomeResult:
    """Calculate actual net passive income from pure-domain input.

    No division, no float, no double-counting of tax/commission.
    Zero data produces zero totals.
    """
    breakdown = PassiveIncomeBreakdown(
        deposit_interest=input_data.deposit_interest,
        bond_coupons=input_data.bond_coupons,
        dividends=input_data.dividends,
        other_capital_income=input_data.other_capital_income,
    )

    total = RubleAmount(
        input_data.deposit_interest.kopecks
        + input_data.bond_coupons.kopecks
        + input_data.dividends.kopecks
        + input_data.other_capital_income.kopecks
    )

    return PassiveIncomeResult(
        total_net_passive_income=total,
        breakdown=breakdown,
        sources=input_data.sources,
    )
