"""Year-scoped administration for progressive salary-tax brackets.

R02-17 / ADR 0006 defines one complete bracket set per calendar tax year.
Public administration replaces a complete set atomically and years containing
closed reporting months are immutable until those months are explicitly reopened.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from hermes_finance.domain import ReportingMonthStatus, RubleAmount
from hermes_finance.domain.salary_tax import TaxBracketRule
from hermes_finance.persistence import ReportingMonth, TaxBracket

TAX_BRACKETS_CONTRACT_VERSION = "tax_brackets_year_v1"
TAX_BRACKETS_SOURCE_OFFICIAL = "official_default"
TAX_BRACKETS_SOURCE_MANUAL = "manual_configuration"


class TaxBracketNotFoundError(LookupError):
    pass


class TaxBracketYearLockedError(RuntimeError):
    def __init__(self, year: int, closed_months: tuple[int, ...]) -> None:
        self.year = year
        self.closed_months = closed_months
        months = ", ".join(f"{year:04d}-{month:02d}" for month in closed_months)
        super().__init__(f"tax brackets for {year} are locked by closed month(s): {months}")


# Official progressive НДФЛ scale introduced in 2025 (ФЗ-176-ФЗ of 12.07.2024).
# Thresholds are integer kopecks; rates are integer basis points.
# Source: https://www.nalog.gov.ru/rn77/news/tax_doc_news/15562179/
_DEFAULT_BRACKETS: tuple[tuple[int, int | None, int], ...] = (
    (0, 240_000_000, 1300),
    (240_000_000, 500_000_000, 1500),
    (500_000_000, 2_000_000_000, 1800),
    (2_000_000_000, 5_000_000_000, 2000),
    (5_000_000_000, None, 2200),
)


def official_default_tax_bracket_rules() -> tuple[TaxBracketRule, ...]:
    return tuple(
        TaxBracketRule(from_kopecks=lower, to_kopecks=upper, rate_bps=rate)
        for lower, upper, rate in _DEFAULT_BRACKETS
    )


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
    if rate_bps < 0 or rate_bps > 10_000:
        raise ValueError("rate_bps must be between 0 and 10000")
    return rate_bps


def _as_rule(bracket: TaxBracket | TaxBracketRule) -> TaxBracketRule:
    if isinstance(bracket, TaxBracketRule):
        return bracket
    return TaxBracketRule(
        from_kopecks=bracket.threshold_from_kopecks,
        to_kopecks=bracket.threshold_to_kopecks,
        rate_bps=bracket.rate_bps,
    )


def validate_complete_tax_bracket_rules(
    brackets: Iterable[TaxBracketRule],
) -> tuple[TaxBracketRule, ...]:
    rules = tuple(sorted(brackets, key=lambda item: item.from_kopecks))
    if not rules:
        raise ValueError("tax brackets must not be empty")
    if rules[0].from_kopecks != 0:
        raise ValueError("first tax bracket must start at zero")

    previous_upper: int | None = None
    for index, rule in enumerate(rules):
        if rule.from_kopecks < 0:
            raise ValueError(f"bracket {index}: threshold_from must not be negative")
        _validate_rate_bps(rule.rate_bps)

        is_last = index == len(rules) - 1
        if rule.to_kopecks is None:
            if not is_last:
                raise ValueError(f"bracket {index}: only the final bracket may be open-ended")
        else:
            if rule.to_kopecks <= rule.from_kopecks:
                raise ValueError(f"bracket {index}: threshold_to must be greater than threshold_from")
            if is_last:
                raise ValueError("final tax bracket must be open-ended")

        if index > 0 and rule.from_kopecks != previous_upper:
            raise ValueError(
                f"bracket {index}: tax brackets must be contiguous without gaps or overlaps"
            )
        previous_upper = rule.to_kopecks

    return rules


def list_tax_brackets(session: Session, year: int) -> list[TaxBracket]:
    return list(
        session.scalars(
            select(TaxBracket)
            .where(TaxBracket.year == year)
            .order_by(TaxBracket.threshold_from_kopecks)
        )
    )


def effective_tax_bracket_rules(session: Session, year: int) -> tuple[TaxBracketRule, ...]:
    existing = list_tax_brackets(session, year)
    if not existing:
        return official_default_tax_bracket_rules()
    return tuple(_as_rule(bracket) for bracket in existing)


def tax_bracket_source(brackets: Iterable[TaxBracket | TaxBracketRule]) -> str:
    rules = tuple(_as_rule(bracket) for bracket in brackets)
    return (
        TAX_BRACKETS_SOURCE_OFFICIAL
        if rules == official_default_tax_bracket_rules()
        else TAX_BRACKETS_SOURCE_MANUAL
    )


def closed_month_numbers_for_tax_year(session: Session, year: int) -> tuple[int, ...]:
    return tuple(
        int(month)
        for month in session.scalars(
            select(ReportingMonth.month)
            .where(
                ReportingMonth.year == year,
                ReportingMonth.status == ReportingMonthStatus.CLOSED.value,
            )
            .order_by(ReportingMonth.month)
        )
    )


def ensure_tax_bracket_year_mutable(session: Session, year: int) -> None:
    closed_months = closed_month_numbers_for_tax_year(session, year)
    if closed_months:
        raise TaxBracketYearLockedError(year, closed_months)


def get_tax_bracket(session: Session, bracket_id: int) -> TaxBracket:
    bracket = session.get(TaxBracket, bracket_id)
    if bracket is None:
        raise TaxBracketNotFoundError(f"tax bracket {bracket_id} was not found")
    return bracket


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
        lower = max(b_from, threshold_from)
        if b_to is not None and threshold_to is not None:
            upper = min(b_to, threshold_to)
        elif b_to is not None:
            upper = b_to
        elif threshold_to is not None:
            upper = threshold_to
        else:
            upper = None
        if upper is None or lower < upper:
            raise ValueError(
                f"new bracket [{threshold_from}, {threshold_to}] overlaps "
                f"existing bracket [{b_from}, {b_to}] for year {year}"
            )


def create_tax_bracket(
    session: Session,
    *,
    year: int,
    threshold_from: RubleAmount | str,
    threshold_to: RubleAmount | str | None = None,
    rate_bps: int,
) -> TaxBracket:
    ensure_tax_bracket_year_mutable(session, year)
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
    ensure_tax_bracket_year_mutable(session, bracket.year)
    if new_year != bracket.year:
        ensure_tax_bracket_year_mutable(session, new_year)

    new_from = (
        _normalize_kopecks(threshold_from, field="threshold_from")
        if threshold_from is not None
        else bracket.threshold_from_kopecks
    )
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
    ensure_tax_bracket_year_mutable(session, bracket.year)
    session.delete(bracket)
    session.commit()


def replace_tax_brackets_for_year(
    session: Session,
    year: int,
    brackets: Iterable[TaxBracketRule],
) -> list[TaxBracket]:
    """Atomically replace one mutable tax year's complete rule set."""
    ensure_tax_bracket_year_mutable(session, year)
    rules = validate_complete_tax_bracket_rules(brackets)

    try:
        session.execute(delete(TaxBracket).where(TaxBracket.year == year))
        for rule in rules:
            session.add(
                TaxBracket(
                    year=year,
                    threshold_from_kopecks=rule.from_kopecks,
                    threshold_to_kopecks=rule.to_kopecks,
                    rate_bps=rule.rate_bps,
                )
            )
        session.commit()
    except Exception:
        session.rollback()
        raise
    return list_tax_brackets(session, year)


def get_or_create_default_tax_brackets(
    session: Session, year: int, *, commit: bool = True
) -> list[TaxBracket]:
    """Return persisted rules, seeding the official default set when empty.

    This compatibility/read-calculation path is intentionally separate from
    user administration. It may seed defaults even when a year is closed,
    because it does not reinterpret an existing configured rule set.
    """
    existing = list_tax_brackets(session, year)
    if existing:
        return existing

    for rule in official_default_tax_bracket_rules():
        session.add(
            TaxBracket(
                year=year,
                threshold_from_kopecks=rule.from_kopecks,
                threshold_to_kopecks=rule.to_kopecks,
                rate_bps=rule.rate_bps,
            )
        )
    if commit:
        session.commit()
    else:
        session.flush()
    return list_tax_brackets(session, year)
