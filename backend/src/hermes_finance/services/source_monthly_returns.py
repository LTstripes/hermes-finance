"""Read-only provisional monthly estimates over persisted source money choices."""

from __future__ import annotations

import calendar
import hashlib
import json
from collections import defaultdict
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import Literal, Mapping

from sqlalchemy import select

from hermes_finance.database import coherent_read_operation, coherent_read_snapshot
from hermes_finance.domain.broker_statement_provisional import ProvisionalAssumptions
from hermes_finance.domain.monthly_return_chain import (
    MonthlyReturnRow,
    PeriodReturnTotals,
    calculate_monthly_return_chain,
)
from hermes_finance.persistence import SourceIntakeOriginal, SourceMoneyClassification
from hermes_finance.services import broker_statement_provisional as provisional
from hermes_finance.services import source_intake
from hermes_finance.services.source_money_classifications import (
    is_broker_transfer,
    source_reference,
    transfer_classification,
)
from hermes_finance.statement_import.money import normalize_currency
from hermes_finance.statement_import.mybroker import MyBrokerError, digest
from hermes_finance.statement_import.mybroker_return_structure import (
    original_cancellation_dates,
    source_return_blockers,
)


@coherent_read_operation
def read_monthly_returns_with_originals(session, *, source_account, documents, expected_sources):
    """Transient evidence for ALL selected journals; never a source-exclusion API."""
    _, originals = verified_originals(
        session,
        source_account=source_account,
        documents=documents,
        expected_sources=expected_sources,
    )
    return read_monthly_returns(session, source_account=source_account, originals=originals)


def verified_originals(session, *, source_account, documents, expected_sources):
    """Shared exact-original verification, without calculating or saving anything."""
    selected, _ = _selected_sources(session, source_account)
    if not selected or any(error for _, _, error in selected):
        raise MyBrokerError("source_return_original_scope_unavailable")
    current = {row.id: view["manifest_digest"] for row, view, _ in selected}
    if current != expected_sources:
        raise MyBrokerError("source_return_original_set_stale")
    by_sha = {}
    for document, filename in documents:
        sha = hashlib.sha256(document).hexdigest()
        if sha in by_sha:
            raise MyBrokerError("source_return_duplicate_original")
        by_sha[sha] = (document, filename)
    if set(by_sha) != {row.document_sha256 for row, _, _ in selected}:
        raise MyBrokerError("source_return_original_set_mismatch")
    originals = {}
    for row, view, _ in selected:
        document, filename = by_sha[row.document_sha256]
        # Verify the immutable descriptor and frozen parser shape before the
        # ordinary reader's per-document error isolation can catch anything.
        provisional.read_context(
            session,
            intake_id=row.id,
            original=document,
            filename=filename,
            expected_manifest_digest=view["manifest_digest"],
        )
        originals[row.id] = (document, filename)
    return selected, originals


SOURCE_PERIOD_INFERRED_MESSAGE = (
    "Statement period was inferred from activity dates; "
    "opening and closing balance dates are unverified."
)

# These structural gaps can hide financial events even when parsed Money is empty.
# Endpoint-only limitations and non-financial intake statuses are separate.
_FINANCIAL_COMPLETENESS_BLOCKERS = {
    "unparsed_source_rows",
    "unknown_section",
    "4_Transfers_unsupported",
    "5_UFSR_unsupported",
    "position_row_unclassified",
    "custody_cancellation_unresolved",
}
_FLOW_REASONS = _FINANCIAL_COMPLETENESS_BLOCKERS | {
    "source_period_inferred",
    "unknown_flow",
    "currency_unsupported",
    "flow_coverage_gap",
}


def _flow_coverage_complete(sources, start, end):
    """Check the union of statement date ranges, independent of valuations."""
    cursor = start
    for _, covered_from, covered_to, _, _ in sorted(sources, key=lambda source: source[1]):
        if covered_to < cursor:
            continue
        if covered_from > cursor:
            return False
        if covered_to >= end:
            return True
        cursor = covered_to + timedelta(days=1)
    return False


