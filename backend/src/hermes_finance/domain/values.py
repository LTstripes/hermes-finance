from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, DecimalException

FINANCIAL_ROUNDING = ROUND_HALF_UP
_KOPECKS_PER_RUBLE = Decimal(100)
_BASIS_POINTS_PER_PERCENTAGE_POINT = Decimal(100)
_BASIS_POINTS_PER_ONE = Decimal(10_000)


def _require_stored_integer(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int, not {type(value).__name__}")
    return value


def _require_finite_decimal(value: object, *, name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be Decimal, not {type(value).__name__}")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")
    return value


def _parse_api_decimal(value: object, *, name: str) -> Decimal:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string, not {type(value).__name__}")
    try:
        return Decimal(value)
    except DecimalException as error:
        raise ValueError(f"{name} must be a decimal string") from error


@dataclass(frozen=True, slots=True)
class RubleAmount:
    """An exact RUB amount stored as integer kopecks."""

    kopecks: int

    def __post_init__(self) -> None:
        _require_stored_integer(self.kopecks, name="kopecks")

    @classmethod
    def from_api(cls, amount: str) -> "RubleAmount":
        return cls.from_decimal(_parse_api_decimal(amount, name="API amount"))

    @classmethod
    def from_decimal(cls, amount: Decimal) -> "RubleAmount":
        amount = _require_finite_decimal(amount, name="amount")
        kopecks = (amount * _KOPECKS_PER_RUBLE).to_integral_value(rounding=FINANCIAL_ROUNDING)
        return cls(int(kopecks))

    def as_decimal(self) -> Decimal:
        return Decimal(self.kopecks) / _KOPECKS_PER_RUBLE

    def to_api(self) -> str:
        return format(self.as_decimal(), ".2f")


@dataclass(frozen=True, slots=True)
class PercentageRate:
    """An exact rate stored as integer basis points."""

    basis_points: int

    def __post_init__(self) -> None:
        _require_stored_integer(self.basis_points, name="basis_points")

    @classmethod
    def from_api(cls, percentage_points: str) -> "PercentageRate":
        percentage = _parse_api_decimal(percentage_points, name="API percentage rate")
        return cls.from_decimal(percentage)

    @classmethod
    def from_decimal(cls, percentage_points: Decimal) -> "PercentageRate":
        percentage = _require_finite_decimal(percentage_points, name="percentage rate")
        basis_points = (percentage * _BASIS_POINTS_PER_PERCENTAGE_POINT).to_integral_value(
            rounding=FINANCIAL_ROUNDING
        )
        return cls(int(basis_points))

    def as_percentage(self) -> Decimal:
        return Decimal(self.basis_points) / _BASIS_POINTS_PER_PERCENTAGE_POINT

    def as_fraction(self) -> Decimal:
        return Decimal(self.basis_points) / _BASIS_POINTS_PER_ONE

    def to_api(self) -> str:
        return format(self.as_percentage(), ".2f")
