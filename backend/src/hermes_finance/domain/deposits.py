from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from hermes_finance.domain.values import FINANCIAL_ROUNDING


class DepositType(StrEnum):
    DEPOSIT = "deposit"
    SAVINGS = "savings"


def calculate_deposit_expected_monthly_interest_kopecks(
    balance_kopecks: int,
    annual_rate_basis_points: int,
) -> int:
    """Canonical deposit monthly interest.

    Formula: expected_monthly_interest = balance * annual_rate / 12
    with PercentageRate/basis-point semantics and ROUND_HALF_UP.

    Reuses exact semantics from services/deposits._compute_expected_monthly_interest
    so future refactors keep a single calculator.
    """
    if not isinstance(balance_kopecks, int) or isinstance(balance_kopecks, bool):
        raise TypeError("balance_kopecks must be int")
    if balance_kopecks < 0:
        raise ValueError("balance_kopecks must be >=0")
    if not isinstance(annual_rate_basis_points, int) or isinstance(annual_rate_basis_points, bool):
        raise TypeError("annual_rate_basis_points must be int")
    if annual_rate_basis_points < 0:
        raise ValueError("annual_rate_basis_points must be >=0")
    monthly = (
        Decimal(balance_kopecks) * Decimal(annual_rate_basis_points) / Decimal(10_000) / Decimal(12)
    )
    return int(monthly.to_integral_value(rounding=FINANCIAL_ROUNDING))
