from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from hermes_finance.domain.cash_balance import CashBalanceBreakdown, CashBalanceResult
from hermes_finance.domain.coverage_goals import CoverageGoalsResult
from hermes_finance.domain.forecast_passive_income import (
    ForecastPassiveIncomeBreakdown,
    ForecastPassiveIncomeResult,
)
from hermes_finance.domain.iis_result import IisResult, IisResultBreakdown
from hermes_finance.domain.liquid_capital import (
    AccountAmount,
    LiquidCapitalClassBreakdown,
    LiquidCapitalResult,
)
from hermes_finance.domain.monthly_summary import MonthlySummaryResult
from hermes_finance.domain.normalized_bonus import NormalizedBonusResult
from hermes_finance.domain.salary_tax import SalaryTaxResult
from hermes_finance.domain.values import RubleAmount
from hermes_finance.services.dashboard import (
    AccountResultSlice,
    AssetClassSlice,
    DashboardResult,
    ExpectedPaymentItem,
    InstrumentClassResult,
    MortgageCoverageSlice,
)
from hermes_finance.services.markdown_export import (
    DebtReportRow,
    ExpenseReportRow,
    GoalReportRow,
    IncomeReportRow,
    InvestmentFlowReportRow,
    MarkdownReport,
    render_markdown_report,
)

R = RubleAmount


def make_dashboard() -> DashboardResult:
    summary = MonthlySummaryResult(
        year=2026,
        month=7,
        liquid_capital=LiquidCapitalResult(
            total_assets=R(137_500_000),
            total_debts_included=R(12_500_000),
            liquid_capital_net=R(125_000_000),
            breakdown=LiquidCapitalClassBreakdown(
                cash=R(12_000_000),
                deposits=R(25_000_000),
                securities=R(100_000_000),
                other_liquid_assets=R(500_000),
            ),
            accounts=(AccountAmount(1, R(90_000_000)), AccountAmount(2, R(35_000_000))),
        ),
        liquid_capital_delta=R(12_500_000),
        passive_income_actual=R(4_525_000),
        passive_income_delta=R(-275_000),
        passive_income_average=R(4_000_000),
        passive_income_average_months=6,
        passive_income_average_complete=False,
        forecast=ForecastPassiveIncomeResult(
            annual_total=R(72_000_000),
            monthly_total=R(6_000_000),
            breakdown=ForecastPassiveIncomeBreakdown(
                expected_deposit_interest=R(24_000_000),
                expected_coupon_net=R(18_000_000),
                expected_dividend_component=R(24_000_000),
                other_expected_capital_income=R(6_000_000),
            ),
            is_approximate=True,
            warnings=("Прогноз содержит приблизительные суммы",),
            dividend_average=R(2_000_000),
            dividend_months_used=(),
        ),
        coverage=CoverageGoalsResult(
            forecast_monthly=R(6_000_000),
            actual_average=R(4_000_000),
            mandatory_expenses=R(5_000_000),
            coverage_pct=Decimal("120.00"),
            passive_income_minus_mandatory_expenses=R(1_000_000),
            goal_target=R(10_000_000),
            goal_progress_pct=Decimal("60.00"),
            is_approximate=True,
            warnings=(),
        ),
        cash_balance=CashBalanceResult(
            total=R(17_325_000),
            breakdown=CashBalanceBreakdown(
                salary_net=R(18_000_000),
                bonus_net=R(3_000_000),
                side_income_net=R(1_500_000),
                cashback=R(300_000),
                passive_income=R(4_525_000),
                mandatory_expenses=R(5_000_000),
                other_expenses=R(2_000_000),
                saving_allocations=R(3_000_000),
            ),
        ),
        salary_tax=SalaryTaxResult(
            tax_kopecks=3_000_000,
            calculated_net_kopecks=18_000_000,
            parts=(),
        ),
        salary_actual_net=R(18_000_000),
        normalized_bonus=NormalizedBonusResult(
            monthly_average=R(2_500_000),
            sum_total=R(15_000_000),
            count_months=6,
            is_complete_12m=False,
            months=(),
            warnings=("Премия оценена по 6 месяцев из 12",),
        ),
        iis=(
            IisResult(
                portfolio_result_without_tax_benefit=R(12_000_000),
                portfolio_result_with_tax_benefit=R(13_000_000),
                breakdown=IisResultBreakdown(
                    unrealized=R(7_000_000),
                    coupons=R(2_000_000),
                    dividends=R(1_000_000),
                    realized_pnl=R(2_000_000),
                    received_tax_benefits=R(1_000_000),
                    planned_tax_benefits=R(500_000),
                    submitted_tax_benefits=R(250_000),
                ),
            ),
        ),
        warnings=(
            "Среднее за доступный период. Учтено 6 месяцев из 12.",
            "Прогноз содержит приблизительные суммы",
            "Премия оценена по 6 месяцев из 12",
        ),
    )
    month = SimpleNamespace(
        year=2026,
        month=7,
        period_start=date(2026, 7, 1),
        period_end=date(2026, 7, 31),
        snapshot_date=date(2026, 7, 31),
        status="closed",
        source="manual",
    )
    return DashboardResult(
        month=month,
        summary=summary,
        historical_series=(),
        asset_allocation=(
            AssetClassSlice("stocks", R(70_000_000)),
            AssetClassSlice("cash", R(12_000_000)),
            AssetClassSlice("bonds", R(30_000_000)),
        ),
        result_by_account=(
            AccountResultSlice(2, "Сберегательный счёт", "savings", R(500_000), R(-100_000)),
            AccountResultSlice(1, "Тестовый брокер", "brokerage", R(1_500_000), R(3_500_000)),
        ),
        result_by_instrument_class=(
            InstrumentClassResult(
                "stock", R(70_000_000), R(65_000_000), R(5_000_000), R(1_000_000)
            ),
        ),
        expected_payments=(
            ExpectedPaymentItem(
                id=2,
                expected_date=date(2026, 8, 10),
                flow_type="dividend",
                account_id=1,
                instrument_id=4,
                gross_amount=R(900_000),
                expected_tax_amount=R(117_000),
                expected_net_amount=R(783_000),
                is_confirmed=False,
                is_approximate=True,
                source="manual",
                forecast_version="v1",
            ),
            ExpectedPaymentItem(
                id=1,
                expected_date=date(2026, 8, 5),
                flow_type="coupon",
                account_id=1,
                instrument_id=3,
                gross_amount=R(2_000_000),
                expected_tax_amount=None,
                expected_net_amount=R(2_000_000),
                is_confirmed=True,
                is_approximate=False,
                source="manual",
                forecast_version="v1",
            ),
        ),
        mortgage=MortgageCoverageSlice(R(50_000_000), Decimal("250.00"), R(75_000_000)),
        warnings=summary.warnings,
    )


