"""Exact-original investment evidence on the existing append-only proof host.

No original cache, cash ledger, financial writer or stored calculated return.
"""

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from hermes_finance.database import coherent_read_operation
from hermes_finance.persistence import (
    SourceMoneyClassification,
    SourceReturnProof,
    SourceReturnProofDependency,
)
from hermes_finance.services import source_intake
from hermes_finance.services.broker_statement_provisional import ProvisionalStaleError
from hermes_finance.services.source_monthly_returns import _selected_sources
from hermes_finance.services.source_return_proofs import FORMS, ProofError, _epoch
from hermes_finance.source_proof_file import file_incarnation
from hermes_finance.statement_import import mybroker
from hermes_finance.statement_import.investment_report import InvestmentPayout, InvestmentReport

VERSION = "source_return_investment_v1"


def _json(value):
    return json.dumps(value, sort_keys=True, default=lambda x: x.isoformat())


def _report(report, account):
    return {
        "sha256": report.sha256,
        "start": str(report.start),
        "end": str(report.end),
        "payouts": [
            {**asdict(p), "date": str(p.date)} for p in report.payouts if p.account == account
        ],
        "closing": {k: v for k, v in report.closing.items() if k == account},
        "reported_pnl": {k: v for k, v in report.reported_pnl.items() if k == account},
        "positions": [
            [a, i, q, v] for (a, i), (q, v) in sorted(report.positions.items()) if a == account
        ],
        "closed_isins": sorted([list(p) for p in report.closed_isins if p[0] == account]),
        "payout_accounts": sorted(report.payout_accounts & {account}),
        "issues": [list(p) for p in report.issues if p[0] == account],
        "instrument_issues": [list(p) for p in report.instrument_issues if p[0] == account],
    }


def _restore_report(data):
    # The host is append-only, the payload is issued only by the server, and its
    # canonical digest is checked before any operand is consumed.
    return InvestmentReport(
        data["sha256"],
        date.fromisoformat(data["start"]),
        date.fromisoformat(data["end"]),
        tuple(
            InvestmentPayout(**{**p, "date": date.fromisoformat(p["date"])})
            for p in data["payouts"]
        ),
        data["closing"],
        data["reported_pnl"],
        {(a, i): (q, v) for a, i, q, v in data["positions"]},
        frozenset(tuple(p) for p in data["closed_isins"]),
        frozenset(data["payout_accounts"]),
        tuple(tuple(p) for p in data["issues"]),
        tuple(tuple(p) for p in data.get("instrument_issues", ())),
    )


def _scope(plan):
    return plan["source_account"], plan["covered_from"], plan["covered_to"]


def _evidence_digest(plan):
    return mybroker.digest(
        {
            key: plan[key]
            for key in (
                "version",
                "source_account",
                "native_account",
                "covered_from",
                "covered_to",
                "from_zero",
                "intake_id",
                "source_sha256",
                "report",
                "native",
                "dependency",
            )
        }
    )


def _latest(session, scope):
    for row in session.scalars(
        select(SourceReturnProof)
        .where(
            SourceReturnProof.proof_version == VERSION,
            SourceReturnProof.source_account == scope[0],
        )
        .order_by(SourceReturnProof.id.desc())
    ):
        plan = json.loads(row.evidence_json)
        if _scope(plan) == scope:
            return row
    return None


def _implementation_digest():
    package = Path(__file__).resolve().parents[1]
    return mybroker.digest(
        [
            (p.relative_to(package).as_posix(), hashlib.sha256(p.read_bytes()).hexdigest())
            for p in sorted(package.rglob("*.py"))
        ]
    )


