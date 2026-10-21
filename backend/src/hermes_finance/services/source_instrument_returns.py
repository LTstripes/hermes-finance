"""Read-only native instrument estimates; never financial receipt authority."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, localcontext

from sqlalchemy import select

from hermes_finance.database import coherent_read_operation
from hermes_finance.persistence import ExecutedTrade, SourceIntakeOriginal
from hermes_finance.services import broker_trade_money, source_intake
from hermes_finance.services.broker_statement_provisional import _minor
from hermes_finance.services.source_monthly_returns import (
    SourceReturnGap,
    _money,
    _month_end,
    _native_scope,
    _next_month,
)
from hermes_finance.statement_import.money import normalize_currency
from hermes_finance.statement_import.mybroker import MyBrokerError, digest


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


@dataclass(frozen=True, kw_only=True)
class InstrumentReturnMonth(InstrumentReturnTotals):
    month: date
    opening_quantity: Decimal | None
    closing_quantity: Decimal | None
    opening_value_kopecks: int | None
    closing_value_kopecks: int | None
    intake_ids: tuple[int, ...]


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


@dataclass(frozen=True)
class SourceInstrumentReturns:
    source_account: str
    instruments: tuple[SourceInstrumentReturn, ...]
    income: tuple[InstrumentIncome, ...]
    gaps: tuple[InstrumentReturnGap, ...]
    authority: str = "provisional"
    financial_authority: str = "none"
    currency: str = "RUB"

    def to_dict(self):
        return asdict(self)


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


def _income(session, views, identities, gaps):
    occurrences = defaultdict(list)
    for view in views:
        saved = {r["source_reference"]: r for r in view["money_classifications"]}
        local_gaps = []
        try:
            for key, flow in _money(session, view, None, local_gaps):
                narrative = saved[flow.source_references[0]]
                isin = _attribute(narrative["operation"] + " " + narrative["narrative"], identities)
                occurrences[key].append((flow, isin))
        except (MyBrokerError, ValueError, TypeError, KeyError, ArithmeticError):
            month = date.fromisoformat(view["covered_from"]).replace(day=1)
            while month <= date.fromisoformat(view["covered_to"]):
                gaps.append(InstrumentReturnGap("source_reader_unavailable", view["id"], month))
                month = _next_month(month)
        gaps.extend(InstrumentReturnGap(**asdict(gap)) for gap in local_gaps)
    result = []
    for observations in occurrences.values():
        confirmed = [pair for pair in observations if pair[0].status == "confirmed"]
        selected = confirmed or observations
        flow, isin = selected[0]
        month = flow.event_date.replace(day=1)
        if len({(f.classification, identity) for f, identity in selected}) != 1:
            gaps.append(InstrumentReturnGap("overlap_flow_choice_conflict", month=month))
            continue
        if flow.classification == "unknown":
            gaps.append(InstrumentReturnGap("unrecognized_money", month=month))
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
                InstrumentReturnGap("unattributed_income", month=month, source_reference=refs[0])
            )
    return tuple(sorted(result, key=lambda row: (row.event_date, row.source_references)))


def _endpoint(views, isin, month, *, closing, flags):
    operands = [set(), set()]
    invalid = [False, False]
    boundary = _month_end(month) if closing else month
    for view in views:
        if date.fromisoformat(view["covered_to" if closing else "covered_from"]) != boundary:
            continue
        rows = [row for row in view["document"]["positions"] if row["isin"] == isin]
        if not rows:
            continue  # An absent position row is not affirmative zero.
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
        accepted = session.scalar(
            select(ExecutedTrade).where(ExecutedTrade.source_identity == trade["identity"])
        )
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
    except (ValueError, TypeError, KeyError, ArithmeticError):
        # A malformed proof is no basis; it must not suppress source inference.
        return None


def _inferred_native_total_basis(trade):
    """Infer this MyBroker row's NKD basis using explicit source nominal."""
    try:
        core = trade["core"]
        price = Decimal(core["price"])
        quantity = Decimal(core["quantity"])
        amount = Decimal(core["trade_amount"])
        nkd = Decimal(trade["accrued_interest"])
        face = Decimal(trade["face_value"])
        if (
            any(not value.is_finite() for value in (price, quantity, amount, nkd, face))
            or quantity == 0
            or face <= 0
            or any(value < 0 for value in (price, amount, nkd))
        ):
            return None
        with localcontext() as context:
            # Parser numeric tokens are bounded to 48 characters; keep the
            # product and residual exact, independent of the caller's context.
            context.prec = 200
            principal = price / 100 * face * abs(quantity)
            includes = abs(amount - principal - nkd) <= Decimal("0.01")
            excludes = nkd != 0 and abs(amount - principal) <= Decimal("0.01")
        if includes == excludes:
            return None
        return "includes_paid_nkd" if includes else "excludes_paid_nkd"
    except (ValueError, TypeError, KeyError, ArithmeticError):
        return None