def test_render_markdown_report_has_complete_stable_snapshot() -> None:
    report = MarkdownReport(
        dashboard=make_dashboard(),
        income_rows=(
            IncomeReportRow("Зарплата", "salary", R(21_000_000), R(3_000_000), R(18_000_000)),
            IncomeReportRow("Премия", "bonus", R(3_500_000), R(500_000), R(3_000_000)),
        ),
        investment_flow_rows=(
            InvestmentFlowReportRow(
                date(2026, 7, 15), "coupon", R(2_000_000), R(200_000), R(0), R(1_800_000)
            ),
            InvestmentFlowReportRow(
                date(2026, 7, 20), "redemption", R(10_000_000), R(0), R(0), R(10_000_000)
            ),
        ),
        expense_rows=(
            ExpenseReportRow("Аренда", "mandatory", R(5_000_000)),
            ExpenseReportRow("Кино", "comfortable", R(800_000)),
        ),
        debt_rows=(DebtReportRow("Кредитная карта", "credit_card", R(12_500_000), True),),
        goal_rows=(
            GoalReportRow("Пассивный доход", "passive_income", R(10_000_000), Decimal("60.00")),
        ),
        comments=(
            "Закрыл месяц после сверки брокерского отчёта.",
            "Проверить дивиденды в августе.",
        ),
    )

    actual = render_markdown_report(report)

    expected = """# Финансовый отчёт — Июль 2026

## 1. Метаданные периода
- Период: 01.07.2026 — 31.07.2026
- Статус: closed
- Дата снимка: 31.07.2026
- Источник: manual
- Версия расчётов: v1

## 2. Итоговые KPI
| Показатель | Значение |
| --- | ---: |
| Ликвидный капитал (net) | 1 250 000 ₽ |
| Фактический пассивный доход | 45 250 ₽ |
| Средний пассивный доход | 40 000 ₽ |
| Прогноз пассивного дохода за 12 месяцев | 720 000 ₽ |
| Прогноз пассивного дохода в месяц | 60 000 ₽ |
| Денежный остаток месяца | 173 250 ₽ |
| Налог с зарплаты (расчётный) | 30 000 ₽ |
| Фактический net зарплаты | 180 000 ₽ |
| Нормализованная премия в месяц | 25 000 ₽ |

## 3. Изменения к предыдущему месяцу
| Показатель | Изменение |
| --- | ---: |
| Ликвидный капитал (net) | +125 000 ₽ |
| Фактический пассивный доход | −2 750 ₽ |

## 4. Активы
### По классам
| Класс | Сумма |
| --- | ---: |
| cash | 120 000 ₽ |
| stocks | 700 000 ₽ |
| bonds | 300 000 ₽ |

### По счетам — ликвидные активы
| Счёт | Сумма |
| --- | ---: |
| Сберегательный счёт (2) | 350 000 ₽ |
| Тестовый брокер (1) | 900 000 ₽ |

### Результат по счетам
| Счёт | Денежный доход | Нереализованный результат |
| --- | ---: | ---: |
| Сберегательный счёт | 5 000 ₽ | −1 000 ₽ |
| Тестовый брокер | 15 000 ₽ | 35 000 ₽ |

## 5. Доходы
| Название | Тип | Gross | Налог | Net |
| --- | --- | ---: | ---: | ---: |
| Зарплата | salary | 210 000 ₽ | 30 000 ₽ | 180 000 ₽ |
| Премия | bonus | 35 000 ₽ | 5 000 ₽ | 30 000 ₽ |

## 6. Пассивный доход
| Показатель | Значение |
| --- | ---: |
| Фактический net пассивный доход | 45 250 ₽ |
| Среднее за доступный период | 40 000 ₽ |
| Прогноз за 12 месяцев | 720 000 ₽ |
| Прогноз в месяц | 60 000 ₽ |
| Дивидендный компонент прогноза | 240 000 ₽ |
| Ожидаемые проценты депозитов | 240 000 ₽ |
| Ожидаемые купоны net | 180 000 ₽ |
| Прочий ожидаемый капитал | 60 000 ₽ |

## 7. Инвестиционные выплаты
| Дата | Тип | Gross | Налог | Комиссия | Net |
| --- | --- | ---: | ---: | ---: | ---: |
| 15.07.2026 | coupon | 20 000 ₽ | 2 000 ₽ | 0 ₽ | 18 000 ₽ |
| 20.07.2026 | redemption | 100 000 ₽ | 0 ₽ | 0 ₽ | 100 000 ₽ |

### Ожидаемые выплаты
| Дата | Тип | Net | Подтверждено | Приблизительно |
| --- | --- | ---: | --- | --- |
| 05.08.2026 | coupon | 20 000 ₽ | да | нет |
| 10.08.2026 | dividend | 7 830 ₽ | нет | да |

## 8. Расходы
| Категория | Тип | Сумма |
| --- | --- | ---: |
| Аренда | mandatory | 50 000 ₽ |
| Кино | comfortable | 8 000 ₽ |

| Итоговый показатель | Значение |
| --- | ---: |
| Обязательные расходы | 50 000 ₽ |
| Прочие расходы | 20 000 ₽ |
| Сбережения | 30 000 ₽ |

## 9. Долги
| Название | Тип | Остаток | В ликвидном капитале |
| --- | --- | ---: | --- |
| Кредитная карта | credit_card | 125 000 ₽ | да |

| Показатель | Значение |
| --- | ---: |
| Итого учитываемые долги | 125 000 ₽ |

## 10. Ипотека
| Показатель | Значение |
| --- | ---: |
| Остаток ипотеки | 500 000 ₽ |
| Покрытие ликвидным капиталом | 250,00% |
| Разрыв покрытия | 750 000 ₽ |

## 11. Цели
| Название | Тип | Цель | Прогресс |
| --- | --- | ---: | ---: |
| Пассивный доход | passive_income | 100 000 ₽ | 60,00% |

## 12. Комментарии
1. Закрыл месяц после сверки брокерского отчёта.
2. Проверить дивиденды в августе.

## 13. Предупреждения о неполных данных
1. Среднее за доступный период. Учтено 6 месяцев из 12.
2. Прогноз содержит приблизительные суммы
3. Премия оценена по 6 месяцев из 12
"""

    assert actual == expected
    assert actual.encode("utf-8").decode("utf-8") == actual

    for line in actual.splitlines():
        if line.startswith("|") and line.endswith("|"):
            assert line.count("|") >= 3


def test_render_markdown_report_escapes_table_delimiters_and_newlines() -> None:
    report = MarkdownReport(
        dashboard=make_dashboard(),
        income_rows=(IncomeReportRow("A|B\nC\\D", "salary", R(100), R(0), R(100)),),
    )

    actual = render_markdown_report(report)

    assert "| A\\|B<br>C\\\\D | salary | 1 ₽ | 0 ₽ | 1 ₽ |" in actual
