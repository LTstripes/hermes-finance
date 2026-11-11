"""Read-only native instrument estimates; never financial receipt authority."""

from __future__ import annotations

import calendar
import json
import re
from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, localcontext

from sqlalchemy import select

from hermes_finance.database import coherent_read_operation
from hermes_finance.domain.instrument_return import (
    AccountReconciliation,
    Coverage,
    InstrumentAnalysis,
    InstrumentEvent,
    Metric,
    chain_monthly,
)
from hermes_finance.persistence import Instrument
from hermes_finance.services import broker_trade_money
from hermes_finance.services.broker_statement_provisional import _minor
from hermes_finance.services.source_money_classifications import source_reference
from hermes_finance.services.source_monthly_returns import (
    _SOURCE_SCOPE_READS,
    SOURCE_PERIOD_INFERRED_MESSAGE,
    SourceReturnGap,
    _money,
    _month_end,
    _native_scope,
    _next_month,
    _selected_sources,
    _source_read_inputs,
)
from hermes_finance.statement_import.money import normalize_currency
from hermes_finance.statement_import.mybroker import PROVIDER, MyBrokerError, digest


@dataclass(frozen=True)
class InstrumentReturnGap(SourceReturnGap):
    isin: str | None = None


@dataclass(frozen=True)
class InstrumentIncome:
    event_date: date
    amount_kopecks: int
    classification: str
    status: str
    source_references: tuple[str, ...]
    isin: str | None


@dataclass(frozen=True, kw_only=True)
class InstrumentReturnTotals:
    buys_cost_kopecks: int | None
    sells_proceeds_kopecks: int | None
    price_effect_kopecks: int | None
    coupons_kopecks: int | None
    dividends_kopecks: int | None
    assumed_income_kopecks: int | None
    confirmed_income_kopecks: int | None
    income_kopecks: int | None
    total_kopecks: int | None
    capital_base_kopecks: int | None
    return_percent: Decimal | None
    income_assumptions_used: bool
    income_complete: bool
    flags: tuple[str, ...]
    approximate: bool
    period: dict | None = None
    valuation_date: date | None = None


@dataclass(frozen=True, kw_only=True)
class InstrumentReturnMonth(InstrumentReturnTotals):
    month: date
    opening_quantity: Decimal | None
    closing_quantity: Decimal | None
    opening_value_kopecks: int | None
    closing_value_kopecks: int | None
    intake_ids: tuple[int, ...]
    analysis: InstrumentAnalysis | None = None


@dataclass(frozen=True, kw_only=True)
class InstrumentAllTime(InstrumentReturnTotals):
    available_months: tuple[date, ...]
    missing_months: tuple[date, ...]
    partial_months: tuple[date, ...]
    partial: bool


@dataclass(frozen=True)
class SourceInstrumentReturn:
    isin: str
    source_name: str | None
    instrument_type: str | None
    months: tuple[InstrumentReturnMonth, ...]
    all_time: InstrumentAllTime
    analysis: InstrumentAnalysis | None = None
    period: dict | None = None
    valuation_date: date | None = None
    account_link: dict | None = None


@dataclass(frozen=True)
class ReturnBreakdown:
    """Exact presentation operands over the existing economic result, never a new P&L."""

    payouts_kopecks: str | None
    price_and_trades_kopecks: str | None
    commissions_kopecks: str | None
    paid_nkd_kopecks: str | None
    taxes_kopecks: str | None
    other_kopecks: str | None
    total_kopecks: str | None
    complete: bool


@dataclass(frozen=True)
class SourceInstrumentReturns:
    source_account: str
    instruments: tuple[SourceInstrumentReturn, ...]
    income: tuple[InstrumentIncome, ...]
    gaps: tuple[InstrumentReturnGap, ...]
    native_source_account: str | None = None
    unresolved_events: tuple[InstrumentEvent, ...] = ()
    account_reconciliation_events: tuple[InstrumentEvent, ...] = ()
    reconciliation: AccountReconciliation | None = None
    authority: str = "provisional"
    financial_authority: str = "none"
    currency: str = "RUB"
    breakdown: ReturnBreakdown | None = None
    account_link: dict | None = None

    def to_dict(self):
        result = asdict(self)
        # The native source API keeps its existing component names; its new root
        # breakdown is the presentation bridge. Returns detail uses the service DTO.
        for instrument in result["instruments"]:
            analysis = instrument["analysis"]
            instrument["account_link"] = self.account_link
            instrument["period"] = (
                {"start": analysis["opening_date"], "end": analysis["closing_date"]}
                if analysis
                else None
            )
            instrument["valuation_date"] = (
                analysis["closing"]["date"]
                if analysis and analysis["closing"]["reported_value_kopecks"] is not None
                else (
                    analysis["opening"]["date"]
                    if analysis and analysis["opening"]["reported_value_kopecks"] is not None
                    else None
                )
            )
            for row in instrument["months"]:
                start = row["month"] - timedelta(days=1)
                end = row["month"].replace(
                    day=calendar.monthrange(row["month"].year, row["month"].month)[1]
                )
                row["period"] = {"start": start, "end": end}
                row["valuation_date"] = (
                    end
                    if row["closing_value_kopecks"] is not None
                    else (start if row["opening_value_kopecks"] is not None else None)
                )
            months = instrument["months"]
            instrument["all_time"]["period"] = (
                {"start": months[0]["period"]["start"], "end": months[-1]["period"]["end"]}
                if months
                else None
            )
            instrument["all_time"]["valuation_date"] = max(
                (r["valuation_date"] for r in months if r["valuation_date"]), default=None
            )
            for analysis in (
                instrument["analysis"],
                *(row["analysis"] for row in instrument["months"]),
            ):
                if analysis:
                    for name in ("payouts", "price_and_trades", "commissions", "paid_nkd"):
                        analysis["components"].pop(name, None)
        return result


def _quantity(value):
    if value is None:
        return None
    result = Decimal(value)
    return result if result.is_finite() and result >= 0 else None


def _percent(total, base):
    if total is None or base is None or base <= 0:
        return None
    with localcontext() as context:
        context.prec = 60
        context.rounding = ROUND_HALF_UP
        return Decimal(total) * 100 / Decimal(base)


def _token(text, value):
    """Whole identifiers/names only; no prefix-ISIN or short-name substring match."""
    value = " ".join(str(value or "").casefold().split())
    return bool(value) and re.search(r"(?<!\w)" + re.escape(value) + r"(?!\w)", text) is not None


def _attribute(text, identities):
    text = " ".join(text.casefold().split())
    for field in ("identifiers", "names"):
        matches = {
            isin
            for isin, metadata in identities.items()
            if any(_token(text, value) for value in metadata[field])
        }
        if matches:
            return next(iter(matches)) if len(matches) == 1 else None
    return None


def _attribute_reader(identities):
    """Reuse whole-token patterns, rebuilding if attribution adds an identity."""
    previous, fields, cache = None, [], {}

    def read(text):
        nonlocal previous, fields
        signature = tuple(
            (isin, tuple(metadata["identifiers"]), tuple(metadata["names"]))
            for isin, metadata in identities.items()
        )
        if signature != previous:
            fields = []
            for index in (1, 2):
                entries = []
                for row in signature:
                    patterns = []
                    for value in row[index]:
                        value = " ".join(str(value or "").casefold().split())
                        if value:
                            patterns.append(re.compile(r"(?<!\w)" + re.escape(value) + r"(?!\w)"))
                    entries.append((row[0], patterns))
                fields.append(entries)
            previous = signature
            cache.clear()
        text = " ".join(text.casefold().split())
        if text not in cache:
            result = None
            for entries in fields:
                matches = {
                    isin for isin, patterns in entries if any(p.search(text) for p in patterns)
                }
                if matches:
                    result = next(iter(matches)) if len(matches) == 1 else None
                    break
            cache[text] = result
        return cache[text]

    return read


