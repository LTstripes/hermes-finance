"""H1-A source-backed ending EOD acceptance, without month/return consumers."""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation, localcontext

from pydantic import ValidationError
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from hermes_finance.database import coherent_read_operation
from hermes_finance.domain.historical_endpoints import AcceptanceEnvelope, EndpointIntent
from hermes_finance.persistence import (
    Account,
    AccountPerformanceScopeMembership,
    BrokerIdentityMapping,
    CashBalance,
    ClassNoCrossingCoverage,
    DepositSnapshot,
    ExecutedTrade,
    ExecutedTradeRevision,
    HistoricalEndpointApply,
    HistoricalEndpointRevision,
    Instrument,
    MyBrokerImport,
    PositionSnapshot,
    ReportingMonth,
)
from hermes_finance.services.executed_trades import _candidate, _context
from hermes_finance.services.mybroker_dispositions import (
    REASON,
    correction_dependencies,
    effective_bindings,
    impact,
)
from hermes_finance.services.mybroker_import import _crosses_cutoff, _reduce
from hermes_finance.statement_import.mybroker import PROVIDER, MyBrokerError, canonical, digest

CONTRACT = "h1-a-ending-rub-v1"
MAX_MINOR = 2**63 - 1


def endpoint_key(account_id: int, valuation_date: date) -> str:
    return digest([account_id, valuation_date.isoformat(), "eod", "RUB"])


def _material(row, fields: tuple[str, ...] | None = None) -> dict:
    names = fields or tuple(c.name for c in row.__table__.columns)
    return {name: str(getattr(row, name)) for name in names}


def _rows(session, model):
    return list(session.scalars(select(model).order_by(model.id)))


def _latest(session, key: str):
    return session.scalar(
        select(HistoricalEndpointRevision)
        .where(HistoricalEndpointRevision.endpoint_key == key)
        .order_by(HistoricalEndpointRevision.revision.desc())
        .limit(1)
    )


def _minor(value: str | None, blockers: set[str]) -> int | None:
    """Scale exactly, including source precision beyond Decimal's default context."""
    if value is None:
        blockers.add("ending_amount_missing")
        return None
    try:
        number = Decimal(value)
        if not number.is_finite():
            raise InvalidOperation
        with localcontext() as context:
            context.prec = max(32, len(number.as_tuple().digits) + 4)
            scaled = number * 100
            if scaled != scaled.to_integral_value():
                blockers.add("fractional_kopeck")
                return None
            if scaled < 0 or scaled > MAX_MINOR:
                blockers.add("amount_out_of_bounds")
                return None
            return int(scaled)
    except (InvalidOperation, ValueError):
        blockers.add("source_decimal_invalid")
        return None


def _bindings(
    session, row: MyBrokerImport, blockers: set[str], selected_bindings=None
) -> list[dict]:
    result = []
    registry = _rows(session, BrokerIdentityMapping)
    for binding in (
        selected_bindings if selected_bindings is not None else effective_bindings(session, row)
    ):
        matches = [
            m
            for m in registry
            if m.provider == PROVIDER
            and m.subject_kind == binding["kind"]
            and m.provider_identity == binding["identity"]
            and m.status == "effective"
        ]
        if (
            len(matches) != 1
            or matches[0].id != binding["mapping_id"]
            or matches[0].hermes_target_id != binding["hermes_id"]
        ):
            blockers.add("accepted_mapping_changed")
        else:
            target = session.get(
                Account if binding["kind"] == "account" else Instrument, binding["hermes_id"]
            )
            if target is None or (
                binding["kind"] == "instrument" and target.isin not in (None, binding["identity"])
            ):
                blockers.add("accepted_mapping_changed")
        result.append({**binding, "material": _material(matches[0]) if len(matches) == 1 else None})
    return result


