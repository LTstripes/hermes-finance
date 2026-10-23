"""Owner-triggered, non-persisting source-to-schedule preview."""

from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from hermes_finance.api.market_data import close_owned_payout_resource, resolve_payout_provider
from hermes_finance.api.settings import session_for_request
from hermes_finance.domain.instrument_return import InstrumentEvent, SourceReference
from hermes_finance.market_data.dto import T_INVEST_PROVIDER
from hermes_finance.market_data.payout import PayoutEventStatus
from hermes_finance.market_data.payout_protocol import PayoutFailure, PayoutFetchResult
from hermes_finance.services.source_payout_preview import (
    reconcile_source_payouts,
    source_payout_context,
)

router = APIRouter(tags=["source-returns"])


class SourcePayoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_account: str = Field(min_length=1, max_length=256, pattern=r"^\S+$")
    isin: str = Field(pattern=r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
    as_of: date = Field(le=date(9998, 12, 31))


class SourcePayoutRow(BaseModel):
    identity_key: str | None
    event_kind: str
    payment_date: date | None
    provider_status: str | None
    source_method: str | None
    per_unit_amount: Decimal | None
    currency: str | None
    announced_amount_kopecks: int | None
    personal_tax_known: Literal[False]
    status: str
    countable_future: bool
    actual_event_keys: list[str]
    reason_codes: list[str]


class SourcePayoutResponse(BaseModel):
    authority: Literal["provisional"]
    financial_authority: Literal["none"]
    source_account: str
    native_source_account: str | None
    account_id: int | None
    isin: str
    instrument_id: int | None
    as_of: date
    quantity: Decimal | None
    quantity_authority: Literal["source_observed"]
    assumptions: list[Literal["fixed_source_quantity_not_entitlement"]]
    quantity_references: tuple[str, ...]
    source_references: tuple[SourceReference, ...]
    dependency_fingerprint: str
    reason_codes: tuple[str, ...]
    provider: Literal["t_invest"]
    instrument_uid: str | None
    actuals: tuple[InstrumentEvent, ...]
    reconciliation_reasons: tuple[str, ...]
    rows: list[SourcePayoutRow]
    failures: list[str]


@router.post("/api/source-returns/payout-preview", response_model=SourcePayoutResponse)
def source_payout_preview(
    payload: SourcePayoutRequest,
    request: Request,
    response: Response,
    session: Session = Depends(session_for_request),
):
    response.headers["Cache-Control"] = "no-store"
    context = source_payout_context(session, payload.source_account, payload.isin, payload.as_of)
    provider_request = context.provider_request()
    fetched = None
    if provider_request is not None:
        provider, owned = resolve_payout_provider(request)
        try:
            try:
                fetched = provider.fetch_payouts(provider_request)
            except Exception:
                fetched = None
        finally:
            close_owned_payout_resource(owned)
        if (
            not isinstance(fetched, PayoutFetchResult)
            or fetched.provider != T_INVEST_PROVIDER
            or fetched.instrument_uid != context.instrument_uid
            or any(
                e.provider != T_INVEST_PROVIDER or e.instrument_uid != context.instrument_uid
                for e in fetched.events
            )
        ):
            fetched = PayoutFetchResult(
                provider=T_INVEST_PROVIDER,
                instrument_uid=context.instrument_uid,
                failures=(
                    PayoutFailure(
                        status=PayoutEventStatus.ERROR, message="Payout provider refresh failed"
                    ),
                ),
            )
        current = source_payout_context(
            session, payload.source_account, payload.isin, payload.as_of
        )
        if current != context:
            raise HTTPException(409, "Source payout context changed; request a new preview")
    return reconcile_source_payouts(context, fetched)
