from collections.abc import Callable
from decimal import Decimal

import pytest

from hermes_finance.domain import PercentageRate, RubleAmount


def test_ruble_amount_converts_one_kopeck_exactly() -> None:
    amount = RubleAmount.from_api("0.01")

    assert amount.kopecks == 1
    assert amount.as_decimal() == Decimal("0.01")
    assert amount.to_api() == "0.01"


@pytest.mark.parametrize(
    ("major_units", "kopecks"),
    [
        (Decimal("999999999999999999.99"), 99_999_999_999_999_999_999),
        (Decimal("-123456789.87"), -12_345_678_987),
    ],
)
def test_ruble_amount_converts_signed_decimal_values_exactly(
    major_units: Decimal, kopecks: int
) -> None:
    amount = RubleAmount.from_decimal(major_units)

    assert amount.kopecks == kopecks
    assert amount.as_decimal() == major_units


@pytest.mark.parametrize(
    ("major_units", "expected_kopecks"),
    [
        (Decimal("1.004"), 100),
        (Decimal("1.005"), 101),
        (Decimal("-1.004"), -100),
        (Decimal("-1.005"), -101),
    ],
)
def test_ruble_amount_rounds_half_away_from_zero(
    major_units: Decimal, expected_kopecks: int
) -> None:
    assert RubleAmount.from_decimal(major_units).kopecks == expected_kopecks


@pytest.mark.parametrize(
    "operation",
    [
        lambda: RubleAmount.from_api(1.25),  # type: ignore[arg-type]
        lambda: RubleAmount.from_decimal(1.25),  # type: ignore[arg-type]
        lambda: RubleAmount(125.0),  # type: ignore[arg-type]
    ],
)
def test_ruble_amount_rejects_binary_float(operation: Callable[[], object]) -> None:
    with pytest.raises(TypeError, match="float"):
        operation()


@pytest.mark.parametrize("amount", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")])
def test_ruble_amount_rejects_non_finite_decimal(amount: Decimal) -> None:
    with pytest.raises(ValueError, match="finite"):
        RubleAmount.from_decimal(amount)


@pytest.mark.parametrize("amount", ["", "not-money", "1,25"])
def test_ruble_amount_rejects_malformed_api_string(amount: str) -> None:
    with pytest.raises(ValueError, match="decimal string"):
        RubleAmount.from_api(amount)


def test_percentage_rate_converts_api_percentage_points_exactly() -> None:
    rate = PercentageRate.from_api("13.50")

    assert rate.basis_points == 1350
    assert rate.as_percentage() == Decimal("13.50")
    assert rate.as_fraction() == Decimal("0.135")
    assert rate.to_api() == "13.50"


@pytest.mark.parametrize(
    ("percentage_points", "expected_basis_points"),
    [(Decimal("13.505"), 1351), (Decimal("-0.005"), -1)],
)
def test_percentage_rate_rounds_decimal_to_nearest_basis_point(
    percentage_points: Decimal, expected_basis_points: int
) -> None:
    rate = PercentageRate.from_decimal(percentage_points)

    assert rate.basis_points == expected_basis_points


@pytest.mark.parametrize(
    "operation",
    [
        lambda: PercentageRate.from_api(13.5),  # type: ignore[arg-type]
        lambda: PercentageRate.from_decimal(13.5),  # type: ignore[arg-type]
        lambda: PercentageRate(1350.0),  # type: ignore[arg-type]
    ],
)
def test_percentage_rate_rejects_binary_float(operation: Callable[[], object]) -> None:
    with pytest.raises(TypeError, match="float"):
        operation()
