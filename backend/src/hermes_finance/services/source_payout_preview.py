"""Ephemeral statement quantity -> existing T-Invest schedule, without finance writes."""

import json
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from hermes_finance.database import coherent_read_operation
from hermes_finance.domain import MarketMappingState
from hermes_finance.domain.instrument_return import InstrumentEvent, SourceReference
from hermes_finance.market_data.dto import T_INVEST_PROVIDER
from hermes_finance.market_data.payout import PayoutEventStatus
from hermes_finance.market_data.payout_protocol import PayoutFetchRequest, PayoutFetchResult
from hermes_finance.persistence import (
    Account,
    BrokerIdentityMapping,
    Instrument,
    InstrumentMarketMapping,
    SourceIntakeRevision,
)
from hermes_finance.services.applied_payouts import compute_applied_total_kopecks
from hermes_finance.services.instrument_mappings import get_instrument_mapping
from hermes_finance.services.source_instrument_events import _decimal, read_events
from hermes_finance.services.source_instrument_returns import _identities
from hermes_finance.services.source_monthly_returns import _native_scope, _selected_sources
from hermes_finance.statement_import.mybroker import digest


@dataclass(frozen=True)
class SourcePayoutContext:
    source_account: str
    native_source_account: str | None
    account_id: int | None
    isin: str
    instrument_id: int | None
    as_of: date
    quantity: Decimal | None
    quantity_references: tuple[str, ...]
    source_references: tuple[SourceReference, ...]
    actuals: tuple[InstrumentEvent, ...]
    reconciliation_reasons: tuple[str, ...]
    instrument_uid: str | None
    reason_codes: tuple[str, ...]
    dependency_fingerprint: str

    def provider_request(self):
        if self.instrument_uid is None or self.quantity is None:
            return None
        try:
            end = self.as_of.replace(year=self.as_of.year + 1)
        except ValueError:
            end = self.as_of.replace(year=self.as_of.year + 1, day=28)
        # Bound comparison history; older actuals remain visible in the response.
        start = min((e.event_date for e in self.actuals if e.event_date), default=self.as_of)
        start = max(start, self.as_of - timedelta(days=366))
        return PayoutFetchRequest(
            instrument_uid=self.instrument_uid,
            calendar_from=min(start, self.as_of),
            calendar_to=end - timedelta(days=1),
        )


@coherent_read_operation
def source_quantity_bases(session, source_account: str, isin: str, on_or_before: date):
    """Discover saved closing dates, using the preview's exact quantity guards.

    This reader neither constructs a provider nor creates financial positions.
    A historical quantity is a scenario basis, never the requested month's EOD.
    """
    selected, native = _selected_sources(session, source_account)
    dates = sorted(
        {
            original.covered_to
            for original, view, error in selected
            if not error
            and native is not None
            and _native_scope(view["document"]) == native
            and original.covered_to <= on_or_before
            and any(p["isin"] == isin for p in view["document"].get("positions", []))
        },
        reverse=True,
    )
    bases = []
    for day in dates:
        context = source_payout_context(session, source_account, isin, day)
        bases.append(
            {
                "as_of": day,
                "quantity": context.quantity,
                "quantity_references": context.quantity_references,
                "reason_codes": context.reason_codes,
            }
        )
    return {
        "source_account": source_account,
        "native_source_account": next(iter(native)) if native else None,
        "isin": isin,
        "on_or_before": on_or_before,
        "bases": bases,
        "authority": "provisional",
        "financial_authority": "none",
    }


