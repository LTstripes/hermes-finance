"""Offline ICF-to-forecast evidence in the existing receipt/reconciliation stores."""

import re
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import insert, select, update
from sqlalchemy.orm import Session

from hermes_finance.database import coherent_read_snapshot
from hermes_finance.domain.payout_reconciliation import PayoutIntent
from hermes_finance.persistence import (
    Account,
    AppliedPayoutReconciliation,
    AppliedPayoutRevision,
    AppliedProviderPayout,
    BrokerIdentityMapping,
    BrokerMonthApply,
    ExpectedCashFlow,
    Instrument,
    InstrumentMarketMapping,
    InvestmentCashFlow,
    MyBrokerImport,
    ReportingMonth,
)
from hermes_finance.services import broker_month_journal as journal
from hermes_finance.services import broker_months
from hermes_finance.services.broker_money import latest_proofs, material, proof_blockers
from hermes_finance.services.broker_money_lifecycle import next_journal_revision
from hermes_finance.source_proof_file import file_incarnation
from hermes_finance.statement_import.mybroker import MyBrokerError, canonical, digest

CONTRACT = journal.PAYOUT


def event_key(payout):
    return digest(
        [
            "actual-provider-event-v1",
            payout.account_id,
            payout.instrument_id,
            payout.provider,
            payout.provider_instrument_uid,
            payout.event_kind,
            payout.identity_key,
        ]
    )


