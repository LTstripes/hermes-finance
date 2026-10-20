"""Read-only monthly native-account estimates over saved source-intake observations.

Saved V1 journals do not retain XML narratives or provisional choices. Callers
may reattach exact originals and transient choices; without them Money rows
remain explicit classification gaps. No receipt, finance write or migration.
"""

from __future__ import annotations

import calendar
import json
import re
from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import Literal, Mapping

from sqlalchemy import select

from hermes_finance.database import coherent_read_operation
from hermes_finance.domain.broker_statement_provisional import ProvisionalAssumptions
from hermes_finance.domain.monthly_return_chain import (
    MonthlyReturnRow,
    PeriodReturnTotals,
    calculate_monthly_return_chain,
)
from hermes_finance.persistence import SourceIntakeOriginal
from hermes_finance.services import broker_statement_provisional as provisional
from hermes_finance.services import source_intake
from hermes_finance.services.mybroker_money_candidates import _narratives, _pattern
from hermes_finance.statement_import.mybroker import MyBrokerError, digest


@dataclass(frozen=True)
class SourceReturnGap:
    code: str
    intake_id: int | None = None
    month: date | None = None
    source_reference: str | None = None


@dataclass(frozen=True)
class SourceReturnFlow:
    event_date: date
    amount_kopecks: int
    status: Literal["assumed", "confirmed"]
    included: bool
    source_references: tuple[str, ...]
    classification: str


@dataclass(frozen=True)
class SourceMonthlyReturnRow:
    result: MonthlyReturnRow
    intake_ids: tuple[int, ...]
    flags: tuple[str, ...]
    previous_closing_kopecks: int | None


@dataclass(frozen=True, kw_only=True)
class SourceReturnSegment(PeriodReturnTotals):
    start: date
    end: date
    partial_segment: bool


@dataclass(frozen=True)
class SourceMonthlyReturns:
    source_account: str
    months: tuple[SourceMonthlyReturnRow, ...]
    period: PeriodReturnTotals
    segments: list[SourceReturnSegment]
    flows: tuple[SourceReturnFlow, ...]
    defaults_applied: tuple[SourceReturnFlow, ...]
    gaps: tuple[SourceReturnGap, ...]
    authority: str = "provisional"
    financial_authority: str = "none"
    currency: str = "RUB"
    approximate: bool = True

    def to_dict(self):
        value = asdict(self)
        value["months"] = [
            {
                **asdict(row.result),
                "intake_ids": row.intake_ids,
                "flags": row.flags,
                "previous_closing_kopecks": row.previous_closing_kopecks,
            }
            for row in self.months
        ]
        return value


def _month_end(day):
    return day.replace(day=calendar.monthrange(day.year, day.month)[1])


def _next_month(day):
    return (day.replace(day=28) + timedelta(days=4)).replace(day=1)


def _native_scope(document):
    aliases = {
        row.get("source_account")
        for section in ("positions", "rub_money", "money")
        for row in document.get(section, [])
    }
    for trade in document.get("trades", []):
        aliases.update(provisional._trade_accounts(trade))
    return aliases - {None}


def _saved_totals(document):
    """Apply the provisional native-EOD eligibility rules to saved operands."""
    reasons = set(document.get("endpoint_conflicts", []))
    reasons.update(
        set(document.get("endpoint_blockers", [])) - {"endpoint_beginning_quantity_unavailable"}
    )
    if document.get("endpoint_basis") != {
        "beginning_value": "previous_day_eod",
        "ending_value": "covered_to_eod",
    }:
        reasons.add("provisional_endpoint_basis_unsupported")
    cash = document.get("rub_money", [])
    if len(cash) != 1:
        return None, None, reasons | {"provisional_rub_cash_unavailable"}
    totals = []
    for position_key, cash_key, quantity_key in (
        ("beginning_value", "beginning_amount", "beginning_actual_quantity"),
        ("ending_value", "ending_amount", "actual_quantity"),
    ):
        components = [
            provisional._minor(row.get(position_key)) for row in document.get("positions", [])
        ]
        components.append(provisional._minor(cash[0].get(cash_key)))
        if any(value is None or value < 0 for value in components):
            reasons.add("provisional_endpoint_value_unavailable")
        for row, value in zip(document.get("positions", []), components):
            quantity = row.get(quantity_key)
            if quantity is not None and Decimal(quantity) == 0 and value not in (None, 0):
                reasons.add("provisional_quantity_value_conflict")
        totals.append(sum(value for value in components if value is not None))
    return (None, None, reasons) if reasons else (*totals, reasons)


