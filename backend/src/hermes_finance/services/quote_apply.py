"""Explicit selective quote apply with immutable snapshot provenance (R04-06)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from hermes_finance.domain import PriceSource
from hermes_finance.market_data.dto import T_INVEST_PROVIDER, MarketIdentity, QuoteStatus
from hermes_finance.market_data.protocol import MarketDataProvider
from hermes_finance.persistence import PositionQuoteProvenance, PositionSnapshot
from hermes_finance.services._guard import require_editable_reporting_month
from hermes_finance.services.positions import apply_snapshot_market_quote, get_position_snapshot
from hermes_finance.services.quote_preview import QuotePreviewRow, preview_market_quotes
from hermes_finance.services.quote_preview_evidence import (
    QuotePreviewEvidenceError,
    QuotePreviewEvidenceStore,
    capture_context,
    frozen_last,
)


class PreviewChangedError(Exception):
    code = "preview_changed"

    def __init__(self) -> None:
        super().__init__("quote changed since preview; request a new preview")


@dataclass(frozen=True, slots=True)
class QuoteApplySelection:
    position_snapshot_id: int
    accept_stale: bool
    expected_market_price_kopecks: int
    expected_price_date: date
    expected_identity: MarketIdentity
    expected_quote_kind: str | None = None


@dataclass(frozen=True, slots=True)
class QuoteApplyRowResult:
    position_snapshot_id: int
    market_price_per_unit_kopecks: int
    market_value_kopecks: int
    unrealized_result_kopecks: int
    accrued_interest_kopecks: int | None
    price_date: date
    price_source: str
    freshness: str


@dataclass(frozen=True, slots=True)
class QuoteApplyResult:
    reporting_month_id: int
    applied_count: int
    rows: tuple[QuoteApplyRowResult, ...]


def _preview_by_snapshot(rows: Sequence[QuotePreviewRow]) -> dict[int, QuotePreviewRow]:
    return {row.position_snapshot_id: row for row in rows}


def _identity_matches(actual: MarketIdentity | None, expected: MarketIdentity) -> bool:
    if actual is None:
        return False
    return (
        actual.provider == expected.provider
        and actual.provider_instrument_id == expected.provider_instrument_id
        and actual.provider_venue_id == expected.provider_venue_id
    )


def _materially_changed(row: QuotePreviewRow, selection: QuoteApplySelection) -> bool:
    if row.proposed_market_price_kopecks != selection.expected_market_price_kopecks:
        return True
    if row.proposed_price_date != selection.expected_price_date:
        return True
    if not _identity_matches(row.identity, selection.expected_identity):
        return True
    if selection.expected_quote_kind is not None:
        actual_kind = row.proposed_quote_kind.value if row.proposed_quote_kind else None
        if actual_kind != selection.expected_quote_kind:
            return True
    return False


def _eligible_preview_row(row: QuotePreviewRow, selection: QuoteApplySelection) -> None:
    if row.identity is None or row.identity.provider != T_INVEST_PROVIDER:
        raise ValueError("production apply is T-Invest only")
    if row.proposed_market_price_kopecks is None or row.proposed_price_date is None:
        raise ValueError("quote status cannot be applied")
    if row.status is QuoteStatus.OK:
        return
    if row.status is QuoteStatus.STALE:
        if not selection.accept_stale:
            raise ValueError("stale quote was not explicitly selected")
        return
    raise ValueError("quote status cannot be applied")


def _append_provenance(
    session: Session,
    *,
    snapshot: PositionSnapshot,
    row: QuotePreviewRow,
    applied_at: datetime,
    target_date: date,
) -> None:
    assert row.identity is not None
    assert row.proposed_market_price_kopecks is not None
    assert row.proposed_price_date is not None
    assert row.proposed_quote_kind is not None
    assert row.proposed_raw_price is not None
    assert row.proposed_raw_price_basis is not None
    assert row.fetched_at_utc is not None
    session.add(
        PositionQuoteProvenance(
            position_snapshot_id=snapshot.id,
            reporting_month_id=snapshot.reporting_month_id,
            provider=row.identity.provider,
            provider_instrument_id=row.identity.provider_instrument_id,
            provider_venue_id=row.identity.provider_venue_id,
            quote_kind=row.proposed_quote_kind.value,
            raw_price=row.proposed_raw_price,
            raw_price_basis=row.proposed_raw_price_basis.value,
            normalized_price_kopecks=row.proposed_market_price_kopecks,
            price_date=row.proposed_price_date,
            fetched_at_utc=row.fetched_at_utc,
            target_date=target_date,
            freshness=row.status.value,
            applied_at_utc=applied_at,
        )
    )


def apply_market_quotes(
    session: Session,
    reporting_month_id: int,
    selections: Sequence[QuoteApplySelection],
    *,
    provider: MarketDataProvider,
    today: date,
    clock: datetime | None = None,
    evidence_store: QuotePreviewEvidenceStore | None = None,
    preview_id: str | None = None,
    current_day: Callable[[], date] | None = None,
) -> QuoteApplyResult:
    """Claim Q645-C1 evidence; strictly refetch all non-frozen selected rows."""

    if not selections:
        raise ValueError("at least one quote row must be selected")
    seen: set[int] = set()
    for selection in selections:
        if selection.position_snapshot_id in seen:
            raise ValueError("duplicate position snapshot in apply selection")
        seen.add(selection.position_snapshot_id)

    evidence = None
    frozen: dict[int, QuotePreviewRow] = {}
    if preview_id is not None:
        if evidence_store is None:
            raise QuotePreviewEvidenceError()
        evidence = evidence_store.claim(reporting_month_id, preview_id, today)
        frozen = {
            row.position_snapshot_id: row
            for row in evidence.preview.rows
            if row.position_snapshot_id in seen
            and frozen_last(row, evidence.preview.target_date, today)
        }

    require_editable_reporting_month(session, reporting_month_id)
    session.expire_all()
    if evidence is not None:
        actual = capture_context(session, reporting_month_id)
        if actual.selected(seen) != evidence.context.selected(seen):
            raise QuotePreviewEvidenceError()
        if not seen.issubset({row.position_snapshot_id for row in evidence.preview.rows}):
            raise QuotePreviewEvidenceError()
    preview = preview_market_quotes(
        session,
        reporting_month_id,
        provider=provider,
        today=today,
        snapshot_ids=seen - frozen.keys(),
    )
    by_snapshot = _preview_by_snapshot(preview.rows)
    by_snapshot.update(frozen)
    planned: list[tuple[QuoteApplySelection, QuotePreviewRow, PositionSnapshot]] = []
    for selection in selections:
        snapshot = get_position_snapshot(session, selection.position_snapshot_id)
        if snapshot.reporting_month_id != reporting_month_id:
            raise ValueError("position snapshot does not belong to the reporting month")
        row = by_snapshot.get(selection.position_snapshot_id)
        if row is None:
            raise ValueError("position snapshot has no quote preview row")
        _eligible_preview_row(row, selection)
        if (
            frozen_last(row, preview.target_date, today)
            and selection.position_snapshot_id not in frozen
        ):
            raise QuotePreviewEvidenceError()
        if selection.position_snapshot_id in frozen and selection.expected_quote_kind != "last":
            raise PreviewChangedError()
        if _materially_changed(row, selection):
            raise PreviewChangedError()
        planned.append((selection, row, snapshot))

    applied_at = clock or datetime.now(UTC)
    try:
        if evidence is not None:
            assert evidence_store is not None
            evidence_store.validate_lifetime(evidence, current_day() if current_day else today)
        applied: list[QuoteApplyRowResult] = []
        for _selection, row, snapshot in planned:
            apply_snapshot_market_quote(
                session,
                snapshot,
                market_price_per_unit_kopecks=row.proposed_market_price_kopecks or 0,
                price_date=row.proposed_price_date or preview.target_date,
                price_source=PriceSource.T_INVEST,
            )
            _append_provenance(
                session,
                snapshot=snapshot,
                row=row,
                applied_at=applied_at,
                target_date=preview.target_date,
            )
            applied.append(
                QuoteApplyRowResult(
                    position_snapshot_id=snapshot.id,
                    market_price_per_unit_kopecks=snapshot.market_price_per_unit_kopecks,
                    market_value_kopecks=snapshot.market_value_kopecks,
                    unrealized_result_kopecks=snapshot.unrealized_result_kopecks,
                    accrued_interest_kopecks=snapshot.accrued_interest_kopecks,
                    price_date=snapshot.price_date,
                    price_source=snapshot.price_source,
                    freshness=row.status.value,
                )
            )
        session.commit()
    except Exception:
        session.rollback()
        raise

    for item in applied:
        session.refresh(get_position_snapshot(session, item.position_snapshot_id))
    return QuoteApplyResult(
        reporting_month_id=reporting_month_id,
        applied_count=len(applied),
        rows=tuple(applied),
    )