def _components(document, bindings, import_id, side, blockers):
    instruments = {b["identity"]: b["hermes_id"] for b in bindings if b["kind"] == "instrument"}
    positions = []
    seen = set()
    positive = False
    for row in document["positions"]:
        instrument_id = instruments.get(row["isin"])
        if instrument_id is None:
            blockers.add("instrument_mapping_missing")
            continue
        if instrument_id in seen:
            blockers.add("duplicate_position")
        seen.add(instrument_id)
        quantity = (
            row["actual_quantity"] if side == "ending" else row.get("beginning_actual_quantity")
        )
        value = row.get("ending_value" if side == "ending" else "beginning_value")
        amount = _minor(value, blockers)
        if quantity is None:
            blockers.add("quantity_missing")
        else:
            q = Decimal(quantity)
            if q < 0 or (q == 0 and amount not in (0, None)):
                blockers.add("quantity_value_incompatible")
            positive |= q > 0
        if Decimal(row["actual_quantity"]) != Decimal(row["forward_quantity"]):
            blockers.add("endpoint_unsettled")
        positions.append(
            {
                "import_id": import_id,
                "section": "positions",
                "ordinal": row["ordinal"],
                "row_fingerprint": digest(row),
                "instrument_id": instrument_id,
                "quantity": quantity,
                "value": value,
                "value_kopecks": amount,
            }
        )
    if not positive:
        blockers.add("positive_stock_required")
    cash_rows = document.get("rub_money", [])
    cash = None
    if len(cash_rows) != 1:
        blockers.add("rub_cash_missing_or_ambiguous")
    else:
        row = cash_rows[0]
        value = row.get("ending_amount" if side == "ending" else "beginning_amount")
        cash = {
            "import_id": import_id,
            "section": "rub_money",
            "ordinal": row["ordinal"],
            "row_fingerprint": digest(row),
            "currency": "RUB",
            "amount": value,
            "amount_kopecks": _minor(value, blockers),
        }
    return positions, cash


def _economics(positions, cash):
    return {
        "positions": sorted(
            [[p["instrument_id"], p["quantity"], p["value_kopecks"]] for p in positions],
            key=canonical,
        ),
        "cash": cash["amount_kopecks"] if cash else None,
    }


def _overlap(session, intent, positions, cash, blockers):
    day, account_id = intent.valuation_date, intent.account_id
    months = {m.id: m for m in _rows(session, ReportingMonth)}
    dependencies, comparisons = [], []
    by_month = {}
    archived = []
    for row in _rows(session, PositionSnapshot):
        if row.account_id != account_id:
            continue
        month = months.get(row.reporting_month_id)
        if month is None:
            # Archives retain a reporting label, not an immutable snapshot date.
            # Quote date cannot prove the original actual date. A later reporting
            # period is provably irrelevant; older/unresolvable provenance blocks.
            period = row.archived_from_period or ""
            if not re.fullmatch(r"[0-9]{4}-[0-9]{2}", period):
                archived.append(row)
            else:
                try:
                    earliest = date.fromisoformat(period + "-01")
                except ValueError:
                    archived.append(row)
                else:
                    if earliest <= day:
                        archived.append(row)
        elif month.snapshot_date == day:
            by_month.setdefault(month.id, {"positions": [], "cash": [], "deposits": []})[
                "positions"
            ].append(row)
    for model, kind in ((CashBalance, "cash"), (DepositSnapshot, "deposits")):
        for row in _rows(session, model):
            month = months.get(row.reporting_month_id)
            if month and month.snapshot_date == day and row.account_id in (account_id, None):
                by_month.setdefault(month.id, {"positions": [], "cash": [], "deposits": []})[
                    kind
                ].append(row)
    if len(by_month) > 1 or archived:
        blockers.add("overlap_ambiguous_or_archived")
    expected = _economics(positions, cash)
    for month_id, components in sorted(by_month.items()):
        month = months[month_id]
        legacy = {
            "positions": sorted(
                [
                    [p.instrument_id, format(p.quantity.normalize(), "f"), p.market_value_kopecks]
                    for p in components["positions"]
                ],
                key=canonical,
            ),
            "cash": components["cash"][0].amount_kopecks if len(components["cash"]) == 1 else None,
        }
        compatible = (
            legacy == expected
            and not components["deposits"]
            and len(components["cash"]) == 1
            and components["cash"][0].account_id == account_id
            and components["cash"][0].currency == "RUB"
            and all(
                p.historical_instrument_type in (None, "stock") for p in components["positions"]
            )
        )
        if not compatible:
            blockers.add("reconciliation_required")
        material = {
            "month_id": month_id,
            "month": _material(month, ("id", "snapshot_date", "period_start", "period_end")),
            "positions": [
                _material(
                    p,
                    (
                        "id",
                        "instrument_id",
                        "quantity",
                        "market_value_kopecks",
                        "historical_instrument_type",
                        "updated_at",
                    ),
                )
                for p in components["positions"]
            ],
            "cash": [
                _material(
                    c,
                    (
                        "id",
                        "reporting_month_id",
                        "account_id",
                        "amount_kopecks",
                        "currency",
                        "include_in_capital",
                    ),
                )
                for c in components["cash"]
            ],
            "deposits": [
                _material(d, ("id", "balance_kopecks", "updated_at"))
                for d in components["deposits"]
            ],
        }
        dependencies.append(material)
        comparisons.append({"month_id": month_id, "identical": compatible})
    return (
        dependencies,
        comparisons,
        [
            _material(
                p,
                (
                    "id",
                    "account_id",
                    "instrument_id",
                    "quantity",
                    "market_value_kopecks",
                    "historical_instrument_type",
                    "archived_from_period",
                    "price_date",
                    "updated_at",
                ),
            )
            for p in archived
        ],
    )


