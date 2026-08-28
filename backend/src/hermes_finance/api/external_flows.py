"""Explicit external boundary flows and owner-managed transfer links (R08-01A)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Query, status
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from hermes_finance.api.settings import MoneyValue, session_for_request
from hermes_finance.domain import RubleAmount
from hermes_finance.services.external_flows import (
    classify_external_flow,
    create_external_flow,
    create_external_transfer_link,
    delete_external_flow,
    delete_external_transfer_link,
    external_flow_transfer_status,
    get_external_flow,
    get_external_transfer_link,
    list_external_flows,
    list_external_transfer_links,
    transfer_link_legs,
    update_external_flow,
    update_external_transfer_link,
)

router = APIRouter(tags=["external-flows"])


class ExternalFlowCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reporting_month_id: int
    account_id: int
    event_date: date
    boundary_amount: MoneyValue = Field(validation_alias=AliasChoices("boundary_amount", "amount"))
    direction: str = Field(min_length=1, max_length=16)
    kind: str = Field(
        min_length=1,
        max_length=32,
        validation_alias=AliasChoices("kind", "flow_kind", "flow_type"),
    )
    transfer_link_id: int | None = Field(
        default=None,
        validation_alias=AliasChoices("transfer_link_id", "transfer_group_id"),
    )
    source: str = Field(default="manual", min_length=1, max_length=64)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("boundary_amount")
    @classmethod
    def validate_exact_boundary_amount(cls, value: MoneyValue) -> MoneyValue:
        decimal_amount = Decimal(value.amount)
        scaled = decimal_amount * Decimal(100)
        if scaled != scaled.to_integral_value():
            raise ValueError("boundary_amount must have no more than two decimal places")
        return value


class ExternalFlowUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: int | None = None
    event_date: date | None = None
    boundary_amount: MoneyValue | None = Field(
        default=None,
        validation_alias=AliasChoices("boundary_amount", "amount"),
    )
    direction: str | None = Field(default=None, min_length=1, max_length=16)
    kind: str | None = Field(
        default=None,
        min_length=1,
        max_length=32,
        validation_alias=AliasChoices("kind", "flow_kind", "flow_type"),
    )
    transfer_link_id: int | None = Field(
        default=None,
        validation_alias=AliasChoices("transfer_link_id", "transfer_group_id"),
    )
    source: str | None = Field(default=None, min_length=1, max_length=64)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("boundary_amount")
    @classmethod
    def validate_exact_boundary_amount(cls, value: MoneyValue | None) -> MoneyValue | None:
        if value is None:
            return None
        decimal_amount = Decimal(value.amount)
        scaled = decimal_amount * Decimal(100)
        if scaled != scaled.to_integral_value():
            raise ValueError("boundary_amount must have no more than two decimal places")
        return value


class ExternalFlowResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    reporting_month_id: int
    account_id: int
    event_date: date
    boundary_amount: MoneyValue
    direction: str
    kind: str
    currency: str
    transfer_link_id: int | None
    transfer_status: str | None
    portfolio_scope_classification: str
    account_scope_classification: str
    source: str
    notes: str | None


class TransferLinkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transfer_key: str | None = Field(default=None, max_length=128)
    flow_ids: list[int] = Field(default_factory=list, max_length=2)
    notes: str | None = Field(default=None, max_length=2000)


class TransferLinkUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transfer_key: str | None = Field(default=None, min_length=1, max_length=128)
    notes: str | None = Field(default=None, max_length=2000)


class TransferLinkResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    transfer_key: str
    status: str
    flow_ids: list[int]
    notes: str | None


def _amount(money: MoneyValue) -> RubleAmount:
    return RubleAmount.from_api(money.amount)


def _money(kopecks: int, currency: str) -> MoneyValue:
    return MoneyValue(amount=RubleAmount(kopecks).to_api(), currency=currency)


def _flow_response(session: Session, flow: Any) -> ExternalFlowResponse:
    transfer_status = external_flow_transfer_status(session, flow)
    return ExternalFlowResponse(
        id=flow.id,
        reporting_month_id=flow.reporting_month_id,
        account_id=flow.account_id,
        event_date=flow.event_date,
        boundary_amount=_money(flow.boundary_amount_kopecks, flow.currency),
        direction=flow.direction,
        kind=flow.kind,
        currency=flow.currency,
        transfer_link_id=flow.transfer_link_id,
        transfer_status=transfer_status.value if transfer_status is not None else None,
        portfolio_scope_classification=classify_external_flow(
            session, flow.id, scope="portfolio"
        ).value,
        account_scope_classification=classify_external_flow(
            session, flow.id, scope="account", account_id=flow.account_id
        ).value,
        source=flow.source,
        notes=flow.notes,
    )


def _transfer_link_response(session: Session, link: Any) -> TransferLinkResponse:
    return TransferLinkResponse(
        id=link.id,
        transfer_key=link.transfer_key,
        status=link.status,
        flow_ids=[flow.id for flow in transfer_link_legs(session, link.id)],
        notes=link.notes,
    )


@router.get("/api/external-flows", response_model=list[ExternalFlowResponse])
def list_external_flows_endpoint(
    month_id: int | None = Query(default=None),
    account_id: int | None = Query(default=None),
    transfer_link_id: int | None = Query(default=None),
    session: Session = Depends(session_for_request),
) -> list[ExternalFlowResponse]:
    flows = list_external_flows(
        session,
        reporting_month_id=month_id,
        account_id=account_id,
        transfer_link_id=transfer_link_id,
    )
    return [_flow_response(session, flow) for flow in flows]


@router.post(
    "/api/external-flows",
    response_model=ExternalFlowResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_external_flow_endpoint(
    payload: ExternalFlowCreate,
    session: Session = Depends(session_for_request),
) -> ExternalFlowResponse:
    flow = create_external_flow(
        session,
        reporting_month_id=payload.reporting_month_id,
        account_id=payload.account_id,
        event_date=payload.event_date,
        boundary_amount=_amount(payload.boundary_amount),
        direction=payload.direction,
        kind=payload.kind,
        transfer_link_id=payload.transfer_link_id,
        currency=payload.boundary_amount.currency,
        source=payload.source,
        notes=payload.notes,
    )
    return _flow_response(session, flow)


@router.get("/api/external-flows/{flow_id}", response_model=ExternalFlowResponse)
def get_external_flow_endpoint(
    flow_id: int,
    session: Session = Depends(session_for_request),
) -> ExternalFlowResponse:
    return _flow_response(session, get_external_flow(session, flow_id))


@router.patch("/api/external-flows/{flow_id}", response_model=ExternalFlowResponse)
def update_external_flow_endpoint(
    flow_id: int,
    payload: ExternalFlowUpdate,
    session: Session = Depends(session_for_request),
) -> ExternalFlowResponse:
    kwargs: dict[str, object] = {
        "account_id": payload.account_id,
        "event_date": payload.event_date,
        "boundary_amount": (
            _amount(payload.boundary_amount) if payload.boundary_amount is not None else None
        ),
        "direction": payload.direction,
        "kind": payload.kind,
        "source": payload.source,
        "notes": payload.notes,
    }
    if "transfer_link_id" in payload.model_fields_set:
        kwargs["transfer_link_id"] = payload.transfer_link_id
    flow = update_external_flow(session, flow_id, **kwargs)
    return _flow_response(session, flow)


@router.delete("/api/external-flows/{flow_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_external_flow_endpoint(
    flow_id: int,
    session: Session = Depends(session_for_request),
) -> None:
    delete_external_flow(session, flow_id)


@router.get("/api/transfer-links", response_model=list[TransferLinkResponse])
def list_transfer_links_endpoint(
    session: Session = Depends(session_for_request),
) -> list[TransferLinkResponse]:
    return [
        _transfer_link_response(session, link) for link in list_external_transfer_links(session)
    ]


@router.post(
    "/api/transfer-links",
    response_model=TransferLinkResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_transfer_link_endpoint(
    payload: TransferLinkCreate,
    session: Session = Depends(session_for_request),
) -> TransferLinkResponse:
    link = create_external_transfer_link(
        session,
        transfer_key=payload.transfer_key,
        flow_ids=payload.flow_ids,
        notes=payload.notes,
    )
    return _transfer_link_response(session, link)


@router.get("/api/transfer-links/{link_id}", response_model=TransferLinkResponse)
def get_transfer_link_endpoint(
    link_id: int,
    session: Session = Depends(session_for_request),
) -> TransferLinkResponse:
    return _transfer_link_response(session, get_external_transfer_link(session, link_id))


@router.patch("/api/transfer-links/{link_id}", response_model=TransferLinkResponse)
def update_transfer_link_endpoint(
    link_id: int,
    payload: TransferLinkUpdate,
    session: Session = Depends(session_for_request),
) -> TransferLinkResponse:
    link = update_external_transfer_link(
        session,
        link_id,
        transfer_key=payload.transfer_key,
        notes=payload.notes,
    )
    return _transfer_link_response(session, link)


@router.delete("/api/transfer-links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_transfer_link_endpoint(
    link_id: int,
    session: Session = Depends(session_for_request),
) -> None:
    delete_external_transfer_link(session, link_id)


@router.post(
    "/api/transfer-links/{link_id}/flows/{flow_id}",
    response_model=TransferLinkResponse,
)
def attach_transfer_leg_endpoint(
    link_id: int,
    flow_id: int,
    session: Session = Depends(session_for_request),
) -> TransferLinkResponse:
    update_external_flow(session, flow_id, transfer_link_id=link_id)
    return _transfer_link_response(session, get_external_transfer_link(session, link_id))


@router.delete(
    "/api/transfer-links/{link_id}/flows/{flow_id}",
    response_model=TransferLinkResponse,
)
def detach_transfer_leg_endpoint(
    link_id: int,
    flow_id: int,
    session: Session = Depends(session_for_request),
) -> TransferLinkResponse:
    flow = get_external_flow(session, flow_id)
    if flow.transfer_link_id != link_id:
        raise ValueError("external flow is not attached to this transfer link")
    update_external_flow(session, flow_id, transfer_link_id=None)
    return _transfer_link_response(session, get_external_transfer_link(session, link_id))
