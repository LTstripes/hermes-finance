"""Read-only native account endpoints + existing effective H2 crossing evidence."""

import json
from datetime import timedelta
from decimal import DecimalException

from sqlalchemy import select

from hermes_finance.database import coherent_read_operation
from hermes_finance.domain.broker_statement_return import (
    BrokerStatementBasis,
    StatementCrossing,
    StatementEndpoint,
    StatementPosition,
    StatementSectionAuthority,
    StatementSource,
    calculate_statement_return,
)
from hermes_finance.persistence import (
    BrokerMonthApply,
    CashBoundaryCoverage,
    HistoricalOwnerFlow,
    MyBrokerImport,
    ReportingMonth,
)
from hermes_finance.services import broker_month_journal as journal
from hermes_finance.services import (
    broker_months,
    broker_sections,
    mybroker_import,
    source_cash_coverage,
    source_intake,
)
from hermes_finance.services.historical_owner_flows import read_historical_owner_flow
from hermes_finance.services.mybroker_dispositions import effective_bindings
from hermes_finance.services.mybroker_money_candidates import _original_equal
from hermes_finance.statement_import.mybroker import PARSER, MyBrokerError, digest


@coherent_read_operation
def statement_sources(session, account_id):
    return [
        {
            "request_id": r.request_id,
            "account_id": r.account_id,
            "t0": s.covered_from - timedelta(days=1),
            "t1": s.covered_to,
        }
        for r in session.scalars(
            select(BrokerMonthApply)
            .where(BrokerMonthApply.account_id == account_id)
            .order_by(BrokerMonthApply.accepted_at, BrokerMonthApply.request_id)
        )
        if journal.kind(r) == journal.SOURCE
        and (s := session.get(MyBrokerImport, r.import_id)) is not None
    ]


def _endpoint(document, instruments, account_id, day, opening, reasons):
    side = "beginning" if opening else "ending"
    positions = []
    for row in document.get("positions", []):
        matched = [int(k) for k, v in instruments.items() if v[0] == row["isin"]]
        if len(matched) != 1:
            reasons.add("statement_instrument_identity_unproved")
        try:
            value = broker_months._minor(row[f"{side}_value"])
        except (MyBrokerError, DecimalException):
            value = None
        positions.append(
            StatementPosition(
                instrument_id=matched[0] if len(matched) == 1 else 0,
                isin=row["isin"],
                quantity=row["beginning_actual_quantity" if opening else "actual_quantity"],
                market_value_kopecks=value,
                source_ordinal=row["ordinal"],
            )
        )
    rub = document.get("rub_money", [])
    try:
        cash = broker_months._minor(rub[0][f"{side}_amount"]) if len(rub) == 1 else None
    except (MyBrokerError, DecimalException):
        cash = None
    values = [p.market_value_kopecks for p in positions]
    total = sum(values) if all(v is not None for v in values) and document else None
    complete = (
        bool(document)
        and not (document.get("endpoint_blockers") or document.get("endpoint_conflicts"))
        and all(p.quantity is not None and p.instrument_id > 0 for p in positions)
    )
    if not complete:
        reasons.add("statement_inventory_incomplete")
    return StatementEndpoint(
        account_id=account_id,
        valuation_date=day,
        positions=tuple(positions),
        positions_value_kopecks=total,
        cash_kopecks=cash,
        total_value_kopecks=total + cash if total is not None and cash is not None else None,
        inventory_state="complete" if complete else "unknown",
    )


def _section_authority(session, sources, account_id, month_id, reasons):
    diagnostics, material = [], []
    for source in sorted(sources, key=lambda s: s.id):
        # Retain even conflicting/malformed histories in freshness material. A
        # fork has no head; adding another fork must still invalidate Preview.
        rows = list(
            session.scalars(
                select(BrokerMonthApply)
                .where(
                    BrokerMonthApply.import_id == source.id,
                    BrokerMonthApply.account_id == account_id,
                    BrokerMonthApply.reporting_month_id == month_id,
                )
                .order_by(BrokerMonthApply.request_id)
                .execution_options(populate_existing=True)
            )
        )
        material.append(
            [
                [str(getattr(source, c.name)) for c in source.__table__.columns],
                [[str(getattr(r, c.name)) for c in r.__table__.columns] for r in rows],
            ]
        )
        try:
            heads, errors = broker_sections._heads(session, source.id, account_id, month_id)
            # Do not allow an unexpected partial/None proof to escape as a
            # missing grant or optimistic pattern, even if the chain resolved.
            if any(
                proof is None or proof != broker_sections.validated_proof(row)
                for row, proof in heads.values()
            ):
                raise MyBrokerError("statement_section_evidence_invalid")
            current = {
                section: broker_sections._valid_current(session, row, proof)
                for section, (row, proof) in heads.items()
            }
        except (KeyError, TypeError, ValueError, AttributeError, MyBrokerError):
            heads, current, errors = {}, {}, ["statement_section_evidence_invalid"]
        reasons.update(errors)
        for section in broker_sections.SHAPES:
            head = heads.get(section)
            effective = not errors and head is not None and current[section]
            diagnostics.append(
                StatementSectionAuthority(
                    import_id=source.id,
                    account_id=account_id,
                    reporting_month_id=month_id,
                    section=section,
                    state="blocked"
                    if errors or (head and not effective)
                    else ("effective" if effective else "missing"),
                    pattern=broker_sections.SHAPES[section]["pattern"] if effective else None,
                    head_request_id=head[0].request_id if head else None,
                    proof_material_signature=digest(head[1]) if head else None,
                )
            )
    return tuple(diagnostics), material