def _classification(operation, narrative, kind):
    if kind in {"settlement", "commission"}:
        return "internal_trade"
    pattern = _pattern(operation, narrative)
    if pattern == "account_cash_in_candidate":
        return "external_deposit"
    if pattern in {"coupon_paid_candidate", "trade_paid_nkd_candidate"}:
        return "internal_income" if pattern == "coupon_paid_candidate" else "internal_trade"
    if operation == "Перевод" and re.fullmatch(r"в АО [^\r\n]+", narrative):
        return "external_withdrawal"
    if operation == "Внесено/Выведено по распоряжению Клиента":
        return "external_client"
    if operation == "Внесено по распоряжению Клиента":
        return "external_deposit"
    if operation == "Выведено по распоряжению Клиента":
        return "external_withdrawal"
    if operation in {"Купон", "Купоны", "Дивиденды", "Выплата дивидендов"}:
        return "internal_income"
    return None


def _money(view, original, choices, gaps):
    rows = view["document"].get("money", [])
    if original is None:
        narratives = [(None, None, None)] * len(rows)
    else:
        narratives = list(_narratives(original))
    counts = defaultdict(int)
    result = []
    for row, (operation, narrative, _) in zip(rows, narratives, strict=True):
        event_date = date.fromisoformat(row["date"])
        reference = f"money:{view['id']}:money:{row['ordinal']}:{digest(row)}"
        classification = (
            _classification(operation, narrative, row.get("kind"))
            if operation
            else ("internal_trade" if row.get("kind") in {"settlement", "commission"} else None)
        )
        if classification is None:
            gaps.append(
                SourceReturnGap(
                    "money_classification_unavailable"
                    if original is None
                    else "unrecognized_money",
                    view["id"],
                    month=event_date.replace(day=1),
                    source_reference=reference,
                )
            )
            continue
        if not classification.startswith("external_"):
            continue
        amount = provisional._minor(row.get("amount"))
        if classification == "external_client" and amount is not None:
            classification = "external_deposit" if amount > 0 else "external_withdrawal"
        if (
            row.get("currency") != "RUB"
            or amount is None
            or amount == 0
            or (amount > 0) != (classification == "external_deposit")
            or not view["covered_from"] <= row["date"] <= view["covered_to"]
        ):
            gaps.append(
                SourceReturnGap(
                    "invalid_external_flow",
                    view["id"],
                    month=event_date.replace(day=1),
                    source_reference=reference,
                )
            )
            continue
        requirement = f"candidate:{row['ordinal']}:{digest(row)[:12]}"
        selected = (
            [
                choice
                for choice in choices.selections
                if choice.requirement_id == requirement and choice.source_references == (reference,)
            ]
            if choices
            else []
        )
        requested = (
            [choice for choice in choices.selections if choice.requirement_id == requirement]
            if choices
            else []
        )
        if requested and (len(selected) != 1 or len(requested) != 1):
            gaps.append(
                SourceReturnGap(
                    "invalid_assumption_choice",
                    view["id"],
                    month=event_date.replace(day=1),
                    source_reference=reference,
                )
            )
        included, status = True, "assumed"
        if len(selected) == 1:
            if selected[0].choice == "exclude_from_external_schedule":
                included, status = False, "confirmed"
            elif selected[0].choice == "include_as_account_inflow" and amount > 0:
                status = "confirmed"
        signature = digest(
            {key: value for key, value in row.items() if key not in {"ordinal", "last_update"}}
            | {
                "operation": operation,
                "narrative": narrative,
            }
        )
        occurrence = counts[signature]
        counts[signature] += 1
        result.append(
            (
                (signature, occurrence),
                SourceReturnFlow(
                    event_date, amount, status, included, (reference,), classification
                ),
            )
        )
    return result