def _source_union(session, intent, selected, blockers):
    """New relevant observations strengthen guards; none can relax accepted S2 truth."""
    docs, dependencies = [], []
    for row in _rows(session, MyBrokerImport):
        bindings = effective_bindings(session, row)
        relevant = any(
            b["kind"] == "account" and b["hermes_id"] == intent.account_id for b in bindings
        )
        if not relevant:
            continue
        document = json.loads(row.normalized_json)
        scoped_aliases = {
            b["identity"]
            for b in bindings
            if b["kind"] == "account" and b["hermes_id"] == intent.account_id
        }
        document = {**document, "source_accounts": sorted(scoped_aliases)}
        for section in ("positions", "rub_money", "money"):
            document[section] = [
                r for r in document.get(section, []) if r["source_account"] in scoped_aliases
            ]
        document["trades"] = [
            t for t in document["trades"] if t["core"]["source_account"] in scoped_aliases
        ]
        isins = {p["isin"] for p in document["positions"]} | {
            t["core"]["isin"] for t in document["trades"]
        }
        scoped_bindings = [
            b
            for b in bindings
            if (b["kind"] == "account" and b["identity"] in scoped_aliases)
            or (b["kind"] == "instrument" and b["identity"] in isins)
        ]
        docs.append(document)
        dependencies.append({"import_id": row.id, "fingerprint": digest(_material(row))})
        day = intent.valuation_date.isoformat()
        for trade in document["trades"]:
            if (
                trade["identity"] is None
                and trade["core"]["trade_time"][:10] <= day
                and (_crosses_cutoff(trade, day, day) or trade["repo_observed"])
            ):
                blockers.add("unresolved_cutoff_identity")
        if row.covered_from <= intent.valuation_date:
            blockers.update(document["syntax_blockers"])
            blockers.update(
                set(document.get("endpoint_blockers", [])) & {"position_row_unclassified"}
            )
        if row.covered_to <= intent.valuation_date and any(
            Decimal(p["actual_quantity"]) != Decimal(p["forward_quantity"])
            for p in document["positions"]
        ):
            blockers.add("unresolved_source_forward_exposure")
        if row.covered_to == intent.valuation_date and row.id != selected.id:
            other_bindings = _bindings(session, row, blockers, scoped_bindings)
            if row.parser_version != "mybroker-s1-v2":
                blockers.add("overlap_source_basis_unknown")
                continue
            other_positions, other_cash = _components(
                document, other_bindings, row.id, "ending", blockers
            )
            selected_doc = json.loads(selected.normalized_json)
            p, c = _components(
                selected_doc, effective_bindings(session, selected), selected.id, "ending", blockers
            )
            if _economics(other_positions, other_cash) != _economics(p, c):
                blockers.add("reconciliation_required")
        # A beginning observation supports the preceding day's EOD, never the report start.
        if (
            row.id != selected.id
            and row.covered_from.toordinal() - 1 == intent.valuation_date.toordinal()
        ):
            if row.parser_version != "mybroker-s1-v2":
                blockers.add("overlap_source_basis_unknown")
            else:
                p, c = _components(
                    document,
                    _bindings(session, row, blockers, scoped_bindings),
                    row.id,
                    "beginning",
                    blockers,
                )
                original = json.loads(selected.normalized_json)
                sp, sc = _components(
                    original, effective_bindings(session, selected), selected.id, "ending", blockers
                )
                if _economics(p, c) != _economics(sp, sc):
                    blockers.add("reconciliation_required")
    trades, conflicts = _reduce(docs)
    limitations = set()
    day = intent.valuation_date.isoformat()
    # Retain the complete reducer context (including pending-disappearance
    # evidence), but assign its conflicts to identities observed by the cutoff.
    # Check every occurrence: a disputed core must not move an earlier trade
    # into the future merely because the reducer selected its later observation.
    cutoff_observations = [
        t for document in docs for t in document["trades"] if t["core"]["trade_time"][:10] <= day
    ]
    cutoff_identities = {t["identity"] for t in cutoff_observations if t["identity"]}
    cutoff_cash_links = {
        (t["core"]["source_account"], t["ids"][0]) for t in cutoff_observations if t["ids"]
    }
    for document in docs:
        for money in document["money"]:
            if money["kind"] == "unsupported":
                limitations.add("money_semantics_unsupported")
            elif (
                money["kind"] in {"settlement", "commission"}
                and money["date"] > day
                and (money["source_account"], money["primary_id"]) in cutoff_cash_links
            ):
                # Native trade linkage also covers money-only later reports;
                # generic interval cash never proves unsettled cutoff exposure.
                blockers.add("unresolved_cutoff_cash_date")
    for identity, trade in trades.items():
        limitations.update(trade["blockers"])
        if identity not in cutoff_identities:
            continue
        blockers.update(set(trade["blockers"]) & set(conflicts))
        if _crosses_cutoff(trade, day, day):
            blockers.add("unresolved_cutoff_trade")
        if trade["repo_observed"] or trade["core"]["currency"] != "RUB":
            blockers.add("unsupported_cutoff_exposure")
    execution_dependencies = []
    context = None
    for trade in _rows(session, ExecutedTrade):
        if (
            trade.account_id != intent.account_id
            or json.loads(trade.core_json)["trade_time"][:10] > day
        ):
            continue
        if context is None:
            context = _context(session)
        revisions = list(
            session.scalars(
                select(ExecutedTradeRevision)
                .where(ExecutedTradeRevision.trade_id == trade.id)
                .order_by(ExecutedTradeRevision.revision)
            )
        )
        execution_dependencies.append(
            {"trade": _material(trade), "revisions": [_material(r) for r in revisions]}
        )
        if not revisions:
            blockers.add("canonical_trade_disputed")
            continue
        try:
            candidate = _candidate(session, context, trade.source_identity)
            if candidate["conflicts"] or revisions[-1].acceptance_state != "active":
                blockers.add("canonical_trade_disputed")
            for evidence in (json.loads(revisions[-1].evidence_json), candidate["evidence"]):
                if (
                    evidence["lifecycle"] == "pending"
                    or any(
                        evidence.get(field) is None or evidence[field] > day
                        for field in ("settlement_date", "depo_settlement_date")
                    )
                    or any(leg["effective_date"] > day for leg in evidence["cash_legs"])
                ):
                    blockers.add("unresolved_cutoff_trade")
                if evidence.get("readiness", {}).get("unsupported"):
                    blockers.add("unsupported_cutoff_exposure")
        except MyBrokerError:
            blockers.add("canonical_trade_disputed")
    return dependencies, execution_dependencies, sorted(limitations)


