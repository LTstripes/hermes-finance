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


def default_classification(operation, narrative, kind, amount):
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
    if op in {"внутренний перевод", "internal transfer"}:
        return "internal_transfer"
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
    if re.search(r"\bнкд\b", text):
        return "unknown"
    if pattern == "coupon_paid_candidate":
        return "coupon"
    if "ндфл" in text:
        return "tax"
    if any(word in text for word in ("комисси", "тариф", "commission")):
        return "fee"
    if any(word in text for word in ("погашение купона", "купон", "coupon")):
        return "coupon"
    if "дивиденд" in text or "dividend" in text:
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


def persist_money_classifications(session, intake_id, document):
    """Called inside the save transaction, after immutable observations exist.

    Existing rows, especially confirmed user choices, are never overwritten.
    A re-save of a legacy intake may fill missing rows from its exact original.
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
    existing = set(
        session.scalars(
            select(SourceMoneyClassification.source_reference).where(
                SourceMoneyClassification.intake_id == intake_id
            )
        )
    )
    narratives = list(_narratives(document))
    if len(observations) != len(narratives):
        raise MyBrokerError("source_intake_parser_revision_changed")
    now = datetime.now(UTC)
    for observation, (operation, narrative, _) in zip(observations, narratives, strict=True):
        row = json.loads(observation.facts_json)
        reference = source_reference(intake_id, row)
        if reference in existing:
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
                classification=default_classification(
                    operation, narrative, row.get("kind"), row["amount"]
                ),
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
