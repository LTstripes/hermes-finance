"""Deterministic hypothetical capital plan; integer kopecks, no persistence."""

from calendar import monthrange
from datetime import date
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal, localcontext


def validate_plan_parameters(*, annual_rate: Decimal, contribution: int | None) -> None:
    if not annual_rate.is_finite() or not 0 <= annual_rate <= 100:
        raise ValueError("Годовая доходность должна быть от 0 до 100%")
    if contribution is not None and not 0 <= contribution <= 10**17:
        raise ValueError("Взнос должен быть от 0 до 1 000 000 000 000 000 рублей")


def contribution_date(first: date, offset: int) -> date:
    month = first.year * 12 + first.month - 1 + offset
    year, index = divmod(month, 12)
    return date(year, index + 1, min(first.day, monthrange(year, index + 1)[1]))


def calculate_goal_plan(
    *,
    capital: int,
    target: int,
    snapshot: date,
    contribution: int | None,
    first: date | None = None,
    annual_rate: Decimal = Decimal(0),
    deadline: date | None = None,
) -> dict:
    first = first or contribution_date(snapshot.replace(day=1), 1)
    if first <= snapshot:
        raise ValueError("Первый взнос должен быть после даты снимка")
    validate_plan_parameters(annual_rate=annual_rate, contribution=contribution)
    with localcontext() as ctx:
        ctx.prec = 60
        factor = (1 + annual_rate / 100) ** (Decimal(1) / 12)

        def grow(value: int) -> int:
            return int((Decimal(value) * factor).quantize(Decimal(1), rounding=ROUND_HALF_UP))

        def final(payment: int, count: int) -> int:
            value = capital
            for _ in range(count):
                value = grow(value) + payment
            return value

        horizon = contribution_date(snapshot, 1200)
        dates = []
        for i in range(1200):
            if first.year * 12 + first.month - 1 + i > horizon.year * 12 + horizon.month - 1:
                break
            scheduled = contribution_date(first, i)
            if scheduled > horizon:
                break
            dates.append(scheduled)
        count = sum(d <= deadline for d in dates) if deadline else None
        required = last = difference = None
        deadline_status = (
            "absent" if deadline is None else "passed" if deadline <= snapshot else "available"
        )
        if deadline and deadline > horizon:
            deadline_status = "outside_horizon"
        elif count and deadline_status == "available":
            # Annuity seed; binary search corrects for monthly kopeck rounding.
            seed = (
                (Decimal(target) - Decimal(capital) * factor**count) / count
                if factor == 1
                else (Decimal(target) - Decimal(capital) * factor**count)
                * (factor - 1)
                / (factor**count - 1)
            )
            high = max(0, int(seed.to_integral_value(rounding=ROUND_CEILING)))
            while final(high, count) < target:
                high = max(1, high * 2)
            low = 0
            while low < high:
                mid = (low + high) // 2
                if final(mid, count) >= target:
                    high = mid
                else:
                    low = mid + 1
            required = low
            last = max(0, target - grow(final(required, count - 1)))
            difference = None if contribution is None else contribution - required
        elif deadline_status == "available":
            deadline_status = "no_contributions"
        points = []
        achieved = snapshot if capital >= target else None
        value = capital
        if achieved is None and contribution is not None:
            for d in dates:
                value = grow(value) + contribution
                points.append({"date": d.isoformat(), "capital": money(value)})
                if value >= target:
                    achieved = d
                    break
        return {
            "method_version": "goal_plan_v1",
            "status": "achieved"
            if capital >= target
            else "contribution_missing"
            if contribution is None
            else "projected"
            if achieved
            else "not_reached",
            "as_of_date": snapshot.isoformat(),
            "base_capital": money(capital),
            "first_contribution_date": first.isoformat(),
            "monthly_contribution": optional_money(contribution),
            "annual_rate_pct": str(annual_rate),
            "achievement_date": achieved.isoformat() if achieved else None,
            "deadline_status": deadline_status,
            "remaining_contributions": count,
            "required_contribution": optional_money(required),
            "last_required_contribution": optional_money(last),
            "contribution_difference": optional_money(difference),
            "trajectory": points,
        }


def money(value: int) -> str:
    return format(Decimal(value) / 100, ".2f")


def optional_money(value: int | None) -> str | None:
    return None if value is None else money(value)
