"""Pure, no-write preview for migrating a known legacy Excel extraction.

This module deliberately consumes F08's in-memory extraction rather than any
SQLAlchemy service.  It produces a private report of what would be mapped,
what needs manual resolution, and which source control totals agree with the
Hermes Finance contract.  It never opens or writes a database.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from hermes_finance.services.legacy_excel import (
    LegacyExtractionWarning,
    LegacyMonthExtraction,
    LegacyWorkbookExtraction,
)


@dataclass(frozen=True, slots=True)
class UnmatchedLegacyRow:
    code: str
    sheet_name: str
    row: int | None
    reason: str


@dataclass(frozen=True, slots=True)
class ControlTotalDiff:
    key: str
    legacy_label: str
    unit: str
    legacy_value: int | Decimal
    calculated_value: int | Decimal | None
    delta: int | Decimal | None
    status: str


@dataclass(frozen=True, slots=True)
class MonthlyMigrationPreview:
    year: int
    month: int
    sheet_name: str
    counts: dict[str, int]
    calculated_kpis: dict[str, int]
    goal_progress_percent: Decimal | None
    control_diffs: tuple[ControlTotalDiff, ...]
    unmatched_rows: tuple[UnmatchedLegacyRow, ...]


@dataclass(frozen=True, slots=True)
class MigrationPreview:
    source_file: str
    dry_run: bool
    months: tuple[MonthlyMigrationPreview, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_file": self.source_file,
            "dry_run": self.dry_run,
            "months": [
                {
                    "reporting_month": {"year": month.year, "month": month.month},
                    "sheet_name": month.sheet_name,
                    "counts": month.counts,
                    "calculated_kpis": month.calculated_kpis,
                    "goal_progress_percent": (
                        None
                        if month.goal_progress_percent is None
                        else format(month.goal_progress_percent, "f")
                    ),
                    "control_diffs": [
                        {
                            "key": diff.key,
                            "legacy_label": diff.legacy_label,
                            "unit": diff.unit,
                            "legacy_value": _serialize_value(diff.legacy_value),
                            "calculated_value": _serialize_value(diff.calculated_value),
                            "delta": _serialize_value(diff.delta),
                            "status": diff.status,
                        }
                        for diff in month.control_diffs
                    ],
                    "unmatched_rows": [
                        {
                            "code": row.code,
                            "sheet_name": row.sheet_name,
                            "row": row.row,
                            "reason": row.reason,
                        }
                        for row in month.unmatched_rows
                    ],
                }
                for month in self.months
            ],
        }


def _serialize_value(value: int | Decimal | None) -> int | str | None:
    return format(value, "f") if isinstance(value, Decimal) else value


def _label(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


_CONTROL_KEYS = {
    "хранениеактивысуммарно": "assets_total",
    "хранениесучётомдолгов": "liquid_capital_net",
    "пассивныйдоходбезкэшбэка": "passive_income_excluding_cashback",
    "обязательныерасходы": "mandatory_expenses",
    "всегооткладываю": "saving_allocations",
    "сальдоостатоквмесяц": "monthly_cash_balance",
    "кцелипассивныйдоход": "goal_progress_percent",
}


_COUNTED_SECTIONS = (
    "deposits",
    "stocks",
    "bonds",
    "gold",
    "mandatory_expenses",
    "saving_allocations",
    "cashback",
    "debts_receivable",
    "debts_payable",
    "goals",
    "dividends",
    "comments",
)


def _sum_amount(rows: tuple[dict[str, Any], ...], field: str) -> int:
    return sum(int(value) for row in rows if isinstance((value := row.get(field)), int))


def _goal_progress(month: LegacyMonthExtraction, passive_income: int) -> Decimal | None:
    targets = [
        int(goal["amount_kopecks"])
        for goal in month.goals
        if "пассивныйдоход" in _label(str(goal.get("name", "")))
        and isinstance(goal.get("amount_kopecks"), int)
    ]
    if len(targets) != 1 or targets[0] == 0:
        return None
    return Decimal(passive_income) * Decimal(100) / Decimal(targets[0])


def _calculated_kpis(month: LegacyMonthExtraction) -> dict[str, int]:
    deposits = _sum_amount(month.deposits, "balance_kopecks")
    stocks = _sum_amount(month.stocks, "market_value_kopecks")
    bonds = _sum_amount(month.bonds, "market_value_kopecks")
    gold = _sum_amount(month.gold, "current_value_kopecks")
    debts = _sum_amount(month.debts_payable, "amount_kopecks")
    mandatory_expenses = _sum_amount(month.mandatory_expenses, "amount_kopecks")
    saving_allocations = _sum_amount(month.saving_allocations, "amount_kopecks")
    cashback = _sum_amount(month.cashback, "amount_kopecks")
    deposit_interest = _sum_amount(month.deposits, "expected_monthly_interest_kopecks")
    bond_coupons = _sum_amount(month.bonds, "monthly_coupon_kopecks")
    dividends = _sum_amount(month.dividends, "monthly_kopecks")
    passive_income = deposit_interest + bond_coupons + dividends
    salary = 0 if month.salary is None else int(month.salary["amount_kopecks"])
    assets_total = deposits + stocks + bonds + gold
    return {
        "assets_total": assets_total,
        "liquid_capital_net": assets_total - debts,
        "passive_income_excluding_cashback": passive_income,
        "mandatory_expenses": mandatory_expenses,
        "saving_allocations": saving_allocations,
        "monthly_cash_balance": (
            salary + cashback + passive_income - mandatory_expenses - saving_allocations
        ),
    }


def _warnings_for_month(
    warnings: tuple[LegacyExtractionWarning, ...], sheet_name: str
) -> tuple[UnmatchedLegacyRow, ...]:
    return tuple(
        UnmatchedLegacyRow(
            code=warning.code,
            sheet_name=warning.sheet_name,
            row=warning.row,
            reason=warning.message,
        )
        for warning in warnings
        if warning.sheet_name == sheet_name
    )


def _control_diffs(
    month: LegacyMonthExtraction,
    calculated_kpis: dict[str, int],
    goal_progress_percent: Decimal | None,
) -> tuple[ControlTotalDiff, ...]:
    diffs: list[ControlTotalDiff] = []
    for control in month.control_totals:
        label = str(control["label"])
        unit = str(control["unit"])
        key = _CONTROL_KEYS.get(_label(label))
        raw_value = control["value"]
        if unit == "percentage":
            try:
                legacy_value: int | Decimal = Decimal(str(raw_value))
            except (InvalidOperation, ValueError):
                continue
            calculated_value: int | Decimal | None = (
                goal_progress_percent if key == "goal_progress_percent" else None
            )
        else:
            legacy_value = int(raw_value)
            calculated_value = calculated_kpis.get(key) if key else None
        if calculated_value is None:
            status = "unmapped"
            delta: int | Decimal | None = None
        else:
            delta = calculated_value - legacy_value
            status = "matched" if delta == 0 else "different"
        diffs.append(
            ControlTotalDiff(
                key=key or "unmapped",
                legacy_label=label,
                unit=unit,
                legacy_value=legacy_value,
                calculated_value=calculated_value,
                delta=delta,
                status=status,
            )
        )
    return tuple(diffs)


def _counts(month: LegacyMonthExtraction) -> dict[str, int]:
    return {
        "salary": int(month.salary is not None),
        **{section: len(getattr(month, section)) for section in _COUNTED_SECTIONS},
    }


def build_migration_preview(extraction: LegacyWorkbookExtraction) -> MigrationPreview:
    """Build a deterministic F09 preview without writing to SQLite or the filesystem."""
    months: list[MonthlyMigrationPreview] = []
    for month in extraction.months:
        calculated_kpis = _calculated_kpis(month)
        goal_progress_percent = _goal_progress(
            month, calculated_kpis["passive_income_excluding_cashback"]
        )
        months.append(
            MonthlyMigrationPreview(
                year=month.reporting_month["year"],
                month=month.reporting_month["month"],
                sheet_name=month.sheet_name,
                counts=_counts(month),
                calculated_kpis=calculated_kpis,
                goal_progress_percent=goal_progress_percent,
                control_diffs=_control_diffs(month, calculated_kpis, goal_progress_percent),
                unmatched_rows=_warnings_for_month(extraction.warnings, month.sheet_name),
            )
        )
    return MigrationPreview(source_file=extraction.source_file, dry_run=True, months=tuple(months))


def _format_value(value: int | Decimal | None, unit: str) -> str:
    if value is None:
        return "—"
    if unit == "percentage":
        return f"{format(Decimal(value), '.2f')}%"
    return f"{int(value):,} коп.".replace(",", " ")


def _table(headers: tuple[str, ...], rows: tuple[tuple[str, ...], ...]) -> list[str]:
    lines = [f"| {' | '.join(headers)} |", f"| {' | '.join('---' for _ in headers)} |"]
    lines.extend(f"| {' | '.join(row)} |" for row in rows)
    return lines


def render_migration_preview_markdown(preview: MigrationPreview) -> str:
    """Render a private F09 report without source names, notes, or comments."""
    lines = [
        "# Preview миграции Excel — dry run",
        "",
        "- SQLite не открывался и не изменялся.",
        "- Отчёт не является импортом; unresolved rows требуют ручного решения перед F10.",
        "",
        "## Месяцы и строки",
    ]
    lines.extend(
        _table(
            ("Период", "Лист", "Строки", "Unmatched"),
            tuple(
                (
                    f"{month.year:04d}-{month.month:02d}",
                    month.sheet_name,
                    str(sum(month.counts.values())),
                    str(len(month.unmatched_rows)),
                )
                for month in preview.months
            ),
        )
    )
    for month in preview.months:
        lines.extend(("", f"## Control KPI diff — {month.year:04d}-{month.month:02d}"))
        lines.extend(
            _table(
                ("KPI", "Статус", "Excel", "Preview", "Delta"),
                tuple(
                    (
                        diff.key,
                        diff.status,
                        _format_value(diff.legacy_value, diff.unit),
                        _format_value(diff.calculated_value, diff.unit),
                        _format_value(diff.delta, diff.unit),
                    )
                    for diff in month.control_diffs
                ),
            )
        )
        lines.extend(("", f"## Unmatched rows — {month.year:04d}-{month.month:02d}"))
        if month.unmatched_rows:
            lines.extend(
                _table(
                    ("Code", "Лист", "Строка", "Причина"),
                    tuple(
                        (row.code, row.sheet_name, str(row.row or "—"), row.reason)
                        for row in month.unmatched_rows
                    ),
                )
            )
        else:
            lines.append("Нет.")
    return "\n".join(lines) + "\n"
