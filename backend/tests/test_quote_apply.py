"""R04-06 selective apply and immutable provenance."""

from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import AccountType, InstrumentType, PriceSource
from hermes_finance.market_data.dto import (
    T_INVEST_PROVIDER,
    MarketIdentity,
    QuoteFailure,
    QuoteKind,
    QuoteResult,
    QuoteStatus,
    QuoteSuccess,
    RawPriceBasis,
    market_identity_key,
)
from hermes_finance.market_data.moex_identity import market_identity_from_moex
from hermes_finance.persistence import (
    Base,
    InstrumentMarketMapping,
    PositionQuoteProvenance,
)
from hermes_finance.services.accounts import create_account
from hermes_finance.services.instrument_mappings import (
    get_instrument_mapping,
    set_accepted_mapping,
)
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.positions import create_position_snapshot
from hermes_finance.services.quote_apply import (
    PreviewChangedError,
    QuoteApplySelection,
    apply_market_quotes,
)
from hermes_finance.services.reporting_months import close_reporting_month, create_reporting_month

TODAY = date(2026, 8, 13)
SNAPSHOT_DATE = date(2026, 8, 31)
FETCHED_AT = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)
APPLIED_AT = datetime(2026, 8, 13, 12, 5, tzinfo=timezone.utc)
STOCK_UID = "11111111-1111-1111-1111-111111111111"
FUND_UID = "22222222-2222-2222-2222-222222222222"
STOCK_IDENTITY = MarketIdentity(
    provider=T_INVEST_PROVIDER,
    provider_instrument_id=STOCK_UID,
    provider_venue_id=None,
)
FUND_IDENTITY = MarketIdentity(
    provider=T_INVEST_PROVIDER,
    provider_instrument_id=FUND_UID,
    provider_venue_id=None,
)
MOEX_IDENTITY = market_identity_from_moex(
    engine="stock",
    market="shares",
    boardid="TQBR",
    secid="SBER",
)


class ScriptedProvider:
    def __init__(self, quotes: dict[tuple[str, str, str | None], QuoteResult]) -> None:
        self.quotes = quotes
        self.fetch_calls: list[tuple[MarketIdentity, date]] = []
        self.discover_calls = 0

    def discover_candidates(self, **kwargs: object) -> object:
        self.discover_calls += 1
        raise AssertionError("apply must not call discover_candidates")

    def fetch_quote(self, identity: MarketIdentity, target_date: date) -> QuoteResult:
        self.fetch_calls.append((identity, target_date))
        return self.quotes[market_identity_key(identity)]

    def fetch_quotes(self, items: list[tuple[MarketIdentity, date]]) -> list[QuoteResult]:
        return [self.fetch_quote(identity, target_date) for identity, target_date in items]


class CountingProvider(ScriptedProvider):
    def __init__(self, quotes: dict[tuple[str, str, str | None], QuoteResult]) -> None:
        super().__init__(quotes)
        self.started = 0

    def fetch_quotes(self, items: list[tuple[MarketIdentity, date]]) -> list[QuoteResult]:
        self.started += 1
        return super().fetch_quotes(items)


def session_for(tmp_path: Path) -> tuple[Session, object]:
    database = create_database(tmp_path / "quote-apply.db")
    Base.metadata.create_all(database.engine)
    return database.session_factory(), database


def _success(
    identity: MarketIdentity,
    *,
    kopecks: int,
    status: QuoteStatus = QuoteStatus.OK,
    price_date: date = TODAY,
    quote_kind: QuoteKind = QuoteKind.LAST,
) -> QuoteSuccess:
    return QuoteSuccess(
        identity=identity,
        instrument_kind=InstrumentType.STOCK,
        raw_price=f"{kopecks // 100}.{(kopecks % 100):02d}",
        raw_price_basis=RawPriceBasis.CASH_PER_UNIT,
        proposed_price_kopecks=kopecks,
        price_date=price_date,
        quote_kind=quote_kind,
        fetched_at_utc=FETCHED_AT,
        freshness_status=status,
    )


