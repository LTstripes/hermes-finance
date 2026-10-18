"""Read-only conditional result for one instrument from durable source intake.

Journal-only provenance: the original's own native facts supply the observed
position values and quantity control; accepted #858 payouts and #862 executions
are reused for distributions and confirmed cash legs when an instrument identity
exists. No strict receipt, financial Apply or second money ledger is required to
display a visibly hypothetical number. Unknown semantics stay NULL with a finite
reason: absence is never zero, embedded taxes/fees are never subtracted twice
and no bond NKD basis is invented. Actual instrument performance remains
unavailable.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal, DecimalException, InvalidOperation, localcontext

from sqlalchemy import select

from hermes_finance.database import coherent_read_operation
from hermes_finance.domain import RubleAmount
from hermes_finance.persistence import (
    Account,
    InKindMovement,
    Instrument,
    InvestmentCashFlow,
    SourceIntakeOriginal,
    SourceIntakeRevision,
)
from hermes_finance.services import broker_months, source_intake
from hermes_finance.services.instrument_cash_income import known_instrument_cash_income
from hermes_finance.services.instrument_trades import known_instrument_trades
from hermes_finance.services.instrument_what_if import (
    PAYOUT_UNCERTAINTY,
    TRADE_UNCERTAINTY,
)
from hermes_finance.statement_import.mybroker import MyBrokerError
from hermes_finance.statement_import.mybroker_identity import ISIN as ISIN_PATTERN

METHOD = "source-intake-fixed-holding-result"
VERSION = 1
AUTHORITY = "hypothetical"
INTERVAL = "(t0,t1]"
ASSUMPTIONS = (
    "no_unobserved_movements",
    "no_unobserved_payouts",
    "no_other_costs_or_taxes",
)
MAX_MINOR = 2**63 - 1
READ_ERRORS = (MyBrokerError, ValueError, TypeError, KeyError, AttributeError, DecimalException)


def _decimal(value: Decimal) -> str:
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _kopecks(value, reasons: set[str], missing_code: str) -> int | None:
    """Scale a source value exactly; a fractional kopeck is never rounded away."""
    if value is None:
        reasons.add(missing_code)
        return None
    try:
        number = Decimal(value)
        if not number.is_finite():
            raise InvalidOperation
        with localcontext() as context:
            context.prec = max(32, len(number.as_tuple().digits) + 4)
            scaled = number * 100
            if scaled != scaled.to_integral_value():
                reasons.add("fractional_kopeck")
                return None
            if scaled < 0 or scaled > MAX_MINOR:
                reasons.add("amount_out_of_bounds")
                return None
            return int(scaled)
    except (InvalidOperation, ValueError, TypeError, DecimalException):
        reasons.add("source_decimal_invalid")
        return None


def _quantity(value, reasons: set[str], missing_code: str) -> Decimal | None:
    if value is None:
        reasons.add(missing_code)
        return None
    try:
        number = Decimal(value)
    except (InvalidOperation, ValueError, TypeError, DecimalException):
        reasons.add("source_decimal_invalid")
        return None
    if not number.is_finite():
        reasons.add("source_decimal_invalid")
        return None
    return number


def _observation_ref(view, section: str, index: int | None):
    if index is None:
        return None
    for observation in view["observations"]:
        if observation["section"] == section and observation["ordinal"] == index:
            return {
                "ordinal": observation["ordinal"],
                "locator": observation["locator"],
                "row_fingerprint": observation["row_fingerprint"],
            }
    return None


def _position_economics(position) -> list[str]:
    """Type-safe comparison key; a missing source value is never a numeric zero."""
    return [
        "" if position.get(field) is None else str(position[field])
        for field in ("actual_quantity", "beginning_value", "ending_value")
    ]


def _source_controls(document) -> set[str]:
    """Accepted cash and quantity-movement controls for the raw retained original.

    Trade readiness is not claimed here: the stored manifest source is raw
    parser output without enriched trade blockers, and any observed trade
    already blocks the fixed-holding total with its own finite reason. The
    quantity movement and cash formulas follow `broker_months._controls`.
    """
    reasons: set[str] = set()
    positions = document.get("positions", [])
    if not positions:
        reasons.add("security_inventory_unproven")
    cash = document.get("rub_money", [])
    if len(cash) == 1 and all(
        cash[0].get(field) is not None for field in ("beginning_amount", "ending_amount")
    ):
        try:
            posted = sum(
                (
                    broker_months._minor(row.get("amount"), signed=True)
                    for row in document.get("money", [])
                ),
                0,
            )
            delta = (
                broker_months._minor(cash[0]["ending_amount"])
                - broker_months._minor(cash[0]["beginning_amount"])
                - posted
            )
        except (MyBrokerError, ValueError, TypeError, DecimalException):
            reasons.add("source_decimal_invalid")
        else:
            if delta != 0:
                reasons.add("cash_control_mismatch")
    else:
        reasons.add("rub_money_incomplete")
    for position in positions:
        if position.get("beginning_actual_quantity") is None:
            reasons.add("quantity_control_unavailable")
            continue
        try:
            with localcontext() as context:
                context.prec = 100
                movement = sum(
                    (
                        Decimal(trade["core"]["quantity"])
                        for trade in document.get("trades", [])
                        if trade["core"]["source_account"] == position["source_account"]
                        and trade["core"]["isin"] == position["isin"]
                        and trade["state"] == "settled"
                        and trade.get("depo_settlement_date") is not None
                        and document["covered_from"]
                        <= trade["depo_settlement_date"]
                        <= document["covered_to"]
                    ),
                    Decimal(0),
                )
                delta = (
                    Decimal(position["actual_quantity"])
                    - Decimal(position["beginning_actual_quantity"])
                    - movement
                )
        except (MyBrokerError, ValueError, TypeError, KeyError, DecimalException):
            reasons.add("source_decimal_invalid")
        else:
            if delta != 0:
                reasons.add("quantity_control_mismatch")
    return reasons


def _journal_state(session, original_id: int):
    row = session.scalar(
        select(SourceIntakeRevision)
        .where(SourceIntakeRevision.original_id == original_id)
        .order_by(SourceIntakeRevision.seq.desc())
        .limit(1)
    )
    if row is None:
        return None
    try:
        return json.loads(row.payload_json).get("state")
    except (ValueError, TypeError, AttributeError):
        return None


def _manifest_source(session, original_id: int):
    row = session.scalar(
        select(SourceIntakeRevision)
        .where(
            SourceIntakeRevision.original_id == original_id,
            SourceIntakeRevision.operation == "manifest",
        )
        .order_by(SourceIntakeRevision.seq)
        .limit(1)
    )
    if row is None:
        return None
    try:
        return json.loads(row.payload_json)["manifest"]["source"]
    except (ValueError, TypeError, KeyError, AttributeError):
        return None


def _overlap_blockers(session, original, account_id, isin, economics) -> set[str]:
    """An overlapping same-account original must agree or the interval is ambiguous."""
    reasons = set()
    for row in session.scalars(select(SourceIntakeOriginal).order_by(SourceIntakeOriginal.id)):
        if row.id == original.id:
            continue
        if row.covered_to < original.covered_from or row.covered_from > original.covered_to:
            continue
        state = _journal_state(session, row.id)
        if state is None:
            reasons.add("source_intake_journal_invalid")
            continue
        if state.get("account_id") != account_id:
            continue
        document = _manifest_source(session, row.id)
        if document is None:
            reasons.add("source_intake_journal_invalid")
            continue
        rows = [p for p in document.get("positions", []) if p["isin"] == isin]
        other = sorted(_position_economics(p) for p in rows)
        same_range = (row.covered_from, row.covered_to) == (
            original.covered_from,
            original.covered_to,
        )
        if not same_range or other != economics:
            reasons.add("ambiguous_overlapping_originals")
    return reasons


def _confirmed_cost_legs(trades) -> list[dict]:
    if trades is None:
        return []
    legs = []
    for event in trades["events"]:
        for leg in event["cash_legs"]:
            if leg["role"] not in {"commission", "paid_nkd"}:
                continue
            if leg["proof_class"] != "effective_cash_leg_authority":
                continue
            legs.append(
                {
                    "trade_id": event["trade_id"],
                    "role": leg["role"],
                    "signed_rub": leg["signed_rub"],
                    "effective_date": leg["effective_date"],
                    "in_interval": leg["in_interval"],
                    "receipt_id": leg["receipt_id"],
                }
            )
    return legs


def _distributions(payouts) -> tuple[str | None, list[str]]:
    """P is the exact supported net dividend sum once, or NULL with reasons."""
    if payouts is None:
        return None, ["instrument_identity_unmapped"]
    events = payouts["events"]
    if not events:
        return None, ["no_observed_events"]
    if not all(
        event["included_in_known_net"]
        and event["currentness"] == "current"
        and event["kind"] == "dividend"
        for event in events
    ):
        return None, ["proven_net_dividend_required"]
    minor = sum(RubleAmount.from_api(event["booked_net"]).kopecks for event in events)
    return RubleAmount(minor).to_api(), []


@coherent_read_operation
def source_intake_instrument_result(
    session,
    intake_id: int,
    isin: str,
    chosen: dict[str, bool],
    request_nonce: str,
):
    if not ISIN_PATTERN.fullmatch(isin):
        raise ValueError("isin_invalid")
    view = source_intake.read_intake(session, intake_id)
    original = session.get(SourceIntakeOriginal, intake_id)
    state = view["state"]
    document = view["document"]
    covered_from = date.fromisoformat(view["covered_from"])
    covered_to = date.fromisoformat(view["covered_to"])
    t0, t1 = covered_from - timedelta(days=1), covered_to

    blockers: set[str] = set()
    observed_reasons: set[str] = set()
    account = None
    account_id = state.get("account_id")
    if account_id is None:
        blockers.add("source_intake_not_bound")
    else:
        account = session.get(Account, account_id)
        if account is None:
            blockers.add("source_intake_account_missing")
        else:
            if account.status != "active":
                blockers.add("account_inactive")
            if account.account_type not in {"brokerage", "iis"}:
                blockers.add("brokerage_or_iis_required")

    proposals = [p for p in view["proposals"] if p["isin"] == isin]
    if len(proposals) != 1:
        blockers.add(
            "source_intake_instrument_absent"
            if not proposals
            else "source_intake_instrument_ambiguous"
        )
    proposal = proposals[0] if len(proposals) == 1 else None

    instrument = None
    if proposal is not None:
        assessment = proposal["currency_assessment"]
        if assessment["effective_currency"] is None:
            blockers.add("source_intake_currency_unproven")
        elif assessment["effective_currency"] != "RUB":
            blockers.add("source_intake_currency_unsupported")
        if assessment["basis"] == "conflict":
            blockers.add("source_intake_currency_conflict")
        instrument_type = proposal["instrument_type"]
        if instrument_type == "bond":
            blockers.add("bond_dirty_basis_source_unproven")
        elif instrument_type != "stock":
            blockers.add("stock_required")
        if isin in state.get("deferred_isins", []):
            blockers.add("source_intake_identity_deferred")
        blockers.update(proposal.get("review_reasons", []))
        if proposal["hermes_id"] is not None:
            instrument = session.get(Instrument, proposal["hermes_id"])
            if (
                instrument is None
                or instrument.isin != isin
                or instrument.instrument_type != instrument_type
            ):
                instrument = None
                blockers.add("instrument_identity_mismatch")
            elif instrument.currency != "RUB":
                blockers.add("instrument_currency_unsupported")
        else:
            blockers.add("instrument_identity_unmapped")

    blockers.update(document.get("syntax_blockers", []))
    blockers.update(document.get("endpoint_conflicts", []))
    blockers.update(document.get("endpoint_blockers", []))
    # The accepted cash and quantity-movement controls are recomputed for the
    # retained original; trade readiness is not claimed (see _source_controls).
    try:
        blockers.update(_source_controls(document))
        blockers.update(
            _overlap_blockers(
                session,
                original,
                account_id,
                isin,
                sorted(_position_economics(p) for p in document["positions"] if p["isin"] == isin),
            )
        )
    except READ_ERRORS:
        blockers.add("source_reader_unavailable")

    rows = [(index, p) for index, p in enumerate(document["positions"]) if p["isin"] == isin]
    position = rows[0][1] if len(rows) == 1 else None
    position_index = rows[0][0] if len(rows) == 1 else None
    if position is None:
        observed_reasons.add("source_fixed_holding_unproven")
    beginning_quantity = actual_quantity = forward_quantity = None
    value_change = v0 = v1 = None
    fraction = percent = None
    if position is not None:
        beginning_quantity = _quantity(
            position.get("beginning_actual_quantity"),
            observed_reasons,
            "beginning_quantity_unavailable",
        )
        actual_quantity = _quantity(
            position.get("actual_quantity"), observed_reasons, "quantity_unavailable"
        )
        forward_quantity = _quantity(
            position.get("forward_quantity"), observed_reasons, "forward_quantity_unavailable"
        )
        if (
            beginning_quantity is not None
            and actual_quantity is not None
            and forward_quantity is not None
        ):
            if forward_quantity != actual_quantity:
                observed_reasons.add("endpoint_unsettled")
            if beginning_quantity != actual_quantity:
                observed_reasons.add("quantity_changed_not_profit")
                observed_reasons.add("changing_quantity_result_unavailable")
            if actual_quantity <= 0:
                observed_reasons.add("fixed_positive_quantity_required")
        v0 = _kopecks(
            position.get("beginning_value"), observed_reasons, "beginning_value_unavailable"
        )
        v1 = _kopecks(position.get("ending_value"), observed_reasons, "ending_value_unavailable")
        if v0 is not None and v1 is not None:
            value_change = v1 - v0
            if v0 <= 0:
                observed_reasons.add("positive_opening_value_required")
            else:
                with localcontext() as context:
                    context.prec = 100
                    rate = Decimal(value_change) / Decimal(v0)
                    fraction, percent = _decimal(rate), _decimal(rate * 100)
    observed_available = (
        position is not None
        and beginning_quantity is not None
        and actual_quantity is not None
        and forward_quantity is not None
        and v0 is not None
        and v1 is not None
    )
    blockers.update(observed_reasons)

    instrument_trades = [t for t in document.get("trades", []) if t["core"]["isin"] == isin]
    if instrument_trades:
        blockers.add("observed_native_movement_or_crossing")
        blockers.add("changing_quantity_result_unavailable")
    if any(t.get("repo_observed") for t in instrument_trades):
        blockers.add("repo_observed")
    if document.get("money"):
        # A stock dividend could hide in an unclassified posting; this slice has
        # no authority to attribute or waive any scoped Money row.
        blockers.add("money_economic_effect_unproven")

    payouts = trades = None
    if instrument is not None and account is not None:
        try:
            payouts = known_instrument_cash_income(session, account_id, instrument.id, t0, t1)
            blockers.update(set(payouts["reason_codes"]) - PAYOUT_UNCERTAINTY)
            for event in payouts["events"]:
                blockers.update(event["reason_codes"])
            if not payouts["events"] or not all(
                event["included_in_known_net"]
                and event["currentness"] == "current"
                and event["kind"] == "dividend"
                for event in payouts["events"]
            ):
                blockers.add("proven_net_dividend_required")
            trades = known_instrument_trades(session, account_id, instrument.id, t0, t1)
            blockers.update(set(trades["reason_codes"]) - TRADE_UNCERTAINTY)
            if trades["events"] or trades["status"] != "available":
                blockers.add("known_execution_or_crossing")
            if any(
                flow.flow_type not in {"coupon", "dividend"}
                for flow in session.scalars(
                    select(InvestmentCashFlow).where(
                        InvestmentCashFlow.account_id == account_id,
                        InvestmentCashFlow.instrument_id == instrument.id,
                        InvestmentCashFlow.event_date > t0,
                        InvestmentCashFlow.event_date <= t1,
                    )
                )
            ):
                blockers.add("principal_or_other_economic_flow")
            if any(
                movement.instrument_id in {None, instrument.id}
                for movement in session.scalars(
                    select(InKindMovement).where(
                        (InKindMovement.source_account_id == account_id)
                        | (InKindMovement.destination_account_id == account_id),
                        InKindMovement.event_date > t0,
                        InKindMovement.event_date <= t1,
                    )
                )
            ):
                blockers.add("observed_in_kind_movement")
        except READ_ERRORS:
            blockers.add("source_reader_unavailable")
            payouts = trades = None

    net_distributions, distribution_reasons = _distributions(payouts)
    result = result_fraction = result_percent = None
    if (
        not blockers
        and all(chosen.get(key) is True for key in ASSUMPTIONS)
        and value_change is not None
        and net_distributions is not None
        and v0 is not None
        and v0 > 0
    ):
        minor = value_change + RubleAmount.from_api(net_distributions).kopecks
        result = RubleAmount(minor).to_api()
        with localcontext() as context:
            context.prec = 100
            rate = Decimal(minor) / Decimal(v0)
            result_fraction, result_percent = _decimal(rate), _decimal(rate * 100)

    instrument_type = proposal["instrument_type"] if proposal is not None else None
    return {
        "method": METHOD,
        "version": VERSION,
        "authority": AUTHORITY,
        "request_nonce": request_nonce,
        "intake": {
            "id": view["id"],
            "head_seq": view["head_seq"],
            "manifest_digest": view["manifest_digest"],
            "document_sha256": view["document_sha256"],
            "covered_from": view["covered_from"],
            "covered_to": view["covered_to"],
            "finance_link": "present" if view["finance_link"] else "absent",
            "exceptions": view["exceptions"],
        },
        "account": {"id": account.id, "name": account.name} if account else None,
        "instrument": {
            "isin": isin,
            "instrument_type": instrument_type,
            "hermes_id": proposal["hermes_id"] if proposal is not None else None,
            "name": instrument.name if instrument is not None else None,
        },
        "currency_assessment": {
            "observed_denomination": proposal["currency_assessment"]["observed_denomination"]
            if proposal is not None
            else None,
            "effective_currency": proposal["currency_assessment"]["effective_currency"]
            if proposal is not None
            else None,
            "basis": proposal["currency_assessment"]["basis"] if proposal is not None else None,
            "provisional": proposal["currency_assessment"]["provisional"]
            if proposal is not None
            else None,
        },
        "t0": t0.isoformat(),
        "t1": t1.isoformat(),
        "interval": INTERVAL,
        "currency": "RUB",
        "observed": {
            "availability": "available" if observed_available else "unavailable",
            "quantity": format(actual_quantity.normalize(), "f")
            if actual_quantity is not None
            else None,
            "beginning_quantity": format(beginning_quantity.normalize(), "f")
            if beginning_quantity is not None
            else None,
            "forward_quantity": format(forward_quantity.normalize(), "f")
            if forward_quantity is not None
            else None,
            "beginning_value": RubleAmount(v0).to_api() if v0 is not None else None,
            "ending_value": RubleAmount(v1).to_api() if v1 is not None else None,
            "beginning_basis": "previous_day_eod",
            "ending_basis": "covered_to_eod",
            "value_change": RubleAmount(value_change).to_api()
            if value_change is not None
            else None,
            "value_change_fraction": fraction,
            "value_change_percent": percent,
            "bond_nkd_basis": "not_applicable" if instrument_type == "stock" else "unknown",
            "source_row": _observation_ref(view, "positions", position_index),
            "reason_codes": sorted(observed_reasons),
        },
        "known": {
            "payouts": payouts,
            "trades": trades,
            "net_distributions": net_distributions,
            "confirmed_cost_legs": _confirmed_cost_legs(trades),
            "cost_coverage": "unknown",
            "reason_codes": sorted(
                set(distribution_reasons)
                | blockers.intersection(
                    {
                        "money_economic_effect_unproven",
                        "observed_native_movement_or_crossing",
                        "known_execution_or_crossing",
                    }
                )
            ),
        },
        "chosen_assumptions": {key: chosen.get(key) is True for key in ASSUMPTIONS},
        "missing_assumptions": [key for key in ASSUMPTIONS if chosen.get(key) is not True],
        "hard_blockers": sorted(blockers),
        "hypothetical_result": {
            "conditional_result": result,
            "conditional_period_fraction": result_fraction,
            "conditional_period_percent": result_percent,
            "percent_unit": "percentage_points",
            "annualized": False,
            "formula": "V1-V0+P",
            "decimal_precision": 100,
        },
        "actual_instrument_return": None,
        "whole_period_completeness": "unknown",
        "dependency_fingerprint": None,
    }
