"""Pure helpers for the bounded current-state tax planner.

The planner does not forecast salary or tax.  It only locates the currently
accumulated taxable gross inside an already configured, complete tax scale and
reports the remaining distance to that scale's next finite threshold.
"""

from __future__ import annotations

from dataclasses import dataclass

from hermes_finance.domain.salary_tax import TaxBracketRule


@dataclass(frozen=True, slots=True)
class TaxBracketPosition:
    """The configured bracket containing the current taxable gross."""

    bracket: TaxBracketRule
    distance_to_next_threshold_kopecks: int | None


def tax_bracket_position(
    brackets: tuple[TaxBracketRule, ...], taxable_gross_ytd_kopecks: int
) -> TaxBracketPosition:
    """Return the bracket for a non-negative accumulated taxable gross.

    ``brackets`` are expected to have been validated by the tax-bracket
    application service.  Bounds use the same half-open semantics as the
    progressive-tax calculator: a gross exactly at a threshold belongs to the
    next bracket.  An open-ended final bracket has no next threshold.
    """
    if isinstance(taxable_gross_ytd_kopecks, bool) or not isinstance(
        taxable_gross_ytd_kopecks, int
    ):
        raise TypeError("taxable_gross_ytd_kopecks must be an int")
    if taxable_gross_ytd_kopecks < 0:
        raise ValueError("taxable_gross_ytd_kopecks must not be negative")

    for bracket in brackets:
        if taxable_gross_ytd_kopecks < bracket.from_kopecks:
            break
        if bracket.to_kopecks is None or taxable_gross_ytd_kopecks < bracket.to_kopecks:
            distance = (
                None
                if bracket.to_kopecks is None
                else bracket.to_kopecks - taxable_gross_ytd_kopecks
            )
            return TaxBracketPosition(
                bracket=bracket,
                distance_to_next_threshold_kopecks=distance,
            )

    raise ValueError("tax brackets do not cover taxable gross YTD")
