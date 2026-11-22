"""Owner-confirmed savings movements, scoped to a posting month and exact bank account."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from collections import Counter, defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.alfa_csv import AlfaRow, parse_alfa_csv
from hermes_finance.database import coherent_read_snapshot
from hermes_finance.domain import PercentageRate, RubleAmount
from hermes_finance.domain.deposits import calculate_deposit_expected_monthly_interest_kopecks
from hermes_finance.persistence import Account, AlfaSavingsLink, DepositSnapshot, ReportingMonth
from hermes_finance.services._guard import require_editable_reporting_month
from hermes_finance.services.deposits import create_deposit_snapshot, update_deposit_snapshot
from hermes_finance.services.reporting_months import get_reporting_month

_TOKEN_KEY = secrets.token_bytes(32)
_MAX_STORED = 2**63 - 1
_INTEREST = re.compile(
    r"выплата процентов на ежедневный остаток по сч[её]ту за "
    r"(0[1-9]|1[0-2])\.(\d{4})"
    r"(?: по итоговой ставке (\d{1,3}(?:[,.]\d{1,2})?)\s*% годовых)?[.]?",
    re.IGNORECASE,
)


class StaleSavingsPreview(ValueError):
    """The file, selected identity, restore epoch or month evidence changed."""


def _money(value: int | None) -> str | None:
    return None if value is None else RubleAmount(value).to_api()


def _values(snapshot: DepositSnapshot | None) -> dict:
    return {
        "balance": _money(snapshot.balance_kopecks) if snapshot else None,
        "actual_interest_received": _money(snapshot.actual_interest_received_kopecks)
        if snapshot
        else None,
        "annual_rate": PercentageRate(snapshot.annual_rate_basis_points).to_api()
        if snapshot
        else None,
    }


def _interest(rows: list[AlfaRow], start: date) -> tuple[int | None, int | None]:
    total, rates = 0, set()
    for row in rows:
        fields = row.fields
        category = fields["category"].strip().casefold()
        descriptions = [" ".join(fields[k].split()) for k in ("merchant", "comment")]
        looks_like_interest = any("выплата процент" in s.casefold() for s in descriptions)
        if not looks_like_interest and not (
            category == "накопления" and row.direction == "Пополнение"
        ):
            continue
        matches = [m for s in descriptions if (m := _INTEREST.fullmatch(s))]
        if (
            category != "накопления"
            or row.direction != "Пополнение"
            or not matches
            or len({m.groups() for m in matches}) != 1
        ):
            return None, None
        month, year, rate = matches[0].groups()
        total += row.amount_kopecks
        rate_applies = rate and (int(year), int(month)) == (start.year, start.month)
        rates.add(
            PercentageRate.from_api(rate.replace(",", ".")).basis_points if rate_applies else None
        )
    return total or None, next(iter(rates)) if len(rates) == 1 else None


def _groups(csv: str) -> dict[str, list[AlfaRow]]:
    payload = csv.encode("utf-8")
    if len(payload) > 8 * 1024 * 1024:
        raise ValueError("Файл превышает 8 МБ.")
    parsed = parse_alfa_csv(payload)
    if parsed.errors:
        raise ValueError(
            f"Проверьте строку {parsed.errors[0]['line']} в выписке. Файл не применён."
        )
    if not parsed.rows:
        raise ValueError("В выписке нет операций.")
    groups = defaultdict(list)
    for row in parsed.rows:
        number = row.fields["accountNumber"].strip()
        # A digest of the entire number is sufficient for repeat local matching.
        key = hashlib.sha256(number.encode()).hexdigest()
        groups[key].append(row)
    return groups


def _snapshots(session: Session, month_id: int | None) -> dict[int, list[DepositSnapshot]]:
    result = defaultdict(list)
    if month_id:
        for row in session.scalars(
            select(DepositSnapshot).where(DepositSnapshot.reporting_month_id == month_id)
        ):
            result[row.account_id].append(row)
    return result


def _proposal(source_rows, start, end, source_key, account_id, mapped):
    booked = [r for r in source_rows if r.transaction_date and start <= r.transaction_date <= end]
    dates = [r.transaction_date for r in booked]
    number = source_rows[0].fields["accountNumber"].strip()
    return {
        "source_key": source_key,
        "label": "Счёт ··" + number[-4:],
        "first_line": source_rows[0].line,
        "count": len(booked),
        "first_date": min(dates) if dates else None,
        "last_date": max(dates) if dates else None,
        "account_id": account_id,
        "mapped": mapped,
        "snapshot_id": None,
        "current": _values(None),
        "proposed": _values(None),
        "difference": None,
        "messages": [],
        "token": None,
    }, booked


def _prepare_row(row, booked, source_rows, current, previous, month, full_month, conflict):
    messages = row["messages"]
    if current:
        row["current"] = _values(current)
        row["snapshot_id"] = current.id
    if not re.fullmatch(r"[0-9]{20}", source_rows[0].fields["accountNumber"].strip()):
        messages.append("Для привязки нужен полный номер банковского счёта.")
    if not row["account_id"]:
        messages.append("Выберите соответствующий накопительный счёт в Finance.")
    if conflict:
        messages.append("Привязка неоднозначна. Проверьте выбранный счёт и его снимки.")
    if not booked:
        messages.append("Нет проведённых операций в выбранном месяце.")
    if any(r.transaction_date is None for r in source_rows):
        messages.append("Есть строки без даты проводки. Проверьте выписку в банке.")
    if any(r.currency not in {"RUR", "RUB"} or r.status not in {"", "Выполнен"} for r in booked):
        messages.append("Есть неподдерживаемая валюта или статус операции.")
    if not full_month:
        messages.append("Подтвердите, что выгрузка содержит все движения за календарный месяц.")
    if month.status != "draft":
        messages.append("Месяц закрыт. Для записи его нужно открыть.")
    if messages:
        return False
    delta = sum(
        r.amount_kopecks if r.direction == "Пополнение" else -r.amount_kopecks for r in booked
    )
    interest, rate = _interest(booked, month.period_start)
    balance = previous.balance_kopecks + delta if previous else None
    if balance is None:
        messages.append("Нет однозначного остатка предыдущего месяца. Баланс остаётся ручным.")
    if interest is None:
        messages.append("Сумма процентов не подтверждена. Текущее значение сохраняется.")
    if not current and (not previous or balance is None or interest is None):
        messages.append("Для нового снимка недостаточно данных. Заполните вклад вручную.")
        return False
    reference = current or previous
    next_balance = reference.balance_kopecks if balance is None else balance
    next_rate = reference.annual_rate_basis_points if rate is None else rate
    if (
        not 0 <= next_balance <= _MAX_STORED
        or (interest or 0) > _MAX_STORED
        or calculate_deposit_expected_monthly_interest_kopecks(next_balance, next_rate)
        > _MAX_STORED
    ):
        messages.append("Расчёт выходит за допустимые границы. Проверьте остаток и движения.")
        return False
    row["proposed"] = {
        "balance": _money(balance),
        "actual_interest_received": _money(interest),
        "annual_rate": PercentageRate(rate).to_api()
        if rate is not None and rate != reference.annual_rate_basis_points
        else None,
    }
    if current and balance is not None:
        row["difference"] = _money(balance - current.balance_kopecks)
    return any(v is not None for v in row["proposed"].values())


def _build(session, month, csv, full_month, bindings):
    groups = _groups(csv)
    if set(bindings) - groups.keys():
        raise ValueError("Выбранный счёт отсутствует в этой выписке.")
    last_day = month.period_start.replace(day=1) - timedelta(days=1)
    prior_month = session.scalar(
        select(ReportingMonth).where(
            ReportingMonth.year == last_day.year, ReportingMonth.month == last_day.month
        )
    )
    previous_rows = _snapshots(session, prior_month.id if prior_month else None)
    current_rows = _snapshots(session, month.id)
    possible_accounts = {
        account_id
        for snapshots in (previous_rows, current_rows)
        for account_id, items in snapshots.items()
        if any(s.deposit_type == "savings" for s in items)
    }
    accounts = session.scalars(
        select(Account).where(Account.id.in_(possible_accounts)).order_by(Account.name, Account.id)
    ).all()
    links = {m.source_key: m.account_id for m in session.scalars(select(AlfaSavingsLink))}
    target_owners = {v: k for k, v in links.items()}
    selected = {key: bindings.get(key, links.get(key)) for key in groups}
    selected_counts = Counter(selected.values())
    csv_hash = hashlib.sha256(csv.encode()).hexdigest()
    result = []
    for key, items in groups.items():
        account_id = selected[key]
        current_items = current_rows.get(account_id, [])
        previous_items = previous_rows.get(account_id, [])
        current = (
            current_items[0]
            if len(current_items) == 1 and current_items[0].deposit_type == "savings"
            else None
        )
        previous = (
            previous_items[0]
            if len(previous_items) == 1 and previous_items[0].deposit_type == "savings"
            else None
        )
        row, booked = _proposal(
            items,
            month.period_start,
            month.period_end,
            key,
            account_id,
            key in links and account_id == links[key],
        )
        result.append(row)
        conflict = account_id is not None and (
            account_id not in possible_accounts
            or selected_counts[account_id] > 1
            or target_owners.get(account_id, key) != key
            or (current_items and not current)
        )
        if not _prepare_row(row, booked, items, current, previous, month, full_month, conflict):
            continue
        if (
            row["mapped"]
            and current
            and all(v is None or row["current"][k] == v for k, v in row["proposed"].items())
        ):
            row["messages"].append("Значения уже совпадают с выпиской.")
            continue
        state = [
            session.info.get("source_intake_epoch"),
            month.id,
            month.updated_at.isoformat(),
            csv_hash,
            key,
            account_id,
            links.get(key),
            row["current"],
            row["proposed"],
            [
                (
                    s.id,
                    s.updated_at.isoformat(),
                    s.name,
                    s.deposit_type,
                    s.balance_kopecks,
                    s.annual_rate_basis_points,
                )
                for s in [*previous_items, *current_items]
            ],
        ]
        row["token"] = hmac.new(
            _TOKEN_KEY, json.dumps(state, sort_keys=True).encode(), "sha256"
        ).hexdigest()
    return {
        "month_id": month.id,
        "period_start": month.period_start,
        "period_end": month.period_end,
        "accounts": [{"id": a.id, "name": a.name} for a in accounts],
        "rows": result,
    }


def preview(session: Session, *, month_id: int, csv: str, full_month: bool, bindings: dict) -> dict:
    with coherent_read_snapshot(session):
        return _build(session, get_reporting_month(session, month_id), csv, full_month, bindings)


def apply(
    session: Session,
    *,
    month_id: int,
    csv: str,
    full_month: bool,
    bindings: dict,
    source_key: str,
    token: str,
) -> DepositSnapshot:
    month = require_editable_reporting_month(session, month_id)
    proposal = _build(session, month, csv, full_month, bindings)
    row = next((r for r in proposal["rows"] if r["source_key"] == source_key), None)
    if not row or not row["token"] or not hmac.compare_digest(row["token"], token):
        raise StaleSavingsPreview("Предпросмотр изменился. Проверьте выписку и суммы заново.")
    link = session.get(AlfaSavingsLink, source_key)
    if link is None:
        session.add(AlfaSavingsLink(source_key=source_key, account_id=row["account_id"]))
    else:
        link.account_id = row["account_id"]
    values = {k: v for k, v in row["proposed"].items() if v is not None}
    if row["snapshot_id"] is not None:
        snapshot = session.get(DepositSnapshot, row["snapshot_id"])
        if all(row["current"][k] == v for k, v in values.items()):
            session.commit()
            return snapshot
        return update_deposit_snapshot(
            session, snapshot.id, expected_updated_at=snapshot.updated_at, **values
        )
    last_day = month.period_start.replace(day=1) - timedelta(days=1)
    prior = session.scalars(
        select(DepositSnapshot)
        .join(ReportingMonth)
        .where(
            ReportingMonth.year == last_day.year,
            ReportingMonth.month == last_day.month,
            DepositSnapshot.account_id == row["account_id"],
        )
    ).one()
    values.setdefault("annual_rate", PercentageRate(prior.annual_rate_basis_points).to_api())
    return create_deposit_snapshot(
        session,
        reporting_month_id=month.id,
        account_id=prior.account_id,
        name=prior.name,
        deposit_type=prior.deposit_type,
        **values,
    )
