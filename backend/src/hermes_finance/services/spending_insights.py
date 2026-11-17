"""Exact, read-only projections for the spending screen. No month-fact writes."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from hermes_finance.persistence import SpendingCategory, SpendingUpload
from hermes_finance.services import spending_diary as diary
from hermes_finance.spending_files import UNCATEGORIZED, digest, month_bounds, normalize


def money(kopecks: int | Decimal | None, currency: str = "RUB") -> dict | None:
    if kopecks is None:
        return None
    return {
        "amount": str((Decimal(kopecks) / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "currency": currency,
    }


def shift_month(month: str, offset: int) -> str:
    start, _ = month_bounds(month)
    serial = start.year * 12 + start.month - 1 + offset
    year, number = divmod(serial, 12)
    return f"{year:04d}-{number + 1:02d}"


def delta(current: int, average: Decimal) -> str | None:
    if not average:
        return None
    return str(
        ((Decimal(current) - average) * 100 / abs(average)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    )


def coverage_status(session: Session, month: str, overrides: list[dict] | None = None) -> dict:
    start, end = month_bounds(month)
    uploads = [
        dict(
            source=u.source,
            account=u.account,
            period_from=u.period_from,
            period_to=u.period_to,
            date_from=u.date_from,
            date_to=u.date_to,
        )
        for u in diary._objects(session, SpendingUpload)
        if u.month == month
    ]
    uploads += overrides or []
    latest, intervals = {}, defaultdict(list)
    for upload in uploads:
        latest[upload["source"], upload["account"]] = upload
        if upload["source"] == "alfa_csv":
            if upload["period_from"] is None or upload["period_to"] is None:
                intervals[upload["account"]] = []
            else:
                intervals[upload["account"]].append((upload["period_from"], upload["period_to"]))
    statements = [u for u in latest.values() if u["source"] == "alfa_csv"]
    spans, full = [], bool(statements)
    for upload in statements:
        a, b = upload["period_from"], upload["period_to"]
        merged = []
        for first, last in sorted(intervals[upload["account"]]):
            if merged and first.toordinal() <= merged[-1][1].toordinal() + 1:
                merged[-1] = (merged[-1][0], max(last, merged[-1][1]))
            else:
                merged.append((first, last))
        full = full and any(first <= start and last >= end for first, last in merged)
        if merged:
            a, b = merged[0][0], merged[-1][1]
        a, b = (
            (a, b) if a is not None and b is not None else (upload["date_from"], upload["date_to"])
        )
        if a <= end and b >= start:
            spans.append((max(a, start), min(b, end)))
    has_statement = bool(statements)
    has_manual = any(u["source"] == "manual_md" for u in latest.values())
    common_from = max((a for a, _ in spans), default=None)
    common_to = min((b for _, b in spans), default=None)
    if common_from and common_to and common_from > common_to:
        common_from = common_to = None
    return dict(
        has_statement=has_statement,
        has_manual=has_manual,
        coverage={
            "from": common_from,
            "to": common_to,
            "full": bool(full),
        },
        coverage_kind="statement_and_manual"
        if has_statement and has_manual
        else "statement_only"
        if has_statement
        else "manual_only"
        if has_manual
        else "not_loaded",
        partial=has_statement and not full,
    )


def _source(item: dict) -> str:
    if item["source"] == "expense_entries":
        return "month_entries"
    if item["source"] == "alfa_csv" or item["payment"] == "альфа":
        return "alfa"
    return {"нал": "cash", "сбер": "sber"}.get(item["payment"], "manual_other")


def _category_id(session: Session, name: str, *, virtual: bool = True) -> int | None:
    obj = next(
        (
            c
            for c in diary._objects(session, SpendingCategory)
            if normalize(name) in {c.name_key, normalize(c.name)}
        ),
        None,
    )
    return obj.id if obj else -int(digest(normalize(name))[:13], 16) if virtual else None


def _category_key(session: Session, item: dict) -> tuple:
    category_id = _category_id(session, item["category"])
    return ("id", category_id) if category_id else ("name", normalize(item["category"]))


def _sums_by_category(session: Session, result: dict) -> dict:
    sums = defaultdict(int)
    for item in result["contributions"]:
        sums[_category_key(session, item)] += item["amount_kopecks"]
    return sums


def _entry_links(
    session: Session, result: dict, *, include_unconfirmed: bool = False
) -> list[dict]:
    expenses = {e.id: e for e in diary._expense_rows(session, result["month"])}
    return [
        dict(
            id=link["link_id"],
            expense_entry_id=link["expense_entry_id"],
            entry_category=expenses[link["expense_entry_id"]].category,
            month_amount=money(link["month_amount_kopecks"]),
            diary_amount=money(link["diary_amount_kopecks"]),
            automatic=link["remembered"],
            operation_ids=link["operation_ids"],
            confirmed=link["confirmed"],
            needs_review=link["needs_review"],
            separate=link["separate"],
        )
        for link in result["links"]
        if link["confirmed"] or include_unconfirmed and link["link_id"] is not None
    ]


def operations(
    session: Session,
    result: dict,
    *,
    category: int | None = None,
    source: str | None = None,
    limit: int | None = 50,
) -> dict:
    if source not in {None, "alfa", "cash", "sber", "manual_other", "month_entries"}:
        raise ValueError("Неизвестный источник трат")
    linked = {
        operation_id: link
        for link in _entry_links(session, result)
        for operation_id in link["operation_ids"]
    }
    descriptions = {r["id"]: r["description"] for r in result["operations"]}
    items = []
    for item in result["contributions"]:
        month_entry = item["source"] == "expense_entries"
        category_id = _category_id(session, item["category"])
        item_source = _source(item)
        if category is not None and category_id != category or source and item_source != source:
            continue
        link = linked.get(item["id"]) if not month_entry else None
        items.append(
            dict(
                id=item["id"],
                date=item["date"],
                description=item["category"] if month_entry else descriptions.get(item["id"], ""),
                category_id=category_id,
                category_name=item["category"],
                source=item_source,
                amount=money(item["amount_kopecks"]),
                kind="refund" if item["amount_kopecks"] < 0 else "purchase",
                processing=item["pending"],
                linked_entry={"category": link["entry_category"], "amount": link["month_amount"]}
                if link
                else None,
                is_month_entry=month_entry,
            )
        )
    items.sort(
        key=lambda item: (
            item["is_month_entry"],
            item["date"] is None,
            -(item["date"].toordinal() if item["date"] else 0),
            item["id"] or 0,
        )
    )
    total = sum((Decimal(item["amount"]["amount"]) * 100 for item in items), Decimal(0))
    return dict(
        items=items if limit is None else items[:limit],
        total_count=len(items),
        filtered_total=money(total),
    )


GROUPS = {
    "transfer_decision": "transfer",
    "refund_candidate": "refund",
    "possible_duplicate": "possible_duplicate",
    "foreign_currency": "foreign_currency",
    "uncategorized": "uncategorized",
    "new_category": "new_category",
    "cash_withdrawal_decision": "unknown_debit",
}


def exception_views(session: Session, result: dict) -> list[dict]:
    items = []
    rows = {r["id"]: r for r in result["operations"] if r["id"] is not None}
    for row in result["exceptions"]:
        reason = row["effective_reason"]
        previous = next(
            (
                r["previous"]
                for r in result["reviews"]
                if r["previous"].get("fingerprint") == row["fingerprint"]
            ),
            None,
        )
        # A changed fingerprint has no provable one-to-one prior decision. Show all receipts.
        candidates = [rows[i] for i in (row.get("duplicate_candidates") or []) if i in rows]
        key = row["merchant_key"] if row["source"] == "alfa_csv" else None
        items.append(
            dict(
                id=f"operation:{row['id']}"
                if row["id"] is not None
                else f"row:{row['fingerprint']}:{row['ordinal']}",
                operation_id=row["id"],
                fingerprint=row["fingerprint"],
                ordinal=row["ordinal"],
                group=GROUPS.get(reason, "unknown_debit"),
                reason_code=reason,
                date=row["operation_date"],
                description=row["description"],
                amount=money(
                    row["amount_kopecks"], "RUB" if row["currency"] == "RUR" else row["currency"]
                ),
                bank_category=row.get("bank_category"),
                candidates=candidates,
                remember_key=key,
                remember_default=reason == "uncategorized" and key is not None,
                carried_over_failed=reason == "decision_not_transferred",
                previous_decision=previous,
                previous_decisions=[r["previous"] for r in result["reviews"]]
                if reason == "decision_not_transferred"
                else [],
                counted_now=bool(row["included"]),
                kind_hint=row.get("kind_hint"),
                recurring=False,
            )
        )
    for review in result["reviews"]:
        items.append(
            dict(
                id=f"review:{review['id']}",
                review_id=review["id"],
                group="unknown_debit",
                reason_code=review["reason"],
                carried_over_failed=True,
                previous_decision=review["previous"],
                counted_now=False,
                remember_key=None,
                remember_default=False,
                kind_hint=None,
                recurring=False,
                candidates=[],
            )
        )
    expenses = {e.id: e for e in diary._expense_rows(session, result["month"])}
    for link in result["month_link_candidates"]:
        entry = expenses[link["expense_entry_id"]]
        items.append(
            dict(
                id=f"entry:{entry.id}",
                expense_entry_id=entry.id,
                group="entry_link",
                amount=money(entry.amount_kopecks),
                category=entry.category,
                recurring=entry.is_recurring,
                candidates=[rows[i] for i in link["operation_ids"] if i in rows],
                counted_now=True,
                remember_key=None,
                remember_default=False,
                carried_over_failed=False,
                previous_decision=None,
                kind_hint=None,
            )
        )
    for link in result["links"]:
        if link["needs_review"]:
            items.append(
                dict(
                    id=f"link:{link['link_id']}",
                    link_id=link["link_id"],
                    group="entry_link",
                    reason_code="invalid_link",
                    counted_now=True,
                    carried_over_failed=True,
                    previous_decision=link,
                    remember_key=None,
                    remember_default=False,
                    recurring=False,
                    kind_hint=None,
                    candidates=[],
                )
            )
    return items


def _daily(result: dict, *, today: date | None = None) -> list[dict]:
    today = today or date.today()
    start, end = month_bounds(result["month"])
    amounts = {date.fromisoformat(day["date"]).day: day["amount_kopecks"] for day in result["days"]}
    last = end.day
    if start.year == today.year and start.month == today.month:
        last = max(amounts, default=0)
    cumulative, points = 0, []
    for day in range(1, last + 1):
        cumulative += amounts.get(day, 0)
        points.append(dict(day=day, cumulative=money(cumulative)))
    return points if result["loaded"] else []


def enrich_month(session: Session, result: dict) -> dict:
    month = result["month"]
    result["total"] = money(result["total_kopecks"]) if result["loaded"] else None
    result["known_subtotal"] = money(result["known_subtotal_kopecks"])
    sources = dict.fromkeys(("alfa", "cash", "sber", "manual_other", "month_entries"), 0)
    types = dict.fromkeys(("mandatory", "comfortable", "other"), 0)
    for item in result["contributions"]:
        sources[_source(item)] += item["amount_kopecks"]
        types[item["expense_type"]] += item["amount_kopecks"]
    result["by_source"] = {key: money(value) for key, value in sources.items()}
    result["by_type"] = {
        key: money(value) if result["loaded"] else None for key, value in types.items()
    }
    result["month_entries_total"] = money(sources["month_entries"])
    result["processing_total"] = money(result["pending_kopecks"])
    result["refunds_total"] = money(result["returns_kopecks"])
    result["cash"] = dict(withdrawn=None, recorded=money(sources["cash"]))
    result["entry_links"] = _entry_links(session, result)
    items = exception_views(session, result)
    result["open_exceptions"] = dict(
        count=len(items),
        excluded_count=sum(not item["counted_now"] for item in items),
        double_risk_count=sum(item["group"] == "entry_link" for item in items),
    )
    current_ops = operations(session, result, limit=None)["items"]
    result["top_purchases"] = sorted(
        (
            item
            for item in current_ops
            if not item["is_month_entry"] and Decimal(item["amount"]["amount"]) > 0
        ),
        key=lambda item: (-Decimal(item["amount"]["amount"]), item["id"] or 0),
    )[:5]
    previous_month = shift_month(month, -1)
    previous = diary.read_month_base(session, previous_month)
    reason = (
        "not_loaded"
        if not previous["loaded"]
        else "partial"
        if not previous["coverage"]["full"]
        else None
    )
    result["daily"] = dict(
        current=_daily(result),
        previous=dict(month=previous_month, points=_daily(previous)) if reason is None else None,
        previous_unavailable_reason=reason,
        undated_total=money(result["undated_kopecks"] - sources["month_entries"]),
        month_entries_total=money(sources["month_entries"]),
    )
    comparison_months = []
    if result["loaded"] and not result["partial"]:
        for candidate in reversed(diary.known_months(session)):
            if candidate >= month:
                continue
            past = diary.read_month_base(session, candidate)
            if past["loaded"] and past["coverage"]["full"] and past["total_kopecks"] is not None:
                comparison_months.append(past)
                if len(comparison_months) == 3:
                    break
    result["comparison"] = None
    if comparison_months:
        average = sum(
            (Decimal(past["total_kopecks"]) for past in comparison_months), Decimal(0)
        ) / len(comparison_months)
        result["comparison"] = dict(
            average_total=money(average),
            delta_percent=delta(result["total_kopecks"], average)
            if result["total_kopecks"] is not None
            else None,
            months=[
                dict(month=past["month"], has_manual=past["has_manual"])
                for past in reversed(comparison_months)
            ],
            caveat="missing_manual"
            if result["has_manual"] and any(not past["has_manual"] for past in comparison_months)
            else None,
        )
    past_sums = [_sums_by_category(session, past) for past in comparison_months]
    refund_categories = []
    for category in result["categories"]:
        name = category["category"]
        key = _category_key(session, category)
        average = (
            sum((Decimal(sums.get(key, 0)) for sums in past_sums), Decimal(0)) / len(past_sums)
            if past_sums
            else None
        )
        category.update(
            id=_category_id(session, name),
            name=name,
            type=next(
                (c["expense_type"] for c in result["contributions"] if c["category"] == name),
                "other",
            ),
            amount=money(category["amount_kopecks"]),
            average_3m=money(average),
            delta_percent=delta(category["amount_kopecks"], average)
            if average is not None
            else None,
            is_new=bool(past_sums) and all(key not in sums for sums in past_sums),
        )
        refunded = sum(
            c["amount_kopecks"]
            for c in result["contributions"]
            if c["category"] == name and c["amount_kopecks"] < 0
        )
        if refunded:
            refund_categories.append(dict(id=category["id"], name=name, amount=money(refunded)))
    # Retain legacy negative category rows with null shares; the screen reads positive_categories.
    result["categories"].sort(
        key=lambda category: (-category["amount_kopecks"], category["category"])
    )
    result["positive_categories"] = [
        category for category in result["categories"] if category["amount_kopecks"] > 0
    ]
    result["refunds"] = (
        dict(amount=money(result["returns_kopecks"]), categories=refund_categories)
        if refund_categories
        else None
    )
    result["uncategorized_id"] = _category_id(session, UNCATEGORIZED, virtual=False)
    return result


def history(
    session: Session, *, until: str | None = None, count: int = 12, category: int | None = None
) -> dict:
    if not 1 <= count <= 1200:
        raise ValueError("count должен быть от 1 до 1200")
    if (
        category is not None
        and session.get(SpendingCategory, category) is None
        and not any(
            _category_id(session, entry.category) == category
            for entry in diary._objects(session, diary.ExpenseEntry)
        )
    ):
        raise LookupError("Категория не найдена")
    known = diary.known_months(session)
    uploaded = sorted({upload.month for upload in diary._objects(session, SpendingUpload)})
    until = until or (uploaded[-1] if uploaded else shift_month(date.today().strftime("%Y-%m"), -1))
    month_bounds(until)
    items = []
    for offset in range(1 - count, 1):
        month = shift_month(until, offset)
        result = diary.read_month_base(session, month)
        contributions = (
            result["contributions"]
            if category is None
            else [
                item
                for item in result["contributions"]
                if _category_id(session, item["category"]) == category
            ]
        )
        entries = sum(
            item["amount_kopecks"] for item in contributions if item["source"] == "expense_entries"
        )
        total = (
            result["total_kopecks"]
            if category is None
            else sum(item["amount_kopecks"] for item in contributions)
            if result["total_kopecks"] is not None
            else None
        )
        types = {
            kind: money(
                sum(
                    item["amount_kopecks"] for item in contributions if item["expense_type"] == kind
                )
            )
            if result["loaded"]
            else None
            for kind in ("mandatory", "comfortable", "other")
        }
        items.append(
            dict(
                month=month,
                loaded=result["loaded"],
                total=money(total) if result["loaded"] else None,
                total_kopecks=total,
                by_type=types,
                refunds_total=money(
                    sum(
                        item["amount_kopecks"]
                        for item in contributions
                        if item["amount_kopecks"] < 0
                    )
                )
                if result["loaded"]
                else None,
                coverage=result["coverage"],
                partial=result["partial"],
                has_statement=result["has_statement"],
                has_manual=result["has_manual"],
                month_entries_total=money(entries),
            )
        )
    return dict(items=items, has_more=any(month < items[0]["month"] for month in known))


ERROR_CODES = {
    "Ожидается 16 колонок": "csv_column_count",
    "Сумма должна быть положительным числом с точкой": "invalid_amount",
    "Неизвестное направление операции": "invalid_direction",
    "Не указан счёт или валюта": "missing_account_or_currency",
    "Ожидается дата ДД.ММ.ГГГГ": "invalid_date",
    "Неверная дата операции": "invalid_date",
    "Неверная дата": "invalid_date",
    "Ожидается пять колонок": "manual_column_count",
    "Дата вне выбранного месяца": "date_outside_month",
    "Нужна ненулевая сумма в рублях": "invalid_amount",
    "Неизвестный способ оплаты": "invalid_payment",
}


def enrich_preview(
    session: Session,
    public: dict,
    *,
    source: str,
    month: str,
    incoming: list[dict],
    projected: list[dict],
    scopes: dict,
    period: tuple | None,
    parsed: dict,
    rule_overrides: dict | None = None,
) -> None:
    effective = diary._effective(session, projected, rule_overrides)
    overrides = [
        dict(
            source=source,
            account=account,
            period_from=period[0] if period else None,
            period_to=period[1] if period else None,
            date_from=span[0],
            date_to=span[1],
        )
        for account, span in scopes.items()
    ]
    coverage = coverage_status(session, month, overrides)
    public.update(
        month=month,
        total_before=money(public["before"]["total_kopecks"]),
        total_after=money(public["after"]["total_kopecks"]),
        coverage=coverage["coverage"],
        out_of_month={
            "count": parsed["outside_month"],
            "from": parsed.get("outside_from"),
            "to": parsed.get("outside_to"),
        },
        stale=False,
        file_errors=[
            dict(
                file="statement" if source == "alfa_csv" else "manual",
                code=ERROR_CODES.get(error["reason"], "invalid_row"),
                line=error["line"],
                month=month,
            )
            for error in parsed["errors"]
        ],
        blocking=dict(
            needs_removal_confirmation=bool(public["disappearing"]),
            unreadable_manual_rows=[error["line"] for error in parsed["errors"]]
            if source == "manual_md"
            else [],
        ),
    )
    public["after"].update(coverage)
    exceptions = exception_views(session, public["after"])
    for row in exceptions:
        if row["carried_over_failed"]:
            receipts = public["decisions_not_transferred"]
            row["previous_decision"] = next(
                (
                    receipt
                    for receipt in receipts
                    if receipt.get("fingerprint") == row.get("fingerprint")
                ),
                None,
            )
            row["previous_decisions"] = receipts
    public["exceptions"] = exceptions
    public["sets"] = []
    for account in scopes:
        rows = [row for row in incoming if row["account"] == account]
        account_name = next(
            (json.loads(row["raw_json"]).get("accountName", "") for row in rows), ""
        )
        label = (
            (account_name + " ··" + account[-4:]).strip() if source == "alfa_csv" else "Ручной файл"
        )
        identities = {diary._identity(row) for row in rows}
        removed = [
            row
            for row in public["disappearing"]
            if any(
                old["account"] == account and diary._identity(old) == diary._identity(row)
                for old in diary._month_rows(session, month)
            )
        ]
        changed = [row for row in public["changed"] if diary._identity(row) in identities]
        before = [
            row
            for row in diary._effective(session, diary._month_rows(session, month))
            if row["source"] == source and row["account"] == account and row["included"]
        ]
        after = [
            row
            for row in effective
            if row["source"] == source and row["account"] == account and row["included"]
        ]
        public["sets"].append(
            dict(
                label=label,
                kind="statement" if source == "alfa_csv" else "manual",
                added=sum(diary._identity(row) in identities for row in public["added"]),
                changed=len(changed),
                removed=len(removed),
                total_before=money(sum(row["amount_kopecks"] for row in before))
                if any(
                    upload.source == source and upload.month == month and upload.account == account
                    for upload in diary._objects(session, SpendingUpload)
                )
                else None,
                total_after=money(sum(row["amount_kopecks"] for row in after)),
                removed_items=removed,
                changed_items=changed,
            )
        )
    technical = [
        diary._public(row)
        for row in effective
        if row["kind"] in {"transfer", "interest", "repayment"}
    ]
    public["technical"] = dict(count=len(technical), items=technical)
    public["processing"] = dict(
        count=sum(row["included"] and row["status"] == "В обработке" for row in effective),
        amount=money(public["after"]["pending_kopecks"]),
    )


def exceptions(session: Session, month: str) -> dict:
    result = diary.read_month_base(session, month)
    items = exception_views(session, result)
    return dict(
        month=month,
        items=items,
        count=len(items),
        total=money(result["total_kopecks"]) if result["loaded"] else None,
    )


def decide_exceptions(session: Session, month: str, decisions: list[dict]) -> dict:
    from hermes_finance.persistence import SpendingExpenseLink, SpendingOperation, SpendingReview

    month_bounds(month)
    for decision in decisions:
        kind, _, value = decision["id"].partition(":")
        if not value.isdigit():
            raise ValueError("Неверный идентификатор исключения")
        object_id = int(value)
        action = decision["action"]
        if kind == "operation":
            obj = session.get(SpendingOperation, object_id)
            if obj is None or obj.month != month:
                raise LookupError("Операция не найдена в выбранном месяце")
            diary.decide_operation(
                session,
                object_id,
                action=action,
                category=decision.get("category"),
                duplicate_of_id=decision.get("duplicate_of_id"),
                remember=decision.get("remember", False),
            )
        elif kind == "review" and action == "acknowledge":
            obj = session.get(SpendingReview, object_id)
            if obj is None or obj.month != month:
                raise LookupError("Исключение не найдено в выбранном месяце")
            obj.resolved = True
        elif kind == "entry":
            if object_id not in {entry.id for entry in diary._expense_rows(session, month)}:
                raise LookupError("Запись не найдена в выбранном месяце")
            if action == "separate":
                diary.separate_month_expense(session, object_id)
            elif action == "link":
                diary.create_link(
                    session,
                    object_id,
                    decision.get("operation_ids", []),
                    remember=decision.get("remember", False),
                )
            else:
                raise ValueError("Выберите связь или отдельную трату")
        elif kind == "link" and action == "unlink":
            link = session.get(SpendingExpenseLink, object_id)
            if link is None or link.expense_entry_id not in {
                entry.id for entry in diary._expense_rows(session, month)
            }:
                raise LookupError("Связь не найдена в выбранном месяце")
            diary.delete_link(session, object_id)
        else:
            raise ValueError("Неверное решение исключения")
        session.flush()
    return dict(exceptions=exceptions(session, month), month=diary.read_month(session, month))


def merge_category(session: Session, category_id: int, target_id: int) -> dict:
    from hermes_finance.persistence import SpendingOperation, SpendingRule

    source, target = (
        session.get(SpendingCategory, category_id),
        session.get(SpendingCategory, target_id),
    )
    if source is None or target is None:
        raise LookupError("Категория не найдена")
    if category_id == target_id:
        raise ValueError("Выберите другую категорию")
    for alias in {source.name_key, normalize(source.name)}:
        diary.set_rule(
            session, scope="bank_category", key=alias, action="expense", category=target.name
        )
    for rule in diary._objects(session, SpendingRule):
        if rule.category_id == category_id:
            rule.category_id = target_id
    for operation in diary._objects(session, SpendingOperation):
        if operation.decision_category_id == category_id:
            operation.decision_category_id = target_id
    session.flush()
    session.delete(source)
    session.flush()
    return dict(id=target.id, name=target.name, expense_type=target.expense_type)