def _selection(
    snapshot_id: int,
    *,
    kopecks: int,
    identity: MarketIdentity = STOCK_IDENTITY,
    accept_stale: bool = False,
    price_date: date = TODAY,
    quote_kind: str = "last",
) -> QuoteApplySelection:
    return QuoteApplySelection(
        position_snapshot_id=snapshot_id,
        accept_stale=accept_stale,
        expected_market_price_kopecks=kopecks,
        expected_price_date=price_date,
        expected_identity=identity,
        expected_quote_kind=quote_kind,
    )


def _seed(session: Session) -> tuple[int, object, object, object]:
    month = create_reporting_month(session, year=2026, month=8, snapshot_date=SNAPSHOT_DATE)
    account = create_account(session, name="Broker", account_type=AccountType.BROKERAGE)
    stock = create_instrument(session, name="Synthetic Stock", instrument_type=InstrumentType.STOCK)
    fund = create_instrument(session, name="Synthetic Fund", instrument_type=InstrumentType.FUND)
    set_accepted_mapping(
        session,
        stock.id,
        provider=T_INVEST_PROVIDER,
        provider_instrument_id=STOCK_UID,
    )
    set_accepted_mapping(
        session,
        fund.id,
        provider=T_INVEST_PROVIDER,
        provider_instrument_id=FUND_UID,
    )
    return month.id, account, stock, fund


def test_one_ok_apply_persists_t_invest_source_and_provenance(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account, stock, _fund = _seed(session)
        snapshot = create_position_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=account.id,
            instrument_id=stock.id,
            quantity="10",
            average_cost_per_unit="200.00",
            market_price_per_unit="200.00",
            accrued_interest="15.00",
            price_date=date(2026, 8, 1),
            price_source=PriceSource.MANUAL,
        )
        nkd = snapshot.accrued_interest_kopecks
        provider = ScriptedProvider(
            {market_identity_key(STOCK_IDENTITY): _success(STOCK_IDENTITY, kopecks=21550)}
        )
        result = apply_market_quotes(
            session,
            month_id,
            [_selection(snapshot.id, kopecks=21550)],
            provider=provider,
            today=TODAY,
            clock=APPLIED_AT,
        )
        assert result.applied_count == 1
        session.refresh(snapshot)
        assert snapshot.price_source == PriceSource.T_INVEST.value
        assert snapshot.market_price_per_unit_kopecks == 21550
        assert snapshot.market_value_kopecks == 10 * 21550 + nkd
        assert snapshot.accrued_interest_kopecks == nkd
        provenance = session.scalar(
            select(PositionQuoteProvenance).where(
                PositionQuoteProvenance.position_snapshot_id == snapshot.id
            )
        )
        assert provenance is not None
        assert provenance.provider == T_INVEST_PROVIDER
        assert provenance.provider_instrument_id == STOCK_UID
        assert provenance.normalized_price_kopecks == 21550
        assert provenance.price_date == TODAY
        assert provenance.freshness == "ok"
        assert provenance.reporting_month_id == month_id
        assert provider.discover_calls == 0
    finally:
        session.close()
        database.engine.dispose()


def test_multi_row_apply_is_one_transaction(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account, stock, fund = _seed(session)
        first = create_position_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=account.id,
            instrument_id=stock.id,
            quantity="2",
            average_cost_per_unit="100.00",
            market_price_per_unit="100.00",
            price_date=date(2026, 8, 1),
        )
        second = create_position_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=account.id,
            instrument_id=fund.id,
            quantity="3",
            average_cost_per_unit="50.00",
            market_price_per_unit="50.00",
            price_date=date(2026, 8, 1),
        )
        provider = ScriptedProvider(
            {
                market_identity_key(STOCK_IDENTITY): _success(STOCK_IDENTITY, kopecks=12000),
                market_identity_key(FUND_IDENTITY): _success(FUND_IDENTITY, kopecks=7000),
            }
        )
        result = apply_market_quotes(
            session,
            month_id,
            [
                _selection(first.id, kopecks=12000),
                _selection(second.id, kopecks=7000, identity=FUND_IDENTITY),
            ],
            provider=provider,
            today=TODAY,
        )
        assert result.applied_count == 2
        session.refresh(first)
        session.refresh(second)
        assert first.market_price_per_unit_kopecks == 12000
        assert second.market_price_per_unit_kopecks == 7000
        assert session.scalars(select(PositionQuoteProvenance)).all().__len__() == 2
    finally:
        session.close()
        database.engine.dispose()