def _identities(views):
    result = defaultdict(lambda: {"identifiers": set(), "names": set(), "types": set()})
    for view in views:
        for row in view["document"].get("positions", []):
            result[row["isin"]]["identifiers"].add(row["isin"])
        for trade in view["document"].get("trades", []):
            isin = trade["core"]["isin"]
            result[isin]["identifiers"].add(isin)
        for proposal in view.get("proposals", []):
            metadata = result[proposal["isin"]]
            metadata["identifiers"].add(proposal["isin"])
            if proposal.get("source_name"):
                metadata["names"].add(proposal["source_name"])
            if proposal.get("instrument_type"):
                metadata["types"].add(proposal["instrument_type"])
            # Only explicit saved aliases support registration-code attribution.
            for observation in (proposal, *proposal.get("observations", [])):
                for key in ("registration_code", "registration_number", "reg_code"):
                    if observation.get(key):
                        metadata["identifiers"].add(observation[key])
    return result


def _income(
    session,
    views,
    identities,
    gaps,
    *,
    resolved_redemptions=frozenset(),
    events=(),
    historical_evidence=None,
    analytical_payouts=None,
):
    from hermes_finance.services.money_instrument_links import MoneyInstrumentResolver
    from hermes_finance.services.source_instrument_events import payout_attribution

    resolver = MoneyInstrumentResolver(session)
    attribute_reader = _attribute_reader(identities)
    from hermes_finance.services.source_return_evidence import (
        canonical_payout_groups,
        overlapping_payout_index,
    )

    payout_groups = canonical_payout_groups(session, views, resolver)
    overlap_index = overlapping_payout_index(views)
    occurrences = defaultdict(list)
    compensation_refs = {
        ref
        for event in events
        if "unallocated_compensation" in event.reason_codes
        for ref in event.source_references
    }
    account_only_refs = {
        ref
        for event in events
        if event.attribution_basis == "account_only"
        for ref in event.source_references
    }
    event_scopes = defaultdict(set)
    for event in events:
        for reference in event.source_references:
            event_scopes[reference].add(event.isin)

    def gap_scope(flows):
        # Identity scope is not permission to count a payout. Reuse the dated
        # reader's exact source/trade/registration evidence, including conflicts.
        scopes = {
            scope
            for flow in flows
            for ref in flow.source_references
            for scope in event_scopes.get(ref, {None})
        }
        return next(iter(scopes)) if len(scopes) == 1 else None

    for view in views:
        saved = {r["source_reference"]: r for r in view["money_classifications"]}
        raw = {source_reference(view["id"], row): row for row in view["document"].get("money", [])}
        local_gaps = []
        try:
            for key, flow in _money(session, view, None, local_gaps, payout_groups=payout_groups):
                narrative = saved[flow.source_references[0]]
                isin, basis, reasons = payout_attribution(
                    narrative,
                    resolver,
                    identities,
                    session=session,
                    view=view,
                    raw=raw[flow.source_references[0]],
                    views=views,
                    historical_evidence=historical_evidence,
                    canonical_matches=payout_groups,
                    overlap_index=overlap_index,
                    attribute_reader=attribute_reader,
                    analytical_payouts=analytical_payouts,
                )
                if basis in {"accepted_money", "current_source_proof"}:
                    flow = replace(flow, status="confirmed")
                if basis == "registration_scope":
                    # Legacy income must not turn coverage-only identity into a payout.
                    isin = None
                if flow.classification in {"coupon", "dividend"}:
                    gaps.extend(
                        InstrumentReturnGap(
                            code,
                            view["id"],
                            flow.event_date.replace(day=1),
                            flow.source_references[0],
                            isin=gap_scope([flow]),
                        )
                        for code in reasons
                    )
                occurrences[key].append((flow, isin))
        except (MyBrokerError, ValueError, TypeError, KeyError, ArithmeticError):
            month = date.fromisoformat(view["covered_from"]).replace(day=1)
            while month <= date.fromisoformat(view["covered_to"]):
                gaps.append(InstrumentReturnGap("source_reader_unavailable", view["id"], month))
                month = _next_month(month)
        # A confirmed cash gift is an account-level external flow, not a gap
        # in the evidence for each individual instrument.
        gaps.extend(
            InstrumentReturnGap(
                **asdict(gap),
                isin=next(iter(event_scopes[gap.source_reference]))
                if len(event_scopes[gap.source_reference]) == 1
                else None,
            )
            for gap in local_gaps
            if gap.code != "broker_gift_external_flow"
        )
    result = []
    for key, observations in occurrences.items():
        confirmed = [pair for pair in observations if pair[0].status == "confirmed"]
        selected = confirmed or observations
        flow, isin = selected[0]
        month = flow.event_date.replace(day=1)
        scope_isin = gap_scope([f for f, _ in selected])
        if flow.classification == "unknown" and f"money:{key[0]}:{key[1]}" in resolved_redemptions:
            continue
        if all(ref in account_only_refs for f, _ in observations for ref in f.source_references):
            continue
        if len({(f.classification, identity) for f, identity in selected}) != 1:
            gaps.append(
                InstrumentReturnGap(
                    "overlap_flow_choice_conflict",
                    month=month,
                    isin=scope_isin,
                )
            )
            continue
        if flow.classification == "unknown":
            code = (
                "unallocated_compensation"
                if all(
                    ref in compensation_refs for f, _ in observations for ref in f.source_references
                )
                else "unrecognized_money"
            )
            gaps.append(InstrumentReturnGap(code, month=month, isin=scope_isin))
        if flow.classification not in {"coupon", "dividend"}:
            continue
        refs = tuple(ref for f, _ in observations for ref in f.source_references)
        result.append(
            InstrumentIncome(
                flow.event_date, flow.amount_kopecks, flow.classification, flow.status, refs, isin
            )
        )
        if isin is None:
            gaps.append(
                InstrumentReturnGap(
                    "unattributed_income", month=month, source_reference=refs[0], isin=scope_isin
                )
            )
    return tuple(sorted(result, key=lambda row: (row.event_date, row.source_references)))


def _endpoint(views, isin, month, *, closing, flags):
    operands = [set(), set()]
    invalid = [False, False]
    boundary = _month_end(month) if closing else month
    for view in views:
        if "period_inferred_from_content" in view["document"].get("warnings", []):
            continue  # Activity dates cannot date the statement's outer balances.
        if date.fromisoformat(view["covered_to" if closing else "covered_from"]) != boundary:
            continue
        rows = [row for row in view["document"]["positions"] if row["isin"] == isin]
        if not rows:
            continue  # An absent position row is not affirmative zero.
        if len({row["source_account"] for row in rows}) != len(rows):
            flags.add("duplicate_position")
            invalid = [True, True]
            continue
        values = [_minor(row.get("ending_value" if closing else "beginning_value")) for row in rows]
        quantities = []
        for row in rows:
            try:
                quantities.append(
                    _quantity(
                        row.get("actual_quantity" if closing else "beginning_actual_quantity")
                    )
                )
            except (ValueError, TypeError, ArithmeticError):
                quantities.append(None)
        if any(q == 0 and v not in (None, 0) for q, v in zip(quantities, values, strict=True)):
            flags.add("quantity_value_conflict")
            invalid[1] = True
        for index, components in enumerate((quantities, values)):
            if any(v is None or v < 0 for v in components):
                invalid[index] = True
            else:
                with localcontext() as context:
                    context.prec = 100
                    operands[index].add(sum(components))
        if view["document"].get("endpoint_basis") != {
            "beginning_value": "previous_day_eod",
            "ending_value": "covered_to_eod",
        }:
            invalid = [True, True]
    result = []
    for values, unavailable in zip(operands, invalid, strict=True):
        if len(values) > 1:
            flags.add("overlapping_endpoint_conflict")
        if unavailable or len(values) != 1:
            flags.add("missing_endpoint")
            result.append(None)
        else:
            result.append(next(iter(values)))
    return tuple(result)


def _trade_core(core):
    return core | {"currency": normalize_currency(core["currency"])}


