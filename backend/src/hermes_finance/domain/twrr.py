"""Exact, fail-closed time-weighted return primitives.

The calculator consumes only trusted persisted valuation values and explicit
pre/post observations around external-flow boundaries.  It never estimates a
valuation, assumes an intra-day order, or turns a capital delta into return.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, localcontext
from enum import StrEnum
from typing import Iterable


class TwrrAvailabilityStatus(StrEnum):
    """Whether an exact whole-period TWRR was computed."""

    AVAILABLE = "available"
    NOT_COMPUTABLE = "not_computable"


class TwrrQuality(StrEnum):
    """Quality metadata for a calculated or unavailable TWRR."""

    EXACT = "exact"
    UNAVAILABLE = "unavailable"


class TwrrReasonCode(StrEnum):
    """Stable calculator-level TWRR failure reasons."""

    ZERO_OR_NEGATIVE_DENOMINATOR = "not_computable_twrr_zero_or_negative_denominator"


@dataclass(frozen=True, slots=True)
class TwrrBoundary:
    """One ordered external-flow boundary with exact observed values.

    ``signed_flow_kopecks`` is positive for a contribution and negative for a
    withdrawal from the selected portfolio's perspective.  The service layer
    creates one record per explicit flow or same-date flow group.
    """

    event_date: date
    signed_flow_kopecks: int
    pre_value_kopecks: int
    post_value_kopecks: int

    def __post_init__(self) -> None:
        if type(self.event_date) is not date:
            raise TypeError("event_date must be a date")
        for name, value in (
            ("signed_flow_kopecks", self.signed_flow_kopecks),
            ("pre_value_kopecks", self.pre_value_kopecks),
            ("post_value_kopecks", self.post_value_kopecks),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an int")
        if self.pre_value_kopecks < 0 or self.post_value_kopecks < 0:
            raise ValueError("observed boundary values must not be negative")


@dataclass(frozen=True, slots=True)
class TwrrResult:
    """Fail-closed result of one exact TWRR calculation."""

    availability: TwrrAvailabilityStatus
    quality: TwrrQuality
    return_rate: Decimal | None
    reason_codes: tuple[str, ...] = ()

    @property
    def is_available(self) -> bool:
        return self.availability is TwrrAvailabilityStatus.AVAILABLE

    @property
    def rate(self) -> Decimal | None:
        """Compatibility spelling for the fractional period return."""

        return self.return_rate


def _unavailable(reason: TwrrReasonCode) -> TwrrResult:
    return TwrrResult(
        availability=TwrrAvailabilityStatus.NOT_COMPUTABLE,
        quality=TwrrQuality.UNAVAILABLE,
        return_rate=None,
        reason_codes=(reason.value,),
    )


def _validate_value(value: int, *, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int")
    if value < 0:
        raise ValueError(f"{name} must not be negative")


def calculate_twrr(
    opening_value_kopecks: int,
    closing_value_kopecks: int,
    boundaries: Iterable[TwrrBoundary] = (),
) -> TwrrResult:
    """Calculate an exact chained TWRR from persisted observations.

    For every boundary the preceding subperiod ends at ``pre``.  The flow is
    applied explicitly between ``pre`` and ``post``; the next subperiod starts
    at ``post``.  All denominators must be strictly positive, otherwise the
    return is unavailable because the factor is undefined.
    """

    _validate_value(opening_value_kopecks, name="opening_value_kopecks")
    _validate_value(closing_value_kopecks, name="closing_value_kopecks")
    ordered_boundaries = tuple(boundaries)
    if any(not isinstance(boundary, TwrrBoundary) for boundary in ordered_boundaries):
        raise TypeError("boundaries must contain TwrrBoundary values")
    if any(
        earlier.event_date > later.event_date
        for earlier, later in zip(ordered_boundaries, ordered_boundaries[1:])
    ):
        raise ValueError("boundaries must be ordered by event_date")

    factor = Decimal(1)
    previous_value = opening_value_kopecks
    with localcontext() as context:
        context.prec = 60
        for boundary in ordered_boundaries:
            if previous_value <= 0:
                return _unavailable(TwrrReasonCode.ZERO_OR_NEGATIVE_DENOMINATOR)
            post_flow_value = boundary.pre_value_kopecks + boundary.signed_flow_kopecks
            if post_flow_value <= 0:
                return _unavailable(TwrrReasonCode.ZERO_OR_NEGATIVE_DENOMINATOR)
            factor *= Decimal(boundary.pre_value_kopecks) / Decimal(previous_value)
            factor *= Decimal(boundary.post_value_kopecks) / Decimal(post_flow_value)
            previous_value = boundary.post_value_kopecks

        if previous_value <= 0:
            return _unavailable(TwrrReasonCode.ZERO_OR_NEGATIVE_DENOMINATOR)
        factor *= Decimal(closing_value_kopecks) / Decimal(previous_value)
        return TwrrResult(
            availability=TwrrAvailabilityStatus.AVAILABLE,
            quality=TwrrQuality.EXACT,
            return_rate=factor - Decimal(1),
        )


# Discoverable aliases for downstream callers.
compute_twrr = calculate_twrr
twrr = calculate_twrr