def _build(session, intent):
    blockers = set()
    exclusions = impact(session, (intent.account_id,))
    if exclusions:
        blockers.add(REASON)
    row = session.get(MyBrokerImport, intent.source_import_id)
    if row is None:
        raise MyBrokerError("source_import_not_found")
    document = json.loads(row.normalized_json)
    if (
        row.parser_version != "mybroker-s1-v2"
        or document["parser"] != row.parser_version
        or document["document_sha256"] != row.document_sha256
        or document["covered_to"] != row.covered_to.isoformat()
        or document["covered_from"] != row.covered_from.isoformat()
        or document["provider"] != PROVIDER
        or document.get("endpoint_basis", {}).get("ending_value") != "covered_to_eod"
    ):
        blockers.add("source_integrity_or_version")
    if intent.source_side != "ending":
        blockers.add("beginning_apply_unsupported")
    if intent.source_side == "ending" and row.covered_to != intent.valuation_date:
        blockers.add("exact_ending_date_required")
    bindings = _bindings(session, row, blockers)
    accounts = {b["identity"]: b["hermes_id"] for b in bindings if b["kind"] == "account"}
    observed_aliases = (
        {document["filename_account"]}
        | {
            p["source_account"]
            for section in ("positions", "rub_money", "money")
            for p in document.get(section, [])
        }
        | {t["core"]["source_account"] for t in document["trades"]}
    )
    if any(accounts.get(alias) != intent.account_id for alias in observed_aliases):
        blockers.add("single_account_bindings_required")
    blockers.update(document["syntax_blockers"])
    blockers.update(document.get("endpoint_conflicts", []))
    blockers.update(set(document.get("endpoint_blockers", [])) & {"position_row_unclassified"})
    positions, cash = _components(document, bindings, row.id, intent.source_side, blockers)
    source_set = digest(
        {
            "account_id": intent.account_id,
            "valuation_date": intent.valuation_date.isoformat(),
            "side": intent.source_side,
            "import_id": row.id,
            "rows": [p["row_fingerprint"] for p in positions]
            + ([cash["row_fingerprint"]] if cash else []),
        }
    )
    claims = intent.claims
    if claims is None:
        blockers.add("endpoint_claims_missing")
    else:
        if (
            claims.account_id != intent.account_id
            or claims.valuation_date != intent.valuation_date
            or claims.source_side != intent.source_side
            or claims.source_set_fingerprint != source_set
        ):
            blockers.add("claim_binding_mismatch")
        for name in (
            "inventory_complete",
            "other_components_absent",
            "rub_cash_complete_and_reconciled",
        ):
            if not getattr(claims, name):
                blockers.add(name + "_unconfirmed")
        fingerprints = claims.rub_stock_basis_confirmed
        if sorted(fingerprints) != sorted(p["row_fingerprint"] for p in positions):
            blockers.add("rub_stock_basis_unconfirmed")
    memberships = [
        m
        for m in _rows(session, AccountPerformanceScopeMembership)
        if m.account_id == intent.account_id
        and m.effective_from <= intent.valuation_date
        and (m.effective_to is None or m.effective_to >= intent.valuation_date)
    ]
    if len(memberships) != 1:
        blockers.add("membership_missing_or_ambiguous")
    overlap, comparisons, archived = _overlap(session, intent, positions, cash, blockers)
    sources, executions, limitations = _source_union(session, intent, row, blockers)
    total = None
    amounts = [p["value_kopecks"] for p in positions] + ([cash["amount_kopecks"]] if cash else [])
    if cash and all(a is not None for a in amounts):
        total = sum(amounts)
        if total > MAX_MINOR:
            blockers.add("account_total_out_of_bounds")
            total = None
    evidence = {
        "contract_version": CONTRACT,
        "intent": intent.model_dump(mode="json"),
        "source": {
            "import_id": row.id,
            "document_sha256": row.document_sha256,
            "parser": row.parser_version,
            "provider": document["provider"],
            "covered_from": row.covered_from.isoformat(),
            "covered_to": row.covered_to.isoformat(),
            "side": intent.source_side,
            "basis": "covered_to_eod" if intent.source_side == "ending" else "previous_day_eod",
            "fingerprint": digest(_material(row)),
        },
        "bindings": bindings,
        "positions": positions,
        "rub_cash": cash,
        "claims": claims.model_dump(mode="json") if claims else None,
        "membership": [_material(m) for m in memberships],
        "endpoint_c1": None,
        "dependencies": {
            "sources": sources,
            "executions": executions,
            "overlap": overlap,
            "archived": archived,
        },
    }
    corrections = correction_dependencies(session, (intent.account_id,))
    if corrections:
        evidence["dependencies"]["corrections"] = corrections
    if exclusions:
        evidence["dependencies"]["instrument_dispositions"] = exclusions
        total = None
    return evidence, sorted(blockers), limitations, comparisons, total, source_set