def _native_total_basis(session, trade):
    """Use only a current accepted proof matching this exact native trade.

    Source-intake V1 alone stores no reviewed NKD inclusion basis.
    Existing cash proofs currently cover buys.
    """
    proof = broker_trade_money.effective_proof(session, trade["identity"])
    if (
        not isinstance(proof, dict)
        or "proof_variant" in proof
        or not isinstance(proof.get("claims"), dict)
    ):
        return None
    try:
        from hermes_finance.services.returns_read_inputs import executed_trade

        accepted = executed_trade(session, trade["identity"])
        if accepted is None or _trade_core(json.loads(accepted.core_json)) != _trade_core(
            trade["core"]
        ):
            return None
        basis = proof["claims"].get("native_total_basis")
        if (
            basis not in ("includes_paid_nkd", "excludes_paid_nkd")
            or proof["source_identity"] != trade["identity"]
            or proof["native_ids"] != trade["ids"]
        ):
            return None
        with localcontext() as context:
            context.prec = 100
            groups = {
                role: [
                    {
                        "amount": str(Decimal(proof["signed_minor"][key]) / 100),
                        "date": proof["nkd_leg"]["effective_date"],
                        "currency": proof["nkd_leg"]["currency"],
                    }
                ]
                for role, key in (
                    ("settlement", "settlement"),
                    ("paid_nkd", "paid_nkd"),
                    ("commission", "commission"),
                )
            }
        normalized = dict(trade, core=_trade_core(trade["core"]))
        return None if broker_trade_money.cash_reasons(normalized, groups, proof) else basis
    except (ValueError, TypeError, KeyError, AttributeError, ArithmeticError):
        # A malformed proof is no basis; it cannot override the field definition.
        return None


def _missing_face_value(trade):
    # A present None is the parser's invalid/conflicting nominal marker.
    return "face_value" not in trade or trade["face_value"] == ""


def _face_signature(trade):
    """Canonicalize the two spellings of "no nominal" for overlap comparison.

    A missing key and an empty string both represent the same absent nominal
    marker. An invalid/conflicting None and explicit values stay distinct.
    """
    return "" if _missing_face_value(trade) else trade["face_value"]


def _bond_total_basis(session, trade, flags, *, documents):
    """Read MyBroker's field definition; never attest a Money occurrence owner.

    The frozen alfa_mybroker / mybroker-s1-v2 document identifies the parsed
    MyBroker report family (completed 2_Trades rows). No raw sign is rewritten.
    Explicit dated nominal checks consistency, never selects an excludes basis.
    """
    if not documents or any(
        d.get("provider") != "alfa_mybroker" or d.get("parser") != "mybroker-s1-v2"
        for d in documents
    ):
        return None
    if trade.get("section") != "completed":
        return None
    reviewed = _native_total_basis(session, trade)
    if reviewed is not None and reviewed != "includes_paid_nkd":
        flags.add("trade_nkd_basis_conflict")
        return None
    try:
        core = trade["core"]
        price, quantity, amount, nkd = (
            Decimal(core["price"]),
            Decimal(core["quantity"]),
            Decimal(core["trade_amount"]),
            Decimal(trade["accrued_interest"]),
        )
        if (
            any(not value.is_finite() for value in (price, quantity, amount, nkd))
            or quantity == 0
            or any(value < 0 for value in (price, amount, nkd))
        ):
            return None
        if _missing_face_value(trade):
            flags.add("trade_face_value_missing")
        else:
            face = Decimal(trade["face_value"])
            if not face.is_finite() or face <= 0:
                return None
            with localcontext() as context:
                context.prec = 200
                principal = price / 100 * face * abs(quantity)
                if abs(amount - principal - nkd) > Decimal("0.01"):
                    flags.add("trade_nkd_basis_conflict")
                    return None
        return "includes_paid_nkd"
    except (ValueError, TypeError, KeyError, ArithmeticError):
        return None


def _trade_cash_total(amount, nkd, fee, quantity, basis):
    if basis not in {"includes_paid_nkd", "excludes_paid_nkd"}:
        return None
    total = amount + (nkd if basis == "excludes_paid_nkd" else 0)
    return total + fee if quantity > 0 else total - fee


def _trades(session, views, isin, month, instrument_type, flags):
    from hermes_finance.services.source_trade_identity import (
        repo_return_identities,
        trade_observation_conflict,
    )

    groups = defaultdict(list)
    documents = defaultdict(list)
    occurrences = defaultdict(list)
    for view in views:
        repo_ids = view.get("return_repo_identities")
        for trade in view["document"].get("trades", []):
            if trade["core"]["isin"] == isin:
                if repo_ids is None and trade.get("repo_observed"):
                    repo_ids = repo_return_identities(view)
                repo_identity = (
                    (repo_ids or {}).get(trade["ordinal"])
                    if trade["section"] == "completed"
                    else None
                )
                if repo_identity:
                    trade = dict(
                        trade, return_identity=repo_identity[0], repo_signature=repo_identity[1]
                    )
                key = trade.get("identity") or trade.get("return_identity") or object()
                documents[key].append(view["document"])
                occurrences[key].append((view, trade))
                # Keep unresolved occurrences separate solely to flag their months;
                # they are never eligible for counting or deduplication.
                # A position nominal has no proven validity at the trade date.
                groups[key].append(
                    trade if instrument_type == "bond" else dict(trade, face_value=None)
                )
    buys = sells = 0
    quantity = Decimal(0)
    invalid = False
    for key, observations in groups.items():
        settled = [trade for trade in observations if trade["state"] == "settled"]
        selected = settled or observations
        try:

            def observed_month(trade):
                return date.fromisoformat(
                    trade.get("settlement_date") or trade["core"]["trade_time"][:10]
                ).replace(day=1)

            # Pending settlement dates are plans. Disclose uncertainty in both
            # the execution month and the planned settlement month.
            relevant = [
                t
                for t in selected
                if observed_month(t) == month
                or (
                    not settled
                    and date.fromisoformat(t["core"]["trade_time"][:10]).replace(day=1) == month
                )
            ]
            if not relevant:
                continue
            if any(
                not t.get("return_identity")
                and (not t.get("identity") or len(t.get("ids", [])) != 2)
                for t in relevant
            ):
                flags.add("trade_identity_unresolved")
                invalid = True
                continue
            if len({digest(_trade_core(t["core"])) for t in observations}) != 1:
                flags.add("overlapping_trade_conflict")
                invalid = True
                continue
            signatures = {
                digest(
                    {
                        k: _face_signature(t) if k == "face_value" else t.get(k)
                        for k in (
                            "settlement_date",
                            "bank_commission",
                            "accrued_interest",
                            "repo_observed",
                            "repo_signature",
                            "face_value",
                        )
                    }
                )
                for t in selected
            }
            if len(signatures) != 1 or trade_observation_conflict(occurrences[key]):
                flags.add("overlapping_trade_conflict")
                invalid = True
                continue
            trade = relevant[0]
            core = trade["core"]
            if not settled or not trade.get("settlement_date"):
                flags.add("trade_missing_settlement")
                invalid = True
                continue
            if normalize_currency(core["currency"]) != "RUB" or trade.get("repo_observed"):
                flags.add(
                    "trade_currency_unsupported"
                    if normalize_currency(core["currency"]) != "RUB"
                    else "repo_trade_unsupported"
                )
                invalid = True
                continue
            amount, nkd, fee = (
                _minor(core.get("trade_amount")),
                _minor(trade.get("accrued_interest")),
                _minor(trade.get("bank_commission")),
            )
            if nkd is None and instrument_type == "stock" and trade.get("accrued_interest") is None:
                nkd = 0  # NKD is inapplicable only for a known stock.
            qty = Decimal(core["quantity"])
            if (
                not qty.is_finite()
                or qty == 0
                or any(v is None or v < 0 for v in (amount, nkd, fee))
            ):
                flags.add("trade_components_missing")
                invalid = True
                continue
            if instrument_type == "stock":
                basis = "excludes_paid_nkd"
            elif instrument_type == "bond":
                basis = _bond_total_basis(session, trade, flags, documents=documents[key])
            else:
                basis = _native_total_basis(session, trade)
            cash_total = _trade_cash_total(amount, nkd, fee, qty, basis)
            if cash_total is None:
                flags.add("trade_nkd_basis_unknown")
                invalid = True
                continue
            if qty > 0:
                buys += cash_total
            else:
                sells += cash_total
            with localcontext() as context:
                context.prec = 100
                quantity += qty
        except (ValueError, TypeError, KeyError, ArithmeticError):
            flags.add("trade_components_missing")
            invalid = True
    return (None, None, None) if invalid else (buys, sells, quantity)


