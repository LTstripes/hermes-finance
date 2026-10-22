"""Pure monthly Modified Dietz estimates for one account; no source authority.

Money stays in integer kopecks and rates are Decimal fractions (0.1 = 10%).
Every adjacent boundary pair is one reporting interval, with external flows
in (opening_date, closing_date]. Closing-day flows have zero Dietz weight.
Assumed flows are included explicitly; unknown flows block affected metrics.
Missing interior endpoints block adjacent months and chaining, but do not
block period growth/XIRR when the outer endpoints and flows are known.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, DecimalException, localcontext
from typing import Literal

from hermes_finance.domain.xirr import XirrCashFlow, calculate_xirr

MonthBoundary = tuple[date, int | None]
ExternalFlow = tuple[date, int, Literal["confirmed", "assumed", "unknown"]]


@dataclass(frozen=True, slots=True)
class MonthlyReturnRow:
    opening_date: date
    closing_date: date
    opening_kopecks: int | None
    closing_kopecks: int | None
    contributions_kopecks: int | None
    withdrawals_kopecks: int | None
    growth_kopecks: int | None
    modified_dietz_return: Decimal | None
    assumptions_used: bool
    missing_endpoint: bool
    reason_codes: tuple[str, ...] = ()
    approximate: bool = True


@dataclass(frozen=True, slots=True)
class PeriodReturnTotals:
    contributions_kopecks: int | None
    withdrawals_kopecks: int | None
    growth_kopecks: int | None
    chained_return: Decimal | None
    xirr_annualized_return: Decimal | None
    xirr_period_return: Decimal | None
    assumptions_used: bool
    missing_endpoint: bool
    chain_reason_codes: tuple[str, ...] = ()
    growth_reason_codes: tuple[str, ...] = ()
    xirr_reason_codes: tuple[str, ...] = ()
    approximate: bool = True


@dataclass(frozen=True, slots=True)
class MonthlyReturnChainResult:
    months: tuple[MonthlyReturnRow, ...]
    period: PeriodReturnTotals


def _validate(boundaries: list[MonthBoundary], flows: list[ExternalFlow]) -> None:
    for index, (event_date, value) in enumerate(boundaries):
        if type(event_date) is not date:
            raise TypeError("boundary date must be a date")
        if value is not None and type(value) is not int:
            raise TypeError("boundary value must be integer kopecks or None")
        if index and event_date <= boundaries[index - 1][0]:
            raise ValueError("boundaries must be strictly increasing")
    for event_date, amount, status in flows:
        if type(event_date) is not date or type(amount) is not int:
            raise TypeError("flow must contain a date and integer kopecks")
        if status not in ("confirmed", "assumed", "unknown"):
            raise ValueError("flow status must be confirmed, assumed, or unknown")


def _amounts(flows: list[ExternalFlow]) -> tuple[int | None, int | None]:
    if any(status == "unknown" for _, _, status in flows):
        return None, None
    return (
        sum(amount for _, amount, _ in flows if amount > 0),
        -sum(amount for _, amount, _ in flows if amount < 0),
    )


def _month(
    opening: MonthBoundary, closing: MonthBoundary, flows: list[ExternalFlow]
) -> MonthlyReturnRow:
    start, opening_value = opening
    end, closing_value = closing
    contributions, withdrawals = _amounts(flows)
    missing = opening_value is None or closing_value is None
    reasons: list[str] = []
    if missing:
        reasons.append("missing_endpoint")
    if contributions is None:
        reasons.append("unknown_flow")
    growth = None
    rate = None
    if (
        opening_value is not None
        and closing_value is not None
        and contributions is not None
        and withdrawals is not None
    ):
        growth = closing_value - opening_value - contributions + withdrawals
        days = (end - start).days
        # Multiply the Dietz denominator by days to avoid rounding each weight.
        capital_days = opening_value * days + sum(
            amount * (end - event_date).days for event_date, amount, _ in flows
        )
        if capital_days <= 0:
            reasons.append("non_positive_dietz_denominator")
        else:
            rate = Decimal(growth * days) / Decimal(capital_days)
            if 1 + rate < 0:
                reasons.append("negative_dietz_factor")
    return MonthlyReturnRow(
        opening_date=start,
        closing_date=end,
        opening_kopecks=opening_value,
        closing_kopecks=closing_value,
        contributions_kopecks=contributions,
        withdrawals_kopecks=withdrawals,
        growth_kopecks=growth,
        modified_dietz_return=rate,
        assumptions_used=any(status == "assumed" for _, _, status in flows),
        missing_endpoint=missing,
        reason_codes=tuple(reasons),
    )


def _period_xirr(
    opening: MonthBoundary, closing: MonthBoundary, flows: list[ExternalFlow]
) -> tuple[Decimal | None, Decimal | None, tuple[str, ...]]:
    start, opening_value = opening
    end, closing_value = closing
    reasons = []
    if opening_value is None or closing_value is None:
        reasons.append("missing_endpoint")
    if any(status == "unknown" for _, _, status in flows):
        reasons.append("unknown_flow")
    if reasons:
        return None, None, tuple(reasons)
    assert opening_value is not None and closing_value is not None
    solved = calculate_xirr(
        [
            XirrCashFlow(start, -opening_value),
            *(XirrCashFlow(event_date, -amount) for event_date, amount, _ in flows),
            XirrCashFlow(end, closing_value),
        ]
    )
    annual = solved.annualized_rate
    if annual is None:
        return None, None, solved.reason_codes
    try:
        period = (Decimal(1) + annual) ** (Decimal((end - start).days) / Decimal(365)) - 1
        if not period.is_finite():
            raise DecimalException
    except DecimalException:
        return None, None, ("not_computable_xirr_convergence_failed",)
    return annual, period, ()


def calculate_monthly_return_chain(
    boundaries: list[MonthBoundary], flows: list[ExternalFlow]
) -> MonthlyReturnChainResult:
    """Return monthly estimates and period totals without mutating inputs.

    Boundaries must be strictly increasing date/value pairs; missing values
    are None, never zero. Flows may be unsorted; those outside the overall
    (first, last] interval are ignored. Withdrawals are positive magnitudes.
    Unknown flow status makes affected flow totals, growth and rates None.
    A nonpositive Dietz denominator blocks the rate, preserving known growth.
    All rows/totals carry approximate=True: this method grants no exact TWRR
    or accepted financial/source authority. Assumed flows also flag period XIRR.
    Empty/single-boundary input returns no months, unknown flow totals and unavailable rates.
    Malformed types/order/status raise TypeError/ValueError; missing data does not.
    Calculations use a local 60-digit ROUND_HALF_UP Decimal context.
    """
    _validate(boundaries, flows)
    if len(boundaries) < 2:
        reasons = ("insufficient_boundaries",)
        return MonthlyReturnChainResult(
            months=(),
            period=PeriodReturnTotals(
                contributions_kopecks=None,
                withdrawals_kopecks=None,
                growth_kopecks=None,
                chained_return=None,
                xirr_annualized_return=None,
                xirr_period_return=None,
                assumptions_used=False,
                missing_endpoint=any(value is None for _, value in boundaries),
                chain_reason_codes=reasons,
                growth_reason_codes=reasons,
                xirr_reason_codes=reasons,
            ),
        )
    selected = sorted(flow for flow in flows if boundaries[0][0] < flow[0] <= boundaries[-1][0])
    with localcontext() as ctx:
        ctx.prec = 60
        ctx.rounding = ROUND_HALF_UP
        months = tuple(
            _month(
                opening, closing, [flow for flow in selected if opening[0] < flow[0] <= closing[0]]
            )
            for opening, closing in zip(boundaries, boundaries[1:])
        )
        chain = Decimal(1)
        for month in months:
            if month.modified_dietz_return is None or 1 + month.modified_dietz_return < 0:
                break
            chain *= 1 + month.modified_dietz_return
        chain_reasons = tuple(
            dict.fromkeys(reason for month in months for reason in month.reason_codes)
        )
        contributions, withdrawals = _amounts(selected)
        opening_value, closing_value = boundaries[0][1], boundaries[-1][1]
        growth_reasons = []
        if opening_value is None or closing_value is None:
            growth_reasons.append("missing_endpoint")
        if contributions is None:
            growth_reasons.append("unknown_flow")
        growth = None
        if (
            opening_value is not None
            and closing_value is not None
            and contributions is not None
            and withdrawals is not None
        ):
            growth = closing_value - opening_value - contributions + withdrawals
        annual, period, xirr_reasons = _period_xirr(boundaries[0], boundaries[-1], selected)
        return MonthlyReturnChainResult(
            months=months,
            period=PeriodReturnTotals(
                contributions_kopecks=contributions,
                withdrawals_kopecks=withdrawals,
                growth_kopecks=growth,
                chained_return=None if chain_reasons else chain - 1,
                xirr_annualized_return=annual,
                xirr_period_return=period,
                assumptions_used=any(month.assumptions_used for month in months),
                missing_endpoint=any(month.missing_endpoint for month in months),
                chain_reason_codes=chain_reasons,
                growth_reason_codes=tuple(growth_reasons),
                xirr_reason_codes=xirr_reasons,
            ),
        )
