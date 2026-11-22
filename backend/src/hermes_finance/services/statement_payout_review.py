"""Read-only comparison of one Alfa depository PDF with one forecast vintage per month."""

from calendar import monthrange
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from hermes_finance.persistence import (
    AppliedPayoutReconciliation,
    AppliedProviderPayout,
    ExpectedCashFlow,
    InvestmentCashFlow,
    ReportingMonth,
)
from hermes_finance.services.actual_payouts import _distinct_current, event_key, relation_state
from hermes_finance.services.applied_statement_events import get_applied_statement_event_by_identity
from hermes_finance.services.instrument_names import instrument_names
from hermes_finance.services.monthly_summary import DEFAULT_FORECAST_VERSION
from hermes_finance.services.statement_import_apply import _linked_flow_matches_accepted
from hermes_finance.services.statement_import_preparation import StatementApplyPreparationRow
from hermes_finance.statement_import.dto import DuplicateClass, ReportStatus, RowStatus


@dataclass(frozen=True)
class Forecast:
    key: tuple[str, int]
    account: int
    instrument: int
    kind: str
    day: date
    currency: str
    amount: Decimal
    gross: Decimal | None
    tax: Decimal | None
    snapshot: date
    version: str | None
    provider_key: str | None


def forecast_view(kind, f, month):
    manual = kind == "ecf"
    return Forecast(
        (kind, f.id),
        f.account_id,
        f.instrument_id,
        f.flow_type if manual else f.event_kind,
        f.expected_date if manual else f.payment_date,
        f.currency,
        Decimal(f.expected_net_amount_kopecks if manual else f.total_amount_kopecks) / 100,
        Decimal(f.gross_amount_kopecks) / 100 if manual else None,
        Decimal(f.expected_tax_amount_kopecks) / 100
        if manual and f.expected_tax_amount_kopecks is not None
        else None,
        month.snapshot_date,
        f.forecast_version if manual else None,
        None if manual else event_key(f),
    )


def month_forecasts(session, start, accounts):
    end = start.replace(day=monthrange(start.year, start.month)[1])
    # Compare against the latest available opening snapshot. A first month can
    # have only its own plan; explicitly identify that vintage in the response.
    month = session.scalar(
        select(ReportingMonth)
        .where(ReportingMonth.snapshot_date < start)
        .order_by(ReportingMonth.snapshot_date.desc(), ReportingMonth.id.desc())
        .limit(1)
    )
    if month is None:
        month = session.scalar(
            select(ReportingMonth).where(
                ReportingMonth.year == start.year, ReportingMonth.month == start.month
            )
        )
    if month is None:
        return None, []
    forecasts = []
    for model, kind in ((ExpectedCashFlow, "ecf"), (AppliedProviderPayout, "app")):
        manual = kind == "ecf"
        event = model.flow_type if manual else model.event_kind
        day = model.expected_date if manual else model.payment_date
        query = (
            select(model)
            .where(
                model.reporting_month_id == month.id,
                model.account_id.in_(accounts),
                model.archived_from_period.is_(None),
                event.in_(("dividend", "coupon", "redemption")),
                day.between(start, end),
                model.forecast_version == DEFAULT_FORECAST_VERSION
                if manual
                else model.lifecycle == "active",
            )
            .order_by(day, model.id)
        )
        for f in session.scalars(query):
            forecasts.append(forecast_view(kind, f, month))
    return month.snapshot_date, forecasts


def accepted_flow(session, provider, row):
    """Proof must bind this exact PDF fingerprint, current cash flow and terminal settlement."""
    if row.duplicate_class != DuplicateClass.DUPLICATE or not row.natural_identity:
        return None, None
    event = get_applied_statement_event_by_identity(
        session, provider=provider, natural_identity=row.natural_identity
    )
    if (
        event is None
        or event.status != "active"
        or event.material_fingerprint != row.material_fingerprint
        or event.account_id != row.expected_hermes_account_id
        or event.instrument_id != row.expected_hermes_instrument_id
        or not event.investment_cash_flow_id
    ):
        return "stale_evidence", None
    flow = session.get(InvestmentCashFlow, event.investment_cash_flow_id)
    if not _linked_flow_matches_accepted(session, event=event, flow=flow):
        return "stale_evidence", None
    return None, flow


