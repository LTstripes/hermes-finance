"""API tests for R04-06 selective quote apply."""

from collections.abc import Generator
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hermes_finance.database import create_database
from hermes_finance.domain import InstrumentType
from hermes_finance.main import create_app
from hermes_finance.market_data.dto import (
    T_INVEST_PROVIDER,
    MarketIdentity,
    QuoteKind,
    QuoteResult,
    QuoteStatus,
    QuoteSuccess,
    RawPriceBasis,
    market_identity_key,
)
from hermes_finance.persistence import Base

TODAY = date(2026, 8, 13)
FETCHED_AT = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)
STOCK_UID = "11111111-1111-1111-1111-111111111111"
STOCK_IDENTITY = MarketIdentity(
    provider=T_INVEST_PROVIDER,
    provider_instrument_id=STOCK_UID,
    provider_venue_id=None,
)


class ScriptedProvider:
    def __init__(self, quotes: dict[tuple[str, str, str | None], QuoteResult]) -> None:
        self.quotes = quotes

    def discover_candidates(self, **kwargs: object) -> object:
        raise AssertionError("apply API must not discover candidates")

    def fetch_quote(self, identity: MarketIdentity, target_date: date) -> QuoteResult:
        return self.quotes[market_identity_key(identity)]

    def fetch_quotes(self, items: list[tuple[MarketIdentity, date]]) -> list[QuoteResult]:
        return [self.fetch_quote(identity, target_date) for identity, target_date in items]


def _success(
    identity: MarketIdentity, kopecks: int, status: QuoteStatus = QuoteStatus.OK
) -> QuoteSuccess:
    return QuoteSuccess(
        identity=identity,
        instrument_kind=InstrumentType.STOCK,
        raw_price="215.50",
        raw_price_basis=RawPriceBasis.CASH_PER_UNIT,
        proposed_price_kopecks=kopecks,
        price_date=TODAY,
        quote_kind=QuoteKind.LAST,
        fetched_at_utc=FETCHED_AT,
        freshness_status=status,
    )


@pytest.fixture
def client(tmp_path: Path) -> Generator[TestClient, None, None]:
    database = create_database(tmp_path / "quote_apply_api.db")
    Base.metadata.create_all(database.engine)
    provider = ScriptedProvider(
        {market_identity_key(STOCK_IDENTITY): _success(STOCK_IDENTITY, 21550)}
    )
    application = create_app(database, market_data_provider=provider)
    application.state.quote_preview_clock = lambda: TODAY
    try:
        with TestClient(application) as test_client:
            yield test_client
    finally:
        database.engine.dispose()


def _rub(amount: str) -> dict[str, str]:
    return {"amount": amount, "currency": "RUB"}


def _month(client: TestClient) -> dict:
    created = client.post(
        "/api/months", json={"year": 2026, "month": 8, "snapshot_date": "2026-08-31"}
    )
    assert created.status_code == 201
    return created.json()


def _setup_position(client: TestClient) -> tuple[dict, dict]:
    month = _month(client)
    account = client.post("/api/accounts", json={"name": "Broker", "account_type": "brokerage"})
    assert account.status_code == 201
    instrument = client.post(
        "/api/instruments", json={"name": "T Stock", "instrument_type": "stock"}
    )
    assert instrument.status_code == 201
    mapped = client.put(
        f"/api/instruments/{instrument.json()['id']}/market-mapping",
        json={
            "provider": T_INVEST_PROVIDER,
            "provider_instrument_id": STOCK_UID,
            "provider_venue_id": None,
        },
    )
    assert mapped.status_code == 200
    position = client.post(
        "/api/positions",
        json={
            "reporting_month_id": month["id"],
            "account_id": account.json()["id"],
            "instrument_id": instrument.json()["id"],
            "quantity": "10",
            "average_cost_per_unit": _rub("200.00"),
            "market_price_per_unit": _rub("200.00"),
            "accrued_interest": _rub("15.00"),
            "price_date": "2026-08-01",
            "price_source": "manual",
        },
    )
    assert position.status_code == 201
    return month, position.json()


def _apply_body(position_id: int, *, amount: str = "215.50", accept_stale: bool = False) -> dict:
    return {
        "rows": [
            {
                "position_snapshot_id": position_id,
                "accept_stale": accept_stale,
                "expected_market_price_per_unit": _rub(amount),
                "expected_price_date": "2026-08-13",
                "expected_identity": {
                    "provider": T_INVEST_PROVIDER,
                    "provider_instrument_id": STOCK_UID,
                    "provider_venue_id": None,
                },
                "expected_quote_kind": "last",
            }
        ]
    }


def test_apply_ok_row(client: TestClient) -> None:
    month, position = _setup_position(client)
    response = client.post(
        f"/api/months/{month['id']}/quote-apply", json=_apply_body(position["id"])
    )
    assert response.status_code == 200
    body = response.json()
    assert body["applied_count"] == 1
    assert body["rows"][0]["price_source"] == "t_invest"
    assert body["rows"][0]["market_price_per_unit"] == _rub("215.50")
    assert body["rows"][0]["accrued_interest"] == _rub("15.00")
    listed = client.get(f"/api/positions?month_id={month['id']}")
    assert listed.json()[0]["price_source"] == "t_invest"


def test_apply_preview_changed_is_conflict(client: TestClient) -> None:
    month, position = _setup_position(client)
    response = client.post(
        f"/api/months/{month['id']}/quote-apply",
        json=_apply_body(position["id"], amount="200.00"),
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "preview_changed"
    listed = client.get(f"/api/positions?month_id={month['id']}")
    assert listed.json()[0]["price_source"] == "manual"


def test_apply_closed_month_is_conflict(client: TestClient) -> None:
    month, position = _setup_position(client)
    closed = client.post(f"/api/months/{month['id']}/close")
    assert closed.status_code == 200
    response = client.post(
        f"/api/months/{month['id']}/quote-apply", json=_apply_body(position["id"])
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"
