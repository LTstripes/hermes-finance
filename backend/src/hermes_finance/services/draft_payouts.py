"""Explicit DRAFT-only orchestration of the existing forecast reader/writer.

No source acceptance, actual payout, ECF, progress journal or background retry.
Each position commits independently; a new click always starts with fresh reads.
"""

from collections import Counter
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.database import coherent_read_snapshot
from hermes_finance.domain import InstrumentType, MarketMappingState
from hermes_finance.market_data.dto import T_INVEST_PROVIDER, QuoteStatus
from hermes_finance.market_data.payout_protocol import PayoutFetchRequest
from hermes_finance.persistence import (
    Account,
    AppliedPayoutReconciliation,
    AppliedPayoutRevision,
    AppliedProviderPayout,
    BrokerMonthApply,
    ExpectedCashFlow,
    Instrument,
    InstrumentMarketMapping,
    InvestmentCashFlow,
    PositionSnapshot,
    ReportingMonth,
)
from hermes_finance.services import actual_payouts, broker_months
from hermes_finance.services import broker_month_journal as journal
from hermes_finance.services._guard import require_editable_reporting_month
from hermes_finance.services.instrument_mappings import get_instrument_mapping, set_accepted_mapping
from hermes_finance.services.payout_apply import PayoutApplySelection, apply_payout_preview
from hermes_finance.services.payout_calendar import merged_payout_calendar
from hermes_finance.services.payout_preview import PayoutPreviewStatus, build_payout_preview
from hermes_finance.services.reporting_months import ReportingMonthNotFoundError
from hermes_finance.services.source_native import NATIVE_SOURCE
from hermes_finance.statement_import.mybroker import digest


def _material(row):
    return [str(getattr(row, c.name)) for c in row.__table__.columns] if row else None


def _mapping_token(session, instrument_id):
    return _material(session.get(InstrumentMarketMapping, instrument_id, populate_existing=True))


def _forecast_token(session):
    return digest(
        [
            [_material(row) for row in broker_months._rows(session, model)]
            for model in (
                InstrumentMarketMapping,
                AppliedProviderPayout,
                AppliedPayoutRevision,
                AppliedPayoutReconciliation,
                ExpectedCashFlow,
            )
        ]
    )


def _context(session, month_id):
    month = session.get(ReportingMonth, month_id, populate_existing=True)
    if month is None:
        raise ReportingMonthNotFoundError("reporting month not found")
    receipts = [
        r
        for r in broker_months._rows(session, BrokerMonthApply)
        if r.reporting_month_id == month_id and journal.kind(r) == journal.SOURCE
    ]
    readiness = {
        r.account_id: broker_months._account_readiness(session, month_id, r.account_id)
        for r in receipts
    }
    items = []
    for position in broker_months._rows(session, PositionSnapshot):
        if position.reporting_month_id != month_id:
            continue
        # Manual/copied positions never become statement-backed through this CTA.
        if position.price_source != NATIVE_SOURCE:
            continue
        account = session.get(Account, position.account_id, populate_existing=True)
        instrument = session.get(Instrument, position.instrument_id, populate_existing=True)
        reasons = set(readiness.get(position.account_id, []))
        bases = [
            r
            for r in receipts
            if r.account_id == position.account_id
            and r.import_id == position.source_import_id
            and position.id in journal.payload(r)["position_ids"]
        ]
        if not bases:
            reasons.add("financial_draft_required")
        if month.status != "draft":
            reasons.add("closed_month")
        if (
            not account
            or account.status != "active"
            or account.account_type not in {"brokerage", "iis"}
        ):
            reasons.add("account_binding_changed")
        if (
            not instrument
            or not instrument.isin
            or instrument.instrument_type not in {"stock", "bond"}
            or instrument.currency != "RUB"
        ):
            reasons.add("instrument_unsupported")
        if position.quantity <= 0:
            reasons.add("position_not_positive")
        if position.price_date != month.snapshot_date:
            reasons.add("source_projection_changed")
        items.append(
            {
                "account_id": position.account_id,
                "account_name": account.name if account else "",
                "instrument_id": position.instrument_id,
                "instrument_name": instrument.name if instrument else "",
                "isin": instrument.isin if instrument else None,
                "position_snapshot_id": position.id,
                "quantity": str(position.quantity),
                "eligible": not reasons,
                "reason_codes": sorted(reasons),
            }
        )
    source_token = broker_months._dependencies(session)
    return {
        "reporting_month_id": month_id,
        "snapshot_date": month.snapshot_date.isoformat(),
        "status": month.status,
        "context_digest": digest([source_token, _forecast_token(session)]),
        "eligible_positions": sum(item["eligible"] for item in items),
        "items": items,
    }, source_token


