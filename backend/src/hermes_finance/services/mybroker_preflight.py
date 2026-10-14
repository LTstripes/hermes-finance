"""Bounded, ephemeral original inventory before S1 or ReportingMonth acceptance.

Source endpoints are observations, never reconstructed monthly valuations. Only
the existing S1 reducer owns native trade projections; nothing here is staged.
"""

from __future__ import annotations

import calendar
import json
from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import Decimal, localcontext

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.database import coherent_read_snapshot
from hermes_finance.persistence import MyBrokerImport
from hermes_finance.services.historical_reconstruction import _endpoint, _month_ends
from hermes_finance.services.mybroker_identity import _prepare as identity_plan
from hermes_finance.services.mybroker_import import _attach_cash, _reduce, parse_import_original
from hermes_finance.services.mybroker_money_candidates import _original_equal
from hermes_finance.statement_import.mybroker import (
    MAX_BYTES,
    PARSER,
    PROVIDER,
    MyBrokerError,
    canonical,
)
from hermes_finance.statement_import.mybroker_identity import parse_identity

MAX_DOCUMENTS = 8
MAX_BATCH_BYTES = 32 * 1024 * 1024
MAX_BATCH_ROWS = 30000
MAX_MONTHS = 120


def _difference(left: str | None, right: str | None, *, money: bool = False) -> dict:
    if left is None or right is None:
        return {"state": "unknown", "left": left, "right": right, "delta": None}
    # S1 accepts up to 48 digits; preserve all of them, including the final cent.
    with localcontext() as context:
        context.prec = 100
        delta = Decimal(right) - Decimal(left)
        result = {
            "state": "equal" if not delta else "conflict",
            "left": left,
            "right": right,
            "delta": format(delta, "f"),
        }
        if money:
            scaled = delta * 100
            result["delta_kopecks"] = int(scaled) if scaled == scaled.to_integral_value() else None
            result["minor_unit_state"] = (
                "exact"
                if all(
                    (Decimal(v) * 100) == (Decimal(v) * 100).to_integral_value()
                    for v in (left, right)
                )
                else "sub_kopeck_observation"
            )
        return result


def _seam(left: dict, right: dict, alias: str) -> dict:
    a, b = left["document"], right["document"]
    left_positions = defaultdict(list)
    right_positions = defaultdict(list)
    for document, positions in ((a, left_positions), (b, right_positions)):
        for row in document["positions"]:
            if row["source_account"] == alias:
                positions[row["isin"]].append(row)
    securities = []
    for isin in sorted(left_positions.keys() | right_positions.keys()):
        lrows, rrows = left_positions[isin], right_positions[isin]
        lrow = lrows[0] if len(lrows) == 1 else {}
        rrow = rrows[0] if len(rrows) == 1 else {}
        securities.append(
            {
                "isin": isin,
                "quantity": _difference(
                    lrow.get("actual_quantity"), rrow.get("beginning_actual_quantity")
                ),
                "value": _difference(
                    lrow.get("ending_value"), rrow.get("beginning_value"), money=True
                ),
                "inventory_state": "observed" if len(lrows) == len(rrows) == 1 else "unknown",
            }
        )
    lc = [r for r in a["rub_money"] if r["source_account"] == alias]
    rc = [r for r in b["rub_money"] if r["source_account"] == alias]
    cash = _difference(
        lc[0].get("ending_amount") if len(lc) == 1 else None,
        rc[0].get("beginning_amount") if len(rc) == 1 else None,
        money=True,
    )
    states = [cash["state"]] + [r[k]["state"] for r in securities for k in ("quantity", "value")]
    blockers = sorted(
        set(
            a["syntax_blockers"]
            + b["syntax_blockers"]
            + a["endpoint_conflicts"]
            + b["endpoint_conflicts"]
            + left["binder_blockers"]
            + right["binder_blockers"]
        )
    )
    if any("position_row_unclassified" in d["endpoint_blockers"] for d in (a, b)):
        blockers.append("position_row_unclassified")
    return {
        "source_account": alias,
        "left_document": a["document_sha256"],
        "right_document": b["document_sha256"],
        "cutoff": a["covered_to"],
        "state": "conflict"
        if "conflict" in states
        else (
            "equal_observations"
            if securities and "unknown" not in states and not blockers
            else "unknown"
        ),
        "securities": securities,
        "rub_cash": cash,
        "blockers": sorted(set(blockers)),
        "financial_completeness": "unknown",
    }


