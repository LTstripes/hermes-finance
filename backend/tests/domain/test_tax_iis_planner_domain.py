"""Pure current-state Tax/IIS Planner helpers."""

import pytest

from hermes_finance.domain.salary_tax import TaxBracketRule
from hermes_finance.domain.tax_iis_planner import tax_bracket_position


def _brackets() -> tuple[TaxBracketRule, ...]:
    return (
        TaxBracketRule(from_kopecks=0, to_kopecks=240_000_000, rate_bps=1300),
        TaxBracketRule(from_kopecks=240_000_000, to_kopecks=500_000_000, rate_bps=1500),
        TaxBracketRule(from_kopecks=500_000_000, to_kopecks=None, rate_bps=1800),
    )


def test_position_uses_next_bracket_at_exact_threshold() -> None:
    position = tax_bracket_position(_brackets(), 240_000_000)

    assert position.bracket.rate_bps == 1500
    assert position.bracket.from_kopecks == 240_000_000
    assert position.distance_to_next_threshold_kopecks == 260_000_000


def test_open_ended_bracket_has_no_next_threshold() -> None:
    position = tax_bracket_position(_brackets(), 500_000_000)

    assert position.bracket.rate_bps == 1800
    assert position.distance_to_next_threshold_kopecks is None


def test_negative_taxable_gross_is_rejected() -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        tax_bracket_position(_brackets(), -1)


def test_uncovered_taxable_gross_is_rejected() -> None:
    with pytest.raises(ValueError, match="do not cover"):
        tax_bracket_position(
            (TaxBracketRule(from_kopecks=100, to_kopecks=None, rate_bps=1300),),
            0,
        )