_INCOME_GAPS = {
    "source_period_inferred",
    "unattributed_income",
    "currency_unsupported",
    "classification_missing_legacy_intake",
    "invalid_money_row",
    "invalid_external_flow",
    "unrecognized_money",
    "unallocated_compensation",
    "overlap_flow_choice_conflict",
    "overlap_money_occurrence_missing",
}
_SOURCE_GAPS = {
    "source_period_inferred",
    # Structure gaps affect both trades and income; currency/REPO gaps do not.
    "4_Transfers_unsupported",
    "custody_cancellation_unresolved",
    "5_UFSR_unsupported",
    "source_reader_unavailable",
    "native_source_scope_ambiguous",
    "unparsed_source_rows",
    "unknown_section",
    "position_row_unclassified",
}
_DISCLOSURES = {
    "bond_valuation_basis_unknown",
    "trade_face_value_missing",
    "income_assumed",
    "income_confirmed",
}


def _source_gap(code):
    return code in _SOURCE_GAPS


def _month(
    session,
    views,
    isin,
    instrument_type,
    month,
    income,
    gaps,
    previous,
    *,
    reviewed_basis=None,
    events=(),
):
    from hermes_finance.services.source_instrument_events import endpoint

    end = _month_end(month)
    relevant = [
        v
        for v in views
        if v["covered_from"] <= month.isoformat() and v["covered_to"] >= end.isoformat()
    ]
    flags = set()
    if not relevant:
        flags.add("missing_month")
    if instrument_type == "bond" and not (
        relevant
        and reviewed_basis is not None
        and all(
            endpoint(
                views, isin, day, instrument_type, reviewed_basis=reviewed_basis
            ).valuation_basis
            == "dirty"
            for day in (month - timedelta(days=1), end)
        )
    ):
        flags.add("bond_valuation_basis_unknown")
    elif instrument_type not in {"stock", "bond"}:
        flags.add("instrument_type_unknown")
    for gap in gaps:
        if (
            gap.month == month
            and gap.isin in (None, isin)
            and (gap.code in _INCOME_GAPS or _source_gap(gap.code))
        ):
            flags.add(gap.code)
    q0, v0 = _endpoint(relevant, isin, month, closing=False, flags=flags)
    q1, v1 = _endpoint(relevant, isin, month, closing=True, flags=flags)
    buys, sells, traded_quantity = _trades(session, views, isin, month, instrument_type, flags)
    redemptions = [
        e
        for e in events
        if e.isin == isin
        and e.kind == "REDEMPTION"
        and e.counted
        and e.current
        and not e.reason_codes
    ]
    redemption_cash = sum(
        leg.account_cash_kopecks
        for e in redemptions
        for leg in e.cash_legs
        if month <= leg.date <= end
    )
    with localcontext() as context:
        context.prec = 100
        if traded_quantity is not None:
            traded_quantity += sum(
                (
                    e.quantity_delta
                    for e in redemptions
                    if e.quantity_delta is not None
                    and e.depository_settlement_date is not None
                    and month <= e.depository_settlement_date <= end
                ),
                Decimal(0),
            )
    if not relevant or any(_source_gap(flag) for flag in flags):
        buys = sells = None
    if previous and (
        (
            v0 is not None
            and previous.closing_value_kopecks is not None
            and v0 != previous.closing_value_kopecks
        )
        or (
            q0 is not None
            and previous.closing_quantity is not None
            and q0 != previous.closing_quantity
        )
    ):
        flags.add("seam_mismatch")
    with localcontext() as context:
        context.prec = 100
        if (
            q0 is not None
            and q1 is not None
            and traded_quantity is not None
            and q1 - q0 != traded_quantity
        ):
            flags.add("seam_mismatch")
    paid = [row for row in income if row.isin == isin and row.event_date.replace(day=1) == month]
    income_complete = bool(relevant) and not (
        flags & _INCOME_GAPS or any(_source_gap(flag) for flag in flags)
    )

    def observed_income(rows):
        values = [row.amount_kopecks for row in rows]
        return sum(values) if values or income_complete else None

    coupons = observed_income(row for row in paid if row.classification == "coupon")
    dividends = observed_income(row for row in paid if row.classification == "dividend")
    assumed = observed_income(row for row in paid if row.status == "assumed")
    confirmed = observed_income(row for row in paid if row.status == "confirmed")
    income_total = observed_income(paid)
    assumptions = any(row.status == "assumed" for row in paid)
    if assumptions:
        flags.add("income_assumed")
    if any(row.status == "confirmed" for row in paid):
        flags.add("income_confirmed")
    price = None if None in (v0, v1, buys, sells) else v1 - v0 - buys + sells + redemption_cash
    base = None if None in (v0, buys) else v0 + buys
    # Preserve independent observed components, but never publish a monthly net
    # result while a relevant non-trade cash operation is unresolved. Trade fees
    # already belong to buys/sells; only standalone dated FEE/TAX legs go here.
    local_events = [
        e
        for e in events
        if e.isin in (None, isin)
        and e.attribution_basis != "account_only"
        and e.event_date is not None
        and month <= e.event_date <= end
        and e.kind not in {"BUY", "SELL"}
    ]
    cash_reasons = {reason for e in local_events for reason in e.reason_codes}
    flags.update(cash_reasons)
    separate_costs = sum(
        leg.account_cash_kopecks
        for e in local_events
        if e.kind in {"FEE", "TAX"}
        and e.isin == isin
        and e.current
        and e.counted
        and not e.reason_codes
        for leg in e.cash_legs
        if month <= leg.date <= end
    )
    total = (
        None
        if price is None or not income_complete or cash_reasons
        else price + income_total + separate_costs
    )
    if base is not None and base <= 0:
        flags.add("nonpositive_capital_base")
    return InstrumentReturnMonth(
        month=month,
        opening_quantity=q0,
        closing_quantity=q1,
        opening_value_kopecks=v0,
        closing_value_kopecks=v1,
        buys_cost_kopecks=buys,
        sells_proceeds_kopecks=sells,
        price_effect_kopecks=price,
        coupons_kopecks=coupons,
        dividends_kopecks=dividends,
        assumed_income_kopecks=assumed,
        confirmed_income_kopecks=confirmed,
        income_kopecks=income_total,
        total_kopecks=total,
        capital_base_kopecks=base,
        return_percent=_percent(total, base),
        income_assumptions_used=assumptions,
        income_complete=income_complete,
        flags=tuple(sorted(flags)),
        approximate=bool(flags - {"income_confirmed"}),
        intake_ids=tuple(v["id"] for v in relevant),
    )


