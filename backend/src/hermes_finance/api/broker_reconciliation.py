"""Explicit read-only normalized broker reconciliation API (R07-08A)."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from hermes_finance.alfa_pro_diagnostics import (
    DEFAULT_API_DOC_VERSION,
    AlfaDiagnosticFailureClass,
    AlfaDiagnosticReport,
    diagnostic_for_failure,
)
from hermes_finance.api.broker_snapshot import (
    BrokerAccountRowOut,
    BrokerCashRowOut,
    BrokerInstrumentRowOut,
    BrokerMappingIn,
    BrokerSnapshotDiagnosticsOut,
    _mapping,
    _provider,
)
from hermes_finance.api.settings import session_for_request
from hermes_finance.broker_data.dto import BrokerSnapshot, SnapshotStatus
from hermes_finance.broker_data.reconciliation.dto import (
    NormalizedReconciliationResult,
    NormalizedReconciliationRow,
    ReconciliationStatus,
)
from hermes_finance.services.broker_reconciliation import (
    build_normalized_reconciliation_for_snapshot,
    load_hermes_state_for_month,
)

router = APIRouter(tags=["broker-reconciliation"])


class BrokerReconciliationExpectedRowIn(BaseModel):
    """Fingerprint expectation for one canonical local position."""

    model_config = ConfigDict(extra="forbid")

    hermes_account_id: int = Field(gt=0)
    instrument_id: int = Field(gt=0)
    fingerprint: str = Field(min_length=1, max_length=128)


class BrokerReconciliationRequest(BrokerMappingIn):
    """Mapping plus optional stale-preview expectations.

    The mapping fields intentionally match the existing broker snapshot
    preview request. Expectations are optional because this endpoint has no
    apply operation; when supplied they provide the existing stale-preview
    guard for a read-only revalidation.
    """

    model_config = ConfigDict(extra="forbid")

    expected_rows: list[BrokerReconciliationExpectedRowIn] = Field(
        default_factory=list, max_length=2_000
    )
    expected_snapshot_fingerprint: str | None = Field(default=None, max_length=128)


class BrokerNormalizedReconciliationRowOut(BaseModel):
    """Pydantic response projection of a normalized position row."""

    model_config = ConfigDict(extra="forbid")

    state: str
    account_id: int | None
    instrument_id: int | None
    account_name: str | None
    instrument_name: str | None
    instrument_isin: str | None
    instrument_ticker: str | None
    provider_account_id: str | None
    provider_instrument_id: str | None
    hermes_quantity: str | None
    provider_quantity: str | None
    quantity_difference: str | None
    quantity_equal: bool | None
    hermes_market_price_per_unit_kopecks: int | None
    provider_broker_unit_price: str | None
    provider_accounting_price: str | None
    provider_market_value: str | None
    price_comparable: str
    hermes_accrued_interest_kopecks: int | None
    provider_accrued_interest_nkd: str | None
    nkd_comparable: str
    hermes_unrealized_result_kopecks: int | None
    provider_unrealized_result: str | None
    unrealized_comparable: str
    reason: str | None
    warnings: list[str]
    comparison_only_fields: list[str]
    fingerprint: str | None = None


class BrokerReconciliationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reporting_month_id: int
    provider: str
    status: str
    read_only: Literal[True]
    eligible_for_apply: Literal[False]
    stale: bool
    snapshot_status: str
    compatibility_state: str
    compatibility_fingerprint: str | None
    snapshot_fingerprint: str | None
    source_as_of: datetime | None
    captured_at: datetime
    month_status: str
    month_closed: bool
    accounts: list[BrokerAccountRowOut]
    instruments: list[BrokerInstrumentRowOut]
    rows: list[BrokerNormalizedReconciliationRowOut]
    cash: list[BrokerCashRowOut]
    warnings: list[str]
    diagnostics: BrokerSnapshotDiagnosticsOut
    diagnostic_report: str
    error_code: str | None = None
    message: str | None = None


def _decimal(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


def _expected_rows(payload: BrokerReconciliationRequest) -> dict[tuple[int, int], str]:
    expected: dict[tuple[int, int], str] = {}
    for row in payload.expected_rows:
        key = (row.hermes_account_id, row.instrument_id)
        if key in expected:
            raise ValueError("expected reconciliation row fingerprints must be unique")
        expected[key] = row.fingerprint.strip()
    return expected


def _diagnostics(
    *,
    snapshot: BrokerSnapshot,
    result: NormalizedReconciliationResult,
) -> AlfaDiagnosticReport:
    diagnostics = snapshot.diagnostics
    if (
        diagnostics.compatibility_state is not result.compatibility_state
        or diagnostics.compatibility_fingerprint != result.compatibility_fingerprint
    ):
        diagnostics = replace(
            diagnostics,
            compatibility_state=result.compatibility_state,
            compatibility_fingerprint=result.compatibility_fingerprint,
        )
    if (
        result.compatibility_state.value != "compatible"
        and diagnostics.failure_class is AlfaDiagnosticFailureClass.NONE
    ):
        diagnostics = diagnostics.with_failure(
            AlfaDiagnosticFailureClass.PROTOCOL,
            "compatibility_unknown",
        )
    diagnostics = diagnostics.with_snapshot(
        status=result.snapshot_status.value,
        eligible_for_apply=False,
    )
    if (
        not result.stale
        and snapshot.provenance.eligible_for_apply
        and result.compatibility_state.value == "compatible"
        and result.snapshot_status is SnapshotStatus.COMPLETE
        and result.status in {ReconciliationStatus.NON_APPLICABLE, ReconciliationStatus.CONFLICTS}
        and diagnostics.failure_class
        in {
            AlfaDiagnosticFailureClass.NONE,
            AlfaDiagnosticFailureClass.MAPPING,
        }
    ):
        code = (
            "mapping_conflict"
            if result.status is ReconciliationStatus.CONFLICTS
            else "mapping_unresolved"
        )
        diagnostics = diagnostics.with_failure(AlfaDiagnosticFailureClass.MAPPING, code)
    return diagnostics


def _row_out(row: NormalizedReconciliationRow) -> BrokerNormalizedReconciliationRowOut:
    return BrokerNormalizedReconciliationRowOut(
        state=row.state.value,
        account_id=row.account_id,
        instrument_id=row.instrument_id,
        account_name=row.account_name,
        instrument_name=row.instrument_name,
        instrument_isin=row.instrument_isin,
        instrument_ticker=row.instrument_ticker,
        provider_account_id=row.provider_account_id,
        provider_instrument_id=row.provider_instrument_id,
        hermes_quantity=_decimal(row.hermes_quantity),
        provider_quantity=_decimal(row.provider_quantity),
        quantity_difference=_decimal(row.quantity_difference),
        quantity_equal=row.quantity_equal,
        hermes_market_price_per_unit_kopecks=row.hermes_market_price_per_unit_kopecks,
        provider_broker_unit_price=_decimal(row.provider_broker_unit_price),
        provider_accounting_price=_decimal(row.provider_accounting_price),
        provider_market_value=_decimal(row.provider_market_value),
        price_comparable=row.price_comparable.value,
        hermes_accrued_interest_kopecks=row.hermes_accrued_interest_kopecks,
        provider_accrued_interest_nkd=_decimal(row.provider_accrued_interest_nkd),
        nkd_comparable=row.nkd_comparable.value,
        hermes_unrealized_result_kopecks=row.hermes_unrealized_result_kopecks,
        provider_unrealized_result=_decimal(row.provider_unrealized_result),
        unrealized_comparable=row.unrealized_comparable.value,
        reason=row.reason,
        warnings=list(row.warnings),
        comparison_only_fields=list(row.comparison_only_fields),
        fingerprint=row.fingerprint,
    )


def _response(
    *,
    snapshot: BrokerSnapshot,
    result: NormalizedReconciliationResult,
) -> BrokerReconciliationResponse:
    diagnostics = _diagnostics(snapshot=snapshot, result=result)
    return BrokerReconciliationResponse(
        reporting_month_id=result.month_id,
        provider=result.provider,
        status=result.status.value,
        read_only=True,
        eligible_for_apply=False,
        stale=result.stale,
        snapshot_status=result.snapshot_status.value,
        compatibility_state=result.compatibility_state.value,
        compatibility_fingerprint=result.compatibility_fingerprint,
        snapshot_fingerprint=result.snapshot_fingerprint,
        source_as_of=result.source_as_of,
        captured_at=result.captured_at,
        month_status=result.month_status,
        month_closed=result.month_closed,
        accounts=[
            BrokerAccountRowOut(
                provider_account_id=row.provider_account_id,
                hermes_account_id=row.hermes_account_id,
                status=row.status.value,
                reason=row.reason,
            )
            for row in result.accounts
        ],
        instruments=[
            BrokerInstrumentRowOut(
                provider_instrument_id=row.provider_instrument_id,
                isin=row.isin,
                ticker=row.ticker,
                display_name=row.display_name,
                hermes_instrument_id=row.hermes_instrument_id,
                status=row.status.value,
                reason=row.reason,
            )
            for row in result.instruments
        ],
        rows=[_row_out(row) for row in result.rows],
        cash=[
            BrokerCashRowOut(
                provider_account_id=row.provider_account_id,
                hermes_account_id=row.hermes_account_id,
                currency=row.currency,
                provider_amount=_decimal(row.provider_amount),
                status=row.status.value,
                reason=row.reason,
            )
            for row in result.cash
        ],
        warnings=list(result.warnings),
        diagnostics=BrokerSnapshotDiagnosticsOut(**diagnostics.to_dict()),
        diagnostic_report=diagnostics.to_text(),
    )


def _provider_failure_response(
    *,
    month_id: int,
    month_status: str,
) -> BrokerReconciliationResponse:
    diagnostics = diagnostic_for_failure(
        api_doc_version=DEFAULT_API_DOC_VERSION,
        failure_class=AlfaDiagnosticFailureClass.CONNECTION,
        failure_code="provider_fetch_failed",
        snapshot_status=SnapshotStatus.MALFORMED_RESPONSE.value,
    )
    now = datetime.now().astimezone()
    return BrokerReconciliationResponse(
        reporting_month_id=month_id,
        provider="alfa_pro",
        status=ReconciliationStatus.NON_APPLICABLE.value,
        read_only=True,
        eligible_for_apply=False,
        stale=False,
        snapshot_status=SnapshotStatus.MALFORMED_RESPONSE.value,
        compatibility_state=diagnostics.compatibility_state.value,
        compatibility_fingerprint=None,
        snapshot_fingerprint=None,
        source_as_of=None,
        captured_at=now,
        month_status=month_status,
        month_closed=month_status == "closed",
        accounts=[],
        instruments=[],
        rows=[],
        cash=[],
        warnings=["broker snapshot refresh failed"],
        diagnostics=BrokerSnapshotDiagnosticsOut(**diagnostics.to_dict()),
        diagnostic_report=diagnostics.to_text(),
        error_code="provider_error",
        message="Broker snapshot refresh failed",
    )


@router.post(
    "/api/months/{month_id}/broker-reconciliation-preview",
    response_model=BrokerReconciliationResponse,
)
@router.post(
    "/api/months/{month_id}/reconciliation-preview",
    response_model=BrokerReconciliationResponse,
)
def broker_reconciliation_preview_endpoint(
    month_id: int,
    payload: BrokerReconciliationRequest,
    request: Request,
    session: Session = Depends(session_for_request),
) -> BrokerReconciliationResponse:
    hermes = load_hermes_state_for_month(session, month_id)
    try:
        snapshot = _provider(request).fetch_snapshot()
    except Exception:
        return _provider_failure_response(month_id=month_id, month_status=hermes.month_status)
    if not isinstance(snapshot, BrokerSnapshot):
        return _provider_failure_response(month_id=month_id, month_status=hermes.month_status)
    try:
        expected_rows = _expected_rows(payload)
    except ValueError as error:
        # The request is invalid, but no provider or database state is changed.
        raise HTTPException(status_code=422, detail=str(error)) from error
    result = build_normalized_reconciliation_for_snapshot(
        session,
        snapshot=snapshot,
        hermes=hermes,
        mapping=_mapping(payload),
        expected_row_fingerprints=expected_rows,
        expected_snapshot_fingerprint=payload.expected_snapshot_fingerprint,
    )
    return _response(snapshot=snapshot, result=result)
