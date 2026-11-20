"""Independent diary commands and a single authoritative month-spending read model."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.persistence import (
    ExpenseEntry,
    ReportingMonth,
    SpendingCategory,
    SpendingExpenseLink,
    SpendingLinkOperation,
    SpendingOperation,
    SpendingPaymentRule,
    SpendingReview,
    SpendingRule,
    SpendingUpload,
)
from hermes_finance.spending_files import (
    UNCATEGORIZED,
    VERSION,
    FileProblem,
    alfa_operations,
    digest,
    manual_operations,
    month_bounds,
    normalize,
    statement_period,
)

# Models are deliberately separate from reporting-month children and guards.
TABLES = (
    SpendingCategory,
    SpendingRule,
    SpendingUpload,
    SpendingOperation,
    SpendingPaymentRule,
    SpendingExpenseLink,
    SpendingLinkOperation,
    SpendingReview,
    ExpenseEntry,
    ReportingMonth,
)
ROW_FIELDS = (
    "operation_date transaction_date amount_kopecks direction currency status category description "
    "account card payment kind reason merchant_key fingerprint ordinal raw_json"
).split()


class PreviewChanged(ValueError):
    pass


def _objects(session: Session, model: type) -> list:
    return list(session.scalars(select(model).order_by(*model.__table__.primary_key.columns)))


def _state_token(session: Session) -> str:
    return digest(
        [
            (
                model.__tablename__,
                sorted(
                    [
                        dict((c.name, getattr(obj, c.name)) for c in model.__table__.columns)
                        for obj in _objects(session, model)
                    ],
                    key=lambda row: digest(row),
                ),
            )
            for model in TABLES
        ]
        + [session.info.get("source_intake_epoch")]
    )


def _row(operation: SpendingOperation) -> dict:
    result = {field: getattr(operation, field) for field in ROW_FIELDS}
    result.update(
        id=operation.id,
        source=operation.source,
        month=operation.month,
        decision=operation.decision,
        decision_category_id=operation.decision_category_id,
        duplicate_of_id=operation.duplicate_of_id,
        needs_review=operation.needs_review,
    )
    return result


def _month_rows(session: Session, month: str) -> list[dict]:
    return [
        _row(o)
        for o in session.scalars(
            select(SpendingOperation)
            .where(SpendingOperation.month == month)
            .order_by(SpendingOperation.id)
        )
    ]


def _categories(session: Session) -> dict[int, SpendingCategory]:
    return {c.id: c for c in _objects(session, SpendingCategory)}


def _category(session: Session, name: str) -> SpendingCategory:
    name = name.strip() or UNCATEGORIZED
    if len(name) > 128:
        raise ValueError("Название категории длиннее 128 символов")
    key = normalize(name)
    category = next(
        (
            c
            for c in _objects(session, SpendingCategory)
            if c.name_key == key or normalize(c.name) == key
        ),
        None,
    )
    if category is None:
        mapping = session.scalar(
            select(SpendingRule).where(
                SpendingRule.scope == "bank_category", SpendingRule.key == key
            )
        )
        if mapping and mapping.category_id:
            return session.get(SpendingCategory, mapping.category_id)
        category = SpendingCategory(name=name, name_key=key, expense_type="other")
        session.add(category)
        session.flush()
    return category


def _preview_rules(session: Session, rows: list[dict], choices: list[dict]) -> dict:
    categories = _categories(session)
    by_name = {
        key: category
        for category in categories.values()
        for key in {category.name_key, normalize(category.name)}
    }
    result = {}
    for choice in choices:
        if not choice.get("remember"):
            continue
        row = next((row for row in rows if _identity(row) == _identity(choice)), None)
        if (
            row is None
            or row["source"] != "alfa_csv"
            or choice["action"] not in {"expense", "refund", "not_spending"}
        ):
            raise ValueError("Это решение не может стать правилом продавца")
        category = by_name.get(normalize(choice.get("category") or ""))
        result["merchant", row["merchant_key"]] = SimpleNamespace(
            action=choice["action"],
            category_id=category.id if category else None,
            category_name=choice.get("category"),
        )
    return result


def _effective(
    session: Session, rows: list[dict], rule_overrides: dict | None = None
) -> list[dict]:
    categories = _categories(session)
    by_name = {key: c for c in categories.values() for key in {c.name_key, normalize(c.name)}}
    rules = {(r.scope, r.key): r for r in _objects(session, SpendingRule)}
    rules.update(rule_overrides or {})
    bank_candidates = (
        _effective(session, [r for r in rows if r["source"] == "alfa_csv"], rule_overrides)
        if any(r["source"] == "manual_md" for r in rows)
        else []
    )
    result = []
    for original in rows:
        row = original.copy()
        row["bank_category"] = original["category"] if original["source"] == "alfa_csv" else None
        category = by_name.get(normalize(row["category"]))
        action, category_id = row.get("decision"), row.get("decision_category_id")
        rule = rules.get(("merchant", row["merchant_key"]))
        override_name = None
        mapping = rules.get(("bank_category", normalize(row["category"])))
        if (
            not action
            and rule
            and row["source"] == "alfa_csv"
            and (
                rule.action == "not_spending"
                or rule.action == "expense"
                and row["amount_kopecks"] > 0
                or rule.action == "refund"
                and row["amount_kopecks"] < 0
            )
            and row["kind"] not in {"transfer", "repayment", "interest"}
        ):
            action, category_id = rule.action, rule.category_id
            override_name = getattr(rule, "category_name", None)
        elif not action and mapping:
            category_id = mapping.category_id
        if category_id:
            category = categories.get(category_id)
        row["category"] = category.name if category else row["category"]
        if override_name:
            row["category"] = override_name
        if row.get("choice_category"):
            row["category"] = row["choice_category"]
        row["expense_type"] = category.expense_type if category else "other"
        row["category_id"] = category.id if category else None
        row["included"] = (
            row["kind"] == "purchase" or row["source"] == "manual_md" and row["kind"] == "refund"
        )
        row["effective_reason"] = row["reason"]
        row["effective_action"] = action
        if action in {"expense", "refund", "separate"}:
            row["included"] = True
            row["effective_reason"] = None
        elif action in {"not_spending", "duplicate"}:
            row["included"] = False
            row["effective_reason"] = None
        if row["source"] == "manual_md" and row["payment"] in {"", "альфа"}:
            candidates = [
                r.get("id")
                for r in bank_candidates
                if r["included"]
                and r["amount_kopecks"] == row["amount_kopecks"]
                and (
                    not row["operation_date"]
                    or abs((row["operation_date"] - r["operation_date"]).days) <= 3
                )
            ]
            row["duplicate_candidates"] = candidates
            if candidates and action not in {"separate", "duplicate", "not_spending"}:
                row["included"] = False
                row["effective_reason"] = "possible_duplicate"
            if action == "duplicate" and row.get("duplicate_of_id") not in candidates:
                row["included"] = False
                row["effective_reason"] = "duplicate_target_missing"
        if row.get("needs_review"):
            row["included"] = False
            row["effective_reason"] = "decision_not_transferred"
        # A decision cannot mix currencies or turn cash withdrawal into a purchase.
        if row["currency"] != "RUR":
            row["included"] = False
            row["effective_reason"] = None if action == "not_spending" else "foreign_currency"
        if row["reason"] == "unknown_status":
            row["included"] = False
            row["effective_reason"] = None if action == "not_spending" else "unknown_status"
        if row["kind"] in {"transfer", "repayment", "interest"} and row["included"]:
            row["included"] = False
            row["effective_reason"] = "technical_decision_conflict"
        if row["reason"] == "cash_withdrawal_decision" and action in {"expense", "refund"}:
            row["included"] = False
            row["effective_reason"] = "cash_withdrawal_decision"
        result.append(row)
    return result


def _public(row: dict) -> dict:
    # Deliberate allowlist: bank account/card/raw CSV are local storage only.
    result = {
        key: row.get(key)
        for key in (
            "id",
            "source",
            "operation_date",
            "transaction_date",
            "amount_kopecks",
            "direction",
            "currency",
            "status",
            "category",
            "description",
            "payment",
            "kind",
            "fingerprint",
            "ordinal",
            "merchant_key",
            "included",
            "effective_reason",
            "effective_action",
            "duplicate_candidates",
            "expense_type",
            "category_id",
            "bank_category",
        )
    }
    from hermes_finance.services.spending_insights import money

    result["amount"] = money(
        row.get("amount_kopecks"),
        "RUB" if row.get("currency") == "RUR" else row.get("currency", "RUB"),
    )
    result["counted_now"] = bool(row.get("included"))
    result["kind_hint"] = (
        "cash_withdrawal" if row.get("reason") == "cash_withdrawal_decision" else None
    )
    result["remember_key"] = row.get("merchant_key") if row.get("source") == "alfa_csv" else None
    result["remember_default"] = (
        row.get("effective_reason") == "uncategorized" and row.get("source") == "alfa_csv"
    )
    return result


def _decision_receipt(session: Session, row: dict) -> dict:
    receipt = _public(row)
    category = (
        session.get(SpendingCategory, row["decision_category_id"])
        if row["decision_category_id"]
        else None
    )
    receipt.update(
        decision=row["decision"],
        decision_category=category.name if category else None,
        duplicate_of_id=row["duplicate_of_id"],
        links=[],
    )
    for member in _objects(session, SpendingLinkOperation):
        if member.operation_id == row["id"]:
            link = session.get(SpendingExpenseLink, member.link_id)
            expense = session.get(ExpenseEntry, link.expense_entry_id)
            receipt["links"].append(
                dict(
                    link_id=link.id,
                    expense_entry_id=expense.id,
                    month_amount_kopecks=expense.amount_kopecks,
                    diary_amount_kopecks=row["amount_kopecks"],
                    remember_recurring=link.remember_recurring,
                )
            )
    return receipt


def _expense_rows(session: Session, month: str) -> list[ExpenseEntry]:
    year, number = map(int, month.split("-"))
    return list(
        session.scalars(
            select(ExpenseEntry)
            .join(ReportingMonth, ExpenseEntry.reporting_month_id == ReportingMonth.id)
            .where(ReportingMonth.year == year, ReportingMonth.month == number)
            .order_by(ExpenseEntry.id)
        )
    )


def _link_views(session: Session, month: str, rows: list[dict]) -> list[dict]:
    """Remembered links are deterministic read rules; GET never materialises writes."""
    expenses = _expense_rows(session, month)
    all_expenses = {e.id: e for e in _objects(session, ExpenseEntry)}
    month_keys = {m.id: (m.year, m.month) for m in _objects(session, ReportingMonth)}
    links = sorted(_objects(session, SpendingExpenseLink), key=lambda link: link.id)
    members = _objects(session, SpendingLinkOperation)
    operations = {r["id"]: r for r in rows if r.get("id") is not None}
    target_expenses = {expense.id for expense in expenses}
    reserved = {
        member.operation_id
        for member in members
        if any(
            link.id == member.link_id and link.active and link.expense_entry_id in target_expenses
            for link in links
        )
    }
    claimed, result = set(), []
    for expense in expenses:
        direct = next((link for link in links if link.expense_entry_id == expense.id), None)
        ids, link_id, remembered = [], None, False
        if direct:
            link_id = direct.id
            if direct.active:
                ids = [m.operation_id for m in members if m.link_id == direct.id]
        elif (
            expense.is_recurring
            and sum(
                e.is_recurring and normalize(e.category) == normalize(expense.category)
                for e in expenses
            )
            == 1
        ):
            templates = [
                link
                for link in links
                if link.active
                and link.remember_recurring
                and link.expense_entry_id in all_expenses
                and month_keys[all_expenses[link.expense_entry_id].reporting_month_id]
                < month_keys[expense.reporting_month_id]
                and normalize(all_expenses[link.expense_entry_id].category)
                == normalize(expense.category)
            ]
            # Competing templates/categories never make an automatic financial choice.
            key_sets = {tuple(json.loads(link.merchant_keys_json)) for link in templates}
            if len(key_sets) == 1:
                keys = next(iter(key_sets))
                ids = [
                    r["id"]
                    for r in rows
                    if r.get("id") is not None
                    and r["merchant_key"] in keys
                    and r["included"]
                    and r["amount_kopecks"] > 0
                    and r["id"] not in reserved
                ]
                remembered = bool(ids)
        valid = bool(ids) and all(
            i in operations and operations[i]["included"] and i not in claimed for i in ids
        )
        if valid:
            claimed.update(ids)
        result.append(
            dict(
                expense_entry_id=expense.id,
                link_id=link_id,
                confirmed=valid,
                needs_review=bool(direct and direct.active and not valid),
                remembered=remembered,
                separate=bool(direct and not direct.active and direct.merchant_keys_json == "[]"),
                operation_ids=sorted(ids),
                month_amount_kopecks=expense.amount_kopecks,
                diary_amount_kopecks=sum(
                    operations[i]["amount_kopecks"] for i in ids if i in operations
                )
                if ids
                else None,
            )
        )
    return result


def _read(
    session: Session,
    month: str,
    rows: list[dict],
    *,
    loaded: bool,
    link_choices: list[dict] | None = None,
    rule_overrides: dict | None = None,
) -> dict:
    effective = _effective(session, rows, rule_overrides)
    links = _link_views(session, month, effective)
    for choice in link_choices or []:
        link = next(
            (link for link in links if link["expense_entry_id"] == choice["expense_entry_id"]), None
        )
        if link is None:
            raise ValueError("Запись расходов не найдена в выбранном месяце")
        if choice["action"] == "separate":
            link.update(confirmed=False, separate=True, needs_review=False, operation_ids=[])
            continue
        ids = choice.get("operation_ids", [])
        chosen = [row for row in effective if row["id"] in ids and row["included"]]
        occupied = {
            i
            for other in links
            if other is not link and other["confirmed"]
            for i in other["operation_ids"]
        }
        if (
            choice["action"] != "link"
            or not ids
            or len(set(ids)) != len(chosen)
            or occupied.intersection(ids)
        ):
            raise ValueError("Выберите учитываемые операции для связи")
        expense = next(
            entry
            for entry in _expense_rows(session, month)
            if entry.id == choice["expense_entry_id"]
        )
        if choice.get("remember") and (
            not expense.is_recurring or any(row["amount_kopecks"] <= 0 for row in chosen)
        ):
            raise ValueError("Запоминать можно связь повторяющегося расхода с покупками")
        link.update(
            confirmed=True,
            separate=False,
            needs_review=False,
            operation_ids=ids,
            diary_amount_kopecks=sum(row["amount_kopecks"] for row in chosen),
        )
    excluded = {link["expense_entry_id"] for link in links if link["confirmed"]}
    contributions = [
        dict(
            id=r.get("id"),
            source=r["source"],
            payment=r["payment"],
            category=r["category"],
            expense_type=r["expense_type"],
            date=r["operation_date"],
            amount_kopecks=r["amount_kopecks"],
            pending=r["status"] == "В обработке",
        )
        for r in effective
        if r["included"]
    ]
    expenses = _expense_rows(session, month)
    contributions += [
        dict(
            id=e.id,
            source="expense_entries",
            payment=None,
            category=e.category,
            expense_type=e.expense_type,
            date=None,
            amount_kopecks=e.amount_kopecks,
            pending=False,
        )
        for e in expenses
        if e.id not in excluded
    ]
    category_sums, days, sources = defaultdict(int), defaultdict(int), defaultdict(int)
    category_sources = defaultdict(lambda: defaultdict(int))
    day_sources = defaultdict(lambda: defaultdict(int))
    origins = defaultdict(int)
    detail_sources = {key: defaultdict(int) for key in ("undated", "returns", "pending")}
    pending = returns = undated = 0
    for item in contributions:
        amount = item["amount_kopecks"]
        category_sums[item["category"]] += amount
        sources[item["source"]] += amount
        origin = (
            "manual_" + (item["payment"] or "unknown")
            if item["source"] == "manual_md"
            else item["source"]
        )
        origins[origin] += amount
        category_sources[item["category"]][item["source"]] += amount
        if item["date"]:
            days[item["date"].isoformat()] += amount
            day_sources[item["date"].isoformat()][item["source"]] += amount
        else:
            undated += amount
            detail_sources["undated"][item["source"]] += amount
        if item["pending"]:
            detail_sources["pending"][item["source"]] += amount
        if amount < 0:
            detail_sources["returns"][item["source"]] += amount
        pending += amount if item["pending"] else 0
        returns += amount if amount < 0 else 0
    positive = sum(value for value in category_sums.values() if value > 0)
    names = sorted(name for name, amount in category_sums.items() if amount > 0)
    units = {name: category_sums[name] * 10000 // positive for name in names}
    order = sorted(names, key=lambda name: (-(category_sums[name] * 10000 % positive), name))
    for name in order[: 10000 - sum(units.values())]:
        units[name] += 1
    shares = {
        name: (Decimal(value) / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        for name, value in units.items()
    }
    reviews = [
        dict(id=r.id, reason=r.reason, previous=json.loads(r.previous_json))
        for r in session.scalars(
            select(SpendingReview)
            .where(SpendingReview.month == month, SpendingReview.resolved.is_(False))
            .order_by(SpendingReview.id)
        )
    ]
    exceptions = [_public(r) for r in effective if r["effective_reason"]]
    double_count = []
    for expense, link in zip(expenses, links, strict=True):
        if link["confirmed"] or link["separate"]:
            continue
        candidates = [
            r["id"]
            for r in effective
            if r["included"]
            and (
                normalize(r["category"]) == normalize(expense.category)
                if expense.is_recurring
                else r["amount_kopecks"] == expense.amount_kopecks
            )
        ]
        if candidates:
            double_count.append(
                dict(
                    expense_entry_id=expense.id,
                    operation_ids=candidates,
                    reason="possible_month_double_count",
                )
            )
    known = sum(sources.values())
    return dict(
        contract_version=VERSION,
        month=month,
        loaded=loaded,
        total_kopecks=known
        if (loaded or expenses) and not reviews and not any(link["needs_review"] for link in links)
        else None,
        known_subtotal_kopecks=known,
        unresolved=bool(
            exceptions or reviews or double_count or any(link["needs_review"] for link in links)
        ),
        categories=[
            dict(
                category=name,
                amount_kopecks=category_sums[name],
                share_percent=str(shares[name]) if name in shares else None,
                sources=dict(sorted(category_sources[name].items())),
            )
            for name in sorted(category_sums)
        ],
        days=[
            dict(date=day, amount_kopecks=amount, sources=dict(sorted(day_sources[day].items())))
            for day, amount in sorted(days.items())
        ],
        undated_kopecks=undated,
        returns_kopecks=returns,
        pending_kopecks=pending,
        sources=dict(sorted(sources.items())),
        origins=dict(sorted(origins.items())),
        detail_sources={key: dict(sorted(value.items())) for key, value in detail_sources.items()},
        contributions=contributions,
        operations=[_public(r) for r in effective],
        exceptions=exceptions,
        reviews=reviews,
        links=links,
        month_link_candidates=double_count,
    )


def read_month(session: Session, month: str) -> dict:
    from hermes_finance.services.spending_insights import enrich_month

    return enrich_month(session, read_month_base(session, month))


def read_month_base(session: Session, month: str) -> dict:
    month_bounds(month)
    result = _read(
        session,
        month,
        _month_rows(session, month),
        loaded=bool(
            session.scalar(select(SpendingUpload.id).where(SpendingUpload.month == month).limit(1))
        ),
    )
    from hermes_finance.services.spending_insights import coverage_status

    result.update(coverage_status(session, month))
    return result


def list_months(session: Session, until: str | None = None, count: int = 12) -> dict:
    from hermes_finance.services.spending_insights import history

    return history(session, until=until, count=count)


def known_months(session: Session) -> list[str]:
    months = {u.month for u in _objects(session, SpendingUpload)}
    months |= {f"{m.year:04d}-{m.month:02d}" for m in _objects(session, ReportingMonth)}
    return sorted(months)


def _identity(row: dict) -> tuple:
    return row["fingerprint"], row["ordinal"]


def _validate_choice(
    row: dict, action: str, category: str | None, duplicate_of_id: int | None
) -> None:
    if action not in {"expense", "refund", "not_spending", "separate", "duplicate"}:
        raise ValueError("Неизвестное решение")
    if action in {"expense", "refund"} and not category:
        raise ValueError("Выберите категорию")
    if row["kind"] in {"transfer", "repayment", "interest"} and action != "not_spending":
        raise ValueError("Подтверждённая техническая операция не является тратой")
    if (
        action == "expense"
        and row["amount_kopecks"] < 0
        or action == "refund"
        and row["amount_kopecks"] > 0
    ):
        raise ValueError("Решение не соответствует направлению операции")
    if row["currency"] != "RUR" and action != "not_spending":
        raise ValueError("Валютную операцию нельзя складывать с рублями")
    if row["reason"] == "cash_withdrawal_decision" and action != "not_spending":
        raise ValueError("Снятие наличных не является тратой")
    if action in {"duplicate", "separate"} and (
        row["source"] != "manual_md" or row["payment"] not in {"", "альфа"}
    ):
        raise ValueError("Сопоставление разрешено только для оплаты альфа или пустой")
    if action == "duplicate" and duplicate_of_id is None:
        raise ValueError("Выберите операцию выписки")


def _plan(
    session: Session,
    source: str,
    month: str,
    filename: str,
    content: bytes,
    choices: list[dict],
    skip_error_lines: list[int],
    current_rows: list[dict] | None = None,
) -> dict:
    month_bounds(month)
    if source not in {"alfa_csv", "manual_md"}:
        raise ValueError("Поддерживаются alfa_csv и manual_md")
    if not filename.lower().endswith(".csv" if source == "alfa_csv" else ".md"):
        raise FileProblem(
            "unsupported_extension",
            "Выгрузите CSV Альфы" if source == "alfa_csv" else "Нужен файл .md",
            allowed_extension=".csv" if source == "alfa_csv" else ".md",
        )
    parsed = (alfa_operations if source == "alfa_csv" else manual_operations)(content, month)
    period = statement_period(filename) if source == "alfa_csv" else None
    incoming = parsed["rows"]
    session.info.setdefault("spending_redactions", set()).update(
        value for row in incoming for value in (row["account"], row["card"]) if value
    )
    if source == "alfa_csv" and not incoming and not parsed["errors"]:
        raise FileProblem(
            "no_month_rows",
            "Нет операций выбранного месяца; диапазон замены неизвестен",
            month=month,
            **{"from": parsed["outside_from"], "to": parsed["outside_to"]},
        )
    for r in incoming:
        r.update(
            source=source,
            month=month,
            id=None,
            decision=None,
            decision_category_id=None,
            duplicate_of_id=None,
            needs_review=False,
        )
    scopes = {}
    if source == "manual_md":
        scopes[""] = month_bounds(month)
    else:
        for account in sorted({r["account"] for r in incoming}):
            dates = [r["operation_date"] for r in incoming if r["account"] == account]
            scopes[account] = min(dates), max(dates)
    current = _month_rows(session, month) if current_rows is None else current_rows
    replaced = [
        r
        for r in current
        if r["source"] == source
        and r["account"] in scopes
        and (
            source == "manual_md"
            or scopes[r["account"]][0] <= r["operation_date"] <= scopes[r["account"]][1]
        )
    ]
    old_by_id = {_identity(r): r for r in replaced}
    categories = _categories(session)
    by_name = {key: c.id for c in categories.values() for key in {c.name_key, normalize(c.name)}}
    if source == "manual_md":
        projected_bank_categories = {
            normalize(row["category"]) for row in current if row["source"] == "alfa_csv"
        }
        for row in incoming:
            old = old_by_id.get(_identity(row))
            if row["category"] == UNCATEGORIZED:
                row["reason"] = "uncategorized"
            elif (
                normalize(row["category"]) not in by_name
                and normalize(row["category"]) not in projected_bank_categories
                or old
                and old["reason"] == "new_category"
            ):
                row["reason"] = "new_category"
    old_counts = Counter(r["fingerprint"] for r in replaced)
    new_counts = Counter(r["fingerprint"] for r in incoming)
    unchanged = bool(
        session.scalar(
            select(SpendingUpload.id)
            .where(SpendingUpload.source == source, SpendingUpload.month == month)
            .limit(1)
        )
    ) and sorted(digest([r[k] for k in ROW_FIELDS]) for r in replaced) == sorted(
        digest([r[k] for k in ROW_FIELDS]) for r in incoming
    )
    if source == "alfa_csv":
        for account in scopes:
            previous = session.scalar(
                select(SpendingUpload)
                .where(
                    SpendingUpload.month == month,
                    SpendingUpload.source == source,
                    SpendingUpload.account == account,
                )
                .order_by(SpendingUpload.id.desc())
                .limit(1)
            )
            previous_period = (
                (previous.period_from, previous.period_to)
                if previous and previous.period_from
                else None
            )
            unchanged = unchanged and previous is not None and previous_period == period
    added, changed, removed, lost = [], [], [], []
    memberships = {m.operation_id for m in _objects(session, SpendingLinkOperation)}
    annotated = set(
        session.scalars(
            select(SpendingPaymentRule.operation_id).where(SpendingPaymentRule.month == month)
        )
    )
    duplicate_targets = {r["duplicate_of_id"] for r in current if r["duplicate_of_id"]}
    for r in incoming:
        old = old_by_id.get(_identity(r))
        if old:
            r["id"] = old["id"]
            if unchanged or old_counts[r["fingerprint"]] == new_counts[r["fingerprint"]] == 1:
                for field in (
                    "decision",
                    "decision_category_id",
                    "duplicate_of_id",
                    "needs_review",
                ):
                    r[field] = old[field]
            elif (
                old["decision"]
                or old["id"] in memberships
                or old["id"] in duplicate_targets
                or old["id"] in annotated
            ):
                lost.append(old)
                r["needs_review"] = True
            if any(r[k] != old[k] for k in ROW_FIELDS):
                changed.append(r)
        else:
            added.append(r)
    new_keys = {_identity(r) for r in incoming}
    for old in replaced:
        if _identity(old) not in new_keys:
            removed.append(old)
            if old["decision"] or old["id"] in memberships or old["id"] in duplicate_targets:
                lost.append(old)
    if lost:
        for r in added:
            r["needs_review"] = True
    choice_map = {}
    for choice in choices:
        key = choice["fingerprint"], choice["ordinal"]
        if key in choice_map:
            raise ValueError("Повторное решение для строки")
        choice_map[key] = choice
    for r in incoming:
        choice = choice_map.pop(_identity(r), None)
        if choice:
            _validate_choice(
                r, choice["action"], choice.get("category"), choice.get("duplicate_of_id")
            )
            r.update(
                decision=choice["action"],
                decision_category_id=by_name.get(normalize(choice.get("category") or "")),
                duplicate_of_id=choice.get("duplicate_of_id"),
                needs_review=False,
            )
            if choice.get("category"):
                r["choice_category"] = (
                    categories[r["decision_category_id"]].name
                    if r["decision_category_id"]
                    else choice["category"].strip()
                )
    if choice_map:
        raise ValueError("Решение относится к отсутствующей строке")
    kept = [r for r in current if r not in replaced]
    projected = kept + incoming
    explicit_choices = {(choice["fingerprint"], choice["ordinal"]) for choice in choices}
    for r in _effective(session, projected):
        if (
            _identity(r) in explicit_choices
            and r.get("decision") == "duplicate"
            and r["effective_reason"] == "duplicate_target_missing"
        ):
            raise ValueError("Выбранная операция не является кандидатом в дубль")
    errors = parsed["errors"]
    if source == "alfa_csv" and skip_error_lines:
        raise ValueError("CSV с ошибками нельзя применять как замену")
    if set(skip_error_lines) - {e["line"] for e in errors}:
        raise ValueError("Указана отсутствующая ошибка строки")
    applicable = (
        not errors or source == "manual_md" and {e["line"] for e in errors} <= set(skip_error_lines)
    )
    token = digest(
        [
            VERSION,
            _state_token(session),
            source,
            month,
            hashlib.sha256(content).hexdigest(),
            choices,
            sorted(skip_error_lines),
            period,
        ]
    )
    before = _read(
        session,
        month,
        current,
        loaded=bool(current)
        or bool(
            session.scalar(select(SpendingUpload.id).where(SpendingUpload.month == month).limit(1))
        ),
    )
    after = _read(
        session,
        month,
        projected,
        loaded=True,
        rule_overrides=_preview_rules(session, projected, choices),
    )
    from hermes_finance.services.spending_insights import enrich_preview

    if lost:
        after["total_kopecks"] = None
        after["unresolved"] = True
    public = dict(
        contract_version=VERSION,
        preview_token=token,
        applicable=applicable,
        added=[_public(r) for r in added],
        changed=[_public(r) for r in changed],
        disappearing=[_public(r) for r in removed],
        decisions_not_transferred=[_decision_receipt(session, r) for r in lost],
        errors=errors,
        outside_month=parsed["outside_month"],
        technical_count=sum(r["kind"] in {"transfer", "repayment", "interest"} for r in incoming),
        ranges=[
            dict(account_key=digest(account), date_from=span[0], date_to=span[1])
            for account, span in sorted(scopes.items())
        ],
        before=before,
        after=after,
        delta_kopecks=(
            after["total_kopecks"] - before["total_kopecks"]
            if after["total_kopecks"] is not None and before["total_kopecks"] is not None
            else None
        ),
        advice="Выгружайте выписку не раньше 5-го числа следующего месяца",
        category_proposals=sorted(
            {r["category"] for r in incoming if normalize(r["category"]) not in by_name}
        ),
    )
    enrich_preview(
        session,
        public,
        source=source,
        month=month,
        incoming=incoming,
        projected=projected,
        scopes=scopes,
        period=period,
        parsed=parsed,
        rule_overrides=_preview_rules(session, projected, choices),
    )
    return dict(
        public=public,
        incoming=incoming,
        replaced=replaced,
        scopes=scopes,
        lost=lost,
        removed=removed,
        unchanged=unchanged and not choices,
        period=period,
        projected=projected,
    )


def preview_upload(
    session: Session,
    *,
    source: str,
    month: str,
    filename: str,
    content: bytes,
    choices: list[dict] | None = None,
    skip_error_lines: list[int] | None = None,
) -> dict:
    with session.no_autoflush:
        return _plan(
            session, source, month, filename, content, choices or [], skip_error_lines or []
        )["public"]


def _invalidate_links(session: Session, operation_ids: set[int]) -> None:
    memberships = [
        m for m in _objects(session, SpendingLinkOperation) if m.operation_id in operation_ids
    ]
    for member in memberships:
        link = session.get(SpendingExpenseLink, member.link_id)
        link.active = False
        session.delete(member)
    for operation in _objects(session, SpendingOperation):
        if operation.duplicate_of_id in operation_ids:
            operation.duplicate_of_id = None
            operation.decision = None
            operation.needs_review = True
    session.flush()


def apply_upload(
    session: Session,
    *,
    source: str,
    month: str,
    filename: str,
    content: bytes,
    preview_token: str,
    confirm_disappearance: bool = False,
    choices: list[dict] | None = None,
    skip_error_lines: list[int] | None = None,
) -> dict:
    plan = _plan(session, source, month, filename, content, choices or [], skip_error_lines or [])
    public = plan["public"]
    if not public["applicable"]:
        raise ValueError("Исправьте ошибки файла или подтвердите пропуск строк ручного файла")
    if plan["unchanged"]:
        return dict(changed=False, month=read_month(session, month))
    if preview_token != public["preview_token"]:
        raise PreviewChanged("Данные изменились: получите новое preview")
    if plan["removed"] and not confirm_disappearance:
        raise ValueError("Подтвердите исчезновение операций внутри диапазона замены")
    uploads = {}
    for account, (start, end) in sorted(plan["scopes"].items()):
        period = plan["period"]
        account_name = next(
            (
                json.loads(r["raw_json"]).get("accountName", "")
                for r in plan["incoming"]
                if r["account"] == account
            ),
            "",
        )
        upload = SpendingUpload(
            source=source,
            month=month,
            account=account,
            filename=filename.replace("\\", "/").split("/")[-1],
            sha256=hashlib.sha256(content).hexdigest(),
            date_from=start,
            date_to=end,
            period_from=period[0] if period else None,
            period_to=period[1] if period else None,
            account_name=account_name,
            uploaded_at=datetime.now(UTC),
        )
        session.add(upload)
        session.flush()
        uploads[account] = upload.id
    lost_ids = {r["id"] for r in plan["lost"]} | {r["id"] for r in plan["removed"]}
    receipts = [_decision_receipt(session, old) for old in plan["lost"]]
    for rule in session.scalars(
        select(SpendingPaymentRule).where(SpendingPaymentRule.operation_id.in_(lost_ids))
    ):
        rule.operation_id = None
        rule.version += 1
    _invalidate_links(session, lost_ids)
    for receipt in receipts:
        session.add(
            SpendingReview(
                month=month,
                reason="decision_not_transferred",
                previous_json=json.dumps(receipt, ensure_ascii=False, default=str),
            )
        )
    for old in plan["removed"]:
        session.delete(session.get(SpendingOperation, old["id"]))
    session.flush()
    for r in plan["incoming"]:
        _category(session, r["category"])
        category = _category(session, r["choice_category"]) if r.get("choice_category") else None
        values = {key: r[key] for key in ROW_FIELDS}
        values.update(
            source=source,
            month=month,
            upload_id=uploads[r["account"]],
            decision=r["decision"],
            decision_category_id=category.id if category else r["decision_category_id"],
            duplicate_of_id=r["duplicate_of_id"],
            needs_review=r["needs_review"],
        )
        operation = session.get(SpendingOperation, r["id"]) if r["id"] is not None else None
        if operation is None:
            session.add(SpendingOperation(**values))
        else:
            for key, value in values.items():
                setattr(operation, key, value)
    session.flush()
    for choice in choices or []:
        if choice.get("remember"):
            row = next(row for row in plan["incoming"] if _identity(row) == _identity(choice))
            set_rule(
                session,
                scope="merchant",
                key=row["merchant_key"],
                action=choice["action"],
                category=choice.get("category"),
            )
    return dict(changed=True, month=read_month(session, month))


def decide_operation(
    session: Session,
    operation_id: int,
    *,
    action: str,
    category: str | None = None,
    duplicate_of_id: int | None = None,
    remember: bool = False,
) -> dict:
    operation = session.get(SpendingOperation, operation_id)
    if operation is None:
        raise LookupError("Операция не найдена")
    row = _row(operation)
    _validate_choice(row, action, category, duplicate_of_id)
    if duplicate_of_id is not None:
        candidates = next(
            r
            for r in _effective(session, _month_rows(session, operation.month))
            if r["id"] == operation.id
        ).get("duplicate_candidates", [])
        if duplicate_of_id not in candidates:
            raise ValueError("Операция не является кандидатом в дубль")
    cat = _category(session, category) if category else None
    operation.decision, operation.decision_category_id = action, cat.id if cat else None
    operation.duplicate_of_id = duplicate_of_id if action == "duplicate" else None
    operation.needs_review = False
    if remember:
        if action not in {"expense", "refund", "not_spending"} or operation.source != "alfa_csv":
            raise ValueError("Это решение не может стать правилом продавца")
        set_rule(
            session, scope="merchant", key=operation.merchant_key, action=action, category=category
        )
    session.flush()
    return read_month(session, operation.month)


def set_rule(
    session: Session, *, scope: str, key: str, action: str, category: str | None = None
) -> int:
    if scope not in {"merchant", "bank_category"} or not key.strip():
        raise ValueError("Неверный ключ правила")
    if (
        action not in {"expense", "refund", "not_spending"}
        or action != "not_spending"
        and not category
    ):
        raise ValueError("Неверное решение правила")
    if scope == "bank_category" and action != "expense":
        raise ValueError("Соответствие категорий меняет только категорию")
    key = normalize(key)
    cat = _category(session, category) if category else None
    rule = session.scalar(
        select(SpendingRule).where(SpendingRule.scope == scope, SpendingRule.key == key)
    )
    if rule is None:
        rule = SpendingRule(scope=scope, key=key)
        session.add(rule)
    rule.action, rule.category_id = action, cat.id if cat else None
    session.flush()
    return rule.id


def create_link(
    session: Session, expense_entry_id: int, operation_ids: list[int], *, remember: bool = False
) -> int:
    expense = session.get(ExpenseEntry, expense_entry_id)
    if expense is None:
        raise LookupError("Запись расходов месяца не найдена")
    month_obj = session.get(ReportingMonth, expense.reporting_month_id)
    month = f"{month_obj.year:04d}-{month_obj.month:02d}"
    rows = _effective(session, _month_rows(session, month))
    chosen = [r for r in rows if r["id"] in operation_ids]
    if (
        not operation_ids
        or len(chosen) != len(set(operation_ids))
        or any(not r["included"] for r in chosen)
    ):
        raise ValueError("Выберите учитываемые операции того же месяца")
    if remember and (not expense.is_recurring or any(r["amount_kopecks"] <= 0 for r in chosen)):
        raise ValueError("Запоминать можно связь повторяющегося расхода с покупками")
    link = session.scalar(
        select(SpendingExpenseLink).where(SpendingExpenseLink.expense_entry_id == expense_entry_id)
    )
    occupied = [
        m for m in _objects(session, SpendingLinkOperation) if m.operation_id in operation_ids
    ]
    if any(link is None or member.link_id != link.id for member in occupied):
        raise ValueError("Операция уже связана с другой записью месяца")
    if link is None:
        link = SpendingExpenseLink(
            expense_entry_id=expense_entry_id,
            merchant_keys_json="[]",
            remember_recurring=False,
            active=True,
        )
        session.add(link)
        session.flush()
    for member in _objects(session, SpendingLinkOperation):
        if member.link_id == link.id:
            session.delete(member)
    session.flush()
    link.remember_recurring, link.active = remember, True
    link.merchant_keys_json = json.dumps(
        sorted({r["merchant_key"] for r in chosen}), ensure_ascii=False
    )
    for operation_id in sorted(set(operation_ids)):
        session.add(SpendingLinkOperation(link_id=link.id, operation_id=operation_id))
    session.flush()
    return link.id


def delete_link(session: Session, link_id: int) -> None:
    link = session.get(SpendingExpenseLink, link_id)
    if link is None:
        raise LookupError("Связь не найдена")
    for member in _objects(session, SpendingLinkOperation):
        if member.link_id == link_id:
            session.delete(member)
    session.flush()
    session.delete(link)
    session.flush()


def separate_month_expense(session: Session, expense_entry_id: int) -> None:
    expense = session.get(ExpenseEntry, expense_entry_id)
    if expense is None:
        raise LookupError("Запись расходов месяца не найдена")
    link = session.scalar(
        select(SpendingExpenseLink).where(SpendingExpenseLink.expense_entry_id == expense_entry_id)
    )
    if link:
        delete_link(session, link.id)
    session.add(
        SpendingExpenseLink(
            expense_entry_id=expense_entry_id,
            active=False,
            remember_recurring=False,
            merchant_keys_json="[]",
        )
    )
    session.flush()
