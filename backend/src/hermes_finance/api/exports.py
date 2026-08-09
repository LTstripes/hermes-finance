"""Downloadable report exports (F02)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.api.settings import session_for_request
from hermes_finance.domain.values import RubleAmount
from hermes_finance.persistence import (
    APP_SETTINGS_ID,
    DEFAULT_BASE_CURRENCY,
    DEFAULT_FORMULA_VERSION,
    DEFAULT_LOCALE,
    DEFAULT_PASSIVE_INCOME_GOAL_KOPECKS,
    DEFAULT_TIMEZONE,
    AppSettings,
    Goal,
)
from hermes_finance.services.comments import list_monthly_comments
from hermes_finance.services.dashboard import build_dashboard
from hermes_finance.services.debts import list_debts
from hermes_finance.services.expenses import list_expense_entries
from hermes_finance.services.goals import DEFAULT_PASSIVE_INCOME_CALCULATION_MODE, list_goals
from hermes_finance.services.incomes import list_income_entries
from hermes_finance.services.investment_cash_flows import list_investment_cash_flows
from hermes_finance.services.markdown_export import (
    DebtReportRow,
    ExpenseReportRow,
    GoalReportRow,
    IncomeReportRow,
    InvestmentFlowReportRow,
    MarkdownReport,
    render_markdown_report,
)
from hermes_finance.services.monthly_summary import DEFAULT_FORECAST_VERSION
from hermes_finance.services.reporting_months import get_reporting_month
from hermes_finance.services.tax_brackets import get_or_create_default_tax_brackets

router = APIRouter(prefix="/api/months", tags=["exports"])


def _prepare_read_only_defaults(session: Session, year: int) -> None:
    """Make lazy calculation defaults transient for this read-only request."""
    settings = session.scalar(select(AppSettings).where(AppSettings.id == APP_SETTINGS_ID))
    if settings is None:
        settings = AppSettings(
            id=APP_SETTINGS_ID,
            base_currency=DEFAULT_BASE_CURRENCY,
            locale=DEFAULT_LOCALE,
            timezone=DEFAULT_TIMEZONE,
            passive_income_goal_kopecks=DEFAULT_PASSIVE_INCOME_GOAL_KOPECKS,
            formula_version=DEFAULT_FORMULA_VERSION,
        )
        session.add(settings)
        session.flush()

    main_goal = session.scalar(
        select(Goal).where(Goal.goal_type == "passive_income").order_by(Goal.id).limit(1)
    )
    if main_goal is None:
        session.add(
            Goal(
                name="Пассивный доход в месяц",
                goal_type="passive_income",
                target_value_kopecks=settings.passive_income_goal_kopecks,
                target_date=None,
                is_active=True,
                calculation_mode=DEFAULT_PASSIVE_INCOME_CALCULATION_MODE,
                notes=None,
            )
        )
        session.flush()

    get_or_create_default_tax_brackets(session, year, commit=False)


def _report_for_month(
    session: Session,
    month_id: int,
    *,
    forecast_version: str,
) -> MarkdownReport:
    month = get_reporting_month(session, month_id)
    _prepare_read_only_defaults(session, month.year)
    dashboard = build_dashboard(session, month_id, forecast_version=forecast_version)

    incomes = tuple(
        IncomeReportRow(
            name=item.name,
            income_type=item.income_type,
            gross=RubleAmount(item.gross_amount_kopecks),
            tax=RubleAmount(item.tax_amount_kopecks),
            net=RubleAmount(item.net_amount_kopecks),
        )
        for item in list_income_entries(session)
        if item.reporting_month_id == month_id
    )
    investment_flows = tuple(
        InvestmentFlowReportRow(
            event_date=item.event_date,
            flow_type=item.flow_type,
            gross=RubleAmount(item.gross_amount_kopecks),
            tax=RubleAmount(item.tax_amount_kopecks),
            commission=RubleAmount(item.commission_amount_kopecks),
            net=RubleAmount(item.net_amount_kopecks),
        )
        for item in list_investment_cash_flows(session)
        if item.reporting_month_id == month_id
    )
    expenses = tuple(
        ExpenseReportRow(
            category=item.category,
            expense_type=item.expense_type,
            amount=RubleAmount(item.amount_kopecks),
        )
        for item in list_expense_entries(session)
        if item.reporting_month_id == month_id
    )
    debts = tuple(
        DebtReportRow(
            name=item.name,
            debt_type=item.debt_type,
            balance=RubleAmount(item.current_balance_kopecks),
            included_in_liquid_capital=item.include_in_liquid_capital,
        )
        for item in list_debts(session)
        if item.reporting_month_id == month_id
    )
    goals = tuple(
        GoalReportRow(
            name=item.name,
            goal_type=item.goal_type,
            target=RubleAmount(item.target_value_kopecks),
            progress_pct=(
                dashboard.summary.coverage.goal_progress_pct
                if item.goal_type == "passive_income"
                else None
            ),
        )
        for item in list_goals(session)
    )
    comments = tuple(item.text for item in list_monthly_comments(session, month_id))
    return MarkdownReport(
        dashboard=dashboard,
        income_rows=incomes,
        investment_flow_rows=investment_flows,
        expense_rows=expenses,
        debt_rows=debts,
        goal_rows=goals,
        comments=comments,
    )


@router.post("/{month_id}/export/markdown")
def export_markdown(
    month_id: int,
    forecast_version: str = Query(default=DEFAULT_FORECAST_VERSION, min_length=1, max_length=32),
    session: Session = Depends(session_for_request),
) -> Response:
    try:
        report = _report_for_month(session, month_id, forecast_version=forecast_version)
        content = render_markdown_report(report)
        filename = (
            f"finance_report_{report.dashboard.month.year:04d}-"
            f"{report.dashboard.month.month:02d}.md"
        )
        return Response(
            content=content,
            media_type="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    finally:
        session.rollback()
