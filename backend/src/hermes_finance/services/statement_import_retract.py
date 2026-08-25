"""Owner correction: retract a wrongly applied statement-backed payout.

Statement-specific and atomic. Generic investment-flow DELETE stays
non-cascading so provenance is not silently destroyed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from hermes_finance.persistence import AppliedStatementEvent, InvestmentCashFlow
from hermes_finance.services._guard import require_editable_child_month
from hermes_finance.services.applied_statement_events import (
    StatementEventStatus,
    StatementLinkMode,
    StatementRevisionKind,
    _append_revision_row,
    get_applied_statement_event,
    get_applied_statement_event_by_cash_flow,
    list_applied_statement_event_revisions,
)
from hermes_finance.services.investment_cash_flows import get_investment_cash_flow
from hermes_finance.services.reporting_months import (
    ClosedReportingMonthError,
    ReportingMonthNotFoundError,
)


class StatementRetractError(Exception):
    """Typed owner-correction conflict that must not look like generic integrity."""

    def __init__(self, code: str, message: str, *, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class StatementRetractResult:
    applied_statement_event_id: int
    link_mode: str
    cash_flow_deleted: bool
    investment_cash_flow_id: int | None
    revision_id: int


def _timestamp(value: datetime | None) -> datetime:
    accepted = value or datetime.now(UTC)
    if not isinstance(accepted, datetime):
        raise TypeError("retracted_at must be a datetime")
    if accepted.tzinfo is None:
        return accepted.replace(tzinfo=UTC)
    return accepted


def _stage_retract_event(
    session: Session,
    event: AppliedStatementEvent,
    *,
    retracted_at: datetime,
) -> int:
    revisions = list_applied_statement_event_revisions(session, event.id)
    if not revisions:
        raise StatementRetractError(
            "incompatible_provenance",
            "applied statement event has no revision history",
        )
    accepted = revisions[-1]
    if accepted.revision_kind == StatementRevisionKind.RETRACT.value:
        raise StatementRetractError(
            "incompatible_provenance",
            "active statement event already ends with a retract revision",
        )
    event.status = StatementEventStatus.RETRACTED.value
    event.investment_cash_flow_id = None
    event.retracted_at = retracted_at
    event.updated_at = retracted_at
    tax_rate = Decimal(accepted.tax_rate) if accepted.tax_rate is not None else None
    revision = _append_revision_row(
        session,
        event=event,
        revision_kind=StatementRevisionKind.RETRACT,
        document_sha256=accepted.document_sha256,
        natural_identity=accepted.natural_identity,
        material_fingerprint=accepted.material_fingerprint,
        account_id=accepted.account_id,
        instrument_id=accepted.instrument_id,
        event_kind=accepted.event_kind,
        isin=accepted.isin,
        record_date=accepted.record_date,
        event_date=accepted.event_date,
        quantity=Decimal(accepted.quantity),
        per_unit=Decimal(accepted.per_unit),
        gross_amount_kopecks=accepted.gross_amount_kopecks,
        gross_currency=accepted.gross_currency,
        tax_available=accepted.tax_available,
        tax_amount_kopecks=accepted.tax_amount_kopecks,
        tax_rate=tax_rate,
        net_amount_kopecks=accepted.net_amount_kopecks,
        net_currency=accepted.net_currency,
        applied_at=retracted_at,
    )
    session.flush()
    return revision.id


def retract_applied_statement_event(
    session: Session,
    event_id: int,
    *,
    retracted_at: datetime | None = None,
) -> StatementRetractResult:
    event = get_applied_statement_event(session, event_id)
    if event.status == StatementEventStatus.RETRACTED.value:
        raise StatementRetractError(
            "already_retracted",
            "applied statement event is already retracted",
        )
    if event.status != StatementEventStatus.ACTIVE.value:
        raise StatementRetractError(
            "incompatible_provenance",
            "applied statement event status is not retractable",
        )
    try:
        link_mode = StatementLinkMode(event.link_mode)
    except ValueError as error:
        raise StatementRetractError(
            "incompatible_provenance",
            "applied statement event has unknown link mode",
        ) from error
    if event.investment_cash_flow_id is None:
        raise StatementRetractError(
            "incompatible_provenance",
            "active statement event is missing its cash flow",
        )
    flow = session.get(InvestmentCashFlow, event.investment_cash_flow_id)
    if flow is None:
        raise StatementRetractError(
            "incompatible_provenance",
            "linked investment cash flow is missing",
        )
    try:
        require_editable_child_month(session, flow)
    except ClosedReportingMonthError as error:
        raise StatementRetractError("closed_month", str(error)) from error
    except ReportingMonthNotFoundError as error:
        raise StatementRetractError("incompatible_provenance", str(error)) from error

    accepted_at = _timestamp(retracted_at)
    remaining_flow_id = None if link_mode is StatementLinkMode.STATEMENT_CREATED else flow.id
    cash_flow_deleted = link_mode is StatementLinkMode.STATEMENT_CREATED
    try:
        revision_id = _stage_retract_event(session, event, retracted_at=accepted_at)
        if cash_flow_deleted:
            session.delete(flow)
            session.flush()
        session.commit()
    except Exception:
        session.rollback()
        raise
    return StatementRetractResult(
        applied_statement_event_id=event.id,
        link_mode=link_mode.value,
        cash_flow_deleted=cash_flow_deleted,
        investment_cash_flow_id=remaining_flow_id,
        revision_id=revision_id,
    )


def retract_statement_backed_cash_flow(
    session: Session,
    flow_id: int,
    *,
    retracted_at: datetime | None = None,
) -> StatementRetractResult:
    get_investment_cash_flow(session, flow_id)
    event = get_applied_statement_event_by_cash_flow(session, flow_id)
    if event is None:
        raise StatementRetractError(
            "not_statement_backed",
            "investment cash flow is not statement-backed",
        )
    return retract_applied_statement_event(session, event.id, retracted_at=retracted_at)
