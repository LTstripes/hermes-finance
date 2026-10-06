"""H0 structural inventory of accepted S1/S2-A; never financial acceptance.

All reads share a committed, query-only snapshot. Only dates, Hermes/source
digests and structural categories leave this builder, never normalized holdings,
amounts, native identifiers or raw provider content. There is no Apply route.
"""

from __future__ import annotations

import calendar
import json
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.database import coherent_read_snapshot
from hermes_finance.persistence import (
    Account,
    AccountPerformanceScopeMembership,
    CashBalance,
    CashBoundaryCoverage,
    ClassNoCrossingCoverage,
    DepositSnapshot,
    ExternalFlow,
    ExternalTransferLink,
    ExternalTransferReconciliationEvidence,
    InKindBoundaryCoverage,
    InKindMovement,
    Instrument,
    InvestmentCashFlow,
    ObservedValuationPoint,
    PositionSnapshot,
    ReportingMonth,
)
from hermes_finance.services.executed_trades import _candidate, _context, _read
from hermes_finance.services.performance_availability import _membership_at
from hermes_finance.statement_import.mybroker import PARSER, MyBrokerError, digest

FACTS = (
    PositionSnapshot,
    DepositSnapshot,
    CashBalance,
    ExternalFlow,
    InvestmentCashFlow,
    InKindMovement,
)


def _range(start: date, end: date) -> dict:
    return {"from": start.isoformat(), "to": end.isoformat()}


def _gaps(start: date, end: date, ranges: list[tuple[date, date]]) -> list[dict]:
    cursor = start
    gaps = []
    for left, right in sorted(ranges):
        if right < cursor or left > end:
            continue
        if left > cursor:
            gaps.append(_range(cursor, left - timedelta(days=1)))
        if right >= end:
            return gaps
        cursor = max(cursor, right + timedelta(days=1))
    if cursor <= end:
        gaps.append(_range(cursor, end))
    return gaps


def _month_ends(start: date, end: date) -> list[date]:
    result = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        cutoff = date(year, month, calendar.monthrange(year, month)[1])
        if start <= cutoff <= end:
            result.append(cutoff)
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return result


def _mapping_blockers(session: Session, context: dict, bindings: list[dict]) -> list[str]:
    blockers = set()
    for binding in bindings:
        current = [
            m
            for m in context["registry"]
            if m.status == "effective"
            and m.subject_kind == binding["kind"]
            and m.provider_identity == binding["identity"]
        ]
        if (
            len(current) != 1
            or current[0].id != binding["mapping_id"]
            or current[0].hermes_target_id != binding["hermes_id"]
        ):
            blockers.add(f"{binding['kind']}_mapping_changed_or_missing")
        model = Account if binding["kind"] == "account" else Instrument
        target = session.get(model, binding["hermes_id"])
        if target is None or (
            binding["kind"] == "instrument" and target.isin not in (None, binding["identity"])
        ):
            blockers.add(f"{binding['kind']}_mapping_target_invalid")
    return sorted(blockers)


def _exposure(trades: list[dict], cutoff: date) -> list[str]:
    """Both current source projection and frozen canonical revision constrain cuts."""
    blockers = set()
    for trade in trades:
        if date.fromisoformat(trade["core"]["trade_time"][:10]) > cutoff:
            continue
        evidence = trade.get("evidence", trade)
        lifecycle = evidence.get("lifecycle", evidence.get("state"))
        if lifecycle == "pending":
            blockers.add("pending_at_cutoff")
        else:
            for field in ("settlement_date", "depo_settlement_date"):
                actual = evidence.get(field)
                if actual is None:
                    blockers.add("actual_settlement_date_unknown")
                elif date.fromisoformat(actual) > cutoff:
                    blockers.add("settlement_crosses_cutoff")
        if trade.get("conflicts") or any(
            b in trade.get("blockers", [])
            for b in ("immutable_trade_conflict", "trade_material_conflict", "pending_disappeared")
        ):
            blockers.add("execution_reconciliation_required")
    return sorted(blockers)