def _snapshot(session, account, start, end, *, reserved=False):
    selected, native = _selected_sources(session, account, reserved=reserved)
    if native is None or len(native) != 1:
        raise ProofError("investment_proof_scope_ambiguous")
    sources, money_ids = [], []
    for original, view, error in selected:
        if error:
            raise ProofError("investment_proof_source_unavailable")
        if original.covered_to < start or original.covered_from > end:
            continue
        decisions = [
            r.seq
            for r in source_intake._events(session, original.id)
            if r.operation == "manifest"
            or (r.operation == "decision" and not json.loads(r.payload_json).get("no_change"))
        ]
        sources.append(
            {
                "id": original.id,
                "sha256": original.document_sha256,
                "manifest": view["manifest_digest"],
                "generation": view["generation"],
                "document": mybroker.digest(view["document"]),
                "state": mybroker.digest(view["state"]),
                "decisions": decisions,
                "classifications": hashlib.sha256(
                    _json(view["money_classifications"]).encode()
                ).hexdigest(),
            }
        )
        money_ids.extend(
            session.scalars(
                select(SourceMoneyClassification.id).where(
                    SourceMoneyClassification.intake_id == original.id
                )
            )
        )
    connection = session.connection()
    physical = file_incarnation(Path(connection.engine.url.database))
    if not physical or connection.info.get("source_proof_incarnation") != physical:
        raise ProofError("investment_proof_database_incarnation_unavailable")
    ids = set(money_ids)
    clocks = []
    for clock in session.scalars(
        select(SourceReturnProofDependency).order_by(SourceReturnProofDependency.seq)
    ):
        bits = clock.token.split(":")
        # Legacy global clocks cannot be attributed, and therefore retire all
        # profiles. New scoped clocks follow both old and current member IDs.
        if len(bits) != 3 or (bits[0] == "m" and int(bits[1]) in ids):
            clocks.append([clock.seq, clock.token])
    # Conservative implementation fingerprint, including transitive classifier,
    # identity, Decimal/money and XIRR helpers. A hand-picked parent-module list
    # could silently keep a proof current after a helper-only semantic change.
    code = _implementation_digest()
    digest = mybroker.digest(
        {
            "physical": physical,
            "code": code,
            "sources": sources,
            "money_ids": sorted(ids),
            "clocks": clocks,
            "native": sorted(native),
        }
    )
    return digest, selected, next(iter(native))


def _bound_view(selected, sha):
    matches = [(r, v) for r, v, error in selected if not error and r.document_sha256 == sha]
    if len(matches) != 1:
        raise ProofError("investment_proof_save_exact_xml_first")
    return matches[0]


def _captured_money(document, view):
    from hermes_finance.services.source_report_preview import _money

    rows = view["money_classifications"]
    if len(rows) != len(document["money"]):
        raise ProofError("investment_proof_classification_conflict")
    money = _money(document, None, texts=[(r["operation"], r["narrative"], None) for r in rows])
    for value, captured in zip(money, rows):
        if (
            (
                captured["origin"] == "user_choice"
                and value["classification"] != captured["classification"]
            )
            or value["minor"] != captured["amount_kopecks"]
            or str(value["day"]) != str(captured["date"])
            or value["currency"] != captured["currency"]
        ):
            raise ProofError("investment_proof_classification_conflict")
    return money


def prepare(session, documents, payloads, filenames, report, intervals, comparison, from_zero):
    """Offer an explicit source-proof Save only after immutable XML Save exists."""
    from hermes_finance.services.source_report_preview import _native, _unresolved_movements

    plans, reasons, replacements, already = [], [], [], []
    if len({d["filename_account"] for d in documents}) != len(documents):
        reasons.append("investment_proof_one_original_per_account_required")
    if any(c.get("kind") or c.get("conflicting_native_trades") for c in comparison):
        reasons.append("investment_proof_saved_source_conflict")
    scopes = set()
    for document, interval in zip(documents, intervals):
        account = document["filename_account"]
        scope = account, document["covered_from"], document["covered_to"]
        if scope in scopes:
            reasons.append("investment_proof_duplicate_scope")
        scopes.add(scope)
        try:
            dependency, selected, native = _snapshot(
                session, account, date.fromisoformat(scope[1]), date.fromisoformat(scope[2])
            )
            original, view = _bound_view(selected, document["document_sha256"])
            from hermes_finance.services.broker_statement_provisional import _matching_source

            if original.filename_digest != mybroker.digest(filenames[document["document_sha256"]]):
                raise ProofError("investment_proof_exact_document_changed")
            _matching_source(
                view["document"],
                payloads[document["document_sha256"]],
                filenames[document["document_sha256"]],
            )
            captured = _captured_money(document, view)
            trades, names, _, cancellations = _native(
                document, payloads[document["document_sha256"]]
            )
            del trades
            plan = {
                "version": VERSION,
                "source_account": account,
                "native_account": native,
                "covered_from": scope[1],
                "covered_to": scope[2],
                "from_zero": from_zero,
                "intake_id": original.id,
                "source_sha256": document["document_sha256"],
                "report": _report(report, account),
                "native": {
                    "names": {k: sorted(v) for k, v in names.items()},
                    "cancellations": [[a, i, str(d), str(q)] for a, i, d, q in cancellations],
                    "unresolved": _unresolved_movements(
                        payloads[document["document_sha256"]], native, cancellations
                    ),
                },
                "dependency": dependency,
            }
            # Validate the upload interpretation against the retained current
            # Money observations; these observations remain the sole cash.
            if len(captured) != len(document["money"]):
                raise ProofError("investment_proof_money_mismatch")
            previous = _latest(session, scope)
            plan["predecessor_id"] = previous.id if previous else None
            content = mybroker.digest({k: v for k, v in plan.items() if k != "predecessor_id"})
            if previous:
                old = json.loads(previous.evidence_json)
                old_content = mybroker.digest(
                    {
                        k: v
                        for k, v in old.items()
                        if k not in {"predecessor_id", "batch_id", "batch_accounts", "batch_digest"}
                    }
                )
                if old_content == content:
                    already.append(previous.id)
                else:
                    replacements.append(
                        {
                            "source_account": account,
                            "proof_id": previous.id,
                            "covered_from": scope[1],
                            "covered_to": scope[2],
                        }
                    )
            plans.append(plan)
        except (ProofError, OSError, ProvisionalStaleError) as error:
            reasons.append(str(error))
    if reasons:
        return {
            "available": False,
            "reason_codes": sorted(set(reasons)),
            "replacements": replacements,
        }
    if len(already) == len(plans):
        return {
            "available": False,
            "reason_codes": ["investment_proof_already_saved"],
            "proof_ids": already,
            "replacements": [],
        }
    batch = {"plans": plans}
    return {
        "available": True,
        "reason_codes": [],
        "replacements": replacements,
        "preview_digest": mybroker.digest(batch),
        "form_token": FORMS.issue(_epoch(session), batch),
        "financial_authority": "none",
        "proof_rows": len(plans),
    }


