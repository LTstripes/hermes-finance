"""Finite, explicit historical membership corrections; no inferred history."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from hashlib import sha256

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from hermes_finance.persistence import (
    Account,
    CashBalance,
    CashBoundaryCoverage,
    ExternalFlow,
    ExternalFlowBoundaryGroup,
    ExternalFlowBoundaryGroupMember,
    ExternalTransferLink,
    ExternalTransferReconciliationEvidence,
    InKindBoundaryCoverage,
    InKindMovement,
    ObservedValuationPoint,
    ReportingMonth,
)
from hermes_finance.persistence import (
    AccountPerformanceScopeMembership as Membership,
)
from hermes_finance.services.valuation_boundaries import (
    boundary_group_flows,
    validate_external_flow_boundary_group_members,
)


@dataclass(frozen=True)
class Interval:
    effective_from: date
    effective_to: date
    include_in_returns: bool


def history(session: Session, account_id: int) -> list[Membership]:
    return list(
        session.scalars(
            select(Membership)
            .where(Membership.account_id == account_id)
            .order_by(Membership.effective_from, Membership.id)
        )
    )


def state_identity(session: Session) -> str:
    """Conservative conflict detection, distinct from financial material identity.

    Includes all potential targets, including captures/groups not yet observed.
    A form may propose dates outside the displayed return interval.
    """
    digest = sha256(b"historical-membership-form-v1")
    for model in (
        Account,
        Membership,
        ReportingMonth,
        CashBalance,
        CashBoundaryCoverage,
        InKindBoundaryCoverage,
        ExternalFlow,
        ExternalTransferLink,
        ExternalTransferReconciliationEvidence,
        InKindMovement,
        ExternalFlowBoundaryGroup,
        ExternalFlowBoundaryGroupMember,
        ObservedValuationPoint,
    ):
        table = model.__table__
        digest.update(table.name.encode())
        for row in session.execute(select(table).order_by(*table.primary_key.columns)):
            digest.update(json.dumps(tuple(row), default=str, separators=(",", ":")).encode())
    return digest.hexdigest()


def _overlap(start: date, end: date | None, intervals: list[Interval]) -> bool:
    return any(
        start <= item.effective_to and (end is None or end >= item.effective_from)
        for item in intervals
    )


def _target(session: Session, point: ObservedValuationPoint) -> tuple[date, int]:
    """Resolve canonical identity even when the stored date/parent is corrupt."""
    if (point.external_flow_id is None) == (point.boundary_group_id is None):
        raise ValueError("Unresolvable observation target; correction blocked")
    if point.external_flow_id is not None:
        target = session.get(ExternalFlow, point.external_flow_id)
        if target is None:
            raise ValueError("Unresolvable observation flow; correction blocked")
        if point.scope == "account" and target.account_id != point.account_id:
            raise ValueError("Inconsistent observation account; correction blocked")
        return target.event_date, target.reporting_month_id
    group = session.get(ExternalFlowBoundaryGroup, point.boundary_group_id)
    if group is None or (group.scope, group.account_id) != (point.scope, point.account_id):
        raise ValueError("Unresolvable observation group; correction blocked")
    validate_external_flow_boundary_group_members(group, boundary_group_flows(session, group.id))
    return group.boundary_date, group.reporting_month_id


def stage_replace(
    session: Session,
    *,
    account_id: int,
    expected_identity: str,
    replaced_ids: list[int],
    replacements: list[Interval],
) -> dict[str, object]:
    """Reserve, compare, validate, replace and invalidate without committing."""
    if session.new or session.dirty or session.deleted:
        raise ValueError("Membership write requires a clean session")
    session.execute(text("UPDATE reporting_months SET status = status WHERE 0"))
    session.expire_all()
    if state_identity(session) != expected_identity:
        raise ValueError("Membership evidence changed; reread before saving")
    if session.get(Account, account_id) is None:
        raise ValueError("Account not found")
    rows = history(session, account_id)
    by_id = {row.id: row for row in rows}
    if len(set(replaced_ids)) != len(replaced_ids) or any(i not in by_id for i in replaced_ids):
        raise ValueError("Replaced identities must be unique rows of this account")
    old = [by_id[i] for i in replaced_ids]
    if any(row.effective_to is None for row in old):
        raise ValueError("Open-ended membership is read-only")
    if not old and not replacements:
        raise ValueError("No explicit membership change")
    for item in replacements:
        if item.effective_from > item.effective_to:
            raise ValueError("Finite inclusive intervals must have ordered dates")
    remaining = [row for row in rows if row.id not in replaced_ids]
    resulting = sorted(
        [
            *((r.effective_from, r.effective_to) for r in remaining),
            *((r.effective_from, r.effective_to) for r in replacements),
        ],
        key=lambda item: item[0],
    )
    for previous, following in zip(resulting, resulting[1:]):
        if previous[1] is None or previous[1] >= following[0]:
            raise ValueError("Every overlap is rejected; correct ambiguous rows as one set")
    # Do not bridge gaps: each complete old and new interval remains separate.
    affected = [
        *replacements,
        *(Interval(r.effective_from, r.effective_to, r.include_in_returns) for r in old),
    ]
    months = {month.id: month for month in session.scalars(select(ReportingMonth))}
    closed = {
        month.id
        for month in months.values()
        if month.status == "closed"
        and (
            _overlap(month.period_start, month.period_end, affected)
            or (
                month.snapshot_date is not None
                and _overlap(month.snapshot_date, month.snapshot_date, affected)
            )
        )
    }
    observations = []
    for point in session.scalars(
        select(ObservedValuationPoint)
        .where(
            (ObservedValuationPoint.scope == "portfolio")
            | (
                (ObservedValuationPoint.scope == "account")
                & (ObservedValuationPoint.account_id == account_id)
            )
        )
        .order_by(ObservedValuationPoint.id)
    ):
        target_date, target_month_id = _target(session, point)
        if not (
            _overlap(point.observed_date, point.observed_date, affected)
            or _overlap(target_date, target_date, affected)
        ):
            continue
        for month_id in (point.reporting_month_id, target_month_id):
            if month_id not in months:
                raise ValueError("Unresolvable observation parent; correction blocked")
            if months[month_id].status == "closed":
                closed.add(month_id)
        observations.append(point)
    if closed:
        raise ValueError(
            "Reopen affected reporting months before correction: "
            + ", ".join(str(i) for i in sorted(closed))
        )
    changed_coverages: dict[str, list[int]] = {}
    for model in (CashBoundaryCoverage, InKindBoundaryCoverage):
        changed_coverages[model.__tablename__] = []
        for row in session.scalars(
            select(model).where(model.account_id == account_id, model.coverage_state == "complete")
        ):
            if _overlap(row.covered_from, row.covered_to, affected):
                row.coverage_state = "unknown"
                changed_coverages[model.__tablename__].append(row.id)
    retired = [point.id for point in observations]
    # Report material identities even when an in-flight capture has no stored side.
    targets = []
    for flow in session.scalars(select(ExternalFlow).order_by(ExternalFlow.id)):
        if _overlap(flow.event_date, flow.event_date, affected):
            scopes = [("portfolio", None)]
            if flow.account_id == account_id:
                scopes.append(("account", account_id))
            for scope, selected_id in scopes:
                targets.append(
                    (
                        scope,
                        selected_id,
                        "flow",
                        flow.id,
                        flow.reporting_month_id,
                        flow.event_date.isoformat(),
                    )
                )
    for group in session.scalars(
        select(ExternalFlowBoundaryGroup).order_by(ExternalFlowBoundaryGroup.id)
    ):
        if (group.scope == "portfolio" or group.account_id == account_id) and _overlap(
            group.boundary_date, group.boundary_date, affected
        ):
            validate_external_flow_boundary_group_members(
                group, boundary_group_flows(session, group.id)
            )
            targets.append(
                (
                    group.scope,
                    group.account_id,
                    "group",
                    group.id,
                    group.reporting_month_id,
                    group.boundary_date.isoformat(),
                )
            )
    for row in observations:
        session.delete(row)
    for row in old:
        session.delete(row)
    session.flush()
    for item in replacements:
        session.add(
            Membership(
                account_id=account_id,
                effective_from=item.effective_from,
                effective_to=item.effective_to,
                include_in_returns=item.include_in_returns,
            )
        )
    session.flush()
    return {
        "retired_observation_ids": retired,
        "targets": targets,
        "invalidated_coverages": changed_coverages,
        "affected_intervals": [(r.effective_from, r.effective_to) for r in affected],
        "identity": state_identity(session),
    }
