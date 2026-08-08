"""ORM application service for the IIS account result (C09).

Loads persisted rows for an IIS account, maps them into the pure
domain calculator input, and returns the domain result DTO.  No API,
no Pydantic, no React.

Implements MASTER_SPEC §10.16:

    portfolio_result_without_tax_benefit
    portfolio_result_with_tax_benefit =
        portfolio_result_without_tax_benefit
      + received_tax_benefits

Key invariants (AGENTS.md / wiki §7):
- Money is always integer kopecks; never binary ``float``.
- Bond principal repayment (redemption) is NOT income and never
  appears in the result.
- Contributions, deposits and withdrawals never appear in the result.
- Planned/submitted tax benefits are shown separately in the breakdown
  and never added to either portfolio result.
- Rejected benefits are ignored entirely.
- Only ``received`` tax benefits feed ``portfolio_result_with_tax_benefit``.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hermes_finance.domain.cash_flows import InvestmentCashFlowType
from hermes_finance.domain.iis import TaxBenefitStatus
from hermes_finance.domain.iis_result import (
    IisResult,
    IisResultInput,
    calculate_iis_result,
)
from hermes_finance.domain.values import RubleAmount
from hermes_finance.persistence import (
    Account,
    IisProfile,
    InvestmentCashFlow,
    PositionSnapshot,
    TaxBenefit,
)
from hermes_finance.services.accounts import AccountNotFoundError


def _sum_cash_flows(
    session: Session, account_id: int, flow_type: InvestmentCashFlowType
) -> RubleAmount:
    """Sum ``net_amount_kopecks`` for a single flow type across all time."""
    total = session.scalar(
        select(func.coalesce(func.sum(InvestmentCashFlow.net_amount_kopecks), 0)).where(
            InvestmentCashFlow.account_id == account_id,
            InvestmentCashFlow.flow_type == flow_type.value,
        )
    )
    return RubleAmount(int(total or 0))


def _sum_tax_benefits(session: Session, account_id: int, status: TaxBenefitStatus) -> RubleAmount:
    """Sum ``amount_kopecks`` for tax benefits of a single status (all time)."""
    total = session.scalar(
        select(func.coalesce(func.sum(TaxBenefit.amount_kopecks), 0)).where(
            TaxBenefit.account_id == account_id,
            TaxBenefit.status == status.value,
        )
    )
    return RubleAmount(int(total or 0))


def iis_result(session: Session, *, account_id: int, reporting_month_id: int) -> IisResult:
    """Assemble IIS account-result input from the database and calculate.

    Parameters
    ----------
    session:
        The SQLAlchemy ORM session.
    account_id:
        The account to calculate the IIS result for.  Must exist and have
        an :class:`IisProfile`.
    reporting_month_id:
        The month whose position snapshots determine the unrealized result.
        Coupons, dividends, realized PnL and tax benefits are summed across
        *all* months (all time) per the fixed C09 contract.

    Raises
    ------
    AccountNotFoundError
        If the account does not exist.
    ValueError
        If the account exists but is not an IIS account (no
        :class:`IisProfile`).
    """
    if session.get(Account, account_id) is None:
        raise AccountNotFoundError(f"account {account_id} was not found")

    has_iis_profile = session.scalar(
        select(IisProfile.id).where(IisProfile.account_id == account_id)
    )
    if has_iis_profile is None:
        raise ValueError(f"account {account_id} is not an IIS account")

    unrealized_total = session.scalar(
        select(func.coalesce(func.sum(PositionSnapshot.unrealized_result_kopecks), 0)).where(
            PositionSnapshot.account_id == account_id,
            PositionSnapshot.reporting_month_id == reporting_month_id,
        )
    )
    unrealized = RubleAmount(int(unrealized_total or 0))

    coupons = _sum_cash_flows(session, account_id, InvestmentCashFlowType.COUPON)
    dividends = _sum_cash_flows(session, account_id, InvestmentCashFlowType.DIVIDEND)

    realized_profit = _sum_cash_flows(session, account_id, InvestmentCashFlowType.REALIZED_PROFIT)
    realized_loss = _sum_cash_flows(session, account_id, InvestmentCashFlowType.REALIZED_LOSS)
    realized_pnl = RubleAmount(realized_profit.kopecks + realized_loss.kopecks)

    received_tax_benefits = _sum_tax_benefits(session, account_id, TaxBenefitStatus.RECEIVED)
    planned_tax_benefits = _sum_tax_benefits(session, account_id, TaxBenefitStatus.PLANNED)
    submitted_tax_benefits = _sum_tax_benefits(session, account_id, TaxBenefitStatus.SUBMITTED)

    return calculate_iis_result(
        IisResultInput(
            unrealized=unrealized,
            coupons=coupons,
            dividends=dividends,
            realized_pnl=realized_pnl,
            received_tax_benefits=received_tax_benefits,
            planned_tax_benefits=planned_tax_benefits,
            submitted_tax_benefits=submitted_tax_benefits,
        )
    )