def _derive(session, row, plan, *, analyses=None):
    from hermes_finance.services.source_report_preview import _interval, _payout_links

    dependency, selected, _ = _snapshot(
        session,
        plan["source_account"],
        date.fromisoformat(plan["covered_from"]),
        date.fromisoformat(plan["covered_to"]),
    )
    if (
        _evidence_digest(plan) != row.dependency_digest
        or plan["dependency"] != dependency
        or row.native_account != plan["native_account"]
    ):
        raise ProofError("investment_proof_dependencies_changed")
    original, view = _bound_view(selected, plan["source_sha256"])
    if original.id != plan["intake_id"]:
        raise ProofError("investment_proof_binding_changed")
    document = view["document"]
    money = _captured_money(document, view)
    report = _restore_report(plan["report"])
    links, issues = _payout_links([document], {plan["source_sha256"]: money}, report)
    return _interval(
        document,
        None,
        report,
        money,
        links,
        issues,
        plan["from_zero"],
        native_evidence=plan["native"],
        analyses=analyses,
    )


@coherent_read_operation
def read_reports(session, *, source_account=None, analyses=None):
    rows = session.scalars(
        select(SourceReturnProof)
        .where(SourceReturnProof.proof_version == VERSION)
        .order_by(SourceReturnProof.id.desc())
    )
    seen, result = set(), []
    for row in rows:
        if source_account is not None and source_account not in {
            row.source_account,
            row.native_account,
        }:
            continue
        plan = json.loads(row.evidence_json)
        scope = _scope(plan)
        if scope in seen:
            continue
        seen.add(scope)
        item = {
            "proof_id": row.id,
            "source_account": scope[0],
            "covered_from": scope[1],
            "covered_to": scope[2],
            "history_from_zero": plan["from_zero"],
            "pdf_sha256": plan["report"]["sha256"],
            "pdf_period": {
                "covered_from": plan["report"]["start"],
                "covered_to": plan["report"]["end"],
            },
            "pdf_payout_rows": len(plan["report"]["payouts"]),
            "status": "current",
            "reason_codes": [],
            "interval": None,
            "financial_authority": "none",
        }
        try:
            derived = {} if analyses is not None else None
            item["interval"] = _derive(session, row, plan, analyses=derived)
            if analyses is not None:
                analyses[row.id] = derived
        except (ProofError, ValueError, TypeError, KeyError, ArithmeticError, OSError) as error:
            item.update(
                status="stale",
                reason_codes=[
                    str(error) if isinstance(error, ProofError) else "investment_proof_invalid"
                ],
            )
        result.append(item)
    return result


