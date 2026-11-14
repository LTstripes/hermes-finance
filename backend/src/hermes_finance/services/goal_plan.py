"""Read-only composition of canonical goal sources and hypothetical plans."""

from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from hermes_finance.database import coherent_read_operation
from hermes_finance.domain.goal_plan import calculate_goal_plan, money
from hermes_finance.services.goals import get_goal
from hermes_finance.services.liquid_capital import liquid_capital_for_month
from hermes_finance.services.passive_income_average import passive_income_average
from hermes_finance.services.portfolio_source_coverage import portfolio_source_coverage_for_month
from hermes_finance.services.reporting_months import get_reporting_month


@coherent_read_operation
def build_goal_plan(session: Session, goal_id: int, reporting_month_id: int, **parameters) -> dict:
    goal = get_goal(session, goal_id)
    month = get_reporting_month(session, reporting_month_id)
    if not goal.is_active or (goal.goal_type, goal.calculation_mode) not in {
        ("capital", "liquid_capital_net"),
        ("passive_income", "monthly_net_passive_income"),
    }:
        return {"method_version": "goal_plan_v1", "status": "unsupported"}
    capital = liquid_capital_for_month(session, reporting_month_id)
    coverage = portfolio_source_coverage_for_month(session, reporting_month_id)
    source = coverage.source_account_financial_coverage
    coverage_status = coverage.status
    if source and source["status"] != "complete" and coverage_status == "complete":
        coverage_status = "partial"
    base = {
        "reporting_month_id": month.id,
        "as_of_date": month.snapshot_date.isoformat(),
        "base_capital": money(capital.liquid_capital_net.kopecks),
        "coverage": coverage_status,
        "components": {
            "liquid_assets": money(capital.total_assets.kopecks),
            "included_debts": money(capital.total_debts_included.kopecks),
        },
    }
    if coverage_status == "unavailable":
        return {
            **base,
            "base_capital": None,
            "method_version": "goal_plan_v1",
            "status": "base_unavailable",
        }
    if goal.goal_type == "passive_income":
        average = passive_income_average(session)
        income = average.average.kopecks
        amount = None
        if average.count_months and income > 0 and capital.liquid_capital_net.kopecks > 0:
            amount = money(
                int(
                    (
                        Decimal(goal.target_value_kopecks)
                        * capital.liquid_capital_net.kopecks
                        / income
                    ).quantize(Decimal(1), rounding=ROUND_HALF_UP)
                )
            )
        return {
            **base,
            "method_version": "goal_plan_v1",
            "status": "income_estimate",
            "required_capital": amount,
            "income_months_count": average.count_months,
            "income_months_used": list(average.months_used),
            "income_months_complete": average.is_complete_12m,
        }
    return {
        **calculate_goal_plan(
            capital=capital.liquid_capital_net.kopecks,
            target=goal.target_value_kopecks,
            snapshot=month.snapshot_date,
            deadline=goal.target_date,
            **parameters,
        ),
        **base,
    }