def read_context(session, month_id):
    with coherent_read_snapshot(session):
        return _context(session, month_id)[0]


def _source_current(session, month_id, source_token):
    month = session.get(ReportingMonth, month_id, populate_existing=True)
    connection = session.connection()
    return (
        connection.connection.driver_connection is session.info["draft_payout_connection"]
        and connection.exec_driver_sql("PRAGMA data_version").scalar_one()
        == session.info["draft_payout_data_version"]
        and month is not None
        and month.status == "draft"
        and broker_months._dependencies(session) == source_token
    )


def _ensure_mapping(session, item, month_id, source_token, tokens, provider):
    instrument_id = item["instrument_id"]
    mapping_token = tokens[instrument_id]
    with coherent_read_snapshot(session):
        if (
            not _source_current(session, month_id, source_token)
            or _mapping_token(session, instrument_id) != mapping_token
        ):
            return "draft_changed"
        mapping = get_instrument_mapping(session, instrument_id)
        if mapping.state is MarketMappingState.EXCLUDED:
            return "mapping_excluded"
        if mapping.identity is not None:
            return (
                None
                if mapping.identity.provider == T_INVEST_PROVIDER
                else "mapping_provider_unsupported"
            )
        if (
            session.scalar(
                select(AppliedProviderPayout.id)
                .where(
                    AppliedProviderPayout.instrument_id == instrument_id,
                )
                .limit(1)
            )
            is not None
        ):
            return "mapping_review_required"
        instrument = session.get(Instrument, instrument_id)
        kind, isin = InstrumentType(instrument.instrument_type), instrument.isin
    # Only the public ISIN/type leave Hermes. No account/quantity/source payload.
    candidates = provider.discover_candidates(isin=isin, instrument_kind=kind)
    if (
        candidates.status is not QuoteStatus.OK
        or len(candidates.candidates) != 1
        or candidates.rejected
    ):
        return "mapping_" + candidates.status.value
    candidate = candidates.candidates[0]
    if (
        candidate.identity.provider != T_INVEST_PROVIDER
        or candidate.identity.isin != isin
        or candidate.verified_isin != isin
        or candidate.instrument_kind is not kind
        or candidate.currency != "RUB"
    ):
        return "mapping_exact_identity_required"

    def before_write():
        require_editable_reporting_month(session, month_id)
        if (
            not _source_current(session, month_id, source_token)
            or _mapping_token(session, instrument_id) != mapping_token
        ):
            raise ValueError("draft_changed")

    set_accepted_mapping(
        session,
        instrument_id,
        provider=T_INVEST_PROVIDER,
        provider_instrument_id=candidate.identity.provider_instrument_id,
        isin=isin,
        verify_provider=provider,
        require_exact=True,
        before_write=before_write,
        # Pin our own write before commit: an intervening mapping edit/revert
        # after commit must not be adopted as this batch's verified identity.
        after_flush=lambda row: tokens.__setitem__(instrument_id, _material(row)),
    )
    return None