@coherent_read_operation
def request_status(session, request_id):
    rows = list(
        session.scalars(
            select(SourceReturnProof)
            .where(
                SourceReturnProof.proof_version == VERSION,
                SourceReturnProof.request_id.startswith(request_id + ":", autoescape=True),
            )
            .order_by(SourceReturnProof.id)
        )
    )
    if not rows:
        raise ProofError("investment_proof_request_not_found")
    plans = [json.loads(r.evidence_json) for r in rows]
    if (
        any(
            p["batch_id"] != request_id
            or p["batch_accounts"] != plans[0]["batch_accounts"]
            or p["batch_digest"] != plans[0]["batch_digest"]
            for p in plans
        )
        or sorted(r.source_account for r in rows) != plans[0]["batch_accounts"]
    ):
        raise ProofError("investment_proof_batch_incomplete")
    current = {p["proof_id"]: p for p in read_reports(session)}
    return {
        "request_id": request_id,
        "preview_digest": plans[0]["batch_digest"],
        "proof_ids": [r.id for r in rows],
        "current": all(current.get(r.id, {}).get("status") == "current" for r in rows),
        "financial_authority": "none",
    }


def confirm(session, *, form_token, preview_digest, request_id, replace_existing=False):
    source_intake._reserve(session)
    try:
        session.expire_all()
        existing = session.scalar(
            select(SourceReturnProof).where(
                SourceReturnProof.request_id.startswith(request_id + ":", autoescape=True)
            )
        )
        fingerprint = mybroker.digest([form_token, preview_digest, replace_existing])
        if existing:
            if existing.request_fingerprint != fingerprint:
                raise ProofError("investment_proof_request_conflict")
            session.rollback()
            return {**request_status(session, request_id), "replay": True}
        batch = FORMS.consume(form_token, _epoch(session), preview_digest)
        if set(batch) != {"plans"}:
            raise ProofError("investment_proof_form_invalid")
        plans = batch["plans"]
        if not plans or len(plans) > 8 or len({_scope(p) for p in plans}) != len(plans):
            raise ProofError("investment_proof_batch_invalid")
        for plan in plans:
            if plan["version"] != VERSION:
                raise ProofError("investment_proof_version_invalid")
            dependency, selected, native = _snapshot(
                session,
                plan["source_account"],
                date.fromisoformat(plan["covered_from"]),
                date.fromisoformat(plan["covered_to"]),
                reserved=True,
            )
            previous = _latest(session, _scope(plan))
            if (
                dependency != plan["dependency"]
                or native != plan["native_account"]
                or (previous.id if previous else None) != plan["predecessor_id"]
            ):
                raise ProofError("investment_proof_dependencies_changed")
            if previous and not replace_existing:
                raise ProofError("investment_proof_replacement_not_confirmed")
            original, view = _bound_view(selected, plan["source_sha256"])
            if original.id != plan["intake_id"]:
                raise ProofError("investment_proof_binding_changed")
            _captured_money(view["document"], view)
            evidence = {
                **plan,
                "batch_id": request_id,
                "batch_accounts": sorted(p["source_account"] for p in plans),
                "batch_digest": preview_digest,
            }
            session.add(
                SourceReturnProof(
                    source_account=plan["source_account"],
                    native_account=native,
                    request_id=request_id + ":" + mybroker.digest(_scope(plan))[:24],
                    request_fingerprint=fingerprint,
                    proof_version=VERSION,
                    dependency_digest=_evidence_digest(plan),
                    evidence_json=_json(evidence),
                    confirmed_at=datetime.now(UTC),
                )
            )
        session.commit()
        return {**request_status(session, request_id), "replay": False}
    except BaseException:
        session.rollback()
        raise


