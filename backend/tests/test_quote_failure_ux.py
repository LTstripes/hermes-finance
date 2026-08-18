"""R04-07 sanitized quote failure/recovery contract."""

from datetime import date, datetime, timezone
from pathlib import Path

import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from t_invest_mapping_fixtures import accept_t_invest_mapping

from hermes_finance.database import create_database
from hermes_finance.domain import AccountType, InstrumentType
from hermes_finance.main import create_app
from hermes_finance.market_data.dto import (
    T_INVEST_PROVIDER,
    DiscoverCandidate,
    DiscoverResult,
    MarketIdentity,
    QuoteFailure,
    QuoteKind,
    QuoteResult,
    QuoteStatus,
    QuoteSuccess,
    RawPriceBasis,
    market_identity_key,
)
from hermes_finance.market_data.t_invest import TOKEN_UNAVAILABLE_MESSAGE, TInvestClient
from hermes_finance.persistence import Base, PositionQuoteProvenance
from hermes_finance.services.accounts import create_account
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.positions import create_position_snapshot, update_position_snapshot
from hermes_finance.services.quote_apply import QuoteApplySelection, apply_market_quotes
from hermes_finance.services.quote_preview import QuoteFailureReason, preview_market_quotes
from hermes_finance.services.reporting_months import close_reporting_month, create_reporting_month

TODAY = date(2026, 8, 13)
SNAPSHOT_DATE = date(2026, 8, 31)
FETCHED_AT = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)
STOCK_UID = "11111111-1111-1111-1111-111111111111"
STOCK_IDENTITY = MarketIdentity(
    provider=T_INVEST_PROVIDER,
    provider_instrument_id=STOCK_UID,
    provider_venue_id=None,
)


class ForbiddenTransport(httpx2.BaseTransport):
    def handle_request(self, request: httpx2.Request) -> httpx2.Response:
        raise AssertionError(f"authenticated network must not be called: {request.url}")


class ScriptedProvider:
    def __init__(self, quotes: dict[tuple[str, str, str | None], QuoteResult]) -> None:
        self.quotes = quotes
        self.fetch_calls: list[tuple[MarketIdentity, date]] = []

    def discover_candidates(self, **kwargs: object) -> DiscoverResult:
        return DiscoverResult(
            status=QuoteStatus.OK,
            candidates=(
                DiscoverCandidate(identity=STOCK_IDENTITY, instrument_kind=InstrumentType.STOCK),
            ),
        )

    def fetch_quote(self, identity: MarketIdentity, target_date: date) -> QuoteResult:
        self.fetch_calls.append((identity, target_date))
        return self.quotes[market_identity_key(identity)]

    def fetch_quotes(self, items: list[tuple[MarketIdentity, date]]) -> list[QuoteResult]:
        return [self.fetch_quote(identity, target_date) for identity, target_date in items]


def _session(tmp_path: Path):
    database = create_database(tmp_path / "quote-failure.db")
    Base.metadata.create_all(database.engine)
    return database.session_factory(), database


def _success(identity: MarketIdentity, kopecks: int = 21550) -> QuoteSuccess:
    return QuoteSuccess(
        identity=identity,
        instrument_kind=InstrumentType.STOCK,
        raw_price="215.50",
        raw_price_basis=RawPriceBasis.CASH_PER_UNIT,
        proposed_price_kopecks=kopecks,
        price_date=TODAY,
        quote_kind=QuoteKind.LAST,
        fetched_at_utc=FETCHED_AT,
        freshness_status=QuoteStatus.OK,
    )


def _mapped_stock(session):
    month = create_reporting_month(session, year=2026, month=8, snapshot_date=SNAPSHOT_DATE)
    account = create_account(session, name="Broker", account_type=AccountType.BROKERAGE)
    stock = create_instrument(session, name="T Stock", instrument_type=InstrumentType.STOCK)
    accept_t_invest_mapping(session, stock.id, STOCK_UID, kind=InstrumentType.STOCK)
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
    return month, snapshot


def test_missing_token_preview_makes_no_authenticated_call(tmp_path: Path) -> None:
    session, database = _session(tmp_path)
    try:
        month, snapshot = _mapped_stock(session)
        http = httpx2.Client(transport=ForbiddenTransport())
        provider = TInvestClient(token=None, client=http)
        result = preview_market_quotes(session, month.id, provider=provider, today=TODAY)
        row = result.rows[0]
        assert row.position_snapshot_id == snapshot.id
        assert row.status is QuoteStatus.UNAVAILABLE
        assert row.failure_reason is QuoteFailureReason.TOKEN_UNAVAILABLE
        assert row.message is not None
        assert "token" in row.message.lower()
        assert "t." not in row.message
        assert row.apply_allowed is False
        assert row.current_market_price_kopecks == 10000
        assert result.batch_error_reason is QuoteFailureReason.TOKEN_UNAVAILABLE
        assert "t." not in (result.batch_error or "")
    finally:
        session.close()
        database.engine.dispose()


