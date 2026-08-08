"""Pure domain salary-tax (НДФЛ) calculator (framework-independent).

Implements MASTER_SPEC §10.14 progressive tax algorithm:

1. Take year-to-date taxable gross.
2. Split the current payment across active bracket ranges.
3. Apply the rate to the part inside each range.
4. Sum the tax.
5. Calculate ``calculated_net = payment_gross - tax``.
6. The actual employer-paid net is tracked separately (salary service).

Official progressive scale (ФЗ-176-ФЗ of 12.07.2024, in force since 2025):
    up to 2 400 000 RUB       — 13%
    2 400 000 – 5 000 000     — 15%
    5 000 000 – 20 000 000    — 18%
    20 000 000 – 50 000 000   — 20%
    over 50 000 000           — 22%

Source: https://www.nalog.gov.ru/rn77/news/tax_doc_news/15562179/

All money values are integer kopecks; rates are integer basis points.
Binary ``float`` is never used.  Division uses :class:`Decimal` with
:data:`FINANCIAL_ROUNDING` (ROUND_HALF_UP).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from hermes_finance.domain.values import FINANCIAL_ROUNDING

_BASIS_POINTS_DENOMINATOR = Decimal(10_000)


@dataclass(frozen=True, slots=True)
class TaxBracketRule:
    """A single progressive-tax range (pure-domain, no ORM)."""

    from_kopecks: int
    to_kopecks: int | None
    rate_bps: int


@dataclass(frozen=True, slots=True)
class TaxPart:
    """The slice of a payment that falls into one bracket range."""

    from_kopecks: int
    to_kopecks: int | None
    rate_bps: int
    taxable_kopecks: int
    tax_kopecks: int


@dataclass(frozen=True, slots=True)
class SalaryTaxInput:
    """Pure-domain input for the progressive-tax calculator."""

    ytd_gross_kopecks: int
    payment_gross_kopecks: int
    brackets: tuple[TaxBracketRule, ...]


@dataclass(frozen=True, slots=True)
class SalaryTaxResult:
    """Pure-domain output of the progressive-tax calculator."""

    tax_kopecks: int
    calculated_net_kopecks: int
    parts: tuple[TaxPart, ...]


def _validate_and_sort_brackets(
    brackets: tuple[TaxBracketRule, ...],
) -> list[TaxBracketRule]:
    """Sort ascending by ``from_kopecks`` and validate no gaps/overlaps.

    The sorted ranges must be contiguous: each bracket's lower bound must
    equal the previous bracket's upper bound.  The last bracket may have
    ``to_kopecks=None`` (open upper range).  A ``ValueError`` is raised
    for empty brackets, overlaps, or gaps.
    """
    if not brackets:
        raise ValueError("tax brackets must not be empty")

    sorted_brackets = sorted(brackets, key=lambda b: b.from_kopecks)

    for i, bracket in enumerate(sorted_brackets):
        if bracket.to_kopecks is not None and bracket.to_kopecks <= bracket.from_kopecks:
            raise ValueError(f"bracket {i}: upper bound must be greater than lower bound")
        if i == 0:
            continue
        prev = sorted_brackets[i - 1]
        if prev.to_kopecks is None:
            raise ValueError(
                f"bracket {i}: previous bracket has open upper bound, no further brackets allowed"
            )
        if bracket.from_kopecks < prev.to_kopecks:  # type: ignore[operator]
            raise ValueError(
                f"bracket {i}: lower bound {bracket.from_kopecks} "
                f"overlaps previous upper bound {prev.to_kopecks}"
            )
        if bracket.from_kopecks > prev.to_kopecks:  # type: ignore[operator]
            raise ValueError(
                f"bracket {i}: gap between previous upper bound "
                f"{prev.to_kopecks} and lower bound {bracket.from_kopecks}"
            )

    return sorted_brackets


def _compute_bracket_tax(taxable_kopecks: int, rate_bps: int) -> int:
    """Compute tax for a single bracket slice using Decimal roundup."""
    if taxable_kopecks == 0 or rate_bps == 0:
        return 0
    tax = (
        Decimal(taxable_kopecks) * Decimal(rate_bps) / _BASIS_POINTS_DENOMINATOR
    ).to_integral_value(rounding=FINANCIAL_ROUNDING)
    return int(tax)


def calculate_progressive_tax(input_data: SalaryTaxInput) -> SalaryTaxResult:
    """Calculate progressive НДФЛ for a single salary payment.

    The payment occupies the range ``[ytd_gross, ytd_gross + payment_gross)``
    and is split across bracket ranges.  Each overlapping slice is taxed at
    its bracket's rate.  Zero payment produces zero tax and zero net.

    Raises :class:`ValueError` if the brackets are empty, overlapping, or leave
    the payment range uncovered (defense in depth).
    """
    ytd = input_data.ytd_gross_kopecks
    payment = input_data.payment_gross_kopecks

    if payment == 0:
        return SalaryTaxResult(
            tax_kopecks=0,
            calculated_net_kopecks=0,
            parts=(),
        )

    if payment < 0:
        raise ValueError("payment_gross_kopecks must not be negative")
    if ytd < 0:
        raise ValueError("ytd_gross_kopecks must not be negative")

    sorted_brackets = _validate_and_sort_brackets(input_data.brackets)

    payment_start = ytd
    payment_end = ytd + payment

    # Verify coverage: the first bracket must start at or below ytd, and the
    # payment range must be fully covered up to the last bracket's upper bound
    # (which may be None for the open-ended final bracket).
    if sorted_brackets[0].from_kopecks > payment_start:
        raise ValueError(
            "brackets do not cover the start of the payment range "
            f"(first bracket starts at {sorted_brackets[0].from_kopecks}, "
            f"payment starts at {payment_start})"
        )

    parts: list[TaxPart] = []
    remaining_start = payment_start

    for bracket in sorted_brackets:
        if remaining_start >= payment_end:
            break

        upper = bracket.to_kopecks

        # Skip brackets entirely below the payment range.
        if upper is not None and upper <= remaining_start:
            continue

        # If this bracket's lower bound is above our current position,
        # there is an uncovered gap.
        if bracket.from_kopecks > remaining_start:
            raise ValueError(
                f"uncovered gap between {remaining_start} and "
                f"{bracket.from_kopecks} in bracket coverage"
            )

        slice_start = max(remaining_start, bracket.from_kopecks)
        if upper is None:
            slice_end = payment_end
        else:
            slice_end = min(payment_end, upper)

        taxable = slice_end - slice_start
        if taxable <= 0:
            continue

        tax = _compute_bracket_tax(taxable, bracket.rate_bps)
        parts.append(
            TaxPart(
                from_kopecks=bracket.from_kopecks,
                to_kopecks=bracket.to_kopecks,
                rate_bps=bracket.rate_bps,
                taxable_kopecks=taxable,
                tax_kopecks=tax,
            )
        )
        remaining_start = slice_end

    if remaining_start < payment_end:
        raise ValueError(
            f"brackets do not cover the full payment range "
            f"(covered up to {remaining_start} of {payment_end})"
        )

    total_tax = sum(p.tax_kopecks for p in parts)
    calculated_net = payment - total_tax

    return SalaryTaxResult(
        tax_kopecks=total_tax,
        calculated_net_kopecks=calculated_net,
        parts=tuple(parts),
    )
