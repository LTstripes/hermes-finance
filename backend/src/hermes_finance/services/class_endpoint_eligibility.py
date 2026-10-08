"""C2/endpoint-C3: explicit RUB class evidence. No return solvers or providers."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from decimal import Decimal
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.database import coherent_read_operation
from hermes_finance.domain import PerformanceScope
from hermes_finance.persistence import (
    APP_SETTINGS_ID,
    AppSettings,
    ClassNoCrossingCoverage,
    ExecutedTradeRevision,
    InKindMovement,
    InvestmentCashFlow,
    PositionSnapshot,
    ReportingMonth,
)
from hermes_finance.services._guard import reserve_reporting_month_interval_writer
from hermes_finance.services.concurrency import ConcurrencyError
from hermes_finance.services.executed_trades import unresolved_execution_ids
from hermes_finance.services.mybroker_dispositions import REASON, impact
from hermes_finance.services.mybroker_import import unresolved_class_source_ids
from hermes_finance.services.performance_availability import (
    _membership_at,
    _scope_membership_coverage,
)
from hermes_finance.services.reporting_months import ClosedReportingMonthError

SUPPORTED_CLASSES = frozenset({"stock", "bond", "gold"})


def _interval(start: date, end: date) -> None:
    if type(start) is not date or type(end) is not date or start >= end:
        raise ValueError("an ordered, non-empty date interval is required")


def _facts(session: Session, asset_class: str, start: date, end: date) -> dict:
    """Read only current persisted material, under a read snapshot or writer lock."""
    reasons = set()
    membership, rows_by_account = _scope_membership_coverage(
        session,
        scope=PerformanceScope.PORTFOLIO,
        account_id=None,
        start_date=start,
        end_date=end,
    )
    if membership.reason_codes:
        reasons.add("membership_incomplete_or_changed")
    accounts = tuple(
        account_id
        for account_id in membership.account_ids
        if _membership_at(rows_by_account.get(account_id, []), start) is True
        and _membership_at(rows_by_account.get(account_id, []), end) is True
    )
    if not accounts:
        reasons.add("historical_universe_empty")
    exclusions = impact(session, accounts)
    if exclusions:
        reasons.add(REASON)
    source_ids = unresolved_class_source_ids(session, accounts, start, end)
    if source_ids:
        reasons.add("mybroker_class_reconciliation_required")
    execution_ids = unresolved_execution_ids(session, accounts, start, end)
    if execution_ids:
        reasons.add("mybroker_class_reconciliation_required")
    months = list(
        session.scalars(
            select(ReportingMonth)
            .where(
                ReportingMonth.snapshot_date >= start,
                ReportingMonth.snapshot_date <= end,
            )
            .order_by(ReportingMonth.snapshot_date, ReportingMonth.id)
        )
    )
    endpoints = [[m for m in months if m.snapshot_date == day] for day in (start, end)]
    actual = [group[0].snapshot_date if len(group) == 1 else None for group in endpoints]
    if any(len(group) != 1 for group in endpoints):
        reasons.add("exact_endpoint_missing_or_ambiguous")
    if any(m.status != "closed" for m in months):
        reasons.add("reporting_month_not_closed")
    settings = session.get(AppSettings, APP_SETTINGS_ID)
    currency = "RUB" if settings is None else settings.base_currency
    if currency != "RUB":
        reasons.add("unsupported_currency")
    positions = list(
        session.scalars(
            select(PositionSnapshot)
            .where(
                PositionSnapshot.account_id.in_(accounts),
                PositionSnapshot.reporting_month_id.in_([m.id for m in months]),
            )
            .order_by(PositionSnapshot.id)
        )
    )
    # Archived rows in the interval are retained facts, never silent exclusions.
    archived = list(
        session.scalars(
            select(PositionSnapshot)
            .where(
                PositionSnapshot.account_id.in_(accounts),
                PositionSnapshot.reporting_month_id.is_(None),
                PositionSnapshot.archived_from_period >= start.strftime("%Y-%m"),
                PositionSnapshot.archived_from_period <= end.strftime("%Y-%m"),
            )
            .order_by(PositionSnapshot.id)
        )
    )
    history = positions + archived
    identities = defaultdict(set)
    for p in history:
        identities[p.instrument_id].add(p.historical_instrument_type)
    if any(p.historical_instrument_type is None for p in history):
        reasons.add("historical_class_unknown")
    for kinds in identities.values():
        if asset_class in kinds and len(kinds) != 1:
            reasons.add("historical_class_reclassified")
    relevant = [p for p in history if p.historical_instrument_type in (asset_class, None)]
    if any(p in archived for p in relevant):
        reasons.add("archived_position_incomplete")

    def event_class(instrument_id: int | None) -> str | None:
        kinds = identities.get(instrument_id, set())
        return next(iter(kinds)) if len(kinds) == 1 else None

    flows = list(
        session.scalars(
            select(InvestmentCashFlow)
            .where(
                InvestmentCashFlow.account_id.in_(accounts),
                InvestmentCashFlow.event_date >= start,
                InvestmentCashFlow.event_date <= end,
            )
            .order_by(InvestmentCashFlow.id)
        )
    )
    relevant_flows = []
    for flow in flows:
        kind = event_class(flow.instrument_id)
        # Unallocated account-level cash contributions alone say nothing about
        # a security class. Income/cost/other facts without class proof block.
        if flow.instrument_id is None and flow.flow_type in {"deposit", "withdrawal"}:
            continue
        if kind is None:
            reasons.add("cash_flow_class_unknown")
        if kind in (asset_class, None):
            relevant_flows.append(flow)
            reasons.add("known_cash_crossing")
    movements = list(
        session.scalars(
            select(InKindMovement)
            .where(
                InKindMovement.event_date >= start,
                InKindMovement.event_date <= end,
                (
                    InKindMovement.source_account_id.in_(accounts)
                    | InKindMovement.destination_account_id.in_(accounts)
                ),
            )
            .order_by(InKindMovement.event_date, InKindMovement.id)
        )
    )
    transfers = []
    relevant_movements = []
    for movement in movements:
        kind = event_class(movement.instrument_id)
        if kind not in (asset_class, None):
            continue
        relevant_movements.append(movement)
        if kind is None:
            reasons.add("in_kind_class_unknown")
        if movement.movement_kind != "internal_transfer":
            reasons.add("external_in_kind_crossing")
        elif (
            kind != asset_class
            or movement.quantity is None
            or movement.source_account_id not in accounts
            or movement.destination_account_id not in accounts
            or movement.provenance_kind != "owner_attestation"
        ):
            reasons.add("internal_transfer_ambiguous")
        else:
            transfers.append(movement)

    # Exact per-account quantity reconciliation across every observed interval.
    # An internal marker is one two-account movement, not inferred leg matching.
    snapshots = {}
    for month in months:
        snapshots[month.id] = {
            (p.account_id, p.instrument_id): p.quantity
            for p in positions
            if p.reporting_month_id == month.id and p.historical_instrument_type == asset_class
        }
    used = set()
    for opening, closing in zip(months, months[1:]):
        before, after = snapshots[opening.id], snapshots[closing.id]
        expected = defaultdict(Decimal)
        for movement in transfers:
            if opening.snapshot_date < movement.event_date <= closing.snapshot_date:
                used.add(movement.id)
                expected[(movement.source_account_id, movement.instrument_id)] -= movement.quantity
                expected[(movement.destination_account_id, movement.instrument_id)] += (
                    movement.quantity
                )
                # Both ends of the transfer need historical identity evidence.
                if (movement.source_account_id, movement.instrument_id) not in before or (
                    movement.destination_account_id,
                    movement.instrument_id,
                ) not in after:
                    reasons.add("internal_transfer_ambiguous")
        for key in before.keys() | after.keys() | expected.keys():
            delta = after.get(key, Decimal(0)) - before.get(key, Decimal(0))
            if delta != expected[key]:
                reasons.add(
                    "position_set_changed"
                    if key not in before or key not in after
                    else "position_quantity_changed"
                )
                if expected[key]:
                    reasons.add("internal_transfer_ambiguous")
    if any(m.id not in used for m in transfers):
        reasons.add("internal_transfer_ambiguous")
    values = [None, None]
    for index, group in enumerate(endpoints):
        if len(group) == 1:
            component_rows = [
                p
                for p in positions
                if p.reporting_month_id == group[0].id
                and p.historical_instrument_type == asset_class
            ]
            if not component_rows:
                reasons.add("class_endpoint_empty")
            values[index] = sum(p.market_value_kopecks for p in component_rows)
    # Current catalogue labels/flags/quotes/metadata are deliberately absent.
    material = {
        "class": asset_class,
        "dates": (start, end),
        "currency": currency,
        # The accepted PositionSnapshot money path persists RUB totals, including
        # its existing bond accrued-interest basis. Catalogue currency is metadata.
        "valuation_basis": "persisted_rub_market_value_kopecks",
        "accounts": accounts,
        "memberships": [
            (r.id, r.account_id, r.effective_from, r.effective_to, r.include_in_returns)
            for rows in rows_by_account.values()
            for r in rows
        ],
        "months": [(m.id, m.snapshot_date, m.period_start, m.period_end) for m in months],
        "positions": [
            (
                p.id,
                p.reporting_month_id,
                p.archived_from_period,
                p.account_id,
                p.instrument_id,
                p.historical_instrument_type,
                str(p.quantity),
                p.market_value_kopecks,
            )
            for p in relevant
        ],
        "flows": [
            (
                f.id,
                f.account_id,
                f.instrument_id,
                f.event_date,
                f.flow_type,
                f.gross_amount_kopecks,
                f.tax_amount_kopecks,
                f.commission_amount_kopecks,
                f.net_amount_kopecks,
                f.currency,
            )
            for f in relevant_flows
        ],
        "movements": [
            (
                m.id,
                m.event_date,
                m.source_account_id,
                m.destination_account_id,
                m.instrument_id,
                m.movement_kind,
                str(m.quantity),
                m.provenance_kind,
            )
            for m in relevant_movements
        ],
    }
    if exclusions:
        material["instrument_dispositions"] = exclusions
    if source_ids:
        material["unresolved_mybroker_import_ids"] = source_ids
    if execution_ids:
        material["unresolved_executions"] = [
            (r.trade_id, r.revision, r.material_fingerprint, r.acceptance_state, r.event_c1_json)
            for r in session.scalars(
                select(ExecutedTradeRevision)
                .where(ExecutedTradeRevision.trade_id.in_(execution_ids))
                .order_by(ExecutedTradeRevision.trade_id, ExecutedTradeRevision.revision)
            )
        ]
    signature = sha256(
        json.dumps(material, default=str, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return dict(
        reason_codes=sorted(reasons),
        historical_account_ids=accounts,
        actual_opening_date=actual[0],
        actual_closing_date=actual[1],
        currency=currency,
        opening_value_kopecks=values[0],
        closing_value_kopecks=values[1],
        material_signature=signature,
    )


def _coverage_signature(material_signature: str, opening: bool, closing: bool) -> str:
    """Bind both explicit whole-class inventory claims to the same exact material."""
    return sha256(
        json.dumps(
            ["whole_class_historical_account_universe_v1", material_signature, opening, closing],
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


@coherent_read_operation
def class_endpoint_eligibility(
    session: Session,
    *,
    asset_class: str,
    start_date: date,
    end_date: date,
) -> dict:
    _interval(start_date, end_date)
    result = dict(
        requested_class=asset_class,
        requested_opening_date=start_date,
        requested_closing_date=end_date,
        historical_account_ids=(),
        actual_opening_date=None,
        actual_closing_date=None,
        currency="RUB",
        opening_value_kopecks=None,
        closing_value_kopecks=None,
        coverage_state="unknown",
        coverage_provenance=[],
        status="unavailable",
    )
    if asset_class not in SUPPORTED_CLASSES:
        return dict(result, status="unsupported", reason_codes=["unsupported_class"])
    facts = _facts(session, asset_class, start_date, end_date)
    signature = facts.pop("material_signature")
    reasons = set(facts.pop("reason_codes"))
    rows = list(
        session.scalars(
            select(ClassNoCrossingCoverage)
            .where(
                ClassNoCrossingCoverage.asset_class == asset_class,
                ClassNoCrossingCoverage.covered_from <= end_date,
                ClassNoCrossingCoverage.covered_to >= start_date,
            )
            .order_by(ClassNoCrossingCoverage.id)
        )
    )
    # First slice requires exactly the asserted interval, never unions/subsets.
    if len(rows) != 1 or (rows[0].covered_from, rows[0].covered_to) != (start_date, end_date):
        reasons.add("no_crossing_coverage_missing_or_ambiguous")
        reasons.update(
            {"opening_class_inventory_not_complete", "closing_class_inventory_not_complete"}
        )
    else:
        row = rows[0]
        result["coverage_state"] = row.coverage_state
        if not row.opening_inventory_complete:
            reasons.add("opening_class_inventory_not_complete")
        if not row.closing_inventory_complete:
            reasons.add("closing_class_inventory_not_complete")
        if row.coverage_state != "complete" or row.provenance_kind != "owner_attestation":
            reasons.add("no_crossing_coverage_not_complete")
        elif row.material_signature != _coverage_signature(
            signature, row.opening_inventory_complete, row.closing_inventory_complete
        ):
            result["coverage_state"] = "invalidated"
            reasons.add("no_crossing_material_changed")
    result["coverage_provenance"] = [coverage_response(row) for row in rows]
    result.update(facts)
    result["reason_codes"] = sorted(reasons)
    if reasons:
        result["opening_value_kopecks"] = result["closing_value_kopecks"] = None
        if "unsupported_currency" in reasons:
            result["status"] = "unsupported"
    else:
        result["status"] = "eligible"
    return result


def coverage_response(row: ClassNoCrossingCoverage) -> dict:
    return {
        key: getattr(row, key)
        for key in (
            "id",
            "asset_class",
            "covered_from",
            "covered_to",
            "coverage_state",
            "provenance_kind",
            "provenance_reference",
            "opening_inventory_complete",
            "closing_inventory_complete",
            "revision",
        )
    }


def _editable(session: Session, start: date, end: date) -> None:
    reserve_reporting_month_interval_writer(session, covered_from=start, covered_to=end)
    closed = session.scalar(
        select(ReportingMonth.id).where(
            ReportingMonth.status == "closed",
            ((ReportingMonth.period_start <= end) & (ReportingMonth.period_end >= start))
            | ((ReportingMonth.snapshot_date >= start) & (ReportingMonth.snapshot_date <= end)),
        )
    )
    if closed is not None:
        raise ClosedReportingMonthError("closed reporting month must be reopened before editing")


def save_no_crossing_coverage(
    session: Session,
    *,
    asset_class: str,
    covered_from: date,
    covered_to: date,
    coverage_state: str,
    provenance_kind: str = "owner_attestation",
    provenance_reference: str | None = None,
    opening_inventory_complete: bool = False,
    closing_inventory_complete: bool = False,
    coverage_id: int | None = None,
    expected_revision: int | None = None,
) -> ClassNoCrossingCoverage:
    """Create/correct/revoke under the same writer reservation as Close."""
    if session.new or session.dirty or session.deleted:
        raise ValueError("coverage write requires a clean session")
    _interval(covered_from, covered_to)
    if asset_class not in SUPPORTED_CLASSES or coverage_state not in {
        "complete",
        "unknown",
        "revoked",
    }:
        raise ValueError("unsupported class or coverage state")
    if provenance_kind != "owner_attestation":
        raise ValueError("only explicit owner_attestation is supported")
    if type(opening_inventory_complete) is not bool or type(closing_inventory_complete) is not bool:
        raise ValueError("inventory completeness requires explicit booleans")
    if provenance_reference is not None and (
        not provenance_reference.strip() or len(provenance_reference) > 128
    ):
        raise ValueError("provenance reference must be a non-empty label of at most 128 characters")
    try:
        _editable(session, covered_from, covered_to)
        session.expire_all()
        row = None
        if coverage_id is not None:
            row = session.get(ClassNoCrossingCoverage, coverage_id)
            if row is None:
                raise LookupError("class coverage not found")
            if expected_revision != row.revision:
                raise ConcurrencyError("revision", expected_revision, row.revision)
            _editable(session, row.covered_from, row.covered_to)
        overlaps = session.scalar(
            select(ClassNoCrossingCoverage.id).where(
                ClassNoCrossingCoverage.asset_class == asset_class,
                ClassNoCrossingCoverage.covered_from <= covered_to,
                ClassNoCrossingCoverage.covered_to >= covered_from,
                ClassNoCrossingCoverage.id != (coverage_id or -1),
            )
        )
        if overlaps is not None:
            raise ValueError("overlapping class coverage must be corrected explicitly")
        signature = None
        if coverage_state == "complete":
            facts = _facts(session, asset_class, covered_from, covered_to)
            reasons = set(facts["reason_codes"]) - {"reporting_month_not_closed"}
            if reasons:
                raise ValueError(
                    "no-crossing assertion contradicted: " + ", ".join(sorted(reasons))
                )
            signature = _coverage_signature(
                facts["material_signature"], opening_inventory_complete, closing_inventory_complete
            )
        if row is None:
            row = ClassNoCrossingCoverage(revision=1)
            session.add(row)
        else:
            row.revision += 1
        row.asset_class, row.covered_from, row.covered_to = asset_class, covered_from, covered_to
        row.coverage_state, row.provenance_kind = coverage_state, provenance_kind
        row.provenance_reference, row.material_signature = provenance_reference, signature
        row.opening_inventory_complete = opening_inventory_complete
        row.closing_inventory_complete = closing_inventory_complete
        session.commit()
        session.refresh(row)
        return row
    except Exception:
        session.rollback()
        raise


def invalidate_class_coverages_for_reopen(session: Session, month: ReportingMonth) -> None:
    """Reopen retires C2 even if corrected data later returns to the old values."""
    rows = session.scalars(
        select(ClassNoCrossingCoverage).where(
            ClassNoCrossingCoverage.coverage_state == "complete",
            (
                (ClassNoCrossingCoverage.covered_from <= month.period_end)
                & (ClassNoCrossingCoverage.covered_to >= month.period_start)
            )
            | (
                (ClassNoCrossingCoverage.covered_from <= month.snapshot_date)
                & (ClassNoCrossingCoverage.covered_to >= month.snapshot_date)
            ),
        )
    )
    for row in rows:
        row.coverage_state = "unknown"
        row.material_signature = None
        row.revision += 1


def invalidate_class_coverages_for_identity_correction(
    session: Session,
    snapshot: PositionSnapshot,
    new_type: str | None,
) -> None:
    """An explicit C1 correction retires assertions even if later undone."""
    old_type = snapshot.historical_instrument_type
    if old_type == new_type:
        return
    month = session.get(ReportingMonth, snapshot.reporting_month_id)
    affected = SUPPORTED_CLASSES if None in (old_type, new_type) else {old_type, new_type}
    for row in session.scalars(
        select(ClassNoCrossingCoverage).where(
            ClassNoCrossingCoverage.coverage_state == "complete",
            ClassNoCrossingCoverage.asset_class.in_(affected),
            ClassNoCrossingCoverage.covered_from <= month.snapshot_date,
            ClassNoCrossingCoverage.covered_to >= month.snapshot_date,
        )
    ):
        row.coverage_state = "unknown"
        row.material_signature = None
        row.revision += 1
