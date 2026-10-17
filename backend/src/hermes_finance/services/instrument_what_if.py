"""Request-local, fixed-holding stock HPR. No actual return or write authority."""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal, DecimalException, localcontext

from sqlalchemy import select

from hermes_finance.database import coherent_read_operation
from hermes_finance.domain import RubleAmount
from hermes_finance.persistence import (
    Account,
    BrokerIdentityMapping,
    InKindMovement,
    Instrument,
    InvestmentCashFlow,
    MyBrokerImport,
)
from hermes_finance.services import broker_months
from hermes_finance.services.instrument_eod_observations import instrument_eod_observations
from hermes_finance.services.instrument_trades import known_instrument_trades
from hermes_finance.services.mybroker_corrections import _source_integrity
from hermes_finance.services.mybroker_dispositions import accepted_account_binding, resolve
from hermes_finance.statement_import.mybroker import MyBrokerError

METHOD = "hypothetical-fixed-stock-hpr"
VERSION = 1
ASSUMPTIONS = (
    "no_unobserved_movements",
    "no_unobserved_payouts",
    "no_other_costs_or_taxes",
)
TRADE_UNCERTAINTY = {
    "trade_history_completeness_unknown",
    "financial_coverage_unknown",
    "full_instrument_return_unavailable",
    "inventory_revision_journal_unavailable",
    "no_known_trades_not_zero_activity",
}
PAYOUT_UNCERTAINTY = {"whole_interval_coverage_unknown", "full_instrument_return_unavailable"}
READ_ERRORS = (ValueError, TypeError, KeyError, AttributeError, DecimalException, MyBrokerError)


class ReaderBindingError(ValueError):
    pass


def _bind_readers(eod, trades, account_id, instrument_id, t0, t1):
    for payload, method in (
        (eod, "persisted-instrument-eod-pair"),
        (eod["known_payouts"], "known-booked-net-payouts"),
        (trades, "known-instrument-trades"),
    ):
        if (
            payload["method"],
            payload["version"],
            payload["account"]["id"],
            payload["instrument"]["id"],
            payload["t0"],
            payload["t1"],
            payload["currency"],
        ) != (method, 1, account_id, instrument_id, str(t0), str(t1), "RUB"):
            raise ReaderBindingError
    for boundary, day in ((eod["opening"], t0), (eod["closing"], t1)):
        if (
            boundary["account_id"],
            boundary["instrument_id"],
            boundary["date"],
            boundary["currency"],
        ) != (account_id, instrument_id, str(day), "RUB"):
            raise ReaderBindingError
    if trades["dependency_fingerprint"] is not None or any(
        e["account_id"] != account_id or e["instrument_id"] != instrument_id
        for e in trades["events"]
    ):
        raise ReaderBindingError