@dataclass(frozen=True)
class SourceReturnGap:
    code: str
    intake_id: int | None = None
    month: date | None = None
    source_reference: str | None = None
    message: str | None = None


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
    coupons_kopecks: int | None
    dividends_kopecks: int | None
    income_assumptions_used: bool


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
    source_proof: dict | None = None

    def to_dict(self):
        value = asdict(self)
        value["months"] = [
            {
                **asdict(row.result),
                "intake_ids": row.intake_ids,
                "flags": row.flags,
                "previous_closing_kopecks": row.previous_closing_kopecks,
                "coupons_kopecks": row.coupons_kopecks,
                "dividends_kopecks": row.dividends_kopecks,
                "income_assumptions_used": row.income_assumptions_used,
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


_SOURCE_READ_VIEWS = "returns_source_read_views"


@contextmanager
def source_read_snapshot(session):
    """Reuse verified source views only within this committed read snapshot.

    No value survives a request, including failed reads. Copies keep consumers
    from changing another reader's operands. Financial writers never use this.
    """
    with coherent_read_snapshot(session):
        if _SOURCE_READ_VIEWS in session.info:
            yield
            return
        session.info[_SOURCE_READ_VIEWS] = {}
        try:
            yield
        finally:
            session.info.pop(_SOURCE_READ_VIEWS, None)


def _read_source_view(session, original, *, reserved):
    if reserved:
        return source_intake._view(session, original)
    cache = session.info.get(_SOURCE_READ_VIEWS)
    if cache is None:
        return source_intake.read_intake(session, original.id)
    if original.id not in cache:
        cache[original.id] = source_intake.read_intake(session, original.id)
    return deepcopy(cache[original.id])


def _selected_sources(session, source_account, *, reserved=False):
    """Resolve a filename alias only through its documents' single row account.

    This is local source selection, not a persisted Hermes account mapping.
    Every selected document must agree; no suffix matching or transitive aliases.
    """
    selected = []
    scopes = set()
    for original in session.scalars(select(SourceIntakeOriginal).order_by(SourceIntakeOriginal.id)):
        try:
            aliases = json.loads(original.native_accounts_json)
            if not isinstance(aliases, list) or source_account not in aliases:
                continue
            view = _read_source_view(session, original, reserved=reserved)
            document = view["document"]
            native = _native_scope(document)
            if len(native) == 1 and source_account in native | {document["filename_account"]}:
                scopes.update(native)
            selected.append((original, view, None))
        except (MyBrokerError, ValueError, TypeError, KeyError, ArithmeticError):
            selected.append((original, None, "source_reader_unavailable"))
    return selected, scopes if len(scopes) == 1 else None


def _saved_totals(document):
    """Apply the provisional native-EOD eligibility rules to saved operands."""
    reasons = set(document.get("endpoint_conflicts", []))
    keys = [(row["source_account"], row["isin"]) for row in document.get("positions", [])]
    if len(set(keys)) != len(keys):
        reasons.add("duplicate_position")
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


def _money(session, view, choices, gaps, *, selected_accounts=None):
    persisted = {
        row.source_reference: row
        for row in session.scalars(
            select(SourceMoneyClassification).where(
                SourceMoneyClassification.intake_id == view["id"]
            )
        )
    }
    counts = defaultdict(int)
    result = []
    for row in view["document"].get("money", []):
        event_date = date.fromisoformat(row["date"])
        reference = source_reference(view["id"], row)
        if not view["covered_from"] <= row["date"] <= view["covered_to"]:
            # The invalid event belongs to this document's coverage, even when
            # its reported date is outside every displayed calculation month.
            saved = persisted.get(reference)
            code = (
                "invalid_external_flow"
                if saved and saved.classification in {"external_deposit", "external_withdrawal"}
                else "invalid_money_row"
            )
            month = date.fromisoformat(view["covered_from"]).replace(day=1)
            while month <= date.fromisoformat(view["covered_to"]):
                gaps.append(SourceReturnGap(code, view["id"], month, reference))
                month = _next_month(month)
            continue
        if normalize_currency(row.get("currency")) != "RUB":
            gaps.append(
                SourceReturnGap(
                    "currency_unsupported",
                    view["id"],
                    month=event_date.replace(day=1),
                    source_reference=reference,
                )
            )
            continue
        saved = persisted.get(reference)
        if saved is None:
            gaps.append(
                SourceReturnGap(
                    "classification_missing_legacy_intake",
                    view["id"],
                    month=event_date.replace(day=1),
                    source_reference=reference,
                )
            )
            continue
        classification = saved.classification
        if classification == "internal_transfer" or (
            selected_accounts is not None
            and (saved.origin, saved.status) == ("default_rule", "assumed")
            and is_broker_transfer(saved.operation, saved.narrative)
        ):
            classification = transfer_classification(
                saved.operation,
                saved.narrative,
                row["amount"],
                source_account=row["source_account"],
                selected_accounts=(
                    {row["source_account"]} if selected_accounts is None else selected_accounts
                ),
            )
        amount = saved.amount_kopecks
        external = classification in {"external_deposit", "external_withdrawal"}
        if (
            normalize_currency(saved.currency) != "RUB"
            or amount is None
            or amount != provisional._minor(row.get("amount"))
            or saved.date != event_date
            or normalize_currency(saved.currency) != normalize_currency(row.get("currency"))
            or (
                external and (amount == 0 or (amount > 0) != (classification == "external_deposit"))
            )
            or not view["covered_from"] <= row["date"] <= view["covered_to"]
        ):
            gaps.append(
                SourceReturnGap(
                    "invalid_external_flow" if external else "invalid_money_row",
                    view["id"],
                    month=event_date.replace(day=1),
                    source_reference=reference,
                )
            )
            continue
        included, status = external, saved.status
        # Preserve the Python provisional-choice compatibility surface for default
        # rows only; an explicit persisted classification is always authoritative.
        requirement = f"candidate:{row['ordinal']}:{digest(row)[:12]}"
        requested = (
            [choice for choice in choices.selections if choice.requirement_id == requirement]
            if choices and external and saved.origin == "default_rule"
            else []
        )
        selected = [choice for choice in requested if choice.source_references == (reference,)]
        if requested and (len(selected) != 1 or len(requested) != 1):
            gaps.append(
                SourceReturnGap(
                    "invalid_assumption_choice",
                    view["id"],
                    month=event_date.replace(day=1),
                    source_reference=reference,
                )
            )
        elif len(selected) == 1:
            if selected[0].choice == "exclude_from_external_schedule":
                included, status = False, "confirmed"
            elif selected[0].choice == "include_as_account_inflow" and amount > 0:
                status = "confirmed"
        signature = digest(
            {key: value for key, value in row.items() if key not in {"ordinal", "last_update"}}
            | {
                "currency": normalize_currency(row.get("currency")),
                "operation": saved.operation,
                "narrative": saved.narrative,
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
    """Read persisted classifications; isolate bad originals/months and retain gaps."""
    sources = []
    gaps = []
    money = defaultdict(list)
    uncertain_source_months = set()
    conflicting_endpoint_dates = set()
    source_flow_reasons = defaultdict(set)
    selected, native_scope = _selected_sources(session, source_account)
    from hermes_finance.services.source_return_proofs import resolve_proof

    saved_dates, proof_status = resolve_proof(session, source_account, selected, native_scope)
    for original, view, error in selected:
        start, end = original.covered_from, original.covered_to
        unknown_source_flows = False
        period_inferred = False
        try:
            if error:
                raise MyBrokerError(error)
            document = view["document"]
            attached = (originals or {}).get(original.id)
            context = None
            cancellation_dates = None
            blockers = source_return_blockers(view)
            scope_valid = (
                native_scope is not None
                and _native_scope(document) == native_scope
                and source_account in native_scope | {document["filename_account"]}
            )
            if attached and scope_valid:
                context = provisional.read_context(
                    session,
                    intake_id=original.id,
                    original=attached[0],
                    filename=attached[1],
                    expected_manifest_digest=view["manifest_digest"],
                )
                cancellation_dates = original_cancellation_dates(view, attached[0])
            elif not originals and scope_valid:
                cancellation_dates = saved_dates.get(original.id)
            if cancellation_dates is not None:
                blockers -= {
                    "unparsed_source_rows",
                    "4_Transfers_unsupported",
                    "5_UFSR_unsupported",
                }
            financial_blockers = _FINANCIAL_COMPLETENESS_BLOCKERS.intersection(
                (*blockers, *document.get("endpoint_blockers", []))
            )
            period_inferred = "period_inferred_from_content" in document.get("warnings", [])
            if period_inferred:
                financial_blockers.add("source_period_inferred")
            covered_month = start.replace(day=1)
            while covered_month <= end:
                month_blockers = financial_blockers.copy()
                if cancellation_dates and any(
                    day.replace(day=1) == covered_month for day in cancellation_dates
                ):
                    month_blockers.add("custody_cancellation_unresolved")
                if month_blockers:
                    uncertain_source_months.add(covered_month)
                    source_flow_reasons[covered_month].update(month_blockers)
                    gaps.extend(
                        SourceReturnGap(
                            code,
                            original.id,
                            covered_month,
                            message=(
                                SOURCE_PERIOD_INFERRED_MESSAGE
                                if code == "source_period_inferred"
                                else None
                            ),
                        )
                        for code in sorted(month_blockers)
                    )
                covered_month = _next_month(covered_month)
            if not scope_valid:
                gaps.append(SourceReturnGap("native_source_scope_ambiguous", original.id))
                unknown_source_flows = True
                opening = closing = None
            else:
                opening, closing, reasons = _saved_totals(view["document"])
                if "duplicate_position" in reasons:
                    conflicting_endpoint_dates.update((start - timedelta(days=1), end))
                gaps.extend(SourceReturnGap(code, original.id) for code in sorted(reasons))
                if context is not None:
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
                    # Keep the explained per-month inferred-period gaps above.
                    gaps.extend(
                        SourceReturnGap(code, original.id)
                        for code in context.hard_blockers
                        if code != "source_period_inferred" or not period_inferred
                    )
                for key, flow in _money(
                    session,
                    view,
                    (assumptions or {}).get(original.id),
                    gaps,
                ):
                    money[key].append(flow)
        except (MyBrokerError, ValueError, TypeError, KeyError, ArithmeticError):
            opening = closing = None
            gaps.append(SourceReturnGap("source_reader_unavailable", original.id))
            unknown_source_flows = True
        if unknown_source_flows:
            covered_month = start.replace(day=1)
            while covered_month <= end:
                uncertain_source_months.add(covered_month)
                covered_month = _next_month(covered_month)
        if start.day != 1 or end != _month_end(end):
            gaps.append(SourceReturnGap("partial_month_source", original.id))
        if period_inferred:
            # Activity months cannot date the statement's outer balances, even
            # when the unchanged original bytes are reattached.
            opening = closing = None
        sources.append((original.id, start, end, opening, closing))

    flows = []
    income = defaultdict(lambda: {"coupon": 0, "dividend": 0})
    assumed_income_months = set()
    for observations in money.values():
        confirmed = [flow for flow in observations if flow.status == "confirmed"]
        selected = confirmed or observations
        if len({(flow.included, flow.classification) for flow in selected}) != 1:
            gaps.append(
                SourceReturnGap(
                    "overlap_flow_choice_conflict", month=selected[0].event_date.replace(day=1)
                )
            )
            continue
        flow = selected[0]
        refs = tuple(ref for item in observations for ref in item.source_references)
        if flow.classification == "unknown":
            gaps.extend(
                SourceReturnGap(
                    "unrecognized_money",
                    int(ref.split(":")[1]),
                    flow.event_date.replace(day=1),
                    ref,
                )
                for ref in refs
            )
        elif flow.classification in {"coupon", "dividend"}:
            income_month = flow.event_date.replace(day=1)
            income[income_month][flow.classification] += flow.amount_kopecks
            if flow.status == "assumed":
                assumed_income_months.add(income_month)
        elif flow.classification in {"external_deposit", "external_withdrawal"}:
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
            source_proof=proof_status,
        )

    currency_months = {gap.month for gap in gaps if gap.code == "currency_unsupported"}
    uncertain_months = uncertain_source_months | {
        gap.month
        for gap in gaps
        if gap.code
        in {
            "currency_unsupported",
            "classification_missing_legacy_intake",
            "invalid_money_row",
            "unrecognized_money",
            "invalid_external_flow",
            "invalid_assumption_choice",
            "overlap_flow_choice_conflict",
        }
    }
    rows = []
    first = min(source[1] for source in sources)
    month = first.replace(day=1)
    last = max(source[2] for source in sources)
    period_uncertain_months = uncertain_months.copy()
    previous_closing = None
    while month <= last:
        end = _month_end(month)
        income_covered = _flow_coverage_complete(sources, month, end)
        if not income_covered:
            uncertain_months.add(month)
            source_flow_reasons[month].add("flow_coverage_gap")
        # Calendar-edge months can be incomplete while the reported period has
        # complete Money coverage. Only gaps inside its actual date bounds
        # invalidate period flows; valuation availability is independent.
        if not _flow_coverage_complete(sources, max(month, first), min(end, last)):
            period_uncertain_months.add(month)
        relevant = [source for source in sources if source[1] <= month and source[2] >= end]

        def endpoint(index, matches):
            point_date = month - timedelta(days=1) if index == 3 else end
            if point_date in conflicting_endpoint_dates:
                return None
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
        if {month - timedelta(days=1), end} & conflicting_endpoint_dates:
            calculated = replace(
                calculated, reason_codes=(*calculated.reason_codes, "duplicate_position")
            )
        if month in uncertain_months:
            calculated = replace(
                calculated,
                contributions_kopecks=None,
                withdrawals_kopecks=None,
                growth_kopecks=None,
                modified_dietz_return=None,
                reason_codes=(
                    *calculated.reason_codes,
                    "unknown_flow",
                    *(("currency_unsupported",) if month in currency_months else ()),
                    *sorted(source_flow_reasons[month]),
                ),
            )
        flags = list(calculated.reason_codes)
        if opening is not None and previous_closing is not None and opening != previous_closing:
            flags.append("seam_mismatch")
        # Inferred periods already have one explained gap per intake/month.
        gaps.extend(
            SourceReturnGap(code, month=month) for code in flags if code != "source_period_inferred"
        )
        rows.append(
            SourceMonthlyReturnRow(
                calculated,
                tuple(s[0] for s in relevant),
                tuple(flags),
                previous_closing,
                income[month]["coupon"]
                if income_covered and month not in uncertain_months
                else None,
                income[month]["dividend"]
                if income_covered and month not in uncertain_months
                else None,
                month in assumed_income_months,
            )
        )
        previous_closing = closing
        month = _next_month(month)
    period = _period_totals(rows, schedule, period_uncertain_months)
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
            **asdict(_period_totals(group, schedule, period_uncertain_months)),
        )
        for group in groups
    ]
    # A continuous long report may supply only the outer endpoints: retain
    # its available period estimate without inventing monthly valuations.
    if (
        not segments
        and all(row.intake_ids for row in rows)
        and rows[0].result.opening_kopecks is not None
        and rows[-1].result.closing_kopecks is not None
    ):
        segments.append(
            SourceReturnSegment(
                start=rows[0].result.opening_date,
                end=rows[-1].result.closing_date,
                partial_segment=True,
                **asdict(period),
            )
        )
    return SourceMonthlyReturns(
        source_account,
        tuple(rows),
        period,
        segments,
        tuple(flows),
        tuple(f for f in flows if f.status == "assumed"),
        tuple(gaps),
        source_proof=proof_status,
    )


def _period_totals(rows, schedule, uncertain_months):
    """Use native monthly endpoints/rates and retain unknown-flow blockers."""
    boundaries = [(rows[0].result.opening_date, rows[0].result.opening_kopecks)] + [
        (row.result.closing_date, row.result.closing_kopecks) for row in rows
    ]
    period = calculate_monthly_return_chain(boundaries, schedule).period
    chain_reasons = list(
        dict.fromkeys(reason for row in rows for reason in row.result.reason_codes)
    )
    with localcontext() as ctx:
        ctx.prec = 60
        ctx.rounding = ROUND_HALF_UP
        chain = Decimal(1)
        for row in rows:
            if row.result.modified_dietz_return is not None:
                factor = 1 + row.result.modified_dietz_return
                if factor < 0:
                    if "negative_dietz_factor" not in chain_reasons:
                        chain_reasons.append("negative_dietz_factor")
                else:
                    chain *= factor
        chained_return = None if chain_reasons else chain - 1
    period = replace(
        period,
        chained_return=chained_return,
        chain_reason_codes=tuple(chain_reasons),
        missing_endpoint=any(row.result.missing_endpoint for row in rows),
    )
    if any(row.result.closing_date.replace(day=1) in uncertain_months for row in rows):
        flow_reasons = tuple(reason for reason in chain_reasons if reason in _FLOW_REASONS)
        period = replace(
            period,
            contributions_kopecks=None,
            withdrawals_kopecks=None,
            growth_kopecks=None,
            xirr_annualized_return=None,
            xirr_period_return=None,
            growth_reason_codes=tuple(dict.fromkeys((*period.growth_reason_codes, *flow_reasons))),
            xirr_reason_codes=tuple(dict.fromkeys((*period.xirr_reason_codes, *flow_reasons))),
        )
    return period