@pytest.mark.parametrize(
    ("status", "raw", "reason"),
    [
        (
            QuoteStatus.NETWORK_ERROR,
            "timeout from upstream 502",
            QuoteFailureReason.PROVIDER_NETWORK,
        ),
        (
            QuoteStatus.UNAVAILABLE,
            "no valid quote in lookback window",
            QuoteFailureReason.QUOTE_UNAVAILABLE,
        ),
        (
            QuoteStatus.UNSUPPORTED,
            "bond quote is not RUB-compatible",
            QuoteFailureReason.UNSUPPORTED,
        ),
        (
            QuoteStatus.MALFORMED_RESPONSE,
            "quote is not a positive amount",
            QuoteFailureReason.MALFORMED,
        ),
        (QuoteStatus.UNAVAILABLE, TOKEN_UNAVAILABLE_MESSAGE, QuoteFailureReason.TOKEN_UNAVAILABLE),
    ],
)
def test_preview_sanitizes_provider_messages(
    tmp_path: Path, status: QuoteStatus, raw: str, reason: QuoteFailureReason
) -> None:
    session, database = _session(tmp_path)
    try:
        month, _snapshot = _mapped_stock(session)
        result = preview_market_quotes(
            session,
            month.id,
            provider=ScriptedProvider(
                {
                    market_identity_key(STOCK_IDENTITY): QuoteFailure(
                        status=status, message=raw, identity=STOCK_IDENTITY
                    )
                }
            ),
            today=TODAY,
        )
        row = result.rows[0]
        assert row.failure_reason is reason
        assert row.message is not None
        assert raw not in row.message
        assert "502" not in row.message
        assert "timeout" not in row.message
    finally:
        session.close()
        database.engine.dispose()


def test_preview_api_does_not_leak_raw_provider_text(tmp_path: Path) -> None:
    database = create_database(tmp_path / "quote-failure-api.db")
    Base.metadata.create_all(database.engine)
    provider = ScriptedProvider(
        {
            market_identity_key(STOCK_IDENTITY): QuoteFailure(
                status=QuoteStatus.NETWORK_ERROR,
                message="upstream timeout Authorization: Bearer t.secret",
                identity=STOCK_IDENTITY,
            )
        }
    )
    application = create_app(database, market_data_provider=provider)
    application.state.quote_preview_clock = lambda: TODAY
    try:
        with TestClient(application) as client:
            month = client.post(
                "/api/months", json={"year": 2026, "month": 8, "snapshot_date": "2026-08-31"}
            )
            account = client.post(
                "/api/accounts", json={"name": "Broker", "account_type": "brokerage"}
            )
            instrument = client.post(
                "/api/instruments", json={"name": "T Stock", "instrument_type": "stock"}
            )
            mapped = client.put(
                f"/api/instruments/{instrument.json()['id']}/market-mapping",
                params={"verify": "true"},
                json={
                    "provider": T_INVEST_PROVIDER,
                    "provider_instrument_id": STOCK_UID,
                    "provider_venue_id": None,
                },
            )
            assert mapped.status_code == 200
            client.post(
                "/api/positions",
                json={
                    "reporting_month_id": month.json()["id"],
                    "account_id": account.json()["id"],
                    "instrument_id": instrument.json()["id"],
                    "quantity": "1",
                    "average_cost_per_unit": {"amount": "100.00", "currency": "RUB"},
                    "market_price_per_unit": {"amount": "100.00", "currency": "RUB"},
                    "price_date": "2026-08-01",
                    "price_source": "manual",
                },
            )
            preview = client.post(f"/api/months/{month.json()['id']}/quote-preview")
            assert preview.status_code == 200
            body = preview.json()
            dumped = preview.text
            assert "t.secret" not in dumped
            assert "Bearer" not in dumped
            assert "Authorization" not in dumped
            row = body["rows"][0]
            assert row["failure_reason"] == "provider_network"
            assert row["message"] is not None
            assert "Local Hermes Finance is running" in row["message"]
            assert body["batch_error_reason"] == "provider_network"
            assert "Bearer" not in (body["batch_error"] or "")
    finally:
        database.engine.dispose()