def _all_time(months):
    flags = set(flag for row in months for flag in row.flags)
    available = [row for row in months if row.total_kopecks is not None]
    missing = [row.month for row in months if "missing_month" in row.flags]
    partial = [
        row.month
        for row in months
        if row.total_kopecks is None and "missing_month" not in row.flags
    ]

    def subtotal(field):
        values = [getattr(row, field) for row in months if getattr(row, field) is not None]
        return sum(values) if values else None

    total = sum(row.total_kopecks for row in available) if available else None
    # The assignment defines monthly rates and all-time monetary sums only.
    # Repeated monthly opening capital is not an all-time investment basis.
    base = None
    return InstrumentAllTime(
        buys_cost_kopecks=subtotal("buys_cost_kopecks"),
        sells_proceeds_kopecks=subtotal("sells_proceeds_kopecks"),
        price_effect_kopecks=subtotal("price_effect_kopecks"),
        coupons_kopecks=subtotal("coupons_kopecks"),
        dividends_kopecks=subtotal("dividends_kopecks"),
        assumed_income_kopecks=subtotal("assumed_income_kopecks"),
        confirmed_income_kopecks=subtotal("confirmed_income_kopecks"),
        income_kopecks=subtotal("income_kopecks"),
        total_kopecks=total,
        capital_base_kopecks=base,
        return_percent=_percent(total, base),
        income_assumptions_used=any(row.income_assumptions_used for row in months),
        income_complete=all(row.income_complete for row in months),
        flags=tuple(sorted(flags)),
        approximate=any(row.approximate for row in months),
        available_months=tuple(row.month for row in available),
        missing_months=tuple(missing),
        partial_months=tuple(partial),
        partial=bool(missing or partial or flags - _DISCLOSURES),
    )


def _breakdown_analysis(analysis, money_roles):
    """Reclassify counted cash once, preserving settlement dates and missing operands."""
    start, end = analysis.opening_date, analysis.closing_date
    embedded_fees, paid_nkd = 0, 0
    nkd_known = True
    costs_complete = analysis.coverage["costs"].complete
    for event in analysis.events:
        if not event.counted or event.kind not in {"BUY", "SELL"}:
            continue
        inside = [leg for leg in event.cash_legs if start < leg.date <= end]
        embedded_fees += sum(
            leg.instrument_flow_kopecks for leg in inside if leg.role == "commission"
        )
        if event.kind != "BUY":
            continue
        explicit_nkd = [leg for leg in event.cash_legs if leg.role == "nkd"]
        if explicit_nkd:
            paid_nkd += sum(
                leg.instrument_flow_kopecks for leg in explicit_nkd if start < leg.date <= end
            )
        principal = [leg for leg in event.cash_legs if leg.role == "principal"]
        selected_principal = [leg for leg in principal if start < leg.date <= end]
        if selected_principal and not explicit_nkd:
            if event.accrued_interest_kopecks is None or len(selected_principal) != len(principal):
                nkd_known = False
            else:
                paid_nkd += event.accrued_interest_kopecks
        for leg in inside:
            if leg.role == "native_money":
                # Original-bound Money owns cash, not the informational native trade NKD.
                is_nkd = money_roles.get(leg.ownership)
                if is_nkd is None:
                    nkd_known = False
                    continue
                if is_nkd:
                    paid_nkd += leg.instrument_flow_kopecks
            elif leg.role not in {"principal", "commission", "nkd"}:
                nkd_known = False
    if not costs_complete or not nkd_known:
        paid_nkd = None
    components = dict(analysis.components)

    def combine(names, adjustment=0):
        operands = [components[name] for name in names]
        values = [metric.value for metric in operands]
        value = None if adjustment is None or None in values else sum(values) + adjustment
        reasons = tuple(sorted({r for metric in operands for r in metric.reason_codes}))
        assumptions = tuple(sorted({a for metric in operands for a in metric.assumptions}))
        complete = value is not None and all(
            metric.status in {"supported", "provisional"} for metric in operands
        )
        if complete:
            status = (
                "provisional"
                if assumptions or any(m.status == "provisional" for m in operands)
                else "supported"
            )
        else:
            status = "unavailable" if value is None else "partial"
        if value is None:
            reasons = tuple(sorted(set(reasons) | {"breakdown_incomplete"}))
        return Metric(value, status, reasons, assumptions)

    components["payouts"] = combine(("coupons", "dividends"))
    components["commissions"] = combine(("fees",), embedded_fees if costs_complete else None)
    components["paid_nkd"] = Metric(
        paid_nkd,
        "supported" if paid_nkd is not None else "unavailable",
        () if paid_nkd is not None else ("breakdown_incomplete",),
    )
    components["price_and_trades"] = combine(
        ("valuation_and_trades", "redemption"),
        None if paid_nkd is None or not costs_complete else embedded_fees + paid_nkd,
    )
    return replace(analysis, components=components)


def _with_return_breakdown(result, views, *, account_rows=()):
    from hermes_finance.services.source_money_classifications import _is_nkd, source_reference

    money_roles = {}
    for view in views:
        saved = {r["source_reference"]: r for r in view["money_classifications"]}
        for raw in view["document"].get("money", []):
            row = saved.get(source_reference(view["id"], raw))
            if row is not None:
                ref = f"{view['document']['document_sha256']}:money:{raw['ordinal']}"
                money_roles[ref] = _is_nkd(row["operation"] + " " + row["narrative"])
    instruments = tuple(
        replace(
            row,
            analysis=_breakdown_analysis(row.analysis, money_roles) if row.analysis else None,
            months=tuple(
                replace(month, analysis=_breakdown_analysis(month.analysis, money_roles))
                if month.analysis
                else month
                for month in row.months
            ),
        )
        for row in result.instruments
    )
    analyses = [row.analysis for row in instruments if row.analysis is not None]

    def aggregate(name):
        values = [row.components[name].value for row in analyses]
        return sum(values) if values and None not in values else None

    reconciliation = result.reconciliation
    total = reconciliation.account_growth.value if reconciliation else None
    other = reconciliation.account_only_result.value if reconciliation else None
    values = [
        aggregate(name)
        for name in ("payouts", "price_and_trades", "commissions", "paid_nkd", "taxes")
    ]
    # Keep proven account costs in their own expense rows without allocating them to ISINs.
    account_costs = {
        kind: -sum(int(row["amount_kopecks"]) for row in account_rows if row["kind"] == name)
        for kind, name in (("FEE", "account_fee"), ("TAX", "account_tax"))
    }
    if reconciliation:
        for event in result.account_reconciliation_events:
            if event.kind in account_costs and not event.reason_codes:
                account_costs[event.kind] += sum(
                    leg.instrument_flow_kopecks
                    for leg in event.cash_legs
                    if reconciliation.opening_date < leg.date <= reconciliation.closing_date
                )
    for index, kind in ((2, "FEE"), (4, "TAX")):
        if values[index] is not None:
            values[index] += account_costs[kind]
    if other is not None:
        other += sum(account_costs.values())
    complete = bool(
        reconciliation
        and reconciliation.complete
        and total is not None
        and other is not None
        and None not in values
        and all(all(c.complete for c in row.coverage.values()) for row in analyses)
        and values[0] + values[1] - values[2] - values[3] - values[4] + other == total
    )

    def wire(value):
        return None if value is None else str(value)

    return replace(
        result,
        instruments=instruments,
        breakdown=ReturnBreakdown(
            *(wire(value) for value in values),
            wire(other),
            wire(total),
            complete,
        ),
    )


