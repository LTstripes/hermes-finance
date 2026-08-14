"""Clone a reporting month into a new draft period (D03).

Implements MASTER_SPEC §11.3 and PROJECT_WIKI §7.6:

- accounts / instruments / goals / IIS / tax brackets stay global (not copied);
- month-scoped permanent state is copied;
- actual event streams and comments are zeroed (not copied);
- the whole operation is one transaction: commit once or rollback everything.

Copied
------
- position snapshots (quantities and valuations as of the source month);
- deposit snapshots with ``actual_interest_received = 0`` and recalculated
  expected monthly interest;
- cash balances;
- mandatory expenses only;
- saving allocations;
- debts;
- property snapshots;
- recurring salary income entries (salary settings template; ``received_at``
  cleared).

Not copied
----------
- investment cash flows (coupons, dividends, interest, commissions, taxes,
  deposits, withdrawals, realized PnL);
- expected cash flows (forecast versions stay month-local);
- non-mandatory expenses;
- bonus / cashback / non-recurring incomes;
- monthly comments.
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.domain import FINANCIAL_ROUNDING, ExpenseType, IncomeType, ReportingMonthStatus
from hermes_finance.persistence import (
    CashBalance,
    Debt,
    DepositSnapshot,
    ExpenseEntry,
    IncomeEntry,
    PositionSnapshot,
    PropertySnapshot,
    ReportingMonth,
    SavingAllocation,
)
from hermes_finance.services.reporting_months import (
    ReportingMonthNotFoundError,
    get_reporting_month,
    get_reporting_month_by_period,
)


def _period_bounds(year: int, month: int) -> tuple[date, date]:
    try:
        period_start = date(year, month, 1)
    except ValueError as error:
        raise ValueError("year and month must describe a valid calendar month") from error
    return period_start, date(year, month, monthrange(year, month)[1])


def _expected_monthly_interest(balance_kopecks: int, annual_rate_basis_points: int) -> int:
    monthly = (
        Decimal(balance_kopecks) * Decimal(annual_rate_basis_points) / Decimal(10_000) / Decimal(12)
    )
    return int(monthly.to_integral_value(rounding=FINANCIAL_ROUNDING))


def _copy_positions(session: Session, *, source_id: int, target_id: int) -> None:
    rows = session.scalars(
        select(PositionSnapshot).where(PositionSnapshot.reporting_month_id == source_id)
    )
    for row in rows:
        session.add(
            PositionSnapshot(
                reporting_month_id=target_id,
                account_id=row.account_id,
                instrument_id=row.instrument_id,
                quantity=row.quantity,
                average_cost_per_unit_kopecks=row.average_cost_per_unit_kopecks,
                market_price_per_unit_kopecks=row.market_price_per_unit_kopecks,
                accrued_interest_kopecks=row.accrued_interest_kopecks,
                market_value_kopecks=row.market_value_kopecks,
                cost_basis_kopecks=row.cost_basis_kopecks,
                unrealized_result_kopecks=row.unrealized_result_kopecks,
                price_date=row.price_date,
                price_source=row.price_source,
                manual_adjustment=row.manual_adjustment,
                notes=row.notes,
            )
        )


def _copy_deposits(session: Session, *, source_id: int, target_id: int) -> None:
    rows = session.scalars(
        select(DepositSnapshot).where(DepositSnapshot.reporting_month_id == source_id)
    )
    for row in rows:
        session.add(
            DepositSnapshot(
                reporting_month_id=target_id,
                account_id=row.account_id,
                name=row.name,
                deposit_type=row.deposit_type,
                balance_kopecks=row.balance_kopecks,
                annual_rate_basis_points=row.annual_rate_basis_points,
                expected_monthly_interest_kopecks=_expected_monthly_interest(
                    row.balance_kopecks, row.annual_rate_basis_points
                ),
                actual_interest_received_kopecks=0,
                notes=row.notes,
            )
        )


def _copy_cash(session: Session, *, source_id: int, target_id: int) -> None:
    rows = session.scalars(select(CashBalance).where(CashBalance.reporting_month_id == source_id))
    for row in rows:
        session.add(
            CashBalance(
                reporting_month_id=target_id,
                name=row.name,
                amount_kopecks=row.amount_kopecks,
                currency=row.currency,
                include_in_capital=row.include_in_capital,
                notes=row.notes,
            )
        )


def _copy_mandatory_expenses(session: Session, *, source_id: int, target_id: int) -> None:
    rows = session.scalars(
        select(ExpenseEntry).where(
            ExpenseEntry.reporting_month_id == source_id,
            ExpenseEntry.expense_type == ExpenseType.MANDATORY.value,
        )
    )
    for row in rows:
        session.add(
            ExpenseEntry(
                reporting_month_id=target_id,
                category=row.category,
                amount_kopecks=row.amount_kopecks,
                expense_type=row.expense_type,
                is_recurring=row.is_recurring,
                notes=row.notes,
            )
        )


def _copy_savings(session: Session, *, source_id: int, target_id: int) -> None:
    rows = session.scalars(
        select(SavingAllocation).where(SavingAllocation.reporting_month_id == source_id)
    )
    for row in rows:
        session.add(
            SavingAllocation(
                reporting_month_id=target_id,
                destination=row.destination,
                amount_kopecks=row.amount_kopecks,
                notes=row.notes,
            )
        )


def _copy_debts(session: Session, *, source_id: int, target_id: int) -> None:
    rows = session.scalars(select(Debt).where(Debt.reporting_month_id == source_id))
    for row in rows:
        session.add(
            Debt(
                reporting_month_id=target_id,
                debt_type=row.debt_type,
                name=row.name,
                current_balance_kopecks=row.current_balance_kopecks,
                include_in_liquid_capital=row.include_in_liquid_capital,
                notes=row.notes,
            )
        )


def _copy_properties(session: Session, *, source_id: int, target_id: int) -> None:
    rows = session.scalars(
        select(PropertySnapshot).where(PropertySnapshot.reporting_month_id == source_id)
    )
    for row in rows:
        session.add(
            PropertySnapshot(
                reporting_month_id=target_id,
                name=row.name,
                estimated_value_kopecks=row.estimated_value_kopecks,
                mortgage_balance_kopecks=row.mortgage_balance_kopecks,
                monthly_payment_kopecks=row.monthly_payment_kopecks,
                notes=row.notes,
            )
        )


def _copy_salary_settings(session: Session, *, source_id: int, target_id: int) -> None:
    """Copy recurring salary settings as one canonical target row.

    Legacy source months may contain duplicate recurring SALARY rows. The target
    month receives their exact aggregate so clone cannot propagate that invalid
    cardinality. The first source row's name is preserved. ``received_at`` is
    cleared because payment dates are actual events.
    """
    rows = list(
        session.scalars(
            select(IncomeEntry)
            .where(
                IncomeEntry.reporting_month_id == source_id,
                IncomeEntry.income_type == IncomeType.SALARY.value,
                IncomeEntry.is_recurring.is_(True),
            )
            .order_by(IncomeEntry.id)
        )
    )
    if not rows:
        return

    first = rows[0]
    session.add(
        IncomeEntry(
            reporting_month_id=target_id,
            income_type=IncomeType.SALARY.value,
            name=first.name,
            gross_amount_kopecks=sum(row.gross_amount_kopecks for row in rows),
            tax_amount_kopecks=sum(row.tax_amount_kopecks for row in rows),
            net_amount_kopecks=sum(row.net_amount_kopecks for row in rows),
            received_at=None,
            is_recurring=True,
            include_in_cash_flow=any(row.include_in_cash_flow for row in rows),
            include_in_passive_income=False,
            notes=first.notes,
        )
    )


def clone_reporting_month(
    session: Session,
    source_month_id: int,
    *,
    target_year: int,
    target_month: int,
    snapshot_date: date,
) -> ReportingMonth:
    """Create ``target_year/target_month`` by cloning permanent state from *source*.

    Source may be draft or closed. Target must not already exist. On any error
    the session is rolled back and no target month remains.
    """
    source = get_reporting_month(session, source_month_id)
    if get_reporting_month_by_period(session, year=target_year, month=target_month) is not None:
        raise ValueError(f"reporting month {target_year:04d}-{target_month:02d} already exists")

    period_start, period_end = _period_bounds(target_year, target_month)
    if snapshot_date < period_start:
        raise ValueError("snapshot_date cannot be before the reporting period")

    target = ReportingMonth(
        year=target_year,
        month=target_month,
        period_start=period_start,
        period_end=period_end,
        snapshot_date=snapshot_date,
        status=ReportingMonthStatus.DRAFT.value,
        source=source.source,
    )
    session.add(target)

    try:
        session.flush()  # allocate target.id without committing
        target_id = target.id
        source_id = source.id

        _copy_positions(session, source_id=source_id, target_id=target_id)
        _copy_deposits(session, source_id=source_id, target_id=target_id)
        _copy_cash(session, source_id=source_id, target_id=target_id)
        _copy_mandatory_expenses(session, source_id=source_id, target_id=target_id)
        _copy_savings(session, source_id=source_id, target_id=target_id)
        _copy_debts(session, source_id=source_id, target_id=target_id)
        _copy_properties(session, source_id=source_id, target_id=target_id)
        _copy_salary_settings(session, source_id=source_id, target_id=target_id)

        session.commit()
    except Exception:
        session.rollback()
        raise

    session.refresh(target)
    return target


__all__ = ["clone_reporting_month", "ReportingMonthNotFoundError"]
