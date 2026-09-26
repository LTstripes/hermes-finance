"""Bounded material identity for observed external-flow valuation evidence."""

from __future__ import annotations

import json
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.persistence import (
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
    external_flow_id: int | None = None,
    boundary_group_id: int | None = None,
) -> str | None:
    """Hash current material fields; return None for a missing/corrupt target.

    Callers that persist evidence must first acquire a writer reservation and
    pass the signature recorded when an asynchronous capture began.
    """

    if (external_flow_id is None) == (boundary_group_id is None):
        raise ValueError("exactly one boundary target is required")
    if external_flow_id is not None:
        flow = session.get(ExternalFlow, external_flow_id, populate_existing=True)
        if flow is None:
            return None
        material: tuple[object, ...] = ("flow", _flow_material(flow))
    else:
        group = session.get(ExternalFlowBoundaryGroup, boundary_group_id, populate_existing=True)
        if group is None:
            return None
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
    encoded = json.dumps(("observed-valuation-material-v1", material), separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()
