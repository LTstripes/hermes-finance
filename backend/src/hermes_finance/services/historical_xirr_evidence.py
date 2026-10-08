"""Read-only H3 inputs from effective H1/H2 authority; no legacy/source mixing."""

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.domain import ExternalFlowClassification, PerformanceScope
from hermes_finance.domain.historical_owner_flows import COMPATIBLE_FLOW_CONTRACT
from hermes_finance.persistence import HistoricalEndpointRevision, HistoricalOwnerFlow
from hermes_finance.services.cash_boundary_coverage import cash_boundary_coverage_for_interval
from hermes_finance.services.historical_endpoints import endpoint_key, read_historical_endpoint
from hermes_finance.services.historical_owner_flows import read_historical_owner_flow
from hermes_finance.services.historical_portfolio_flows import read_historical_portfolio_flow
from hermes_finance.services.in_kind_boundary_coverage import in_kind_boundary_coverage_for_interval
from hermes_finance.services.performance_availability import (
    _excluded_source_reason_codes,
    _performance_currency,
    _portfolio_transfer_safety,
    _scope_membership_coverage,
)
from hermes_finance.statement_import.mybroker import MyBrokerError


@dataclass(frozen=True)
class HistoricalXirrEvidence:
    performance_currency: str
    opening_kopecks: int
    closing_kopecks: int
    flows: tuple[tuple[date, ExternalFlowClassification, int], ...]
    reason_codes: tuple[str, ...]


def historical_xirr_evidence(
    session: Session,
    *,
    start_date: date,
    end_date: date,
    scope: PerformanceScope,
    account_id: int | None,
) -> HistoricalXirrEvidence | None:
    """Build within the XIRR caller's coherent snapshot after legacy refusal.

    Absence of H1 at the requested boundaries preserves the legacy diagnostics.
    Once an H1 identity exists, every source gate must pass independently. Retired
    identities still select this path and can never fall back to a legacy side.
    """
    membership, rows_by_account = _scope_membership_coverage(
        session, scope=scope, account_id=account_id, start_date=start_date, end_date=end_date
    )
    if (
        session.scalar(
            select(HistoricalEndpointRevision.id)
            .where(
                HistoricalEndpointRevision.account_id.in_(membership.account_ids),
                HistoricalEndpointRevision.valuation_date.in_((start_date, end_date)),
            )
            .limit(1)
        )
        is None
    ):
        return None

    currency, reasons = _performance_currency(session)
    reasons.update(
        _excluded_source_reason_codes(
            session,
            scope=scope,
            membership=membership,
            rows_by_account=rows_by_account,
            start_date=start_date,
            end_date=end_date,
        )
    )
    reasons.update(membership.reason_codes)
    required_ids = (
        (account_id,)
        if scope is PerformanceScope.ACCOUNT
        else tuple(
            identity
            for identity, rows in rows_by_account.items()
            if any(
                row.include_in_returns
                and row.effective_from <= end_date
                and (row.effective_to is None or row.effective_to >= start_date)
                for row in rows
            )
        )
    )
    if not required_ids:
        reasons.add("not_computable_scope_coverage_incomplete")
    in_kind = in_kind_boundary_coverage_for_interval(
        session,
        scope=scope,
        account_id=account_id,
        start_date=start_date,
        end_date=end_date,
        rows_by_account=rows_by_account,
    )
    reasons.update(in_kind.reason_codes)
    if scope is PerformanceScope.PORTFOLIO:
        shared, xirr, _ = _portfolio_transfer_safety(
            session,
            start_date=start_date,
            end_date=end_date,
            xirr_required_dates={start_date, end_date},
            twrr_required_dates=set(),
            rows_by_account=rows_by_account,
        )
        reasons.update(shared)
        reasons.update(xirr)
    totals = [0, 0]
    for identity in required_ids:
        for index, (day, role) in enumerate(((start_date, "opening"), (end_date, "closing"))):
            try:
                endpoint = read_historical_endpoint(session, endpoint_key(identity, day))
            except MyBrokerError:
                reasons.add(f"not_computable_{role}_valuation_missing")
                continue
            amount = endpoint["total_value_kopecks"]
            if (
                endpoint["effective_state"] != "accepted"
                or type(amount) is not int
                or amount < 0
                or endpoint["currency"] != currency
            ):
                reasons.add("not_computable_historical_endpoint_ineffective")
            else:
                totals[index] += amount

        # The shared assessor validates the effective COMPLETE union for this
        # exact window, including every H2-A1 revision/occurrence. Adjacent slices
        # are valid; source-free evidence, overlaps, gaps and retired rows fail.
        window_start = start_date + timedelta(days=1)
        coverage = cash_boundary_coverage_for_interval(
            session,
            scope=PerformanceScope.ACCOUNT,
            account_id=identity,
            start_date=window_start,
            end_date=end_date,
            rows_by_account=rows_by_account,
            ledger_binding=COMPATIBLE_FLOW_CONTRACT,
        )
        reasons.update(coverage.reason_codes)
        if coverage.status != "complete":
            reasons.add("not_computable_external_flows_incomplete")

    statement = (
        select(HistoricalOwnerFlow)
        .where(
            HistoricalOwnerFlow.event_date > start_date,
            HistoricalOwnerFlow.event_date <= end_date,
        )
        .order_by(HistoricalOwnerFlow.event_date, HistoricalOwnerFlow.id)
    )
    if scope is PerformanceScope.ACCOUNT:
        statement = statement.where(HistoricalOwnerFlow.account_id == account_id)
    flows = []
    for flow in session.scalars(statement):
        try:
            view = (
                read_historical_owner_flow(session, flow.id)
                if scope is PerformanceScope.ACCOUNT
                else read_historical_portfolio_flow(session, flow.id)
            )
        except MyBrokerError:
            reasons.add("not_computable_historical_owner_flow_ineffective")
            continue
        authority = view[
            "account_scope" if scope is PerformanceScope.ACCOUNT else "portfolio_scope"
        ]
        if scope is PerformanceScope.PORTFOLIO and authority["status"] == "not_in_scope":
            continue
        if authority["status"] != "authoritative":
            reasons.add(
                "not_computable_historical_portfolio_flow_unknown"
                if scope is PerformanceScope.PORTFOLIO
                else "not_computable_historical_owner_flow_ineffective"
            )
            continue
        amount = view["boundary_amount_kopecks"]
        if type(amount) is not int or amount < 0 or view["core"]["currency"] != currency:
            reasons.add("not_computable_external_flows_incomplete")
            continue
        flows.append(
            (flow.event_date, ExternalFlowClassification(authority["classification"]), amount)
        )
    return HistoricalXirrEvidence(currency, *totals, tuple(flows), tuple(sorted(reasons)))
