"""ORM application service for liquid capital (C01).

Loads persisted rows for a reporting month, maps them into the pure
domain calculator input, and returns the domain result DTO.  No API,
no Pydantic, no React.  Property snapshots are never loaded.

Implements MASTER_SPEC §10.1:

    liquid_assets = cash + deposits + securities + other_liquid_assets
    liquid_capital_net = liquid_assets - included_debts

Reads are allowed on closed months (B19-R2 guard is for writes only).
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hermes_finance.domain.liquid_capital import (
    AccountAmount,
    LiquidCapitalInput,
    LiquidCapitalResult,
    calculate_liquid_capital,
)
from hermes_finance.domain.values import RubleAmount
from hermes_finance.persistence import Account, DepositSnapshot, PositionSnapshot
from hermes_finance.services.cash import total_cash
from hermes_finance.services.debts import total_included_debts


def liquid_capital_for_month(session: Session, reporting_month_id: int) -> LiquidCapitalResult:
    """Assemble liquid-capital input from the database and calculate."""
    cash = total_cash(session, reporting_month_id, include_in_capital_only=True)
    included_debts = total_included_debts(session, reporting_month_id)

    # Deposits: sum balance_kopecks where Account.include_in_capital is True.
    deposit_total = session.scalar(
        select(func.coalesce(func.sum(DepositSnapshot.balance_kopecks), 0))
        .join(Account, DepositSnapshot.account_id == Account.id)
        .where(DepositSnapshot.reporting_month_id == reporting_month_id)
        .where(Account.include_in_capital.is_(True))
    )
    deposits = RubleAmount(int(deposit_total or 0))

    # Securities: sum market_value_kopecks where Account.include_in_capital is True.
    securities_total = session.scalar(
        select(func.coalesce(func.sum(PositionSnapshot.market_value_kopecks), 0))
        .join(Account, PositionSnapshot.account_id == Account.id)
        .where(PositionSnapshot.reporting_month_id == reporting_month_id)
        .where(Account.include_in_capital.is_(True))
    )
    securities = RubleAmount(int(securities_total or 0))

    # Per-account breakdown (deposits + securities), respecting include_in_capital.
    deposit_by_account = session.execute(
        select(DepositSnapshot.account_id, func.sum(DepositSnapshot.balance_kopecks))
        .join(Account, DepositSnapshot.account_id == Account.id)
        .where(DepositSnapshot.reporting_month_id == reporting_month_id)
        .where(Account.include_in_capital.is_(True))
        .group_by(DepositSnapshot.account_id)
    ).all()

    deposit_accounts = tuple(
        AccountAmount(account_id=account_id, amount=RubleAmount(int(total or 0)))
        for account_id, total in deposit_by_account
    )

    securities_by_account = session.execute(
        select(PositionSnapshot.account_id, func.sum(PositionSnapshot.market_value_kopecks))
        .join(Account, PositionSnapshot.account_id == Account.id)
        .where(PositionSnapshot.reporting_month_id == reporting_month_id)
        .where(Account.include_in_capital.is_(True))
        .group_by(PositionSnapshot.account_id)
    ).all()

    securities_accounts = tuple(
        AccountAmount(account_id=account_id, amount=RubleAmount(int(total or 0)))
        for account_id, total in securities_by_account
    )

    return calculate_liquid_capital(
        LiquidCapitalInput(
            cash=cash,
            deposits=deposits,
            securities=securities,
            other_liquid_assets=RubleAmount(0),
            included_debts=included_debts,
            deposit_accounts=deposit_accounts,
            securities_accounts=securities_accounts,
        )
    )