def _clean_proof_constraints(analysis, proof):
    """Keep exact current proof boundaries and conflicts in the clean read."""
    if proof is None or (analysis.opening_date, analysis.closing_date) != (
        proof.opening_date,
        proof.closing_date,
    ):
        return analysis
    relevant = {
        "pdf_xml_position_mismatch",
        "pdf_position_invalid",
        "pdf_position_date_missing",
        "pdf_position_date_invalid",
        "pdf_payout_row_invalid",
        "pdf_xml_payout_mismatch",
        "payout_identity_ambiguous",
        "pdf_actual_payout_section_missing",
        "pdf_account_period_invalid",
    }
    coverage = dict(analysis.coverage)

    def proved_zero(native, confirmed):
        if (
            native.quantity == confirmed.quantity == 0
            and native.reported_value_kopecks is None
            and confirmed.reported_value_kopecks == confirmed.economic_value_kopecks == 0
            and native.source_references
            and set(native.reason_codes) <= {"missing_endpoint", "bond_valuation_basis_unknown"}
            and all(
                proof.coverage[name].complete for name in ("quantity", "endpoints", "valuation")
            )
        ):
            return replace(
                native,
                reported_value_kopecks=0,
                economic_value_kopecks=0,
                reason_codes=tuple(r for r in native.reason_codes if r != "missing_endpoint"),
            )
        return native

    opening = proved_zero(analysis.opening, proof.opening)
    closing = proved_zero(analysis.closing, proof.closing)
    reasons = set(analysis.reason_codes)
    inherited = set()
    for name, old in coverage.items():
        conflicts = set(proof.coverage[name].reason_codes) & relevant
        if conflicts:
            inherited.update(conflicts)
            coverage[name] = Coverage(False, tuple(sorted(set(old.reason_codes) | conflicts)))
    endpoint_conflicts = set(coverage["endpoints"].reason_codes) & relevant
    if endpoint_conflicts:
        closing = replace(
            closing,
            economic_value_kopecks=None,
            reason_codes=tuple(sorted(set(closing.reason_codes) | endpoint_conflicts)),
        )
    return replace(
        analysis,
        opening=opening,
        closing=closing,
        coverage=coverage,
        reason_codes=tuple(sorted(reasons | inherited)),
    )


_PDF_PAYOUT_CONFLICTS = {
    "pdf_payout_row_invalid",
    "pdf_xml_payout_mismatch",
    "payout_identity_ambiguous",
    "pdf_actual_payout_section_missing",
    "pdf_account_period_invalid",
}


def _clean_historical_payout_conflicts(analysis, proof):
    if not (
        analysis.opening_date < proof.closing_date and proof.opening_date < analysis.closing_date
    ):
        return analysis
    conflicts = set(proof.coverage["payouts"].reason_codes) & _PDF_PAYOUT_CONFLICTS
    if not conflicts:
        return analysis
    coverage = dict(analysis.coverage)
    coverage["payouts"] = Coverage(
        False, tuple(sorted(set(coverage["payouts"].reason_codes) | conflicts))
    )
    return replace(
        analysis,
        coverage=coverage,
        reason_codes=tuple(sorted(set(analysis.reason_codes) | conflicts)),
    )


def _clean_historical_position_conflicts(analysis, proof):
    """Retain a current PDF position conflict at a boundary in this period."""
    boundary = proof.closing_date
    if not analysis.opening_date <= boundary <= analysis.closing_date:
        return analysis
    conflicts = set(proof.reason_codes) & {
        "pdf_xml_position_mismatch",
        "pdf_position_invalid",
        "pdf_position_date_missing",
        "pdf_position_date_invalid",
    }
    if not conflicts:
        return analysis
    coverage = dict(analysis.coverage)
    quantity = coverage["quantity"]
    coverage["quantity"] = Coverage(False, tuple(sorted(set(quantity.reason_codes) | conflicts)))

    def conflicted(endpoint):
        return replace(
            endpoint,
            economic_value_kopecks=None,
            reason_codes=tuple(sorted(set(endpoint.reason_codes) | conflicts)),
        )

    return replace(
        analysis,
        opening=conflicted(analysis.opening)
        if boundary == analysis.opening_date
        else analysis.opening,
        closing=conflicted(analysis.closing)
        if boundary == analysis.closing_date
        else analysis.closing,
        coverage=coverage,
        reason_codes=tuple(sorted(set(analysis.reason_codes) | conflicts)),
    )


def _prepare_instrument_inputs(
    session,
    source_account,
    selected,
    native_scope,
    *,
    clean_projection,
    clean_proofs,
    reviewed_basis,
    cancellation_dates,
    relevant_cancellation,
    catalogue_outer,
):
    from hermes_finance.services.source_instrument_events import read_events
    from hermes_finance.services.source_redemption_evidence import verified_redemptions

    views, sources, gaps = [], [], []
    cancellation_scopes, redemption_evidence = (
        verified_redemptions(session, source_account, selected, native_scope, cancellation_dates)
        if relevant_cancellation
        else ({}, {})
    )
    for original, view, error in selected:
        try:
            sources.append(original)
            if error:
                raise MyBrokerError(error)
            if (
                native_scope is None
                or _native_scope(view["document"]) != native_scope
                or source_account not in native_scope | {view["document"]["filename_account"]}
            ):
                raise MyBrokerError("native_source_scope_ambiguous")
            views.append(view)
            period_inferred = "period_inferred_from_content" in view["document"].get("warnings", [])
            from hermes_finance.services.returns_read_inputs import source_blockers

            blockers = source_blockers(session, view)
            proven_cancellations = cancellation_dates.get(original.id)
            if proven_cancellations is not None:
                blockers -= {
                    "unparsed_source_rows",
                    "4_Transfers_unsupported",
                    "5_UFSR_unsupported",
                }
            month = original.covered_from.replace(day=1)
            while month <= original.covered_to:
                month_blockers = blockers | (
                    {"custody_cancellation_unresolved"}
                    if proven_cancellations and month in proven_cancellations
                    else set()
                )
                gaps.extend(
                    InstrumentReturnGap(
                        code,
                        original.id,
                        month,
                        isin=cancellation_scopes.get((original.id, month))
                        if code == "custody_cancellation_unresolved"
                        else None,
                        message=SOURCE_PERIOD_INFERRED_MESSAGE
                        if code == "source_period_inferred"
                        else None,
                    )
                    for code in sorted(
                        {
                            *(("source_period_inferred",) if period_inferred else ()),
                            *month_blockers,
                            *(
                                code
                                for code in (
                                    *view["document"].get("endpoint_blockers", []),
                                    *view["document"].get("endpoint_conflicts", []),
                                )
                                if _source_gap(code)
                            ),
                        }
                    )
                )
                month = _next_month(month)
        except (MyBrokerError, ValueError, TypeError, KeyError, ArithmeticError) as error:
            code = (
                "native_source_scope_ambiguous"
                if str(error) == "native_source_scope_ambiguous"
                else "source_reader_unavailable"
            )
            month = original.covered_from.replace(day=1)
            while month <= original.covered_to:
                gaps.append(InstrumentReturnGap(code, original.id, month))
                month = _next_month(month)
    from hermes_finance.services.returns_read_inputs import repo_identities
    from hermes_finance.services.source_trade_identity import repo_return_identities

    # Owned by this one coherent read; never persisted or reused by a later GET.
    views = [
        {
            **view,
            "return_repo_identities": repo_identities(
                session, view, identity_reader=repo_return_identities
            ),
        }
        for view in views
    ]
    identities = _identities(views)
    catalogue_kinds = {}
    unsupported_type_isins = set()
    if clean_projection and views:
        # A catalogue classification may fill a missing source type for this
        # exact ISIN in the sold-out history path. It cannot resolve a source
        # type conflict or reclassify an ordinary current position.
        last_source = max(date.fromisoformat(v["covered_to"]) for v in views)
        last_views = [v for v in views if date.fromisoformat(v["covered_to"]) == last_source]
        present = {
            row["isin"] for view in last_views for row in view["document"].get("positions", ())
        }
        absent = set(identities) - present
        unsupported_type_isins = {
            proposal["isin"]
            for view in views
            for proposal in view.get("proposals", ())
            for observation in proposal.get("observations", ())
            if observation.get("source_type") and observation.get("instrument_type") is None
        }
        if catalogue_outer and absent:
            # MyBroker's positive trade NKD is bond evidence. An absent or zero
            # NKD says nothing about type; REPO and unidentified rows cannot
            # establish it. Conflicting source/catalogue types still block.
            eligible = absent - unsupported_type_isins
            for view in views:
                document = view["document"]
                if (document.get("provider"), document.get("parser")) != (
                    PROVIDER,
                    "mybroker-s1-v2",
                ):
                    continue
                for trade in document.get("trades", ()):
                    isin = trade["core"]["isin"]
                    nkd = _minor(trade.get("accrued_interest"))
                    if (
                        isin in eligible
                        and trade.get("section") == "completed"
                        and trade.get("state") == "settled"
                        and trade.get("identity")
                        and len(trade.get("ids", ())) == 2
                        and not trade.get("repo_observed")
                        and nkd is not None
                        and nkd > 0
                    ):
                        identities[isin]["types"].add("bond")
            catalogue_kinds = dict(
                session.execute(
                    select(Instrument.isin, Instrument.instrument_type).where(
                        Instrument.isin.in_(absent)
                    )
                ).all()
            )
            unknown = {isin for isin in absent if not identities[isin]["types"]}
            for isin in unknown:
                kind = catalogue_kinds.get(isin)
                if kind in {"stock", "bond"} and not any(
                    observation.get("source_type") and observation.get("instrument_type") != kind
                    for view in views
                    for proposal in view.get("proposals", ())
                    if proposal["isin"] == isin
                    for observation in proposal.get("observations", ())
                ):
                    identities[isin]["types"].add(kind)
    event_gaps = []
    native_account = next(iter(native_scope)) if native_scope else None
    from hermes_finance.services.source_return_evidence import (
        analytical_coupon_links,
        historical_payout_evidence,
    )

    retained_proofs = {} if clean_projection else None
    historical_evidence = historical_payout_evidence(
        session, source_account, selected, native_scope, retained_proofs
    )
    analytical_payouts = (
        analytical_coupon_links(
            session, selected, native_scope, historical_evidence=historical_evidence
        )
        if clean_projection
        else None
    )
    if analytical_payouts:
        from hermes_finance.services.source_money_classifications import source_reference

        dates = {
            source_reference(view["id"], row): date.fromisoformat(row["date"])
            for view in views
            for row in view["document"].get("money", [])
        }
        analytical_payouts = {
            ref: isin
            for ref, isin in analytical_payouts.items()
            if not any(
                proof.opening_date < dates[ref] <= proof.closing_date
                and set(proof.coverage["payouts"].reason_codes) & _PDF_PAYOUT_CONFLICTS
                for proof in [
                    *([clean_proofs[isin]] if isin in clean_proofs else []),
                    *(retained_proofs or {}).get(isin, ()),
                ]
            )
        }
    events, references = read_events(
        session,
        views,
        identities,
        native_account or source_account,
        event_gaps,
        historical_evidence=historical_evidence,
        analytical_payouts=analytical_payouts,
    )
    from hermes_finance.services.source_redemption_evidence import apply_verified_redemptions

    events, resolved_redemptions = apply_verified_redemptions(events, redemption_evidence)
    if clean_projection:
        from hermes_finance.services.clean_redemption import apply_clean_redemptions

        events, analytical_redemptions = apply_clean_redemptions(
            session, events, views, cancellation_dates
        )
        resolved_redemptions |= analytical_redemptions
        from hermes_finance.services.clean_sale_nkd import reconcile_sale_nkd

        events = reconcile_sale_nkd(session, events, views)
    from hermes_finance.services.source_monthly_internal_evidence import (
        apply_verified_compensations,
    )

    events = apply_verified_compensations(session, source_account, selected, events)
    resolved_scopes = {
        (e.isin, e.depository_settlement_date.replace(day=1))
        for e in events
        if e.event_key in resolved_redemptions and e.depository_settlement_date is not None
    }
    gaps = [
        gap
        for gap in gaps
        if not (
            gap.code == "custody_cancellation_unresolved"
            and (gap.isin, gap.month) in resolved_scopes
        )
    ]
    income = _income(
        session,
        views,
        identities,
        gaps,
        resolved_redemptions=resolved_redemptions,
        events=events,
        historical_evidence=historical_evidence,
        analytical_payouts=analytical_payouts,
    )
    ambiguous_payouts = {
        ref
        for event in events
        if event.kind in {"COUPON", "DIVIDEND", "UNRESOLVED"}
        and "overlap_money_occurrence_missing" in event.reason_codes
        for ref in event.source_references
    }
    income = tuple(
        row for row in income if not ambiguous_payouts.intersection(row.source_references)
    )
    gaps.extend(
        InstrumentReturnGap(
            "overlap_money_occurrence_missing",
            month=event.event_date.replace(day=1),
            isin=event.isin,
        )
        for event in events
        if "overlap_money_occurrence_missing" in event.reason_codes
        and event.event_date is not None
        and event.attribution_basis != "account_only"
    )
    for gap in event_gaps:
        if gap not in gaps:
            gaps.append(gap)
    return (
        views,
        sources,
        gaps,
        catalogue_kinds,
        unsupported_type_isins,
        events,
        references,
        income,
        native_account,
        retained_proofs,
        identities,
    )