def paid_forecasts(session, flow):
    if flow is None:
        return None, []
    links = list(
        session.scalars(
            select(AppliedPayoutReconciliation).where(
                AppliedPayoutReconciliation.investment_cash_flow_id == flow.id
            )
        )
    )
    superseded = {link.supersedes_id for link in links}
    current = [link for link in links if link.id not in superseded]
    if not current:
        return None, []
    if len(current) == 1 and current[0].retired_request_id:
        return "retired", []
    if (
        len(current) != 1
        or current[0].archived_from_period
        or relation_state(session, current[0]) != "paid"
    ):
        return "stale_evidence", []
    link = current[0]
    forecasts = []
    for kind, model, ident in (
        ("ecf", ExpectedCashFlow, link.expected_cash_flow_id),
        ("app", AppliedProviderPayout, link.applied_payout_id),
    ):
        if ident is None:
            continue
        forecast = session.get(model, ident)
        if (
            forecast is None
            or forecast.archived_from_period
            or (kind == "app" and forecast.lifecycle != "active")
        ):
            return "stale_evidence", []
        month = session.get(ReportingMonth, forecast.reporting_month_id)
        if month is None or month.snapshot_date is None:
            return "stale_evidence", []
        forecasts.append(forecast_view(kind, forecast, month))
    return None, forecasts


def settled_forecast_keys(session, pool):
    """Exclude already settled plans even if the PDF contains only another payment."""
    if not pool:
        return set()
    manual = {f.key[1] for f in pool if f.key[0] == "ecf"}
    providers = {f.key[1] for f in pool if f.key[0] == "app"}
    keys = {f.provider_key for f in pool if f.provider_key}
    links = session.scalars(
        select(AppliedPayoutReconciliation).where(
            AppliedPayoutReconciliation.retired_request_id.is_(None),
            AppliedPayoutReconciliation.archived_from_period.is_(None),
            or_(
                AppliedPayoutReconciliation.expected_cash_flow_id.in_(manual),
                AppliedPayoutReconciliation.applied_payout_id.in_(providers),
                AppliedPayoutReconciliation.provider_event_key.in_(keys),
            ),
        )
    )
    settled = set()
    provider_keys = set()
    for link in links:
        if relation_state(session, link) == "paid":
            settled.add(("ecf", link.expected_cash_flow_id))
            settled.add(("app", link.applied_payout_id))
            if link.provider_event_key:
                provider_keys.add(link.provider_event_key)
    return {f.key for f in pool if f.key in settled or f.provider_key in provider_keys}


def distinct_from_flow(session, flow, forecast):
    if flow is None:
        return False
    kind, ident = forecast.key
    model = ExpectedCashFlow if kind == "ecf" else AppliedProviderPayout
    return _distinct_current(session, flow, kind, session.get(model, ident))


def verdict(row: StatementApplyPreparationRow, forecast: Forecast, proven: bool):
    if row.duplicate_class == DuplicateClass.CORRECTION:
        return "correction"
    if (
        not row.tax_available
        or row.tax_amount is None
        or forecast.tax is None
        or row.gross_amount is None
        or row.gross_currency != forecast.currency
        or row.net_currency != forecast.currency
        or row.net_amount is None
    ):
        return "incomparable"
    if row.net_amount < forecast.amount:
        return "below_expected"
    if row.net_amount > forecast.amount:
        return "different_amount"
    if row.tax_amount != forecast.tax or row.gross_amount != forecast.gross:
        return "different_components"
    return "verified" if proven else "unconfirmed"