@coherent_read_operation
def source_payout_context(session, source_account: str, isin: str, as_of: date):
    selected, native = _selected_sources(session, source_account)
    reasons, views = set(), []
    for original, view, error in selected:
        if error or native is None or _native_scope(view["document"]) != native:
            reasons.add(error or "native_source_scope_ambiguous")
        else:
            views.append(view)
    if not views:
        reasons.add("source_not_found")
    native_account = next(iter(native)) if native else None
    accounts = {v["state"]["account_id"] for v in views}
    if len(accounts) > 1:
        reasons.add("account_binding_conflict")
    account_id = next(iter(accounts)) if len(accounts) == 1 else None
    bindings = list(
        session.scalars(select(BrokerIdentityMapping).order_by(BrokerIdentityMapping.id))
    )
    if account_id is not None:
        account = session.get(Account, account_id)
        if (
            account is None
            or account.status != "active"
            or account.account_type not in {"brokerage", "iis"}
        ):
            reasons.add("account_binding_invalid")
        for view in views:
            for alias in {native_account, view["document"].get("filename_account")}:
                mappings = [
                    m
                    for m in bindings
                    if m.provider == view["document"]["provider"]
                    and m.subject_kind == "account"
                    and m.provider_identity == alias
                ]
                active = [m for m in mappings if m.status == "effective"]
                if (
                    len(active) > 1
                    or any(m.hermes_target_id != account_id for m in active)
                    or (not active and any(m.status == "revoked" for m in mappings))
                ):
                    reasons.add("account_binding_conflict")
    quantities, refs = set(), []
    for view in views:
        if view["covered_to"] != as_of.isoformat():
            continue
        doc = view["document"]
        if "period_inferred_from_content" in doc.get("warnings", []):
            reasons.add("source_period_inferred")
        if doc.get("endpoint_basis", {}).get("ending_value") != "covered_to_eod":
            reasons.add("quantity_date_unproven")
        reasons.update(doc.get("syntax_blockers", []))
        reasons.update(doc.get("endpoint_conflicts", []))
        positions = [
            p
            for p in doc.get("positions", [])
            if p["isin"] == isin and p["source_account"] == native_account
        ]
        if len(positions) != 1:
            reasons.add("quantity_absent_or_ambiguous")
            continue
        row = positions[0]
        quantity = _decimal(row.get("actual_quantity"))
        forward = _decimal(row.get("forward_quantity"))
        if quantity is None or quantity < 0:
            reasons.add("quantity_unknown")
        elif forward is None or forward != quantity:
            reasons.add("endpoint_unsettled")
        else:
            quantities.add(quantity)
        refs.append(f"position:{view['id']}:{row['ordinal']}:closing")
        for p in view["proposals"]:
            if p["isin"] == isin:
                if isin in view["state"].get("deferred_isins", []):
                    reasons.add("source_intake_identity_deferred")
                reasons.update(p.get("review_reasons", []))
                if p["currency_assessment"]["basis"] == "conflict":
                    reasons.add("source_intake_currency_conflict")
    if len(quantities) != 1:
        reasons.add("quantity_unknown" if not quantities else "overlapping_quantity_conflict")
    quantity = next(iter(quantities)) if len(quantities) == 1 and not reasons else None
    instruments = list(session.scalars(select(Instrument).where(Instrument.isin == isin)))
    instrument = instruments[0] if len(instruments) == 1 else None
    uid = None
    if instrument is None:
        reasons.add("exact_instrument_required")
    elif instrument.instrument_type not in {"stock", "bond"}:
        reasons.add("instrument_type_unsupported")
    else:
        mapping = get_instrument_mapping(session, instrument.id)
        if (
            mapping.state == MarketMappingState.MAPPED
            and mapping.identity is not None
            and mapping.identity.provider == T_INVEST_PROVIDER
            and mapping.instrument_isin == isin
        ):
            uid = mapping.identity.provider_instrument_id
        else:
            reasons.add("exact_t_invest_mapping_required")
        if any(
            p["instrument_type"] != instrument.instrument_type
            for v in views
            for p in v["proposals"]
            if p["isin"] == isin
        ):
            reasons.add("instrument_type_conflict")
            quantity = None
    gaps = []
    events, sources = read_events(session, views, _identities(views), native_account, gaps)
    actuals = tuple(
        e
        for e in events
        if e.isin in (isin, None) and e.kind in {"COUPON", "DIVIDEND", "REDEMPTION", "UNRESOLVED"}
    )
    # Bind complete source revisions (including ABA dependency events), catalogue,
    # current payout links/classifications and mapping mutation time across provider I/O.
    dependency = digest(
        json.dumps(
            [
                views,
                [asdict(e) for e in events],
                [asdict(s) for s in sources],
                [vars(g) for g in gaps],
                [
                    [getattr(m, c.name) for c in BrokerIdentityMapping.__table__.columns]
                    for m in bindings
                ],
                [
                    (r.seq, r.request_fingerprint)
                    for r in session.scalars(
                        select(SourceIntakeRevision).order_by(SourceIntakeRevision.seq)
                    )
                ],
                [[getattr(i, c.name) for c in Instrument.__table__.columns] for i in instruments],
                [
                    [getattr(m, c.name) for c in InstrumentMarketMapping.__table__.columns]
                    for m in session.scalars(select(InstrumentMarketMapping))
                ],
            ],
            sort_keys=True,
            default=str,
        )
    )
    return SourcePayoutContext(
        source_account,
        native_account,
        account_id,
        isin,
        instrument.id if instrument else None,
        as_of,
        quantity,
        tuple(refs),
        sources,
        actuals,
        tuple(sorted({g.code for g in gaps})),
        uid,
        tuple(sorted(reasons)),
        dependency,
    )


