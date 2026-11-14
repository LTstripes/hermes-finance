"""Month checklist for the Month page (#1079, stage 2).

Presentation of facts the close workflow already reads: which month workspace
section holds saved rows, which close-readiness findings point at it and one
key figure per section. Nothing here decides readiness, changes a close rule
or recomputes a financial result; sums only add existing integer-kopeck
subtotals of the same monthly summary.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hermes_finance.domain.expenses import ExpenseType
from hermes_finance.domain.monthly_summary import MonthlySummaryResult
from hermes_finance.domain.values import RubleAmount
from hermes_finance.persistence import (
    BrokerMonthApply,
    ExpenseEntry,
    IncomeEntry,
    InvestmentCashFlow,
    MonthlyComment,
    PositionSnapshot,
    ReportingMonth,
    SavingAllocation,
)
from hermes_finance.services.close_readiness import CloseReadiness, CloseReadinessItem
from hermes_finance.services.debts import total_debts
from hermes_finance.services.month_working_status import saved_section_facts
from hermes_finance.services.monthly_summary import DEFAULT_FORECAST_VERSION
from hermes_finance.services.payout_calendar import merged_payout_calendar

ChecklistStepId = Literal[
    "general",
    "income",
    "assets",
    "liabilities",
    "positions",
    "brokers",
    "payouts",
    "budget",
    "note",
    "close",
]
ChecklistGroup = Literal["data", "sources", "plan", "close"]
ChecklistState = Literal["done", "attention", "empty", "optional"]

# P keeps personal data first, then statements before the positions and payouts
# that depend on them, then comments and Close.
STEP_GROUPS: tuple[tuple[ChecklistStepId, ChecklistGroup], ...] = (
    ("general", "data"),
    ("income", "data"),
    ("assets", "data"),
    ("liabilities", "data"),
    ("budget", "data"),
    ("brokers", "sources"),
    ("positions", "sources"),
    ("payouts", "sources"),
    ("note", "plan"),
    ("close", "close"),
)
OPTIONAL_STEPS: frozenset[str] = frozenset({"note"})

# Freshness findings carry their family; each family belongs to one section.
_FAMILY_STEP: dict[str, ChecklistStepId] = {
    "market_quotes": "positions",
    "broker_positions": "positions",
    "t_invest_payouts": "payouts",
    "alfa_statement_payouts": "brokers",
    "manual_month_data": "general",
    "deposit_cash_snapshots": "assets",
}
_CODE_STEP: dict[str, ChecklistStepId] = {
    "snapshot_date_required": "general",
    "salary_tax_history_incomplete": "income",
    "active_account_snapshot_missing": "positions",
    "unresolved_payout_reconciliation": "payouts",
}
# Already visible as empty sections; counting it again would double the gap.
_NOT_A_SECTION_FINDING = frozenset({"empty_manual_month"})
_ATTENTION_SEVERITIES = frozenset({"hard_blocker", "warning"})
# Received payouts only; fees, taxes, transfers and trading results are not payouts.
_PAYOUT_FLOW_TYPES = ("coupon", "dividend", "interest", "redemption")


@dataclass(frozen=True, slots=True)
class ChecklistFigure:
    kind: Literal["money", "date", "count"]
    amount: RubleAmount | None = None
    day: date | None = None
    count: int | None = None


@dataclass(frozen=True, slots=True)
class ChecklistStep:
    id: ChecklistStepId
    group: ChecklistGroup
    required: bool
    has_saved_facts: bool
    has_templates: bool
    state: ChecklistState
    attention_count: int
    remark_count: int
    figure: ChecklistFigure | None
    secondary_count: int | None


@dataclass(frozen=True, slots=True)
class ChecklistExpenseItem:
    category: str
    amount: RubleAmount


@dataclass(frozen=True, slots=True)
class MonthChecklist:
    completed_count: int
    total_count: int
    attention_count: int
    remarks: tuple[CloseReadinessItem, ...]
    has_statement_positions: bool
    steps: tuple[ChecklistStep, ...]
    mandatory_expenses_total: RubleAmount
    other_expenses_total: RubleAmount
    mandatory_expense_items: tuple[ChecklistExpenseItem, ...]


def month_remarks(readiness: CloseReadiness) -> tuple[CloseReadinessItem, ...]:
    """One visible action per issue; original readiness evidence stays unchanged."""
    selected = []
    seen = set()
    for item in sorted(readiness.items, key=lambda item: item.severity.value != "hard_blocker"):
        if item.severity.value not in _ATTENTION_SEVERITIES:
            continue
        message = item.message
        account = re.fullmatch(
            r"(.*): .*\. Проверь подробности в разделе «Месяц → Брокерские выписки»\.", message
        )
        if account:
            message = (
                f"{account[1]}: сверка выписки с данными месяца не завершена. "
                "Открой «Месяц → Брокерские выписки» и проверь замечания."
            )
        key = message.strip()
        if key not in seen:
            seen.add(key)
            selected.append(replace(item, message=message))
    return tuple(selected)


def attention_step(item: CloseReadinessItem) -> ChecklistStepId | None:
    """Section a close-readiness finding belongs to, or None when it is not one.

    Remaining hard blockers and warnings come from broker statement and source
    checks (``broker_month_close_blockers``, integrity guards), whose home in
    the Month page is the statements section.
    """

    if item.severity.value not in _ATTENTION_SEVERITIES or item.code in _NOT_A_SECTION_FINDING:
        return None
    family = item.context.get("family_id")
    if isinstance(family, str) and family in _FAMILY_STEP:
        return _FAMILY_STEP[family]
    if item.code in _CODE_STEP:
        return _CODE_STEP[item.code]
    if item.code.startswith("salary"):
        return "income"
    return "brokers"


def _count(session: Session, model: type, month_id: int, *criteria: object) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(model)
            .where(model.reporting_month_id == month_id, *criteria)
        )
        or 0
    )


def _plus(*amounts: RubleAmount) -> RubleAmount:
    return RubleAmount(sum(amount.kopecks for amount in amounts))


def _mandatory_expense_items(session: Session, month_id: int) -> tuple[ChecklistExpenseItem, ...]:
    rows = session.execute(
        select(ExpenseEntry.category, func.sum(ExpenseEntry.amount_kopecks))
        .where(
            ExpenseEntry.reporting_month_id == month_id,
            ExpenseEntry.expense_type == ExpenseType.MANDATORY.value,
        )
        .group_by(ExpenseEntry.category)
    ).all()
    items = [
        ChecklistExpenseItem(category=category, amount=RubleAmount(int(total or 0)))
        for category, total in rows
    ]
    items.sort(key=lambda item: (-item.amount.kopecks, item.category))
    return tuple(items)


def _expected_payout_count(session: Session, month: ReportingMonth) -> int:
    """Items of the payout calendar the Payouts section shows.

    The merged calendar de-duplicates manual and applied provider rows. Close
    readiness reads it with the same arguments inside the same read snapshot,
    so this reuses that result rather than reading the calendar again.
    """

    if month.snapshot_date is None:
        return 0
    calendar = merged_payout_calendar(
        session, reporting_month_id=month.id, forecast_version=DEFAULT_FORECAST_VERSION
    )
    return sum(len(bucket.items) for bucket in calendar)


def _figures(
    session: Session, month: ReportingMonth, summary: MonthlySummaryResult
) -> dict[str, tuple[ChecklistFigure | None, int | None]]:
    month_id = month.id
    cash = summary.cash_balance.breakdown
    liquid = summary.liquid_capital.breakdown
    return {
        "general": (
            ChecklistFigure(kind="date", day=month.snapshot_date) if month.snapshot_date else None,
            None,
        ),
        "income": (
            ChecklistFigure(
                kind="money",
                amount=_plus(
                    cash.salary_net,
                    cash.bonus_net,
                    cash.side_income_net,
                    cash.cashback,
                    cash.other_income,
                ),
            ),
            None,
        ),
        "assets": (ChecklistFigure(kind="money", amount=_plus(liquid.cash, liquid.deposits)), None),
        "liabilities": (ChecklistFigure(kind="money", amount=total_debts(session, month_id)), None),
        "positions": (
            ChecklistFigure(kind="money", amount=liquid.securities),
            _count(session, PositionSnapshot, month_id),
        ),
        "brokers": (
            ChecklistFigure(kind="count", count=_count(session, BrokerMonthApply, month_id)),
            None,
        ),
        "payouts": (
            ChecklistFigure(
                kind="count",
                count=_count(
                    session,
                    InvestmentCashFlow,
                    month_id,
                    InvestmentCashFlow.flow_type.in_(_PAYOUT_FLOW_TYPES),
                ),
            ),
            _expected_payout_count(session, month),
        ),
        "budget": (
            ChecklistFigure(kind="money", amount=cash.mandatory_expenses),
            _count(
                session,
                ExpenseEntry,
                month_id,
                ExpenseEntry.expense_type == ExpenseType.MANDATORY.value,
            ),
        ),
        "note": (
            ChecklistFigure(kind="count", count=_count(session, MonthlyComment, month_id)),
            None,
        ),
        "close": (None, None),
    }


def build_month_checklist(
    session: Session,
    month: ReportingMonth,
    *,
    readiness: CloseReadiness,
    summary: MonthlySummaryResult,
) -> MonthChecklist:
    facts = saved_section_facts(session, month)
    attention: dict[str, int] = {}
    for item in readiness.items:
        step_id = attention_step(item)
        if step_id is not None:
            attention[step_id] = attention.get(step_id, 0) + 1
    figures = _figures(session, month, summary)
    remarks = month_remarks(readiness)
    remark_counts: dict[str, int] = {}
    for item in remarks:
        # A global gap still needs a home so totals equal the sum of steps.
        destination = attention_step(item) or "close"
        remark_counts[destination] = remark_counts.get(destination, 0) + 1
    steps: list[ChecklistStep] = []
    for step_id, group in STEP_GROUPS:
        has_facts = facts[step_id]
        count = attention.get(step_id, 0)
        required = step_id not in OPTIONAL_STEPS
        if count:
            state: ChecklistState = "attention"
        elif has_facts:
            state = "done"
        elif not required:
            state = "optional"
        else:
            state = "empty"
        figure, secondary = figures[step_id]
        steps.append(
            ChecklistStep(
                id=step_id,
                group=group,
                required=required,
                has_saved_facts=has_facts,
                has_templates=any(
                    _count(
                        session, model, month.id, model.actual_fact_origin == "clone_template_v1"
                    )
                    for model in (
                        (IncomeEntry,)
                        if step_id == "income"
                        else (ExpenseEntry, SavingAllocation)
                        if step_id == "budget"
                        else ()
                    )
                ),
                state=state,
                attention_count=count,
                remark_count=remark_counts.get(step_id, 0),
                # A figure of an empty section would read as a zero fact.
                figure=figure if has_facts else None,
                secondary_count=secondary if has_facts else None,
            )
        )
    return MonthChecklist(
        completed_count=sum(facts.values()),
        total_count=len(facts),
        attention_count=sum(attention.values()),
        remarks=remarks,
        has_statement_positions=session.scalar(
            select(PositionSnapshot.id)
            .where(
                PositionSnapshot.reporting_month_id == month.id,
                PositionSnapshot.price_source == "broker_statement_native",
            )
            .limit(1)
        )
        is not None,
        steps=tuple(steps),
        mandatory_expenses_total=summary.cash_balance.breakdown.mandatory_expenses,
        other_expenses_total=summary.cash_balance.breakdown.other_expenses,
        mandatory_expense_items=_mandatory_expense_items(session, month.id),
    )