def test_t_invest_mixed_success_keeps_good_row_applicable(tmp_path: Path) -> None:
    session, database = _session(tmp_path)
    try:
        month, snapshot = _mapped_stock(session)
        failed = create_instrument(
            session, name="Broken Stock", instrument_type=InstrumentType.STOCK
        )
        failed_uid = "22222222-2222-2222-2222-222222222222"
        failed_identity = MarketIdentity(
            provider=T_INVEST_PROVIDER,
            provider_instrument_id=failed_uid,
            provider_venue_id=None,
        )
        accept_t_invest_mapping(session, failed.id, failed_uid, kind=InstrumentType.STOCK)
        create_position_snapshot(
            session,
            reporting_month_id=month.id,
            account_id=snapshot.account_id,
            instrument_id=failed.id,
            quantity="1",
            average_cost_per_unit="100.00",
            market_price_per_unit="100.00",
            price_date=date(2026, 8, 1),
        )
        result = preview_market_quotes(
            session,
            month.id,
            provider=ScriptedProvider(
                {
                    market_identity_key(STOCK_IDENTITY): _success(STOCK_IDENTITY),
                    market_identity_key(failed_identity): QuoteFailure(
                        status=QuoteStatus.NETWORK_ERROR,
                        message="timeout from upstream 502",
                        identity=failed_identity,
                    ),
                }
            ),
            today=TODAY,
        )
        by_name = {row.instrument_name: row for row in result.rows}
        assert result.batch_error is None
        assert by_name["T Stock"].apply_allowed is True
        assert by_name["T Stock"].status is QuoteStatus.OK
        assert by_name["Broken Stock"].apply_allowed is False
        assert by_name["Broken Stock"].failure_reason is QuoteFailureReason.PROVIDER_NETWORK
        assert "502" not in (by_name["Broken Stock"].message or "")
    finally:
        session.close()
        database.engine.dispose()


def test_all_network_failures_set_sanitized_batch_error(tmp_path: Path) -> None:
    session, database = _session(tmp_path)
    try:
        month, _snapshot = _mapped_stock(session)
        result = preview_market_quotes(
            session,
            month.id,
            provider=ScriptedProvider(
                {
                    market_identity_key(STOCK_IDENTITY): QuoteFailure(
                        status=QuoteStatus.NETWORK_ERROR,
                        message="timeout from upstream 502",
                        identity=STOCK_IDENTITY,
                    )
                }
            ),
            today=TODAY,
        )
        assert result.batch_error_reason is QuoteFailureReason.PROVIDER_NETWORK
        assert result.batch_error is not None
        assert "timeout" not in result.batch_error
        assert "502" not in result.batch_error
        assert result.rows[0].apply_allowed is False
    finally:
        session.close()
        database.engine.dispose()


def test_missing_token_sets_batch_reason_and_leaves_manual_path(
    tmp_path: Path,
) -> None:
    session, database = _session(tmp_path)
    try:
        month, snapshot = _mapped_stock(session)
        http = httpx2.Client(transport=ForbiddenTransport())
        provider = TInvestClient(token=None, client=http)
        preview = preview_market_quotes(session, month.id, provider=provider, today=TODAY)
        assert preview.batch_error_reason is QuoteFailureReason.TOKEN_UNAVAILABLE
        assert preview.rows[0].current_market_price_kopecks == 10000

        updated = update_position_snapshot(
            session,
            snapshot.id,
            market_price_per_unit="125.00",
            price_date=date(2026, 8, 2),
            price_source="manual",
        )
        assert updated.price_source == "manual"
        assert updated.market_price_per_unit_kopecks == 12500
        assert session.scalars(select(PositionQuoteProvenance)).first() is None

        with pytest.raises(ValueError, match="quote apply"):
            update_position_snapshot(session, snapshot.id, price_source="t_invest")
    finally:
        session.close()
        database.engine.dispose()


def test_closed_month_preview_cannot_apply(tmp_path: Path) -> None:
    session, database = _session(tmp_path)
    try:
        month, _snapshot = _mapped_stock(session)
        close_reporting_month(session, month.id)
        preview = preview_market_quotes(
            session,
            month.id,
            provider=ScriptedProvider(
                {market_identity_key(STOCK_IDENTITY): _success(STOCK_IDENTITY)}
            ),
            today=TODAY,
        )
        assert preview.month_editable is False
        assert preview.rows[0].apply_allowed is False
        with pytest.raises(ValueError, match="closed"):
            apply_market_quotes(
                session,
                month.id,
                [
                    QuoteApplySelection(
                        position_snapshot_id=preview.rows[0].position_snapshot_id,
                        accept_stale=False,
                        expected_market_price_kopecks=21550,
                        expected_price_date=TODAY,
                        expected_identity=STOCK_IDENTITY,
                        expected_quote_kind="last",
                    )
                ],
                provider=ScriptedProvider(
                    {market_identity_key(STOCK_IDENTITY): _success(STOCK_IDENTITY)}
                ),
                today=TODAY,
            )
    finally:
        session.close()
        database.engine.dispose()