def _source_guards(session, account, instrument, t0, t1, quantity):
    """Inspect originals too: absence from the accepted execution list proves nothing.

    This slice cannot independently attribute Money to a stock dividend or waive
    its economic effect. Any scoped Money row therefore blocks, even if another
    reader can display a known subset. This does not change Money authority.
    """
    sources = list(session.scalars(select(MyBrokerImport).order_by(MyBrokerImport.id)))
    aliases = {
        m.provider_identity
        for m in session.scalars(select(BrokerIdentityMapping))
        if m.subject_kind == "account" and m.hermes_account_id == account.id
    }
    parsed = []
    for source in sources:
        try:
            bindings = json.loads(source.mappings_json)
            aliases.update(
                b["identity"]
                for b in bindings
                if b["kind"] == "account" and b["hermes_id"] == account.id
            )
            parsed.append((source, json.loads(source.normalized_json), bindings))
        except READ_ERRORS:
            # An unreadable retained original cannot establish irrelevance.
            return {"source_reader_unavailable"}, []
    blockers, checks, intervals, scoped = set(), [], [], []
    for source, document, bindings in parsed:
        belongs = document.get("filename_account") in aliases or any(
            b["kind"] == "account" and (b["hermes_id"] == account.id or b["identity"] in aliases)
            for b in bindings
        )
        if not belongs:
            continue
        # Retain crossing executions even when the report interval precedes t0.
        target_trades = [
            t for t in document.get("trades", []) if t["core"]["isin"] == instrument.isin
        ]

        def crosses(trade):
            days = [
                trade["core"]["trade_time"][:10],
                trade.get("settlement_date"),
                trade.get("depo_settlement_date"),
            ]
            days = [date.fromisoformat(d) for d in days if d]
            return (
                any(t0 < d <= t1 for d in days)
                or (trade.get("state") == "pending" and min(days) <= t1)
                or min(days) <= t0 < max(days)
            )

        crossing = any(crosses(t) for t in target_trades)
        if not crossing and (source.covered_from > t1 or source.covered_to < t0):
            continue
        reasons = set(document.get("syntax_blockers", [])) | set(document.get("blockers", []))
        reasons.update(document.get("endpoint_blockers", []))
        reasons.update(document.get("endpoint_conflicts", []))
        if not _source_integrity(source, document):
            reasons.add("source_evidence_invalid")
        if document.get("endpoint_basis", {}).get("ending_value") != "covered_to_eod":
            reasons.add("source_eod_basis_unsupported")
        account_aliases = {b["identity"] for b in bindings if b["kind"] == "account"}
        if not account_aliases or any(
            (accepted := accepted_account_binding(session, source, alias)) is None
            or accepted["hermes_id"] != account.id
            for alias in account_aliases
        ):
            reasons.add("source_account_binding_unavailable")
        if any(
            i["isin"] == instrument.isin and i["effective_state"] != "mapped"
            for i in resolve(session, source)
        ):
            reasons.add("source_identity_retired_or_unmapped")
        reasons.update(broker_months._overlap(session, document, account.id))
        if crossing:
            reasons.add("observed_native_movement_or_crossing")
        # Unknown source sections, REPO and opaque transfers remain hard blockers.
        if any(t.get("repo_observed") for t in target_trades):
            reasons.add("repo_observed")
        if source.covered_to > t0:
            intervals.append((source.covered_from, source.covered_to))
            if any(
                r["source_account"] in aliases and t0.isoformat() < r["date"] <= t1.isoformat()
                for r in document.get("money", [])
            ):
                reasons.add("money_economic_effect_unproven")
        positions = [p for p in document.get("positions", []) if p["isin"] == instrument.isin]
        if len(positions) != 1:
            reasons.add("source_fixed_holding_unproven")
        else:
            p = positions[0]
            fields = ["actual_quantity", "forward_quantity"]
            if source.covered_to > t0:
                fields.append("beginning_actual_quantity")
            if any(p.get(f) is None or Decimal(p[f]) != quantity for f in fields):
                reasons.add("source_quantity_changed_or_pending")
        scoped.append((source, document))
        blockers.update(reasons)
        checks.append({"source_import_id": source.id, "reason_codes": sorted(reasons)})
    covered = t0
    for start, end in sorted(intervals):
        if start > covered + timedelta(days=1):
            break
        covered = max(covered, end)
    if covered < t1:
        blockers.add("source_calendar_gap")
    for index, (a, doc_a) in enumerate(scoped):
        for b, doc_b in scoped[index + 1 :]:
            if max(a.covered_from, b.covered_from) <= min(a.covered_to, b.covered_to) and (
                (a.covered_from, a.covered_to) != (b.covered_from, b.covered_to)
                or broker_months._economics(doc_a) != broker_months._economics(doc_b)
            ):
                blockers.add("ambiguous_overlapping_originals")
    return blockers, checks


def _decimal(value):
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


