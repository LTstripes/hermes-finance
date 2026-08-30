"""Read-only freshness/provenance summary for a selected reporting month (R07-07).

Four clocks stay distinct: source timestamp, import/apply time, reporting month,
and local edit time. There is no universal freshness score. This module does not
call providers or write provenance.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hermes_finance.domain import PriceSource
from hermes_finance.market_data.dto import QuoteStatus
from hermes_finance.market_data.normalize import (
    NormalizeError,
    classify_freshness,
    quote_refresh_target_date,
)
from hermes_finance.persistence import (
    Account,
    AppliedPayoutRevision,
    AppliedProviderPayout,
    AppliedStatementEvent,
    AppliedStatementEventRevision,
    BrokerBaselineApply,
    BrokerBaselineApplyItem,
    CashBalance,
    DepositSnapshot,
    ExpectedCashFlow,
    ExpenseEntry,
    IncomeEntry,
    Instrument,
    InstrumentMarketMapping,
    InvestmentCashFlow,
    PositionQuoteProvenance,
    PositionSnapshot,
    SavingAllocation,
)
from hermes_finance.services.reporting_months import get_reporting_month

PROVIDER_PRICE_SOURCES = frozenset({PriceSource.T_INVEST.value, PriceSource.MOEX.value})
MANUAL_PRICE_SOURCES = frozenset({PriceSource.MANUAL.value, PriceSource.ALFA_PDF.value})


class FreshnessFamilyId(StrEnum):
    MARKET_QUOTES = "market_quotes"
    T_INVEST_PAYOUTS = "t_invest_payouts"
    ALFA_PRO_POSITIONS = "alfa_pro_positions"
    ALFA_STATEMENT_PAYOUTS = "alfa_statement_payouts"
    MANUAL_MONTH_DATA = "manual_month_data"
    DEPOSIT_CASH_SNAPSHOTS = "deposit_cash_snapshots"


class FreshnessStatus(StrEnum):
    CURRENT = "current"
    STALE = "stale"
    MIXED = "mixed"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"
    MISSING = "missing"


class FreshnessSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"


class FreshnessReasonCode(StrEnum):
    QUOTE_CURRENT = "quote_current"
    QUOTE_STALE = "quote_stale"
    QUOTE_UNAVAILABLE = "quote_unavailable"
    QUOTE_SOURCE_TIMESTAMP_INCONSISTENT = "quote_source_timestamp_inconsistent"
    MAPPED_QUOTE_NOT_APPLIED = "mapped_quote_not_applied"
    MANUAL_SOURCE_NO_PROVIDER_TIMESTAMP = "manual_source_no_provider_timestamp"
    HISTORICAL_QUOTE_PROVENANCE_PRESENT = "historical_quote_provenance_present"
    PAYOUT_EVENT_PRESENT = "payout_event_present"
    PAYOUT_NONE_FOR_MONTH = "payout_none_for_month"
    PAYOUT_NOT_FRESHNESS_CLASSIFIED = "payout_not_freshness_classified"
    ALFA_PRO_OBSERVATION_NOT_PERSISTED = "alfa_pro_observation_not_persisted"
    ALFA_PRO_BASELINE_PRESENT = "alfa_pro_baseline_present"
    ALFA_PRO_OBSERVATION_NOT_FRESHNESS_CLASSIFIED = "alfa_pro_observation_not_freshness_classified"
    STATEMENT_EVENT_PRESENT = "statement_event_present"
    STATEMENT_NONE_FOR_MONTH = "statement_none_for_month"
    STATEMENT_NOT_FRESHNESS_CLASSIFIED = "statement_not_freshness_classified"
    MANUAL_MONTH_DATA_PRESENT = "manual_month_data_present"
    MANUAL_MONTH_DATA_EMPTY = "manual_month_data_empty"
    DEPOSIT_CASH_PRESENT = "deposit_cash_present"
    DEPOSIT_CASH_EMPTY = "deposit_cash_empty"
    DEPOSIT_CASH_LOCAL_EDIT_ONLY = "deposit_cash_local_edit_only"
    SOURCE_TIMESTAMP_UNAVAILABLE = "source_timestamp_unavailable"
    MULTIPLE_PROVIDERS = "multiple_providers"


class SourceTimestampKind(StrEnum):
    PRICE_DATE = "price_date"
    PAYMENT_DATE = "payment_date"
    EVENT_DATE = "event_date"
    RECORD_DATE = "record_date"
    FETCHED_AT = "fetched_at"
    SOURCE_AS_OF = "source_as_of"
    UNAVAILABLE = "unavailable"
    NOT_APPLICABLE = "not_applicable"


_REASON_TEXT: dict[FreshnessReasonCode, str] = {
    FreshnessReasonCode.QUOTE_CURRENT: "Есть применённые котировки, актуальные относительно даты оценки месяца.",
    FreshnessReasonCode.QUOTE_STALE: "Есть применённые котировки старше окна актуальности относительно даты оценки месяца.",
    FreshnessReasonCode.QUOTE_UNAVAILABLE: "Есть применённые котировки старше 30 дней относительно даты оценки месяца.",
    FreshnessReasonCode.QUOTE_SOURCE_TIMESTAMP_INCONSISTENT: (
        "Дата котировки позже даты оценки месяца; актуальность не классифицируется."
    ),
    FreshnessReasonCode.MAPPED_QUOTE_NOT_APPLIED: (
        "Есть привязка к провайдеру котировок, но текущая цена не из провайдера."
    ),
    FreshnessReasonCode.MANUAL_SOURCE_NO_PROVIDER_TIMESTAMP: (
        "Ручные значения без времени наблюдения провайдера не считаются устаревшими."
    ),
    FreshnessReasonCode.HISTORICAL_QUOTE_PROVENANCE_PRESENT: (
        "Сохранена историческая provenance котировки после ручного переопределения."
    ),
    FreshnessReasonCode.PAYOUT_EVENT_PRESENT: "В месяце есть принятые выплаты T-Invest.",
    FreshnessReasonCode.PAYOUT_NONE_FOR_MONTH: "В месяце нет принятых выплат T-Invest.",
    FreshnessReasonCode.PAYOUT_NOT_FRESHNESS_CLASSIFIED: (
        "Дата выплаты — событие, а не котировка; по возрасту она не помечается устаревшей."
    ),
    FreshnessReasonCode.ALFA_PRO_OBSERVATION_NOT_PERSISTED: (
        "Hermes не сохраняет время наблюдения Alfa PRO после apply, поэтому актуальность "
        "этой семьи нельзя честно классифицировать."
    ),
    FreshnessReasonCode.ALFA_PRO_BASELINE_PRESENT: (
        "В месяце есть подтверждённый владельцем текущий срез Alfa PRO."
    ),
    FreshnessReasonCode.ALFA_PRO_OBSERVATION_NOT_FRESHNESS_CLASSIFIED: (
        "Время наблюдения Alfa PRO сохранено; confirmed_at — время применения, не актуальность."
    ),
    FreshnessReasonCode.STATEMENT_EVENT_PRESENT: "В месяце есть принятые события выписки Alfa.",
    FreshnessReasonCode.STATEMENT_NONE_FOR_MONTH: "В месяце нет принятых событий выписки Alfa.",
    FreshnessReasonCode.STATEMENT_NOT_FRESHNESS_CLASSIFIED: (
        "Дата в выписке — событие документа, а не котировка; по возрасту она не устаревает."
    ),
    FreshnessReasonCode.MANUAL_MONTH_DATA_PRESENT: "В месяце есть данные, которые ведутся вручную.",
    FreshnessReasonCode.MANUAL_MONTH_DATA_EMPTY: "В месяце нет ручных доходов, расходов, накоплений и ожидаемых выплат.",
    FreshnessReasonCode.DEPOSIT_CASH_PRESENT: "В месяце есть депозиты или остатки кэша.",
    FreshnessReasonCode.DEPOSIT_CASH_EMPTY: "В месяце нет депозитов и остатков кэша.",
    FreshnessReasonCode.DEPOSIT_CASH_LOCAL_EDIT_ONLY: (
        "Для депозитов/кэша есть только локальное время правки, не время наблюдения провайдера."
    ),
    FreshnessReasonCode.SOURCE_TIMESTAMP_UNAVAILABLE: (
        "Время наблюдения провайдера отсутствует; это не означает, что данные устарели."
    ),
    FreshnessReasonCode.MULTIPLE_PROVIDERS: "В выбранном месяце есть данные более чем одного провайдера.",
}


@dataclass(frozen=True, slots=True)
class FreshnessReason:
    code: FreshnessReasonCode
    severity: FreshnessSeverity
    message: str


@dataclass(frozen=True, slots=True)
class FreshnessCoverage:
    row_count: int
    current_count: int = 0
    stale_count: int = 0
    unavailable_count: int = 0
    unknown_count: int = 0
    missing_count: int = 0
    manual_count: int = 0
    provider_count: int = 0


@dataclass(frozen=True, slots=True)
class FreshnessItem:
    item_kind: str
    label: str
    freshness_status: FreshnessStatus
    source_kind: str
    source_timestamp_kind: SourceTimestampKind
    source_date: date | None
    source_datetime: datetime | None
    fetched_at: datetime | None
    import_apply_time: datetime | None
    local_edit_time: datetime | None
    reason_codes: tuple[FreshnessReasonCode, ...]
    account_name: str | None = None
    instrument_name: str | None = None


@dataclass(frozen=True, slots=True)
class FreshnessFamily:
    family_id: FreshnessFamilyId
    title: str
    status: FreshnessStatus
    providers: tuple[str, ...]
    coverage: FreshnessCoverage
    reasons: tuple[FreshnessReason, ...]
    items: tuple[FreshnessItem, ...]


@dataclass(frozen=True, slots=True)
class ReportingMonthContext:
    id: int
    year: int
    month: int
    status: str
    snapshot_date: date
    source: str


@dataclass(frozen=True, slots=True)
class FreshnessProvenanceSummary:
    reporting_month: ReportingMonthContext
    evaluated_on: date
    quote_valuation_target_date: date
    generated_at: datetime
    families: tuple[FreshnessFamily, ...]
    reasons: tuple[FreshnessReason, ...]
    providers: tuple[str, ...]


def _reason(code: FreshnessReasonCode, severity: FreshnessSeverity) -> FreshnessReason:
    return FreshnessReason(code=code, severity=severity, message=_REASON_TEXT[code])


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _dedupe_reasons(reasons: list[FreshnessReason]) -> tuple[FreshnessReason, ...]:
    seen: set[FreshnessReasonCode] = set()
    ordered: list[FreshnessReason] = []
    for reason in reasons:
        if reason.code in seen:
            continue
        seen.add(reason.code)
        ordered.append(reason)
    return tuple(ordered)


def _iso_providers(values: set[str]) -> tuple[str, ...]:
    return tuple(sorted(values))


def _quote_item_status(
    price_date: date, target_date: date
) -> tuple[FreshnessStatus, FreshnessReasonCode]:
    try:
        classified = classify_freshness(target_date, price_date)
    except NormalizeError:
        return FreshnessStatus.UNKNOWN, FreshnessReasonCode.QUOTE_SOURCE_TIMESTAMP_INCONSISTENT
    if classified is QuoteStatus.OK:
        return FreshnessStatus.CURRENT, FreshnessReasonCode.QUOTE_CURRENT
    if classified is QuoteStatus.STALE:
        return FreshnessStatus.STALE, FreshnessReasonCode.QUOTE_STALE
    return FreshnessStatus.UNAVAILABLE, FreshnessReasonCode.QUOTE_UNAVAILABLE


def _family_status_from_quote_counts(coverage: FreshnessCoverage) -> FreshnessStatus:
    classified = coverage.current_count + coverage.stale_count + coverage.unavailable_count
    if classified == 0:
        if coverage.row_count == 0:
            return FreshnessStatus.MISSING
        if coverage.unknown_count:
            return FreshnessStatus.UNKNOWN
        return FreshnessStatus.NOT_APPLICABLE
    distinct = {
        status
        for status, count in (
            (FreshnessStatus.CURRENT, coverage.current_count),
            (FreshnessStatus.STALE, coverage.stale_count),
            (FreshnessStatus.UNAVAILABLE, coverage.unavailable_count),
        )
        if count
    }
    if len(distinct) == 1:
        return next(iter(distinct))
    return FreshnessStatus.MIXED


def _name_maps(
    session: Session, account_ids: set[int], instrument_ids: set[int]
) -> tuple[dict[int, str], dict[int, str]]:
    accounts = {
        row.id: row.name
        for row in session.scalars(select(Account).where(Account.id.in_(account_ids or {-1}))).all()
    }
    instruments = {
        row.id: row.name
        for row in session.scalars(
            select(Instrument).where(Instrument.id.in_(instrument_ids or {-1}))
        ).all()
    }
    return accounts, instruments


def _latest_quote_provenance(session: Session, month_id: int) -> dict[int, PositionQuoteProvenance]:
    rows = session.scalars(
        select(PositionQuoteProvenance)
        .where(PositionQuoteProvenance.reporting_month_id == month_id)
        .order_by(
            PositionQuoteProvenance.position_snapshot_id,
            PositionQuoteProvenance.applied_at_utc.desc(),
            PositionQuoteProvenance.id.desc(),
        )
    ).all()
    latest: dict[int, PositionQuoteProvenance] = {}
    for row in rows:
        latest.setdefault(row.position_snapshot_id, row)
    return latest


def _refresh_eligible_instrument_ids(session: Session) -> set[int]:
    rows = session.scalars(select(InstrumentMarketMapping)).all()
    return {
        row.instrument_id
        for row in rows
        if not row.excluded and row.provider and row.provider_instrument_id
    }


def _build_market_quotes(
    session: Session,
    *,
    month_id: int,
    target_date: date,
) -> FreshnessFamily:
    snapshots = list(
        session.scalars(
            select(PositionSnapshot)
            .where(PositionSnapshot.reporting_month_id == month_id)
            .order_by(PositionSnapshot.id)
        )
    )
    provenance_by_snapshot = _latest_quote_provenance(session, month_id)
    mapped_ids = _refresh_eligible_instrument_ids(session)
    accounts, instruments = _name_maps(
        session,
        {row.account_id for row in snapshots},
        {row.instrument_id for row in snapshots},
    )
    items: list[FreshnessItem] = []
    family_reasons: list[FreshnessReason] = []
    providers: set[str] = set()
    current_count = stale_count = unavailable_count = unknown_count = 0
    missing_count = manual_count = provider_count = 0

    for snapshot in snapshots:
        quote = provenance_by_snapshot.get(snapshot.id)
        account_name = accounts.get(snapshot.account_id, f"account-{snapshot.account_id}")
        instrument_name = instruments.get(
            snapshot.instrument_id, f"instrument-{snapshot.instrument_id}"
        )
        mapped = snapshot.instrument_id in mapped_ids
        codes: list[FreshnessReasonCode] = []
        if snapshot.price_source in PROVIDER_PRICE_SOURCES and quote is not None:
            status, code = _quote_item_status(quote.price_date, target_date)
            codes.append(code)
            providers.add(quote.provider)
            provider_count += 1
            if status is FreshnessStatus.CURRENT:
                current_count += 1
            elif status is FreshnessStatus.STALE:
                stale_count += 1
            elif status is FreshnessStatus.UNAVAILABLE:
                unavailable_count += 1
            else:
                unknown_count += 1
            items.append(
                FreshnessItem(
                    item_kind="quote",
                    label=instrument_name,
                    freshness_status=status,
                    source_kind=snapshot.price_source,
                    source_timestamp_kind=SourceTimestampKind.PRICE_DATE,
                    source_date=quote.price_date,
                    source_datetime=None,
                    fetched_at=_utc(quote.fetched_at_utc),
                    import_apply_time=_utc(quote.applied_at_utc),
                    local_edit_time=_utc(snapshot.updated_at),
                    reason_codes=tuple(codes),
                    account_name=account_name,
                    instrument_name=instrument_name,
                )
            )
            continue

        if snapshot.price_source in PROVIDER_PRICE_SOURCES:
            unknown_count += 1
            codes.append(FreshnessReasonCode.SOURCE_TIMESTAMP_UNAVAILABLE)
            if mapped:
                missing_count += 1
                codes.append(FreshnessReasonCode.MAPPED_QUOTE_NOT_APPLIED)
            items.append(
                FreshnessItem(
                    item_kind="quote",
                    label=instrument_name,
                    freshness_status=FreshnessStatus.UNKNOWN,
                    source_kind=snapshot.price_source,
                    source_timestamp_kind=SourceTimestampKind.UNAVAILABLE,
                    source_date=None,
                    source_datetime=None,
                    fetched_at=None,
                    import_apply_time=None,
                    local_edit_time=_utc(snapshot.updated_at),
                    reason_codes=tuple(codes),
                    account_name=account_name,
                    instrument_name=instrument_name,
                )
            )
            continue

        manual_count += 1
        codes.append(FreshnessReasonCode.MANUAL_SOURCE_NO_PROVIDER_TIMESTAMP)
        if quote is not None:
            codes.append(FreshnessReasonCode.HISTORICAL_QUOTE_PROVENANCE_PRESENT)
            family_reasons.append(
                _reason(
                    FreshnessReasonCode.HISTORICAL_QUOTE_PROVENANCE_PRESENT, FreshnessSeverity.INFO
                )
            )
        if mapped:
            missing_count += 1
            codes.append(FreshnessReasonCode.MAPPED_QUOTE_NOT_APPLIED)
        items.append(
            FreshnessItem(
                item_kind="quote",
                label=instrument_name,
                freshness_status=FreshnessStatus.NOT_APPLICABLE,
                source_kind=snapshot.price_source,
                source_timestamp_kind=SourceTimestampKind.NOT_APPLICABLE,
                source_date=None,
                source_datetime=None,
                fetched_at=_utc(quote.fetched_at_utc) if quote is not None else None,
                import_apply_time=_utc(quote.applied_at_utc) if quote is not None else None,
                local_edit_time=_utc(snapshot.updated_at),
                reason_codes=tuple(codes),
                account_name=account_name,
                instrument_name=instrument_name,
            )
        )

    coverage = FreshnessCoverage(
        row_count=len(snapshots),
        current_count=current_count,
        stale_count=stale_count,
        unavailable_count=unavailable_count,
        unknown_count=unknown_count,
        missing_count=missing_count,
        manual_count=manual_count,
        provider_count=provider_count,
    )
    if current_count:
        family_reasons.append(_reason(FreshnessReasonCode.QUOTE_CURRENT, FreshnessSeverity.INFO))
    if stale_count:
        family_reasons.append(_reason(FreshnessReasonCode.QUOTE_STALE, FreshnessSeverity.WARNING))
    if unavailable_count:
        family_reasons.append(
            _reason(FreshnessReasonCode.QUOTE_UNAVAILABLE, FreshnessSeverity.WARNING)
        )
    if unknown_count:
        family_reasons.append(
            _reason(FreshnessReasonCode.SOURCE_TIMESTAMP_UNAVAILABLE, FreshnessSeverity.INFO)
        )
    if missing_count:
        family_reasons.append(
            _reason(FreshnessReasonCode.MAPPED_QUOTE_NOT_APPLIED, FreshnessSeverity.WARNING)
        )
    if manual_count:
        family_reasons.append(
            _reason(FreshnessReasonCode.MANUAL_SOURCE_NO_PROVIDER_TIMESTAMP, FreshnessSeverity.INFO)
        )
    items.sort(key=lambda item: (item.account_name or "", item.instrument_name or "", item.label))
    return FreshnessFamily(
        family_id=FreshnessFamilyId.MARKET_QUOTES,
        title="Рыночные котировки",
        status=_family_status_from_quote_counts(coverage),
        providers=_iso_providers(providers),
        coverage=coverage,
        reasons=_dedupe_reasons(family_reasons),
        items=tuple(items),
    )


def _latest_payout_revision(
    session: Session, payout_ids: list[int]
) -> dict[int, AppliedPayoutRevision]:
    if not payout_ids:
        return {}
    rows = session.scalars(
        select(AppliedPayoutRevision)
        .where(AppliedPayoutRevision.applied_payout_id.in_(payout_ids))
        .order_by(
            AppliedPayoutRevision.applied_payout_id,
            AppliedPayoutRevision.applied_at.desc(),
            AppliedPayoutRevision.id.desc(),
        )
    ).all()
    latest: dict[int, AppliedPayoutRevision] = {}
    for row in rows:
        latest.setdefault(row.applied_payout_id, row)
    return latest


def _build_t_invest_payouts(session: Session, *, month_id: int) -> FreshnessFamily:
    payouts = [
        row
        for row in session.scalars(
            select(AppliedProviderPayout)
            .where(AppliedProviderPayout.reporting_month_id == month_id)
            .order_by(AppliedProviderPayout.id)
        )
        if row.lifecycle == "active"
    ]
    revisions = _latest_payout_revision(session, [row.id for row in payouts])
    accounts, instruments = _name_maps(
        session,
        {row.account_id for row in payouts},
        {row.instrument_id for row in payouts},
    )
    items: list[FreshnessItem] = []
    providers: set[str] = set()
    for payout in payouts:
        revision = revisions.get(payout.id)
        providers.add(payout.provider)
        instrument_name = instruments.get(
            payout.instrument_id, f"instrument-{payout.instrument_id}"
        )
        account_name = accounts.get(payout.account_id, f"account-{payout.account_id}")
        items.append(
            FreshnessItem(
                item_kind="payout",
                label=f"{instrument_name} · {payout.event_kind}",
                freshness_status=FreshnessStatus.NOT_APPLICABLE,
                source_kind=payout.provider,
                source_timestamp_kind=SourceTimestampKind.PAYMENT_DATE,
                source_date=payout.payment_date,
                source_datetime=None,
                fetched_at=_utc(revision.fetched_at) if revision is not None else None,
                import_apply_time=_utc(
                    revision.applied_at if revision is not None else payout.first_applied_at
                ),
                local_edit_time=None,
                reason_codes=(FreshnessReasonCode.PAYOUT_NOT_FRESHNESS_CLASSIFIED,),
                account_name=account_name,
                instrument_name=instrument_name,
            )
        )
    if payouts:
        reasons = (
            _reason(FreshnessReasonCode.PAYOUT_EVENT_PRESENT, FreshnessSeverity.INFO),
            _reason(FreshnessReasonCode.PAYOUT_NOT_FRESHNESS_CLASSIFIED, FreshnessSeverity.INFO),
        )
        status = FreshnessStatus.NOT_APPLICABLE
    else:
        reasons = (_reason(FreshnessReasonCode.PAYOUT_NONE_FOR_MONTH, FreshnessSeverity.INFO),)
        status = FreshnessStatus.MISSING
    return FreshnessFamily(
        family_id=FreshnessFamilyId.T_INVEST_PAYOUTS,
        title="Выплаты T-Invest",
        status=status,
        providers=_iso_providers(providers),
        coverage=FreshnessCoverage(row_count=len(payouts), provider_count=len(payouts)),
        reasons=reasons,
        items=tuple(items),
    )


def _latest_baseline_apply(session: Session, month_id: int) -> BrokerBaselineApply | None:
    return session.scalar(
        select(BrokerBaselineApply)
        .where(BrokerBaselineApply.reporting_month_id == month_id)
        .order_by(BrokerBaselineApply.confirmed_at.desc(), BrokerBaselineApply.id.desc())
    )


def _build_alfa_pro_positions(session: Session, *, month_id: int) -> FreshnessFamily:
    """Alfa PRO family from persisted baseline provenance (ADR 0016 §8).

    ``source_as_of`` is the observation clock. ``confirmed_at`` is apply time and
    is never used as freshness. Capability/configuration alone must not list
    ``alfa_pro`` or contribute it to ``multiple_providers``.
    """

    latest = _latest_baseline_apply(session, month_id)
    if latest is None:
        return FreshnessFamily(
            family_id=FreshnessFamilyId.ALFA_PRO_POSITIONS,
            title="Позиции Alfa PRO",
            status=FreshnessStatus.UNKNOWN,
            providers=(),
            coverage=FreshnessCoverage(row_count=0, unknown_count=1),
            reasons=(
                _reason(
                    FreshnessReasonCode.ALFA_PRO_OBSERVATION_NOT_PERSISTED,
                    FreshnessSeverity.INFO,
                ),
                _reason(FreshnessReasonCode.SOURCE_TIMESTAMP_UNAVAILABLE, FreshnessSeverity.INFO),
            ),
            items=(),
        )

    item_count = (
        session.scalar(
            select(func.count())
            .select_from(BrokerBaselineApplyItem)
            .where(BrokerBaselineApplyItem.baseline_apply_id == latest.id)
        )
        or 0
    )
    source_as_of = _utc(latest.source_as_of)
    captured_at = _utc(latest.captured_at)
    confirmed_at = _utc(latest.confirmed_at)
    item = FreshnessItem(
        item_kind="alfa_pro_baseline",
        label="Текущий срез Alfa PRO",
        freshness_status=FreshnessStatus.NOT_APPLICABLE,
        source_kind=latest.provider,
        source_timestamp_kind=SourceTimestampKind.SOURCE_AS_OF,
        source_date=source_as_of.date() if source_as_of is not None else None,
        source_datetime=source_as_of,
        fetched_at=captured_at,
        import_apply_time=confirmed_at,
        local_edit_time=None,
        reason_codes=(FreshnessReasonCode.ALFA_PRO_OBSERVATION_NOT_FRESHNESS_CLASSIFIED,),
    )
    return FreshnessFamily(
        family_id=FreshnessFamilyId.ALFA_PRO_POSITIONS,
        title="Позиции Alfa PRO",
        status=FreshnessStatus.NOT_APPLICABLE,
        providers=_iso_providers({latest.provider}),
        coverage=FreshnessCoverage(row_count=item_count, provider_count=item_count),
        reasons=(
            _reason(FreshnessReasonCode.ALFA_PRO_BASELINE_PRESENT, FreshnessSeverity.INFO),
            _reason(
                FreshnessReasonCode.ALFA_PRO_OBSERVATION_NOT_FRESHNESS_CLASSIFIED,
                FreshnessSeverity.INFO,
            ),
        ),
        items=(item,),
    )


def _latest_statement_revision(
    session: Session, event_ids: list[int]
) -> dict[int, AppliedStatementEventRevision]:
    if not event_ids:
        return {}
    rows = session.scalars(
        select(AppliedStatementEventRevision)
        .where(AppliedStatementEventRevision.applied_statement_event_id.in_(event_ids))
        .order_by(
            AppliedStatementEventRevision.applied_statement_event_id,
            AppliedStatementEventRevision.applied_at.desc(),
            AppliedStatementEventRevision.id.desc(),
        )
    ).all()
    latest: dict[int, AppliedStatementEventRevision] = {}
    for row in rows:
        latest.setdefault(row.applied_statement_event_id, row)
    return latest


def _build_alfa_statements(session: Session, *, month_id: int) -> FreshnessFamily:
    flows = list(
        session.scalars(
            select(InvestmentCashFlow).where(InvestmentCashFlow.reporting_month_id == month_id)
        )
    )
    flow_ids = {row.id for row in flows}
    events = [
        row
        for row in session.scalars(select(AppliedStatementEvent).order_by(AppliedStatementEvent.id))
        if row.status == "active" and row.investment_cash_flow_id in flow_ids
    ]
    revisions = _latest_statement_revision(session, [row.id for row in events])
    accounts, instruments = _name_maps(
        session,
        {row.account_id for row in events},
        {row.instrument_id for row in events},
    )
    items: list[FreshnessItem] = []
    providers: set[str] = set()
    for event in events:
        revision = revisions.get(event.id)
        providers.add(event.provider)
        instrument_name = instruments.get(event.instrument_id, f"instrument-{event.instrument_id}")
        account_name = accounts.get(event.account_id, f"account-{event.account_id}")
        items.append(
            FreshnessItem(
                item_kind="statement_event",
                label=f"{instrument_name} · {event.event_kind}",
                freshness_status=FreshnessStatus.NOT_APPLICABLE,
                source_kind=event.provider,
                source_timestamp_kind=SourceTimestampKind.EVENT_DATE,
                source_date=revision.event_date if revision is not None else None,
                source_datetime=None,
                fetched_at=None,
                import_apply_time=_utc(
                    revision.applied_at if revision is not None else event.created_at
                ),
                local_edit_time=_utc(event.updated_at),
                reason_codes=(FreshnessReasonCode.STATEMENT_NOT_FRESHNESS_CLASSIFIED,),
                account_name=account_name,
                instrument_name=instrument_name,
            )
        )
    if events:
        reasons = (
            _reason(FreshnessReasonCode.STATEMENT_EVENT_PRESENT, FreshnessSeverity.INFO),
            _reason(FreshnessReasonCode.STATEMENT_NOT_FRESHNESS_CLASSIFIED, FreshnessSeverity.INFO),
        )
        status = FreshnessStatus.NOT_APPLICABLE
    else:
        reasons = (_reason(FreshnessReasonCode.STATEMENT_NONE_FOR_MONTH, FreshnessSeverity.INFO),)
        status = FreshnessStatus.MISSING
    return FreshnessFamily(
        family_id=FreshnessFamilyId.ALFA_STATEMENT_PAYOUTS,
        title="Выписка Alfa PDF",
        status=status,
        providers=_iso_providers(providers),
        coverage=FreshnessCoverage(row_count=len(events), provider_count=len(events)),
        reasons=reasons,
        items=tuple(items),
    )


def _count_month_rows(session: Session, model: type, month_id: int) -> int:
    return len(
        session.scalars(select(model).where(model.reporting_month_id == month_id)).all()  # type: ignore[attr-defined]
    )


def _build_manual_month_data(session: Session, *, month_id: int) -> FreshnessFamily:
    incomes = _count_month_rows(session, IncomeEntry, month_id)
    expenses = _count_month_rows(session, ExpenseEntry, month_id)
    savings = _count_month_rows(session, SavingAllocation, month_id)
    expected = _count_month_rows(session, ExpectedCashFlow, month_id)
    manual_positions = len(
        [
            row
            for row in session.scalars(
                select(PositionSnapshot).where(PositionSnapshot.reporting_month_id == month_id)
            )
            if row.price_source in MANUAL_PRICE_SOURCES
        ]
    )
    row_count = incomes + expenses + savings + expected + manual_positions
    groups = (
        ("Доходы", incomes),
        ("Расходы", expenses),
        ("Накопления", savings),
        ("Ожидаемые выплаты", expected),
        ("Позиции с ручной ценой", manual_positions),
    )
    items = tuple(
        FreshnessItem(
            item_kind="manual_group",
            label=f"{title}: {count}",
            freshness_status=FreshnessStatus.NOT_APPLICABLE,
            source_kind="manual",
            source_timestamp_kind=SourceTimestampKind.NOT_APPLICABLE,
            source_date=None,
            source_datetime=None,
            fetched_at=None,
            import_apply_time=None,
            local_edit_time=None,
            reason_codes=(FreshnessReasonCode.MANUAL_SOURCE_NO_PROVIDER_TIMESTAMP,),
        )
        for title, count in groups
        if count
    )
    if row_count:
        reasons = (
            _reason(FreshnessReasonCode.MANUAL_MONTH_DATA_PRESENT, FreshnessSeverity.INFO),
            _reason(
                FreshnessReasonCode.MANUAL_SOURCE_NO_PROVIDER_TIMESTAMP, FreshnessSeverity.INFO
            ),
        )
        status = FreshnessStatus.NOT_APPLICABLE
    else:
        reasons = (_reason(FreshnessReasonCode.MANUAL_MONTH_DATA_EMPTY, FreshnessSeverity.INFO),)
        status = FreshnessStatus.MISSING
        items = ()
    return FreshnessFamily(
        family_id=FreshnessFamilyId.MANUAL_MONTH_DATA,
        title="Ручные данные месяца",
        status=status,
        providers=(),
        coverage=FreshnessCoverage(row_count=row_count, manual_count=row_count),
        reasons=reasons,
        items=items,
    )


def _build_deposit_cash(session: Session, *, month_id: int) -> FreshnessFamily:
    deposits = list(
        session.scalars(
            select(DepositSnapshot)
            .where(DepositSnapshot.reporting_month_id == month_id)
            .order_by(DepositSnapshot.id)
        )
    )
    cash = list(
        session.scalars(
            select(CashBalance)
            .where(CashBalance.reporting_month_id == month_id)
            .order_by(CashBalance.id)
        )
    )
    accounts, _instruments = _name_maps(session, {row.account_id for row in deposits}, set())
    items: list[FreshnessItem] = []
    for deposit in deposits:
        items.append(
            FreshnessItem(
                item_kind="deposit",
                label=deposit.name,
                freshness_status=FreshnessStatus.NOT_APPLICABLE,
                source_kind="manual",
                source_timestamp_kind=SourceTimestampKind.NOT_APPLICABLE,
                source_date=None,
                source_datetime=None,
                fetched_at=None,
                import_apply_time=None,
                local_edit_time=_utc(deposit.updated_at),
                reason_codes=(
                    FreshnessReasonCode.DEPOSIT_CASH_LOCAL_EDIT_ONLY,
                    FreshnessReasonCode.MANUAL_SOURCE_NO_PROVIDER_TIMESTAMP,
                ),
                account_name=accounts.get(deposit.account_id),
            )
        )
    for balance in cash:
        items.append(
            FreshnessItem(
                item_kind="cash",
                label=balance.name,
                freshness_status=FreshnessStatus.NOT_APPLICABLE,
                source_kind="manual",
                source_timestamp_kind=SourceTimestampKind.UNAVAILABLE,
                source_date=None,
                source_datetime=None,
                fetched_at=None,
                import_apply_time=None,
                local_edit_time=None,
                reason_codes=(
                    FreshnessReasonCode.SOURCE_TIMESTAMP_UNAVAILABLE,
                    FreshnessReasonCode.MANUAL_SOURCE_NO_PROVIDER_TIMESTAMP,
                ),
            )
        )
    row_count = len(deposits) + len(cash)
    reasons: list[FreshnessReason] = []
    if row_count:
        reasons.append(_reason(FreshnessReasonCode.DEPOSIT_CASH_PRESENT, FreshnessSeverity.INFO))
        reasons.append(
            _reason(FreshnessReasonCode.MANUAL_SOURCE_NO_PROVIDER_TIMESTAMP, FreshnessSeverity.INFO)
        )
        if deposits:
            reasons.append(
                _reason(FreshnessReasonCode.DEPOSIT_CASH_LOCAL_EDIT_ONLY, FreshnessSeverity.INFO)
            )
        if cash:
            reasons.append(
                _reason(FreshnessReasonCode.SOURCE_TIMESTAMP_UNAVAILABLE, FreshnessSeverity.INFO)
            )
        status = FreshnessStatus.NOT_APPLICABLE
    else:
        reasons.append(_reason(FreshnessReasonCode.DEPOSIT_CASH_EMPTY, FreshnessSeverity.INFO))
        status = FreshnessStatus.MISSING
    return FreshnessFamily(
        family_id=FreshnessFamilyId.DEPOSIT_CASH_SNAPSHOTS,
        title="Депозиты и кэш",
        status=status,
        providers=(),
        coverage=FreshnessCoverage(row_count=row_count, manual_count=row_count),
        reasons=_dedupe_reasons(reasons),
        items=tuple(items),
    )


def build_freshness_provenance_summary(
    session: Session,
    month_id: int,
    *,
    today: date,
    generated_at: datetime | None = None,
) -> FreshnessProvenanceSummary:
    month = get_reporting_month(session, month_id)
    target_date = quote_refresh_target_date(month.snapshot_date, today=today)
    clock = generated_at or datetime.now(UTC)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=UTC)
    families = (
        _build_market_quotes(session, month_id=month.id, target_date=target_date),
        _build_t_invest_payouts(session, month_id=month.id),
        _build_alfa_pro_positions(session, month_id=month.id),
        _build_alfa_statements(session, month_id=month.id),
        _build_manual_month_data(session, month_id=month.id),
        _build_deposit_cash(session, month_id=month.id),
    )
    providers: set[str] = set()
    reasons: list[FreshnessReason] = []
    for family in families:
        providers.update(family.providers)
        reasons.extend(family.reasons)
    if len(providers) > 1:
        reasons.append(_reason(FreshnessReasonCode.MULTIPLE_PROVIDERS, FreshnessSeverity.INFO))
    return FreshnessProvenanceSummary(
        reporting_month=ReportingMonthContext(
            id=month.id,
            year=month.year,
            month=month.month,
            status=month.status,
            snapshot_date=month.snapshot_date,
            source=month.source,
        ),
        evaluated_on=today,
        quote_valuation_target_date=target_date,
        generated_at=clock,
        families=families,
        reasons=_dedupe_reasons(reasons),
        providers=_iso_providers(providers),
    )
