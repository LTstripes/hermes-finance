from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hermes_finance.domain import ExpenseType, RubleAmount
from hermes_finance.persistence import ExpenseEntry, ReportingMonth, SavingAllocation
from hermes_finance.services.reporting_months import ReportingMonthNotFoundError


class ExpenseEntryNotFoundError(LookupError):
    pass


class SavingAllocationNotFoundError(LookupError):
    pass


def _require_reporting_month(session: Session, month_id: int) -> None:
    if session.get(ReportingMonth, month_id) is None:
        raise ReportingMonthNotFoundError(f"reporting month {month_id} was not found")


def _normalize_text(value: str, *, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


def _normalize_amount(amount: RubleAmount | str, *, field: str) -> int:
    if isinstance(amount, str):
        amount = RubleAmount.from_api(amount)
    if not isinstance(amount, RubleAmount):
        raise TypeError(f"{field} must be RubleAmount or decimal string")
    if amount.kopecks < 0:
        raise ValueError(f"{field} must not be negative")
    return amount.kopecks


def _coerce_expense_type(expense_type: ExpenseType | str) -> ExpenseType:
    try:
        return ExpenseType(expense_type)
    except ValueError as error:
        raise ValueError(f"unsupported expense type: {expense_type!r}") from error


def list_expense_entries(session: Session) -> list[ExpenseEntry]:
    return list(
        session.scalars(
            select(ExpenseEntry).order_by(ExpenseEntry.reporting_month_id, ExpenseEntry.id)
        )
    )


def get_expense_entry(session: Session, entry_id: int) -> ExpenseEntry:
    entry = session.get(ExpenseEntry, entry_id)
    if entry is None:
        raise ExpenseEntryNotFoundError(f"expense entry {entry_id} was not found")
    return entry


def total_expenses(
    session: Session, reporting_month_id: int, *, expense_type: ExpenseType | str | None = None
) -> RubleAmount:
    statement = select(func.coalesce(func.sum(ExpenseEntry.amount_kopecks), 0)).where(
        ExpenseEntry.reporting_month_id == reporting_month_id
    )
    if expense_type is not None:
        statement = statement.where(
            ExpenseEntry.expense_type == _coerce_expense_type(expense_type).value
        )
    total = session.scalar(statement)
    return RubleAmount(int(total or 0))


def total_mandatory_expenses(session: Session, reporting_month_id: int) -> RubleAmount:
    return total_expenses(session, reporting_month_id, expense_type=ExpenseType.MANDATORY)


def create_expense_entry(
    session: Session,
    *,
    reporting_month_id: int,
    category: str,
    amount: RubleAmount | str,
    expense_type: ExpenseType | str,
    is_recurring: bool = False,
    notes: str | None = None,
) -> ExpenseEntry:
    _require_reporting_month(session, reporting_month_id)
    entry = ExpenseEntry(
        reporting_month_id=reporting_month_id,
        category=_normalize_text(category, field="category"),
        amount_kopecks=_normalize_amount(amount, field="amount"),
        expense_type=_coerce_expense_type(expense_type).value,
        is_recurring=is_recurring,
        notes=notes,
    )
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


def update_expense_entry(
    session: Session,
    entry_id: int,
    *,
    category: str | None = None,
    amount: RubleAmount | str | None = None,
    expense_type: ExpenseType | str | None = None,
    is_recurring: bool | None = None,
    notes: str | None = None,
) -> ExpenseEntry:
    entry = get_expense_entry(session, entry_id)
    if category is not None:
        entry.category = _normalize_text(category, field="category")
    if amount is not None:
        entry.amount_kopecks = _normalize_amount(amount, field="amount")
    if expense_type is not None:
        entry.expense_type = _coerce_expense_type(expense_type).value
    if is_recurring is not None:
        entry.is_recurring = is_recurring
    if notes is not None:
        entry.notes = notes
    session.commit()
    session.refresh(entry)
    return entry


def delete_expense_entry(session: Session, entry_id: int) -> None:
    entry = get_expense_entry(session, entry_id)
    session.delete(entry)
    session.commit()


def list_saving_allocations(session: Session) -> list[SavingAllocation]:
    return list(
        session.scalars(
            select(SavingAllocation).order_by(
                SavingAllocation.reporting_month_id, SavingAllocation.id
            )
        )
    )


def get_saving_allocation(session: Session, allocation_id: int) -> SavingAllocation:
    allocation = session.get(SavingAllocation, allocation_id)
    if allocation is None:
        raise SavingAllocationNotFoundError(f"saving allocation {allocation_id} was not found")
    return allocation


def total_saving_allocations(session: Session, reporting_month_id: int) -> RubleAmount:
    total = session.scalar(
        select(func.coalesce(func.sum(SavingAllocation.amount_kopecks), 0)).where(
            SavingAllocation.reporting_month_id == reporting_month_id
        )
    )
    return RubleAmount(int(total or 0))


def create_saving_allocation(
    session: Session,
    *,
    reporting_month_id: int,
    destination: str,
    amount: RubleAmount | str,
    notes: str | None = None,
) -> SavingAllocation:
    _require_reporting_month(session, reporting_month_id)
    allocation = SavingAllocation(
        reporting_month_id=reporting_month_id,
        destination=_normalize_text(destination, field="destination"),
        amount_kopecks=_normalize_amount(amount, field="amount"),
        notes=notes,
    )
    session.add(allocation)
    session.commit()
    session.refresh(allocation)
    return allocation


def update_saving_allocation(
    session: Session,
    allocation_id: int,
    *,
    destination: str | None = None,
    amount: RubleAmount | str | None = None,
    notes: str | None = None,
) -> SavingAllocation:
    allocation = get_saving_allocation(session, allocation_id)
    if destination is not None:
        allocation.destination = _normalize_text(destination, field="destination")
    if amount is not None:
        allocation.amount_kopecks = _normalize_amount(amount, field="amount")
    if notes is not None:
        allocation.notes = notes
    session.commit()
    session.refresh(allocation)
    return allocation


def delete_saving_allocation(session: Session, allocation_id: int) -> None:
    allocation = get_saving_allocation(session, allocation_id)
    session.delete(allocation)
    session.commit()