@coherent_read_operation
def instrument_what_if(
    session,
    account_id: int,
    instrument_id: int,
    t0: date,
    t1: date,
    chosen: dict[str, bool],
    request_nonce: str,
):
    if t0 >= t1:
        raise ValueError("t0 must precede t1")
    account, instrument = session.get(Account, account_id), session.get(Instrument, instrument_id)
    if account is None or instrument is None:
        raise LookupError("account or instrument not found")
    blockers, checks = set(), []
    observed = payouts = trades = None
    if instrument.instrument_type == "bond":
        blockers.add("bond_dirty_basis_source_unproven")
    elif instrument.instrument_type != "stock":
        blockers.add("stock_required")
    if instrument.currency != "RUB" or account.account_type not in {"brokerage", "iis"}:
        blockers.add("rub_stock_brokerage_or_iis_required")
    if account.status != "active":
        blockers.add("account_inactive")
    result = fraction = percent = None
    try:
        # #860 calls #858 inside this same outer query-only committed snapshot.
        eod = instrument_eod_observations(session, account_id, instrument_id, t0, t1)
        read_trades = known_instrument_trades(session, account_id, instrument_id, t0, t1)
        _bind_readers(eod, read_trades, account_id, instrument_id, t0, t1)
        payouts, trades = eod["known_payouts"], read_trades
        observed = {k: eod[k] for k in ("opening", "closing", "comparable")}
        a, b = eod["opening"], eod["closing"]
        if eod["comparable"] is not True:
            blockers.add("eod_not_comparable")
        for boundary in (a, b):
            blockers.update(boundary["reason_codes"])
            if boundary["availability"] != "available" or boundary["currentness"] != "current":
                blockers.add("eod_current_source_unavailable")
        if a["quantity"] is None or a["quantity"] != b["quantity"]:
            blockers.add("fixed_positive_quantity_required")
        quantity = Decimal(a["quantity"]) if a["quantity"] is not None else Decimal(0)
        if quantity <= 0:
            blockers.add("fixed_positive_quantity_required")
        blockers.update(set(trades["reason_codes"]) - TRADE_UNCERTAINTY)
        if trades["events"] or trades["status"] != "available":
            blockers.add("known_execution_or_crossing")
        blockers.update(set(payouts["reason_codes"]) - PAYOUT_UNCERTAINTY)
        if not payouts["events"] or not all(
            e["included_in_known_net"] and e["currentness"] == "current" and e["kind"] == "dividend"
            for e in payouts["events"]
        ):
            blockers.add("proven_net_dividend_required")
        for event in payouts["events"]:
            blockers.update(event["reason_codes"])
        if any(
            f.flow_type not in {"coupon", "dividend"}
            for f in session.scalars(
                select(InvestmentCashFlow).where(
                    InvestmentCashFlow.account_id == account_id,
                    InvestmentCashFlow.instrument_id == instrument_id,
                    InvestmentCashFlow.event_date > t0,
                    InvestmentCashFlow.event_date <= t1,
                )
            )
        ):
            blockers.add("principal_or_other_economic_flow")
        if any(
            m.instrument_id in {None, instrument_id}
            for m in session.scalars(
                select(InKindMovement).where(
                    (InKindMovement.source_account_id == account_id)
                    | (InKindMovement.destination_account_id == account_id),
                    InKindMovement.event_date > t0,
                    InKindMovement.event_date <= t1,
                )
            )
        ):
            blockers.add("observed_in_kind_movement")
        source_blockers, checks = _source_guards(session, account, instrument, t0, t1, quantity)
        blockers.update(source_blockers)
        opening = RubleAmount.from_api(a["market_value"]).kopecks if a["market_value"] else 0
        if opening <= 0:
            blockers.add("positive_opening_value_required")
        if not blockers and all(chosen.get(k) is True for k in ASSUMPTIONS):
            net = sum(RubleAmount.from_api(e["booked_net"]).kopecks for e in payouts["events"])
            minor = RubleAmount.from_api(b["market_value"]).kopecks - opening + net
            result = RubleAmount(minor).to_api()
            with localcontext() as ctx:
                ctx.prec = 100
                rate = Decimal(minor) / Decimal(opening)
                fraction, percent = _decimal(rate), _decimal(rate * 100)
    except ReaderBindingError:
        blockers.add("reader_context_mismatch")
    except READ_ERRORS:
        blockers.add("source_reader_unavailable")
        result = fraction = percent = None
    return {
        "method": METHOD,
        "version": VERSION,
        "authority": "hypothetical",
        "request_nonce": request_nonce,
        "account": {"id": account.id, "name": account.name},
        "instrument": {"id": instrument.id, "name": instrument.name},
        "t0": str(t0),
        "t1": str(t1),
        "interval": "(t0,t1]",
        "currency": "RUB",
        "observed": observed,
        "accepted_known": {"payouts": payouts, "trades": trades},
        "chosen_assumptions": {k: chosen.get(k) is True for k in ASSUMPTIONS},
        "missing_assumptions": [k for k in ASSUMPTIONS if chosen.get(k) is not True],
        "hard_blockers": sorted(blockers),
        "source_checks": checks,
        "hypothetical_result": {
            "conditional_result": result,
            "conditional_period_fraction": fraction,
            "conditional_period_percent": percent,
            "percent_unit": "percentage_points",
            "annualized": False,
            "formula": "V1-V0+P",
            "decimal_precision": 100,
        },
        "actual_instrument_return": None,
        "whole_period_completeness": "unknown",
        "dependency_fingerprint": None,
    }