def _latest_revision(session, payout_id):
    return session.scalar(
        select(AppliedPayoutRevision)
        .where(AppliedPayoutRevision.applied_payout_id == payout_id)
        .order_by(AppliedPayoutRevision.id.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )


def _physical(session):
    connection = session.connection()
    path = connection.engine.url.database
    stamp = file_incarnation(Path(path)) if path else None
    if not stamp or stamp != connection.info.get("source_proof_incarnation"):
        raise MyBrokerError("payout_database_incarnation_unavailable")
    return stamp


def _same_scope(actual, forecast):
    kind = (
        forecast.event_kind if isinstance(forecast, AppliedProviderPayout) else forecast.flow_type
    )
    return (actual.account_id, actual.instrument_id, actual.flow_type, actual.currency) == (
        forecast.account_id,
        forecast.instrument_id,
        kind,
        forecast.currency,
    )


def _future_pool(session, forecast):
    month = (
        session.get(ReportingMonth, forecast.reporting_month_id)
        if forecast.reporting_month_id
        else None
    )
    if month is None or month.status != "draft":
        return False
    start, end = _future_bounds(month)
    day = (
        forecast.payment_date
        if isinstance(forecast, AppliedProviderPayout)
        else forecast.expected_date
    )
    return start <= day < end


def _future_bounds(month):
    start = month.snapshot_date
    try:
        end = start.replace(year=start.year + 1)
    except ValueError:
        end = start.replace(year=start.year + 1, day=28)
    return start, end


def _forecasts(session, actual, *, selected=()):
    result = []
    history = list(
        session.scalars(
            select(AppliedPayoutReconciliation).where(
                AppliedPayoutReconciliation.investment_cash_flow_id == actual.id
            )
        )
    )
    historical_apps = {r.applied_payout_id for r in history}
    historical_ecfs = {r.expected_cash_flow_id for r in history}
    historical_keys = {r.provider_event_key for r in history if r.provider_event_key}
    for kind, ident in selected:
        if kind == "app" and (chosen := session.get(AppliedProviderPayout, ident)) is not None:
            historical_keys.add(event_key(chosen))
    for model, kind in ((AppliedProviderPayout, "app"), (ExpectedCashFlow, "ecf")):
        flow_kind = model.event_kind if kind == "app" else model.flow_type
        for row in session.scalars(
            select(model)
            .where(
                model.account_id == actual.account_id,
                model.instrument_id == actual.instrument_id,
                model.currency == actual.currency,
                flow_kind == actual.flow_type,
                model.archived_from_period.is_(None),
                model.reporting_month_id.is_not(None),
            )
            .order_by(model.id)
            .execution_options(populate_existing=True)
        ):
            if (
                not _same_scope(actual, row)
                or row.archived_from_period is not None
                or row.reporting_month_id is None
            ):
                continue
            if kind == "app" and row.lifecycle != "active":
                continue
            month = session.get(ReportingMonth, row.reporting_month_id)
            if month is None:
                continue
            start, end = _future_bounds(month)
            day = row.payment_date if kind == "app" else row.expected_date
            explicit = (kind, row.id) in selected or row.id in (
                historical_apps if kind == "app" else historical_ecfs
            )
            if kind == "app" and event_key(row) in historical_keys:
                explicit = True
            if explicit or (start <= day < end and abs((day - actual.event_date).days) <= 3):
                result.append((kind, row))
    return result


def _forecast_snapshot(session, kind, row):
    facts = material(row)
    facts.pop("notes", None)
    return {
        "kind": kind,
        "facts": facts,
        "revision": material(_latest_revision(session, row.id)) if kind == "app" else None,
        "provider_event_key": event_key(row) if kind == "app" else None,
    }


def _dependency(session, intent, *, exclude_request=None):
    actual = session.get(InvestmentCashFlow, intent.investment_cash_flow_id, populate_existing=True)
    if actual is None or (actual.account_id, actual.reporting_month_id) != (
        intent.account_id,
        intent.reporting_month_id,
    ):
        raise MyBrokerError("actual_payout_scope_mismatch")
    base = session.get(BrokerMonthApply, intent.base_request_id, populate_existing=True)
    if (
        base is None
        or journal.kind(base) != journal.SOURCE
        or (base.account_id, base.reporting_month_id)
        != (actual.account_id, actual.reporting_month_id)
    ):
        raise MyBrokerError("existing_source_draft_required")
    chosen = tuple(
        (kind, value)
        for kind, value in (
            ("app", intent.applied_payout_id),
            ("ecf", intent.expected_cash_flow_id),
        )
        if value
    )
    candidates = [
        _forecast_snapshot(session, kind, row)
        for kind, row in _forecasts(session, actual, selected=chosen)
    ]
    month_ids = {
        actual.reporting_month_id,
        *[int(c["facts"]["reporting_month_id"]) for c in candidates],
    }
    money = latest_proofs(session).get((actual.flow_type, actual.id))
    source = session.get(MyBrokerImport, base.import_id, populate_existing=True)
    mapping_rows = [
        material(r)
        for r in session.scalars(select(BrokerIdentityMapping).order_by(BrokerIdentityMapping.id))
        if r.hermes_account_id == actual.account_id
        or r.hermes_instrument_id == actual.instrument_id
    ]
    market = [
        material(r)
        for r in session.scalars(
            select(InstrumentMarketMapping).order_by(InstrumentMarketMapping.instrument_id)
        )
        if r.instrument_id == actual.instrument_id
    ]
    tokens = []
    sections = []
    for row in session.scalars(select(BrokerMonthApply).order_by(BrokerMonthApply.request_id)):
        if row.request_id == exclude_request or (row.account_id, row.reporting_month_id) != (
            actual.account_id,
            actual.reporting_month_id,
        ):
            continue
        proof = journal.payload(row)
        kind = journal.kind(row)
        if proof.get("base_request_id") != base.request_id:
            continue
        if kind == journal.PAYOUT_DEPENDENCY:
            changed_months = proof.get("changed_reporting_month_ids")
            if actual.id in proof.get("investment_cash_flow_ids", []) and (
                changed_months is None or month_ids.intersection(changed_months)
            ):
                tokens.append([row.request_id, proof])
        elif kind == CONTRACT and any(
            t.get("investment_cash_flow_id") == actual.id
            and (
                proof["operation"] != "distinct"
                or (t.get("applied_payout_id"), t.get("expected_cash_flow_id"))
                == (intent.applied_payout_id, intent.expected_cash_flow_id)
            )
            for t in proof["targets"]
        ):
            tokens.append([row.request_id, proof])
        elif kind not in {*journal.MONEY_KINDS, CONTRACT, journal.DEPENDENCY}:
            sections.append([row.request_id, proof])
    month = session.get(ReportingMonth, actual.reporting_month_id)
    result = {
        "actual": material(actual),
        "account": material(session.get(Account, actual.account_id)),
        "instrument": material(session.get(Instrument, actual.instrument_id)),
        "base_request_id": base.request_id,
        "base_fingerprint": base.request_fingerprint,
        "source": material(source),
        "source_projection": broker_months._projection(session, base),
        "source_findings": broker_months._readiness(session, base),
        "section_heads": sections,
        "money_proof_request_id": money[0].request_id if money else None,
        "money_proof": money[1] if money else None,
        "money_blockers": proof_blockers(session, *money)
        if money
        else ["source_money_proof_required"],
        "mappings": mapping_rows,
        "market_mappings": market,
        "dependency_receipts": tokens,
        "candidates": candidates,
        "candidate_set_digest": digest(candidates),
        "month_geometry": [
            str(getattr(month, f))
            for f in ("year", "month", "snapshot_date", "period_start", "period_end")
        ],
        "forecast_month_geometry": [
            [
                month_id,
                *[
                    str(getattr(session.get(ReportingMonth, month_id), field))
                    for field in ("year", "month", "snapshot_date", "period_start", "period_end")
                ],
            ]
            for month_id in sorted(month_ids - {actual.reporting_month_id})
        ],
        "physical_incarnation": _physical(session),
    }
    return result, actual, base, money


def _editable(session, actual, forecasts):
    for month_id in {actual.reporting_month_id, *[r.reporting_month_id for r in forecasts]}:
        month = session.get(ReportingMonth, month_id, populate_existing=True) if month_id else None
        if month is None or month.status != "draft":
            raise MyBrokerError("payout_involved_scope_requires_reopen")


def _paid_forecasts(session, dependency, core):
    """Freeze the DRAFT future projections actually covered by this acceptance."""
    result = []
    for candidate in dependency["candidates"]:
        kind = candidate["kind"]
        ident = int(candidate["facts"]["id"])
        covered = (
            kind == "app"
            and core.get("provider_event_key")
            and candidate["provider_event_key"] == core["provider_event_key"]
        ) or (kind == "ecf" and ident == core.get("expected_cash_flow_id"))
        if not covered:
            continue
        row = session.get(AppliedProviderPayout if kind == "app" else ExpectedCashFlow, ident)
        if _future_pool(session, row):
            result.append({"kind": kind, "id": ident, "reporting_month_id": row.reporting_month_id})
    return result


def _identity_supported(payout):
    key = payout.identity_key
    if payout.event_kind == "coupon" and re.fullmatch(r"n:[0-9]+", key):
        return True
    if payout.event_kind == "coupon" and key.startswith("p:"):
        parts = key.split(":")
        try:
            return len(parts) == 3 and date.fromisoformat(parts[1]) <= date.fromisoformat(parts[2])
        except ValueError:
            return False
    if payout.event_kind == "dividend" and key.startswith("r:"):
        try:
            return date.fromisoformat(key[2:]).isoformat() == key[2:]
        except ValueError:
            return False
    if payout.event_kind == "dividend" and key.startswith("id:"):
        return bool(key[3:].strip())
    return False


def _predecessor_proof(session, intent, predecessor, blockers):
    """Bind the terminal row and its original retirement; never revive history."""
    if predecessor is None:
        if intent.operation in {"link", "reaffirm"} and session.scalar(
            select(AppliedPayoutReconciliation.id)
            .where(
                AppliedPayoutReconciliation.investment_cash_flow_id
                == intent.investment_cash_flow_id
            )
            .limit(1)
        ):
            blockers.add("payout_terminal_predecessor_required")
        return None
    if session.scalar(
        select(AppliedPayoutReconciliation.id)
        .where(AppliedPayoutReconciliation.supersedes_id == predecessor.id)
        .limit(1)
    ):
        blockers.add("payout_predecessor_already_successored")
    accepted = (
        session.get(BrokerMonthApply, predecessor.accepted_request_id)
        if predecessor.accepted_request_id
        else None
    )
    retired = (
        session.get(BrokerMonthApply, predecessor.retired_request_id)
        if predecessor.retired_request_id
        else None
    )
    if predecessor.investment_cash_flow_id is None:
        if intent.operation != "link" or retired is not None:
            blockers.add("legacy_predecessor_requires_live_conversion")
    else:
        if intent.operation not in {"reaffirm", "retire"}:
            blockers.add("actual_predecessor_requires_reaffirmation")
        if (
            accepted is None
            or journal.kind(accepted) != CONTRACT
            or journal.payload(accepted).get("base_request_id") != intent.base_request_id
        ):
            blockers.add("payout_predecessor_source_scope_invalid")
        if predecessor.retired_request_id:
            a = journal.payload(accepted) if accepted else {}
            d = journal.payload(retired) if retired else {}
            valid = (
                retired is not None
                and journal.kind(retired) == CONTRACT
                and d.get("operation") == "retire"
                and (retired.account_id, retired.reporting_month_id)
                == (intent.account_id, intent.reporting_month_id)
                and d.get("base_request_id") == intent.base_request_id
                and d.get("journal_revision", 0) > a.get("journal_revision", 0)
                and any(
                    t.get("relation_id") == predecessor.id
                    and t.get("investment_cash_flow_id") == predecessor.investment_cash_flow_id
                    for t in d.get("targets", [])
                )
            )
            if not valid:
                blockers.add("payout_predecessor_retirement_invalid")
            if intent.operation == "retire":
                blockers.add("payout_predecessor_already_retired")
    return {
        "relation": material(predecessor),
        "acceptance": material(accepted),
        "retirement": material(retired),
    }


def _plan(session, intent):
    dependency, actual, base, money = _dependency(session, intent)
    blockers = set()
    forecasts = []
    app = (
        session.get(AppliedProviderPayout, intent.applied_payout_id, populate_existing=True)
        if intent.applied_payout_id
        else None
    )
    ecf = (
        session.get(ExpectedCashFlow, intent.expected_cash_flow_id, populate_existing=True)
        if intent.expected_cash_flow_id
        else None
    )
    predecessor = (
        session.get(AppliedPayoutReconciliation, intent.predecessor_id, populate_existing=True)
        if intent.predecessor_id
        else None
    )
    if intent.predecessor_id and predecessor is None:
        blockers.add("payout_predecessor_missing")
    predecessor_proof = _predecessor_proof(session, intent, predecessor, blockers)
    if predecessor:
        for model, ident in (
            (AppliedProviderPayout, predecessor.applied_payout_id),
            (ExpectedCashFlow, predecessor.expected_cash_flow_id),
        ):
            if ident:
                forecasts.append(session.get(model, ident))
        if predecessor.investment_cash_flow_id not in (None, actual.id):
            blockers.add("payout_actual_reassignment_unsupported")
        if (
            predecessor.investment_cash_flow_id is not None
            and intent.operation == "reaffirm"
            and (predecessor.applied_payout_id, predecessor.expected_cash_flow_id)
            != (intent.applied_payout_id, intent.expected_cash_flow_id)
        ):
            blockers.add("payout_core_reassignment_unsupported")
    for selected, row in ((intent.applied_payout_id, app), (intent.expected_cash_flow_id, ecf)):
        if selected and row is None:
            blockers.add("payout_forecast_missing")
        if row:
            forecasts.append(row)
            if not _same_scope(actual, row) or row.archived_from_period is not None:
                blockers.add("payout_forecast_scope_mismatch")
    try:
        _editable(session, actual, forecasts)
        if predecessor and predecessor.investment_cash_flow_id is not None:
            from hermes_finance.services.payout_link_lifecycle import _require_editable_history

            _require_editable_history(session, predecessor)
    except MyBrokerError as e:
        blockers.add(str(e))
    if intent.operation != "retire":
        if (
            dependency["money_blockers"]
            or money is None
            or money[1]["base_request_id"] != base.request_id
        ):
            blockers.add("source_money_proof_required")
        if (
            dependency["source_projection"] != journal.payload(base)["projection_digest"]
            or dependency["source_findings"]
        ):
            blockers.add("source_economic_scope_unresolved")
        if actual.currency != "RUB" or actual.flow_type not in {"coupon", "dividend"}:
            blockers.add("actual_payout_kind_unsupported")
        if app and (app.lifecycle != "active" or not _identity_supported(app)):
            blockers.add("payout_provider_identity_unsupported")
        if app and (app.provider_status or "").lower() in {
            "cancelled",
            "canceled",
            "tentative",
            "unknown",
        }:
            blockers.add("payout_provider_status_unsupported")
        if app and _latest_revision(session, app.id) is None:
            blockers.add("payout_provider_revision_required")
        if app:
            mapping = session.get(
                InstrumentMarketMapping, app.instrument_id, populate_existing=True
            )
            if (
                mapping is None
                or mapping.excluded
                or (mapping.provider, mapping.provider_instrument_id)
                != (app.provider, app.provider_instrument_uid)
            ):
                blockers.add("payout_provider_mapping_changed")
    core = {
        "investment_cash_flow_id": actual.id,
        "money_proof_request_id": money[0].request_id if money else None,
        "applied_payout_id": intent.applied_payout_id,
        "expected_cash_flow_id": intent.expected_cash_flow_id,
        "applied_payout_revision_id": _latest_revision(session, app.id).id
        if app and _latest_revision(session, app.id)
        else None,
        "provider_event_key": event_key(app) if app else None,
        "predecessor_id": intent.predecessor_id,
        "predecessor_retirement_request_id": predecessor.retired_request_id
        if predecessor
        else None,
    }
    review = digest(
        [intent.model_dump(mode="json", exclude={"claims"}), dependency, predecessor_proof, core]
    )
    claims = intent.claims
    if claims is None or claims.review_context_digest != review:
        blockers.add("payout_review_claim_binding_required")
    if intent.operation in {"link", "reaffirm"}:
        if (
            claims is None
            or not claims.actual_is_exact_event
            or not claims.full_event_settled_not_partial
        ):
            blockers.add("full_event_settlement_evidence_required")
        if app and (claims is None or claims.provider_identity_key != app.identity_key):
            blockers.add("exact_provider_event_bridge_required")
        if ecf and (claims is None or not claims.exact_manual_row_is_same_event):
            blockers.add("exact_manual_event_bridge_required")
        if claims and claims.actual_and_forecast_are_distinct:
            blockers.add("payout_contradictory_claims")
        for link in session.scalars(select(AppliedPayoutReconciliation)):
            if (
                core["provider_event_key"]
                and link.provider_event_key == core["provider_event_key"]
                and link.investment_cash_flow_id != actual.id
            ):
                blockers.add("payout_actual_reassignment_unsupported")
            same_slot = (
                link.investment_cash_flow_id == actual.id
                or (app and link.applied_payout_id == app.id)
                or (ecf and link.expected_cash_flow_id == ecf.id)
                or (
                    core["provider_event_key"]
                    and link.provider_event_key == core["provider_event_key"]
                )
            )
            if (
                same_slot
                and link.retired_request_id is None
                and link.archived_from_period is None
                and link.id != intent.predecessor_id
            ):
                blockers.add("payout_active_slot_occupied")
        if (
            predecessor
            and predecessor.investment_cash_flow_id is None
            and (predecessor.applied_payout_id, predecessor.expected_cash_flow_id)
            != (intent.applied_payout_id, intent.expected_cash_flow_id)
        ):
            blockers.add("legacy_triple_must_preserve_both_sides")
    if intent.operation == "distinct":
        if (
            claims is None
            or not claims.actual_and_forecast_are_distinct
            or not claims.actual_independent_event_key
            or not claims.forecast_independent_event_key
            or claims.actual_independent_event_key == claims.forecast_independent_event_key
        ):
            blockers.add("distinct_independent_event_evidence_required")
        if claims and (claims.actual_is_exact_event or claims.exact_manual_row_is_same_event):
            blockers.add("payout_contradictory_claims")
        for link in session.scalars(
            select(AppliedPayoutReconciliation).where(
                AppliedPayoutReconciliation.investment_cash_flow_id == actual.id,
                AppliedPayoutReconciliation.retired_request_id.is_(None),
            )
        ):
            if (
                app
                and (link.applied_payout_id == app.id or link.provider_event_key == event_key(app))
            ) or (ecf and link.expected_cash_flow_id == ecf.id):
                blockers.add("payout_active_slot_occupied")
    result = {
        "contract_version": CONTRACT,
        "operation": intent.operation,
        "scope": {"account_id": intent.account_id, "reporting_month_id": intent.reporting_month_id},
        "targets": [core],
        "dependency": dependency,
        "predecessor_proof": predecessor_proof,
        "paid_forecasts": _paid_forecasts(session, dependency, core)
        if intent.operation in {"link", "reaffirm"}
        else [],
        "review_context_digest": review,
        "blockers": sorted(blockers),
        "can_apply": not blockers,
        "expected_effects": {
            "new_icf": 0,
            "cash_increment_minor": "0",
            "new_relation": int(intent.operation in {"link", "reaffirm"}),
        },
    }
    result["confirmation_digest"] = digest([intent.model_dump(mode="json"), result])
    return result


def preview(session, intent):
    with coherent_read_snapshot(session):
        return _plan(session, intent)


def relation_state(session, link):
    if link.retired_request_id:
        return "retired"
    receipt = session.get(BrokerMonthApply, link.accepted_request_id)
    if receipt is None or journal.kind(receipt) != CONTRACT:
        return "stale"
    proof = journal.payload(receipt)
    try:
        requested = PayoutIntent.model_validate(proof["intent"])
        dependency, _, _, _ = _dependency(session, requested, exclude_request=receipt.request_id)
    except (MyBrokerError, ValueError, KeyError):
        return "stale"
    return (
        "paid"
        if dependency == proof["dependency"] and not dependency["money_blockers"]
        else "stale"
    )


def read(session, request_id):
    with coherent_read_snapshot(session):
        receipt = session.get(BrokerMonthApply, request_id, populate_existing=True)
        if receipt is None or journal.kind(receipt) != CONTRACT:
            raise MyBrokerError("payout_receipt_not_found")
        proof = journal.payload(receipt)
        links = list(
            session.scalars(
                select(AppliedPayoutReconciliation).where(
                    AppliedPayoutReconciliation.accepted_request_id == request_id
                )
            )
        )
        return {
            "contract_version": CONTRACT,
            "request_id": request_id,
            "account_id": receipt.account_id,
            "reporting_month_id": receipt.reporting_month_id,
            "confirmation_digest": receipt.confirmation_digest,
            "accepted": proof,
            "relations": [
                {
                    "id": r.id,
                    "state": relation_state(session, r),
                    "retired_request_id": r.retired_request_id,
                }
                for r in links
            ],
            "status": session.get(ReportingMonth, receipt.reporting_month_id).status,
        }


def _distinct_current(session, actual, kind, forecast):
    matches = []
    for receipt in session.scalars(select(BrokerMonthApply)):
        if journal.kind(receipt) != CONTRACT:
            continue
        proof = journal.payload(receipt)
        if proof["operation"] != "distinct" or not any(
            t.get("investment_cash_flow_id") == actual.id
            and t.get("applied_payout_id" if kind == "app" else "expected_cash_flow_id")
            == forecast.id
            for t in proof["targets"]
        ):
            continue
        matches.append((receipt, proof))
    if not matches:
        return False
    receipt, proof = max(matches, key=lambda item: item[1]["journal_revision"])
    try:
        dependency, _, _, _ = _dependency(
            session,
            PayoutIntent.model_validate(proof["intent"]),
            exclude_request=receipt.request_id,
        )
        return dependency == proof["dependency"] and not dependency["money_blockers"]
    except (MyBrokerError, KeyError, ValueError):
        return False


def obligations(
    session,
    month_id=None,
    account_id=None,
    *,
    include_stale=False,
    require_candidates=False,
    calendar_month_id=None,
):
    """Pure current source-owned obligations, independent of UI forecast version."""
    result = []
    base_findings = {}
    for (role, ident), (receipt, proof, target) in latest_proofs(session).items():
        if (
            role not in {"coupon", "dividend"}
            or (month_id is not None and receipt.reporting_month_id != month_id)
            or (account_id is not None and receipt.account_id != account_id)
        ):
            continue
        base = session.get(BrokerMonthApply, proof["base_request_id"])
        actual = session.get(InvestmentCashFlow, ident)
        if base is None or journal.kind(base) != journal.SOURCE or actual is None:
            continue
        forecasts = [
            (kind, forecast)
            for kind, forecast in _forecasts(session, actual)
            if (calendar_month_id is None or forecast.reporting_month_id == calendar_month_id)
            and _future_pool(session, forecast)
        ]
        if require_candidates and not forecasts:
            continue  # No competitor means no settlement obligation or future exclusion.
        if base.request_id not in base_findings:
            base_findings[base.request_id] = broker_months._readiness(session, base)
        stale_economics = bool(
            proof_blockers(session, receipt, proof, target) or base_findings[base.request_id]
        )
        if stale_economics and not include_stale:
            continue  # Existing source/Money guards own lost economic authority.
        links = list(
            session.scalars(
                select(AppliedPayoutReconciliation)
                .where(AppliedPayoutReconciliation.investment_cash_flow_id == ident)
                .order_by(AppliedPayoutReconciliation.id)
            )
        )
        states = {link.id: relation_state(session, link) for link in links}
        candidates = []
        for kind, forecast in forecasts:
            exact = [
                link
                for link in links
                if (
                    (
                        kind == "app"
                        and (
                            link.applied_payout_id == forecast.id
                            or link.provider_event_key == event_key(forecast)
                        )
                    )
                    or (kind == "ecf" and link.expected_cash_flow_id == forecast.id)
                )
            ]
            paid = not stale_economics and any(states[link.id] == "paid" for link in exact)
            distinct = (
                not stale_economics
                and not paid
                and _distinct_current(session, actual, kind, forecast)
            )
            status = "paid" if paid else "future" if distinct else "unresolved"
            code = None
            if status == "unresolved":
                code = (
                    "source_payout_settlement_stale"
                    if exact
                    else "source_payout_identity_unresolved"
                )
                for other in session.scalars(
                    select(AppliedPayoutReconciliation).where(
                        AppliedPayoutReconciliation.investment_cash_flow_id.is_not(None),
                        AppliedPayoutReconciliation.investment_cash_flow_id != ident,
                    )
                ):
                    if (kind == "app" and other.provider_event_key == event_key(forecast)) or (
                        kind == "ecf" and other.expected_cash_flow_id == forecast.id
                    ):
                        code = "source_payout_duplicate_claim"
            candidates.append(
                {
                    **_forecast_snapshot(session, kind, forecast),
                    "state": status,
                    "reason_code": code,
                }
            )
        successors = {link.supersedes_id for link in links}
        terminal = [link for link in links if link.id not in successors]
        choices = []
        for model, kind in ((AppliedProviderPayout, "app"), (ExpectedCashFlow, "ecf")):
            for forecast in session.scalars(select(model).order_by(model.id)):
                if (
                    _same_scope(actual, forecast)
                    and forecast.archived_from_period is None
                    and forecast.reporting_month_id is not None
                ):
                    if kind != "app" or forecast.lifecycle == "active":
                        choices.append(_forecast_snapshot(session, kind, forecast))
        result.append(
            {
                "account_id": actual.account_id,
                "reporting_month_id": actual.reporting_month_id,
                "base_request_id": base.request_id,
                "investment_cash_flow_id": actual.id,
                "actual": material(actual),
                "money_proof_request_id": receipt.request_id,
                "candidates": candidates,
                "forecast_choices": choices,
                "legacy_relations": [
                    material(link)
                    for link in session.scalars(
                        select(AppliedPayoutReconciliation).where(
                            AppliedPayoutReconciliation.investment_cash_flow_id.is_(None),
                            AppliedPayoutReconciliation.retired_request_id.is_(None),
                            AppliedPayoutReconciliation.archived_from_period.is_(None),
                        )
                    )
                    if any(
                        c["kind"] == "app" and c["facts"]["id"] == str(link.applied_payout_id)
                        for c in choices
                    )
                    and any(
                        c["kind"] == "ecf" and c["facts"]["id"] == str(link.expected_cash_flow_id)
                        for c in choices
                    )
                ],
                "terminal_relation": {**material(terminal[0]), "state": states[terminal[0].id]}
                if len(terminal) == 1
                else None,
                "coverage_state": "unknown"
                if any(c["state"] == "unresolved" for c in candidates)
                else "complete",
            }
        )
    return result


def close_blockers(session, month_id):
    month = session.get(ReportingMonth, month_id)
    if month is None or month.status != "draft":
        return ()
    return tuple(
        sorted(
            {
                (
                    c["reason_code"],
                    f"Счёт #{o['account_id']}, выплата #{o['investment_cash_flow_id']}: требуется сверка прогноза {c['kind']} #{c['facts']['id']}.",
                )
                for o in obligations(session, month_id, require_candidates=True)
                for c in o["candidates"]
                if c["reason_code"]
            }
        )
    )


def future_states(session, calendar_month_id):
    """Eligible future only; actual amounts continue to come solely from ICF."""
    month = session.get(ReportingMonth, calendar_month_id)
    result = {}
    if month is None:
        return result
    if month.status == "closed":
        # Preserve only projections that were DRAFT and covered at acceptance.
        # An older CLOSED copy of the canonical event never acquires new authority.
        for link in session.scalars(
            select(AppliedPayoutReconciliation).where(
                AppliedPayoutReconciliation.investment_cash_flow_id.is_not(None),
                AppliedPayoutReconciliation.retired_request_id.is_(None),
            )
        ):
            receipt = session.get(BrokerMonthApply, link.accepted_request_id)
            if receipt is None or journal.kind(receipt) != CONTRACT:
                continue
            for ref in journal.payload(receipt).get("paid_forecasts", []):
                if ref["reporting_month_id"] == calendar_month_id:
                    result[(ref["kind"], ref["id"])] = "paid"
        return result
    # Lost source authority never promotes a competitor to unquestioned future.
    # Close authority for stale economics remains with the existing source guards.
    for obligation in obligations(
        session,
        include_stale=True,
        require_candidates=True,
        calendar_month_id=calendar_month_id,
    ):
        for candidate in obligation["candidates"]:
            if candidate["facts"].get("reporting_month_id") == str(calendar_month_id):
                key = (candidate["kind"], int(candidate["facts"]["id"]))
                if result.get(key) != "unresolved":
                    result[key] = candidate["state"]
    return result


def apply(session, intent, *, request_id, confirmation_digest):
    if session.new or session.dirty or session.deleted:
        raise MyBrokerError("clean_session_required")
    fingerprint = digest([intent.model_dump(mode="json"), confirmation_digest])
    with coherent_read_snapshot(session):
        prior = session.get(BrokerMonthApply, request_id, populate_existing=True)
        if prior:
            if prior.request_fingerprint != fingerprint or journal.kind(prior) != CONTRACT:
                raise MyBrokerError("idempotency_conflict")
            return {**read(session, request_id), "duplicate": True}
    session.rollback()
    try:
        session.execute(
            update(BrokerMonthApply)
            .where(BrokerMonthApply.request_id == "")
            .values(request_id=BrokerMonthApply.request_id)
        )
        session.expire_all()
        prior = session.get(BrokerMonthApply, request_id)
        if prior:
            if prior.request_fingerprint != fingerprint:
                raise MyBrokerError("idempotency_conflict")
            session.rollback()
            return {**read(session, request_id), "duplicate": True}
        plan = _plan(session, intent)
        if plan["confirmation_digest"] != confirmation_digest:
            raise MyBrokerError("payout_preview_stale")
        if not plan["can_apply"]:
            raise MyBrokerError(";".join(plan["blockers"]))
        base = session.get(BrokerMonthApply, intent.base_request_id)
        proof = {
            "contract_version": CONTRACT,
            "operation": intent.operation,
            "base_request_id": base.request_id,
            "journal_revision": next_journal_revision(session),
            "intent": intent.model_dump(mode="json"),
            "targets": plan["targets"],
            "dependency": plan["dependency"],
            "predecessor_proof": plan["predecessor_proof"],
            "paid_forecasts": plan["paid_forecasts"],
        }
        if intent.operation == "retire":
            proof["targets"][0]["relation_id"] = intent.predecessor_id
        session.execute(
            insert(BrokerMonthApply).values(
                request_id=request_id,
                request_fingerprint=fingerprint,
                confirmation_digest=confirmation_digest,
                reporting_month_id=intent.reporting_month_id,
                account_id=intent.account_id,
                import_id=base.import_id,
                projection_json=canonical(proof),
                accepted_at=datetime.now(UTC),
            )
        )
        predecessor = (
            session.get(AppliedPayoutReconciliation, intent.predecessor_id)
            if intent.predecessor_id
            else None
        )
        if predecessor and predecessor.retired_request_id is None:
            session.execute(
                update(AppliedPayoutReconciliation)
                .where(AppliedPayoutReconciliation.id == predecessor.id)
                .values(retired_request_id=request_id)
            )
        if intent.operation in {"link", "reaffirm"}:
            target = plan["targets"][0]
            session.add(
                AppliedPayoutReconciliation(
                    **{
                        k: v
                        for k, v in target.items()
                        if k not in {"predecessor_id", "predecessor_retirement_request_id"}
                    },
                    supersedes_id=intent.predecessor_id,
                    accepted_request_id=request_id,
                    counting_decision="count_actual",
                )
            )
        session.flush()
        session.commit()
    except BaseException:
        session.rollback()
        raise
    with Session(session.get_bind(), autoflush=False) as fresh:
        return {**read(fresh, request_id), "duplicate": False}