def _support(evidence):
    """Reviewed support identity excludes request operation/expected revision."""
    return {k: v for k, v in evidence.items() if k != "intent"}


def _preview_context(session, intent, current):
    months = [
        m
        for m in _rows(session, ReportingMonth)
        if m.snapshot_date == intent.valuation_date
        or m.period_start <= intent.valuation_date <= m.period_end
        or (
            current
            and m.id
            in {d["month_id"] for d in json.loads(current.evidence_json)["dependencies"]["overlap"]}
        )
    ]
    coverages = [
        c
        for c in _rows(session, ClassNoCrossingCoverage)
        if c.covered_from <= intent.valuation_date <= c.covered_to
    ]
    return {
        "months": [_material(m) for m in months],
        "coverages": [_material(c) for c in coverages],
        "target": _material(current) if current else None,
    }


def _plan(session, intent):
    key = endpoint_key(intent.account_id, intent.valuation_date)
    current = _latest(session, key)
    blockers = set()
    if current is not None and intent.expected_revision != current.revision:
        blockers.add("stale_endpoint_revision")
    if current is None and (intent.expected_revision is not None or intent.operation != "accept"):
        blockers.add("endpoint_not_found")
    action, evidence, limitations, comparisons, total, source_set = (
        "created",
        None,
        [],
        [],
        None,
        None,
    )
    if intent.operation == "revoke":
        evidence = json.loads(current.evidence_json) if current else None
        action = "revoked" if current and current.acceptance_state != "revoked" else "noop"
    else:
        evidence, reasons, limitations, comparisons, total, source_set = _build(session, intent)
        blockers.update(reasons)
        if current:
            old = json.loads(current.evidence_json)
            if _economics(old["positions"], old["rub_cash"]) != _economics(
                evidence["positions"], evidence["rub_cash"]
            ):
                blockers.add("reconciliation_required")
            identical = _support(old) == _support(evidence)
            if intent.operation == "accept":
                if current.acceptance_state != "accepted" or not identical:
                    blockers.add("explicit_reaffirm_required")
                action = "noop"
            else:
                action = (
                    "noop" if current.acceptance_state == "accepted" and identical else "reaffirmed"
                )
    context = _preview_context(session, intent, current)
    if action != "noop" and any(m["status"] == "closed" for m in context["months"]):
        blockers.add("reopen_required")
    result = {
        "endpoint_key": key,
        "basis": "eod",
        "currency": "RUB",
        "valuation_date": intent.valuation_date.isoformat(),
        "actual_valuation_date": evidence["source"]["covered_to"]
        if evidence and intent.source_side == "ending"
        else (
            (date.fromisoformat(evidence["source"]["covered_from"]) - timedelta(days=1)).isoformat()
            if evidence
            else None
        ),
        "expected_revision": intent.expected_revision,
        "evidence": evidence,
        "source_set_fingerprint": source_set,
        "observed_candidate_total_kopecks": total,
        "total_value_kopecks": None,
        "overlap_comparisons": comparisons,
        "return_limitations": limitations,
        "blockers": sorted(blockers),
        "can_apply": not blockers,
        "candidate_action": action,
        "dependency_impacts": context,
    }
    result["confirmation_digest"] = digest(
        {"contract": CONTRACT, "intent": intent.model_dump(mode="json"), "plan": result}
    )
    return result