@coherent_read_operation
def read_statement_return(
    session, *, request_id, account_id, expected_fingerprint=None, original=None, filename=None
):
    receipt = session.get(BrokerMonthApply, request_id, populate_existing=True)
    if (
        receipt is None
        or receipt.account_id != account_id
        or journal.kind(receipt) != journal.SOURCE
    ):
        raise MyBrokerError("statement_source_not_found")
    source = session.get(MyBrokerImport, receipt.import_id, populate_existing=True)
    if source is None:
        raise MyBrokerError("statement_source_not_found")
    accepted = journal.payload(receipt)
    t0, t1 = source.covered_from - timedelta(days=1), source.covered_to
    reasons = set()
    document = {}
    current_signature = digest(
        [source.normalized_json, source.mappings_json, source.parser_version]
    )
    try:
        parsed = json.loads(source.normalized_json)
        if (
            current_signature != accepted["source_digest"]
            or source.parser_version != PARSER
            or parsed["document_sha256"] != source.document_sha256
            or (parsed["covered_from"], parsed["covered_to"])
            != (source.covered_from.isoformat(), source.covered_to.isoformat())
            or parsed["endpoint_basis"]
            != {"beginning_value": "previous_day_eod", "ending_value": "covered_to_eod"}
        ):
            reasons.add("statement_source_revision_changed")
        else:
            document = parsed
        if original is not None:
            reparsed = mybroker_import.parse_import_original(session, original, filename)
            if not _original_equal(reparsed, parsed):
                reasons.add("statement_original_mismatch")
    except (KeyError, TypeError, ValueError, MyBrokerError):
        reasons.add("statement_source_evidence_invalid")
    if original is not None and "statement_original_mismatch" in reasons:
        document = {}
    month = session.get(ReportingMonth, receipt.reporting_month_id)
    if month is None or (month.period_start, month.period_end, month.snapshot_date) != (
        source.covered_from,
        t1,
        t1,
    ):
        reasons.add("statement_endpoint_date_mismatch")
    # Exact original account aliases and full instrument inventory remain authoritative.
    try:
        bindings = effective_bindings(session, source)
        if any(
            not isinstance(b, dict) or not {"kind", "identity", "hermes_id"} <= b.keys()
            for b in bindings
        ):
            raise MyBrokerError("statement_account_evidence_invalid")
    except (KeyError, TypeError, ValueError, MyBrokerError):
        bindings = []
        reasons.add("statement_account_evidence_invalid")
    aliases = {
        b["identity"] for b in bindings if b["kind"] == "account" and b["hermes_id"] == account_id
    }
    member = (
        bool(document)
        and document["filename_account"] in aliases
        and all(
            r["source_account"] in aliases for r in document["positions"] + document["rub_money"]
        )
        and all(
            v[1] in {"stock", "bond"} and v[2] == "RUB" for v in accepted["instruments"].values()
        )
    )
    try:
        readback = broker_months.read_broker_month(session, request_id)
        reasons.update(readback["exceptions"])
    except (KeyError, TypeError, ValueError, MyBrokerError, DecimalException):
        reasons.add("statement_dependencies_invalid")
    if document:
        if "period_inferred_from_content" in document.get("warnings", []):
            reasons.add("source_period_inferred")
        reasons.update(document["endpoint_blockers"])
        reasons.update(document["endpoint_conflicts"])
        # Diagnostic safe wrappers cannot assess financial REPO/UFSR/custody impact.
        opaque = any(document["section_inventory"].get(s, 0) for s in ("4_Transfers", "5_UFSR"))
        opaque |= any(t["repo_observed"] or t["section"] == "pending" for t in document["trades"])
        if opaque:
            reasons.add("material_account_exposure_unassessed")
        relevant_sources = list(broker_months._intersecting_sources(session, document, account_id))
        others = [s.id for s in relevant_sources if s.id != source.id]
        if others:
            reasons.add("statement_overlapping_source")
    else:
        opaque, others, relevant_sources = True, [], []
    section_authority, section_material = _section_authority(
        session,
        {s.id: s for s in [source, *relevant_sources]}.values(),
        account_id,
        receipt.reporting_month_id,
        reasons,
    )
    coverages = list(
        session.scalars(
            select(CashBoundaryCoverage).where(
                CashBoundaryCoverage.account_id == account_id,
                CashBoundaryCoverage.covered_from == source.covered_from,
                CashBoundaryCoverage.covered_to == t1,
            )
        )
    )
    coverage = None
    diagnostic_material = None
    if len(coverages) == 1:
        try:
            coverage = source_cash_coverage.read_source_cash_coverage(session, coverages[0].id)
            reasons.update(coverage["blockers"])
        except (KeyError, TypeError, ValueError, MyBrokerError, DecimalException):
            reasons.add("account_crossing_coverage_invalid")
    elif (
        not coverages
        and member
        and not reasons.intersection(
            {
                "statement_source_revision_changed",
                "statement_source_evidence_invalid",
                "statement_original_mismatch",
                "statement_endpoint_date_mismatch",
                "statement_account_evidence_invalid",
                "statement_dependencies_invalid",
                "account_binding_changed",
                "accepted_mapping_changed",
                "source_authority_changed",
                "source_disposition_changed",
                "source_projection_changed",
                "instrument_metadata_changed",
                "canonical_trade_projection_changed",
                "canonical_trade_authority_unavailable",
                "broker_month_receipt_invalid",
            }
        )
    ):
        # Explain missing evidence only after validating the exact source scope.
        # Inventory is not acceptance: even an empty blocker set grants nothing.
        # Keep raw dependency material private, but bind it (not just codes) so
        # unchanged explanations cannot make an old Preview/export look current.
        try:
            diagnostic_material = {
                "contract": source_cash_coverage.CONTRACT,
                "inventory": source_cash_coverage.inventory(session, account_id, t0, t1),
            }
            reasons.update(diagnostic_material["inventory"]["blockers"])
        except (KeyError, TypeError, ValueError, MyBrokerError, DecimalException):
            reasons.add("account_crossing_coverage_invalid")
    effective = coverage is not None and coverage["effective_state"] == "accepted"
    crossings, flow_material = [], []
    for flow in session.scalars(
        select(HistoricalOwnerFlow)
        .where(
            HistoricalOwnerFlow.account_id == account_id,
            HistoricalOwnerFlow.event_date > t0,
            HistoricalOwnerFlow.event_date <= t1,
        )
        .order_by(HistoricalOwnerFlow.event_date, HistoricalOwnerFlow.id)
    ):
        try:
            view = read_historical_owner_flow(session, flow.id)
            flow_material.append(view)
            if view["effective_state"] != "accepted":
                reasons.add("statement_crossing_revision_invalid")
                reasons.update(view["blockers"])
                continue
            crossings.append(
                StatementCrossing(
                    event_id=flow.id,
                    account_id=flow.account_id,
                    event_date=flow.event_date,
                    currency=flow.currency,
                    signed_amount_kopecks=flow.boundary_amount_kopecks
                    * (1 if flow.direction == "contribution" else -1),
                    revision_id=view["revision_id"],
                    material_signature=view["material_signature"],
                )
            )
        except (KeyError, TypeError, ValueError, MyBrokerError):
            reasons.add("statement_crossing_revision_invalid")
    if effective and set(coverage["evidence"]["dependencies"]["effective_flow_ids"]) != {
        c.event_id for c in crossings
    }:
        reasons.add("statement_crossing_inventory_mismatch")
    opening = _endpoint(document, accepted["instruments"], account_id, t0, True, reasons)
    closing = _endpoint(document, accepted["instruments"], account_id, t1, False, reasons)
    material = digest(
        [
            source_intake.scoped_status(session, receipt.reporting_month_id, account_id),
            [str(getattr(source, c.name)) for c in source.__table__.columns],
            receipt.projection_json,
            receipt.confirmation_digest,
            bindings,
            opening.model_dump(mode="json"),
            closing.model_dump(mode="json"),
            coverage,
            flow_material,
            others,
            [s.model_dump(mode="json") for s in section_authority],
            section_material,
            diagnostic_material,
            sorted(reasons),
        ]
    )
    if expected_fingerprint is not None and expected_fingerprint != material:
        reasons.add("statement_preview_stale")
    return calculate_statement_return(
        BrokerStatementBasis(
            account_id=account_id,
            t0=t0,
            t1=t1,
            opening=opening,
            closing=closing,
            sources=(
                StatementSource(
                    import_id=source.id,
                    document_sha256=source.document_sha256,
                    parser_version=source.parser_version,
                    source_signature=current_signature,
                    request_id=request_id,
                    confirmation_digest=receipt.confirmation_digest,
                ),
            ),
            material_fingerprint=material,
            section_authority=section_authority,
            crossings=tuple(crossings),
            cash_coverage_state="complete" if effective else "unknown",
            cash_coverage_revision_id=coverage["revision_id"] if effective else None,
            membership_state="complete" if member else "unknown",
            exposure_state="unknown" if opaque else "assessed",
            bond_nkd_basis="unknown"
            if any(v[1] == "bond" for v in accepted["instruments"].values())
            else "not_applicable",
            reason_codes=tuple(sorted(reasons)),
        )
    )