def _endpoint(
    document: dict,
    import_id: int,
    aliases: set[str],
    side: str,
    common: list[str],
    trades: list[dict],
    memberships: list,
) -> dict:
    beginning = side == "beginning"
    cutoff = date.fromisoformat(document["covered_from"] if beginning else document["covered_to"])
    if beginning:
        cutoff -= timedelta(days=1)
    positions = [p for p in document["positions"] if p["source_account"] in aliases]
    cash = [r for r in document.get("rub_money", []) if r["source_account"] in aliases]
    quantity = "beginning_actual_quantity" if beginning else "actual_quantity"
    value = "beginning_value" if beginning else "ending_value"
    amount = "beginning_amount" if beginning else "ending_amount"
    blockers = set(common) | set(_exposure(trades, cutoff))
    if document["parser"] != PARSER:
        blockers.add("legacy_endpoint_evidence_unavailable")
    if not positions:
        blockers.add("securities_inventory_unknown")
    if any(p.get(quantity) is None for p in positions):
        blockers.add("endpoint_quantity_unavailable")
    if any(p.get(value) is None for p in positions):
        blockers.add("endpoint_value_unavailable")
    if len(cash) != 1 or cash[0].get(amount) is None:
        blockers.add("rub_cash_unavailable_or_ambiguous")
    if "position_row_unclassified" in document.get("endpoint_blockers", []):
        blockers.add("position_row_unclassified")
    # Ending actual=forward says nothing about opening settled inventory.
    if beginning:
        blockers.add("beginning_settled_inventory_unproven")
    elif any(Decimal(p["actual_quantity"]) != Decimal(p["forward_quantity"]) for p in positions):
        blockers.add("forward_exposure_at_cutoff")
    if any(
        Decimal(p[k]) < 0 for p in positions for k in (quantity, value) if p.get(k) is not None
    ) or any(Decimal(r[amount]) < 0 for r in cash if r.get(amount) is not None):
        blockers.add("negative_endpoint_state_unsupported")
    membership = _membership_at(memberships, cutoff)
    if membership is None:
        blockers.add("historical_membership_unknown")
    basis = "previous_day_eod" if beginning else "covered_to_eod"
    if document.get("endpoint_basis", {}).get(value) != basis:
        blockers.add("endpoint_basis_unavailable")
    quantities = bool(positions) and all(p.get(quantity) is not None for p in positions)
    values = bool(positions) and all(p.get(value) is not None for p in positions)
    cash_observed = len(cash) == 1 and cash[0].get(amount) is not None
    return {
        "import_id": import_id,
        "side": side,
        "cutoff": cutoff.isoformat(),
        "basis": basis,
        "components": {
            "security_quantities_observed": quantities,
            "security_values_observed": values,
            "rub_cash": ("observed_zero" if Decimal(cash[0][amount]) == 0 else "observed")
            if cash_observed
            else "unknown",
        },
        "observation_state": "observed"
        if quantities and values and cash_observed
        else ("partial" if quantities or values or cash_observed else "unknown"),
        "historical_membership": membership,
        "blockers": sorted(blockers),
        "complete_endpoint_state": "unknown",
        "candidate_operation": "inspect_source_endpoint",
        "financial_apply_available": False,
    }


def preview_historical_reconstruction(
    session: Session, *, account_ids: list[int], requested_from: date, requested_to: date
) -> dict:
    if (
        not account_ids
        or len(account_ids) > 100
        or len(set(account_ids)) != len(account_ids)
        or any(i <= 0 for i in account_ids)
        or requested_from > requested_to
        or requested_from == date.min
        or (requested_to - requested_from).days > 36600
    ):
        raise MyBrokerError("selection_invalid")
    with coherent_read_snapshot(session):
        return _preview(session, sorted(account_ids), requested_from, requested_to)


