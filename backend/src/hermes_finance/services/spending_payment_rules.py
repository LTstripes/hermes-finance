"""Owner annotations on effective diary purchases. No month-fact writes."""

from __future__ import annotations

from collections import Counter, defaultdict
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.persistence import (
    SpendingOperation,
    SpendingPaymentOccurrence,
    SpendingPaymentRule,
)
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
    rules = list(session.scalars(query))
    occurrences = (
        list(
            session.scalars(
                select(SpendingPaymentOccurrence)
                .where(SpendingPaymentOccurrence.rule_id.in_([rule.id for rule in rules]))
                .order_by(SpendingPaymentOccurrence.id)
            )
        )
        if rules
        else []
    )
    targets = defaultdict(set)
    for item in [*rules, *occurrences]:
        if _target(item)[1] is not None:
            targets[item.month].add(_target(item))
    facts = {key: _purchases(session, key, items) for key, items in targets.items()}
    linked = defaultdict(list)
    for occurrence in occurrences:
        purchase = facts.get(occurrence.month, {}).get(_target(occurrence))
        linked[occurrence.rule_id].append(
            dict(
                id=occurrence.id,
                month=occurrence.month,
                source=occurrence.source,
                title=occurrence.title,
                operation_id=_target(occurrence)[1],
                decision=occurrence.decision,
                needs_review=purchase is None
                or _occurrence_evidence(purchase) != occurrence.evidence,
            )
        )
    return [
        {
            **_project(rule, facts.get(rule.month, {}).get(_target(rule))),
            "occurrences": linked[rule.id],
        }
        for rule in rules
    ]


def _occurrence_evidence(purchase):
    # Classification can change without invalidating the owner's purchase selection.
    return digest(
        [
            purchase["source"],
            purchase["id"],
            purchase["title"],
            purchase["amount_kopecks"],
            purchase["date"],
        ]
    )


def _decisions(session, source, operation_id):
    key = (
        SpendingPaymentOccurrence.entry_id
        if source == "month_entries"
        else SpendingPaymentOccurrence.operation_id
    )
    return list(
        session.scalars(
            select(SpendingPaymentOccurrence)
            .where(key == operation_id)
            .order_by(SpendingPaymentOccurrence.id)
        )
    )


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
        [
            month,
            source,
            operation_id,
            purchase,
            (rule.id, rule.version) if rule else None,
            [
                (d.id, d.rule_id, d.decision, d.evidence)
                for d in _decisions(session, source, operation_id)
            ],
        ]
    )
    return purchase, rule, identity


def card(session, month, source, operation_id):
    purchase, rule, identity = _get_target(session, month, source, operation_id)
    all_rules = payment_rules_for_budget(session)
    owned = next((item for item in all_rules if rule and item["id"] == rule.id), None)
    schedules = []
    decisions = []
    for item in all_rules:
        for occurrence in item["occurrences"]:
            if (occurrence["month"], occurrence["source"], occurrence["operation_id"]) == (
                month,
                source,
                operation_id,
            ):
                decisions.append(
                    {
                        **occurrence,
                        "rule_id": item["id"],
                        "rule_title": item["title"],
                        "rule_version": item["version"],
                    }
                )
        if (
            not item["needs_review"]
            and item["was_recurring"]
            and item["month"] <= month
            and (not rule or rule.id != item["id"])
        ):
            schedules.append(
                {
                    k: item[k]
                    for k in ("id", "title", "month", "version", "repeat", "amount", "next_due")
                }
            )
    return dict(
        token=identity,
        title=purchase["title"],
        fact_amount=_money(purchase["amount_kopecks"]),
        category_mandatory=purchase["expense_type"] == "mandatory",
        rule=owned,
        schedules=schedules,
        decisions=decisions,
    )


def _raw_evidence(row):
    return _occurrence_evidence({**row, "title": row["description"], "date": row["operation_date"]})


