"""CRUD service for configurable progressive tax brackets (НДФЛ).

Tax brackets are stored in a configuration table (``tax_brackets``) so that
thresholds and rates can be edited without code changes (MASTER_SPEC §10.14).

Official progressive scale (ФЗ-176-ФЗ of 12.07.2024, in force since 2025):
    up to 2 400 000 RUB       — 13%
    2 400 000 – 5 000 000     — 15%
    5 000 000 – 20 000 000    — 18%
    20 000 000 – 50 000 000   — 20%
    over 50 000 000           — 22%

Source: https://www.nalog.gov.ru/rn77/news/tax_doc_news/15562179/
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.domain import RubleAmount
from hermes_finance.persistence import TaxBracket


class TaxBracketNotFoundError(LookupError):
    pass


def _normalize_kopecks(amount: RubleAmount | str, *, field: str) -> int:
    if isinstance(amount, str):
        amount = RubleAmount.from_api(amount)
    if not isinstance(amount, RubleAmount):
        raise TypeError(f"{field} must be RubleAmount or decimal string")
    if amount.kopecks < 0:
        raise ValueError(f"{field} must not be negative")
    return amount.kopecks


def _validate_rate_bps(rate_bps: int) -> int:
    if not isinstance(rate_bps, int) or isinstance(rate_bps, bool):
        raise TypeError("rate_bps must be an int")
    if rate_bps < 0:
        raise ValueError("rate_bps must not be negative")
    return rate_bps


def _validate_no_overlap(
    session: Session,
    year: int,
    threshold_from: int,
    threshold_to: int | None,
    *,
    exclude_id: int | None = None,
) -> None:
    existing = list_tax_brackets(session, year)
    for bracket in existing:
        if exclude_id is not None and bracket.id == exclude_id:
            continue
        b_from = bracket.threshold_from_kopecks
        b_to = bracket.threshold_to_kopecks
        new_to = threshold_to
        # Overlap check: ranges [from, to) overlap if max(from) < min(to).
        lower = max(b_from, threshold_from)
        if b_to is not None and new_to is not None:
            upper = min(b_to, new_to)
        elif b_to is not None:
            upper = b_to
        elif new_to is not None:
            upper = new_to
        else:
            upper = None  # both open-ended — overlap
        if upper is None or lower < upper:
            raise ValueError(
                f"new bracket [{threshold_from}, {threshold_to}] overlaps "
                f"existing bracket [{b_from}, {b_to}] for year {year}"
            )


def list_tax_brackets(session: Session, year: int) -> list[TaxBracket]:
    return list(
        session.scalars(
            select(TaxBracket)
            .where(TaxBracket.year == year)
            .order_by(TaxBracket.threshold_from_kopecks)
        )
    )


def get_tax_bracket(session: Session, bracket_id: int) -> TaxBracket:
    bracket = session.get(TaxBracket, bracket_id)
    if bracket is None:
        raise TaxBracketNotFoundError(f"tax bracket {bracket_id} was not found")
    return bracket


def create_tax_bracket(
    session: Session,
    *,
    year: int,
    threshold_from: RubleAmount | str,
    threshold_to: RubleAmount | str | None = None,
    rate_bps: int,
) -> TaxBracket:
    from_kopecks = _normalize_kopecks(threshold_from, field="threshold_from")
    to_kopecks: int | None = None
    if threshold_to is not None:
        to_kopecks = _normalize_kopecks(threshold_to, field="threshold_to")
        if to_kopecks <= from_kopecks:
            raise ValueError("threshold_to must be greater than threshold_from")

    _validate_rate_bps(rate_bps)
    _validate_no_overlap(session, year, from_kopecks, to_kopecks)

    bracket = TaxBracket(
        year=year,
        threshold_from_kopecks=from_kopecks,
        threshold_to_kopecks=to_kopecks,
        rate_bps=rate_bps,
    )
    session.add(bracket)
    session.commit()
    session.refresh(bracket)
    return bracket


def update_tax_bracket(
    session: Session,
    bracket_id: int,
    *,
    year: int | None = None,
    threshold_from: RubleAmount | str | None = None,
    threshold_to: RubleAmount | str | None = None,
    rate_bps: int | None = None,
) -> TaxBracket:
    bracket = get_tax_bracket(session, bracket_id)

    new_year = year if year is not None else bracket.year
    new_from = (
        _normalize_kopecks(threshold_from, field="threshold_from")
        if threshold_from is not None
        else bracket.threshold_from_kopecks
    )
    new_to: int | None
    if threshold_to is not None:
        new_to = _normalize_kopecks(threshold_to, field="threshold_to")
        if new_to <= new_from:
            raise ValueError("threshold_to must be greater than threshold_from")
    else:
        new_to = bracket.threshold_to_kopecks

    new_rate = _validate_rate_bps(rate_bps) if rate_bps is not None else bracket.rate_bps

    _validate_no_overlap(session, new_year, new_from, new_to, exclude_id=bracket.id)

    bracket.year = new_year
    bracket.threshold_from_kopecks = new_from
    bracket.threshold_to_kopecks = new_to
    bracket.rate_bps = new_rate
    session.commit()
    session.refresh(bracket)
    return bracket


def delete_tax_bracket(session: Session, bracket_id: int) -> None:
    bracket = get_tax_bracket(session, bracket_id)
    session.delete(bracket)
    session.commit()


# Official 2025+ progressive НДФЛ brackets (ФЗ-176-ФЗ of 12.07.2024).
# Thresholds in kopecks, rates in basis points.
# Source: https://www.nalog.gov.ru/rn77/news/tax_doc_news/15562179/
_DEFAULT_BRACKETS: tuple[tuple[int, int | None, int], ...] = (
    (0, 240_000_000, 1300),
    (240_000_000, 500_000_000, 1500),
    (500_000_000, 2_000_000_000, 1800),
    (2_000_000_000, 5_000_000_000, 2000),
    (5_000_000_000, None, 2200),
)


def get_or_create_default_tax_brackets(session: Session, year: int) -> list[TaxBracket]:
    """Return tax brackets for ``year``, seeding the official defaults if empty.

    The five official progressive ranges (ФЗ-176-ФЗ of 12.07.2024) are seeded
    only when no rows exist for the given year.  Existing user-edited brackets
    are never overwritten.

    Source: https://www.nalog.gov.ru/rn77/news/tax_doc_news/15562179/
    """
    existing = list_tax_brackets(session, year)
    if existing:
        return existing

    for from_kopecks, to_kopecks, rate_bps in _DEFAULT_BRACKETS:
        session.add(
            TaxBracket(
                year=year,
                threshold_from_kopecks=from_kopecks,
                threshold_to_kopecks=to_kopecks,
                rate_bps=rate_bps,
            )
        )
    session.commit()
    return list_tax_brackets(session, year)
