from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.domain import IncomeType, RubleAmount
from hermes_finance.persistence import IncomeEntry, ReportingMonth
from hermes_finance.services.reporting_months import ReportingMonthNotFoundError


class IncomeEntryNotFoundError(LookupError):
    pass


def _require_reporting_month(session: Session, month_id: int) -> None:
    if session.get(ReportingMonth, month_id) is None:
        raise ReportingMonthNotFoundError(f"reporting month {month_id} was not found")


def _normalize_name(name: str) -> str:
    normalized = name.strip()
    if not normalized:
        raise ValueError("name must not be empty")
    return normalized


def _coerce_income_type(income_type: IncomeType | str) -> IncomeType:
    try:
        return IncomeType(income_type)
    except ValueError as error:
        raise ValueError(f"unsupported income type: {income_type!r}") from error


def _normalize_amount(amount: RubleAmount | str, *, field: str) -> int:
    if isinstance(amount, str):
        amount = RubleAmount.from_api(amount)
    if not isinstance(amount, RubleAmount):
        raise TypeError(f"{field} must be RubleAmount or decimal string")
    if amount.kopecks < 0:
        raise ValueError(f"{field} must not be negative")
    return amount.kopecks


def _passive_income_flag(
    income_type: IncomeType,
    include_in_passive_income: bool | None,
) -> bool:
    if income_type is IncomeType.CASHBACK:
        if include_in_passive_income is True:
            raise ValueError("cashback must not be included in passive income")
        return False
    return bool(include_in_passive_income)


def list_income_entries(session: Session) -> list[IncomeEntry]:
    return list(
        session.scalars(
            select(IncomeEntry).order_by(IncomeEntry.reporting_month_id, IncomeEntry.id)
        )
    )


def get_income_entry(session: Session, entry_id: int) -> IncomeEntry:
    entry = session.get(IncomeEntry, entry_id)
    if entry is None:
        raise IncomeEntryNotFoundError(f"income entry {entry_id} was not found")
    return entry


def create_income_entry(
    session: Session,
    *,
    reporting_month_id: int,
    income_type: IncomeType | str,
    name: str,
    gross_amount: RubleAmount | str,
    tax_amount: RubleAmount | str,
    net_amount: RubleAmount | str,
    received_at: date | None = None,
    is_recurring: bool = False,
    include_in_cash_flow: bool = True,
    include_in_passive_income: bool = False,
    notes: str | None = None,
) -> IncomeEntry:
    _require_reporting_month(session, reporting_month_id)
    normalized_type = _coerce_income_type(income_type)
    entry = IncomeEntry(
        reporting_month_id=reporting_month_id,
        income_type=normalized_type.value,
        name=_normalize_name(name),
        gross_amount_kopecks=_normalize_amount(gross_amount, field="gross_amount"),
        tax_amount_kopecks=_normalize_amount(tax_amount, field="tax_amount"),
        net_amount_kopecks=_normalize_amount(net_amount, field="net_amount"),
        received_at=received_at,
        is_recurring=is_recurring,
        include_in_cash_flow=include_in_cash_flow,
        include_in_passive_income=_passive_income_flag(normalized_type, include_in_passive_income),
        notes=notes,
    )
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


def update_income_entry(
    session: Session,
    entry_id: int,
    *,
    income_type: IncomeType | str | None = None,
    name: str | None = None,
    gross_amount: RubleAmount | str | None = None,
    tax_amount: RubleAmount | str | None = None,
    net_amount: RubleAmount | str | None = None,
    received_at: date | None = None,
    is_recurring: bool | None = None,
    include_in_cash_flow: bool | None = None,
    include_in_passive_income: bool | None = None,
    notes: str | None = None,
) -> IncomeEntry:
    entry = get_income_entry(session, entry_id)
    if income_type is not None:
        entry.income_type = _coerce_income_type(income_type).value
    if name is not None:
        entry.name = _normalize_name(name)
    if gross_amount is not None:
        entry.gross_amount_kopecks = _normalize_amount(gross_amount, field="gross_amount")
    if tax_amount is not None:
        entry.tax_amount_kopecks = _normalize_amount(tax_amount, field="tax_amount")
    if net_amount is not None:
        entry.net_amount_kopecks = _normalize_amount(net_amount, field="net_amount")
    if received_at is not None:
        entry.received_at = received_at
    if is_recurring is not None:
        entry.is_recurring = is_recurring
    if include_in_cash_flow is not None:
        entry.include_in_cash_flow = include_in_cash_flow
    if include_in_passive_income is not None:
        entry.include_in_passive_income = _passive_income_flag(
            IncomeType(entry.income_type), include_in_passive_income
        )
    if notes is not None:
        entry.notes = notes
    session.commit()
    session.refresh(entry)
    return entry


def delete_income_entry(session: Session, entry_id: int) -> None:
    entry = get_income_entry(session, entry_id)
    session.delete(entry)
    session.commit()
