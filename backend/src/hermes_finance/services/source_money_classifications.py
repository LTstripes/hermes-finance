"""Capture original narratives once; never grant financial receipt authority."""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime
from decimal import Decimal, localcontext

from sqlalchemy import select

from hermes_finance.domain.source_money_classifications import (
    NARRATIVE_MAX_LENGTH,
    OPERATION_MAX_LENGTH,
)
from hermes_finance.persistence import SourceIntakeObservation, SourceMoneyClassification
from hermes_finance.services.mybroker_money_candidates import _narratives, _pattern
from hermes_finance.statement_import.money import normalize_currency
from hermes_finance.statement_import.mybroker import MyBrokerError, digest


def source_reference(intake_id, row):
    return f"money:{intake_id}:money:{row['ordinal']}:{digest(row)}"


def _is_verbal_nkd(text):
    return (
        re.search(r"\bнакопленн[а-яё]*\s+купонн[а-яё]*\s+доход[а-яё]*\b", text.casefold())
        is not None
    )


def _is_nkd(text):
    return re.search(r"\bнкд\b", text.casefold()) is not None or _is_verbal_nkd(text)


def is_broker_transfer(operation, narrative):
    op = operation.casefold().strip()
    return op in {"внутренний перевод", "internal transfer"} or (
        op == "перевод" and "внутри брокера" in narrative.casefold()
    )


def transfer_classification(operation, narrative, amount, *, source_account, selected_accounts):
    """Resolve only explicit directional account operands within the requested scope."""
    text = " ".join(narrative.casefold().replace("ё", "е").split())
    account = r"[0-9]{7}(?:-[0-9]{3})?"
    pair = re.fullmatch(
        rf"(?:перевод )?с(?:о)? (?:счета )?({account}) на (?:счет )?({account})(?: внутри брокера)?",
        text,
    )
    outgoing = re.fullmatch(rf"на (?:другой )?счет ({account})(?: внутри брокера)?", text)
    incoming = re.fullmatch(rf"с(?:о)? (?:другого )?счета ({account})(?: внутри брокера)?", text)
    value = Decimal(amount)
    if source_account is None or not selected_accounts or not value:
        return "unknown"
    if pair:
        sender, recipient = pair.groups()
    elif outgoing and value < 0:
        sender, recipient = source_account, outgoing[1]
    elif incoming and value > 0:
        sender, recipient = incoming[1], source_account
    else:
        return "unknown"
    if sender == recipient or source_account != (sender if value < 0 else recipient):
        return "unknown"
    if sender in selected_accounts and recipient in selected_accounts:
        return "internal_transfer"
    if sender in selected_accounts and recipient not in selected_accounts and value < 0:
        return "external_withdrawal"
    if recipient in selected_accounts and sender not in selected_accounts and value > 0:
        return "external_deposit"
    return "unknown"


