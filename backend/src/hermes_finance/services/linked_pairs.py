"""Backend-owned read model for linked liquid accounts and credit-card debt.

The relation is authoritative on ``Debt.linked_account_id`` and is
month-local on the debt row.  This service only assembles presentation facts:
the account amount is already included in liquid assets and the debt amount is
already included in total included debts.  It never changes either canonical
total and never applies a second debt subtraction.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hermes_finance.domain import LINKED_DEBT_ACCOUNT_TYPES, DebtType
from hermes_finance.domain.liquid_capital import LinkedPairReadModel
from hermes_finance.domain.values import RubleAmount
from hermes_finance.persistence import Account, CashBalance, Debt, DepositSnapshot


class LinkedPairReadModelError(ValueError):
    """Raised when persisted link facts cannot be represented safely."""


def _validate_linked_facts(
    *,
    debt_type: str,
    include_in_liquid_capital: bool,
    account_type: str,
    account_include_in_capital: bool,
) -> None:
    if debt_type != DebtType.CREDIT_CARD.value:
        raise LinkedPairReadModelError("stored linked debt must be a credit_card debt")
    if not include_in_liquid_capital:
        raise LinkedPairReadModelError("stored linked debt must be included in liquid capital")
    if account_type not in LINKED_DEBT_ACCOUNT_TYPES:
        raise LinkedPairReadModelError("stored linked account type is not eligible")
    if not account_include_in_capital:
        raise LinkedPairReadModelError("stored linked account must be included in capital")


def linked_pairs_for_month(
    session: Session, reporting_month_id: int
) -> tuple[LinkedPairReadModel, ...]:
    """Return linked-pair facts for one month in deterministic order."""
    return linked_pairs_for_months(session, (reporting_month_id,)).get(reporting_month_id, ())


def linked_pairs_for_months(
    session: Session, reporting_month_ids: Iterable[int]
) -> dict[int, tuple[LinkedPairReadModel, ...]]:
    """Return linked-pair facts for several months using set-based reads."""
    month_ids = tuple(dict.fromkeys(reporting_month_ids))
    if not month_ids:
        return {}

    linked_debts = session.execute(
        select(
            Debt.reporting_month_id,
            Debt.id,
            Debt.name,
            Debt.debt_type,
            Debt.current_balance_kopecks,
            Debt.include_in_liquid_capital,
            Account.id,
            Account.name,
            Account.account_type,
            Account.include_in_capital,
        )
        .join(Account, Debt.linked_account_id == Account.id)
        .where(Debt.reporting_month_id.in_(month_ids))
        .where(Debt.linked_account_id.is_not(None))
        .order_by(Debt.reporting_month_id, Debt.id)
    ).all()

    cash_rows = session.execute(
        select(
            CashBalance.reporting_month_id,
            CashBalance.account_id,
            func.sum(CashBalance.amount_kopecks),
        )
        .join(Account, CashBalance.account_id == Account.id)
        .where(CashBalance.reporting_month_id.in_(month_ids))
        .where(CashBalance.account_id.is_not(None))
        .where(CashBalance.include_in_capital.is_(True))
        .where(Account.include_in_capital.is_(True))
        .group_by(CashBalance.reporting_month_id, CashBalance.account_id)
    ).all()
    deposit_rows = session.execute(
        select(
            DepositSnapshot.reporting_month_id,
            DepositSnapshot.account_id,
            func.sum(DepositSnapshot.balance_kopecks),
        )
        .join(Account, DepositSnapshot.account_id == Account.id)
        .where(DepositSnapshot.reporting_month_id.in_(month_ids))
        .where(Account.include_in_capital.is_(True))
        .group_by(DepositSnapshot.reporting_month_id, DepositSnapshot.account_id)
    ).all()

    account_amounts: dict[tuple[int, int], int] = {}
    for month_id, account_id, amount in (*cash_rows, *deposit_rows):
        if account_id is None:
            continue
        key = (month_id, account_id)
        account_amounts[key] = account_amounts.get(key, 0) + int(amount or 0)

    pairs_by_month: dict[int, list[LinkedPairReadModel]] = {month_id: [] for month_id in month_ids}
    for (
        month_id,
        debt_id,
        debt_name,
        debt_type,
        debt_balance_kopecks,
        debt_included,
        account_id,
        account_name,
        account_type,
        account_included,
    ) in linked_debts:
        _validate_linked_facts(
            debt_type=debt_type,
            include_in_liquid_capital=debt_included,
            account_type=account_type,
            account_include_in_capital=account_included,
        )
        pairs_by_month[month_id].append(
            LinkedPairReadModel(
                debt_id=debt_id,
                debt_name=debt_name,
                debt_type=debt_type,
                debt_balance=RubleAmount(debt_balance_kopecks),
                account_id=account_id,
                account_name=account_name,
                account_type=account_type,
                account_balance=RubleAmount(account_amounts.get((month_id, account_id), 0)),
            )
        )

    return {month_id: tuple(pairs) for month_id, pairs in pairs_by_month.items()}
