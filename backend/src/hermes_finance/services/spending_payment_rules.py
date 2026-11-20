"""Owner annotations on effective diary purchases. No month-fact writes."""

from __future__ import annotations

from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.persistence import SpendingPaymentRule
from hermes_finance.services import spending_diary as diary
from hermes_finance.services import spending_insights as insights
from hermes_finance.spending_files import digest, month_bounds


def _purchases(session, month, targets):
    month_bounds(month)
    result = diary.read_month_base(session, month)
    descriptions = {row["id"]: row["description"] for row in result["operations"]}
    return {
        (insights._source(item), item["id"]): {
            **item,
            "title": descriptions.get(item["id"], "")
            if item["source"] != "expense_entries"
            else item["category"],
            "category_id": insights._category_id(session, item["category"]),
        }
        for item in result["contributions"]
        if item["amount_kopecks"] > 0 and (insights._source(item), item["id"]) in targets
    }


def _target(rule):
    return (rule.source, rule.entry_id if rule.source == "month_entries" else rule.operation_id)


def _project(rule, purchase):
    mandatory = rule.mandatory_override
    if mandatory is None:
        mandatory = purchase["expense_type"] == "mandatory" if purchase else None
    return dict(
        id=rule.id,
        title=purchase["title"] if purchase else rule.title,
        month=rule.month,
        source=rule.source,
        operation_id=_target(rule)[1],
        category_id=purchase["category_id"] if purchase else None,
        note=rule.note,
        mandatory_override=rule.mandatory_override,
        mandatory=mandatory,
        repeat=rule.repeat,
        was_recurring=rule.was_recurring,
        archived=rule.archived,
        period_months=rule.period_months,
        next_due=rule.next_due,
        amount_kopecks=rule.amount_kopecks,
        amount=_money(rule.amount_kopecks),
        monthly_amount=_money(
            int(
                (Decimal(rule.amount_kopecks) / rule.period_months).quantize(
                    Decimal(1), rounding=ROUND_HALF_UP
                )
            )
        )
        if rule.repeat and rule.amount_kopecks is not None and rule.period_months
        else None,
        needs_review=purchase is None,
        version=rule.version,
    )


def _money(kopecks):
    return f"{Decimal(kopecks) / 100:.2f}" if kopecks is not None else None


def payment_rules_for_budget(
    session: Session, month: str | None = None, *, include_archived: bool = False
) -> list[dict]:
    query = select(SpendingPaymentRule).order_by(SpendingPaymentRule.id)
    if month is not None:
        month_bounds(month)
        query = query.where(SpendingPaymentRule.month == month)
    if not include_archived:
        query = query.where(SpendingPaymentRule.archived.is_(False))
    grouped = defaultdict(list)
    for rule in session.scalars(query):
        grouped[rule.month].append(rule)
    rows = []
    for key, rules in grouped.items():
        purchases = _purchases(session, key, {_target(rule) for rule in rules})
        rows.extend(_project(rule, purchases.get(_target(rule))) for rule in rules)
    return rows


def _get_target(session, month, source, operation_id):
    target = (source, operation_id)
    purchase = _purchases(session, month, {target}).get(target)
    if purchase is None:
        raise LookupError("Покупка больше не входит в расходы этого месяца")
    key = (
        SpendingPaymentRule.entry_id
        if source == "month_entries"
        else SpendingPaymentRule.operation_id
    )
    rule = session.scalar(select(SpendingPaymentRule).where(key == operation_id))
    # The receipt covers the actual transaction, amount, classification and rule revision.
    identity = digest(
        [month, source, operation_id, purchase, (rule.id, rule.version) if rule else None]
    )
    return purchase, rule, identity


def card(session, month, source, operation_id):
    purchase, rule, identity = _get_target(session, month, source, operation_id)
    return dict(
        token=identity,
        title=purchase["title"],
        fact_amount=_money(purchase["amount_kopecks"]),
        category_mandatory=purchase["expense_type"] == "mandatory",
        rule=_project(rule, purchase) if rule else None,
    )


def save(session, month, source, operation_id, values):
    purchase, rule, identity = _get_target(session, month, source, operation_id)
    if values["token"] != identity:
        raise diary.PreviewChanged("Покупка или правило изменились. Откройте карточку заново.")
    if rule is None:
        rule = SpendingPaymentRule(month=month, source=source, title=purchase["title"], version=0)
        if source == "month_entries":
            rule.entry_id = operation_id
        else:
            rule.operation_id = operation_id
        session.add(rule)
    rule.note = values["note"].strip()
    rule.mandatory_override = values["mandatory_override"]
    rule.repeat = values["repeat"]
    rule.was_recurring = bool(rule.was_recurring or rule.repeat)
    rule.period_months = values["period_months"]
    rule.next_due = values["next_due"]
    rule.amount_kopecks = (
        int(Decimal(values["amount"]) * 100) if values["amount"] is not None else None
    )
    if not rule.repeat and any(
        x is not None for x in (rule.period_months, rule.next_due, rule.amount_kopecks)
    ):
        raise ValueError("Для разовой покупки очистите параметры продления")
    if rule.next_due is not None and purchase["date"] and rule.next_due <= purchase["date"]:
        raise ValueError("Продление должно быть позже даты покупки")
    rule.version += 1
    session.flush()
    return card(session, month, source, operation_id)


def archive_detached(session, month, rule_id, version):
    rule = session.get(SpendingPaymentRule, rule_id)
    if (
        not rule
        or rule.month != month
        or rule.version != version
        or rule.archived
        or _target(rule) in _purchases(session, month, {_target(rule)})
    ):
        raise diary.PreviewChanged("Пометка изменилась. Обновите список.")
    rule.entry_id = rule.operation_id = None
    rule.archived = True
    rule.version += 1
    session.flush()
    return _project(rule, None)


def reattach(session, month, source, operation_id, token, rule_id, version):
    purchase, existing, identity = _get_target(session, month, source, operation_id)
    rule = session.get(SpendingPaymentRule, rule_id)
    if (
        not rule
        or rule.month != month
        or rule.version != version
        or existing is not None
        or token != identity
        or _target(rule) in _purchases(session, month, {_target(rule)})
    ):
        raise diary.PreviewChanged("Привязка изменилась. Обновите сведения о покупке.")
    rule.entry_id = operation_id if source == "month_entries" else None
    rule.operation_id = operation_id if source != "month_entries" else None
    rule.source = source
    rule.archived = False
    rule.title = purchase["title"]
    rule.version += 1
    session.flush()
    return card(session, month, source, operation_id)
