"""Read-only total-income analytics; money is integer kopecks throughout."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal

from hermes_finance.domain.values import FINANCIAL_ROUNDING, RubleAmount


@dataclass(frozen=True, slots=True)
class TotalIncomePoint:
    reporting_month_id: int
    year: int
    month: int
    salary_net: RubleAmount
    bonus_net: RubleAmount
    passive_actual: RubleAmount | None
    other_net: RubleAmount
    salary_is_estimate: bool = False

    @property
    def key(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"


@dataclass(frozen=True, slots=True)
class TotalIncomeWindow:
    from_month: str | None
    to_month: str | None
    months_observed: int
    months_used: tuple[str, ...]
    salary_months: int
    passive_months: int
    bonus_months: int
    estimate_months: int
    salary_sum: RubleAmount | None
    passive_sum: RubleAmount | None
    bonus_sum: RubleAmount | None
    other_sum: RubleAmount | None
    salary_monthly_average: RubleAmount | None
    passive_monthly_average: RubleAmount | None
    bonus_smoothed_monthly: RubleAmount | None
    monthly_average: RubleAmount | None
    current_level: RubleAmount | None
    current_passive_months: int
    warnings: tuple[str, ...]
    bonus_target_months: int = 12


@dataclass(frozen=True, slots=True)
class TotalIncomeResult:
    points: tuple[TotalIncomePoint, ...]
    calendar_year: TotalIncomeWindow
    rolling_12: TotalIncomeWindow
    all: TotalIncomeWindow
    configured_start_month: str | None


_MONTH_ADJECTIVES = (
    "январской",
    "февральской",
    "мартовской",
    "апрельской",
    "майской",
    "июньской",
    "июльской",
    "августовской",
    "сентябрьской",
    "октябрьской",
    "ноябрьской",
    "декабрьской",
)


def _rounded(kopecks: Decimal) -> RubleAmount:
    return RubleAmount(int(kopecks.to_integral_value(rounding=FINANCIAL_ROUNDING)))


def _average(total: RubleAmount | None, count: int) -> Decimal | None:
    return Decimal(total.kopecks) / Decimal(count) if total is not None and count else None


def _window(
    points: tuple[TotalIncomePoint, ...],
    *,
    from_month: str | None,
    to_month: str | None,
    latest_points: tuple[TotalIncomePoint, ...],
    estimate_basis: TotalIncomePoint | None,
    history_start_month: tuple[int, int] | None,
    span_months: int,
) -> TotalIncomeWindow:
    count = len(points)
    # A yearly bonus is spread over twelve months; a longer window spreads all
    # of its bonuses over its whole calendar span, never over twelve.
    bonus_target = max(12, span_months)
    passive = tuple(p.passive_actual for p in points if p.passive_actual is not None)
    salary_sum = RubleAmount(sum(p.salary_net.kopecks for p in points)) if count else None
    bonus_sum = RubleAmount(sum(p.bonus_net.kopecks for p in points)) if count else None
    passive_sum = RubleAmount(sum(p.kopecks for p in passive)) if passive else None
    salary_avg = _average(salary_sum, count)
    passive_avg = _average(passive_sum, len(passive))
    bonus_avg = _average(bonus_sum, bonus_target)
    # Add unrounded component ratios, then round the resulting money once.
    average = (
        _rounded(salary_avg + passive_avg + bonus_avg)
        if salary_avg is not None and passive_avg is not None and bonus_avg is not None
        else None
    )
    recent = tuple(p.passive_actual for p in latest_points[-3:] if p.passive_actual is not None)
    recent_avg = Decimal(sum(p.kopecks for p in recent)) / Decimal(len(recent)) if recent else None
    current_level = (
        _rounded(Decimal(latest_points[-1].salary_net.kopecks) + recent_avg + bonus_avg)
        if latest_points and recent_avg is not None and bonus_avg is not None
        else None
    )
    estimate_months = sum(p.salary_is_estimate for p in points)
    warnings: list[str] = []
    if estimate_months and estimate_basis is not None:
        warnings.append(
            f"Зарплата за {estimate_months} мес оценена по "
            f"{_MONTH_ADJECTIVES[estimate_basis.month - 1]} "
            f"({estimate_basis.month:02d}.{estimate_basis.year:04d})"
        )
    if history_start_month is not None and any(
        (p.year, p.month) < history_start_month for p in points
    ):
        year, month = history_start_month
        warnings.append(f"Пассивка учитывается с {month:02d}.{year:04d}")
    if not count:
        warnings.append("Нет закрытых месяцев для расчёта общего дохода")
    elif count < bonus_target and bonus_sum is not None and bonus_sum.kopecks != 0:
        # Without any paid bonus the note only confuses; coverage counts stay explicit.
        warnings.append(
            f"Премия учтена за {count} мес из {bonus_target}; "
            f"сумма распределена на {bonus_target} месяцев"
        )
    if count and not passive:
        warnings.append("Нет доступных месяцев пассивного дохода для расчёта среднего")
    return TotalIncomeWindow(
        from_month=from_month,
        to_month=to_month,
        months_observed=count,
        months_used=tuple(p.key for p in points),
        salary_months=count,
        passive_months=len(passive),
        bonus_months=count,
        estimate_months=estimate_months,
        salary_sum=salary_sum,
        passive_sum=passive_sum,
        bonus_sum=bonus_sum,
        other_sum=RubleAmount(sum(p.other_net.kopecks for p in points)) if count else None,
        salary_monthly_average=_rounded(salary_avg) if salary_avg is not None else None,
        passive_monthly_average=_rounded(passive_avg) if passive_avg is not None else None,
        bonus_smoothed_monthly=_rounded(bonus_avg) if bonus_avg is not None else None,
        monthly_average=average,
        current_level=current_level,
        current_passive_months=len(recent),
        warnings=tuple(warnings),
        bonus_target_months=bonus_target,
    )


def calculate_total_income(
    months: tuple[TotalIncomePoint, ...],
    *,
    history_start_month: tuple[int, int] | None = None,
) -> TotalIncomeResult:
    """Estimate only leading zero salaries; never invent calendar observations.

    A known passive zero participates; None does not. The global inclusive
    history boundary applies before windowing. All three windows end at the
    latest CLOSED observation supplied by the service. Current level uses the
    last three CLOSED observations, including their availability gaps, and the
    selected window's bonus / 12. Missing components make the headline unknown.
    """
    ordered = tuple(sorted(months, key=lambda p: (p.year, p.month)))
    if len({(p.year, p.month) for p in ordered}) != len(ordered):
        raise ValueError("duplicate reporting month in total income")
    for point in ordered:
        if not 1 <= point.month <= 12 or point.year < 1:
            raise ValueError("invalid reporting month in total income")
    basis = next((p for p in ordered if p.salary_net.kopecks != 0), None)
    points = tuple(
        replace(
            p,
            salary_net=(basis.salary_net if estimated and basis is not None else p.salary_net),
            salary_is_estimate=estimated,
            passive_actual=(
                None
                if history_start_month is not None and (p.year, p.month) < history_start_month
                else p.passive_actual
            ),
        )
        for p in ordered
        for estimated in (
            basis is not None
            and p.salary_net.kopecks == 0
            and (p.year, p.month) < (basis.year, basis.month),
        )
    )
    latest = points[-1] if points else None
    rolling_start = latest.year * 12 + latest.month - 12 if latest else 0
    rolling_from = f"{rolling_start // 12:04d}-{rolling_start % 12 + 1:02d}" if latest else None
    end = latest.key if latest else None

    def window(
        selected: tuple[TotalIncomePoint, ...], start: str | None, span: int
    ) -> TotalIncomeWindow:
        return _window(
            selected,
            from_month=start,
            to_month=end,
            latest_points=points,
            estimate_basis=basis,
            history_start_month=history_start_month,
            span_months=span,
        )

    all_span = (
        (latest.year * 12 + latest.month) - (points[0].year * 12 + points[0].month) + 1
        if latest
        else 0
    )
    return TotalIncomeResult(
        points=points,
        calendar_year=window(
            tuple(p for p in points if latest is not None and p.year == latest.year),
            f"{latest.year:04d}-01" if latest else None,
            latest.month if latest else 0,
        ),
        rolling_12=window(
            tuple(p for p in points if p.key >= rolling_from) if rolling_from else (),
            rolling_from,
            12,
        ),
        all=window(points, points[0].key if points else None, all_span),
        configured_start_month=(
            f"{history_start_month[0]:04d}-{history_start_month[1]:02d}"
            if history_start_month is not None
            else None
        ),
    )