def _actual_review(session, row, states):
    state = states.get(("app", row.applied_payout_id))
    if state in {"paid", "unresolved"}:
        return state
    # Preserve #970's canonical event lineage across months, including retired
    # links. Proximity remains an exception, never evidence of actual receipt.
    probe = AppliedProviderPayout(
        account_id=row.account_id,
        instrument_id=row.instrument_id,
        provider=row.provider,
        provider_instrument_uid=row.instrument_uid,
        event_kind=row.event_kind.value,
        identity_key=row.identity_key,
    )
    if (
        session.scalar(
            select(AppliedPayoutReconciliation.id)
            .where(
                AppliedPayoutReconciliation.investment_cash_flow_id.is_not(None),
                AppliedPayoutReconciliation.provider_event_key == actual_payouts.event_key(probe),
            )
            .limit(1)
        )
        is not None
    ):
        return "unresolved"
    if (
        row.payment_date
        and session.scalar(
            select(InvestmentCashFlow.id)
            .where(
                InvestmentCashFlow.account_id == row.account_id,
                InvestmentCashFlow.instrument_id == row.instrument_id,
                InvestmentCashFlow.flow_type == row.event_kind.value,
                InvestmentCashFlow.currency == row.currency,
                InvestmentCashFlow.event_date.between(
                    row.payment_date - timedelta(days=3), row.payment_date + timedelta(days=3)
                ),
            )
            .limit(1)
        )
        is not None
    ):
        return "unresolved"
    return None


def _refresh_position(session, item, month_id, version, source_token, mapping_token, provider):
    with coherent_read_snapshot(session):
        if (
            not _source_current(session, month_id, source_token)
            or _mapping_token(session, item["instrument_id"]) != mapping_token
        ):
            return "needs_review", ["draft_changed"], []
        month = session.get(ReportingMonth, month_id)
        start, end = actual_payouts._future_bounds(month)
        mapping = get_instrument_mapping(session, item["instrument_id"])
        uid = mapping.identity.provider_instrument_id
        if (
            session.scalar(
                select(AppliedProviderPayout.id)
                .where(
                    AppliedProviderPayout.reporting_month_id == month_id,
                    AppliedProviderPayout.account_id == item["account_id"],
                    AppliedProviderPayout.instrument_id == item["instrument_id"],
                    AppliedProviderPayout.lifecycle == "active",
                    (AppliedProviderPayout.provider != T_INVEST_PROVIDER)
                    | (AppliedProviderPayout.provider_instrument_uid != uid),
                )
                .limit(1)
            )
            is not None
        ):
            # The calendar retains active history under the previous UID. A new
            # accepted mapping cannot prove these are independent future events.
            return "needs_review", ["saved_provider_identity_changed"], []
        context_token = _forecast_token(session)
    request = PayoutFetchRequest(
        instrument_uid=uid, calendar_from=start, calendar_to=end - timedelta(days=1)
    )
    fetched = provider.fetch_payouts(request)
    if fetched.provider != T_INVEST_PROVIDER or fetched.instrument_uid != uid or fetched.failures:
        return "error", ["provider_error"], []
    if not fetched.events:
        return "needs_review", ["provider_empty"], []
    with coherent_read_snapshot(session):
        if (
            not _source_current(session, month_id, source_token)
            or _forecast_token(session) != context_token
        ):
            return "needs_review", ["draft_changed"], []
        preview = build_payout_preview(
            session,
            reporting_month_id=month_id,
            account_id=item["account_id"],
            instrument_id=item["instrument_id"],
            position_snapshot_id=item["position_snapshot_id"],
            forecast_version=version,
            fetch_result=fetched,
        )
        states = actual_payouts.future_states(session, month_id)
        identities = Counter(
            (r.provider, r.instrument_uid, r.event_kind, r.identity_key) for r in preview.rows
        )
        reasons, selections = set(), []
        for row in preview.rows:
            if row.event_kind is None or row.identity_key is None:
                reasons.add(row.status.value)
                continue
            actual = _actual_review(session, row, states)
            if actual == "paid":
                continue
            if actual:
                reasons.add("actual_payout_review_required")
                continue
            if (
                identities[(row.provider, row.instrument_uid, row.event_kind, row.identity_key)]
                != 1
                or row.manual_candidate_ids
                or row.applied_lifecycle not in {None, "active"}
            ):
                reasons.add("payout_identity_review_required")
                continue
            if row.status is PayoutPreviewStatus.UNCHANGED:
                continue
            if (
                row.status not in {PayoutPreviewStatus.NEW, PayoutPreviewStatus.REVISED}
                or not row.selectable
                or not row.fingerprint
                or row.currency != "RUB"
                or row.payment_date is None
                or not start <= row.payment_date < end
            ):
                reasons.add(row.status.value)
                continue
            selections.append(
                PayoutApplySelection(
                    row.provider,
                    row.instrument_uid,
                    row.event_kind,
                    row.identity_key,
                    row.fingerprint,
                )
            )
    if not selections:
        return ("needs_review" if reasons else "unchanged"), sorted(reasons), []
    result = apply_payout_preview(
        session,
        provider=provider,
        provider_request=request,
        reporting_month_id=month_id,
        account_id=item["account_id"],
        instrument_id=item["instrument_id"],
        position_snapshot_id=item["position_snapshot_id"],
        forecast_version=version,
        selections=tuple(selections),
        context_is_current=lambda: (
            _source_current(session, month_id, source_token)
            and _forecast_token(session) == context_token
        ),
    )
    if not result.success:
        return "error", sorted(reasons | {result.error_code.value}), []
    # Fresh committed read, never the apply ACK or its ORM identity map.
    with coherent_read_snapshot(session):
        for saved in result.items:
            latest = actual_payouts._latest_revision(session, saved.payout_id)
            if latest is None or latest.id != saved.revision_id:
                return "error", ["readback_unconfirmed"], []
        merged_payout_calendar(session, reporting_month_id=month_id, forecast_version=version)
    return "updated", sorted(reasons), [i.payout_id for i in result.items]


