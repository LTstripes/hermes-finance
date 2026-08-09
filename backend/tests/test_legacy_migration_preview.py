import json
from decimal import Decimal
from pathlib import Path

from hermes_finance.legacy_migration_preview_cli import main
from hermes_finance.services.legacy_excel import (
    LegacyExtractionWarning,
    LegacyMonthExtraction,
    LegacyWorkbookExtraction,
)
from hermes_finance.services.legacy_migration_preview import (
    build_migration_preview,
    render_migration_preview_markdown,
)


def _extraction() -> LegacyWorkbookExtraction:
    month = LegacyMonthExtraction(
        sheet_name="Январь_2026",
        reporting_month={"year": 2026, "month": 1},
        snapshot_date="2026-01-31",
        salary={"name": "salary", "amount_kopecks": 10_000},
        deposits=(
            {
                "name": "Synthetic deposit",
                "balance_kopecks": 10_000,
                "expected_monthly_interest_kopecks": 100,
            },
        ),
        stocks=(
            {
                "source_row": 61,
                "name": "Synthetic stock",
                "isin": None,
                "account": "Synthetic account",
                "quantity": "1",
                "market_value_kopecks": 2_000,
            },
        ),
        bonds=(
            {
                "source_row": 46,
                "name": "Synthetic bond",
                "isin": "SYNTHISIN",
                "account": "Synthetic account",
                "quantity": "1",
                "market_value_kopecks": 3_000,
                "monthly_coupon_kopecks": 200,
            },
        ),
        gold=(
            {
                "name": "Synthetic gold",
                "current_value_kopecks": 4_000,
            },
        ),
        mandatory_expenses=({"name": "Synthetic expense", "amount_kopecks": 3_000},),
        saving_allocations=({"name": "Synthetic savings", "amount_kopecks": 2_000},),
        cashback=({"name": "Synthetic cashback", "amount_kopecks": 100},),
        debts_receivable=(),
        debts_payable=({"name": "Synthetic debt", "amount_kopecks": 1_000},),
        goals=({"name": "Пассивный доход в месяц", "amount_kopecks": 6_000},),
        dividends=({"period": "Synthetic period", "monthly_kopecks": 300},),
        comments=(),
        control_totals=(
            {"label": "Хранение (активы суммарно)", "unit": "RUB", "value": 19_000},
            {"label": "Хранение с учётом долгов", "unit": "RUB", "value": 18_000},
            {"label": "Пассивный доход без кэшбэка", "unit": "RUB", "value": 600},
            {"label": "Обязательные расходы", "unit": "RUB", "value": 3_000},
            {"label": "Всего откладываю", "unit": "RUB", "value": 2_000},
            {"label": "Сальдо: остаток в месяц", "unit": "RUB", "value": 5_800},
            {"label": "% к цели «пассивный доход»", "unit": "percentage", "value": "10.00"},
        ),
    )
    return LegacyWorkbookExtraction(
        source_file="synthetic.xlsx",
        months=(month,),
        warnings=(
            LegacyExtractionWarning(
                code="empty_isin",
                sheet_name="Январь_2026",
                row=61,
                message="instrument row has no ISIN",
            ),
        ),
    )


def test_builds_dry_run_preview_with_kpis_diffs_and_unmatched_rows() -> None:
    preview = build_migration_preview(_extraction())
    month = preview.months[0]

    assert preview.dry_run is True
    assert month.counts["stocks"] == 1
    assert month.calculated_kpis == {
        "assets_total": 19_000,
        "liquid_capital_net": 18_000,
        "passive_income_excluding_cashback": 600,
        "mandatory_expenses": 3_000,
        "saving_allocations": 2_000,
        "monthly_cash_balance": 5_700,
    }
    assert month.goal_progress_percent == Decimal("10")
    assert month.unmatched_rows[0].code == "empty_isin"
    assert month.unmatched_rows[0].row == 61
    assert {diff.key: diff.status for diff in month.control_diffs} == {
        "assets_total": "matched",
        "liquid_capital_net": "matched",
        "passive_income_excluding_cashback": "matched",
        "mandatory_expenses": "matched",
        "saving_allocations": "matched",
        "monthly_cash_balance": "different",
        "goal_progress_percent": "matched",
    }


def test_renders_private_dry_run_markdown_without_instrument_names() -> None:
    report = render_migration_preview_markdown(build_migration_preview(_extraction()))

    assert "# Preview миграции Excel — dry run" in report
    assert "## Unmatched rows" in report
    assert "empty_isin" in report
    assert "Synthetic stock" not in report
    assert "Synthetic bond" not in report


def test_cli_writes_private_preview_artifacts_and_prints_aggregate_only(
    tmp_path: Path, capsys: object, monkeypatch: object
) -> None:
    json_path = tmp_path / "preview.json"
    markdown_path = tmp_path / "preview.md"
    monkeypatch.setattr(
        "hermes_finance.legacy_migration_preview_cli.extract_legacy_workbook",
        lambda workbook, mapping: _extraction(),
    )

    assert (
        main(
            [
                "--workbook",
                str(tmp_path / "synthetic.xlsx"),
                "--mapping",
                str(tmp_path / "mapping.json"),
                "--json-output",
                str(json_path),
                "--markdown-output",
                str(markdown_path),
            ]
        )
        == 0
    )

    output = capsys.readouterr().out
    assert output == "legacy migration preview is valid: months=1 unmatched=1 different=1\n"
    assert "Synthetic" not in output
    assert json.loads(json_path.read_text(encoding="utf-8"))["dry_run"] is True
    assert "Synthetic stock" not in markdown_path.read_text(encoding="utf-8")
