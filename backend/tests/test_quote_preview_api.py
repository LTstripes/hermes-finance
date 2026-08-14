"""API tests for read-only quote refresh preview (R04-04)."""

from collections.abc import Generator
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hermes_finance.database import create_database
from hermes_finance.domain import InstrumentType
from hermes_finance.main import create_app
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
from hermes_finance.persistence import Base

TODAY = date(2026, 8, 13)
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


class ScriptedProvider:
    def __init__(self, quotes: dict[tuple[str, str, str | None], QuoteResult]) -> None:
        self.quotes = quotes
        self.fetch_calls: list[tuple[str, date]] = []
        self.started_calls = 0

    def discover_candidates(self, **kwargs: object) -> object:
        raise AssertionError("preview API must not discover candidates")

    def fetch_quote(self, identity: MarketIdentity, target_date: date) -> QuoteResult:
        self.fetch_calls.append((identity.provider_instrument_id, target_date))
        return self.quotes[market_identity_key(identity)]

    def fetch_quotes(self, items: list[tuple[MarketIdentity, date]]) -> list[QuoteResult]:
        return [self.fetch_quote(identity, target_date) for identity, target_date in items]


class ForbiddenProvider:
    def discover_candidates(self, **kwargs: object) -> object:
        raise AssertionError("provider must not be called")

    def fetch_quote(self, identity: MarketIdentity, target_date: date) -> QuoteResult:
        raise AssertionError("provider must not be called")

    def fetch_quotes(self, items: object) -> list[QuoteResult]:
        raise AssertionError("provider must not be called")


def _success(
    identity: MarketIdentity, kopecks: int, status: QuoteStatus = QuoteStatus.OK
) -> QuoteSuccess:
    return QuoteSuccess(
        identity=identity,
        instrument_kind=InstrumentType.STOCK,
        raw_price="15.00",
        raw_price_basis=RawPriceBasis.CASH_PER_UNIT,
        proposed_price_kopecks=kopecks,
        price_date=TODAY,
        quote_kind=QuoteKind.LAST,
        fetched_at_utc=FETCHED_AT,
        freshness_status=status,
    )


def _identity_key(identity: MarketIdentity) -> tuple[str, str, str | None]:
    return market_identity_key(identity)


@pytest.fixture
def provider() -> ScriptedProvider:
    return ScriptedProvider(
        {
            _identity_key(STOCK_IDENTITY): _success(STOCK_IDENTITY, 31245),
            _identity_key(FUND_IDENTITY): QuoteFailure(
                status=QuoteStatus.NETWORK_ERROR,
                message="timeout",
                identity=FUND_IDENTITY,
            ),
        }
    )


@pytest.fixture
def client(tmp_path: Path, provider: ScriptedProvider) -> Generator[TestClient, None, None]:
    database = create_database(tmp_path / "quote_preview_api.db")
    Base.metadata.create_all(database.engine)
    application = create_app(database, market_data_provider=provider)
    application.state.quote_preview_clock = lambda: TODAY
    try:
        with TestClient(application) as test_client:
            yield test_client
    finally:
        database.engine.dispose()


def _assert_error_body(body: dict, code: str) -> None:
    assert set(body) == {"error"}
    error = body["error"]
    assert set(error) == {"code", "message", "details"}
    assert error["code"] == code


def _create_month(client: TestClient, *, closed: bool = False) -> dict:
    created = client.post(
        "/api/months",
        json={"year": 2026, "month": 8, "snapshot_date": "2026-08-31"},
    )
    assert created.status_code == 201
    body = created.json()
    if closed:
        closed_response = client.post(f"/api/months/{body['id']}/close")
        assert closed_response.status_code == 200
        return closed_response.json()
    return body


def _create_account(client: TestClient) -> dict:
    response = client.post(
        "/api/accounts",
        json={"name": "Synthetic Broker", "account_type": "brokerage"},
    )
    assert response.status_code == 201
    return response.json()


def _create_instrument(
    client: TestClient, name: str, instrument_type: str = "stock", **extra: object
) -> dict:
    payload: dict[str, object] = {"name": name, "instrument_type": instrument_type}
    payload.update(extra)
    response = client.post("/api/instruments", json=payload)
    assert response.status_code == 201
    return response.json()


