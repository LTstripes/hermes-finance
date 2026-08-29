"""Exact, fail-closed XIRR primitives.

The solver works on signed integer kopecks and exact :class:`~decimal.Decimal`
values.  It accepts no inferred or floating-point cash flows.  A rate is
returned only when one numerically converged root can be identified; histories
without a valid or unambiguous root remain explicitly unavailable.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, DecimalException, localcontext
from enum import StrEnum

_DAYS_PER_YEAR = Decimal(365)
_ZERO = Decimal(0)
_ROOT_TOLERANCE = Decimal("1e-28")
_SCAN_MIN = Decimal("-128")
_SCAN_MAX = Decimal("128")
_SCAN_STEP = Decimal("0.5")
_DEFAULT_MAX_ITERATIONS = 256
_SOLVER_PRECISION = 60


class XirrAvailabilityStatus(StrEnum):
    """Whether a single annualized XIRR value was safely computed."""

    AVAILABLE = "available"
    NOT_COMPUTABLE = "not_computable"


class XirrQuality(StrEnum):
    """Quality metadata for a calculated or unavailable XIRR result."""

    EXACT = "exact"
    UNAVAILABLE = "unavailable"


class XirrReasonCode(StrEnum):
    """Stable reasons for solver-level XIRR unavailability."""

    NO_VALID_ROOT = "not_computable_xirr_no_valid_root"
    CONVERGENCE_FAILED = "not_computable_xirr_convergence_failed"
    MULTIPLE_ROOTS = "not_computable_xirr_multiple_roots"


@dataclass(frozen=True, slots=True)
class XirrCashFlow:
    """One investor-perspective cash flow in signed integer kopecks.

    Negative amounts are owner contributions and positive amounts are owner
    receipts.  ``event_date`` is date-only by contract; intra-day ordering is
    intentionally outside this model.
    """

    event_date: date
    amount_kopecks: int

    def __post_init__(self) -> None:
        if type(self.event_date) is not date:
            raise TypeError("event_date must be a date")
        if isinstance(self.amount_kopecks, bool) or not isinstance(self.amount_kopecks, int):
            raise TypeError("amount_kopecks must be an int")

    @property
    def date(self) -> date:
        """Compatibility spelling for callers that use ``date``."""

        return self.event_date

    @property
    def amount(self) -> int:
        """Compatibility spelling for the signed minor-unit amount."""

        return self.amount_kopecks


@dataclass(frozen=True, slots=True)
class XirrResult:
    """Fail-closed result of one exact XIRR calculation."""

    availability: XirrAvailabilityStatus
    quality: XirrQuality
    annualized_rate: Decimal | None
    reason_codes: tuple[str, ...] = ()
    iterations: int = 0

    @property
    def is_available(self) -> bool:
        return self.availability is XirrAvailabilityStatus.AVAILABLE

    @property
    def rate(self) -> Decimal | None:
        """Compatibility spelling for the annualized fractional rate."""

        return self.annualized_rate


def _unavailable(reason: XirrReasonCode, *, iterations: int = 0) -> XirrResult:
    return XirrResult(
        availability=XirrAvailabilityStatus.NOT_COMPUTABLE,
        quality=XirrQuality.UNAVAILABLE,
        annualized_rate=None,
        reason_codes=(reason.value,),
        iterations=iterations,
    )


def _normalise_cash_flows(
    cash_flows: Iterable[XirrCashFlow],
) -> tuple[tuple[date, int], ...]:
    amounts_by_date: dict[date, int] = {}
    for cash_flow in cash_flows:
        if not isinstance(cash_flow, XirrCashFlow):
            raise TypeError("cash_flows must contain XirrCashFlow values")
        amounts_by_date[cash_flow.event_date] = (
            amounts_by_date.get(cash_flow.event_date, 0) + cash_flow.amount_kopecks
        )
    return tuple(
        (event_date, amount)
        for event_date, amount in sorted(amounts_by_date.items())
        if amount != 0
    )


def _scaled_npv(
    log_growth: Decimal,
    cash_flows: tuple[tuple[int, Decimal], ...],
) -> Decimal:
    """Return NPV up to a positive scale factor.

    Working in ``log(1 + rate)`` keeps the domain ``rate > -1`` automatic.
    Scaling by the largest exponent avoids overflow for long histories while
    preserving the sign and all roots of the NPV function.
    """

    exponents = tuple(-years * log_growth for _, years in cash_flows)
    maximum_exponent = max(exponents)
    return sum(
        (
            Decimal(amount) * (exponent - maximum_exponent).exp()
            for (amount, _), exponent in zip(cash_flows, exponents, strict=True)
        ),
        _ZERO,
    )


def _signs_differ(left: Decimal, right: Decimal) -> bool:
    return (left < _ZERO and right > _ZERO) or (left > _ZERO and right < _ZERO)


def _scan_root_candidates(
    npv: Callable[[Decimal], Decimal],
) -> tuple[tuple[Decimal, ...], tuple[tuple[Decimal, Decimal, Decimal, Decimal], ...]]:
    exact_roots: list[Decimal] = []
    brackets: list[tuple[Decimal, Decimal, Decimal, Decimal]] = []
    left = _SCAN_MIN
    left_value = npv(left)
    while left < _SCAN_MAX:
        right = min(left + _SCAN_STEP, _SCAN_MAX)
        right_value = npv(right)
        if left_value == _ZERO:
            exact_roots.append(left)
        if left_value != _ZERO and right_value != _ZERO and _signs_differ(left_value, right_value):
            brackets.append((left, right, left_value, right_value))
        left = right
        left_value = right_value
    if left_value == _ZERO:
        exact_roots.append(left)
    return tuple(exact_roots), tuple(brackets)


def _bisect_root(
    npv: Callable[[Decimal], Decimal],
    *,
    left: Decimal,
    right: Decimal,
    left_value: Decimal,
    max_iterations: int,
) -> tuple[Decimal, int, bool]:
    midpoint = (left + right) / Decimal(2)
    for iteration in range(1, max_iterations + 1):
        midpoint = (left + right) / Decimal(2)
        midpoint_value = npv(midpoint)
        if midpoint_value == _ZERO:
            return midpoint, iteration, True
        if right - left <= _ROOT_TOLERANCE:
            return midpoint, iteration, True
        if _signs_differ(left_value, midpoint_value):
            right = midpoint
        else:
            left = midpoint
            left_value = midpoint_value
    return midpoint, max_iterations, False


def _deduplicate_roots(roots: Iterable[Decimal]) -> tuple[Decimal, ...]:
    unique: list[Decimal] = []
    for root in sorted(roots):
        if not unique or abs(root - unique[-1]) > _ROOT_TOLERANCE * Decimal(10):
            unique.append(root)
    return tuple(unique)


def calculate_xirr(
    cash_flows: Iterable[XirrCashFlow],
    *,
    max_iterations: int = _DEFAULT_MAX_ITERATIONS,
) -> XirrResult:
    """Calculate one annualized XIRR from exact dated signed cash flows.

    The search is deterministic and bracketed.  It never uses binary floats,
    an initial guess, a provider, or a silently selected root.  A caller gets
    an unavailable result when there is no sign-changing root, convergence
    fails, or more than one root is found in the supported domain.
    """

    if isinstance(max_iterations, bool) or not isinstance(max_iterations, int):
        raise TypeError("max_iterations must be an int")
    if max_iterations <= 0:
        return _unavailable(XirrReasonCode.CONVERGENCE_FAILED)

    normalised = _normalise_cash_flows(cash_flows)
    if len(normalised) < 2 or normalised[0][0] == normalised[-1][0]:
        return _unavailable(XirrReasonCode.NO_VALID_ROOT)

    amounts = tuple(amount for _, amount in normalised)
    if not any(amount < 0 for amount in amounts) or not any(amount > 0 for amount in amounts):
        return _unavailable(XirrReasonCode.NO_VALID_ROOT)

    first_date = normalised[0][0]
    cash_flows_with_time = tuple(
        (
            amount,
            Decimal((event_date - first_date).days) / _DAYS_PER_YEAR,
        )
        for event_date, amount in normalised
    )

    try:
        with localcontext() as context:
            context.prec = max(context.prec, _SOLVER_PRECISION)

            def npv(log_growth: Decimal) -> Decimal:
                return _scaled_npv(log_growth, cash_flows_with_time)

            exact_roots, brackets = _scan_root_candidates(npv)
            roots = list(exact_roots)
            total_iterations = 0
            converged = True
            for left, right, left_value, _ in brackets:
                root, iterations, root_converged = _bisect_root(
                    npv,
                    left=left,
                    right=right,
                    left_value=left_value,
                    max_iterations=max_iterations,
                )
                roots.append(root)
                total_iterations += iterations
                converged = converged and root_converged

            unique_roots = _deduplicate_roots(roots)
            if not unique_roots:
                return _unavailable(XirrReasonCode.NO_VALID_ROOT)
            if not converged:
                return _unavailable(
                    XirrReasonCode.CONVERGENCE_FAILED,
                    iterations=total_iterations,
                )
            if len(unique_roots) > 1:
                return _unavailable(
                    XirrReasonCode.MULTIPLE_ROOTS,
                    iterations=total_iterations,
                )

            annualized_rate = unique_roots[0].exp() - Decimal(1)
            if not annualized_rate.is_finite():
                return _unavailable(
                    XirrReasonCode.CONVERGENCE_FAILED,
                    iterations=total_iterations,
                )
            return XirrResult(
                availability=XirrAvailabilityStatus.AVAILABLE,
                quality=XirrQuality.EXACT,
                annualized_rate=annualized_rate,
                iterations=total_iterations,
            )
    except DecimalException:
        return _unavailable(XirrReasonCode.CONVERGENCE_FAILED)


# Discoverable aliases for downstream callers.
compute_xirr = calculate_xirr
xirr = calculate_xirr