def reconcile_source_payouts(context: SourcePayoutContext, fetched: PayoutFetchResult | None):
    """Date/kind proximity is a candidate, never provider identity or gross/net proof.

    Candidate and ambiguous events cannot contribute a second future payment.
    Actuals are the existing deduplicated source events, not a new cash ledger.
    """
    rows = []
    events = fetched.events if fetched else ()
    identities = [(e.provider, e.instrument_uid, e.event_kind, e.identity_key) for e in events]
    for event, identity in zip(events, identities, strict=True):
        candidates = [
            e
            for e in context.actuals
            if e.kind.lower() == event.event_kind.value
            and e.event_date
            and event.payment_date
            and abs((e.event_date - event.payment_date).days) <= 3
        ]
        uncertain = bool(context.reconciliation_reasons) or any(
            e.isin is None or not e.current or not e.counted or e.assumptions
            for e in context.actuals
        )
        reasons = []
        request = context.provider_request()
        if candidates:
            status = "possible_paid"
            reasons.append("actual_provider_identity_unproven")
        elif event.status != PayoutEventStatus.OK:
            status = event.status.value
        elif identities.count(identity) > 1:
            status = "ambiguous_identity"
            reasons.append("duplicate_provider_identity")
        elif event.payment_date <= context.as_of:
            status = "past_unreconciled"
        elif request is not None and event.payment_date > request.calendar_to:
            status = "outside_horizon"
        elif uncertain:
            status = "reconciliation_required"
            reasons.append("actual_attribution_unresolved")
        else:
            status = "future"
        countable = status == "future" and context.quantity is not None
        total = None
        if (
            event.status == PayoutEventStatus.OK
            and event.currency == "RUB"
            and context.quantity is not None
            and event.per_unit_amount is not None
        ):
            try:
                total = compute_applied_total_kopecks(event.per_unit_amount, context.quantity)
                if not 0 <= total <= 2**63 - 1:
                    raise ValueError
            except (ValueError, ArithmeticError):
                total = None
                reasons.append("announced_amount_out_of_bounds")
                countable = False
        rows.append(
            {
                "identity_key": event.identity_key,
                "event_kind": event.event_kind.value,
                "payment_date": event.payment_date,
                "provider_status": event.provider_status,
                "source_method": event.source_method,
                "per_unit_amount": event.per_unit_amount,
                "currency": event.currency,
                "announced_amount_kopecks": str(total) if total is not None else None,
                "personal_tax_known": False,
                "status": status,
                "countable_future": countable,
                "actual_event_keys": [e.event_key for e in candidates],
                "reason_codes": reasons,
            }
        )
    return {
        "authority": "provisional",
        "financial_authority": "none",
        "source_account": context.source_account,
        "native_source_account": context.native_source_account,
        "account_id": context.account_id,
        "isin": context.isin,
        "instrument_id": context.instrument_id,
        "as_of": context.as_of,
        "quantity": context.quantity,
        "quantity_authority": "source_observed",
        "assumptions": ["fixed_source_quantity_not_entitlement"],
        "quantity_references": context.quantity_references,
        "source_references": context.source_references,
        "dependency_fingerprint": context.dependency_fingerprint,
        "reason_codes": context.reason_codes,
        "provider": T_INVEST_PROVIDER,
        "instrument_uid": context.instrument_uid,
        "actuals": [
            {
                **{
                    key: getattr(e, key)
                    for key in (
                        "event_key",
                        "provider",
                        "native_source_account",
                        "isin",
                        "kind",
                        "source_references",
                        "event_date",
                        "effective_isin",
                        "classification",
                        "classification_origin",
                        "classification_status",
                        "persisted_link_status",
                        "attribution_basis",
                        "current",
                        "counted",
                        "reason_codes",
                        "assumptions",
                    )
                },
                **{
                    key: str(value) if (value := getattr(e, key)) is not None else None
                    for key in (
                        "net_payout_kopecks",
                        "gross_payout_kopecks",
                        "withheld_tax_kopecks",
                    )
                },
            }
            for e in context.actuals
        ],
        "reconciliation_reasons": context.reconciliation_reasons,
        "rows": rows,
        "failures": [f.status.value for f in fetched.failures] if fetched else [],
    }