def _bond_total_basis(session, trade, flags):
    reviewed = _native_total_basis(session, trade)
    inferred = _inferred_native_total_basis(trade)
    if reviewed is not None and inferred is not None and reviewed != inferred:
        flags.add("trade_nkd_basis_conflict")
        return None
    return reviewed if reviewed is not None else inferred


def _trade_cash_total(amount, nkd, fee, quantity, basis):
    if basis not in {"includes_paid_nkd", "excludes_paid_nkd"}:
        return None
    total = amount + (nkd if basis == "excludes_paid_nkd" else 0)
    return total + fee if quantity > 0 else total - fee


def _trades(session, views, isin, month, instrument_type, flags):
    groups = defaultdict(list)
    for view in views:
        for trade in view["document"].get("trades", []):
            if trade["core"]["isin"] == isin:
                key = trade.get("identity") or object()
                # Keep unresolved occurrences separate solely to flag their months;
                # they are never eligible for counting or deduplication.
                # A position nominal has no proven validity at the trade date.
                groups[key].append(
                    dict(
                        trade,
                        face_value=(trade.get("face_value") if instrument_type == "bond" else None),
                    )
                )
    buys = sells = 0
    quantity = Decimal(0)
    invalid = False
    for observations in groups.values():
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
            if any(not t.get("identity") or len(t.get("ids", [])) != 2 for t in relevant):
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
                        k: t.get(k)
                        for k in (
                            "settlement_date",
                            "bank_commission",
                            "accrued_interest",
                            "repo_observed",
                            "face_value",
                        )
                    }
                )
                for t in selected
            }
            if len(signatures) != 1:
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
                basis = _bond_total_basis(session, trade, flags)
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
    "unattributed_income",
    "currency_unsupported",
    "classification_missing_legacy_intake",
    "invalid_money_row",
    "invalid_external_flow",
    "unrecognized_money",
    "overlap_flow_choice_conflict",
}
_SOURCE_GAPS = {
    # Structure gaps affect both trades and income; currency/REPO gaps do not.
    "4_Transfers_unsupported",
    "5_UFSR_unsupported",
    "source_reader_unavailable",
    "native_source_scope_ambiguous",
    "unparsed_source_rows",
    "unknown_section",
    "position_row_unclassified",
}
_DISCLOSURES = {"bond_valuation_basis_unknown", "income_assumed", "income_confirmed"}


def _source_gap(code):
    return code in _SOURCE_GAPS


def _month(session, views, isin, instrument_type, month, income, gaps, previous):
    end = _month_end(month)
    relevant = [
        v
        for v in views
        if v["covered_from"] <= month.isoformat() and v["covered_to"] >= end.isoformat()
    ]
    flags = set()
    if not relevant:
        flags.add("missing_month")
    if instrument_type == "bond":
        flags.add("bond_valuation_basis_unknown")
    elif instrument_type != "stock":
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
    price = None if None in (v0, v1, buys, sells) else v1 - v0 - buys + sells
    base = None if None in (v0, buys) else v0 + buys
    total = None if price is None or not income_complete else price + income_total
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


@coherent_read_operation
def read_instrument_returns(session, *, source_account: str) -> SourceInstrumentReturns:
    """Isolate unreadable sources and individual operand gaps; perform no writes."""
    views = []
    sources = []
    gaps = []
    for original in session.scalars(select(SourceIntakeOriginal).order_by(SourceIntakeOriginal.id)):
        try:
            aliases = json.loads(original.native_accounts_json)
            if not isinstance(aliases, list) or source_account not in aliases:
                continue
            sources.append(original)
            view = source_intake.read_intake(session, original.id)
            if _native_scope(view["document"]) != {source_account}:
                raise MyBrokerError("native_source_scope_ambiguous")
            views.append(view)
            month = original.covered_from.replace(day=1)
            while month <= original.covered_to:
                gaps.extend(
                    InstrumentReturnGap(code, original.id, month)
                    for code in (
                        *view["document"].get("syntax_blockers", []),
                        *(
                            code
                            for code in (
                                *view["document"].get("endpoint_blockers", []),
                                *view["document"].get("endpoint_conflicts", []),
                            )
                            if _source_gap(code)
                        ),
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
    identities = _identities(views)
    income = _income(session, views, identities, gaps)
    instruments = []
    if sources:
        start = min(s.covered_from for s in sources).replace(day=1)
        end = max(s.covered_to for s in sources)
        for isin, metadata in sorted(identities.items()):
            kind = next(iter(metadata["types"])) if len(metadata["types"]) == 1 else None
            name = next(iter(metadata["names"])) if len(metadata["names"]) == 1 else None
            rows = []
            month = start
            while month <= end:
                row = _month(
                    session, views, isin, kind, month, income, gaps, rows[-1] if rows else None
                )
                rows.append(row)
                month = _next_month(month)
            instruments.append(
                SourceInstrumentReturn(isin, name, kind, tuple(rows), _all_time(rows))
            )
    return SourceInstrumentReturns(source_account, tuple(instruments), income, tuple(gaps))
