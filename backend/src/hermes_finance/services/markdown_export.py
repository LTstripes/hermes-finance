"""Pure deterministic Markdown rendering for one C10/D07 report.

The renderer reads accepted C10/D07 values and prints explicit month-scoped
rows supplied by the caller for data not exposed by the D07 DTO. It does not
query persistence, aggregate rows, or recalculate financial formulas.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Callable, Iterable, TypeVar

from hermes_finance.domain.values import RubleAmount

if TYPE_CHECKING:
    from hermes_finance.services.dashboard import DashboardResult


@dataclass(frozen=True, slots=True)
class IncomeReportRow:
    name: str
    income_type: str
    gross: RubleAmount
    tax: RubleAmount
    net: RubleAmount


@dataclass(frozen=True, slots=True)
class InvestmentFlowReportRow:
    event_date: date
    flow_type: str
    gross: RubleAmount
    tax: RubleAmount
    commission: RubleAmount
    net: RubleAmount


@dataclass(frozen=True, slots=True)
class ExpenseReportRow:
    category: str
    expense_type: str
    amount: RubleAmount


@dataclass(frozen=True, slots=True)
class DebtReportRow:
    name: str
    debt_type: str
    balance: RubleAmount
    included_in_liquid_capital: bool


@dataclass(frozen=True, slots=True)
class GoalReportRow:
    name: str
    goal_type: str
    target: RubleAmount
    progress_pct: Decimal | None


@dataclass(frozen=True, slots=True)
class MarkdownReport:
    """Input for one deterministic Markdown report.

    ``dashboard`` is the accepted D07 result and remains the source of all
    calculated KPI, allocation, forecast, mortgage, goal and warning values.
    The additional row collections are already-assembled read-model rows for
    sections that D07 intentionally does not expose. They are printed as
    supplied and are never summed or interpreted here.
    """

    dashboard: DashboardResult
    income_rows: tuple[IncomeReportRow, ...] = ()
    investment_flow_rows: tuple[InvestmentFlowReportRow, ...] = ()
    expense_rows: tuple[ExpenseReportRow, ...] = ()
    debt_rows: tuple[DebtReportRow, ...] = ()
    goal_rows: tuple[GoalReportRow, ...] = ()
    comments: tuple[str, ...] = ()


T = TypeVar("T")

_MONTH_NAMES_RU = (
    "Январь",
    "Февраль",
    "Март",
    "Апрель",
    "Май",
    "Июнь",
    "Июль",
    "Август",
    "Сентябрь",
    "Октябрь",
    "Ноябрь",
    "Декабрь",
)
_ASSET_ORDER = {
    name: index for index, name in enumerate(("cash", "deposits", "stocks", "bonds", "gold_other"))
}
_INCOME_ORDER = {
    name: index
    for index, name in enumerate(("salary", "bonus", "side_income", "cashback", "other"))
}
_EXPENSE_ORDER = {name: index for index, name in enumerate(("mandatory", "comfortable", "other"))}
_NUMERIC_HEADERS = frozenset(
    {
        "Значение",
        "Изменение",
        "Сумма",
        "Gross",
        "Налог",
        "Комиссия",
        "Net",
        "Остаток",
        "Цель",
        "Прогресс",
        "Денежный доход",
        "Нереализованный результат",
    }
)


def _ordered(items: Iterable[T], key: Callable[[T], object]) -> tuple[T, ...]:
    return tuple(sorted(items, key=key))


def _format_date(value: date) -> str:
    return value.strftime("%d.%m.%Y")


def _format_money(amount: RubleAmount) -> str:
    text = format(abs(amount.as_decimal()), ".2f")
    integer, fraction = text.split(".")
    groups: list[str] = []
    while integer:
        groups.append(integer[-3:])
        integer = integer[:-3]
    grouped = " ".join(reversed(groups))
    cents = "" if fraction == "00" else f",{fraction}"
    sign = "−" if amount.kopecks < 0 else ""
    return f"{sign}{grouped}{cents} ₽"


def _format_delta(amount: RubleAmount | None) -> str:
    if amount is None:
        return "—"
    if amount.kopecks > 0:
        return f"+{_format_money(amount)}"
    return _format_money(amount)


def _format_percent(value: Decimal | None) -> str:
    if value is None:
        return "—"
    return f"{format(value, '.2f').replace('.', ',')}%"


def _escape_cell(value: str) -> str:
    """Escape user text so it remains one Markdown table cell."""
    normalized = value.replace(chr(13), "")
    return normalized.replace("\\", "\\\\").replace("|", "\\|").replace("\n", "<br>")


def _table(headers: tuple[str, ...], rows: Iterable[tuple[str, ...]]) -> list[str]:
    materialized = tuple(rows)
    width = len(headers)
    if any(len(row) != width for row in materialized):
        raise ValueError("Markdown table row width must match header width")
    alignments = tuple("---:" if header in _NUMERIC_HEADERS else "---" for header in headers)
    escaped_headers = tuple(_escape_cell(header) for header in headers)
    escaped_rows = tuple(tuple(_escape_cell(cell) for cell in row) for row in materialized)
    lines = [f"| {' | '.join(escaped_headers)} |", f"| {' | '.join(alignments)} |"]
    lines.extend(f"| {' | '.join(row)} |" for row in escaped_rows)
    return lines


def _append_table(
    lines: list[str], headers: tuple[str, ...], rows: Iterable[tuple[str, ...]]
) -> None:
    lines.extend(_table(headers, rows))


def _account_names(dashboard: DashboardResult) -> dict[int, str]:
    return {item.account_id: item.account_name for item in dashboard.result_by_account}


def _render_metadata(lines: list[str], dashboard: DashboardResult) -> None:
    month = dashboard.month
    month_name = _MONTH_NAMES_RU[month.month - 1]
    lines.extend(
        (
            f"# Финансовый отчёт — {month_name} {month.year}",
            "",
            "## 1. Метаданные периода",
            f"- Период: {_format_date(month.period_start)} — {_format_date(month.period_end)}",
            f"- Статус: {month.status}",
            f"- Дата снимка: {_format_date(month.snapshot_date)}",
            f"- Источник: {month.source}",
            f"- Версия расчётов: {dashboard.summary.calculation_version}",
            "",
        )
    )


def _render_kpis(lines: list[str], dashboard: DashboardResult) -> None:
    summary = dashboard.summary
    lines.extend(("## 2. Итоговые KPI",))
    _append_table(
        lines,
        ("Показатель", "Значение"),
        (
            ("Ликвидный капитал (net)", _format_money(summary.liquid_capital.liquid_capital_net)),
            ("Фактический пассивный доход", _format_money(summary.passive_income_actual)),
            ("Средний пассивный доход", _format_money(summary.passive_income_average)),
            (
                "Прогноз пассивного дохода за 12 месяцев",
                _format_money(summary.forecast.annual_total),
            ),
            (
                "Прогноз пассивного дохода в месяц",
                _format_money(summary.forecast.monthly_total),
            ),
            ("Денежный остаток месяца", _format_money(summary.cash_balance.total)),
            (
                "Налог с зарплаты (расчётный)",
                _format_money(RubleAmount(summary.salary_tax.tax_kopecks)),
            ),
            ("Фактический net зарплаты", _format_money(summary.salary_actual_net)),
            (
                "Нормализованная премия в месяц",
                _format_money(summary.normalized_bonus.monthly_average),
            ),
        ),
    )
    lines.append("")


def _render_changes(lines: list[str], dashboard: DashboardResult) -> None:
    summary = dashboard.summary
    lines.extend(("## 3. Изменения к предыдущему месяцу",))
    _append_table(
        lines,
        ("Показатель", "Изменение"),
        (
            ("Ликвидный капитал (net)", _format_delta(summary.liquid_capital_delta)),
            ("Фактический пассивный доход", _format_delta(summary.passive_income_delta)),
        ),
    )
    lines.append("")


def _render_assets(lines: list[str], dashboard: DashboardResult) -> None:
    account_names = _account_names(dashboard)
    lines.extend(("## 4. Активы", "### По классам"))
    allocation = _ordered(
        dashboard.asset_allocation,
        key=lambda item: (_ASSET_ORDER.get(item.asset_class, len(_ASSET_ORDER)), item.asset_class),
    )
    _append_table(
        lines,
        ("Класс", "Сумма"),
        ((item.asset_class, _format_money(item.amount)) for item in allocation),
    )
    lines.extend(("", "### По счетам — ликвидные активы"))
    accounts = _ordered(
        dashboard.summary.liquid_capital.accounts,
        key=lambda item: (
            account_names.get(item.account_id, f"Счёт {item.account_id}"),
            item.account_id,
        ),
    )
    _append_table(
        lines,
        ("Счёт", "Сумма"),
        (
            (
                f"{account_names.get(item.account_id, f'Счёт {item.account_id}')} ({item.account_id})",
                _format_money(item.amount),
            )
            for item in accounts
        ),
    )
    lines.extend(("", "### Результат по счетам"))
    results = _ordered(
        dashboard.result_by_account, key=lambda item: (item.account_name, item.account_id)
    )
    _append_table(
        lines,
        ("Счёт", "Денежный доход", "Нереализованный результат"),
        (
            (
                item.account_name,
                _format_money(item.cash_income),
                _format_money(item.unrealized_result),
            )
            for item in results
        ),
    )
    lines.append("")


def _render_incomes(lines: list[str], report: MarkdownReport) -> None:
    lines.extend(("## 5. Доходы",))
    rows = _ordered(
        report.income_rows,
        key=lambda item: (_INCOME_ORDER.get(item.income_type, len(_INCOME_ORDER)), item.name),
    )
    _append_table(
        lines,
        ("Название", "Тип", "Gross", "Налог", "Net"),
        (
            (
                item.name,
                item.income_type,
                _format_money(item.gross),
                _format_money(item.tax),
                _format_money(item.net),
            )
            for item in rows
        ),
    )
    lines.append("")


def _render_passive_income(lines: list[str], dashboard: DashboardResult) -> None:
    summary = dashboard.summary
    breakdown = summary.forecast.breakdown
    lines.extend(("## 6. Пассивный доход",))
    _append_table(
        lines,
        ("Показатель", "Значение"),
        (
            ("Фактический net пассивный доход", _format_money(summary.passive_income_actual)),
            ("Среднее за доступный период", _format_money(summary.passive_income_average)),
            ("Прогноз за 12 месяцев", _format_money(summary.forecast.annual_total)),
            ("Прогноз в месяц", _format_money(summary.forecast.monthly_total)),
            (
                "Дивидендный компонент прогноза",
                _format_money(breakdown.expected_dividend_component),
            ),
            (
                "Ожидаемые проценты депозитов",
                _format_money(breakdown.expected_deposit_interest),
            ),
            ("Ожидаемые купоны net", _format_money(breakdown.expected_coupon_net)),
            (
                "Прочий ожидаемый капитал",
                _format_money(breakdown.other_expected_capital_income),
            ),
        ),
    )
    lines.append("")


def _render_flows(lines: list[str], report: MarkdownReport) -> None:
    lines.extend(("## 7. Инвестиционные выплаты",))
    flows = _ordered(
        report.investment_flow_rows, key=lambda item: (item.event_date, item.flow_type)
    )
    _append_table(
        lines,
        ("Дата", "Тип", "Gross", "Налог", "Комиссия", "Net"),
        (
            (
                _format_date(item.event_date),
                item.flow_type,
                _format_money(item.gross),
                _format_money(item.tax),
                _format_money(item.commission),
                _format_money(item.net),
            )
            for item in flows
        ),
    )
    lines.extend(("", "### Ожидаемые выплаты"))
    payments = _ordered(
        report.dashboard.expected_payments,
        key=lambda item: (item.expected_date, item.flow_type, item.id),
    )
    _append_table(
        lines,
        ("Дата", "Тип", "Net", "Подтверждено", "Приблизительно"),
        (
            (
                _format_date(item.expected_date),
                item.flow_type,
                _format_money(item.expected_net_amount),
                "да" if item.is_confirmed else "нет",
                "да" if item.is_approximate else "нет",
            )
            for item in payments
        ),
    )
    lines.append("")


def _render_expenses(lines: list[str], report: MarkdownReport) -> None:
    summary = report.dashboard.summary
    rows = _ordered(
        report.expense_rows,
        key=lambda item: (
            _EXPENSE_ORDER.get(item.expense_type, len(_EXPENSE_ORDER)),
            item.category,
        ),
    )
    lines.extend(("## 8. Расходы",))
    _append_table(
        lines,
        ("Категория", "Тип", "Сумма"),
        ((item.category, item.expense_type, _format_money(item.amount)) for item in rows),
    )
    lines.append("")
    _append_table(
        lines,
        ("Итоговый показатель", "Значение"),
        (
            (
                "Обязательные расходы",
                _format_money(summary.cash_balance.breakdown.mandatory_expenses),
            ),
            ("Прочие расходы", _format_money(summary.cash_balance.breakdown.other_expenses)),
            ("Сбережения", _format_money(summary.cash_balance.breakdown.saving_allocations)),
        ),
    )
    lines.append("")


def _render_debts(lines: list[str], report: MarkdownReport) -> None:
    summary = report.dashboard.summary
    debts = _ordered(report.debt_rows, key=lambda item: (item.name, item.debt_type))
    lines.extend(("## 9. Долги",))
    _append_table(
        lines,
        ("Название", "Тип", "Остаток", "В ликвидном капитале"),
        (
            (
                item.name,
                item.debt_type,
                _format_money(item.balance),
                "да" if item.included_in_liquid_capital else "нет",
            )
            for item in debts
        ),
    )
    lines.append("")
    _append_table(
        lines,
        ("Показатель", "Значение"),
        (
            (
                "Итого учитываемые долги",
                _format_money(summary.liquid_capital.total_debts_included),
            ),
        ),
    )
    lines.append("")


def _render_mortgage(lines: list[str], dashboard: DashboardResult) -> None:
    mortgage = dashboard.mortgage
    lines.extend(("## 10. Ипотека",))
    _append_table(
        lines,
        ("Показатель", "Значение"),
        (
            ("Остаток ипотеки", _format_money(mortgage.mortgage_balance)),
            ("Покрытие ликвидным капиталом", _format_percent(mortgage.coverage_pct)),
            ("Разрыв покрытия", _format_money(mortgage.gap)),
        ),
    )
    lines.append("")


def _render_goals(lines: list[str], report: MarkdownReport) -> None:
    summary = report.dashboard.summary
    goals = report.goal_rows or (
        GoalReportRow(
            "Основная цель",
            "monthly_net_passive_income",
            summary.coverage.goal_target,
            summary.coverage.goal_progress_pct,
        ),
    )
    goals = _ordered(goals, key=lambda item: (item.name, item.goal_type))
    lines.extend(("## 11. Цели",))
    _append_table(
        lines,
        ("Название", "Тип", "Цель", "Прогресс"),
        (
            (
                item.name,
                item.goal_type,
                _format_money(item.target),
                _format_percent(item.progress_pct),
            )
            for item in goals
        ),
    )
    lines.append("")


def _render_comments(lines: list[str], report: MarkdownReport) -> None:
    lines.extend(("## 12. Комментарии",))
    if report.comments:
        lines.extend(f"{index}. {text}" for index, text in enumerate(report.comments, start=1))
    else:
        lines.append("Нет комментариев.")
    lines.append("")


def _render_warnings(lines: list[str], dashboard: DashboardResult) -> None:
    lines.extend(("## 13. Предупреждения о неполных данных",))
    if dashboard.warnings:
        lines.extend(f"{index}. {text}" for index, text in enumerate(dashboard.warnings, start=1))
    else:
        lines.append("Нет предупреждений.")


def render_markdown_report(report: MarkdownReport) -> str:
    """Return deterministic UTF-8-compatible Markdown text."""
    lines: list[str] = []
    _render_metadata(lines, report.dashboard)
    _render_kpis(lines, report.dashboard)
    _render_changes(lines, report.dashboard)
    _render_assets(lines, report.dashboard)
    _render_incomes(lines, report)
    _render_passive_income(lines, report.dashboard)
    _render_flows(lines, report)
    _render_expenses(lines, report)
    _render_debts(lines, report)
    _render_mortgage(lines, report.dashboard)
    _render_goals(lines, report)
    _render_comments(lines, report)
    _render_warnings(lines, report.dashboard)
    return "\n".join(lines) + "\n"
