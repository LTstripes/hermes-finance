"""Dated read projection over frozen intakes and current offline payout links.

No writers, provider calls, quote substitution, or persisted calculation cache.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, localcontext

from hermes_finance.domain.instrument_return import (
    AccountReconciliation,
    CashLeg,
    Coverage,
    Endpoint,
    InstrumentAnalysis,
    InstrumentEvent,
    Metric,
    SourceReference,
    calculate_economics,
)
from hermes_finance.domain.money_security import parse_money_security
from hermes_finance.services import broker_trade_money
from hermes_finance.services.money_instrument_links import MoneyInstrumentResolver
from hermes_finance.services.source_money_classifications import (
    _is_nkd,
    _linked_purchase_nkd,
    source_reference,
)
from hermes_finance.services.source_monthly_returns import _money
from hermes_finance.statement_import.money import normalize_currency
from hermes_finance.statement_import.mybroker import PROVIDER, MyBrokerError, digest


def _decimal(value):
    try:
        result = Decimal(value)
        return result if result.is_finite() else None
    except (ValueError, TypeError, ArithmeticError):
        return None


def _date(value):
    return date.fromisoformat(value) if value else None


def _fingerprint(value):
    return digest(json.dumps(value, sort_keys=True, default=str))


def payout_attribution(saved, resolver, identities):
    """Validate a persisted decision; never replace it with a newly possible link."""
    from hermes_finance.services.source_instrument_returns import _attribute

    status = saved.get("instrument_link_status")
    if status == "linked":
        security = parse_money_security(saved["narrative"])
        if (
            security is None
            or security.kind != saved["classification"]
            or (
                security.reg_number != saved.get("security_reg_number")
                or security.issuer_name != saved.get("security_issuer")
            )
        ):
            return None, "persisted_link", ("payout_link_stale",)
        target, current_status = resolver.resolve(security)
        instrument = resolver.instruments.get(target)
        expected_kind = "bond" if security.kind == "coupon" else "stock"
        if (
            current_status != "linked"
            or target != saved.get("instrument_id")
            or instrument is None
            or not instrument.isin
            or instrument.instrument_type != expected_kind
        ):
            return None, "persisted_link", ("payout_link_stale",)
        return instrument.isin, "persisted_link", ()
    if status not in (None, "not_parsed", "not_applicable"):
        return None, "persisted_link", ("payout_link_" + status,)
    # A parsed security with no saved link must not be promoted by today's catalog.
    if parse_money_security(saved["narrative"]) is not None:
        return None, "persisted_link", ("payout_link_missing",)
    isin = _attribute(saved["operation"] + " " + saved["narrative"], identities)
    return isin, "legacy_text", () if isin else ("unattributed_income",)


def read_events(session, views, identities, native_account, gaps):
    from hermes_finance.services.source_instrument_returns import (
        InstrumentReturnGap,
        _attribute,
        _bond_total_basis,
        _face_signature,
        _minor,
        _native_total_basis,
        _trade_cash_total,
        _trade_core,
    )

    resolver = MoneyInstrumentResolver(session)
    dependencies = _fingerprint(
        {
            "catalog": sorted(
                (i.id, i.isin, i.instrument_type, i.name) for i in resolver.instruments.values()
            ),
            "reg_isins": resolver.reg_isins,
            "aliases": {k: sorted(v) for k, v in resolver.aliases.items()},
            "targets": {k: sorted(v) for k, v in resolver.mapping_targets.items()},
            "conflicts": sorted(resolver.conflicts),
        }
    )
    sources = tuple(
        SourceReference(
            v["id"],
            v["document_sha256"],
            v["document"]["parser"],
            v["head_seq"],
            v["manifest_digest"],
            tuple(_fingerprint(row) for row in v["money_classifications"]),
            dependencies,
        )
        for v in views
    )
    occurrences = defaultdict(list)
    invalid_events = []
    for view in views:
        saved = {r["source_reference"]: r for r in view["money_classifications"]}
        raw = {source_reference(view["id"], r): r for r in view["document"].get("money", [])}
        local = []
        validated_refs = set()
        try:
            for key, flow in _money(session, view, None, local):
                ref = flow.source_references[0]
                validated_refs.add(ref)
                row = saved[ref]
                if flow.classification in {"coupon", "dividend"}:
                    isin, basis, reasons = payout_attribution(row, resolver, identities)
                    if isin:
                        metadata = identities[isin]
                        metadata["identifiers"].add(isin)
                        target = resolver.instruments.get(row.get("instrument_id"))
                        if target:
                            metadata["types"].add(target.instrument_type)
                            metadata["names"].add(target.name)
                else:
                    isin = _attribute(row["operation"] + " " + row["narrative"], identities)
                    basis, reasons = "legacy_text", ()
                occurrences[key].append((view, flow, row, raw[ref], isin, basis, reasons))
        except (MyBrokerError, ValueError, TypeError, KeyError, ArithmeticError):
            gaps.append(
                InstrumentReturnGap(
                    "source_reader_unavailable",
                    view["id"],
                    _date(view["covered_from"]).replace(day=1),
                )
            )
        gaps.extend(InstrumentReturnGap(**vars(g)) for g in local)
        for ref, raw_row in raw.items():
            if ref in validated_refs:
                continue
            saved_row = saved.get(ref, {})
            invalid_events.append(
                InstrumentEvent(
                    event_key=ref,
                    provider=PROVIDER,
                    native_source_account=native_account,
                    isin=None,
                    kind="UNRESOLVED",
                    source_references=(ref,),
                    event_date=_date(raw_row.get("date")),
                    counted=False,
                    current=False,
                    classification=saved_row.get("classification"),
                    classification_origin=saved_row.get("origin"),
                    classification_status=saved_row.get("status"),
                    persisted_link_status=saved_row.get("instrument_link_status"),
                    reason_codes=tuple(
                        sorted(
                            {g.code for g in local if g.source_reference == ref}
                            or {"invalid_money_row"}
                        )
                    ),
                )
            )

    money = []
    for key, observations in occurrences.items():
        confirmed = [o for o in observations if o[1].status == "confirmed"]
        chosen = confirmed or observations
        view, flow, row, raw, isin, basis, attribution_reasons = chosen[0]
        reasons = set(attribution_reasons)
        if (
            len({(o[1].classification, o[4], o[2].get("instrument_link_status")) for o in chosen})
            != 1
        ):
            reasons.add("overlap_flow_choice_conflict")
            isin = None
        if any(o[6] for o in observations):
            reasons.update(r for o in observations for r in o[6])
            isin = None
        present = {o[0]["id"] for o in observations}
        if any(
            v["covered_from"] <= flow.event_date.isoformat() <= v["covered_to"]
            and v["id"] not in present
            for v in views
        ):
            reasons.add("overlap_money_occurrence_missing")
        refs = tuple(sorted(o[1].source_references[0] for o in observations))
        money.append(
            dict(
                key=f"money:{key[0]}:{key[1]}",
                flow=flow,
                saved=row,
                raw=raw,
                isin=isin,
                basis=basis,
                reasons=reasons,
                refs=refs,
                owned=False,
            )
        )

    trades = defaultdict(list)
    for view in views:
        for trade in view["document"].get("trades", []):
            key = (
                trade.get("identity")
                or f"unresolved:{view['id']}:{trade['section']}:{trade['ordinal']}"
            )
            trades[key].append((view, trade))
    primary_owners = defaultdict(set)
    for key, observations in trades.items():
        for _, trade in observations:
            if trade.get("ids"):
                primary_owners[trade["ids"][0]].add(key)
    for m in money:
        m["trade_keys"] = primary_owners.get(m["raw"].get("primary_id"), set())
        text = m["saved"]["operation"] + " " + m["saved"]["narrative"]
        if not m["trade_keys"] and _is_nkd(text):
            with localcontext() as context:
                context.prec = 200
                m["trade_keys"] = {
                    key
                    for key, observations in trades.items()
                    if any(
                        _linked_purchase_nkd(
                            m["raw"], m["saved"]["operation"], m["saved"]["narrative"], [t]
                        )
                        for _, t in observations
                    )
                }
    events = invalid_events
    for key, observations in trades.items():
        settled = [(v, t) for v, t in observations if t["state"] == "settled"]
        selected = settled or observations
        view, trade = selected[0]
        core = trade["core"]
        isin = core["isin"]
        kinds = identities[isin]["types"]
        kind = next(iter(kinds)) if len(kinds) == 1 else None
        refs = tuple(f"trade:{v['id']}:{t['section']}:{t['ordinal']}" for v, t in observations)
        reasons, assumptions = set(), set()
        cash_date, depo_date = (
            _date(trade.get("settlement_date")),
            _date(trade.get("depo_settlement_date")),
        )
        execution = _date(core["trade_time"][:10])
        qty = _decimal(core.get("quantity"))
        amount, nkd, fee = (
            _minor(core.get("trade_amount")),
            _minor(trade.get("accrued_interest")),
            _minor(trade.get("bank_commission")),
        )
        if kind == "stock" and trade.get("accrued_interest") is None:
            nkd = 0
        if not trade.get("identity") or len(trade.get("ids", [])) != 2:
            reasons.add("trade_identity_unresolved")
        if not settled or cash_date is None:
            reasons.add("trade_missing_settlement")
        if depo_date is None:
            reasons.add("depository_settlement_missing")
        signatures = {
            _fingerprint(
                (
                    _trade_core(t["core"]),
                    t.get("settlement_date"),
                    t.get("depo_settlement_date"),
                    t.get("bank_commission"),
                    t.get("accrued_interest"),
                    _face_signature(t) if kind == "bond" else None,
                    t.get("repo_observed"),
                )
            )
            for _, t in selected
        }
        if (
            len(signatures) != 1
            or len({digest(_trade_core(t["core"])) for _, t in observations}) != 1
        ):
            reasons.add("overlapping_trade_conflict")
        if normalize_currency(core.get("currency")) != "RUB":
            reasons.add("trade_currency_unsupported")
        if trade.get("repo_observed"):
            reasons.add("repo_trade_unsupported")
        if qty is None or qty == 0 or any(x is None or x < 0 for x in (amount, nkd, fee)):
            reasons.add("trade_components_missing")
        flags = set()
        basis = (
            "excludes_paid_nkd"
            if kind == "stock"
            else _bond_total_basis(
                session, trade, flags, documents=[v["document"] for v, _ in observations]
            )
            if kind == "bond"
            else _native_total_basis(session, trade)
        )
        assumptions.update(flags & {"trade_face_value_missing"})
        reasons.update(flags - assumptions)
        if basis is None:
            reasons.add("trade_nkd_basis_unknown")
        total = (
            None
            if None in (amount, nkd, fee, qty)
            else _trade_cash_total(amount, nkd, fee, qty, basis)
        )
        present = {v["id"] for v, _ in observations}
        if cash_date and any(
            v["id"] not in present
            and v["covered_from"] <= execution.isoformat()
            and cash_date.isoformat() <= v["covered_to"]
            for v in views
        ):
            reasons.add("overlap_trade_occurrence_missing")
        linked = [m for m in money if key in m["trade_keys"]]
        legs = []
        sign = -1 if qty is not None and qty > 0 else 1
        groups = defaultdict(list)
        for m in linked:
            m["owned"] = True
            text = (m["saved"]["operation"] + " " + m["saved"]["narrative"]).casefold()
            role = (
                "commission"
                if m["raw"]["kind"] == "commission"
                else ("nkd" if _is_nkd(text) else "principal")
            )
            groups[role].append(m)
            reasons.update(m["reasons"])
            if len(m["trade_keys"]) != 1:
                reasons.add("money_ownership_ambiguous")
            if m["flow"].classification not in {"trade_settlement", "fee"}:
                reasons.add("trade_money_classification_conflict")
        if total is not None and cash_date:
            # Money's native role/date replaces its corresponding cash component.
            # An included NKD is split only if a separately evidenced NKD row exists.
            expected = {
                "principal": sign * (amount + (nkd if basis == "excludes_paid_nkd" else 0)),
                "commission": -fee,
            }
            if groups.get("nkd"):
                expected["principal"] -= sign * nkd
                expected["nkd"] = sign * nkd
            for role, value in expected.items():
                rows = groups.get(role, [])
                if rows:
                    if sum(m["flow"].amount_kopecks for m in rows) != value:
                        reasons.add("trade_money_cash_conflict")
                    for m in rows:
                        legs.append(
                            CashLeg(
                                role,
                                m["flow"].event_date,
                                m["flow"].amount_kopecks,
                                -m["flow"].amount_kopecks,
                                m["refs"],
                                m["key"],
                            )
                        )
                else:
                    legs.append(
                        CashLeg(role, cash_date, value, -value, refs, f"trade:{key}:{role}")
                    )
        events.append(
            InstrumentEvent(
                event_key=f"trade:{key}",
                provider=PROVIDER,
                native_source_account=native_account,
                isin=isin,
                effective_isin=isin,
                kind="BUY" if qty is not None and qty > 0 else "SELL",
                source_references=refs,
                event_date=cash_date or execution,
                native_identity=trade.get("identity"),
                native_ids=tuple(trade.get("ids", [])),
                trade_time=core.get("trade_time"),
                cash_settlement_date=cash_date,
                depository_settlement_date=depo_date,
                quantity_delta=qty,
                unit_price=_decimal(core.get("price")),
                price_unit="PERCENT_OF_FACE"
                if kind == "bond"
                else "RUB_PER_UNIT"
                if kind == "stock"
                else "UNKNOWN",
                face_value=_decimal(trade.get("face_value")),
                face_value_date=execution if trade.get("face_value") else None,
                attribution_basis="matched_money" if linked else "native_trade_settlement",
                native_trade_amount_kopecks=amount,
                native_total_basis=basis,
                proof_dependency=_fingerprint(proof)
                if (proof := broker_trade_money.effective_proof(session, trade.get("identity")))
                else None,
                accrued_interest_kopecks=nkd,
                commission_kopecks=fee,
                cash_legs=tuple(legs),
                counted=not reasons,
                reason_codes=tuple(sorted(reasons)),
                assumptions=tuple(sorted(assumptions)),
            )
        )

    for m in money:
        if m["owned"]:
            continue
        flow, saved, isin = m["flow"], m["saved"], m["isin"]
        classification = flow.classification
        text = (saved["operation"] + " " + saved["narrative"]).casefold()
        reasons = m["reasons"]
        payout_words = any(w in text for w in ("дивиденд", "dividend", "купон", "coupon"))
        if (
            classification not in {"coupon", "dividend", "trade_settlement"}
            and flow.amount_kopecks > 0
            and payout_words
        ):
            reasons.add("payout_classification_conflict")
        if any(
            w in text for w in ("амортизац", "погашение номинал", "redemption", "погашение облигац")
        ):
            reasons.add("redemption_amortization_unsupported")
        kind = {"coupon": "COUPON", "dividend": "DIVIDEND", "fee": "FEE", "tax": "TAX"}.get(
            classification, "UNRESOLVED"
        )
        account_only = (
            classification in {"fee", "tax"}
            and isin is None
            and any(w in text for w in ("ведение счета", "ведение счёта", "account maintenance"))
        )
        if (
            classification in {"external_deposit", "external_withdrawal", "internal_transfer"}
            and not reasons
        ):
            continue
        if classification == "trade_settlement":
            reasons.add("unmatched_trade_money")
        if classification == "unknown":
            reasons.add("unrecognized_money")
        if (
            classification in {"coupon", "dividend", "fee", "tax"}
            and isin is None
            and not account_only
        ):
            reasons.add(
                "unattributed_income"
                if kind in {"COUPON", "DIVIDEND"}
                else "unallocated_instrument_cost"
            )
        if kind in {"FEE", "TAX"} and flow.amount_kopecks > 0:
            reasons.add("cost_sign_conflict")
        assumptions = (
            ("income_assumed",)
            if flow.status == "assumed" and kind in {"COUPON", "DIVIDEND"}
            else ()
        )
        tax = None
        if kind == "DIVIDEND" and parse_money_security(saved["narrative"]) is not None:
            withholding = re.search(
                r"Удержан налог ([0-9]+(?:[.,][0-9]{1,2})?) руб", saved["narrative"], re.IGNORECASE
            )
            if withholding:
                tax = _minor(withholding[1].replace(",", "."))
        events.append(
            InstrumentEvent(
                event_key=m["key"],
                provider=PROVIDER,
                native_source_account=native_account,
                isin=isin,
                effective_isin=isin if not reasons else None,
                kind=kind,
                source_references=m["refs"],
                event_date=flow.event_date,
                cash_settlement_date=flow.event_date,
                net_payout_kopecks=flow.amount_kopecks if kind in {"COUPON", "DIVIDEND"} else None,
                withheld_tax_kopecks=tax,
                gross_payout_kopecks=None if tax is None else flow.amount_kopecks + tax,
                classification=classification,
                classification_origin=saved["origin"],
                classification_status=flow.status,
                persisted_link_status=saved.get("instrument_link_status"),
                attribution_basis="account_only" if account_only else m["basis"],
                current=not reasons,
                counted=not reasons and not account_only,
                reason_codes=tuple(sorted(reasons)),
                assumptions=assumptions,
                cash_legs=(
                    CashLeg(
                        classification,
                        flow.event_date,
                        flow.amount_kopecks,
                        -flow.amount_kopecks,
                        m["refs"],
                        m["key"],
                    ),
                ),
            )
        )
    return tuple(sorted(events, key=lambda e: (e.event_date or date.min, e.event_key))), sources


def endpoint(views, isin, day, kind):
    from hermes_finance.services.source_instrument_returns import _minor, _quantity

    quantities, values, refs, reasons = set(), set(), [], set()
    for view in views:
        if "period_inferred_from_content" in view["document"].get("warnings", []):
            continue
        for closing in (False, True):
            boundary = (
                _date(view["covered_to"])
                if closing
                else _date(view["covered_from"]) - timedelta(days=1)
            )
            if boundary != day:
                continue
            rows = [r for r in view["document"].get("positions", []) if r["isin"] == isin]
            if not rows:
                continue
            if len(rows) != 1:
                reasons.add("duplicate_position")
                continue
            row = rows[0]
            q = _quantity(row.get("actual_quantity" if closing else "beginning_actual_quantity"))
            v = _minor(row.get("ending_value" if closing else "beginning_value"))
            refs.append(
                f"position:{view['id']}:{row['ordinal']}:{'closing' if closing else 'opening'}"
            )
            quantities.add(q)
            values.add(v)
            if q == 0 and v not in (0, None):
                reasons.add("quantity_value_conflict")
            if view["document"].get("endpoint_basis") != {
                "beginning_value": "previous_day_eod",
                "ending_value": "covered_to_eod",
            }:
                reasons.add("endpoint_basis_unsupported")
    q = next(iter(quantities)) if len(quantities) == 1 else None
    v = next(iter(values)) if len(values) == 1 else None
    if len(quantities) > 1 or len(values) > 1:
        reasons.add("overlapping_endpoint_conflict")
    if q is None or v is None or v < 0:
        reasons.add("missing_endpoint")
    if reasons:
        v = None
    economic = v
    if kind == "bond":
        reasons.add("bond_valuation_basis_unknown")
        economic = None
    elif kind != "stock":
        reasons.add("instrument_type_unknown")
        economic = None
    return Endpoint(
        day,
        q,
        v,
        economic,
        0 if kind == "stock" else None,
        "dirty" if kind == "stock" else "reported_unknown",
        tuple(refs),
        tuple(sorted(reasons)),
    )


def analyse(views, isin, kind, start, end, events, references, gaps):
    opening, closing = endpoint(views, isin, start, kind), endpoint(views, isin, end, kind)
    selected = tuple(
        e
        for e in events
        if e.isin in (isin, None)
        and (
            (e.event_date and start < e.event_date <= end)
            or (e.depository_settlement_date and start < e.depository_settlement_date <= end)
            or any(start < leg.date <= end for leg in e.cash_legs)
            or (e.trade_time and start < _date(e.trade_time[:10]) <= end and not e.counted)
        )
    )
    source_reasons = {
        g.code
        for g in gaps
        if g.isin in (isin, None)
        # v2 attributes these dated failures at event scope; legacy month gaps
        # remain in the root DTO without contaminating an unrelated instrument.
        and g.code
        not in {"unrecognized_money", "unattributed_income", "overlap_flow_choice_conflict"}
        and not g.code.startswith("payout_link_")
        and g.month
        and start.replace(day=1) <= g.month <= end.replace(day=1)
        and not (
            g.month == start.replace(day=1)
            and start.day != 1
            and (start + timedelta(days=1)).month != start.month
        )
    }
    for view in views:
        if _date(view["covered_from"]) > end or _date(view["covered_to"]) <= start:
            continue
        for proposal in view.get("proposals", []):
            if proposal["isin"] == isin:
                source_reasons.update(
                    r
                    for r in proposal.get("currency_assessment", {}).get("reasons", [])
                    if r
                    in {
                        "source_intake_currency_conflict",
                        "source_intake_currency_unsupported",
                        "source_intake_public_proof_stale",
                    }
                )
    intervals = sorted(
        (_date(v["covered_from"]), _date(v["covered_to"]))
        for v in views
        if "period_inferred_from_content" not in v["document"].get("warnings", [])
    )
    cursor = start + timedelta(days=1)
    for a, b in intervals:
        if a <= cursor <= b:
            cursor = b + timedelta(days=1)
    if cursor <= end:
        source_reasons.add("incomplete_source_coverage")
    event_reasons = source_reasons | {r for e in selected for r in e.reason_codes}
    # Conflicting shared inner EOD evidence is a broken seam, even if outer Q nets out.
    boundaries = {_date(v["covered_to"]) for v in views}
    boundaries &= {_date(v["covered_from"]) - timedelta(days=1) for v in views}
    for boundary in boundaries:
        if (
            start < boundary < end
            and "overlapping_endpoint_conflict"
            in endpoint(views, isin, boundary, kind).reason_codes
        ):
            event_reasons.add("seam_mismatch")
    payout_reasons = source_reasons | {
        r for e in selected if e.kind not in {"BUY", "SELL", "FEE", "TAX"} for r in e.reason_codes
    }
    cost_reasons = source_reasons | {
        r for e in selected if e.kind not in {"COUPON", "DIVIDEND"} for r in e.reason_codes
    }
    quantity_reasons = set(source_reasons)
    with localcontext() as context:
        context.prec = 200
        delta = Decimal(0)
        daily = defaultdict(Decimal)
        for e in selected:
            if e.kind not in {"BUY", "SELL"}:
                continue
            if not e.counted or e.quantity_delta is None or e.depository_settlement_date is None:
                quantity_reasons.add("quantity_events_incomplete")
                continue
            cash_inside = any(start < leg.date <= end for leg in e.cash_legs)
            depo_inside = start < e.depository_settlement_date <= end
            if cash_inside != depo_inside:
                quantity_reasons.add("cross_boundary_settlement")
            if depo_inside:
                delta += e.quantity_delta
                daily[e.depository_settlement_date] += e.quantity_delta
        if opening.quantity is None or closing.quantity is None:
            quantity_reasons.add("missing_quantity")
        elif closing.quantity - opening.quantity != delta:
            quantity_reasons.add("quantity_reconciliation_mismatch")
        if opening.quantity is not None:
            holding = opening.quantity
            for _, change in sorted(daily.items()):
                holding += change
                if holding < 0:
                    quantity_reasons.add("negative_observed_holding")
    endpoint_reasons = set(opening.reason_codes + closing.reason_codes) - {
        "bond_valuation_basis_unknown",
        "instrument_type_unknown",
    }
    valuation_reasons = set(opening.reason_codes + closing.reason_codes)
    valuation_reasons.update(
        a for e in selected for a in e.assumptions if a == "face_value_assumed"
    )
    coverage = {
        name: Coverage(not reasons, tuple(sorted(reasons)))
        for name, reasons in (
            ("events", event_reasons),
            ("quantity", quantity_reasons),
            ("endpoints", endpoint_reasons),
            ("payouts", payout_reasons),
            ("costs", cost_reasons),
            ("valuation", valuation_reasons),
        )
    }
    components, pnl, subtotal, rate, estimate = calculate_economics(
        opening, closing, selected, coverage
    )
    history_start = min(
        (_date(v["covered_from"]) - timedelta(days=1) for v in views), default=start
    )
    history_end = max((_date(v["covered_to"]) for v in views), default=end)
    return InstrumentAnalysis(
        opening_date=start,
        closing_date=end,
        history_start=history_start,
        history_end=history_end,
        history_complete_since_acquisition=(
            start == history_start
            and opening.quantity == 0
            and opening.reported_value_kopecks == 0
            and coverage["events"].complete
            and coverage["quantity"].complete
            and any(e.kind == "BUY" and e.counted for e in selected)
        ),
        events=selected,
        opening=opening,
        closing=closing,
        components=components,
        pnl=pnl,
        known_subtotal=subtotal,
        modified_dietz=rate,
        coverage=coverage,
        source_references=references,
        reason_codes=tuple(sorted({r for c in coverage.values() for r in c.reason_codes})),
        assumptions=tuple(sorted({a for e in selected for a in e.assumptions})),
        statement_estimate=estimate,
    )


def reconcile_account(session, views, start, end, analyses, events, *, filtered=False):
    """Compare account growth with instrument P; never distribute the residual."""
    from hermes_finance.services.source_monthly_returns import _saved_totals

    endpoints = [set(), set()]
    reasons = set()
    for view in views:
        if "period_inferred_from_content" in view["document"].get("warnings", []):
            if _date(view["covered_from"]) <= end and start < _date(view["covered_to"]):
                reasons.add("source_period_inferred")
            continue
        v0, v1, _ = _saved_totals(view["document"])
        if _date(view["covered_from"]) - timedelta(days=1) == start:
            endpoints[0].add(v0)
        if _date(view["covered_to"]) == end:
            endpoints[1].add(v1)
    values = [next(iter(v)) if len(v) == 1 else None for v in endpoints]
    if None in values:
        reasons.add("account_endpoint_unavailable")
    flows = defaultdict(list)
    local_gaps = []
    for view in views:
        try:
            for key, flow in _money(session, view, None, local_gaps):
                if start < flow.event_date <= end:
                    flows[key].append(flow)
        except (MyBrokerError, ValueError, TypeError, KeyError, ArithmeticError):
            reasons.add("source_reader_unavailable")
    reasons.update(
        g.code
        for g in local_gaps
        if g.month and (start + timedelta(days=1)).replace(day=1) <= g.month <= end.replace(day=1)
    )
    external = 0
    assumptions = set()
    for copies in flows.values():
        selected = [f for f in copies if f.status == "confirmed"] or copies
        if len({f.classification for f in selected}) != 1:
            reasons.add("overlap_flow_choice_conflict")
        flow = selected[0]
        if flow.classification == "unknown":
            reasons.add("unrecognized_money")
        if flow.included:
            external += flow.amount_kopecks
            if flow.status == "assumed":
                assumptions.add("external_flow_assumed")
    if not analyses or filtered or any(a.pnl.value is None for a in analyses):
        reasons.add("instrument_results_incomplete")
    if any(e.reason_codes for e in events if e.event_date and start < e.event_date <= end):
        reasons.add("unresolved_cash_evidence")
    account_growth = None if None in values else values[1] - values[0] - external
    cash_only = sum(
        leg.account_cash_kopecks
        for e in events
        if e.attribution_basis == "account_only"
        for leg in e.cash_legs
        if start < leg.date <= end and not e.reason_codes
    )
    known = [a.pnl.value for a in analyses if a.pnl.value is not None]
    instrument_total = sum(known) if known else None
    residual = None if reasons else account_growth - instrument_total - cash_only
    if residual not in (None, 0):
        reasons.add("account_reconciliation_residual")
    why = tuple(sorted(reasons))
    used = tuple(sorted(assumptions | {x for a in analyses for x in a.assumptions}))
    return AccountReconciliation(
        start,
        end,
        Metric(
            account_growth,
            "partial" if reasons else "provisional" if used else "supported",
            why,
            used,
        ),
        Metric(
            instrument_total,
            "partial" if reasons else "provisional" if used else "supported",
            why,
            used,
        ),
        Metric(cash_only, "partial" if reasons else "supported", why),
        Metric(
            residual,
            "unavailable" if residual is None else "partial" if reasons else "supported",
            why,
        ),
        not reasons and residual == 0,
        why,
    )
