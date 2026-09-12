"""Owner-managed, transfer-specific reconciliation evidence.

This module stores only explicit canonical explanations.  It never matches a
fee or tax by amount/date/text and never allocates one evidence item between
multiple transfers.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal, DecimalException

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.domain import (
    ExternalTransferReconciliationKind,
    RubleAmount,
)
from hermes_finance.persistence import (
    ExternalFlow,
    ExternalTransferLink,
    ExternalTransferReconciliationEvidence,
)
from hermes_finance.services._guard import require_editable_child_month


class TransferReconciliationEvidenceNotFoundError(LookupError):
    pass


def _normalize_text(value: str, *, field: str, max_length: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    if len(normalized) > max_length:
        raise ValueError(f"{field} must not exceed {max_length} characters")
    return normalized


def _normalize_currency(currency: str) -> str:
    normalized = currency.strip().upper()
    if len(normalized) != 3 or not normalized.isalpha():
        raise ValueError("currency must be a three-letter code")
    return normalized


def _normalize_exact_amount(amount: RubleAmount | str) -> int:
    if isinstance(amount, str):
        try:
            decimal_amount = Decimal(amount)
        except DecimalException as error:
            raise ValueError("amount must be a finite decimal string") from error
        if not decimal_amount.is_finite():
            raise ValueError("amount must be finite")
        scaled = decimal_amount * Decimal(100)
        if scaled != scaled.to_integral_value():
            raise ValueError("amount must have no more than two decimal places")
        amount = RubleAmount.from_decimal(decimal_amount)
    if not isinstance(amount, RubleAmount):
        raise TypeError("amount must be RubleAmount or decimal string")
    if amount.kopecks < 0:
        raise ValueError("amount must not be negative")
    return amount.kopecks


def _coerce_kind(
    kind: ExternalTransferReconciliationKind | str,
) -> ExternalTransferReconciliationKind:
    try:
        return ExternalTransferReconciliationKind(kind)
    except ValueError as error:
        raise ValueError(f"unsupported transfer reconciliation kind: {kind!r}") from error


def _require_evidence(
    session: Session,
    evidence_id: int,
) -> ExternalTransferReconciliationEvidence:
    evidence = session.get(ExternalTransferReconciliationEvidence, evidence_id)
    if evidence is None:
        raise TransferReconciliationEvidenceNotFoundError(
            f"transfer reconciliation evidence {evidence_id} was not found"
        )
    return evidence


def _transfer_legs(session: Session, transfer_link_id: int) -> list[ExternalFlow]:
    return list(
        session.scalars(
            select(ExternalFlow)
            .where(ExternalFlow.transfer_link_id == transfer_link_id)
            .order_by(ExternalFlow.id)
        )
    )


def list_transfer_reconciliation_evidence(
    session: Session,
    *,
    transfer_link_id: int | None = None,
) -> list[ExternalTransferReconciliationEvidence]:
    statement = select(ExternalTransferReconciliationEvidence)
    if transfer_link_id is not None:
        statement = statement.where(
            ExternalTransferReconciliationEvidence.transfer_link_id == transfer_link_id
        )
    return list(
        session.scalars(
            statement.order_by(
                ExternalTransferReconciliationEvidence.transfer_link_id,
                ExternalTransferReconciliationEvidence.id,
            )
        )
    )


def create_transfer_reconciliation_evidence(
    session: Session,
    *,
    transfer_link_id: int,
    kind: ExternalTransferReconciliationKind | str,
    amount: RubleAmount | str,
    currency: str,
    source: str,
    evidence_reference: str,
    notes: str | None = None,
) -> ExternalTransferReconciliationEvidence:
    """Attach one exact canonical evidence item to exactly one transfer link."""

    link = session.get(ExternalTransferLink, transfer_link_id)
    if link is None:
        raise ValueError(f"external transfer link {transfer_link_id} was not found")
    legs = _transfer_legs(session, link.id)
    if not legs:
        raise ValueError("transfer reconciliation evidence requires at least one transfer leg")
    for leg in legs:
        require_editable_child_month(session, leg)

    evidence = ExternalTransferReconciliationEvidence(
        transfer_link_id=link.id,
        kind=_coerce_kind(kind).value,
        amount_kopecks=_normalize_exact_amount(amount),
        currency=_normalize_currency(currency),
        source=_normalize_text(source, field="source", max_length=64),
        evidence_reference=_normalize_text(
            evidence_reference,
            field="evidence_reference",
            max_length=128,
        ),
        notes=notes,
    )
    session.add(evidence)
    session.commit()
    session.refresh(evidence)
    return evidence


def delete_transfer_reconciliation_evidence(session: Session, evidence_id: int) -> None:
    evidence = _require_evidence(session, evidence_id)
    legs = _transfer_legs(session, evidence.transfer_link_id)
    for leg in legs:
        require_editable_child_month(session, leg)
    session.delete(evidence)
    session.commit()


def transfer_reconciliation_evidence(
    session: Session,
    transfer_link_id: int,
) -> tuple[ExternalTransferReconciliationEvidence, ...]:
    return tuple(
        list_transfer_reconciliation_evidence(
            session,
            transfer_link_id=transfer_link_id,
        )
    )


def iter_transfer_reconciliation_evidence(
    session: Session,
    transfer_link_ids: Iterable[int],
) -> dict[int, tuple[ExternalTransferReconciliationEvidence, ...]]:
    ids = tuple(sorted(set(transfer_link_ids)))
    if not ids:
        return {}
    rows = session.scalars(
        select(ExternalTransferReconciliationEvidence)
        .where(ExternalTransferReconciliationEvidence.transfer_link_id.in_(ids))
        .order_by(
            ExternalTransferReconciliationEvidence.transfer_link_id,
            ExternalTransferReconciliationEvidence.id,
        )
    )
    result: dict[int, list[ExternalTransferReconciliationEvidence]] = {
        transfer_link_id: [] for transfer_link_id in ids
    }
    for row in rows:
        result[row.transfer_link_id].append(row)
    return {transfer_link_id: tuple(items) for transfer_link_id, items in result.items()}


# Short aliases keep the transfer terminology discoverable to API/task callers.
create_reconciliation_evidence = create_transfer_reconciliation_evidence
list_reconciliation_evidence = list_transfer_reconciliation_evidence
delete_reconciliation_evidence = delete_transfer_reconciliation_evidence
