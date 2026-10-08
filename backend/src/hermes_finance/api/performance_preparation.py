"""Coherent ledger inspection for Owner data preparation; no historical writer."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.api.cash import CashBalanceResponse
from hermes_finance.api.cash import _response as cash_response
from hermes_finance.api.cash_boundary_coverage import CashBoundaryCoverageResponse
from hermes_finance.api.cash_boundary_coverage import _response as coverage_response
from hermes_finance.api.external_flows import (
    ExternalFlowResponse,
    TransferLinkResponse,
    _flow_response,
    _transfer_link_response,
)
from hermes_finance.api.in_kind_boundary_coverage import (
    InKindBoundaryCoverageResponse,
    InKindMovementResponse,
    _coverage_response,
    _movement_response,
)
from hermes_finance.api.performance_evidence_guard import evidence_signature
from hermes_finance.api.settings import session_for_request
from hermes_finance.database import coherent_read_snapshot
from hermes_finance.persistence import Account, CashBalance, ReportingMonth
from hermes_finance.services.cash_boundary_coverage import list_cash_boundary_coverages
from hermes_finance.services.external_flows import list_external_flows, list_external_transfer_links
from hermes_finance.services.in_kind_boundary_coverage import (
    list_in_kind_boundary_coverages,
    list_in_kind_movements,
)

router = APIRouter(prefix="/api/performance/preparation", tags=["performance"])


class PreparationMonth(BaseModel):
    id: int
    period_start: date
    period_end: date
    status: str


class PreparationResponse(BaseModel):
    account_id: int
    start_date: date
    end_date: date
    evidence_token: str
    flows: list[ExternalFlowResponse]
    transfer_links: list[TransferLinkResponse]
    cash_coverages: list[CashBoundaryCoverageResponse]
    in_kind_coverages: list[InKindBoundaryCoverageResponse]
    movements: list[InKindMovementResponse]
    cash_balances: list[CashBalanceResponse]
    months: list[PreparationMonth]


@router.get("", response_model=PreparationResponse)
def read_preparation(
    account_id: int = Query(gt=0),
    start_date: date = Query(),
    end_date: date = Query(),
    session: Session = Depends(session_for_request),
) -> PreparationResponse:
    if start_date >= end_date:
        raise HTTPException(422, "start_date must precede end_date")
    with coherent_read_snapshot(session):
        if session.get(Account, account_id) is None:
            raise HTTPException(404, "account not found")
        # Include both calendar overlap and boundary snapshots; never infer dates.
        months = list(
            session.scalars(
                select(ReportingMonth)
                .where(
                    (
                        (ReportingMonth.period_start <= end_date)
                        & (ReportingMonth.period_end >= start_date)
                    )
                    | ReportingMonth.snapshot_date.in_((start_date, end_date))
                )
                .order_by(ReportingMonth.period_start, ReportingMonth.id)
            )
        )
        month_ids = [m.id for m in months]
        return PreparationResponse(
            account_id=account_id,
            start_date=start_date,
            end_date=end_date,
            evidence_token=evidence_signature(session),
            transfer_links=[
                _transfer_link_response(session, link)
                for link in list_external_transfer_links(session)
            ],
            flows=[
                _flow_response(session, f)
                for f in list_external_flows(session, account_id=account_id)
                if start_date <= f.event_date <= end_date
            ],
            cash_coverages=[
                coverage_response(r, session)
                for r in list_cash_boundary_coverages(session, account_id=account_id)
                if r.covered_from <= end_date and r.covered_to >= start_date
            ],
            in_kind_coverages=[
                _coverage_response(r, session)
                for r in list_in_kind_boundary_coverages(session, account_id=account_id)
                if r.covered_from <= end_date and r.covered_to >= start_date
            ],
            movements=[
                _movement_response(r)
                for r in list_in_kind_movements(session, account_id=account_id)
                if start_date <= r.event_date <= end_date
            ],
            cash_balances=[
                cash_response(r)
                for r in session.scalars(
                    select(CashBalance)
                    .where(
                        CashBalance.reporting_month_id.in_(month_ids),
                        (CashBalance.account_id == account_id) | CashBalance.account_id.is_(None),
                    )
                    .order_by(CashBalance.id)
                )
            ],
            months=[
                PreparationMonth(
                    id=m.id, period_start=m.period_start, period_end=m.period_end, status=m.status
                )
                for m in months
            ],
        )