def default_classification(
    operation, narrative, kind, amount, *, source_account=None, selected_accounts=None
):
    # A settlement label alone cannot prove a verbal NKD purchase link.
    if kind in {"commission", "settlement"} and _is_verbal_nkd(f"{operation} {narrative}"):
        return "unknown"
    # Parsed trade/commission types and explicit cash directions precede income words.
    if kind == "commission":
        return "fee"
    if kind == "settlement":
        return "trade_settlement"
    op = operation.casefold().strip()
    text = f"{operation} {narrative}".casefold()
    if op == "внесено/выведено по распоряжению клиента":
        return "external_deposit" if Decimal(amount) > 0 else "external_withdrawal"
    if op == "внесено по распоряжению клиента":
        return "external_deposit"
    if op == "выведено по распоряжению клиента":
        return "external_withdrawal"
    if re.match(r"^(?:вывод|выведено|withdrawal)(?:\b|$)", op):
        return "external_withdrawal"
    if re.match(r"^(?:пополнение|внесено|deposit)(?:\b|$)", op):
        return "external_deposit"
    if is_broker_transfer(operation, narrative):
        return transfer_classification(
            operation,
            narrative,
            amount,
            source_account=source_account,
            selected_accounts=selected_accounts,
        )
    if op == "перевод" and re.fullmatch(r"в АО [^\r\n]+", narrative):
        return "external_withdrawal"
    # Bank words must accompany a direction; arbitrary transfers stay unknown.
    for value in (op, narrative.casefold().strip()):
        if re.fullmatch(r"(?:перевод )?из .+банк.*", value) or value == "incoming bank transfer":
            return "external_deposit"
        if re.fullmatch(r"(?:перевод )?в .+банк.*", value) or value == "outgoing bank transfer":
            return "external_withdrawal"
    pattern = _pattern(operation, narrative)
    if pattern == "account_cash_in_candidate":
        return "external_deposit"
    # Accrued interest on a trade is settlement cash, never coupon income.
    if re.search(r"\bнкд по сделке\b", text):
        return "trade_settlement"
    if "расчеты по сделке" in text or "расчёты по сделке" in text or "deal settlement" in text:
        return "trade_settlement"
    if _is_nkd(text):
        return "unknown"
    if pattern == "coupon_paid_candidate":
        return "coupon" if Decimal(amount) >= 0 else "unknown"
    if "ндфл" in text:
        return "tax"
    if any(word in text for word in ("комисси", "тариф", "commission")):
        return "fee"
    # An income word inside an unsupported operation is not income evidence.
    # In particular, a typo in a withdrawal must not become a negative dividend.
    if Decimal(amount) >= 0:
        if re.fullmatch(r"купон(?:ы|ный доход)?|погашение купона|coupon(?: payment)?", op) or (
            op == "перевод" and re.fullmatch(r"погашение купона [^\r\n]+", narrative.casefold())
        ):
            return "coupon"
        if re.fullmatch(r"(?:выплата |зачисление )?дивиденд(?:ы|ов)?|dividends?(?: payment)?", op):
            return "dividend"
    return "unknown"


def _amount_kopecks(amount):
    with localcontext() as context:
        context.prec = 100
        value = Decimal(amount) * 100
        if value != value.to_integral_value() or not -(2**63) <= value <= 2**63 - 1:
            return None
        return int(value)


def _bounded_text(value, limit):
    if len(value) <= limit:
        return value
    # Keep distinct long narratives distinct for overlap deduplication.
    suffix = f"…[{digest(value)}]"
    return value[: limit - len(suffix)] + suffix


def _linked_purchase_nkd(row, operation, narrative, trades):
    """Require a native purchase ID in the text and exact account/date/NKD match."""
    if row.get("kind") == "commission":
        return False
    text = f"{operation} {narrative}"
    matches = []
    for trade in trades:
        core = trade["core"]
        if (
            trade.get("identity")
            and trade["state"] == "settled"
            and not trade.get("repo_observed")
            and core["source_account"] == row["source_account"]
            and trade.get("settlement_date") == row["date"]
            and normalize_currency(core["currency"]) == normalize_currency(row["currency"])
            and Decimal(core["quantity"]) > 0
            and Decimal(row["amount"]) < 0
            and trade.get("accrued_interest") is not None
            and Decimal(trade["accrued_interest"]) == -Decimal(row["amount"])
            and any(
                re.search(r"(?<!\w)" + re.escape(identity) + r"(?!\w)", text)
                for identity in trade["ids"]
            )
        ):
            matches.append(trade)
    return len(matches) == 1


