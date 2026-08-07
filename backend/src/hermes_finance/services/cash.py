from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hermes_finance.domain import RubleAmount
from hermes_finance.persistence import CashBalance
from hermes_finance.services._guard import (
    require_editable_child_month,
    require_editable_reporting_month,
)


class CashBalanceNotFoundError(LookupError):
    pass


def _normalize_name(name: str) -> str:
    normalized = name.strip()
    if not normalized:
        raise ValueError("name must not be empty")
    return normalized


def _normalize_amount(amount: RubleAmount | str) -> int:
    if isinstance(amount, str):
        amount = RubleAmount.from_api(amount)
    if not isinstance(amount, RubleAmount):
        raise TypeError("amount must be RubleAmount or decimal string")
    if amount.kopecks < 0:
        raise ValueError("amount must not be negative")
    return amount.kopecks


def _normalize_currency(currency: str) -> str:
    normalized = currency.strip().upper()
    if not normalized:
        raise ValueError("currency must not be empty")
    return normalized


def list_cash_balances(session: Session) -> list[CashBalance]:
    return list(
        session.scalars(
            select(CashBalance).order_by(CashBalance.reporting_month_id, CashBalance.id)
        )
    )


def get_cash_balance(session: Session, balance_id: int) -> CashBalance:
    balance = session.get(CashBalance, balance_id)
    if balance is None:
        raise CashBalanceNotFoundError(f"cash balance {balance_id} was not found")
    return balance


def total_cash(
    session: Session,
    reporting_month_id: int,
    *,
    include_in_capital_only: bool = False,
) -> RubleAmount:
    """Sum cash amounts for a month; a missing row or empty data means zero."""
    statement = select(func.coalesce(func.sum(CashBalance.amount_kopecks), 0)).where(
        CashBalance.reporting_month_id == reporting_month_id
    )
    if include_in_capital_only:
        statement = statement.where(CashBalance.include_in_capital.is_(True))
    total = session.scalar(statement)
    return RubleAmount(int(total or 0))


def create_cash_balance(
    session: Session,
    *,
    reporting_month_id: int,
    name: str,
    amount: RubleAmount | str,
    currency: str = "RUB",
    include_in_capital: bool = True,
    notes: str | None = None,
) -> CashBalance:
    require_editable_reporting_month(session, reporting_month_id)
    balance = CashBalance(
        reporting_month_id=reporting_month_id,
        name=_normalize_name(name),
        amount_kopecks=_normalize_amount(amount),
        currency=_normalize_currency(currency),
        include_in_capital=include_in_capital,
        notes=notes,
    )
    session.add(balance)
    session.commit()
    session.refresh(balance)
    return balance


def update_cash_balance(
    session: Session,
    balance_id: int,
    *,
    name: str | None = None,
    amount: RubleAmount | str | None = None,
    currency: str | None = None,
    include_in_capital: bool | None = None,
    notes: str | None = None,
) -> CashBalance:
    balance = get_cash_balance(session, balance_id)
    require_editable_child_month(session, balance)
    if name is not None:
        balance.name = _normalize_name(name)
    if amount is not None:
        balance.amount_kopecks = _normalize_amount(amount)
    if currency is not None:
        balance.currency = _normalize_currency(currency)
    if include_in_capital is not None:
        balance.include_in_capital = include_in_capital
    if notes is not None:
        balance.notes = notes
    session.commit()
    session.refresh(balance)
    return balance


def delete_cash_balance(session: Session, balance_id: int) -> None:
    balance = get_cash_balance(session, balance_id)
    require_editable_child_month(session, balance)
    session.delete(balance)
    session.commit()
