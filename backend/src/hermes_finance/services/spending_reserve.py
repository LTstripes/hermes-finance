"""Owner-selected reserve composition and exact mandatory-payment calendar."""

from __future__ import annotations

from calendar import monthrange
from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.persistence import (
    Account,
    CashBalance,
    DepositSnapshot,
    ReportingMonth,
    SpendingCategory,
    SpendingReservePlan,
    SpendingUpload,
)
from hermes_finance.services import spending_diary as diary
from hermes_finance.services import spending_insights as insights


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Source(StrictModel):
    key: str = Field(pattern=r"^(cash|savings):(account|row):[1-9][0-9]*$", max_length=64)
    portion: str | None = Field(default=None, pattern=r"^\d{1,14}(\.\d{1,2})?$")


class Category(StrictModel):
    id: int = Field(gt=0)
    estimate: str | None = Field(default=None, pattern=r"^\d{1,14}(\.\d{1,2})?$")


class Plan(StrictModel):
    start: date
    end: date
    sources: list[Source] = Field(max_length=100)
    categories: list[Category] = Field(max_length=100)
    months: list[str] = Field(max_length=12)

    @model_validator(mode="after")
    def validate_choices(self):
        if (
            not (date(1900, 1, 1) <= self.start <= self.end <= date(9998, 12, 31))
            or (self.end - self.start).days > 366 * 10
        ):
            raise ValueError("Выберите период до десяти лет")
        for keys in ([s.key for s in self.sources], [c.id for c in self.categories], self.months):
            if len(keys) != len(set(keys)):
                raise ValueError("Источник, категория или месяц указаны дважды")
        for month in self.months:
            first = date.fromisoformat(month + "-01")
            if (
                month != first.strftime("%Y-%m")
                or first.replace(day=monthrange(first.year, first.month)[1]) >= self.start
            ):
                raise ValueError(
                    "Среднее рассчитывается по завершившимся месяцам перед началом цели"
                )
        return self


def move_month(day, count):
    index = (day.year - 1) * 12 + day.month - 1 + count
    year, month = divmod(index, 12)
    return date(year + 1, month + 1, min(day.day, monthrange(year + 1, month + 1)[1]))


