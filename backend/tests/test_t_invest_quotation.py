"""Exact T-Invest units+nano conversion. No binary-float financial arithmetic."""

from decimal import Decimal
from inspect import getsource

import pytest

from hermes_finance.domain import RubleAmount
from hermes_finance.market_data.dto import RawPriceBasis
from hermes_finance.market_data.normalize import convert_to_kopecks
from hermes_finance.market_data.quotation import QuotationError, quotation_to_decimal


def test_units_plus_nano_is_exact_decimal() -> None:
    assert quotation_to_decimal(units=312, nano=450_000_000) == Decimal("312.450000000")
    assert quotation_to_decimal(units="1000", nano="0") == Decimal("1000")
    assert quotation_to_decimal(units=0, nano=1) == Decimal("0.000000001")
    assert quotation_to_decimal(units=-1, nano=-500_000_000) == Decimal("-1.500000000")


def test_money_value_uses_the_same_helper() -> None:
    amount = quotation_to_decimal(units="1000", nano=0)
    assert amount == Decimal(1000)
    assert RubleAmount.from_decimal(amount).kopecks == 100_000


def test_rejects_non_integer_and_out_of_range_nano() -> None:
    with pytest.raises(QuotationError):
        quotation_to_decimal(units=1.5, nano=0)
    with pytest.raises(QuotationError):
        quotation_to_decimal(units=1, nano=1_000_000_000)
    with pytest.raises(QuotationError):
        quotation_to_decimal(units="1.0", nano=0)
    with pytest.raises(QuotationError):
        quotation_to_decimal(units=True, nano=0)


def test_kopeck_half_up_boundary_from_quotation() -> None:
    price = quotation_to_decimal(units=1, nano=5_000_000)
    assert (
        convert_to_kopecks(
            raw_price=price,
            basis=RawPriceBasis.CASH_PER_UNIT,
            face_value=None,
            currency_unit="RUB",
            shares_schema_cash_default=False,
        )
        == 101
    )
    just_below = quotation_to_decimal(units=1, nano=4_900_000)
    assert (
        convert_to_kopecks(
            raw_price=just_below,
            basis=RawPriceBasis.CASH_PER_UNIT,
            face_value=None,
            currency_unit="RUB",
            shares_schema_cash_default=False,
        )
        == 100
    )


def test_bond_half_up_uses_official_percent_of_face() -> None:
    points = quotation_to_decimal(units=97, nano=255_500_000)
    nominal = quotation_to_decimal(units=1000, nano=0)
    assert (
        convert_to_kopecks(
            raw_price=points,
            basis=RawPriceBasis.PERCENT_OF_FACE,
            face_value=nominal,
            currency_unit="rub",
            shares_schema_cash_default=False,
        )
        == 97_256
    )


def test_helper_source_has_no_binary_float_arithmetic() -> None:
    source = getsource(quotation_to_decimal)
    assert "float(" not in source
    assert "round(" not in source