@coherent_read_operation
def read_instrument_returns(
    session,
    *,
    source_account: str,
    isin: str | None = None,
    opening_date: date | None = None,
    closing_date: date | None = None,
    reviewed_bond_valuation=None,
    include_monthly_history: bool = True,
    available_period: bool = False,
    excluded_periods=(),
    clean_projection: bool = False,
) -> SourceInstrumentReturns:
    """Isolate unreadable sources and individual operand gaps; perform no writes.

    Presentation callers may omit the unused monthly/all-time projections.
    Default readers retain the ordinary source and proof semantics. Only the
    clean projection may add its independently validated analytical links.
    """
    from hermes_finance.services.source_bond_valuation import (
        FILE_PATH_KEY,
        load_reviewed_basis,
        resolve_reviewed_basis,
    )
    from hermes_finance.services.source_instrument_events import (
        analyse,
        reconcile_account,
    )

    if (opening_date is None) != (closing_date is None) or (
        opening_date is not None and opening_date >= closing_date
    ):
        raise ValueError("both dates are required, with opening_date < closing_date")
    requested_isin = isin
    selected, native_scope = (
        _source_read_inputs(session, source_account)
        if _SOURCE_SCOPE_READS in session.info
        else _selected_sources(session, source_account)
    )
    from hermes_finance.services.source_investment_proofs import instrument_result
    from hermes_finance.services.source_return_proofs import resolve_proof

    investment = (
        instrument_result(
            session, source_account, selected, requested_isin, opening_date, closing_date
        )
        if clean_projection
        or not available_period
        or (
            opening_date is not None
            and closing_date is not None
            and len(selected) == 1
            and selected[0][0] is not None
            and not selected[0][2]
        )
        else None
    )
    from hermes_finance.services.returns_account_link import account_link

    link = account_link(session, source_account)
    if (
        not clean_projection
        and investment is not None
        and (
            not available_period
            or (
                bool(investment.instruments)
                and not any(gap.code == "investment_proof_stale" for gap in investment.gaps)
            )
        )
    ):
        return replace(investment, account_link=link)
    clean_proofs = (
        {row.isin: row.analysis for row in investment.instruments}
        if clean_projection
        and investment is not None
        and not any(gap.code == "investment_proof_stale" for gap in investment.gaps)
        else {}
    )
    cancellation_dates, _ = resolve_proof(session, source_account, selected, native_scope)

    relevant_cancellation = any(
        (opening_date is None or month <= closing_date and _month_end(month) > opening_date)
        for months in cancellation_dates.values()
        for month in months
    )
    if session.info.get(FILE_PATH_KEY) is not None:
        # The ordinary API and Returns share this path. A configured file is
        # authoritative for this call; failure cannot revive a caller's packet.
        reviewed_bond_valuation = load_reviewed_basis(session, session.info[FILE_PATH_KEY])
    reviewed_basis = resolve_reviewed_basis(selected, native_scope, reviewed_bond_valuation)
    valid_views = [
        v
        for _, v, error in selected
        if not error
        and v is not None
        and native_scope is not None
        and _native_scope(v["document"]) == native_scope
        and source_account in native_scope | {v["document"]["filename_account"]}
    ]
    catalogue_outer = bool(valid_views) and (
        opening_date
        in (
            None,
            min(date.fromisoformat(v["covered_from"]) for v in valid_views) - timedelta(days=1),
        )
        and closing_date in (None, max(date.fromisoformat(v["covered_to"]) for v in valid_views))
    )
    cache = session.info.get(_SOURCE_SCOPE_READS)
    input_key = (
        "instrument_inputs",
        source_account,
        clean_projection,
        relevant_cancellation,
        tuple(sorted(cancellation_dates.items())),
        catalogue_outer,
        reviewed_basis,
        json.dumps(
            {isin: asdict(analysis) for isin, analysis in clean_proofs.items()},
            sort_keys=True,
            default=str,
        ),
    )
    if cache is None or input_key not in cache:
        prepared = _prepare_instrument_inputs(
            session,
            source_account,
            selected,
            native_scope,
            clean_projection=clean_projection,
            clean_proofs=clean_proofs,
            reviewed_basis=reviewed_basis,
            cancellation_dates=cancellation_dates,
            relevant_cancellation=relevant_cancellation,
            catalogue_outer=catalogue_outer,
        )
        if cache is not None:
            cache[input_key] = prepared
    else:
        prepared = cache[input_key]
    (
        views,
        sources,
        gaps,
        catalogue_kinds,
        unsupported_type_isins,
        events,
        references,
        income,
        native_account,
        retained_proofs,
        identities,
    ) = prepared
    instruments = []
    account_analyses = []
    reconciliation = None
    if sources:
        start = min(s.covered_from for s in sources).replace(day=1)
        end = max(s.covered_to for s in sources)
        first = opening_date or min(s.covered_from for s in sources) - timedelta(days=1)
        last = closing_date or max(s.covered_to for s in sources)
        for isin, metadata in sorted(identities.items()):
            if requested_isin is not None and isin != requested_isin:
                continue
            kind = next(iter(metadata["types"])) if len(metadata["types"]) == 1 else None
            name = next(iter(metadata["names"])) if len(metadata["names"]) == 1 else None
            rows = []
            month = start
            while include_monthly_history and month <= end:
                row = _month(
                    session,
                    views,
                    isin,
                    kind,
                    month,
                    income,
                    gaps,
                    rows[-1] if rows else None,
                    reviewed_basis=reviewed_basis,
                    events=events,
                )
                rows.append(row)
                month = _next_month(month)
            rows = [
                replace(
                    row,
                    analysis=analyse(
                        views,
                        isin,
                        kind,
                        row.month - timedelta(days=1),
                        _month_end(row.month),
                        events,
                        references,
                        gaps,
                        reviewed_basis=reviewed_basis,
                    ),
                )
                for row in rows
            ]
            analysis = analyse(
                views,
                isin,
                kind,
                first,
                last,
                events,
                references,
                gaps,
                reviewed_basis=reviewed_basis,
            )
            if clean_projection:
                analysis = _clean_proof_constraints(analysis, clean_proofs.get(isin))
                for proof in (retained_proofs or {}).get(isin, ()):
                    analysis = _clean_historical_position_conflicts(analysis, proof)
                    analysis = _clean_historical_payout_conflicts(analysis, proof)
            outer_analysis = analysis
            if (
                available_period
                and opening_date is None
                and closing_date is None
                and (analysis.pnl.value is None or (first, last) in excluded_periods)
            ):
                from hermes_finance.services.source_instrument_events import endpoint

                dates = {
                    day
                    for view in views
                    for day in (
                        date.fromisoformat(view["covered_from"]) - timedelta(days=1),
                        date.fromisoformat(view["covered_to"]),
                    )
                }
                boundaries = sorted(
                    day
                    for day in dates
                    if endpoint(
                        views, isin, day, kind, reviewed_basis=reviewed_basis
                    ).economic_value_kopecks
                    is not None
                )
                found = None
                conditional = (
                    analysis
                    if (first, last) not in excluded_periods
                    and "unallocated_costs_excluded" in analysis.statement_estimate.assumptions
                    else None
                )
                # Choose the earliest reliable start ending at the latest known
                # valuation. At most one calculation per candidate start.
                candidate_end = boundaries[-1] if boundaries else last
                for candidate_start in boundaries[:-1]:
                    if (candidate_start, candidate_end) in excluded_periods:
                        continue
                    candidate = analyse(
                        views,
                        isin,
                        kind,
                        candidate_start,
                        candidate_end,
                        events,
                        references,
                        gaps,
                        reviewed_basis=reviewed_basis,
                    )
                    if candidate.pnl.value is not None:
                        found = candidate
                        break
                    if conditional is None and (
                        "unallocated_costs_excluded" in candidate.statement_estimate.assumptions
                        and candidate.statement_estimate.pnl.value is not None
                    ):
                        conditional = candidate
                if found is None:
                    found = conditional
                if found is not None:
                    analysis = found
                elif (first, last) in excluded_periods:
                    reason = ("investment_proof_stale",)
                    analysis = replace(
                        analysis,
                        pnl=Metric(None, "unavailable", reason),
                        modified_dietz=replace(
                            analysis.modified_dietz,
                            value=None,
                            status="unavailable",
                            reason_codes=reason,
                        ),
                        statement_estimate=replace(
                            analysis.statement_estimate,
                            pnl=Metric(None, "unavailable", reason),
                            modified_dietz=replace(
                                analysis.statement_estimate.modified_dietz,
                                value=None,
                                status="unavailable",
                                reason_codes=reason,
                            ),
                        ),
                        reason_codes=tuple(sorted(set(analysis.reason_codes) | set(reason))),
                    )
            if clean_projection and analysis is not outer_analysis:
                analysis = _clean_proof_constraints(analysis, clean_proofs.get(isin))
                for proof in (retained_proofs or {}).get(isin, ()):
                    analysis = _clean_historical_position_conflicts(analysis, proof)
                    analysis = _clean_historical_payout_conflicts(analysis, proof)
            # Instrument R2 does not grant account reconciliation/EOD authority.
            account_analyses.append(
                analyse(views, isin, kind, first, last, events, references, gaps)
                if kind == "bond" and reviewed_basis is not None
                else outer_analysis
            )
            if (
                clean_projection
                and isin not in unsupported_type_isins
                and catalogue_kinds.get(isin, kind) == kind
            ):
                from hermes_finance.services.clean_closed_position import infer_closed_position

                analysis = infer_closed_position(analysis, views, isin, kind)
            analysis = replace(
                analysis,
                chained_monthly=chain_monthly(
                    [
                        r.analysis
                        for r in rows
                        if first <= r.analysis.opening_date and r.analysis.closing_date <= last
                    ],
                    analysis.opening_date,
                    analysis.closing_date,
                ),
            )
            instruments.append(
                SourceInstrumentReturn(isin, name, kind, tuple(rows), _all_time(rows), analysis)
            )
        reconciliation = reconcile_account(
            session,
            views,
            first,
            last,
            account_analyses,
            events,
            filtered=requested_isin is not None,
        )
    if instruments:
        from hermes_finance.services.source_investment_proofs import (
            read_latest_display_candidates,
            resolve_display_name,
        )

        # Apply verified whole-history labels only after all financial readers
        # and reconciliation finish. They never enter attribution, endpoints or
        # coverage for this independently requested subinterval.
        display_names = read_latest_display_candidates(
            session, source_account=source_account, requested_isin=requested_isin
        )
        instruments = [
            replace(
                row,
                source_name=resolve_display_name(
                    row.isin,
                    source_labels=identities[row.isin]["names"]
                    | set(display_names["source"].get(row.isin, ())),
                    pdf_labels=display_names["pdf"].get(row.isin, ()),
                ),
            )
            for row in instruments
        ]
    result = SourceInstrumentReturns(
        source_account,
        tuple(instruments),
        income,
        tuple(gaps),
        native_source_account=native_account,
        account_link=link,
        reconciliation=reconciliation,
        unresolved_events=tuple(
            e for e in events if e.isin is None and e.attribution_basis != "account_only"
        ),
        account_reconciliation_events=tuple(
            e for e in events if e.attribution_basis == "account_only"
        ),
    )
    return _with_return_breakdown(result, views)