@coherent_read_operation
def read_monthly_returns(
    session,
    *,
    source_account: str,
    originals: Mapping[int, tuple[bytes, str]] | None = None,
    assumptions: Mapping[int, ProvisionalAssumptions] | None = None,
) -> SourceMonthlyReturns:
    """Read one native account; isolate bad originals/months and retain all gaps.

    Originals/choices, when supplied by a Python caller, are transient and exact
    original verification is delegated to the existing provisional reader.
    V1 has no persisted provisional choices; absence never means confirmation.
    """
    sources = []
    gaps = []
    money = defaultdict(list)
    for original in session.scalars(select(SourceIntakeOriginal).order_by(SourceIntakeOriginal.id)):
        try:
            aliases = json.loads(original.native_accounts_json)
        except (ValueError, TypeError):
            gaps.append(SourceReturnGap("source_membership_unavailable", original.id))
            continue
        if not isinstance(aliases, list) or source_account not in aliases:
            continue
        start, end = original.covered_from, original.covered_to
        try:
            view = source_intake.read_intake(session, original.id)
            if _native_scope(view["document"]) != {source_account}:
                gaps.append(SourceReturnGap("native_source_scope_ambiguous", original.id))
                opening = closing = None
            else:
                opening, closing, reasons = _saved_totals(view["document"])
                gaps.extend(SourceReturnGap(code, original.id) for code in sorted(reasons))
                attached = (originals or {}).get(original.id)
                if attached:
                    context = provisional.read_context(
                        session,
                        intake_id=original.id,
                        original=attached[0],
                        filename=attached[1],
                        expected_manifest_digest=view["manifest_digest"],
                    )
                    opening = (
                        int(context.observed.total_opening_kopecks)
                        if context.observed.total_opening_kopecks is not None
                        else None
                    )
                    closing = (
                        int(context.observed.total_closing_kopecks)
                        if context.observed.total_closing_kopecks is not None
                        else None
                    )
                    gaps.extend(
                        SourceReturnGap(code, original.id) for code in context.hard_blockers
                    )
                for key, flow in _money(
                    view,
                    attached[0] if attached else None,
                    (assumptions or {}).get(original.id),
                    gaps,
                ):
                    money[key].append(flow)
        except (MyBrokerError, ValueError, TypeError, KeyError, ArithmeticError):
            opening = closing = None
            gaps.append(SourceReturnGap("source_reader_unavailable", original.id))
        if start.day != 1 or end != _month_end(end):
            gaps.append(SourceReturnGap("partial_month_source", original.id))
            continue
        sources.append((original.id, start, end, opening, closing))

    flows = []
    for observations in money.values():
        confirmed = [flow for flow in observations if flow.status == "confirmed"]
        selected = confirmed or observations
        if len({flow.included for flow in selected}) != 1:
            gaps.append(
                SourceReturnGap(
                    "overlap_flow_choice_conflict", month=selected[0].event_date.replace(day=1)
                )
            )
            continue
        flow = selected[0]
        refs = tuple(ref for item in observations for ref in item.source_references)
        flows.append(replace(flow, source_references=refs))
        if len(observations) > 1:
            gaps.append(SourceReturnGap("overlap_flow_deduplicated", source_reference=refs[0]))
    flows.sort(key=lambda flow: (flow.event_date, flow.source_references))
    schedule = [
        (flow.event_date, flow.amount_kopecks, flow.status) for flow in flows if flow.included
    ]
    if not sources:
        empty = calculate_monthly_return_chain([], [])
        return SourceMonthlyReturns(
            source_account,
            (),
            empty.period,
            [],
            tuple(flows),
            tuple(f for f in flows if f.status == "assumed"),
            tuple(gaps),
        )

    uncertain_months = {
        gap.month
        for gap in gaps
        if gap.code
        in {
            "money_classification_unavailable",
            "unrecognized_money",
            "invalid_external_flow",
            "invalid_assumption_choice",
            "overlap_flow_choice_conflict",
        }
    }
    rows = []
    month = min(source[1] for source in sources)
    last = max(source[2] for source in sources)
    previous_closing = None
    while month <= last:
        end = _month_end(month)
        relevant = [source for source in sources if source[1] <= month and source[2] >= end]

        def endpoint(index, matches):
            values = {
                source[index]
                for source in relevant
                if matches(source) and source[index] is not None
            }
            if len(values) > 1:
                gaps.append(SourceReturnGap("overlapping_endpoint_conflict", month=month))
            return next(iter(values)) if len(values) == 1 else None

        opening = endpoint(3, lambda source: source[1] == month)
        closing = endpoint(4, lambda source: source[2] == end)
        calculated = calculate_monthly_return_chain(
            [(month - timedelta(days=1), opening), (end, closing)], schedule
        ).months[0]
        if month in uncertain_months:
            calculated = replace(
                calculated,
                contributions_kopecks=None,
                withdrawals_kopecks=None,
                growth_kopecks=None,
                modified_dietz_return=None,
                reason_codes=(*calculated.reason_codes, "unknown_flow"),
            )
        flags = list(calculated.reason_codes)
        if opening is not None and previous_closing is not None and opening != previous_closing:
            flags.append("seam_mismatch")
        gaps.extend(SourceReturnGap(code, month=month) for code in flags)
        rows.append(
            SourceMonthlyReturnRow(
                calculated, tuple(s[0] for s in relevant), tuple(flags), previous_closing
            )
        )
        previous_closing = closing
        month = _next_month(month)
    period = _period_totals(rows, schedule, uncertain_months)
    groups = []
    current = []
    for row in rows:
        if row.result.missing_endpoint:
            if current:
                groups.append(current)
                current = []
        else:
            current.append(row)
    if current:
        groups.append(current)
    partial = len(groups) > 1 or period.missing_endpoint or bool(period.chain_reason_codes)
    segments = [
        SourceReturnSegment(
            start=group[0].result.opening_date,
            end=group[-1].result.closing_date,
            partial_segment=partial,
            **asdict(_period_totals(group, schedule, uncertain_months)),
        )
        for group in groups
    ]
    return SourceMonthlyReturns(
        source_account,
        tuple(rows),
        period,
        segments,
        tuple(flows),
        tuple(f for f in flows if f.status == "assumed"),
        tuple(gaps),
    )


