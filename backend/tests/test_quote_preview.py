"""Service tests for read-only quote refresh preview (R04-04)."""

from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import AccountType, InstrumentType, MarketMappingState, PriceSource
from hermes_finance.market_data.dto import (
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
from hermes_finance.market_data.normalize import quote_refresh_target_date
from hermes_finance.persistence import Base, InstrumentMarketMapping, PositionSnapshot
from hermes_finance.services.accounts import create_account
from hermes_finance.services.instrument_mappings import (
    exclude_instrument_mapping,
    get_instrument_mapping,
    set_accepted_mapping,
)
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.positions import create_position_snapshot
from hermes_finance.services.quote_preview import preview_market_quotes
from hermes_finance.services.reporting_months import close_reporting_month, create_reporting_month

TODAY = date(2026, 8, 13)
SNAPSHOT_DATE = date(2026, 8, 31)
FETCHED_AT = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)

STOCK_IDENTITY = market_identity_from_moex(
    engine="stock",
    market="shares",
    boardid="TQBR",
    secid="SBER",
)
FUND_IDENTITY = market_identity_from_moex(
    engine="stock",
    market="shares",
    boardid="TQTF",
    secid="FXGD",
)
BOND_IDENTITY = market_identity_from_moex(
    engine="stock",
    market="bonds",
    boardid="TQCB",
    secid="SU26238RMFS4",
)


class ScriptedProvider:
    def __init__(self, quotes: dict[tuple[str, str, str | None], QuoteResult]) -> None:
        self.quotes = quotes
        self.fetch_calls: list[tuple[MarketIdentity, date]] = []
        self.discover_calls = 0

    def discover_candidates(self, **kwargs: object) -> object:
        self.discover_calls += 1
        raise AssertionError("preview must not call discover_candidates")

    def fetch_quote(self, identity: MarketIdentity, target_date: date) -> QuoteResult:
        self.fetch_calls.append((identity, target_date))
        key = market_identity_key(identity)
        if key not in self.quotes:
            raise AssertionError(f"unexpected fetch {key}")
        return self.quotes[key]

    def fetch_quotes(self, items: list[tuple[MarketIdentity, date]]) -> list[QuoteResult]:
        return [self.fetch_quote(identity, target_date) for identity, target_date in items]


class ForbiddenProvider:
    def discover_candidates(self, **kwargs: object) -> object:
        raise AssertionError("provider must not be called")

    def fetch_quote(self, identity: MarketIdentity, target_date: date) -> QuoteResult:
        raise AssertionError("provider must not be called")

    def fetch_quotes(self, items: object) -> list[QuoteResult]:
        raise AssertionError("provider must not be called")


def session_for(tmp_path: Path) -> tuple[Session, object]:
    database = create_database(tmp_path / "quote_preview.db")
    Base.metadata.create_all(database.engine)
    return database.session_factory(), database


def _success(
    identity: MarketIdentity,
    *,
    kind: InstrumentType,
    raw_price: str,
    basis: RawPriceBasis,
    kopecks: int,
    price_date: date,
    status: QuoteStatus = QuoteStatus.OK,
    quote_kind: QuoteKind = QuoteKind.LAST,
) -> QuoteSuccess:
    return QuoteSuccess(
        identity=identity,
        instrument_kind=kind,
        raw_price=raw_price,
        raw_price_basis=basis,
        proposed_price_kopecks=kopecks,
        price_date=price_date,
        quote_kind=quote_kind,
        fetched_at_utc=FETCHED_AT,
        freshness_status=status,
    )


def _identity_kwargs(identity: MarketIdentity) -> dict[str, str | None]:
    return {
        "provider": identity.provider,
        "provider_instrument_id": identity.provider_instrument_id,
        "provider_venue_id": identity.provider_venue_id,
    }


def _fingerprint_snapshot(session: Session, snapshot_id: int) -> tuple[object, ...]:
    row = session.get(PositionSnapshot, snapshot_id)
    assert row is not None
    return (
        row.market_price_per_unit_kopecks,
        row.market_value_kopecks,
        row.unrealized_result_kopecks,
        row.price_date,
        row.price_source,
        row.accrued_interest_kopecks,
        row.updated_at,
        row.quantity,
        row.notes,
    )


def _fingerprint_mapping(session: Session, instrument_id: int) -> tuple[object, ...] | None:
    row = session.get(InstrumentMarketMapping, instrument_id)
    if row is None:
        return None
    return (
        row.provider,
        row.provider_instrument_id,
        row.provider_venue_id,
        row.excluded,
        row.updated_at,
    )


