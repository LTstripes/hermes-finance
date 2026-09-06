from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, localcontext
from enum import StrEnum

from hermes_finance.domain.values import FINANCIAL_ROUNDING


class DepositType(StrEnum):
    DEPOSIT = "deposit"
    SAVINGS = "savings"


# Local precision guard for the deposit-interest formula. The product
# ``balance * rate`` lives entirely in integer kopecks and basis points and
# is at most ~10^5 kopecks × 10^4 basis points = 10^9 significant digits worth
# of operands. A prec of 28 covers the full int64-style range; the local
# context is opened around the calculation so the function is independent of
# any ambient ``decimal.getcontext().prec`` and survives low-precision callers
# (e.g. a test fixture at prec=5) without silent truncation.
_DEPOSIT_INTEREST_PRECISION = 40


def calculate_deposit_expected_monthly_interest_kopecks(
    balance_kopecks: int,
    annual_rate_basis_points: int,
) -> int:
    """Canonical deposit monthly interest.

    Formula: ``expected_monthly_interest = balance * annual_rate / 12``
    with canonical PercentageRate basis-point semantics and ROUND_HALF_UP.

    Context-independent: the entire expression is evaluated inside a
    ``localcontext`` whose precision is derived from the operand magnitudes,
    so the result does not depend on the ambient ``decimal`` context.
    """
    if not isinstance(balance_kopecks, int) or isinstance(balance_kopecks, bool):
        raise TypeError("balance_kopecks must be int")
    if balance_kopecks < 0:
        raise ValueError("balance_kopecks must be >=0")
    if not isinstance(annual_rate_basis_points, int) or isinstance(annual_rate_basis_points, bool):
        raise TypeError("annual_rate_basis_points must be int")
    if annual_rate_basis_points < 0:
        raise ValueError("annual_rate_basis_points must be >=0")

    with localcontext() as ctx:
        ctx.prec = _DEPOSIT_INTEREST_PRECISION
        ctx.rounding = ROUND_HALF_UP
        monthly = (
            Decimal(balance_kopecks)
            * Decimal(annual_rate_basis_points)
            / Decimal(10_000)
            / Decimal(12)
        )
        return int(monthly.to_integral_value(rounding=FINANCIAL_ROUNDING))
