from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hermes_finance.domain import LINKED_DEBT_ACCOUNT_TYPES, DebtType, PercentageRate, RubleAmount
from hermes_finance.persistence import Debt
from hermes_finance.services._guard import (
    require_editable_child_month,
    require_editable_reporting_month,
)
from hermes_finance.services.accounts import get_account
from hermes_finance.services.reporting_months import get_reporting_month

_UNSET: object = object()


class DebtNotFoundError(LookupError):
    pass


class DebtAccountLinkConflictError(ValueError):
    pass


def _normalize_text(value: str, *, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


def _normalize_balance(balance: RubleAmount | str) -> int:
    if isinstance(balance, str):
        balance = RubleAmount.from_api(balance)
    if not isinstance(balance, RubleAmount):
        raise TypeError("current_balance must be RubleAmount or decimal string")
    if balance.kopecks < 0:
        raise ValueError("current_balance must not be negative")
    return balance.kopecks


def _normalize_rate(annual_rate: PercentageRate | str | None, *, field: str) -> int | None:
    if annual_rate is None:
        return None
    if isinstance(annual_rate, str):
        annual_rate = PercentageRate.from_api(annual_rate)
    if not isinstance(annual_rate, PercentageRate):
        raise TypeError(f"{field} must be PercentageRate, decimal string or None")
    if annual_rate.basis_points < 0:
        raise ValueError(f"{field} must not be negative")
    return annual_rate.basis_points


def _coerce_debt_type(debt_type: DebtType | str) -> DebtType:
    try:
        return DebtType(debt_type)
    except ValueError as error:
        raise ValueError(f"unsupported debt type: {debt_type!r}") from error


def list_debts(session: Session) -> list[Debt]:
    return list(session.scalars(select(Debt).order_by(Debt.reporting_month_id, Debt.id)))


def list_linked_debts(
    session: Session,
    account_id: int,
    *,
    reporting_month_id: int | None = None,
) -> list[Debt]:
    """Read the account-side relation derived from authoritative debt rows."""
    get_account(session, account_id)
    if reporting_month_id is not None:
        get_reporting_month(session, reporting_month_id)

    statement = select(Debt).where(Debt.linked_account_id == account_id)
    if reporting_month_id is not None:
        statement = statement.where(Debt.reporting_month_id == reporting_month_id)
    statement = statement.order_by(Debt.reporting_month_id, Debt.id)
    return list(session.scalars(statement))


def get_debt(session: Session, debt_id: int) -> Debt:
    debt = session.get(Debt, debt_id)
    if debt is None:
        raise DebtNotFoundError(f"debt {debt_id} was not found")
    return debt


def total_debts(
    session: Session, reporting_month_id: int, *, include_in_liquid_capital_only: bool = False
) -> RubleAmount:
    statement = select(func.coalesce(func.sum(Debt.current_balance_kopecks), 0)).where(
        Debt.reporting_month_id == reporting_month_id
    )
    if include_in_liquid_capital_only:
        statement = statement.where(Debt.include_in_liquid_capital.is_(True))
    total = session.scalar(statement)
    return RubleAmount(int(total or 0))


def total_included_debts(session: Session, reporting_month_id: int) -> RubleAmount:
    return total_debts(session, reporting_month_id, include_in_liquid_capital_only=True)


def create_debt(
    session: Session,
    *,
    reporting_month_id: int,
    debt_type: DebtType | str,
    name: str,
    current_balance: RubleAmount | str,
    include_in_liquid_capital: bool = True,
    annual_rate: PercentageRate | str | None = None,
    next_due_date: date | None = None,
    contract_end_date: date | None = None,
    notes: str | None = None,
) -> Debt:
    require_editable_reporting_month(session, reporting_month_id)
    debt = Debt(
        reporting_month_id=reporting_month_id,
        debt_type=_coerce_debt_type(debt_type).value,
        name=_normalize_text(name, field="name"),
        current_balance_kopecks=_normalize_balance(current_balance),
        include_in_liquid_capital=include_in_liquid_capital,
        annual_rate_basis_points=_normalize_rate(annual_rate, field="annual_rate"),
        next_due_date=next_due_date,
        contract_end_date=contract_end_date,
        notes=notes,
    )
    session.add(debt)
    session.commit()
    session.refresh(debt)
    return debt


def update_debt(
    session: Session,
    debt_id: int,
    *,
    debt_type: DebtType | str | None = None,
    name: str | None = None,
    current_balance: RubleAmount | str | None = None,
    include_in_liquid_capital: bool | None = None,
    annual_rate: PercentageRate | str | None | object = _UNSET,
    next_due_date: date | None | object = _UNSET,
    contract_end_date: date | None | object = _UNSET,
    notes: str | None = None,
) -> Debt:
    debt = get_debt(session, debt_id)
    require_editable_child_month(session, debt)
    normalized_debt_type = _coerce_debt_type(debt_type) if debt_type is not None else None
    normalized_name = _normalize_text(name, field="name") if name is not None else None
    normalized_balance = (
        _normalize_balance(current_balance) if current_balance is not None else None
    )
    normalized_annual_rate = None
    if annual_rate is not _UNSET:
        normalized_annual_rate = _normalize_rate(
            annual_rate,  # type: ignore[arg-type]
            field="annual_rate",
        )

    if debt.linked_account_id is not None and normalized_debt_type is not None:
        if normalized_debt_type is not DebtType.CREDIT_CARD:
            raise ValueError("linked debt must remain a credit_card debt")
    if debt.linked_account_id is not None and include_in_liquid_capital is False:
        raise ValueError("linked debt must remain included in liquid capital")

    if normalized_debt_type is not None:
        debt.debt_type = normalized_debt_type.value
    if normalized_name is not None:
        debt.name = normalized_name
    if normalized_balance is not None:
        debt.current_balance_kopecks = normalized_balance
    if include_in_liquid_capital is not None:
        debt.include_in_liquid_capital = include_in_liquid_capital
    if annual_rate is not _UNSET:
        debt.annual_rate_basis_points = normalized_annual_rate
    if next_due_date is not _UNSET:
        debt.next_due_date = next_due_date  # type: ignore[assignment]
    if contract_end_date is not _UNSET:
        debt.contract_end_date = contract_end_date  # type: ignore[assignment]
    if notes is not None:
        debt.notes = notes
    session.commit()
    session.refresh(debt)
    return debt


def delete_debt(session: Session, debt_id: int) -> None:
    debt = get_debt(session, debt_id)
    require_editable_child_month(session, debt)
    session.delete(debt)
    session.commit()


def link_debt_to_account(session: Session, debt_id: int, account_id: int) -> Debt:
    """Explicitly link one eligible month-local debt to one stable account."""
    debt = get_debt(session, debt_id)
    require_editable_child_month(session, debt)
    account = get_account(session, account_id)

    if debt.debt_type != DebtType.CREDIT_CARD.value:
        raise ValueError("only credit_card debts can be linked to an account")
    if not debt.include_in_liquid_capital:
        raise ValueError("linked debt must already be included in liquid capital")
    if account.account_type not in LINKED_DEBT_ACCOUNT_TYPES:
        raise ValueError("linked account must be cash, deposit, or savings")
    if not account.include_in_capital:
        raise ValueError("linked account must already be included in capital")

    existing = session.scalar(
        select(Debt).where(
            Debt.reporting_month_id == debt.reporting_month_id,
            Debt.linked_account_id == account.id,
            Debt.id != debt.id,
        )
    )
    if existing is not None:
        raise DebtAccountLinkConflictError(
            "account is already linked to another debt in this reporting month"
        )

    debt.linked_account_id = account.id
    session.commit()
    session.refresh(debt)
    return debt


def unlink_debt_from_account(session: Session, debt_id: int) -> Debt:
    """Explicitly clear the authoritative debt-side account link."""
    debt = get_debt(session, debt_id)
    require_editable_child_month(session, debt)
    debt.linked_account_id = None
    session.commit()
    session.refresh(debt)
    return debt
