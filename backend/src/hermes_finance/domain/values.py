from dataclasses import dataclass
from decimal import Decimal, DecimalException

FINANCIAL_ROUNDING = __import__("decimal").ROUND_HALF_UP
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


def _scaled_half_up(d: Decimal, scale_exp: int) -> int:
    """Exact integer of round_half_up(d * 10**scale_exp).

    Uses the Decimal tuple (sign, digits, exponent) as exact rational
    m * 10**exp, so no context precision ever truncates.  Ties go away
    from zero (ROUND_HALF_UP).  scale_exp is 2 for *100 conversions.
    """
    sign, digits, exp = d.as_tuple()
    if not digits:
        return 0
    m = 0
    for dig in digits:
        m = m * 10 + dig
    total_exp = exp + scale_exp
    is_negative = bool(sign)
    if total_exp >= 0:
        result = m * (10**total_exp)
    else:
        divisor = 10 ** (-total_exp)
        q, r = divmod(m, divisor)
        if r * 2 >= divisor:
            q += 1
        result = q
    return -result if is_negative else result


def _int_scaled_to_decimal(n: int, scale: int) -> Decimal:
    """Exact Decimal for n / 10**scale without any context."""
    if n == 0:
        return Decimal(0)
    sign = "-" if n < 0 else ""
    s = str(abs(n)).zfill(scale + 1)
    if scale == 0:
        return Decimal(sign + s)
    int_part = s[:-scale].lstrip("0") or "0"
    frac_part = s[-scale:]
    return Decimal(f"{sign}{int_part}.{frac_part}")


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
        kopecks = _scaled_half_up(amount, 2)
        return cls(int(kopecks))

    def as_decimal(self) -> Decimal:
        return _int_scaled_to_decimal(self.kopecks, 2)

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
        basis_points = _scaled_half_up(percentage, 2)
        return cls(int(basis_points))

    def as_percentage(self) -> Decimal:
        return _int_scaled_to_decimal(self.basis_points, 2)

    def as_fraction(self) -> Decimal:
        return _int_scaled_to_decimal(self.basis_points, 4)

    def to_api(self) -> str:
        return format(self.as_percentage(), ".2f")