def payout_review(session: Session, preparation, *, target_month: date | None, today: date):
    if preparation.status != ReportStatus.APPLICABLE:
        return None
    rows = list(preparation.rows)
    periods = (
        {target_month}
        if target_month
        else {r.event_date.replace(day=1) for r in rows if r.event_date}
    )
    names = instrument_names(session)
    items = []

    row_numbers = {id(r): n for n, r in enumerate(rows)}

    def add(reason, row=None, forecast=None):
        instrument = row.expected_hermes_instrument_id if row else forecast.instrument
        isin = row.isin if row else None
        items.append(
            dict(
                key=f"row-{row_numbers[id(row)]}"
                if row
                else f"forecast-{forecast.key[0]}-{forecast.key[1]}",
                reason=reason,
                forecast_snapshot=forecast.snapshot if forecast else None,
                forecast_version=forecast.version if forecast else None,
                name=names.name(instrument_id=instrument, isin=isin) or isin,
                account_id=row.expected_hermes_account_id if row else forecast.account,
                event_kind=row.event_kind if row else forecast.kind,
                actual_date=row.event_date if row else None,
                expected_date=forecast.day if forecast else None,
                actual_net=format(row.net_amount, ".2f")
                if row and row.net_amount is not None
                else None,
                actual_currency=row.net_currency if row else None,
                actual_tax=format(row.tax_amount, ".2f")
                if row and row.tax_available and row.tax_amount is not None
                else None,
                expected_tax=format(forecast.tax, ".2f")
                if forecast and forecast.tax is not None
                else None,
                expected_amount=format(forecast.amount, ".2f") if forecast else None,
                expected_currency=forecast.currency if forecast else None,
                expected_basis=("net" if forecast.key[0] == "ecf" else "announced")
                if forecast
                else None,
            )
        )

    vintages = []
    pending = []
    seen = set()
    for start in sorted(periods):
        scoped = [r for r in rows if r.event_date and r.event_date.replace(day=1) == start]
        accounts = {
            r.expected_hermes_account_id for r in rows if r.expected_hermes_account_id is not None
        }
        stamp, pool = month_forecasts(session, start, accounts)
        vintages.append({"month": start, "snapshot": stamp})
        settled = settled_forecast_keys(session, pool)
        seen.update(settled)
        grouped = defaultdict(list)
        for f in pool:
            grouped[(f.account, f.instrument, f.kind)].append(f)

        def scope(r):
            return r.expected_hermes_account_id, r.expected_hermes_instrument_id, r.event_kind

        multiplicity = Counter(scope(r) for r in scoped)
        identities = Counter(r.natural_identity for r in scoped if r.natural_identity)
        for row in scoped:
            if row.status != RowStatus.MATCHED:
                add("unresolved_row", row)
                continue
            if identities[row.natural_identity] > 1:
                add("ambiguous", row)
                continue
            issue, flow = accepted_flow(session, preparation.provider, row)
            if issue:
                add(issue, row)
                continue
            issue, proven = paid_forecasts(session, flow)
            scoped_plans = grouped[scope(row)]
            candidates = [
                f
                for f in scoped_plans
                if f.key not in settled and not distinct_from_flow(session, flow, f)
            ]
            # A proven manual forecast and its provider counterpart describe one
            # event. Only the manual row supplies a comparable net amount.
            if proven:
                comparable = next((f for f in proven if f.key[0] == "ecf"), proven[0])
                seen.update(f.key for f in proven)
                add(verdict(row, comparable, True), row, comparable)
            elif issue:
                add(issue, row)
            elif row.duplicate_class == DuplicateClass.CORRECTION:
                add("correction", row)
            elif scoped_plans and not candidates:
                add(
                    "already_allocated"
                    if all(f.key in settled for f in scoped_plans)
                    else "distinct",
                    row,
                )
            elif not candidates:
                has_account_plan = any(f.account == row.expected_hermes_account_id for f in pool)
                reason = (
                    "no_forecast"
                    if has_account_plan
                    else ("empty_plan" if stamp else "no_snapshot")
                )
                add(reason, row)
            elif len(candidates) == 1 and multiplicity[scope(row)] == 1:
                f = candidates[0]
                # A suggested pairing is a single review item, never a receipt.
                seen.add(f.key)
                add(verdict(row, f, False), row, f)
            else:
                add("ambiguous", row)
        pending.extend(pool)
    for f in pending:
        if f.key not in seen:
            add("future" if f.day > today else "coverage_unknown", forecast=f)
    for row in rows:
        if not row.event_date:
            add("unresolved_row", row)
        elif target_month and row.event_date.replace(day=1) != target_month:
            add("other_month", row)
    return {"vintages": vintages, "items": items, "forecast_version": DEFAULT_FORECAST_VERSION}