@coherent_read_operation
def preview_historical_endpoint(session: Session, intent: EndpointIntent) -> dict:
    return _plan(session, intent)


def _read(session, key):
    current = _latest(session, key)
    if current is None:
        raise MyBrokerError("endpoint_not_found")
    reasons, total = [], None
    state = current.acceptance_state
    evidence = json.loads(current.evidence_json)
    try:
        frozen = AcceptanceEnvelope.model_validate(evidence)
        if (
            current.account_id != frozen.intent.account_id
            or current.valuation_date != frozen.intent.valuation_date
            or key != endpoint_key(current.account_id, current.valuation_date)
            or (current.basis, current.currency) != ("eod", "RUB")
        ):
            raise ValueError("endpoint_identity_invalid")
        if digest(_support(evidence)) != current.material_signature:
            raise ValueError("material_signature_invalid")
        rebuilt, blockers, _, _, candidate_total, _ = _build(session, frozen.intent)
        reasons.extend(blockers)
        # New identical source occurrences corroborate. Frozen dependencies must
        # still exist byte-for-byte; additional contradictory evidence blocks above.
        frozen_sources = evidence["dependencies"]["sources"]
        current_sources = rebuilt["dependencies"]["sources"]
        if any(item not in current_sources for item in frozen_sources):
            reasons.append("source_dependency_changed")
        rebuilt["dependencies"]["sources"] = frozen_sources
        if _support(rebuilt) != _support(evidence):
            reasons.append("dependency_changed")
        if state == "accepted":
            if reasons:
                state = "invalidated"
            else:
                total = candidate_total
    except (ValidationError, ValueError, KeyError, TypeError, MyBrokerError):
        reasons.append("accepted_envelope_invalid")
        if state == "accepted":
            state = "invalidated"
    history = list(
        session.scalars(
            select(HistoricalEndpointRevision)
            .where(HistoricalEndpointRevision.endpoint_key == key)
            .order_by(HistoricalEndpointRevision.revision)
        )
    )
    return {
        "endpoint_key": key,
        "revision_id": current.id,
        "revision": current.revision,
        "account_id": current.account_id,
        "valuation_date": current.valuation_date.isoformat(),
        "basis": current.basis,
        "currency": current.currency,
        "acceptance_state": current.acceptance_state,
        "effective_state": state,
        "total_value_kopecks": total,
        "evidence": evidence,
        "blockers": sorted(set(reasons)),
        "history": [
            {
                "id": r.id,
                "revision": r.revision,
                "operation": r.operation,
                "acceptance_state": r.acceptance_state,
                "reason_code": r.reason_code,
                "previous_revision_id": r.previous_revision_id,
            }
            for r in history
        ],
    }


