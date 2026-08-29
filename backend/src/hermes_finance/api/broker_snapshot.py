"""Thin local API for the explicit Alfa PRO snapshot review flow (R06-09)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.alfa_pro_diagnostics import (
    DEFAULT_API_DOC_VERSION,
    AlfaCompatibilityState,
    AlfaDiagnosticFailureClass,
    AlfaDiagnosticReport,
    diagnostic_for_failure,
)
from hermes_finance.api.settings import session_for_request
from hermes_finance.broker_data.alfa_pro import AlfaProBrokerSnapshotProvider
from hermes_finance.broker_data.dto import SnapshotStatus
from hermes_finance.broker_data.protocol import BrokerSnapshotProvider
from hermes_finance.broker_data.reconciliation.dto import (
    AccountReconciliationRow,
    InstrumentReconciliationRow,
    OwnerMappingInput,
)
from hermes_finance.broker_data.reconciliation.preview import build_reconciliation_preview
from hermes_finance.domain import PriceSource, RubleAmount
from hermes_finance.persistence import PositionSnapshot
from hermes_finance.services.broker_identity_mappings import (
    IdentityClassification,
    PreviewIdentityLabels,
    classify_preview_identities,
    compose_owner_mapping,
)
from hermes_finance.services.broker_reconciliation import load_hermes_state_for_month
from hermes_finance.services.broker_snapshot_apply import (
    AccruedInterestDecision,
    AverageCostDecision,
    BrokerSnapshotApplyAction,
    BrokerSnapshotApplySelection,
    DependentFieldAction,
    MarketPriceDecision,
    apply_broker_snapshot_preview,
    position_apply_fingerprint,
)

router = APIRouter(tags=["broker-snapshot"])


class BrokerAccountMappingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hermes_account_id: int = Field(gt=0)
    provider_account_id: str = Field(min_length=1, max_length=128)


class BrokerInstrumentMappingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hermes_instrument_id: int = Field(gt=0)
    provider_instrument_id: str = Field(min_length=1, max_length=128)


class BrokerMappingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accounts: list[BrokerAccountMappingIn] = Field(default_factory=list, max_length=200)
    instruments: list[BrokerInstrumentMappingIn] = Field(default_factory=list, max_length=200)


class BrokerDependentAmountIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: DependentFieldAction
    value: str | None = Field(default=None, max_length=64)


class BrokerMarketPriceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: DependentFieldAction
    market_price_per_unit: str | None = Field(default=None, max_length=64)
    price_date: date | None = None
    price_source: PriceSource | None = None


class BrokerApplySelectionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: int = Field(gt=0)
    instrument_id: int = Field(gt=0)
    fingerprint: str = Field(min_length=1, max_length=128)
    action: BrokerSnapshotApplyAction
    average_cost: BrokerDependentAmountIn | None = None
    market_price: BrokerMarketPriceIn | None = None
    accrued_interest: BrokerDependentAmountIn | None = None


class BrokerSnapshotApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mapping: BrokerMappingIn
    selections: list[BrokerApplySelectionIn] = Field(min_length=1, max_length=2_000)


class BrokerAccountObservedInstrumentOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = None
    isin: str | None = None
    ticker: str | None = None


class BrokerAccountRowOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_account_id: str
    hermes_account_id: int | None
    status: str
    reason: str | None
    classification: str
    section_codes: list[str] = Field(default_factory=list)
    observed_instruments: list[BrokerAccountObservedInstrumentOut] = Field(default_factory=list)


def account_row_out(
    row: AccountReconciliationRow,
    classification: str | IdentityClassification = IdentityClassification.NEW,
) -> BrokerAccountRowOut:
    label = (
        classification.value
        if isinstance(classification, IdentityClassification)
        else classification
    )
    return BrokerAccountRowOut(
        provider_account_id=row.provider_account_id,
        hermes_account_id=row.hermes_account_id,
        status=row.status.value,
        reason=row.reason,
        classification=label,
        section_codes=list(row.section_codes),
        observed_instruments=[
            BrokerAccountObservedInstrumentOut(
                display_name=item.display_name,
                isin=item.isin,
                ticker=item.ticker,
            )
            for item in row.observed_instruments
        ],
    )


class BrokerInstrumentRowOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_instrument_id: str | None
    isin: str | None
    ticker: str | None
    display_name: str | None
    hermes_instrument_id: int | None
    status: str
    reason: str | None
    classification: str


def instrument_row_out(
    row: InstrumentReconciliationRow,
    classification: str | IdentityClassification = IdentityClassification.NEW,
) -> BrokerInstrumentRowOut:
    label = (
        classification.value
        if isinstance(classification, IdentityClassification)
        else classification
    )
    return BrokerInstrumentRowOut(
        provider_instrument_id=row.provider_instrument_id,
        isin=row.isin,
        ticker=row.ticker,
        display_name=row.display_name,
        hermes_instrument_id=row.hermes_instrument_id,
        status=row.status.value,
        reason=row.reason,
        classification=label,
    )


def _account_classification(
    row: AccountReconciliationRow, identity_labels: PreviewIdentityLabels | None
) -> IdentityClassification:
    if identity_labels is None:
        return IdentityClassification.NEW
    return identity_labels.accounts.get(row.provider_account_id, IdentityClassification.NEW)


def _instrument_classification(
    row: InstrumentReconciliationRow, identity_labels: PreviewIdentityLabels | None
) -> IdentityClassification:
    if identity_labels is None or row.provider_instrument_id is None:
        if row.reason == "exact unique ISIN match":
            return IdentityClassification.DETERMINISTIC_ISIN
        if row.status.value == "ambiguous":
            return IdentityClassification.AMBIGUOUS
        if row.status.value == "conflict":
            return IdentityClassification.CONFLICT
        if row.status.value == "matched":
            return IdentityClassification.EXPLICIT
        return IdentityClassification.NEW
    return identity_labels.instruments.get(row.provider_instrument_id, IdentityClassification.NEW)


def classified_account_rows(
    preview_accounts,
    identity_labels: PreviewIdentityLabels | None,
) -> list[BrokerAccountRowOut]:
    rows = list(preview_accounts)
    if identity_labels is not None:
        rows.extend(identity_labels.absent_accounts)
    return [account_row_out(row, _account_classification(row, identity_labels)) for row in rows]


def classified_instrument_rows(
    preview_instruments,
    identity_labels: PreviewIdentityLabels | None,
) -> list[BrokerInstrumentRowOut]:
    rows = list(preview_instruments)
    if identity_labels is not None:
        rows.extend(identity_labels.absent_instruments)
    return [
        instrument_row_out(row, _instrument_classification(row, identity_labels)) for row in rows
    ]


class BrokerPositionRowOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: int
    instrument_id: int
    account_name: str | None
    instrument_name: str | None
    instrument_isin: str | None
    status: str
    hermes_quantity: str | None
    provider_quantity: str | None
    quantity_difference: str | None
    quantity_equal: bool | None
    hermes_market_price_per_unit_kopecks: int | None
    provider_broker_unit_price: str | None
    price_comparable: str
    hermes_accrued_interest_kopecks: int | None
    provider_accrued_interest_nkd: str | None
    nkd_comparable: str
    hermes_unrealized_result_kopecks: int | None
    provider_unrealized_result: str | None
    unrealized_comparable: str
    reason: str | None
    warnings: list[str]
    fingerprint: str | None = None


class BrokerCashRowOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_account_id: str
    hermes_account_id: int | None
    currency: str | None
    provider_amount: str | None
    status: str
    reason: str | None


class BrokerSnapshotDiagnosticsOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    provider: str
    snapshot_status: str
    eligible_for_apply: bool
    compatibility_state: str
    compatibility_fingerprint: str | None
    api_doc_version: str
    observed_alfa_pro_version: str | None
    observed_api_version: str | None
    observed_protocol_version: str | None
    protocol_family: str
    layout_family: str
    capabilities: list[str]
    failure_class: str
    failure_codes: list[str]
    entity_status: list[str]
    entity_counts: list[str]
    observed_fields: list[str]
    safe_artifact: bool
    raw_payload_saved: bool
    private_values_included: bool
    credentials_included: bool


class BrokerSnapshotPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reporting_month_id: int
    provider: str
    status: str
    eligible_for_apply: bool
    snapshot_status: str
    source_as_of: datetime | None
    captured_at: datetime
    month_status: str
    month_closed: bool
    would_touch_closed_month: bool
    conflict_count: int
    accounts: list[BrokerAccountRowOut]
    instruments: list[BrokerInstrumentRowOut]
    positions: list[BrokerPositionRowOut]
    cash: list[BrokerCashRowOut]
    warnings: list[str]
    diagnostics: BrokerSnapshotDiagnosticsOut
    diagnostic_report: str
    error_code: str | None = None
    message: str | None = None


class BrokerApplyItemOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str
    position_snapshot_id: int
    account_id: int
    instrument_id: int
    quantity: str
    average_cost_per_unit_kopecks: int
    market_price_per_unit_kopecks: int
    accrued_interest_kopecks: int | None
    market_value_kopecks: int
    cost_basis_kopecks: int
    unrealized_result_kopecks: int
    price_date: date
    price_source: str


class BrokerApplyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool
    selected_count: int
    items: list[BrokerApplyItemOut]
    error_code: str | None
    message: str | None
    source_as_of: datetime | None
    captured_at: datetime | None
    snapshot_status: str | None
    fingerprint: str | None


def _mapping(payload: BrokerMappingIn) -> OwnerMappingInput:
    from hermes_finance.broker_data.reconciliation.dto import (
        AccountMappingInput,
        InstrumentMappingInput,
    )

    return OwnerMappingInput(
        accounts=tuple(
            AccountMappingInput(
                hermes_account_id=row.hermes_account_id,
                provider_account_id=row.provider_account_id.strip(),
            )
            for row in payload.accounts
        ),
        instruments=tuple(
            InstrumentMappingInput(
                hermes_instrument_id=row.hermes_instrument_id,
                provider_instrument_id=row.provider_instrument_id.strip(),
            )
            for row in payload.instruments
        ),
    )


def _provider(request: Request) -> BrokerSnapshotProvider:
    existing = getattr(request.app.state, "broker_snapshot_provider", None)
    if existing is not None:
        return existing
    # Construction validates configuration but performs no network I/O. The
    # first provider call remains inside the explicit owner action below.
    return AlfaProBrokerSnapshotProvider()


def _decimal(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


def _preview_response(
    preview,
    *,
    fingerprint_mapping: OwnerMappingInput,
    session: Session,
    snapshot: object,
    identity_labels: PreviewIdentityLabels | None = None,
) -> BrokerSnapshotPreviewResponse:
    hermes = load_hermes_state_for_month(session, preview.month_id or 0)
    account_names = {account.account_id: account.name for account in hermes.accounts}
    instruments = {instrument.instrument_id: instrument for instrument in hermes.instruments}
    # Reconciliation state is deliberately a display DTO. The apply contract,
    # however, fingerprints persisted PositionSnapshot identity and revision
    # state, so preview must use the same authoritative records as Apply.
    snapshots = {
        (snapshot.account_id, snapshot.instrument_id): snapshot
        for snapshot in session.scalars(
            select(PositionSnapshot).where(
                PositionSnapshot.reporting_month_id == (preview.month_id or 0)
            )
        )
    }
    positions = []
    for row in preview.positions:
        fingerprint = (
            position_apply_fingerprint(
                preview=preview,
                row=row,
                mapping=fingerprint_mapping,
                snapshot=snapshots.get((row.account_id, row.instrument_id)),
            )
            if row.status.value in {"matched", "provider_only"}
            else None
        )
        positions.append(
            BrokerPositionRowOut(
                account_id=row.account_id,
                instrument_id=row.instrument_id,
                account_name=account_names.get(row.account_id),
                instrument_name=(
                    instruments[row.instrument_id].name
                    if row.instrument_id in instruments
                    else None
                ),
                instrument_isin=(
                    instruments[row.instrument_id].isin
                    if row.instrument_id in instruments
                    else None
                ),
                status=row.status.value,
                hermes_quantity=_decimal(row.hermes_quantity),
                provider_quantity=_decimal(row.provider_quantity),
                quantity_difference=_decimal(row.quantity_difference),
                quantity_equal=row.quantity_equal,
                hermes_market_price_per_unit_kopecks=row.hermes_market_price_per_unit_kopecks,
                provider_broker_unit_price=_decimal(row.provider_broker_unit_price),
                price_comparable=row.price_comparable.value,
                hermes_accrued_interest_kopecks=row.hermes_accrued_interest_kopecks,
                provider_accrued_interest_nkd=_decimal(row.provider_accrued_interest_nkd),
                nkd_comparable=row.nkd_comparable.value,
                hermes_unrealized_result_kopecks=row.hermes_unrealized_result_kopecks,
                provider_unrealized_result=_decimal(row.provider_unrealized_result),
                unrealized_comparable=row.unrealized_comparable.value,
                reason=row.reason,
                warnings=list(row.warnings),
                fingerprint=fingerprint,
            )
        )
    diagnostics = getattr(snapshot, "diagnostics", AlfaDiagnosticReport())
    if not isinstance(diagnostics, AlfaDiagnosticReport):
        diagnostics = AlfaDiagnosticReport()
    mapping_failure_codes = _mapping_failure_codes(preview)
    if (
        mapping_failure_codes
        and diagnostics.compatibility_state is AlfaCompatibilityState.COMPATIBLE
        and diagnostics.failure_class
        in {AlfaDiagnosticFailureClass.NONE, AlfaDiagnosticFailureClass.MAPPING}
    ):
        diagnostics = diagnostics.with_failure(
            AlfaDiagnosticFailureClass.MAPPING, *mapping_failure_codes
        )
    diagnostics = diagnostics.with_snapshot(
        status=preview.snapshot_status.value,
        eligible_for_apply=preview.eligible_for_apply,
    )
    diagnostics_out = BrokerSnapshotDiagnosticsOut(**diagnostics.to_dict())
    return BrokerSnapshotPreviewResponse(
        reporting_month_id=preview.month_id or 0,
        provider=preview.provider,
        status=preview.status.value,
        eligible_for_apply=preview.eligible_for_apply,
        snapshot_status=preview.snapshot_status.value,
        source_as_of=preview.source_as_of,
        captured_at=preview.captured_at,
        month_status=preview.month_status or "unknown",
        month_closed=preview.month_closed,
        would_touch_closed_month=preview.would_touch_closed_month,
        conflict_count=preview.conflict_count,
        accounts=classified_account_rows(preview.accounts, identity_labels),
        instruments=classified_instrument_rows(preview.instruments, identity_labels),
        positions=positions,
        cash=[
            BrokerCashRowOut(
                provider_account_id=row.provider_account_id,
                hermes_account_id=row.hermes_account_id,
                currency=row.currency,
                provider_amount=_decimal(row.provider_amount),
                status=row.status.value,
                reason=row.reason,
            )
            for row in preview.cash
        ],
        warnings=list(preview.warnings),
        diagnostics=diagnostics_out,
        diagnostic_report=diagnostics.to_text(),
    )


def _mapping_failure_codes(preview) -> tuple[str, ...]:
    codes: list[str] = []
    if any(row.status.value != "matched" for row in preview.accounts):
        codes.append("account_mapping_unresolved")
    if any(row.status.value != "matched" for row in preview.instruments):
        codes.append("instrument_mapping_unresolved")
    if any(row.status.value == "conflict" for row in preview.positions):
        codes.append("position_mapping_conflict")
    if preview.status.value == "conflicts":
        codes.append("mapping_conflict")
    elif preview.status.value == "non_applicable" and preview.snapshot_status.value == "complete":
        codes.append("mapping_unresolved")
    return tuple(dict.fromkeys(codes))


def _amount(value: str | None) -> RubleAmount | None:
    return RubleAmount.from_api(value) if value is not None else None


def _dependent(value: BrokerDependentAmountIn | None):
    return None if value is None else (value.action, _amount(value.value))


def _selection(row: BrokerApplySelectionIn) -> BrokerSnapshotApplySelection:
    average = None
    if row.average_cost is not None:
        average = AverageCostDecision(
            action=row.average_cost.action, value=_amount(row.average_cost.value)
        )
    market = None
    if row.market_price is not None:
        market = MarketPriceDecision(
            action=row.market_price.action,
            market_price_per_unit=_amount(row.market_price.market_price_per_unit),
            price_date=row.market_price.price_date,
            price_source=row.market_price.price_source,
        )
    accrued = None
    if row.accrued_interest is not None:
        accrued = AccruedInterestDecision(
            action=row.accrued_interest.action, value=_amount(row.accrued_interest.value)
        )
    return BrokerSnapshotApplySelection(
        account_id=row.account_id,
        instrument_id=row.instrument_id,
        fingerprint=row.fingerprint,
        action=row.action,
        average_cost=average,
        market_price=market,
        accrued_interest=accrued,
    )


@router.post(
    "/api/months/{month_id}/broker-snapshot-preview", response_model=BrokerSnapshotPreviewResponse
)
def broker_snapshot_preview_endpoint(
    month_id: int,
    payload: BrokerMappingIn,
    request: Request,
    session: Session = Depends(session_for_request),
) -> BrokerSnapshotPreviewResponse:
    request_mapping = _mapping(payload)
    hermes = load_hermes_state_for_month(session, month_id)
    try:
        snapshot = _provider(request).fetch_snapshot()
    except Exception:
        diagnostics = diagnostic_for_failure(
            api_doc_version=DEFAULT_API_DOC_VERSION,
            failure_class=AlfaDiagnosticFailureClass.CONNECTION,
            failure_code="provider_fetch_failed",
            snapshot_status=SnapshotStatus.MALFORMED_RESPONSE.value,
        )
        return BrokerSnapshotPreviewResponse(
            reporting_month_id=month_id,
            provider="alfa_pro",
            status="non_applicable",
            eligible_for_apply=False,
            snapshot_status=SnapshotStatus.MALFORMED_RESPONSE.value,
            source_as_of=None,
            captured_at=datetime.now().astimezone(),
            month_status=hermes.month_status,
            month_closed=hermes.month_status == "closed",
            would_touch_closed_month=False,
            conflict_count=0,
            accounts=[],
            instruments=[],
            positions=[],
            cash=[],
            warnings=["broker snapshot refresh failed"],
            diagnostics=BrokerSnapshotDiagnosticsOut(**diagnostics.to_dict()),
            diagnostic_report=diagnostics.to_text(),
            error_code="provider_error",
            message="Broker snapshot refresh failed",
        )
    mapping = compose_owner_mapping(
        session, provider=getattr(snapshot, "provider", ""), request=request_mapping
    )
    preview = build_reconciliation_preview(snapshot=snapshot, hermes=hermes, mapping=mapping)
    identity_labels = None
    if hasattr(snapshot, "provider") and hasattr(snapshot, "accounts"):
        identity_labels = classify_preview_identities(
            snapshot=snapshot,
            account_rows=preview.accounts,
            instrument_rows=preview.instruments,
            session=session,
            request=request_mapping,
        )
    return _preview_response(
        preview,
        fingerprint_mapping=mapping,
        session=session,
        snapshot=snapshot,
        identity_labels=identity_labels,
    )


@router.post("/api/months/{month_id}/broker-snapshot-apply", response_model=BrokerApplyResponse)
def broker_snapshot_apply_endpoint(
    month_id: int,
    payload: BrokerSnapshotApplyRequest,
    request: Request,
    session: Session = Depends(session_for_request),
) -> BrokerApplyResponse:
    result = apply_broker_snapshot_preview(
        session,
        provider=_provider(request),
        reporting_month_id=month_id,
        mapping=_mapping(payload.mapping),
        selections=tuple(_selection(row) for row in payload.selections),
    )
    return BrokerApplyResponse(
        success=result.success,
        selected_count=result.selected_count,
        items=[
            BrokerApplyItemOut(
                action=item.action.value,
                position_snapshot_id=item.position_snapshot_id,
                account_id=item.account_id,
                instrument_id=item.instrument_id,
                quantity=format(item.quantity, "f"),
                average_cost_per_unit_kopecks=item.average_cost_per_unit_kopecks,
                market_price_per_unit_kopecks=item.market_price_per_unit_kopecks,
                accrued_interest_kopecks=item.accrued_interest_kopecks,
                market_value_kopecks=item.market_value_kopecks,
                cost_basis_kopecks=item.cost_basis_kopecks,
                unrealized_result_kopecks=item.unrealized_result_kopecks,
                price_date=item.price_date,
                price_source=item.price_source,
            )
            for item in result.items
        ],
        error_code=result.error_code.value if result.error_code is not None else None,
        message=result.message,
        source_as_of=result.source_as_of,
        captured_at=result.captured_at,
        snapshot_status=result.snapshot_status,
        fingerprint=result.fingerprint,
    )