def test_one_failing_row_writes_nothing(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account, stock, fund = _seed(session)
        first = create_position_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=account.id,
            instrument_id=stock.id,
            quantity="2",
            average_cost_per_unit="100.00",
            market_price_per_unit="100.00",
            price_date=date(2026, 8, 1),
        )
        second = create_position_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=account.id,
            instrument_id=fund.id,
            quantity="3",
            average_cost_per_unit="50.00",
            market_price_per_unit="50.00",
            price_date=date(2026, 8, 1),
        )
        before_first = first.market_price_per_unit_kopecks
        before_second = second.market_price_per_unit_kopecks
        provider = ScriptedProvider(
            {
                market_identity_key(STOCK_IDENTITY): _success(STOCK_IDENTITY, kopecks=12000),
                market_identity_key(FUND_IDENTITY): QuoteFailure(
                    status=QuoteStatus.UNAVAILABLE,
                    message="missing",
                    identity=FUND_IDENTITY,
                ),
            }
        )
        with pytest.raises(ValueError, match="cannot be applied"):
            apply_market_quotes(
                session,
                month_id,
                [
                    _selection(first.id, kopecks=12000),
                    _selection(second.id, kopecks=7000, identity=FUND_IDENTITY),
                ],
                provider=provider,
                today=TODAY,
            )
        session.refresh(first)
        session.refresh(second)
        assert first.market_price_per_unit_kopecks == before_first
        assert second.market_price_per_unit_kopecks == before_second
        assert session.scalars(select(PositionQuoteProvenance)).first() is None
    finally:
        session.close()
        database.engine.dispose()


def test_closed_month_rejected(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account, stock, _fund = _seed(session)
        snapshot = create_position_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=account.id,
            instrument_id=stock.id,
            quantity="1",
            average_cost_per_unit="100.00",
            market_price_per_unit="100.00",
            price_date=date(2026, 8, 1),
        )
        close_reporting_month(session, month_id)
        provider = ScriptedProvider(
            {market_identity_key(STOCK_IDENTITY): _success(STOCK_IDENTITY, kopecks=12000)}
        )
        from hermes_finance.services.reporting_months import ClosedReportingMonthError

        with pytest.raises(ClosedReportingMonthError):
            apply_market_quotes(
                session,
                month_id,
                [_selection(snapshot.id, kopecks=12000)],
                provider=provider,
                today=TODAY,
            )
        session.refresh(snapshot)
        assert snapshot.price_source == PriceSource.MANUAL.value
    finally:
        session.close()
        database.engine.dispose()


def test_stale_requires_explicit_selection(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account, stock, _fund = _seed(session)
        snapshot = create_position_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=account.id,
            instrument_id=stock.id,
            quantity="1",
            average_cost_per_unit="100.00",
            market_price_per_unit="100.00",
            price_date=date(2026, 8, 1),
        )
        stale = _success(
            STOCK_IDENTITY, kopecks=9000, status=QuoteStatus.STALE, price_date=date(2026, 8, 1)
        )
        provider = ScriptedProvider({market_identity_key(STOCK_IDENTITY): stale})
        with pytest.raises(ValueError, match="stale quote was not explicitly selected"):
            apply_market_quotes(
                session,
                month_id,
                [_selection(snapshot.id, kopecks=9000, price_date=date(2026, 8, 1))],
                provider=provider,
                today=TODAY,
            )
        apply_market_quotes(
            session,
            month_id,
            [
                _selection(
                    snapshot.id,
                    kopecks=9000,
                    price_date=date(2026, 8, 1),
                    accept_stale=True,
                )
            ],
            provider=provider,
            today=TODAY,
        )
        session.refresh(snapshot)
        assert snapshot.market_price_per_unit_kopecks == 9000
        provenance = session.scalar(select(PositionQuoteProvenance))
        assert provenance is not None
        assert provenance.freshness == "stale"
    finally:
        session.close()
        database.engine.dispose()