def rounded(value):
    return int(Decimal(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def money(value):
    return insights.money(rounded(value)) if value is not None else None


def stored_plan(session):
    row = session.get(SpendingReservePlan, 1)
    if row:
        return row.revision, Plan.model_validate_json(row.settings_json)
    first = move_month(date.today().replace(day=1), 1)
    return 0, Plan(
        start=first,
        end=move_month(first, 6) - timedelta(days=1),
        sources=[],
        categories=[],
        months=[],
    )


def save_plan(session, expected_revision, plan):
    revision, current = stored_plan(session)
    if revision and current == plan:
        return
    if expected_revision != revision:
        raise diary.PreviewChanged("План подушки изменился. Перечитайте сохранённый план.")
    row = session.get(SpendingReservePlan, 1)
    if row is None:
        row = SpendingReservePlan(id=1)
        session.add(row)
    row.revision = revision + 1
    row.settings_json = plan.model_dump_json()
    session.flush()


def source_catalog(session, as_of):
    # Only a closed snapshot is evidence for a balance. Do not carry old absent rows.
    report = session.scalar(
        select(ReportingMonth)
        .where(ReportingMonth.status == "closed", ReportingMonth.snapshot_date <= as_of)
        .order_by(
            ReportingMonth.snapshot_date.desc(),
            ReportingMonth.year.desc(),
            ReportingMonth.month.desc(),
        )
        .limit(1)
    )
    if not report:
        return [], None
    catalog = {}
    for model, kind in [(CashBalance, "cash"), (DepositSnapshot, "savings")]:
        query = (
            select(model, Account.name)
            .outerjoin(Account, model.account_id == Account.id)
            .where(model.reporting_month_id == report.id)
        )
        if kind == "savings":
            query = query.where(DepositSnapshot.deposit_type == "savings")
        for row, account in session.execute(query):
            key = f"{kind}:account:{row.account_id}" if row.account_id else f"{kind}:row:{row.id}"
            detail = catalog.setdefault(
                key,
                dict(
                    key=key,
                    label=account or row.name,
                    kind=kind,
                    account_id=row.account_id,
                    amount_kopecks=0,
                ),
            )
            if kind == "cash" and row.currency != "RUB":
                detail["amount_kopecks"] = None
            elif detail["amount_kopecks"] is not None:
                detail["amount_kopecks"] += (
                    row.amount_kopecks if kind == "cash" else row.balance_kopecks
                )
    return list(catalog.values()), report.snapshot_date


def reserve_total(selections, catalog, gaps):
    by_key = {s["key"]: s for s in catalog}
    seen_accounts = set()
    total = 0
    if not selections:
        gaps.append("Выберите источники резерва.")
        return None
    for choice in selections:
        row = by_key.get(choice.key)
        if row is None or row["amount_kopecks"] is None:
            gaps.append("Для выбранного источника нет подтверждённого рублёвого остатка.")
            return None
        account = row["account_id"]
        if account is not None and account in seen_accounts:
            gaps.append(
                "На одном счёте выбраны деньги и накопительный остаток. Уточните источник, чтобы исключить повторный учёт."
            )
            return None
        seen_accounts.add(account)
        part = (
            rounded(Decimal(choice.portion) * 100)
            if choice.portion is not None
            else row["amount_kopecks"]
        )
        if part > row["amount_kopecks"]:
            gaps.append(f"Выбранная часть превышает остаток: {row['label']}.")
            return None
        total += part
    return total


def historical_amounts(session, plan, rules):
    totals = defaultdict(Decimal)
    if not plan.months:
        return None
    excluded = {
        (r["month"], r["source"], r["operation_id"])
        for r in rules
        if r["repeat"] or r.get("was_recurring") or r["mandatory_override"] is False
    }
    if any(
        r["needs_review"]
        and r["month"] in plan.months
        and (r["repeat"] or r.get("was_recurring") or r["mandatory_override"] is False)
        for r in rules
    ):
        return None
    signature = None
    for month in plan.months:
        base = diary.read_month_base(session, month)
        accounts = set(
            session.scalars(
                select(SpendingUpload.account).where(
                    SpendingUpload.month == month, SpendingUpload.source == "alfa_csv"
                )
            )
        )
        current = (frozenset(accounts), base["has_manual"])
        if (
            not base["coverage"]["full"]
            or base["unresolved"]
            or (signature is not None and signature != current)
        ):
            return None
        signature = current
        for item in insights.operations(session, base, limit=None)["items"]:
            if (month, item["source"], item["id"]) not in excluded:
                totals[item["category_id"]] += Decimal(item["amount"]["amount"]) * 100
    return {c.id: totals[c.id] / len(plan.months) for c in plan.categories}


def next_dates(anchor, period, first, last):
    n = max(0, ((first.year - anchor.year) * 12 + first.month - anchor.month) // period)
    while True:
        offset = n * period
        if (anchor.year - 1) * 12 + anchor.month - 1 + offset >= 9999 * 12:
            return
        due = move_month(anchor, offset)
        if due > last:
            return
        if due >= first:
            yield due
        n += 1


def calculate(plan, rules, categories, historical, reserve, gaps):
    periods = []
    first = plan.start.replace(day=1)
    variable = Decimal(0)
    basis = []
    known_monthly = True
    for c in plan.categories:
        amount = (
            Decimal(c.estimate) * 100 if c.estimate is not None else (historical or {}).get(c.id)
        )
        if c.id not in categories or amount is None or amount < 0:
            known_monthly = False
            gaps.append(
                f"Нужна оценка категории «{categories.get(c.id, 'удалена')}» или полные сопоставимые месяцы."
            )
        else:
            variable += amount
        basis.append(
            dict(
                id=c.id,
                name=categories.get(c.id, "Удалённая категория"),
                method="estimate" if c.estimate is not None else "history",
                amount=money(amount)
                if amount is not None and amount >= 0 and c.id in categories
                else None,
            )
        )
    variable_known = known_monthly
    while first <= plan.end:
        last = first.replace(day=monthrange(first.year, first.month)[1])
        count = (min(last, plan.end) - max(first, plan.start)).days + 1
        periods.append(
            dict(month=first.strftime("%Y-%m"), variable=variable * count / last.day, payments=[])
        )
        first = move_month(first, 1)
    by_month = {p["month"]: p for p in periods}
    monthly = variable
    cash_known = known_monthly
    active = []
    for r in rules:
        if not r["repeat"] or (
            not r["mandatory"] and not (r["needs_review"] and r["mandatory_override"] is not False)
        ):
            continue
        active.append(r)
        amount, period, due = r["amount_kopecks"], r["period_months"], r["next_due"]
        if r["needs_review"] or not period or amount is None:
            known_monthly = cash_known = False
            gaps.append(f"Проверьте правило «{r['title']}».")
            continue
        monthly += Decimal(amount) / period
        if due is None:
            cash_known = False
            gaps.append(f"Неизвестна следующая дата платежа «{r['title']}».")
            continue
        for day in next_dates(due, period, plan.start, plan.end):
            by_month[day.strftime("%Y-%m")]["payments"].append(
                dict(rule_id=r["id"], date=day, title=r["title"], amount=money(amount))
            )
    has_budget = bool(plan.categories or active)
    if not has_budget:
        gaps.append("Выберите обязательные категории или отметьте повторяющийся платёж.")
    calendar = []
    goal = 0
    for item in periods:
        amount = rounded(item["variable"]) + sum(
            rounded(Decimal(p["amount"]["amount"]) * 100) for p in item["payments"]
        )
        goal += amount
        calendar.append(
            dict(
                month=item["month"],
                variable=money(item["variable"]) if variable_known and has_budget else None,
                payments=item["payments"],
                total=money(amount) if has_budget and cash_known else None,
            )
        )
    goal = goal if has_budget and cash_known else None
    monthly = monthly if has_budget and known_monthly else None
    months = (
        (Decimal(reserve) / monthly).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        if reserve is not None and monthly is not None and monthly > 0
        else None
    )
    return dict(
        reserve=money(reserve),
        monthly=money(monthly),
        coverage_months=str(months) if months is not None else None,
        target=money(goal),
        difference=money(reserve - goal) if goal is not None and reserve is not None else None,
        calendar=calendar,
        basis=basis,
        rules=[
            dict(
                id=r["id"],
                title=r["title"],
                amount=money(r["amount_kopecks"]),
                period_months=r["period_months"],
                next_due=r["next_due"],
                needs_review=r["needs_review"],
            )
            for r in active
        ],
    )


def read(session: Session):
    from hermes_finance.services.spending_payment_rules import payment_rules_for_budget

    revision, plan = stored_plan(session)
    gaps = []
    catalog, observed = source_catalog(session, min(date.today(), plan.start))
    reserve = reserve_total(plan.sources, catalog, gaps)
    categories = dict(
        session.execute(
            select(SpendingCategory.id, SpendingCategory.name).order_by(SpendingCategory.name)
        ).all()
    )
    rules = payment_rules_for_budget(session)
    historical = (
        historical_amounts(session, plan, rules)
        if any(c.estimate is None for c in plan.categories)
        else None
    )
    metrics = calculate(plan, rules, categories, historical, reserve, gaps)
    return dict(
        revision=revision,
        plan=plan.model_dump(mode="json"),
        **metrics,
        gaps=list(dict.fromkeys(gaps)),
        snapshot_date=observed,
        sources=[
            dict(key=s["key"], label=s["label"], kind=s["kind"], balance=money(s["amount_kopecks"]))
            for s in catalog
        ],
        categories=[dict(id=i, name=n) for i, n in categories.items()],
    )