def _preview(session: Session, account_ids: list[int], start: date, end: date) -> dict:
    if any(session.get(Account, i) is None for i in account_ids):
        raise MyBrokerError("account_not_found")
    context = _context(session)
    canonical = [_read(session, context, t) for t in context["trades"].values()]
    # S2 readers remain authoritative for canonical conflicts and candidate actions.
    candidates = {}
    tables = {}
    for model in (
        AccountPerformanceScopeMembership,
        ReportingMonth,
        *FACTS,
        CashBoundaryCoverage,
        InKindBoundaryCoverage,
        ClassNoCrossingCoverage,
        ExternalTransferLink,
        ExternalTransferReconciliationEvidence,
        ObservedValuationPoint,
    ):
        tables[model] = list(session.scalars(select(model).order_by(model.id)))
        context["state"][model.__tablename__] = [
            [str(getattr(row, c.name)) for c in model.__table__.columns] for row in tables[model]
        ]
    accounts = []
    for account_id in account_ids:
        memberships = [
            r for r in tables[AccountPerformanceScopeMembership] if r.account_id == account_id
        ]
        docs, endpoints, operations, events, account_source_trades = [], [], [], [], []
        account_aliases = {
            b["identity"]
            for row in context["imports"]
            for b in json.loads(row.mappings_json)
            if b["kind"] == "account" and b["hermes_id"] == account_id
        }
        cutoff_trades = [
            t
            for t in context["projections"].values()
            if t["core"]["source_account"] in account_aliases
        ]
        cutoff_trades += [
            t
            for d in context["documents"]
            for t in d["trades"]
            if t["identity"] is None and t["core"]["source_account"] in account_aliases
        ]
        cutoff_trades += [t for t in canonical if t["account_id"] == account_id]
        for row, document in zip(context["imports"], context["documents"], strict=True):
            bindings = json.loads(row.mappings_json)
            aliases = {
                b["identity"]
                for b in bindings
                if b["kind"] == "account" and b["hermes_id"] == account_id
            }
            if not aliases:
                continue
            common = set(document["syntax_blockers"]) | set(document.get("endpoint_conflicts", []))
            common.update(_mapping_blockers(session, context, bindings))
            required = (
                {("account", a) for a in document["source_accounts"]}
                | {("instrument", p["isin"]) for p in document["positions"]}
                | {("instrument", t["core"]["isin"]) for t in document["trades"]}
            )
            common.update(
                f"{kind}_mapping_missing"
                for kind, identity in required
                if not any(b["kind"] == kind and b["identity"] == identity for b in bindings)
            )
            source_trades = [
                t for t in document["trades"] if t["core"]["source_account"] in aliases
            ]
            money = [r for r in document["money"] if r["source_account"] in aliases]
            dated = [t["core"]["trade_time"][:10] for t in source_trades] + [
                r["date"] for r in money
            ]
            events.extend(dated)
            if any(r["kind"] == "unsupported" for r in money):
                common.add("money_semantics_unsupported")
            if any(t["repo_observed"] for t in source_trades):
                common.add("repo_semantics_unsupported")
            if any(t["identity"] is None for t in source_trades):
                common.add("trade_ids_incomplete")
            reduced = [
                t for t in context["projections"].values() if t["core"]["source_account"] in aliases
            ]
            # Identity-less observations must remain visible and cannot be promoted.
            reduced += [t for t in source_trades if t["identity"] is None]
            account_source_trades.extend(reduced)
            constraints = cutoff_trades
            sides = [
                _endpoint(document, row.id, aliases, side, sorted(common), constraints, memberships)
                for side in ("beginning", "ending")
            ]
            endpoints.extend(
                s
                for s in sides
                if row.covered_from <= end
                and row.covered_to >= start
                or start <= date.fromisoformat(s["cutoff"]) <= end
            )
            doc_start, doc_end = row.covered_from, row.covered_to
            docs.append(
                {
                    "import_id": row.id,
                    "parser": row.parser_version,
                    "confirmed_range": _range(doc_start, doc_end),
                    "intersects_request": doc_start <= end and doc_end >= start,
                    "observed_event_range": {"from": min(dated), "to": max(dated)}
                    if dated
                    else None,
                    "event_state": "observed" if dated else "quiet_unknown",
                    "blockers": sorted(common),
                }
            )
            for trade in source_trades:
                if not start.isoformat() <= trade["core"]["trade_time"][:10] <= end.isoformat():
                    continue
                identity = trade["identity"]
                if identity is None:
                    operation = {
                        "source_identity": None,
                        "import_id": row.id,
                        "operation": "inspect_unpromotable_source",
                        "blockers": ["trade_ids_incomplete"],
                    }
                else:
                    if identity not in candidates:
                        candidates[identity] = _candidate(session, context, identity)
                    candidate = candidates[identity]
                    operation = {
                        "source_identity": identity,
                        "trade_id": candidate["trade_id"],
                        "revision": candidate["revision"],
                        "operation": candidate["action"],
                        "blockers": sorted(
                            set(candidate["conflicts"])
                            | {
                                b
                                for group in candidate["evidence"]["readiness"].values()
                                for b in group
                            }
                        ),
                    }
                if operation not in operations:
                    operations.append(operation)
        ranges = [
            (
                date.fromisoformat(d["confirmed_range"]["from"]),
                date.fromisoformat(d["confirmed_range"]["to"]),
            )
            for d in docs
        ]
        overlaps = []
        for i, left in enumerate(docs):
            for right in docs[i + 1 :]:
                a = max(
                    start,
                    date.fromisoformat(left["confirmed_range"]["from"]),
                    date.fromisoformat(right["confirmed_range"]["from"]),
                )
                b = min(
                    end,
                    date.fromisoformat(left["confirmed_range"]["to"]),
                    date.fromisoformat(right["confirmed_range"]["to"]),
                )
                if a <= b:
                    overlaps.append(
                        {"import_ids": [left["import_id"], right["import_id"]], **_range(a, b)}
                    )
        history_gaps = _gaps(
            start, end, [(r.effective_from, r.effective_to or end) for r in memberships]
        )
        membership_overlaps = []
        for i, left in enumerate(memberships):
            for right in memberships[i + 1 :]:
                a = max(start, left.effective_from, right.effective_from)
                b = min(end, left.effective_to or end, right.effective_to or end)
                if a <= b:
                    membership_overlaps.append(_range(a, b))
        accepted = []
        for month in tables[ReportingMonth]:
            if not (
                month.period_start <= end
                and month.period_end >= start
                or start <= month.snapshot_date <= end
            ):
                continue
            categories = [
                model.__tablename__
                for model in FACTS
                if any(
                    (
                        r.source_account_id == account_id or r.destination_account_id == account_id
                        if model is InKindMovement
                        else r.account_id == account_id
                    )
                    and r.reporting_month_id == month.id
                    for r in tables[model]
                )
            ]
            if categories:
                accepted.append(
                    {
                        "month_id": month.id,
                        "status": month.status,
                        "snapshot_date": month.snapshot_date.isoformat(),
                        "fact_categories": categories,
                        "source_range_overlap": any(
                            a <= month.period_end
                            and b >= month.period_start
                            or a <= month.snapshot_date <= b
                            for a, b in ranges
                        ),
                        "operation": "inspect_overlap_requires_reconciliation",
                    }
                )
        own_canonical = [t for t in canonical if t["account_id"] == account_id]
        executions = [
            t["core"]["trade_time"][:10]
            for t in own_canonical
            if t["acceptance_state"] == "active" and t["evidence"]["lifecycle"] == "settled"
        ]
        blockers = {b for d in docs for b in d["blockers"] if d["intersects_request"]}
        if not docs:
            blockers.add("accepted_source_unavailable")
        if history_gaps or membership_overlaps:
            blockers.add("historical_membership_unknown")
        blockers.update(_exposure(account_source_trades + own_canonical, end))
        accounts.append(
            {
                "account_id": account_id,
                "documents": docs,
                "source_range_gaps": _gaps(start, end, ranges),
                "source_range_overlaps": overlaps,
                "historical_membership_gaps": history_gaps,
                "historical_membership_overlaps": membership_overlaps,
                "historical_membership": [
                    {
                        **_range(max(start, r.effective_from), min(end, r.effective_to or end)),
                        "included": r.include_in_returns,
                    }
                    for r in memberships
                    if r.effective_from <= end
                    and (r.effective_to is None or r.effective_to >= start)
                ],
                "earliest_observed_source_event": min(events) if events else None,
                "earliest_accepted_canonical_execution": min(executions) if executions else None,
                "canonical_executions": [
                    {
                        "trade_id": t["trade_id"],
                        "source_identity": t["source_identity"],
                        "revision": t["revision"],
                        "lifecycle": t["evidence"]["lifecycle"],
                        "acceptance_state": t["acceptance_state"],
                        "conflicts": t["conflicts"],
                    }
                    for t in own_canonical
                ],
                "endpoints": endpoints,
                "month_end_inventory": [
                    {
                        "cutoff": cutoff.isoformat(),
                        "source_sides": [
                            {
                                "import_id": s["import_id"],
                                "side": s["side"],
                                "observation_state": s["observation_state"],
                                "blockers": s["blockers"],
                            }
                            for s in endpoints
                            if s["cutoff"] == cutoff.isoformat()
                        ],
                        "complete_source_endpoint_state": "unknown",
                    }
                    for cutoff in _month_ends(start, end)
                ],
                "hermes_month_overlap": accepted,
                "candidate_operations": operations,
                "blockers": sorted(blockers),
                "availability": {
                    "event_history": "observed"
                    if events
                    else ("quiet_unknown" if docs else "unknown"),
                    "financial_coverage": "unknown",
                    "inception": "unknown",
                    "exact_source_endpoints": "unavailable_until_h1",
                    "monthly_materialization": "unavailable_until_h1",
                    "account_portfolio_xirr": "not_evaluated",
                    "class_xirr_no_crossing": "not_evaluated",
                    "class_xirr_crossing": "not_delivered",
                    "exact_twrr": "not_evaluated",
                },
            }
        )
    return {
        "scope": "selected_accounts",
        "requested_range": _range(start, end),
        "accounts": accounts,
        "preview_digest": digest(
            {"account_ids": account_ids, "range": _range(start, end), "state": context["state"]}
        ),
        "coverage_state": "unknown",
        "financial_apply_available": False,
        "limitations": [
            "h1_endpoint_acceptance_contract_required",
            "source_ranges_do_not_prove_completeness",
            "opaque_event_dates_unavailable",
            "returns_not_evaluated",
            "overlap_values_not_compared",
        ],
    }
