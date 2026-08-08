"""Pure domain IIS account-result calculator (framework-independent).

Implements MASTER_SPEC §10.16:

    portfolio_result_without_tax_benefit
    portfolio_result_with_tax_benefit =
        portfolio_result_without_tax_benefit
      + received_tax_benefits

Planned and submitted tax benefits are summed separately and returned in the
breakdown — they are never added to either portfolio result.  Rejected
benefits are ignored entirely.

All money values use :class:`~hermes_finance.domain.values.RubleAmount`
(integer kopecks); binary ``float`` is never used.  The calculator performs
pure addition of integer kopecks — no division, no rounding.
"""

from __future__ import annotations

from dataclasses import dataclass

from hermes_finance.domain.values import RubleAmount


@dataclass(frozen=True, slots=True)
class IisResultInput:
    """Pure-domain input for the IIS account-result calculator.

    All amounts are integer kopecks via :class:`RubleAmount`.
    The ORM assembler is responsible for sourcing each field from the
    correct persisted rows; the calculator simply sums what it is given.
    """

    unrealized: RubleAmount
    coupons: RubleAmount
    dividends: RubleAmount
    realized_pnl: RubleAmount
    received_tax_benefits: RubleAmount
    planned_tax_benefits: RubleAmount
    submitted_tax_benefits: RubleAmount


@dataclass(frozen=True, slots=True)
class IisResultBreakdown:
    """Transparent breakdown of the IIS account result.

    Mirrors the input parts plus the planned/submitted benefits that are
    shown separately and never added to the portfolio results.
    """

    unrealized: RubleAmount
    coupons: RubleAmount
    dividends: RubleAmount
    realized_pnl: RubleAmount
    received_tax_benefits: RubleAmount
    planned_tax_benefits: RubleAmount
    submitted_tax_benefits: RubleAmount


@dataclass(frozen=True, slots=True)
class IisResult:
    """Pure-domain output of the IIS account-result calculator."""

    portfolio_result_without_tax_benefit: RubleAmount
    portfolio_result_with_tax_benefit: RubleAmount
    breakdown: IisResultBreakdown


def calculate_iis_result(input_data: IisResultInput) -> IisResult:
    """Calculate the IIS account result from pure-domain input.

    Pure addition of integer kopecks — no division, no float, no rounding.
    Zero input produces both results ``RubleAmount(0)``.

    - ``portfolio_result_without_tax_benefit`` = unrealized + coupons +
      dividends + realized_pnl (no contributions, deposits, withdrawals,
      redemptions or tax benefits).
    - ``portfolio_result_with_tax_benefit`` = without + received tax benefits.
    - Planned and submitted benefits are in the breakdown only, never added
      to either portfolio result.
    """
    without = RubleAmount(
        input_data.unrealized.kopecks
        + input_data.coupons.kopecks
        + input_data.dividends.kopecks
        + input_data.realized_pnl.kopecks
    )
    with_benefit = RubleAmount(without.kopecks + input_data.received_tax_benefits.kopecks)
    breakdown = IisResultBreakdown(
        unrealized=input_data.unrealized,
        coupons=input_data.coupons,
        dividends=input_data.dividends,
        realized_pnl=input_data.realized_pnl,
        received_tax_benefits=input_data.received_tax_benefits,
        planned_tax_benefits=input_data.planned_tax_benefits,
        submitted_tax_benefits=input_data.submitted_tax_benefits,
    )
    return IisResult(
        portfolio_result_without_tax_benefit=without,
        portfolio_result_with_tax_benefit=with_benefit,
        breakdown=breakdown,
    )