def _period_totals(rows, schedule, uncertain_months):
    """Use native monthly endpoints/rates and retain unknown-flow blockers."""
    boundaries = [(rows[0].result.opening_date, rows[0].result.opening_kopecks)] + [
        (row.result.closing_date, row.result.closing_kopecks) for row in rows
    ]
    period = calculate_monthly_return_chain(boundaries, schedule).period
    chain_reasons = tuple(
        dict.fromkeys(reason for row in rows for reason in row.result.reason_codes)
    )
    with localcontext() as ctx:
        ctx.prec = 60
        ctx.rounding = ROUND_HALF_UP
        chain = Decimal(1)
        for row in rows:
            if row.result.modified_dietz_return is not None:
                chain *= 1 + row.result.modified_dietz_return
        chained_return = None if chain_reasons else chain - 1
    period = replace(
        period,
        chained_return=chained_return,
        chain_reason_codes=chain_reasons,
        missing_endpoint=any(row.result.missing_endpoint for row in rows),
    )
    if any(row.result.closing_date.replace(day=1) in uncertain_months for row in rows):
        period = replace(
            period,
            contributions_kopecks=None,
            withdrawals_kopecks=None,
            growth_kopecks=None,
            xirr_annualized_return=None,
            xirr_period_return=None,
            growth_reason_codes=tuple(dict.fromkeys((*period.growth_reason_codes, "unknown_flow"))),
            xirr_reason_codes=tuple(dict.fromkeys((*period.xirr_reason_codes, "unknown_flow"))),
        )
    return period