def instrument_result(
    session, source_account, selected, requested_isin, opening_date, closing_date
):
    """Ordinary instrument/Returns readers consume the same current proof.

    Only exact intervals are eligible; historical endpoints never fabricate
    interior month valuations. Latest stale scope has no numeric fallback.
    """
    from dataclasses import replace

    from hermes_finance.domain.instrument_return import (
        AccountReconciliation,
        Coverage,
        Endpoint,
        InstrumentAnalysis,
        Metric,
        SourceReference,
        calculate_economics,
    )
    from hermes_finance.services.source_instrument_returns import (
        InstrumentIncome,
        InstrumentReturnGap,
        SourceInstrumentReturn,
        SourceInstrumentReturns,
        _all_time,
        _identities,
    )

    analyses = {}
    reports = read_reports(session, source_account=source_account, analyses=analyses)
    if opening_date is not None:
        matches = [
            p
            for p in reports
            if date.fromisoformat(p["covered_from"]) - timedelta(days=1) == opening_date
            and date.fromisoformat(p["covered_to"]) == closing_date
        ]
    else:
        matches = [p for p in reports if p["history_from_zero"]]
        matches.sort(key=lambda p: (p["covered_to"], p["proof_id"]), reverse=True)
    if not matches:
        return None
    proof = matches[0]
    first = date.fromisoformat(proof["covered_from"]) - timedelta(days=1)
    last = date.fromisoformat(proof["covered_to"])
    views = [v for _, v, e in selected if not e]
    metadata = _identities(views)
    chosen = analyses.get(proof["proof_id"], {})
    references = tuple(
        SourceReference(
            r.id,
            r.document_sha256,
            v["document"]["parser"],
            v["head_seq"],
            v["manifest_digest"],
            (hashlib.sha256(_json(v["money_classifications"]).encode()).hexdigest(),),
            str(proof["proof_id"]),
        )
        for r, v, e in selected
        if not e and r.covered_from <= last and r.covered_to > first
    )
    instruments, income, gaps = [], [], []
    keys = sorted(chosen) if proof["status"] == "current" else sorted(metadata)
    for isin in keys:
        if requested_isin is not None and isin != requested_isin:
            continue
        analysis = chosen.get(isin)
        if analysis is None:
            coverage = {
                k: Coverage(False, ("investment_proof_stale",))
                for k in ("events", "quantity", "endpoints", "payouts", "costs", "valuation")
            }
            opening, closing = (
                Endpoint(first, None, None, None, None, "reported_unknown"),
                Endpoint(last, None, None, None, None, "reported_unknown"),
            )
            components, pnl, known, dietz, estimate = calculate_economics(
                opening, closing, (), coverage
            )
            analysis = InstrumentAnalysis(
                opening_date=first,
                closing_date=last,
                history_start=first + timedelta(days=1),
                history_end=last,
                history_complete_since_acquisition=False,
                events=(),
                opening=opening,
                closing=closing,
                components=components,
                pnl=pnl,
                known_subtotal=known,
                modified_dietz=dietz,
                coverage=coverage,
                source_references=(),
                reason_codes=("investment_proof_stale",),
                assumptions=(),
                statement_estimate=estimate,
            )
        analysis = replace(analysis, source_references=references)
        for event in analysis.events:
            if event.kind in {"COUPON", "DIVIDEND"}:
                income.append(
                    InstrumentIncome(
                        event.event_date,
                        sum(leg.account_cash_kopecks for leg in event.cash_legs),
                        event.kind.lower(),
                        "assumed",
                        event.source_references,
                        isin,
                    )
                )
        meta = metadata.get(isin, {"names": set(), "types": set()})
        name = next(iter(meta["names"])) if len(meta["names"]) == 1 else None
        kind = next(iter(meta["types"])) if len(meta["types"]) == 1 else None
        totals = replace(
            _all_time(()),
            total_kopecks=analysis.pnl.value,
            buys_cost_kopecks=analysis.components["buys"].value,
            sells_proceeds_kopecks=analysis.components["sells"].value,
            coupons_kopecks=analysis.components["coupons"].value,
            dividends_kopecks=analysis.components["dividends"].value,
            flags=analysis.reason_codes + ("exact_source_interval_use_analysis_rate",),
            approximate=True,
            partial=True,
            income_complete=analysis.coverage["payouts"].complete,
        )
        instruments.append(SourceInstrumentReturn(isin, name, kind, (), totals, analysis))
        gaps.extend(
            InstrumentReturnGap(code, month=None, isin=isin) for code in analysis.reason_codes
        )
    reconciliation = None
    interval = proof["interval"]
    if interval is not None and requested_isin is None:
        account_value = None if interval["pnl"]["value"] is None else int(interval["pnl"]["value"])
        values = [i.analysis.pnl.value for i in instruments]
        instrument_total = sum(values) if values and all(v is not None for v in values) else None
        account_only = sum(int(r["amount_kopecks"]) for r in interval["account_only"])
        residual = (
            None
            if account_value is None or instrument_total is None
            else account_value - instrument_total - account_only
        )
        reasons = tuple(interval["reason_codes"])
        reconciliation = AccountReconciliation(
            first,
            last,
            Metric(account_value, "partial", reasons),
            Metric(instrument_total, "partial", reasons),
            Metric(account_only, "partial", reasons),
            Metric(residual, "partial", reasons),
            residual == 0,
            reasons,
        )
    native = next(
        (v["document"]["money"][0]["source_account"] for v in views if v["document"]["money"]), None
    )
    return SourceInstrumentReturns(
        source_account,
        tuple(instruments),
        tuple(income),
        tuple(gaps),
        native_source_account=native,
        reconciliation=reconciliation,
    )
