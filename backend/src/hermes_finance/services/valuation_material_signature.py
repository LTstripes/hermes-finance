"""Bounded material identity for observed external-flow valuation evidence."""

from __future__ import annotations

import json
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.persistence import (
    Account,
    AccountPerformanceScopeMembership,
    ExternalFlow,
    ExternalFlowBoundaryGroup,
    ExternalFlowBoundaryGroupMember,
)


def _flow_material(flow: ExternalFlow) -> tuple[object, ...]:
    # Keep these economic fields aligned with external_flows' invalidation rule.
    return (
        flow.id,
        flow.reporting_month_id,
        flow.account_id,
        flow.event_date.isoformat(),
        flow.boundary_amount_kopecks,
        flow.direction,
        flow.kind,
        flow.currency,
        flow.scope_membership,
        flow.transfer_link_id,
    )


def material_signature_for_boundary(
    session: Session,
    *,
    scope: str,
    account_id: int | None,
    external_flow_id: int | None = None,
    boundary_group_id: int | None = None,
) -> str | None:
    """Hash current material fields; return None for a missing/corrupt target.

    Callers that persist evidence must first acquire a writer reservation and
    pass the signature recorded when an asynchronous capture began.
    Capture producers read target identity and this signature in one coherent
    snapshot associated with the observed values, never by re-signing at submit.
    """

    if (external_flow_id is None) == (boundary_group_id is None):
        raise ValueError("exactly one boundary target is required")
    if external_flow_id is not None:
        flow = session.get(ExternalFlow, external_flow_id, populate_existing=True)
        if flow is None:
            return None
        material: tuple[object, ...] = ("flow", _flow_material(flow))
        boundary_date = flow.event_date
        if scope == "account" and flow.account_id != account_id:
            return None
    else:
        group = session.get(ExternalFlowBoundaryGroup, boundary_group_id, populate_existing=True)
        if group is None:
            return None
        if (group.scope, group.account_id) != (scope, account_id):
            return None
        boundary_date = group.boundary_date
        member_ids = list(
            session.scalars(
                select(ExternalFlowBoundaryGroupMember.external_flow_id)
                .where(ExternalFlowBoundaryGroupMember.boundary_group_id == group.id)
                .order_by(ExternalFlowBoundaryGroupMember.external_flow_id)
            )
        )
        if not member_ids:
            return None
        flows = [
            session.get(ExternalFlow, flow_id, populate_existing=True) for flow_id in member_ids
        ]
        if any(flow is None for flow in flows):
            return None
        material = (
            "group",
            group.id,
            group.reporting_month_id,
            group.scope,
            group.account_id,
            group.boundary_date.isoformat(),
            tuple(_flow_material(flow) for flow in flows if flow is not None),
        )
    if scope not in {"account", "portfolio"} or (scope == "account") != (account_id is not None):
        return None
    accounts = list(session.scalars(select(Account.id).order_by(Account.id)))
    if scope == "account":
        if account_id not in accounts:
            return None
        accounts = [account_id]
    membership_material = []
    for selected_id in accounts:
        rows = list(
            session.scalars(
                select(AccountPerformanceScopeMembership)
                .where(
                    AccountPerformanceScopeMembership.account_id == selected_id,
                    AccountPerformanceScopeMembership.effective_from <= boundary_date,
                    (AccountPerformanceScopeMembership.effective_to.is_(None))
                    | (AccountPerformanceScopeMembership.effective_to >= boundary_date),
                )
                .order_by(AccountPerformanceScopeMembership.id)
                .execution_options(populate_existing=True)
            )
        )
        if len(rows) != 1:
            return None
        membership_material.append(
            (
                selected_id,
                tuple(
                    (
                        row.id,
                        row.account_id,
                        row.effective_from.isoformat(),
                        row.effective_to.isoformat() if row.effective_to is not None else None,
                        row.include_in_returns,
                    )
                    for row in rows
                ),
            )
        )
    encoded = json.dumps(
        (
            "observed-valuation-material-v2",
            scope,
            account_id,
            boundary_date.isoformat(),
            material,
            membership_material,
        ),
        separators=(",", ":"),
    )
    return sha256(encoded.encode("utf-8")).hexdigest()