def test_preview_changed_writes_nothing(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account, stock, _fund = _seed(session)
        snapshot = create_position_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=account.id,
            instrument_id=stock.id,
            quantity="1",
            average_cost_per_unit="100.00",
            market_price_per_unit="100.00",
            price_date=date(2026, 8, 1),
        )
        provider = ScriptedProvider(
            {market_identity_key(STOCK_IDENTITY): _success(STOCK_IDENTITY, kopecks=21550)}
        )
        with pytest.raises(PreviewChangedError):
            apply_market_quotes(
                session,
                month_id,
                [_selection(snapshot.id, kopecks=20000)],
                provider=provider,
                today=TODAY,
            )
        session.refresh(snapshot)
        assert snapshot.market_price_per_unit_kopecks == 10000
        assert session.scalars(select(PositionQuoteProvenance)).first() is None
    finally:
        session.close()
        database.engine.dispose()


def test_moex_mapping_cannot_apply(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month = create_reporting_month(session, year=2026, month=8, snapshot_date=SNAPSHOT_DATE)
        account = create_account(session, name="Broker", account_type=AccountType.BROKERAGE)
        stock = create_instrument(session, name="MOEX Stock", instrument_type=InstrumentType.STOCK)
        set_accepted_mapping(
            session,
            stock.id,
            provider=MOEX_IDENTITY.provider,
            provider_instrument_id=MOEX_IDENTITY.provider_instrument_id,
            provider_venue_id=MOEX_IDENTITY.provider_venue_id,
        )
        snapshot = create_position_snapshot(
            session,
            reporting_month_id=month.id,
            account_id=account.id,
            instrument_id=stock.id,
            quantity="1",
            average_cost_per_unit="100.00",
            market_price_per_unit="100.00",
            price_date=date(2026, 8, 1),
        )
        provider = ScriptedProvider(
            {market_identity_key(MOEX_IDENTITY): _success(MOEX_IDENTITY, kopecks=12000)}
        )
        with pytest.raises(ValueError, match="T-Invest only"):
            apply_market_quotes(
                session,
                month.id,
                [_selection(snapshot.id, kopecks=12000, identity=MOEX_IDENTITY)],
                provider=provider,
                today=TODAY,
            )
        session.refresh(snapshot)
        assert snapshot.price_source == PriceSource.MANUAL.value
    finally:
        session.close()
        database.engine.dispose()


def test_provenance_survives_mapping_edit(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account, stock, _fund = _seed(session)
        snapshot = create_position_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=account.id,
            instrument_id=stock.id,
            quantity="1",
            average_cost_per_unit="100.00",
            market_price_per_unit="100.00",
            price_date=date(2026, 8, 1),
        )
        provider = ScriptedProvider(
            {market_identity_key(STOCK_IDENTITY): _success(STOCK_IDENTITY, kopecks=21550)}
        )
        apply_market_quotes(
            session,
            month_id,
            [_selection(snapshot.id, kopecks=21550)],
            provider=provider,
            today=TODAY,
        )
        new_uid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        set_accepted_mapping(
            session,
            stock.id,
            provider=T_INVEST_PROVIDER,
            provider_instrument_id=new_uid,
        )
        session.refresh(snapshot)
        provenance = session.scalar(
            select(PositionQuoteProvenance).where(
                PositionQuoteProvenance.position_snapshot_id == snapshot.id
            )
        )
        mapping = get_instrument_mapping(session, stock.id)
        assert mapping.identity is not None
        assert mapping.identity.provider_instrument_id == new_uid
        assert provenance is not None
        assert provenance.provider_instrument_id == STOCK_UID
        assert snapshot.market_price_per_unit_kopecks == 21550
        assert snapshot.price_source == PriceSource.T_INVEST.value
        assert session.get(InstrumentMarketMapping, stock.id) is not None
    finally:
        session.close()
        database.engine.dispose()


def _provenance_fields(row: PositionQuoteProvenance) -> tuple[object, ...]:
    return (
        row.id,
        row.position_snapshot_id,
        row.reporting_month_id,
        row.provider,
        row.provider_instrument_id,
        row.provider_venue_id,
        row.quote_kind,
        row.raw_price,
        row.raw_price_basis,
        row.normalized_price_kopecks,
        row.price_date,
        row.fetched_at_utc,
        row.target_date,
        row.freshness,
        row.applied_at_utc,
    )


def test_repeat_apply_appends_provenance_and_preserves_first_row(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account, stock, _fund = _seed(session)
        snapshot = create_position_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=account.id,
            instrument_id=stock.id,
            quantity="1",
            average_cost_per_unit="100.00",
            market_price_per_unit="100.00",
            price_date=date(2026, 8, 1),
        )
        first_at = datetime(2026, 8, 13, 12, 5, tzinfo=timezone.utc)
        second_at = datetime(2026, 8, 14, 9, 0, tzinfo=timezone.utc)
        first_quote = _success(STOCK_IDENTITY, kopecks=21550)
        second_quote = _success(STOCK_IDENTITY, kopecks=22000)
        apply_market_quotes(
            session,
            month_id,
            [_selection(snapshot.id, kopecks=21550)],
            provider=ScriptedProvider({market_identity_key(STOCK_IDENTITY): first_quote}),
            today=TODAY,
            clock=first_at,
        )
        first_row = session.scalar(
            select(PositionQuoteProvenance).order_by(PositionQuoteProvenance.id)
        )
        assert first_row is not None
        first_fields = _provenance_fields(first_row)

        apply_market_quotes(
            session,
            month_id,
            [_selection(snapshot.id, kopecks=22000)],
            provider=ScriptedProvider({market_identity_key(STOCK_IDENTITY): second_quote}),
            today=TODAY,
            clock=second_at,
        )
        session.refresh(snapshot)
        rows = list(
            session.scalars(select(PositionQuoteProvenance).order_by(PositionQuoteProvenance.id))
        )
        assert snapshot.market_price_per_unit_kopecks == 22000
        assert len(rows) == 2
        assert _provenance_fields(rows[0]) == first_fields
        assert rows[1].normalized_price_kopecks == 22000
        assert rows[1].applied_at_utc.replace(tzinfo=timezone.utc) == second_at
        assert rows[1].id != rows[0].id
    finally:
        session.close()
        database.engine.dispose()


def test_failed_second_apply_does_not_touch_provenance(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account, stock, _fund = _seed(session)
        snapshot = create_position_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=account.id,
            instrument_id=stock.id,
            quantity="1",
            average_cost_per_unit="100.00",
            market_price_per_unit="100.00",
            price_date=date(2026, 8, 1),
        )
        apply_market_quotes(
            session,
            month_id,
            [_selection(snapshot.id, kopecks=21550)],
            provider=ScriptedProvider(
                {market_identity_key(STOCK_IDENTITY): _success(STOCK_IDENTITY, kopecks=21550)}
            ),
            today=TODAY,
            clock=APPLIED_AT,
        )
        first_row = session.scalar(select(PositionQuoteProvenance))
        assert first_row is not None
        first_fields = _provenance_fields(first_row)
        with pytest.raises(PreviewChangedError):
            apply_market_quotes(
                session,
                month_id,
                [_selection(snapshot.id, kopecks=20000)],
                provider=ScriptedProvider(
                    {market_identity_key(STOCK_IDENTITY): _success(STOCK_IDENTITY, kopecks=22000)}
                ),
                today=TODAY,
            )
        rows = list(session.scalars(select(PositionQuoteProvenance)))
        assert len(rows) == 1
        assert _provenance_fields(rows[0]) == first_fields
        session.refresh(snapshot)
        assert snapshot.market_price_per_unit_kopecks == 21550
    finally:
        session.close()
        database.engine.dispose()


def test_apply_does_not_run_on_import(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account, stock, _fund = _seed(session)
        create_position_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=account.id,
            instrument_id=stock.id,
            quantity="1",
            average_cost_per_unit="100.00",
            market_price_per_unit="100.00",
            price_date=date(2026, 8, 1),
        )
        provider = CountingProvider(
            {market_identity_key(STOCK_IDENTITY): _success(STOCK_IDENTITY, kopecks=12000)}
        )
        assert provider.started == 0
        assert provider.fetch_calls == []
    finally:
        session.close()
        database.engine.dispose()