def _overlaps(documents: list[dict], reduced: dict) -> list[dict]:
    observations = defaultdict(list)
    for document in documents:
        for trade in document["trades"]:
            if trade["identity"]:
                observations[trade["identity"]].append((document, trade))
    result = []
    for identity, occurrences in sorted(observations.items()):
        projection = reduced[identity]
        multiplicity = Counter(d["document_sha256"] for d, _ in occurrences)
        conflicts = set(projection["blockers"]) & {
            "immutable_trade_conflict",
            "settled_to_pending_conflict",
            "pending_disappeared",
            "trade_material_conflict",
        }
        if any(count > 1 for count in multiplicity.values()):
            conflicts.add("native_identity_multiplicity_conflict")
        missing = [
            d["document_sha256"]
            for d in documents
            if projection["core"]["source_account"] in d["source_accounts"]
            and d["covered_from"] <= projection["core"]["trade_time"][:10] <= d["covered_to"]
            and not any(t["identity"] == identity for t in d["trades"])
        ]
        if missing:
            conflicts.add("native_identity_missing_in_overlap")
        states = {t["state"] for _, t in occurrences}
        materials = {
            canonical({k: v for k, v in t.items() if k not in ("ordinal", "section")})
            for _, t in occurrences
        }
        state = (
            "conflict"
            if conflicts
            else (
                "pending_to_settled"
                if len(states) > 1
                else (
                    "exact_duplicate"
                    if len(occurrences) > 1 and len(materials) == 1
                    else ("enrichment" if len(occurrences) > 1 else "observed")
                )
            )
        )
        result.append(
            {
                "identity": identity,
                "state": state,
                "conflicts": sorted(conflicts),
                "occurrences": [
                    {"document_sha256": d["document_sha256"], "trade": t} for d, t in occurrences
                ],
                "missing_in_documents": sorted(missing),
                "projection": projection,
                "money_nkd_fee_authority": "unknown",
            }
        )
    return result


def _calendar(entries: list[dict], start: date, end: date) -> list[dict]:
    cutoffs = _month_ends(
        start.replace(day=1), date(end.year, end.month, calendar.monthrange(end.year, end.month)[1])
    )
    if len(cutoffs) > MAX_MONTHS:
        raise MyBrokerError("preflight_range_too_large")
    result = []
    for account in sorted({e["document"]["filename_account"] for e in entries}):
        selected = [e for e in entries if e["document"]["filename_account"] == account]
        for cutoff in cutoffs:
            month_start = cutoff.replace(day=1)
            full = [
                e
                for e in selected
                if e["document"]["covered_from"] == month_start.isoformat()
                and e["document"]["covered_to"] == cutoff.isoformat()
            ]
            endpoints = [
                {"document_sha256": e["document"]["document_sha256"], **row}
                for e in selected
                for row in e["accounts"]
                for side in ("beginning", "ending")
                if row[side]["cutoff"] == cutoff.isoformat()
            ]
            # Keep side references, not an aggregated or borrowed month snapshot.
            endpoint_refs = [
                {
                    "document_sha256": r["document_sha256"],
                    "source_account": r["source_account"],
                    "sides": [
                        s for s in ("beginning", "ending") if r[s]["cutoff"] == cutoff.isoformat()
                    ],
                    "observation_states": {
                        s: r[s]["observation_state"]
                        for s in ("beginning", "ending")
                        if r[s]["cutoff"] == cutoff.isoformat()
                    },
                }
                for r in endpoints
            ]
            reasons = []
            if not full:
                reasons.append("whole_month_original_missing")
            if not endpoint_refs:
                reasons.append("month_end_eod_missing")
            endpoints_observed = bool(endpoint_refs) and all(
                state == "observed"
                for ref in endpoint_refs
                for state in ref["observation_states"].values()
            )
            if endpoint_refs and not endpoints_observed:
                reasons.append("month_end_eod_unavailable")
            result.append(
                {
                    "filename_account": account,
                    "month": cutoff.strftime("%Y-%m"),
                    "whole_month_documents": [e["document"]["document_sha256"] for e in full],
                    "endpoint_references": endpoint_refs,
                    "whole_month_original_state": "observed" if full else "missing",
                    "endpoint_state": "observed" if endpoints_observed else "unknown",
                    "state": "observed" if full and endpoints_observed else "unknown",
                    "blockers": reasons,
                    "financial_completeness": "unknown",
                }
            )
    return result


def preview_batch(
    session: Session,
    *,
    originals: list[tuple[str, bytes]],
    account_bindings: list[dict] | None = None,
    requested_from: date | None = None,
    requested_to: date | None = None,
) -> dict:
    """Read-only snapshot, bounded memory; no receipts, sources or month required."""
    if not 1 <= len(originals) <= MAX_DOCUMENTS:
        raise MyBrokerError("preflight_batch_size_invalid")
    if sum(len(raw) for _, raw in originals) > MAX_BATCH_BYTES or any(
        not raw or len(raw) > MAX_BYTES for _, raw in originals
    ):
        raise MyBrokerError("document_size_invalid")
    if (requested_from is None) != (requested_to is None) or (
        requested_from is not None and requested_to is not None and requested_from > requested_to
    ):
        raise MyBrokerError("preflight_range_invalid")
    with coherent_read_snapshot(session):
        return _preview(session, originals, account_bindings or [], requested_from, requested_to)