def persist_money_classifications(session, intake_id, document):
    """Called inside the save transaction, after immutable observations exist.

    Only assumed defaults are re-evaluated on a new save command.
    User choices and confirmed defaults retain their classification and metadata.
    """
    session.flush()
    observations = list(
        session.scalars(
            select(SourceIntakeObservation)
            .where(
                SourceIntakeObservation.original_id == intake_id,
                SourceIntakeObservation.section == "money",
                SourceIntakeObservation.generation == 1,
            )
            .order_by(SourceIntakeObservation.ordinal)
        )
    )
    existing = {
        row.source_reference: row
        for row in session.scalars(
            select(SourceMoneyClassification).where(
                SourceMoneyClassification.intake_id == intake_id
            )
        )
    }
    trades = [
        json.loads(observation.facts_json)
        for observation in session.scalars(
            select(SourceIntakeObservation).where(
                SourceIntakeObservation.original_id == intake_id,
                SourceIntakeObservation.section == "trades",
                SourceIntakeObservation.generation == 1,
            )
        )
    ]
    narratives = list(_narratives(document))
    if len(observations) != len(narratives):
        raise MyBrokerError("source_intake_parser_revision_changed")
    now = datetime.now(UTC)
    for observation, (operation, narrative, _) in zip(observations, narratives, strict=True):
        row = json.loads(observation.facts_json)
        reference = source_reference(intake_id, row)
        previous = existing.get(reference)
        if previous is not None and (previous.origin, previous.status) != (
            "default_rule",
            "assumed",
        ):
            continue
        classification = default_classification(
            operation,
            narrative,
            row.get("kind"),
            row["amount"],
            source_account=row["source_account"],
            selected_accounts={row["source_account"]},
        )
        if classification == "unknown" and _is_nkd(f"{operation} {narrative}"):
            if _linked_purchase_nkd(row, operation, narrative, trades):
                classification = "trade_settlement"
        if previous is not None:
            if previous.classification != classification:
                previous.classification = classification
                previous.updated_at = now
            continue
        session.add(
            SourceMoneyClassification(
                intake_id=intake_id,
                observation_id=observation.id,
                source_reference=reference,
                date=date.fromisoformat(row["date"]),
                amount_kopecks=_amount_kopecks(row["amount"]),
                currency=row["currency"],
                operation=_bounded_text(operation, OPERATION_MAX_LENGTH),
                narrative=_bounded_text(narrative, NARRATIVE_MAX_LENGTH),
                classification=classification,
                origin="default_rule",
                status="assumed",
                created_at=now,
                updated_at=now,
            )
        )


def classification_dict(row):
    return {
        "intake_id": row.intake_id,
        "source_reference": row.source_reference,
        "date": row.date,
        "amount_kopecks": row.amount_kopecks,
        "currency": row.currency,
        "operation": _bounded_text(row.operation, OPERATION_MAX_LENGTH),
        "narrative": _bounded_text(row.narrative, NARRATIVE_MAX_LENGTH),
        "classification": row.classification,
        "origin": row.origin,
        "status": row.status,
        "created_at": row.created_at.replace(tzinfo=UTC),
        "updated_at": row.updated_at.replace(tzinfo=UTC),
    }


def list_classifications(session, intake_id):
    return [
        classification_dict(row)
        for row in session.scalars(
            select(SourceMoneyClassification)
            .where(SourceMoneyClassification.intake_id == intake_id)
            .order_by(SourceMoneyClassification.id)
        )
    ]


def choose_classification(session, intake_id, reference, classification):
    from typing import get_args

    from hermes_finance.domain.source_money_classifications import MoneyClassification
    from hermes_finance.persistence import ReportingMonth, SourceIntakeOriginal
    from hermes_finance.services import source_intake

    if classification not in get_args(MoneyClassification):
        raise MyBrokerError("money_classification_invalid")
    source_intake._reserve(session)
    try:
        original = session.get(SourceIntakeOriginal, intake_id, populate_existing=True)
        if original is None:
            raise MyBrokerError("source_intake_not_found")
        view = source_intake._view(session, original)
        month_id = view["state"]["reporting_month_id"]
        if month_id is not None:
            month = session.get(ReportingMonth, month_id, populate_existing=True)
            if month is None or month.status != "draft":
                raise MyBrokerError("source_intake_editable_period_required")
        row = session.scalar(
            select(SourceMoneyClassification).where(
                SourceMoneyClassification.intake_id == intake_id,
                SourceMoneyClassification.source_reference == reference,
            )
        )
        if row is None:
            raise MyBrokerError("money_classification_not_found")
        if classification in {"external_deposit", "external_withdrawal"} and (
            normalize_currency(row.currency) != "RUB"
            or row.amount_kopecks is None
            or row.amount_kopecks == 0
            or (row.amount_kopecks > 0) != (classification == "external_deposit")
        ):
            raise MyBrokerError("invalid_external_flow")
        if (row.classification, row.origin, row.status) != (
            classification,
            "user_choice",
            "confirmed",
        ):
            row.classification = classification
            row.origin = "user_choice"
            row.status = "confirmed"
            row.updated_at = datetime.now(UTC)
        session.flush()
        result = classification_dict(row)
        session.commit()
        return result
    except BaseException:
        session.rollback()
        raise