def test_quote_refresh_target_date_uses_earlier_of_snapshot_and_today() -> None:
    assert quote_refresh_target_date(date(2026, 8, 31), today=date(2026, 8, 13)) == date(
        2026, 8, 13
    )
    assert quote_refresh_target_date(date(2026, 7, 31), today=date(2026, 8, 13)) == date(
        2026, 7, 31
    )


def test_mapped_stock_fund_and_bond_quotes(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month = create_reporting_month(session, year=2026, month=8, snapshot_date=SNAPSHOT_DATE)
        account = create_account(
            session, name="Synthetic Broker", account_type=AccountType.BROKERAGE
        )
        stock = create_instrument(
            session,
            name="Synthetic Stock",
            instrument_type=InstrumentType.STOCK,
            moex_secid="WRONG",
        )
        fund = create_instrument(
            session, name="Synthetic Fund", instrument_type=InstrumentType.FUND
        )
        bond_f = create_instrument(
            session, name="Synthetic Bond F", instrument_type=InstrumentType.BOND
        )
        bond_r = create_instrument(
            session, name="Synthetic Bond R", instrument_type=InstrumentType.BOND
        )
        set_accepted_mapping(session, stock.id, **_identity_kwargs(STOCK_IDENTITY))
        set_accepted_mapping(session, fund.id, **_identity_kwargs(FUND_IDENTITY))
        set_accepted_mapping(session, bond_f.id, **_identity_kwargs(BOND_IDENTITY))
        bond_r_identity = market_identity_from_moex(
            engine="stock",
            market="bonds",
            boardid="TQCB",
            secid="RU000A0JX0J2",
        )
        set_accepted_mapping(session, bond_r.id, **_identity_kwargs(bond_r_identity))
        stock_snap = create_position_snapshot(
            session,
            reporting_month_id=month.id,
            account_id=account.id,
            instrument_id=stock.id,
            quantity=1,
            average_cost_per_unit="100.00",
            market_price_per_unit="200.00",
            price_date=date(2026, 8, 1),
            price_source=PriceSource.MANUAL,
        )
        fund_snap = create_position_snapshot(
            session,
            reporting_month_id=month.id,
            account_id=account.id,
            instrument_id=fund.id,
            quantity=2,
            average_cost_per_unit="10.00",
            market_price_per_unit="11.00",
            price_date=date(2026, 8, 1),
        )
        bond_f_snap = create_position_snapshot(
            session,
            reporting_month_id=month.id,
            account_id=account.id,
            instrument_id=bond_f.id,
            quantity=1,
            average_cost_per_unit="900.00",
            market_price_per_unit="950.00",
            price_date=date(2026, 8, 1),
        )
        bond_r_snap = create_position_snapshot(
            session,
            reporting_month_id=month.id,
            account_id=account.id,
            instrument_id=bond_r.id,
            quantity=1,
            average_cost_per_unit="1000.00",
            market_price_per_unit="1010.00",
            price_date=date(2026, 8, 1),
        )
        provider = ScriptedProvider(
            {
                _identity_key(STOCK_IDENTITY): _success(
                    STOCK_IDENTITY,
                    kind=InstrumentType.STOCK,
                    raw_price="312.45",
                    basis=RawPriceBasis.CASH_PER_UNIT,
                    kopecks=31245,
                    price_date=TODAY,
                ),
                _identity_key(FUND_IDENTITY): _success(
                    FUND_IDENTITY,
                    kind=InstrumentType.FUND,
                    raw_price="14.20",
                    basis=RawPriceBasis.CASH_PER_UNIT,
                    kopecks=1420,
                    price_date=TODAY,
                ),
                _identity_key(BOND_IDENTITY): _success(
                    BOND_IDENTITY,
                    kind=InstrumentType.BOND,
                    raw_price="97.25",
                    basis=RawPriceBasis.PERCENT_OF_FACE,
                    kopecks=97250,
                    price_date=TODAY,
                ),
                _identity_key(bond_r_identity): _success(
                    bond_r_identity,
                    kind=InstrumentType.BOND,
                    raw_price="1015.50",
                    basis=RawPriceBasis.CASH_PER_UNIT,
                    kopecks=101550,
                    price_date=TODAY,
                ),
            }
        )
        result = preview_market_quotes(session, month.id, provider=provider, today=TODAY)
        assert result.target_date == TODAY
        assert result.month_editable is True
        assert result.batch_error is None
        by_id = {row.instrument_id: row for row in result.rows}
        assert by_id[stock.id].status is QuoteStatus.OK
        assert by_id[stock.id].current_market_price_kopecks == 20000
        assert by_id[stock.id].proposed_market_price_kopecks == 31245
        assert by_id[stock.id].apply_allowed is False
        assert by_id[stock.id].identity is not None
        assert by_id[stock.id].identity.provider_instrument_id == "SBER"
        assert by_id[fund.id].proposed_market_price_kopecks == 1420
        assert by_id[bond_f.id].proposed_raw_price == "97.25"
        assert by_id[bond_f.id].proposed_raw_price_basis is RawPriceBasis.PERCENT_OF_FACE
        assert by_id[bond_f.id].proposed_market_price_kopecks == 97250
        assert by_id[bond_r.id].proposed_raw_price_basis is RawPriceBasis.CASH_PER_UNIT
        assert by_id[bond_r.id].proposed_market_price_kopecks == 101550
        fetched_ids = {
            identity.provider_instrument_id for identity, _target in provider.fetch_calls
        }
        assert fetched_ids == {"SBER", "FXGD", "SU26238RMFS4", "RU000A0JX0J2"}
        assert "WRONG" not in fetched_ids
        assert all(target == TODAY for _identity, target in provider.fetch_calls)
        assert stock_snap.id and fund_snap.id and bond_f_snap.id and bond_r_snap.id
    finally:
        session.close()
        database.engine.dispose()


def _identity_key(identity: MarketIdentity) -> tuple[str, str, str | None]:
    return market_identity_key(identity)


def test_unmapped_excluded_and_unsupported_skip_provider(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month = create_reporting_month(session, year=2026, month=8, snapshot_date=SNAPSHOT_DATE)
        account = create_account(
            session, name="Synthetic Broker", account_type=AccountType.BROKERAGE
        )
        unmapped = create_instrument(
            session, name="Unmapped Stock", instrument_type=InstrumentType.STOCK, moex_secid="SBER"
        )
        excluded = create_instrument(
            session, name="Excluded Stock", instrument_type=InstrumentType.STOCK
        )
        gold = create_instrument(
            session, name="Synthetic Gold", instrument_type=InstrumentType.GOLD
        )
        set_accepted_mapping(session, excluded.id, **_identity_kwargs(STOCK_IDENTITY))
        exclude_instrument_mapping(session, excluded.id)
        for instrument in (unmapped, excluded, gold):
            create_position_snapshot(
                session,
                reporting_month_id=month.id,
                account_id=account.id,
                instrument_id=instrument.id,
                quantity=1,
                average_cost_per_unit="10.00",
                market_price_per_unit="10.00",
                price_date=date(2026, 8, 1),
            )
        result = preview_market_quotes(session, month.id, provider=ForbiddenProvider(), today=TODAY)
        statuses = {row.instrument_id: row.status for row in result.rows}
        assert statuses[unmapped.id] is QuoteStatus.UNMAPPED
        assert statuses[excluded.id] is QuoteStatus.EXCLUDED
        assert statuses[gold.id] is QuoteStatus.UNSUPPORTED
        assert all(row.apply_allowed is False for row in result.rows)
        assert all(row.proposed_market_price_kopecks is None for row in result.rows)
        assert get_instrument_mapping(session, excluded.id).state is MarketMappingState.EXCLUDED
    finally:
        session.close()
        database.engine.dispose()


def test_stale_unavailable_network_malformed_and_ambiguous(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month = create_reporting_month(session, year=2026, month=8, snapshot_date=SNAPSHOT_DATE)
        account = create_account(
            session, name="Synthetic Broker", account_type=AccountType.BROKERAGE
        )
        names = {
            "stale": STOCK_IDENTITY,
            "unavail": FUND_IDENTITY,
            "net": BOND_IDENTITY,
            "malformed": market_identity_from_moex(
                engine="stock",
                market="shares",
                boardid="TQBR",
                secid="GAZP",
            ),
            "ambiguous": market_identity_from_moex(
                engine="stock",
                market="shares",
                boardid="TQBR",
                secid="LKOH",
            ),
        }
        snaps = {}
        quotes: dict[tuple[str, str, str | None], QuoteResult] = {}
        for name, identity in names.items():
            kind = InstrumentType.BOND if name == "net" else InstrumentType.STOCK
            instrument = create_instrument(session, name=f"Synthetic {name}", instrument_type=kind)
            set_accepted_mapping(session, instrument.id, **_identity_kwargs(identity))
            snaps[name] = create_position_snapshot(
                session,
                reporting_month_id=month.id,
                account_id=account.id,
                instrument_id=instrument.id,
                quantity=1,
                average_cost_per_unit="10.00",
                market_price_per_unit="12.00",
                price_date=date(2026, 8, 1),
            )
        quotes[_identity_key(names["stale"])] = _success(
            names["stale"],
            kind=InstrumentType.STOCK,
            raw_price="20.00",
            basis=RawPriceBasis.CASH_PER_UNIT,
            kopecks=2000,
            price_date=date(2026, 8, 3),
            status=QuoteStatus.STALE,
            quote_kind=QuoteKind.HISTORY,
        )
        quotes[_identity_key(names["unavail"])] = QuoteFailure(
            status=QuoteStatus.UNAVAILABLE,
            message="no valid quote in lookback window",
            identity=names["unavail"],
        )
        quotes[_identity_key(names["net"])] = QuoteFailure(
            status=QuoteStatus.NETWORK_ERROR,
            message="timeout",
            identity=names["net"],
        )
        quotes[_identity_key(names["malformed"])] = QuoteFailure(
            status=QuoteStatus.MALFORMED_RESPONSE,
            message="quote is not a positive amount",
            identity=names["malformed"],
        )
        quotes[_identity_key(names["ambiguous"])] = QuoteFailure(
            status=QuoteStatus.AMBIGUOUS,
            message="multiple boards",
            identity=names["ambiguous"],
        )
        result = preview_market_quotes(
            session, month.id, provider=ScriptedProvider(quotes), today=TODAY
        )
        by_name = {}
        for name, snap in snaps.items():
            row = next(item for item in result.rows if item.position_snapshot_id == snap.id)
            by_name[name] = row
        assert by_name["stale"].status is QuoteStatus.STALE
        assert by_name["stale"].proposed_market_price_kopecks == 2000
        assert by_name["stale"].apply_allowed is False
        assert by_name["stale"].proposed_price_date == date(2026, 8, 3)
        assert by_name["stale"].proposed_price_date <= result.target_date
        assert by_name["unavail"].status is QuoteStatus.UNAVAILABLE
        assert by_name["unavail"].proposed_market_price_kopecks is None
        assert by_name["unavail"].current_market_price_kopecks == 1200
        assert by_name["net"].status is QuoteStatus.NETWORK_ERROR
        assert by_name["malformed"].status is QuoteStatus.MALFORMED_RESPONSE
        assert by_name["ambiguous"].status is QuoteStatus.AMBIGUOUS
        assert all(row.apply_allowed is False for row in by_name.values())
    finally:
        session.close()
        database.engine.dispose()


def test_mixed_batch_and_provider_exceptions_are_per_row(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month = create_reporting_month(session, year=2026, month=8, snapshot_date=SNAPSHOT_DATE)
        account = create_account(
            session, name="Synthetic Broker", account_type=AccountType.BROKERAGE
        )
        ok_instrument = create_instrument(
            session, name="OK Stock", instrument_type=InstrumentType.STOCK
        )
        bad_instrument = create_instrument(
            session, name="Bad Stock", instrument_type=InstrumentType.STOCK
        )
        set_accepted_mapping(session, ok_instrument.id, **_identity_kwargs(STOCK_IDENTITY))
        set_accepted_mapping(session, bad_instrument.id, **_identity_kwargs(FUND_IDENTITY))
        create_position_snapshot(
            session,
            reporting_month_id=month.id,
            account_id=account.id,
            instrument_id=ok_instrument.id,
            quantity=1,
            average_cost_per_unit="10.00",
            market_price_per_unit="10.00",
            price_date=date(2026, 8, 1),
        )
        create_position_snapshot(
            session,
            reporting_month_id=month.id,
            account_id=account.id,
            instrument_id=bad_instrument.id,
            quantity=1,
            average_cost_per_unit="10.00",
            market_price_per_unit="10.00",
            price_date=date(2026, 8, 1),
        )
        mixed = ScriptedProvider(
            {
                _identity_key(STOCK_IDENTITY): _success(
                    STOCK_IDENTITY,
                    kind=InstrumentType.STOCK,
                    raw_price="15.00",
                    basis=RawPriceBasis.CASH_PER_UNIT,
                    kopecks=1500,
                    price_date=TODAY,
                ),
                _identity_key(FUND_IDENTITY): QuoteFailure(
                    status=QuoteStatus.NETWORK_ERROR,
                    message="timeout",
                    identity=FUND_IDENTITY,
                ),
            }
        )
        result = preview_market_quotes(session, month.id, provider=mixed, today=TODAY)
        assert {row.status for row in result.rows} == {QuoteStatus.OK, QuoteStatus.NETWORK_ERROR}
        assert result.batch_error is None
        ok_row = next(row for row in result.rows if row.status is QuoteStatus.OK)
        failed_row = next(row for row in result.rows if row.status is QuoteStatus.NETWORK_ERROR)
        assert ok_row.proposed_market_price_kopecks == 1500
        assert failed_row.proposed_market_price_kopecks is None
        assert failed_row.message == "timeout"
    finally:
        session.close()
        database.engine.dispose()


@pytest.mark.parametrize(
    "error", [RuntimeError("socket exploded"), AssertionError("contract broke")]
)
def test_unexpected_provider_raise_is_not_network_error(error: Exception, tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month = create_reporting_month(session, year=2026, month=8, snapshot_date=SNAPSHOT_DATE)
        account = create_account(
            session, name="Synthetic Broker", account_type=AccountType.BROKERAGE
        )
        stock = create_instrument(session, name="Stock", instrument_type=InstrumentType.STOCK)
        set_accepted_mapping(session, stock.id, **_identity_kwargs(STOCK_IDENTITY))
        create_position_snapshot(
            session,
            reporting_month_id=month.id,
            account_id=account.id,
            instrument_id=stock.id,
            quantity=1,
            average_cost_per_unit="10.00",
            market_price_per_unit="10.00",
            price_date=date(2026, 8, 1),
        )

        class ExplodingProvider:
            def discover_candidates(self, **kwargs: object) -> object:
                raise AssertionError("preview must not call discover_candidates")

            def fetch_quote(self, identity: MarketIdentity, target_date: date) -> QuoteResult:
                raise AssertionError("preview must use fetch_quotes")

            def fetch_quotes(self, items: object) -> list[QuoteResult]:
                raise error

        with pytest.raises(type(error), match=str(error)):
            preview_market_quotes(session, month.id, provider=ExplodingProvider(), today=TODAY)
    finally:
        session.close()
        database.engine.dispose()


def test_wrong_fetch_quotes_count_is_provider_contract_error(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month = create_reporting_month(session, year=2026, month=8, snapshot_date=SNAPSHOT_DATE)
        account = create_account(
            session, name="Synthetic Broker", account_type=AccountType.BROKERAGE
        )
        stock = create_instrument(session, name="Stock", instrument_type=InstrumentType.STOCK)
        set_accepted_mapping(session, stock.id, **_identity_kwargs(STOCK_IDENTITY))
        create_position_snapshot(
            session,
            reporting_month_id=month.id,
            account_id=account.id,
            instrument_id=stock.id,
            quantity=1,
            average_cost_per_unit="10.00",
            market_price_per_unit="10.00",
            price_date=date(2026, 8, 1),
        )

        class ShortProvider:
            def discover_candidates(self, **kwargs: object) -> object:
                raise AssertionError("preview must not call discover_candidates")

            def fetch_quote(self, identity: MarketIdentity, target_date: date) -> QuoteResult:
                raise AssertionError("preview must use fetch_quotes")

            def fetch_quotes(self, items: object) -> list[QuoteResult]:
                return []

        with pytest.raises(RuntimeError, match="result count"):
            preview_market_quotes(session, month.id, provider=ShortProvider(), today=TODAY)
    finally:
        session.close()
        database.engine.dispose()


def test_empty_month_and_closed_month_semantics(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        empty = create_reporting_month(session, year=2026, month=6, snapshot_date=date(2026, 6, 30))
        empty_result = preview_market_quotes(
            session, empty.id, provider=ForbiddenProvider(), today=TODAY
        )
        assert empty_result.rows == ()
        assert empty_result.batch_error is None

        month = create_reporting_month(session, year=2026, month=8, snapshot_date=SNAPSHOT_DATE)
        account = create_account(
            session, name="Synthetic Broker", account_type=AccountType.BROKERAGE
        )
        stock = create_instrument(session, name="Stock", instrument_type=InstrumentType.STOCK)
        set_accepted_mapping(session, stock.id, **_identity_kwargs(STOCK_IDENTITY))
        create_position_snapshot(
            session,
            reporting_month_id=month.id,
            account_id=account.id,
            instrument_id=stock.id,
            quantity=1,
            average_cost_per_unit="10.00",
            market_price_per_unit="10.00",
            price_date=date(2026, 8, 1),
        )
        close_reporting_month(session, month.id)
        provider = ScriptedProvider(
            {
                _identity_key(STOCK_IDENTITY): _success(
                    STOCK_IDENTITY,
                    kind=InstrumentType.STOCK,
                    raw_price="15.00",
                    basis=RawPriceBasis.CASH_PER_UNIT,
                    kopecks=1500,
                    price_date=TODAY,
                )
            }
        )
        closed = preview_market_quotes(session, month.id, provider=provider, today=TODAY)
        assert closed.month_editable is False
        assert closed.rows[0].status is QuoteStatus.OK
        assert closed.rows[0].proposed_market_price_kopecks == 1500
        assert closed.rows[0].apply_allowed is False
    finally:
        session.close()
        database.engine.dispose()


def test_preview_is_read_only_and_idempotent(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month = create_reporting_month(session, year=2026, month=8, snapshot_date=SNAPSHOT_DATE)
        account = create_account(
            session, name="Synthetic Broker", account_type=AccountType.BROKERAGE
        )
        stock = create_instrument(session, name="Stock", instrument_type=InstrumentType.STOCK)
        set_accepted_mapping(session, stock.id, **_identity_kwargs(STOCK_IDENTITY))
        snapshot = create_position_snapshot(
            session,
            reporting_month_id=month.id,
            account_id=account.id,
            instrument_id=stock.id,
            quantity=3,
            average_cost_per_unit="100.00",
            market_price_per_unit="250.00",
            accrued_interest="1.00",
            price_date=date(2026, 8, 1),
            price_source=PriceSource.MOEX,
        )
        before_snap = _fingerprint_snapshot(session, snapshot.id)
        before_map = _fingerprint_mapping(session, stock.id)
        before_month = (month.status, month.snapshot_date, month.updated_at)
        provider = ScriptedProvider(
            {
                _identity_key(STOCK_IDENTITY): _success(
                    STOCK_IDENTITY,
                    kind=InstrumentType.STOCK,
                    raw_price="300.00",
                    basis=RawPriceBasis.CASH_PER_UNIT,
                    kopecks=30000,
                    price_date=TODAY,
                )
            }
        )
        first = preview_market_quotes(session, month.id, provider=provider, today=TODAY)
        second = preview_market_quotes(session, month.id, provider=provider, today=TODAY)
        assert first.rows[0].proposed_market_price_kopecks == 30000
        assert second.rows[0].proposed_market_price_kopecks == 30000
        assert _fingerprint_snapshot(session, snapshot.id) == before_snap
        assert _fingerprint_mapping(session, stock.id) == before_map
        assert (month.status, month.snapshot_date, month.updated_at) == before_month
        assert not session.new
        assert not session.dirty
        assert not session.deleted
    finally:
        session.close()
        database.engine.dispose()


def test_future_quote_date_is_rejected(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month = create_reporting_month(session, year=2026, month=7, snapshot_date=date(2026, 7, 31))
        account = create_account(
            session, name="Synthetic Broker", account_type=AccountType.BROKERAGE
        )
        stock = create_instrument(session, name="Stock", instrument_type=InstrumentType.STOCK)
        set_accepted_mapping(session, stock.id, **_identity_kwargs(STOCK_IDENTITY))
        create_position_snapshot(
            session,
            reporting_month_id=month.id,
            account_id=account.id,
            instrument_id=stock.id,
            quantity=1,
            average_cost_per_unit="10.00",
            market_price_per_unit="10.00",
            price_date=date(2026, 7, 15),
        )
        provider = ScriptedProvider(
            {
                _identity_key(STOCK_IDENTITY): _success(
                    STOCK_IDENTITY,
                    kind=InstrumentType.STOCK,
                    raw_price="15.00",
                    basis=RawPriceBasis.CASH_PER_UNIT,
                    kopecks=1500,
                    price_date=date(2026, 8, 1),
                )
            }
        )
        result = preview_market_quotes(session, month.id, provider=provider, today=TODAY)
        assert result.target_date == date(2026, 7, 31)
        assert result.rows[0].status is QuoteStatus.MALFORMED_RESPONSE
        assert result.rows[0].proposed_market_price_kopecks is None
        assert result.rows[0].apply_allowed is False
    finally:
        session.close()
        database.engine.dispose()