def refresh(
    session, month_id, *, context_digest, forecast_version, mapping_provider, payout_provider
):
    # Pin one physical connection across short read/write transactions and I/O.
    # SQLite data_version changes on OTHER connections' commits, including
    # absent->excluded->absent mapping ABA, but not on this batch's own commits.
    # https://www.sqlite.org/pragma.html#pragma_data_version
    # No transaction or writer reservation is held during provider requests.
    with session.get_bind().connect() as connection:
        with Session(bind=connection, autoflush=False, expire_on_commit=False) as pinned:
            pinned.info.update(session.info)
            pinned.info["draft_payout_connection"] = connection.connection.driver_connection
            pinned.info["draft_payout_data_version"] = (
                pinned.connection().exec_driver_sql("PRAGMA data_version").scalar_one()
            )
            pinned.rollback()
            return _refresh(
                pinned,
                month_id,
                context_digest=context_digest,
                forecast_version=forecast_version,
                mapping_provider=mapping_provider,
                payout_provider=payout_provider,
            )


def _refresh(
    session, month_id, *, context_digest, forecast_version, mapping_provider, payout_provider
):
    with coherent_read_snapshot(session):
        context, source_token = _context(session, month_id)
        if context["status"] != "draft" or context["context_digest"] != context_digest:
            raise ValueError("draft_changed")
        tokens = {
            i["instrument_id"]: _mapping_token(session, i["instrument_id"])
            for i in context["items"]
        }
    items = []
    for item in context["items"]:
        result = {**item, "status": "needs_review", "saved_payout_ids": []}
        if item["eligible"]:
            try:
                reason = _ensure_mapping(
                    session,
                    item,
                    month_id,
                    source_token,
                    tokens,
                    mapping_provider,
                )
                if reason:
                    result["reason_codes"] = [reason]
                    result["status"] = (
                        "unsupported"
                        if reason
                        in {
                            "mapping_unsupported",
                            "mapping_provider_unsupported",
                            "mapping_unavailable",
                        }
                        else "needs_review"
                    )
                else:
                    status, reasons, ids = _refresh_position(
                        session,
                        item,
                        month_id,
                        forecast_version,
                        source_token,
                        tokens[item["instrument_id"]],
                        payout_provider,
                    )
                    result.update(status=status, reason_codes=reasons, saved_payout_ids=ids)
            except Exception:
                # Provider exceptions may contain credentials. Preserve earlier
                # commits and report uncertainty; never replay inside the batch.
                session.rollback()
                result.update(status="error", reason_codes=["refresh_unconfirmed"])
        items.append(result)
    return {
        "reporting_month_id": month_id,
        "items": items,
        "summary": {
            status: sum(
                i["status"] == status
                or (
                    status == "needs_review"
                    and i["status"] == "updated"
                    and bool(i["reason_codes"])
                )
                for i in items
            )
            for status in ("updated", "unchanged", "unsupported", "needs_review", "error")
        },
    }
