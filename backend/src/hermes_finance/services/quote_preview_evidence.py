"""Bounded process-local Q645-C1 observations. No persistence or provider calls."""

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from secrets import token_urlsafe
from threading import Lock
from time import monotonic

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.market_data.dto import T_INVEST_PROVIDER, QuoteKind, QuoteStatus
from hermes_finance.persistence import (
    Account,
    Instrument,
    InstrumentMarketMapping,
    PositionSnapshot,
    ReportingMonth,
)
from hermes_finance.services.quote_preview import QuotePreviewResult, QuotePreviewRow


class QuotePreviewEvidenceError(Exception):
    code = "preview_evidence_invalid"

    def __init__(self) -> None:
        super().__init__("preview evidence is unavailable or changed; request a new preview")


def frozen_last(row: QuotePreviewRow, target_date: date, today: date) -> bool:
    return (
        target_date == today
        and row.proposed_price_date == target_date
        and row.identity is not None
        and row.identity.provider == T_INVEST_PROVIDER
        and row.proposed_quote_kind is QuoteKind.LAST
        and row.status is QuoteStatus.OK
    )


@dataclass(frozen=True, slots=True)
class PreviewContext:
    month: tuple
    # Full scalar row values, including revision timestamps; never ORM references.
    positions: tuple[tuple[int, tuple], ...]

    def selected(self, ids: set[int]) -> tuple:
        return self.month, tuple(item for item in self.positions if item[0] in ids)


def capture_context(session: Session, month_id: int) -> PreviewContext:
    """Core reads bypass the identity map; Apply calls this under writer reservation."""
    month = session.execute(
        select(ReportingMonth.__table__).where(ReportingMonth.id == month_id)
    ).one_or_none()
    rows = session.execute(
        select(
            PositionSnapshot.__table__,
            Instrument.__table__,
            InstrumentMarketMapping.__table__,
            Account.__table__,
        )
        .select_from(PositionSnapshot)
        .join(Instrument, Instrument.id == PositionSnapshot.instrument_id)
        .outerjoin(InstrumentMarketMapping, InstrumentMarketMapping.instrument_id == Instrument.id)
        .join(Account, Account.id == PositionSnapshot.account_id)
        .where(PositionSnapshot.reporting_month_id == month_id)
        .order_by(PositionSnapshot.id)
    ).all()
    return PreviewContext(
        month=tuple(month) if month else (),
        positions=tuple((row[0], tuple(row)) for row in rows),
    )


@dataclass(frozen=True, slots=True)
class PreviewStart:
    preview_id: str
    started: float
    day: date


@dataclass(frozen=True, slots=True)
class PreviewEvidence:
    start: PreviewStart
    context: PreviewContext
    preview: QuotePreviewResult


class QuotePreviewEvidenceStore:
    """One latest preview per month, bounded in memory; every claim consumes it."""

    def __init__(self, clock: Callable[[], float] = monotonic) -> None:
        self.clock = clock
        self._lock = Lock()
        self._latest: OrderedDict[int, tuple[PreviewStart, PreviewEvidence | None]] = OrderedDict()

    def begin(self, month_id: int, today: date) -> PreviewStart:
        with self._lock:
            start = PreviewStart(token_urlsafe(32), self.clock(), today)
            self._latest[month_id] = start, None
            self._latest.move_to_end(month_id)
            while len(self._latest) > 128:
                self._latest.popitem(last=False)
            return start

    def validate_lifetime(self, evidence: PreviewEvidence, today: date) -> None:
        elapsed = self.clock() - evidence.start.started
        if today != evidence.start.day or not 0 <= elapsed < 120:
            raise QuotePreviewEvidenceError()

    def publish(
        self, start: PreviewStart, context: PreviewContext, preview: QuotePreviewResult, today: date
    ) -> str | None:
        with self._lock:
            evidence = PreviewEvidence(start, context, preview)
            if self._latest.get(preview.reporting_month_id) != (start, None):
                return None
            try:
                self.validate_lifetime(evidence, today)
            except QuotePreviewEvidenceError:
                return None
            self._latest[preview.reporting_month_id] = start, evidence
            return start.preview_id

    def claim(self, month_id: int, preview_id: str, today: date) -> PreviewEvidence:
        with self._lock:
            current = self._latest.get(month_id)
            if current is None or current[0].preview_id != preview_id or current[1] is None:
                raise QuotePreviewEvidenceError()
            del self._latest[month_id]
            evidence = current[1]
            self.validate_lifetime(evidence, today)
            return evidence
