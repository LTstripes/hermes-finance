"""Read-only preparation for owner-selected statement apply.

This service deliberately returns only normalized Hermes and financial evidence.
It does not retain provider account references, raw PDF bytes, or extracted text.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.persistence import Account, Instrument, InvestmentCashFlow
from hermes_finance.services.applied_statement_events import (
    get_applied_statement_event_by_identity,
    list_linked_investment_cash_flow_ids,
    load_prior_event_views,
)
from hermes_finance.services.reporting_months import get_reporting_month_by_period
from hermes_finance.statement_import.dto import (
    ALFA_DEPOSITORY_INCOME_PROVIDER,
    AccountMappingInput,
    DuplicateClass,
    HermesAccountView,
    HermesInstrumentView,
    InstrumentMappingInput,
    PreviewRow,
    ReportStatus,
    RowStatus,
)
from hermes_finance.statement_import.preview import preview_income_report


@dataclass(frozen=True, slots=True)
class StatementCashFlowCandidate:
    """Sanitized current cash-flow evidence for an explicit owner choice."""

    investment_cash_flow_id: int
    reporting_month_id: int
    account_id: int
    instrument_id: int | None
    flow_type: str
    event_date: date
    gross_amount_kopecks: int
    tax_amount_kopecks: int
    commission_amount_kopecks: int
    net_amount_kopecks: int
    currency: str
    source: str


@dataclass(frozen=True, slots=True)
class StatementApplyPreparationRow:
    """Sanitized reviewed evidence for one parsed statement row."""

    status: RowStatus
    duplicate_class: DuplicateClass | None
    event_kind: str | None
    expected_hermes_account_id: int | None
    expected_hermes_instrument_id: int | None
    isin: str | None
    record_date: date | None
    event_date: date | None
    quantity: Decimal | None
    per_unit: Decimal | None
    gross_amount: Decimal | None
    gross_currency: str | None
    tax_amount: Decimal | None
    tax_available: bool
    tax_rate: Decimal | None
    net_amount: Decimal | None
    net_currency: str | None
    natural_identity: str | None
    material_fingerprint: str | None
    expected_candidate_ids: tuple[int, ...]
    candidates: tuple[StatementCashFlowCandidate, ...]
    reason: str | None

    def to_apply_selection(
        self,
        *,
        action: object | None = None,
        existing_cash_flow_id: int | None = None,
    ) -> object:
        """Construct the complete apply selection without caller-recreated evidence."""

        from hermes_finance.services.statement_import_apply import StatementApplySelection

        if (
            self.status is not RowStatus.MATCHED
            or self.natural_identity is None
            or self.material_fingerprint is None
            or self.expected_hermes_account_id is None
            or self.expected_hermes_instrument_id is None
        ):
            raise ValueError("only a matched prepared statement row can be selected")
        return StatementApplySelection(
            natural_identity=self.natural_identity,
            material_fingerprint=self.material_fingerprint,
            expected_hermes_account_id=self.expected_hermes_account_id,
            expected_hermes_instrument_id=self.expected_hermes_instrument_id,
            action=action,
            existing_cash_flow_id=existing_cash_flow_id,
            expected_candidate_ids=self.expected_candidate_ids,
        )


@dataclass(frozen=True, slots=True)
class StatementApplyPreparation:
    provider: str
    document_sha256: str
    status: ReportStatus
    rows: tuple[StatementApplyPreparationRow, ...]
    warnings: tuple[str, ...]
    reason: str | None


def find_conservative_cash_flow_candidates(
    session: Session,
    *,
    reporting_month_id: int,
    account_id: int,
    instrument_id: int,
    flow_type: str,
    event_date: date,
) -> tuple[InvestmentCashFlow, ...]:
    """Return the one canonical conservative candidate set, ordered by id."""

    linked = list_linked_investment_cash_flow_ids(session)
    rows = session.scalars(
        select(InvestmentCashFlow)
        .where(
            InvestmentCashFlow.reporting_month_id == reporting_month_id,
            InvestmentCashFlow.account_id == account_id,
            InvestmentCashFlow.instrument_id == instrument_id,
            InvestmentCashFlow.flow_type == flow_type,
            InvestmentCashFlow.event_date == event_date,
        )
        .order_by(InvestmentCashFlow.id)
    )
    return tuple(flow for flow in rows if flow.id not in linked)


def prepare_income_report_apply(
    session: Session,
    *,
    document: bytes,
    account_mappings: tuple[AccountMappingInput, ...],
    instrument_mappings: tuple[InstrumentMappingInput, ...] = (),
) -> StatementApplyPreparation:
    """Build a zero-write, provider-neutral apply-preparation result."""

    with session.no_autoflush:
        preview = preview_income_report(
            document,
            hermes_accounts=_account_views(session),
            hermes_instruments=_instrument_views(session),
            account_mappings=account_mappings,
            instrument_mappings=instrument_mappings,
            prior_events=load_prior_event_views(session),
        )
        rows = tuple(_prepare_row(session, row) for row in preview.rows)
    return StatementApplyPreparation(
        provider=ALFA_DEPOSITORY_INCOME_PROVIDER,
        document_sha256=preview.document_sha256,
        status=preview.status,
        rows=rows,
        warnings=preview.warnings,
        reason=preview.reason,
    )


def _account_views(session: Session) -> tuple[HermesAccountView, ...]:
    accounts = session.scalars(select(Account).order_by(Account.id))
    return tuple(
        HermesAccountView(
            account_id=account.id,
            account_type=account.account_type,
            name=account.name,
        )
        for account in accounts
    )


def _instrument_views(session: Session) -> tuple[HermesInstrumentView, ...]:
    instruments = session.scalars(select(Instrument).order_by(Instrument.id))
    return tuple(
        HermesInstrumentView(
            instrument_id=instrument.id,
            isin=instrument.isin,
            name=instrument.name,
            ticker=instrument.ticker,
        )
        for instrument in instruments
    )


def _prepare_row(session: Session, row: PreviewRow) -> StatementApplyPreparationRow:
    candidates: tuple[InvestmentCashFlow, ...] = ()
    if (
        row.status is RowStatus.MATCHED
        and row.hermes_account_id is not None
        and row.hermes_instrument_id is not None
        and row.event_kind is not None
        and row.event_date is not None
        and row.natural_identity is not None
        and get_applied_statement_event_by_identity(
            session,
            provider=ALFA_DEPOSITORY_INCOME_PROVIDER,
            natural_identity=row.natural_identity,
        )
        is None
    ):
        month = get_reporting_month_by_period(
            session, year=row.event_date.year, month=row.event_date.month
        )
        if month is not None:
            candidates = find_conservative_cash_flow_candidates(
                session,
                reporting_month_id=month.id,
                account_id=row.hermes_account_id,
                instrument_id=row.hermes_instrument_id,
                flow_type=row.event_kind,
                event_date=row.event_date,
            )
    sanitized = tuple(_candidate(flow) for flow in candidates)
    return StatementApplyPreparationRow(
        status=row.status,
        duplicate_class=row.duplicate_class,
        event_kind=row.event_kind,
        expected_hermes_account_id=row.hermes_account_id,
        expected_hermes_instrument_id=row.hermes_instrument_id,
        isin=row.isin,
        record_date=row.record_date,
        event_date=row.event_date,
        quantity=row.quantity,
        per_unit=row.per_unit,
        gross_amount=row.gross_amount,
        gross_currency=row.gross_currency,
        tax_amount=row.tax_amount,
        tax_available=row.tax_available,
        tax_rate=row.tax_rate,
        net_amount=row.net_amount,
        net_currency=row.net_currency,
        natural_identity=row.natural_identity,
        material_fingerprint=row.material_fingerprint,
        expected_candidate_ids=tuple(candidate.investment_cash_flow_id for candidate in sanitized),
        candidates=sanitized,
        reason=row.reason,
    )


def _candidate(flow: InvestmentCashFlow) -> StatementCashFlowCandidate:
    return StatementCashFlowCandidate(
        investment_cash_flow_id=flow.id,
        reporting_month_id=flow.reporting_month_id,
        account_id=flow.account_id,
        instrument_id=flow.instrument_id,
        flow_type=flow.flow_type,
        event_date=flow.event_date,
        gross_amount_kopecks=flow.gross_amount_kopecks,
        tax_amount_kopecks=flow.tax_amount_kopecks,
        commission_amount_kopecks=flow.commission_amount_kopecks,
        net_amount_kopecks=flow.net_amount_kopecks,
        currency=flow.currency,
        source=flow.source,
    )