@coherent_read_operation
def read_historical_endpoint(session: Session, key: str) -> dict:
    return _read(session, key)


def _append(session, current, *, key, intent, evidence, operation, state, reason=None, flush=True):
    row = HistoricalEndpointRevision(
        endpoint_key=key,
        account_id=intent.account_id,
        valuation_date=intent.valuation_date,
        basis="eod",
        currency="RUB",
        revision=current.revision + 1 if current else 1,
        previous_revision_id=current.id if current else None,
        operation=operation,
        acceptance_state=state,
        evidence_json=canonical(evidence),
        material_signature=digest(_support(evidence)),
        reason_code=reason,
        recorded_at=datetime.now(UTC),
    )
    session.add(row)
    if flush:
        session.flush()
    return row


def apply_historical_endpoint(session, intent, *, confirmation_digest, request_id):
    if session.new or session.dirty or session.deleted:
        raise MyBrokerError("clean_session_required")
    intent_digest = digest(intent.model_dump(mode="json"))
    try:
        session.execute(
            text("UPDATE historical_endpoint_revisions SET revision = revision WHERE 0")
        )
        session.expire_all()
        receipt = session.scalar(
            select(HistoricalEndpointApply).where(HistoricalEndpointApply.request_id == request_id)
        )
        if receipt:
            if (
                receipt.intent_digest != intent_digest
                or receipt.confirmation_digest != confirmation_digest
            ):
                raise MyBrokerError("idempotency_conflict")
            key, revision_id, action = (
                receipt.endpoint_key,
                receipt.revision_id,
                receipt.result_action,
            )
            replay = True
        else:
            plan = _plan(session, intent)
            if plan["confirmation_digest"] != confirmation_digest:
                raise MyBrokerError("preview_stale")
            if not plan["can_apply"]:
                raise MyBrokerError(";".join(plan["blockers"]))
            key, action = plan["endpoint_key"], plan["candidate_action"]
            current = _latest(session, key)
            if action == "noop":
                row = current
            else:
                evidence = plan["evidence"]
                AcceptanceEnvelope.model_validate(evidence)
                row = _append(
                    session,
                    current,
                    key=key,
                    intent=intent,
                    evidence=evidence,
                    operation=intent.operation,
                    state="revoked" if intent.operation == "revoke" else "accepted",
                    reason=intent.reason_code,
                )
            revision_id = row.id
            session.add(
                HistoricalEndpointApply(
                    request_id=request_id,
                    intent_digest=intent_digest,
                    confirmation_digest=confirmation_digest,
                    endpoint_key=key,
                    revision_id=revision_id,
                    result_action=action,
                    committed_at=datetime.now(UTC),
                )
            )
            session.flush()
            replay = False
        session.commit()
    except Exception:
        session.rollback()
        raise
    # A new session performs the committed read; an Apply echo cannot prove it.
    with Session(session.get_bind(), autoflush=False) as fresh:
        readback = read_historical_endpoint(fresh, key)
    return {
        "request_id": request_id,
        "committed_revision_id": revision_id,
        "result_action": action,
        "replayed": replay,
        "readback": readback,
    }