def _map(client: TestClient, instrument_id: int, identity: MarketIdentity) -> None:
    payload: dict[str, object] = {
        "provider": identity.provider,
        "provider_instrument_id": identity.provider_instrument_id,
        "provider_venue_id": identity.provider_venue_id,
    }
    if identity.isin:
        payload["isin"] = identity.isin
    response = client.put(
        f"/api/instruments/{instrument_id}/market-mapping",
        json=payload,
    )
    assert response.status_code == 200


def _position(
    client: TestClient,
    *,
    month_id: int,
    account_id: int,
    instrument_id: int,
    price: str = "200.00",
) -> dict:
    response = client.post(
        "/api/positions",
        json={
            "reporting_month_id": month_id,
            "account_id": account_id,
            "instrument_id": instrument_id,
            "quantity": "1",
            "average_cost_per_unit": {"amount": "100.00", "currency": "RUB"},
            "market_price_per_unit": {"amount": price, "currency": "RUB"},
            "price_date": "2026-08-01",
            "price_source": "manual",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_missing_month_is_not_found(client: TestClient) -> None:
    response = client.post("/api/months/999999/quote-preview")
    assert response.status_code == 404
    _assert_error_body(response.json(), "not_found")


def test_empty_month_returns_empty_rows(client: TestClient) -> None:
    month = _create_month(client)
    response = client.post(f"/api/months/{month['id']}/quote-preview")
    assert response.status_code == 200
    body = response.json()
    assert body["reporting_month_id"] == month["id"]
    assert body["month_status"] == "draft"
    assert body["target_date"] == "2026-08-13"
    assert body["month_editable"] is True
    assert body["rows"] == []
    assert body["batch_error"] is None


def test_mapped_and_failed_rows_and_closed_month(
    client: TestClient, provider: ScriptedProvider
) -> None:
    month = _create_month(client)
    account = _create_account(client)
    stock = _create_instrument(client, "Synthetic Stock", moex_secid="WRONG")
    fund = _create_instrument(client, "Synthetic Fund", instrument_type="fund")
    unmapped = _create_instrument(client, "Unmapped")
    _map(client, stock["id"], STOCK_IDENTITY)
    _map(client, fund["id"], FUND_IDENTITY)
    stock_pos = _position(
        client, month_id=month["id"], account_id=account["id"], instrument_id=stock["id"]
    )
    _position(
        client,
        month_id=month["id"],
        account_id=account["id"],
        instrument_id=fund["id"],
        price="11.00",
    )
    _position(
        client,
        month_id=month["id"],
        account_id=account["id"],
        instrument_id=unmapped["id"],
        price="9.00",
    )

    preview = client.post(f"/api/months/{month['id']}/quote-preview")
    assert preview.status_code == 200
    body = preview.json()
    rows = {row["instrument_id"]: row for row in body["rows"]}
    assert rows[stock["id"]]["status"] == "ok"
    assert rows[stock["id"]]["apply_allowed"] is False
    assert rows[stock["id"]]["current_market_price_per_unit"] == {
        "amount": "200.00",
        "currency": "RUB",
    }
    assert rows[stock["id"]]["proposed_market_price_per_unit"] == {
        "amount": "312.45",
        "currency": "RUB",
    }
    assert rows[stock["id"]]["identity"]["provider_instrument_id"] == "SBER"
    assert rows[fund["id"]]["status"] == "network_error"
    assert rows[fund["id"]]["proposed_market_price_per_unit"] is None
    assert rows[fund["id"]]["apply_allowed"] is False
    assert rows[unmapped["id"]]["status"] == "unmapped"
    assert rows[unmapped["id"]]["apply_allowed"] is False
    assert {secid for secid, _target in provider.fetch_calls} == {"SBER", "FXGD"}
    assert all(target == TODAY for _secid, target in provider.fetch_calls)

    listed = client.get(f"/api/positions?month_id={month['id']}")
    assert listed.status_code == 200
    unchanged = next(item for item in listed.json() if item["id"] == stock_pos["id"])
    assert unchanged["market_price_per_unit"] == {"amount": "200.00", "currency": "RUB"}
    assert unchanged["price_source"] == "manual"
    mapping = client.get(f"/api/instruments/{stock['id']}/market-mapping")
    assert mapping.json()["state"] == "mapped"

    closed = client.post(f"/api/months/{month['id']}/close")
    assert closed.status_code == 200
    closed_preview = client.post(f"/api/months/{month['id']}/quote-preview")
    assert closed_preview.status_code == 200
    closed_body = closed_preview.json()
    assert closed_body["month_status"] == "closed"
    assert closed_body["month_editable"] is False
    assert all(row["apply_allowed"] is False for row in closed_body["rows"])
    still_listed = client.get(f"/api/positions?month_id={month['id']}")
    still = next(item for item in still_listed.json() if item["id"] == stock_pos["id"])
    assert still["market_price_per_unit"]["amount"] == "200.00"
    assert still["updated_at"] == unchanged["updated_at"]


def test_startup_and_unmapped_do_not_call_provider(tmp_path: Path) -> None:
    database = create_database(tmp_path / "preview_startup.db")
    Base.metadata.create_all(database.engine)
    provider = ForbiddenProvider()
    application = create_app(database, market_data_provider=provider)
    application.state.quote_preview_clock = lambda: TODAY
    try:
        with TestClient(application) as client:
            assert client.get("/api/health").status_code == 200
            assert client.get("/api/months").status_code == 200
            month = _create_month(client)
            account = _create_account(client)
            instrument = _create_instrument(client, "Unmapped", moex_secid="SBER")
            _position(
                client,
                month_id=month["id"],
                account_id=account["id"],
                instrument_id=instrument["id"],
            )
            preview = client.post(f"/api/months/{month['id']}/quote-preview")
            assert preview.status_code == 200
            assert preview.json()["rows"][0]["status"] == "unmapped"
    finally:
        database.engine.dispose()


def test_unexpected_provider_raise_is_not_successful_preview(tmp_path: Path) -> None:
    database = create_database(tmp_path / "preview_raise.db")
    Base.metadata.create_all(database.engine)

    class ExplodingProvider:
        def discover_candidates(self, **kwargs: object) -> object:
            raise AssertionError("preview API must not discover candidates")

        def fetch_quote(self, identity: MarketIdentity, target_date: date) -> QuoteResult:
            raise AssertionError("preview API must use fetch_quotes")

        def fetch_quotes(self, items: object) -> list[QuoteResult]:
            raise RuntimeError("socket exploded")

    application = create_app(database, market_data_provider=ExplodingProvider())
    application.state.quote_preview_clock = lambda: TODAY
    try:
        with TestClient(application) as client:
            month = _create_month(client)
            account = _create_account(client)
            instrument = _create_instrument(client, "Mapped Stock")
            _map(client, instrument["id"], STOCK_IDENTITY)
            _position(
                client,
                month_id=month["id"],
                account_id=account["id"],
                instrument_id=instrument["id"],
            )
            with pytest.raises(RuntimeError, match="socket exploded"):
                client.post(f"/api/months/{month['id']}/quote-preview")
    finally:
        database.engine.dispose()


def test_production_preview_does_not_call_moex_or_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hermes_finance.market_data import moex_iss
    from hermes_finance.market_data.t_invest import TOKEN_UNAVAILABLE_MESSAGE

    def boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("MoexIssClient must not be constructed in production preview")

    monkeypatch.setattr(moex_iss, "MoexIssClient", boom)
    database = create_database(tmp_path / "preview_production.db")
    Base.metadata.create_all(database.engine)
    application = create_app(database)
    application.state.quote_preview_clock = lambda: TODAY
    try:
        with TestClient(application) as client:
            month = _create_month(client)
            account = _create_account(client)
            moex_instrument = _create_instrument(client, "MOEX Stock")
            t_instrument = _create_instrument(
                client, "T Stock", isin="RU000SYNTH01", moex_secid=None
            )
            _map(client, moex_instrument["id"], STOCK_IDENTITY)
            _map(
                client,
                t_instrument["id"],
                MarketIdentity(
                    provider="t_invest",
                    provider_instrument_id="11111111-1111-1111-1111-111111111111",
                    provider_venue_id=None,
                    isin="RU000SYNTH01",
                ),
            )
            _position(
                client,
                month_id=month["id"],
                account_id=account["id"],
                instrument_id=moex_instrument["id"],
            )
            _position(
                client,
                month_id=month["id"],
                account_id=account["id"],
                instrument_id=t_instrument["id"],
            )
            preview = client.post(f"/api/months/{month['id']}/quote-preview")
            assert preview.status_code == 200
            rows = {row["instrument_id"]: row for row in preview.json()["rows"]}
            assert rows[moex_instrument["id"]]["status"] == "unsupported"
            assert "production provider disabled" in (rows[moex_instrument["id"]]["message"] or "")
            assert rows[t_instrument["id"]]["status"] == "unavailable"
            assert rows[t_instrument["id"]]["message"] == TOKEN_UNAVAILABLE_MESSAGE
    finally:
        database.engine.dispose()