def _preview(session, originals, account_bindings, requested_from, requested_to):
    entries = []
    seen = {}
    total_rows = 0
    # Validate at batch grain; an alias belonging to another uploaded original
    # must not become a false per-document account_alias_unobserved conflict.
    evidence_by_original = {
        (filename, raw): parse_identity(raw, filename) for filename, raw in originals
    }
    batch_aliases = {
        alias for evidence in evidence_by_original.values() for alias in evidence["source_accounts"]
    }
    requested_aliases = [binding["identity"] for binding in account_bindings]
    if len(set(requested_aliases)) != len(requested_aliases):
        raise MyBrokerError("duplicate_account_alias")
    if set(requested_aliases) - batch_aliases:
        raise MyBrokerError("account_alias_unobserved")
    for filename, raw in sorted(originals, key=lambda item: (item[0], item[1])):
        document = parse_import_original(session, raw, filename)
        evidence = evidence_by_original[(filename, raw)]
        plan = identity_plan(
            session,
            evidence,
            [b for b in account_bindings if b["identity"] in evidence["source_accounts"]],
        )
        document["source_accounts"] = evidence["source_accounts"]
        binder = []
        source = session.scalar(
            select(MyBrokerImport).where(
                MyBrokerImport.document_sha256 == document["document_sha256"]
            )
        )
        if source is not None:
            stored = json.loads(source.normalized_json)
            if (
                source.parser_version != PARSER
                or stored.get("parser") != PARSER
                or stored.get("provider") != PROVIDER
                or source.covered_from.isoformat() != document["covered_from"]
                or source.covered_to.isoformat() != document["covered_to"]
                or not _original_equal(document, stored)
                or any(
                    stored.get(k) != document[k]
                    for k in ("document_sha256", "filename_account", "covered_from", "covered_to")
                )
            ):
                binder.append("immutable_source_binder_mismatch")
        key = (document["document_sha256"], filename)
        if key in seen:
            seen[key]["upload_count"] += 1
            continue
        total_rows += (
            len(document["positions"])
            + len(document["rub_money"])
            + len(document["trades"])
            + len(document["money"])
        )
        if total_rows > MAX_BATCH_ROWS:
            raise MyBrokerError("preflight_row_limit_exceeded")
        entry = {
            "filename": filename,
            "document": document,
            "identity_plan": plan,
            "binder_blockers": binder,
            "upload_count": 1,
            "source_acceptance": "persisted_source_reference"
            if source is not None
            else "unpersisted_original",
        }
        entries.append(entry)
        seen[key] = entry
    entries.sort(
        key=lambda e: (
            e["document"]["covered_to"],
            e["document"]["covered_from"],
            e["document"]["document_sha256"],
            e["filename"],
        )
    )
    documents = [e["document"] for e in entries]
    filename_bindings = defaultdict(set)
    for entry in entries:
        filename_bindings[entry["document"]["document_sha256"]].add(entry["filename"])
    for entry in entries:
        if len(filename_bindings[entry["document"]["document_sha256"]]) > 1:
            entry["binder_blockers"].append("original_filename_conflict")
    for entry in entries:
        document = entry["document"]
        prior, _ = _reduce([d for d in documents if d["covered_to"] < document["covered_to"]])
        entry["cash_blockers"] = _attach_cash(document, prior)
    reduced, conflicts = _reduce(documents)
    overlaps = _overlaps(documents, reduced)
    batch_conflicts = sorted(set(conflicts) | {c for row in overlaps for c in row["conflicts"]})
    for entry in entries:
        document, plan = entry["document"], entry["identity_plan"]
        entry["accounts"] = []
        for alias in sorted(
            set(document["source_accounts"]) - {document["filename_account"]}
            | {p["source_account"] for p in document["positions"] + document["rub_money"]}
        ):
            constraints = [t for t in document["trades"] if t["core"]["source_account"] == alias]
            common = sorted(
                set(
                    document["syntax_blockers"]
                    + document["endpoint_conflicts"]
                    + entry["binder_blockers"]
                )
            )
            sides = {
                side: _endpoint(document, None, {alias}, side, common, constraints, [])
                for side in ("beginning", "ending")
            }
            entry["accounts"].append({"source_account": alias, **sides})
        entry["mappings"] = {
            "state": "ready"
            if plan["can_stage"]
            and all(p["mapping_id"] for p in plan["accounts"] + plan["instruments"])
            else "blocked",
            "accounts": plan["accounts"],
            "instruments": plan["instruments"],
            "conflicts": plan["conflicts"],
            "evidence_gaps": plan["evidence_gaps"],
        }
        for mapping in entry["mappings"]["accounts"]:
            mapping["state"] = (
                "ready" if mapping["mapping_id"] and mapping["hermes_id"] else "missing"
            )
            if any(
                c.startswith(("account_", "revoked_account_", "source_account_"))
                and c != "account_binding_required"
                for c in plan["conflicts"]
            ):
                mapping["state"] = "ambiguous"
        for mapping in entry["mappings"]["instruments"]:
            mapping["state"] = (
                "ready" if mapping["mapping_id"] and not mapping["evidence_gaps"] else "missing"
            )
            mapping["type_state"] = "observed" if mapping["instrument_type"] else "unknown"
            mapping["denomination_state"] = (
                "observed_catalogue" if mapping["currency"] else "unknown"
            )
            if any(c.startswith(("instrument_", "revoked_instrument_")) for c in plan["conflicts"]):
                mapping["state"] = "ambiguous"
            if "instrument_type_conflict" in plan["conflicts"]:
                mapping["type_state"] = "ambiguous"
        start, end = (
            date.fromisoformat(document["covered_from"]),
            date.fromisoformat(document["covered_to"]),
        )
        full_month = (
            start.day == 1
            and start.year == end.year
            and start.month == end.month
            and end.day == calendar.monthrange(end.year, end.month)[1]
        )
        observed = bool(entry["accounts"]) and all(
            a[s]["observation_state"] == "observed"
            for a in entry["accounts"]
            for s in ("beginning", "ending")
        )
        candidate = (
            full_month
            and observed
            and plan["can_stage"]
            and not (entry["binder_blockers"] or batch_conflicts or document["syntax_blockers"])
        )
        entry["statuses"] = {
            "source_observations": "observed" if observed else "partial_or_unknown",
            "calendar_seam": "not_evaluated",
            "financial_completeness": "unknown",
            "potential_incomplete_draft": "candidate_for_existing_separate_reviewed_draft_preview"
            if candidate
            else "blocked",
            "close_performance": "blocked",
        }
        entry["range_kind"] = "whole_month" if full_month else "partial_or_wide"
        entry["inventory"] = {
            "money": document["money"],
            "trades": document["trades"],
            "unsupported_money_count": sum(r["kind"] == "unsupported" for r in document["money"]),
            "repo_count": sum(t["repo_observed"] for t in document["trades"]),
            "identityless_trade_count": sum(t["identity"] is None for t in document["trades"]),
            "section_inventory": document["section_inventory"],
            "syntax_blockers": document["syntax_blockers"],
            "cash_blockers": sorted(set(entry["cash_blockers"])),
            "money_nkd_fee_authority": "unknown",
        }
        del entry["identity_plan"]
    seams = []
    for left in entries:
        for right in entries:
            if date.fromisoformat(left["document"]["covered_to"]) + timedelta(
                days=1
            ) != date.fromisoformat(right["document"]["covered_from"]):
                continue
            aliases = {a["source_account"] for a in left["accounts"]} & {
                a["source_account"] for a in right["accounts"]
            }
            for alias in sorted(aliases):
                seams.append(_seam(left, right, alias))
    for entry in entries:
        related = [
            s["state"]
            for s in seams
            if entry["document"]["document_sha256"] in (s["left_document"], s["right_document"])
        ]
        entry["statuses"]["calendar_seam"] = (
            "conflict"
            if "conflict" in related
            else ("unknown" if not related or "unknown" in related else "equal_observations")
        )
        if "conflict" in related or entry["binder_blockers"]:
            entry["statuses"]["potential_incomplete_draft"] = "blocked"
    start = requested_from or min(date.fromisoformat(d["covered_from"]) for d in documents)
    end = requested_to or max(date.fromisoformat(d["covered_to"]) for d in documents)
    availability = [
        {
            "filename_account": account,
            "report_2025": "observed_range_only"
            if any(
                d["filename_account"] == account
                and d["covered_from"] <= "2025-12-31"
                and d["covered_to"] >= "2025-01-01"
                for d in documents
            )
            else "unknown_missing_original",
            "adjacent_originals": "observed"
            if any(
                s
                for s in seams
                if any(
                    d["filename_account"] == account and d["document_sha256"] == s["left_document"]
                    for d in documents
                )
            )
            else "unknown_missing_adjacent_original",
        }
        for account in sorted({d["filename_account"] for d in documents})
    ]
    return {
        "contract": "mybroker-batch-preflight-v1",
        "kind": "preflight",
        "documents": entries,
        "calendar": _calendar(entries, start, end),
        "seams": seams,
        "native_trade_inventory": overlaps,
        "conflicts": batch_conflicts,
        "report_availability": availability,
        "coverage_state": "unknown",
        "financial_completeness": "unknown",
        "financial_apply_available": False,
        "close_performance": "blocked",
        "persisted_source_inventory": "use_existing_h0_preview",
    }
