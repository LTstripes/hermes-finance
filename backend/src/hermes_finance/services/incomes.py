from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.domain import IncomeType, RubleAmount
from hermes_finance.persistence import IncomeEntry
from hermes_finance.services._guard import (
    require_editable_child_month,
    require_editable_reporting_month,
)


class IncomeEntryNotFoundError(LookupError):
    pass


class SalaryCardinalityError(ValueError):
    pass


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
    if include_in_passive_income is True and income_type is not IncomeType.OTHER:
        raise ValueError("only other income may be included in passive income")
    return income_type is IncomeType.OTHER and bool(include_in_passive_income)


def _salary_entries(
    session: Session,
    reporting_month_id: int,
    *,
    exclude_entry_id: int | None = None,
) -> list[IncomeEntry]:
    statement = (
        select(IncomeEntry)
        .where(
            IncomeEntry.reporting_month_id == reporting_month_id,
            IncomeEntry.income_type == IncomeType.SALARY.value,
        )
        .order_by(IncomeEntry.id)
    )
    if exclude_entry_id is not None:
        statement = statement.where(IncomeEntry.id != exclude_entry_id)
    return list(session.scalars(statement))


def _require_salary_slot(
    session: Session,
    reporting_month_id: int,
    *,
    exclude_entry_id: int | None = None,
) -> None:
    if _salary_entries(
        session,
        reporting_month_id,
        exclude_entry_id=exclude_entry_id,
    ):
        raise SalaryCardinalityError("reporting month already has a salary income entry")


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
    require_editable_reporting_month(session, reporting_month_id)
    normalized_type = _coerce_income_type(income_type)
    if normalized_type is IncomeType.SALARY:
        _require_salary_slot(session, reporting_month_id)
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


def replace_salary_entry(
    session: Session,
    reporting_month_id: int,
    *,
    gross_amount: RubleAmount | str,
    tax_amount: RubleAmount | str,
    net_amount: RubleAmount | str,
) -> IncomeEntry | None:
    """Replace the month salary aggregate atomically and collapse legacy duplicates."""

    require_editable_reporting_month(session, reporting_month_id)
    gross_kopecks = _normalize_amount(gross_amount, field="gross_amount")
    tax_kopecks = _normalize_amount(tax_amount, field="tax_amount")
    net_kopecks = _normalize_amount(net_amount, field="net_amount")
    rows = _salary_entries(session, reporting_month_id)

    try:
        if gross_kopecks == 0 and tax_kopecks == 0 and net_kopecks == 0:
            for row in rows:
                session.delete(row)
            session.commit()
            return None

        if rows:
            canonical = rows[0]
        else:
            canonical = IncomeEntry(
                reporting_month_id=reporting_month_id,
                income_type=IncomeType.SALARY.value,
                name="Зарплата",
                gross_amount_kopecks=0,
                tax_amount_kopecks=0,
                net_amount_kopecks=0,
                received_at=None,
                is_recurring=True,
                include_in_cash_flow=True,
                include_in_passive_income=False,
                notes=None,
            )
            session.add(canonical)

        canonical.income_type = IncomeType.SALARY.value
        canonical.name = "Зарплата"
        canonical.gross_amount_kopecks = gross_kopecks
        canonical.tax_amount_kopecks = tax_kopecks
        canonical.net_amount_kopecks = net_kopecks
        canonical.is_recurring = True
        canonical.include_in_cash_flow = True
        canonical.include_in_passive_income = False

        for duplicate in rows[1:]:
            session.delete(duplicate)

        session.commit()
        session.refresh(canonical)
        return canonical
    except Exception:
        session.rollback()
        raise


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
    require_editable_child_month(session, entry)
    final_type = (
        _coerce_income_type(income_type)
        if income_type is not None
        else IncomeType(entry.income_type)
    )
    if final_type is IncomeType.SALARY:
        _require_salary_slot(
            session,
            entry.reporting_month_id,
            exclude_entry_id=entry.id,
        )
    if final_type is not IncomeType.OTHER and include_in_passive_income is True:
        _passive_income_flag(final_type, include_in_passive_income)
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
    if income_type is not None:
        entry.income_type = final_type.value
    if final_type is not IncomeType.OTHER:
        entry.include_in_passive_income = False
    elif include_in_passive_income is not None:
        entry.include_in_passive_income = _passive_income_flag(
            final_type, include_in_passive_income
        )
    if notes is not None:
        entry.notes = notes
    session.commit()
    session.refresh(entry)
    return entry


def delete_income_entry(session: Session, entry_id: int) -> None:
    entry = get_income_entry(session, entry_id)
    require_editable_child_month(session, entry)
    session.delete(entry)
    session.commit()