def transfer_duplicate_decisions(session, month):
    pairs = session.execute(
        select(SpendingPaymentOccurrence, SpendingOperation.duplicate_of_id)
        .join(SpendingOperation, SpendingPaymentOccurrence.operation_id == SpendingOperation.id)
        .where(
            SpendingPaymentOccurrence.month == month,
            SpendingOperation.decision == "duplicate",
            SpendingOperation.duplicate_of_id.is_not(None),
        )
    ).all()
    if not pairs:
        return
    result = diary.read_month_base(session, month)
    rows = {row["id"]: row for row in result["operations"]}
    target_ids = {target for _, target in pairs}
    protected = set(
        session.scalars(
            select(SpendingPaymentRule.operation_id).where(
                SpendingPaymentRule.operation_id.in_(target_ids),
                SpendingPaymentRule.was_recurring.is_(True),
            )
        )
    )
    attached = set()
    for row in session.scalars(
        select(SpendingPaymentOccurrence).where(
            SpendingPaymentOccurrence.operation_id.in_(target_ids)
        )
    ):
        attached.add((row.rule_id, row.operation_id))
        if row.decision == "payment":
            protected.add(row.operation_id)
    pair_counts = Counter((link.rule_id, target_id) for link, target_id in pairs)
    payment_counts = Counter(target_id for link, target_id in pairs if link.decision == "payment")
    for link, target_id in pairs:
        source = rows[link.operation_id]
        target = rows.get(target_id)
        if (
            source["effective_reason"] is not None
            or not target
            or not target["included"]
            or target["source"] != "alfa_csv"
            or (link.rule_id, target_id) in attached
            or pair_counts[link.rule_id, target_id] != 1
            or (
                link.decision == "payment"
                and (target_id in protected or payment_counts[target_id] != 1)
            )
        ):
            continue
        if _raw_evidence(source) != link.evidence:
            continue
        link.operation_id = target_id
        link.source = "alfa"
        link.title = target["description"]
        link.evidence = _raw_evidence(target)
        attached.add((link.rule_id, target_id))
        if link.decision == "payment":
            protected.add(target_id)
        session.get(SpendingPaymentRule, link.rule_id).version += 1
    session.flush()


def choose_occurrence(session, month, source, operation_id, token, rule_id, version, decision):
    purchase, own, identity = _get_target(session, month, source, operation_id)
    schedule = session.get(SpendingPaymentRule, rule_id)
    if (
        token != identity
        or not schedule
        or schedule.archived
        or not schedule.was_recurring
        or schedule.version != version
        or schedule.month > month
        or schedule is own
        or _target(schedule) not in _purchases(session, schedule.month, {_target(schedule)})
    ):
        raise diary.PreviewChanged("Покупка или график изменились. Откройте карточку заново.")
    existing = _decisions(session, source, operation_id)
    if decision == "payment" and (
        (own and own.was_recurring)
        or any(o.decision == "payment" and o.rule_id != rule_id for o in existing)
    ):
        raise ValueError("У покупки уже есть другой график")
    occurrence = next((row for row in existing if row.rule_id == rule_id), None)
    if not occurrence:
        occurrence = SpendingPaymentOccurrence(
            rule_id=rule_id,
            source=source,
            month=month,
            entry_id=operation_id if source == "month_entries" else None,
            operation_id=operation_id if source != "month_entries" else None,
        )
        session.add(occurrence)
    occurrence.decision = decision
    occurrence.title = purchase["title"]
    occurrence.evidence = _occurrence_evidence(purchase)
    schedule.version += 1
    session.flush()
    return card(session, month, source, operation_id)


def undo_occurrence(session, month, source, operation_id, token, occurrence_id, version):
    _, own, identity = _get_target(session, month, source, operation_id)
    occurrence = session.get(SpendingPaymentOccurrence, occurrence_id)
    if occurrence is None:
        raise diary.PreviewChanged("Решение уже изменилось")
    schedule = session.get(SpendingPaymentRule, occurrence.rule_id)
    anchor = own is not None and own.id == schedule.id
    target = occurrence.month == month and _target(occurrence) == (source, operation_id)
    if token != identity or version != schedule.version or not (anchor or target):
        raise diary.PreviewChanged("Покупка или график изменились. Обновите данные.")
    session.delete(occurrence)
    schedule.version += 1
    session.flush()
    return card(session, month, source, operation_id)


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
    if values["repeat"] and any(
        d.decision == "payment" for d in _decisions(session, source, operation_id)
    ):
        raise ValueError("Покупка уже отмечена как оплата существующего графика")
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
        or (
            rule.was_recurring
            and any(d.decision == "payment" for d in _decisions(session, source, operation_id))
        )
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