def retire_dependencies(
    session,
    *,
    month_id=None,
    mapping_id=None,
    membership_id=None,
    position_id=None,
    cash_id=None,
    deposit_id=None,
    trade_id=None,
    instrument_id=None,
    overlap_account_id=None,
    reason="dependency_changed",
):
    """Append lifecycle loss of authority only for exact frozen dependencies."""
    latest = {}
    for row in _rows(session, HistoricalEndpointRevision):
        latest[row.endpoint_key] = row
    for row in session.new:
        if isinstance(row, HistoricalEndpointRevision):
            latest[row.endpoint_key] = row
    for current in latest.values():
        if current.acceptance_state != "accepted":
            continue
        if overlap_account_id is not None and current.account_id != overlap_account_id:
            continue
        evidence = json.loads(current.evidence_json)
        dependencies = evidence["dependencies"]
        match = mapping_id is not None and any(
            b["mapping_id"] == mapping_id for b in evidence["bindings"]
        )
        match |= instrument_id is not None and any(
            b["kind"] == "instrument" and b["hermes_id"] == instrument_id
            for b in evidence["bindings"]
        )
        match |= membership_id is not None and any(
            m["id"] == str(membership_id) for m in evidence["membership"]
        )
        match |= trade_id is not None and any(
            d["trade"]["id"] == str(trade_id) for d in dependencies["executions"]
        )
        for overlap in dependencies["overlap"]:
            match |= month_id is not None and overlap["month_id"] == month_id
            for identity, kind in (
                (position_id, "positions"),
                (cash_id, "cash"),
                (deposit_id, "deposits"),
            ):
                match |= identity is not None and any(
                    r["id"] == str(identity) for r in overlap[kind]
                )
        if match:
            # Dependency retirement changes authority. Existing CLOSED history
            # must be reopened first; reads may already be effectively invalidated.
            reopened = {
                m.id
                for m in session.dirty
                if isinstance(m, ReportingMonth)
                and m.status == "draft"
                and inspect(m).attrs.status.history.has_changes()
            }
            for month in session.execute(select(ReportingMonth.__table__)).mappings():
                if (
                    month["status"] == "closed"
                    and month["id"] not in reopened
                    and (
                        month["id"] in {d["month_id"] for d in dependencies["overlap"]}
                        or month["snapshot_date"] == current.valuation_date
                        or month["period_start"] <= current.valuation_date <= month["period_end"]
                    )
                ):
                    raise MyBrokerError("reopen_required")
            _append(
                session,
                current,
                key=current.endpoint_key,
                intent=EndpointIntent.model_validate(evidence["intent"]),
                evidence=evidence,
                operation="retire",
                state="retired",
                reason=reason,
                flush=False,
            )
