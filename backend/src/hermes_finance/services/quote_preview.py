"""Read-only quote refresh preview for one reporting month (R04-04).

Combines accepted R04-03 mappings with the R04-02 provider and existing
PositionSnapshot rows. Never writes to the database.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.domain import InstrumentType, MarketMappingState, ReportingMonthStatus
from hermes_finance.market_data.dto import (
    MarketIdentity,
    QuoteFailure,
    QuoteKind,
    QuoteResult,
    QuoteStatus,
    RawPriceBasis,
)
from hermes_finance.market_data.normalize import SUPPORTED_KINDS, quote_refresh_target_date
from hermes_finance.market_data.protocol import MarketDataProvider
from hermes_finance.persistence import Instrument, PositionSnapshot
from hermes_finance.services.instrument_mappings import (
    InstrumentMappingView,
    get_instrument_mapping,
)
from hermes_finance.services.instruments import get_instrument
from hermes_finance.services.reporting_months import get_reporting_month


@dataclass(frozen=True, slots=True)
class QuotePreviewRow:
    position_snapshot_id: int
    account_id: int
    instrument_id: int
    instrument_name: str
    instrument_type: str
    mapping_state: MarketMappingState
    identity: MarketIdentity | None
    current_market_price_kopecks: int
    current_price_date: date
    current_price_source: str
    proposed_market_price_kopecks: int | None
    proposed_price_date: date | None
    proposed_quote_kind: QuoteKind | None
    proposed_raw_price: str | None
    proposed_raw_price_basis: RawPriceBasis | None
    fetched_at_utc: datetime | None
    freshness_status: QuoteStatus | None
    status: QuoteStatus
    message: str | None
    apply_allowed: bool


@dataclass(frozen=True, slots=True)
class QuotePreviewResult:
    reporting_month_id: int
    month_status: ReportingMonthStatus
    target_date: date
    month_editable: bool
    batch_error: str | None
    rows: tuple[QuotePreviewRow, ...]


def _identity_key(identity: MarketIdentity) -> tuple[str, str, str, str, str]:
    return (
        identity.provider,
        identity.engine,
        identity.market,
        identity.boardid,
        identity.secid,
    )


def _require_read_only(session: Session) -> None:
    if session.new or session.dirty or session.deleted:
        session.rollback()
        raise RuntimeError("quote preview must not mutate the database session")


def _coerce_kind(instrument_type: str) -> InstrumentType | None:
    try:
        return InstrumentType(instrument_type)
    except ValueError:
        return None


def _empty_proposal_row(
    *,
    snapshot: PositionSnapshot,
    instrument: Instrument,
    mapping: InstrumentMappingView,
    status: QuoteStatus,
    message: str | None,
) -> QuotePreviewRow:
    return QuotePreviewRow(
        position_snapshot_id=snapshot.id,
        account_id=snapshot.account_id,
        instrument_id=snapshot.instrument_id,
        instrument_name=instrument.name,
        instrument_type=instrument.instrument_type,
        mapping_state=mapping.state,
        identity=mapping.identity,
        current_market_price_kopecks=snapshot.market_price_per_unit_kopecks,
        current_price_date=snapshot.price_date,
        current_price_source=snapshot.price_source,
        proposed_market_price_kopecks=None,
        proposed_price_date=None,
        proposed_quote_kind=None,
        proposed_raw_price=None,
        proposed_raw_price_basis=None,
        fetched_at_utc=None,
        freshness_status=None,
        status=status,
        message=message,
        apply_allowed=False,
    )


def _apply_allowed(*, month_editable: bool, status: QuoteStatus, has_proposal: bool) -> bool:
    return month_editable and has_proposal and status is QuoteStatus.OK


def _row_from_quote(
    *,
    snapshot: PositionSnapshot,
    instrument: Instrument,
    mapping: InstrumentMappingView,
    identity: MarketIdentity,
    result: QuoteResult,
    target_date: date,
    month_editable: bool,
) -> QuotePreviewRow:
    if isinstance(result, QuoteFailure):
        return _empty_proposal_row(
            snapshot=snapshot,
            instrument=instrument,
            mapping=mapping,
            status=result.status,
            message=result.message,
        )
    if result.price_date > target_date:
        return _empty_proposal_row(
            snapshot=snapshot,
            instrument=instrument,
            mapping=mapping,
            status=QuoteStatus.MALFORMED_RESPONSE,
            message="quote price_date is after target_date",
        )
    status = result.freshness_status
    if status not in {QuoteStatus.OK, QuoteStatus.STALE}:
        return _empty_proposal_row(
            snapshot=snapshot,
            instrument=instrument,
            mapping=mapping,
            status=status,
            message=None,
        )
    return QuotePreviewRow(
        position_snapshot_id=snapshot.id,
        account_id=snapshot.account_id,
        instrument_id=snapshot.instrument_id,
        instrument_name=instrument.name,
        instrument_type=instrument.instrument_type,
        mapping_state=mapping.state,
        identity=identity,
        current_market_price_kopecks=snapshot.market_price_per_unit_kopecks,
        current_price_date=snapshot.price_date,
        current_price_source=snapshot.price_source,
        proposed_market_price_kopecks=result.proposed_price_kopecks,
        proposed_price_date=result.price_date,
        proposed_quote_kind=result.quote_kind,
        proposed_raw_price=result.raw_price,
        proposed_raw_price_basis=result.raw_price_basis,
        fetched_at_utc=result.fetched_at_utc,
        freshness_status=status,
        status=status,
        message=None,
        apply_allowed=_apply_allowed(
            month_editable=month_editable,
            status=status,
            has_proposal=True,
        ),
    )


def _fetch_quotes(
    provider: MarketDataProvider,
    items: Sequence[tuple[MarketIdentity, date]],
) -> dict[tuple[str, str, str, str, str], QuoteResult]:
    if not items:
        return {}

    results: list[QuoteResult] | None
    try:
        fetched = provider.fetch_quotes(items)
        results = list(fetched) if len(fetched) == len(items) else None
    except Exception:
        results = None

    if results is None:
        results = []
        for identity, target_date in items:
            try:
                results.append(provider.fetch_quote(identity, target_date))
            except Exception:
                results.append(
                    QuoteFailure(
                        status=QuoteStatus.NETWORK_ERROR,
                        message="market-data provider failed",
                        identity=identity,
                    )
                )

    mapped: dict[tuple[str, str, str, str, str], QuoteResult] = {}
    for (identity, _target), result in zip(items, results, strict=True):
        mapped[_identity_key(identity)] = result
    return mapped


def preview_market_quotes(
    session: Session,
    reporting_month_id: int,
    *,
    provider: MarketDataProvider,
    today: date,
) -> QuotePreviewResult:
    month = get_reporting_month(session, reporting_month_id)
    target_date = quote_refresh_target_date(month.snapshot_date, today=today)
    month_status = ReportingMonthStatus(month.status)
    month_editable = month_status is ReportingMonthStatus.DRAFT

    snapshots = list(
        session.scalars(
            select(PositionSnapshot)
            .where(PositionSnapshot.reporting_month_id == reporting_month_id)
            .order_by(
                PositionSnapshot.account_id,
                PositionSnapshot.instrument_id,
                PositionSnapshot.id,
            )
        )
    )

    instrument_cache: dict[int, Instrument] = {}
    mapping_cache: dict[int, InstrumentMappingView] = {}
    fetch_items: list[tuple[MarketIdentity, date]] = []
    fetch_keys: set[tuple[str, str, str, str, str]] = set()
    plans: list[tuple[PositionSnapshot, Instrument, InstrumentMappingView]] = []

    for snapshot in snapshots:
        instrument_id = snapshot.instrument_id
        if instrument_id not in instrument_cache:
            instrument_cache[instrument_id] = get_instrument(session, instrument_id)
            mapping_cache[instrument_id] = get_instrument_mapping(session, instrument_id)
        instrument = instrument_cache[instrument_id]
        mapping = mapping_cache[instrument_id]
        plans.append((snapshot, instrument, mapping))

        if mapping.state is MarketMappingState.MAPPED and mapping.identity is not None:
            kind = _coerce_kind(instrument.instrument_type)
            if kind in SUPPORTED_KINDS:
                key = _identity_key(mapping.identity)
                if key not in fetch_keys:
                    fetch_keys.add(key)
                    fetch_items.append((mapping.identity, target_date))

    quotes = _fetch_quotes(provider, fetch_items)

    rows: list[QuotePreviewRow] = []
    for snapshot, instrument, mapping in plans:
        if mapping.state is MarketMappingState.EXCLUDED:
            rows.append(
                _empty_proposal_row(
                    snapshot=snapshot,
                    instrument=instrument,
                    mapping=mapping,
                    status=QuoteStatus.EXCLUDED,
                    message=None,
                )
            )
            continue

        kind = _coerce_kind(instrument.instrument_type)
        if kind not in SUPPORTED_KINDS:
            rows.append(
                _empty_proposal_row(
                    snapshot=snapshot,
                    instrument=instrument,
                    mapping=mapping,
                    status=QuoteStatus.UNSUPPORTED,
                    message=None,
                )
            )
            continue

        if mapping.state is MarketMappingState.UNMAPPED or mapping.identity is None:
            rows.append(
                _empty_proposal_row(
                    snapshot=snapshot,
                    instrument=instrument,
                    mapping=mapping,
                    status=QuoteStatus.UNMAPPED,
                    message=None,
                )
            )
            continue

        result = quotes.get(_identity_key(mapping.identity))
        if result is None:
            result = QuoteFailure(
                status=QuoteStatus.UNAVAILABLE,
                message="market-data quote is missing",
                identity=mapping.identity,
            )
        rows.append(
            _row_from_quote(
                snapshot=snapshot,
                instrument=instrument,
                mapping=mapping,
                identity=mapping.identity,
                result=result,
                target_date=target_date,
                month_editable=month_editable,
            )
        )

    batch_error = None
    if (
        fetch_items
        and quotes
        and all(
            isinstance(result, QuoteFailure) and result.status is QuoteStatus.NETWORK_ERROR
            for result in quotes.values()
        )
    ):
        batch_error = "market-data provider network error"

    _require_read_only(session)
    return QuotePreviewResult(
        reporting_month_id=month.id,
        month_status=month_status,
        target_date=target_date,
        month_editable=month_editable,
        batch_error=batch_error,
        rows=tuple(rows),
    )
