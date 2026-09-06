from __future__ import annotations

from enum import StrEnum


class DepositType(StrEnum):
    DEPOSIT = "deposit"
    SAVINGS = "savings"


def calculate_deposit_expected_monthly_interest_kopecks(
    balance_kopecks: int,
    annual_rate_basis_points: int,
) -> int:
    """Canonical deposit monthly interest.

    Formula: ``expected_monthly_interest = balance * annual_rate / 12``
    with canonical PercentageRate basis-point semantics and ROUND_HALF_UP.

    Exact rational: balance * basis_points / 120000, rounded half-up
    via integer divmod — no Decimal context, no fixed precision.
    """
    if not isinstance(balance_kopecks, int) or isinstance(balance_kopecks, bool):
        raise TypeError("balance_kopecks must be int")
    if balance_kopecks < 0:
        raise ValueError("balance_kopecks must be >=0")
    if not isinstance(annual_rate_basis_points, int) or isinstance(annual_rate_basis_points, bool):
        raise TypeError("annual_rate_basis_points must be int")
    if annual_rate_basis_points < 0:
        raise ValueError("annual_rate_basis_points must be >=0")

    numerator = balance_kopecks * annual_rate_basis_points
    denominator = 120_000
    q, r = divmod(numerator, denominator)
    if r * 2 >= denominator:
        q += 1
    return int(q)
