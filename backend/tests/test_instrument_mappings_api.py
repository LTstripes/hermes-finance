"""API tests for instrument market-data mapping (R04-03)."""

from collections.abc import Generator
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hermes_finance.database import create_database
from hermes_finance.domain import InstrumentType
from hermes_finance.main import create_app
from hermes_finance.market_data.dto import (
    DiscoverCandidate,
    DiscoverResult,
    MarketIdentity,
    QuoteStatus,
)
from hermes_finance.persistence import Base

MAPPING_KEYS = {
    "instrument_id",
    "state",
    "identity",
    "instrument_isin",
    "legacy_moex_secid",
}
IDENTITY_KEYS = {"provider", "engine", "market", "boardid", "secid"}
STOCK_PAYLOAD = {
    "provider": "moex_iss",
    "engine": "stock",
    "market": "shares",
    "boardid": "TQBR",
    "secid": "SBER",
}


class RecordingProvider:
    def __init__(self, result: DiscoverResult) -> None:
        self.result = result
        self.discover_calls = 0

    def discover_candidates(self, **kwargs: object) -> DiscoverResult:
        self.discover_calls += 1
        return self.result

    def fetch_quote(self, identity: MarketIdentity, target_date: date) -> object:
        raise AssertionError("mapping API must not fetch quotes")

    def fetch_quotes(self, items: object) -> list[object]:
        raise AssertionError("mapping API must not fetch quotes")


class ForbiddenProvider:
    def discover_candidates(self, **kwargs: object) -> DiscoverResult:
        raise AssertionError("provider must not run without verify=true")

    def fetch_quote(self, identity: MarketIdentity, target_date: date) -> object:
        raise AssertionError("mapping API must not fetch quotes")

    def fetch_quotes(self, items: object) -> list[object]:
        raise AssertionError("mapping API must not fetch quotes")


@pytest.fixture
def client(tmp_path: Path) -> Generator[TestClient, None, None]:
    database = create_database(tmp_path / "instrument_mappings_api.db")
    Base.metadata.create_all(database.engine)
    try:
        with TestClient(
            create_app(database, market_data_provider=ForbiddenProvider())
        ) as test_client:
            yield test_client
    finally:
        database.engine.dispose()


def _assert_error_body(body: dict, code: str) -> None:
    assert set(body) == {"error"}
    error = body["error"]
    assert set(error) == {"code", "message", "details"}
    assert error["code"] == code
    assert isinstance(error["message"], str)
    assert isinstance(error["details"], list)


def _create_instrument(client: TestClient, **overrides: object) -> dict:
    payload: dict[str, object] = {
        "name": "Synthetic Stock",
        "instrument_type": "stock",
        "isin": "RU0009029540",
        "moex_secid": "SBER",
    }
    payload.update(overrides)
    response = client.post("/api/instruments", json=payload)
    assert response.status_code == 201
    return response.json()


def test_get_without_mapping_is_unmapped(client: TestClient) -> None:
    created = _create_instrument(client)
    response = client.get(f"/api/instruments/{created['id']}/market-mapping")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == MAPPING_KEYS
    assert body["instrument_id"] == created["id"]
    assert body["state"] == "unmapped"
    assert body["identity"] is None
    assert body["instrument_isin"] == "RU0009029540"
    assert body["legacy_moex_secid"] == "SBER"


def test_put_complete_identity_maps_instrument(client: TestClient) -> None:
    created = _create_instrument(client)
    response = client.put(f"/api/instruments/{created['id']}/market-mapping", json=STOCK_PAYLOAD)
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "mapped"
    assert set(body["identity"]) == IDENTITY_KEYS
    assert body["identity"] == {
        "provider": "moex_iss",
        "engine": "stock",
        "market": "shares",
        "boardid": "TQBR",
        "secid": "SBER",
    }


def test_put_partial_identity_is_unprocessable(client: TestClient) -> None:
    created = _create_instrument(client)
    payload = dict(STOCK_PAYLOAD)
    del payload["boardid"]
    response = client.put(f"/api/instruments/{created['id']}/market-mapping", json=payload)
    assert response.status_code == 422
    _assert_error_body(response.json(), "unprocessable")
    current = client.get(f"/api/instruments/{created['id']}/market-mapping")
    assert current.json()["state"] == "unmapped"


def test_delete_mapping_returns_unmapped(client: TestClient) -> None:
    created = _create_instrument(client)
    client.put(f"/api/instruments/{created['id']}/market-mapping", json=STOCK_PAYLOAD)
    response = client.delete(f"/api/instruments/{created['id']}/market-mapping")
    assert response.status_code == 200
    assert response.json()["state"] == "unmapped"
    assert response.json()["identity"] is None


def test_exclude_from_unmapped_and_mapped(client: TestClient) -> None:
    created = _create_instrument(client)
    excluded = client.put(f"/api/instruments/{created['id']}/market-mapping/exclusion")
    assert excluded.status_code == 200
    assert excluded.json()["state"] == "excluded"
    assert excluded.json()["identity"] is None

    mapped = client.put(f"/api/instruments/{created['id']}/market-mapping", json=STOCK_PAYLOAD)
    assert mapped.json()["state"] == "mapped"
    excluded_again = client.put(f"/api/instruments/{created['id']}/market-mapping/exclusion")
    assert excluded_again.json()["state"] == "excluded"
    assert excluded_again.json()["identity"]["secid"] == "SBER"


def test_exclusion_is_reversible(client: TestClient) -> None:
    created = _create_instrument(client)
    client.put(f"/api/instruments/{created['id']}/market-mapping", json=STOCK_PAYLOAD)
    client.put(f"/api/instruments/{created['id']}/market-mapping/exclusion")
    restored = client.delete(f"/api/instruments/{created['id']}/market-mapping/exclusion")
    assert restored.status_code == 200
    assert restored.json()["state"] == "mapped"
    assert restored.json()["identity"]["boardid"] == "TQBR"


def test_isin_mismatch_and_unsupported_type_are_unprocessable(client: TestClient) -> None:
    stock = _create_instrument(client)
    mismatch = client.put(
        f"/api/instruments/{stock['id']}/market-mapping",
        json={**STOCK_PAYLOAD, "isin": "RU0000000000"},
    )
    assert mismatch.status_code == 422
    _assert_error_body(mismatch.json(), "unprocessable")
    assert "isin mismatch" in mismatch.json()["error"]["message"]

    gold = _create_instrument(
        client, name="Synthetic Gold", instrument_type="gold", isin=None, moex_secid=None
    )
    unsupported = client.put(f"/api/instruments/{gold['id']}/market-mapping", json=STOCK_PAYLOAD)
    assert unsupported.status_code == 422
    _assert_error_body(unsupported.json(), "unprocessable")
    assert "unsupported instrument type" in unsupported.json()["error"]["message"]


def test_incompatible_engine_market_is_unprocessable(client: TestClient) -> None:
    bond = _create_instrument(
        client,
        name="Synthetic Bond",
        instrument_type="bond",
        isin="RU000A0JX0J2",
        moex_secid="SU26238",
    )
    response = client.put(f"/api/instruments/{bond['id']}/market-mapping", json=STOCK_PAYLOAD)
    assert response.status_code == 422
    _assert_error_body(response.json(), "unprocessable")
    assert "incompatible" in response.json()["error"]["message"]


def test_unknown_instrument_mapping_is_not_found(client: TestClient) -> None:
    missing = client.get("/api/instruments/999999/market-mapping")
    assert missing.status_code == 404
    _assert_error_body(missing.json(), "not_found")

    missing_put = client.put("/api/instruments/999999/market-mapping", json=STOCK_PAYLOAD)
    assert missing_put.status_code == 404
    _assert_error_body(missing_put.json(), "not_found")

    missing_delete = client.delete("/api/instruments/999999/market-mapping")
    assert missing_delete.status_code == 404
    _assert_error_body(missing_delete.json(), "not_found")

    missing_exclude = client.put("/api/instruments/999999/market-mapping/exclusion")
    assert missing_exclude.status_code == 404
    _assert_error_body(missing_exclude.json(), "not_found")


def test_verify_true_uses_injected_provider_and_rejects_ambiguity(tmp_path: Path) -> None:
    database = create_database(tmp_path / "mapping_verify.db")
    Base.metadata.create_all(database.engine)
    other = MarketIdentity(
        provider="moex_iss",
        engine="stock",
        market="shares",
        boardid="TQTF",
        secid="SBER",
    )
    provider = RecordingProvider(
        DiscoverResult(
            status=QuoteStatus.AMBIGUOUS,
            candidates=(
                DiscoverCandidate(identity=other, instrument_kind=InstrumentType.STOCK),
                DiscoverCandidate(
                    identity=MarketIdentity(
                        provider="moex_iss",
                        engine="stock",
                        market="shares",
                        boardid="FQBR",
                        secid="SBER",
                    ),
                    instrument_kind=InstrumentType.STOCK,
                ),
            ),
        )
    )
    try:
        with TestClient(create_app(database, market_data_provider=provider)) as client:
            created = _create_instrument(client)
            without_verify = client.put(
                f"/api/instruments/{created['id']}/market-mapping",
                json=STOCK_PAYLOAD,
            )
            assert without_verify.status_code == 200
            assert provider.discover_calls == 0
            client.delete(f"/api/instruments/{created['id']}/market-mapping")
            ambiguous = client.put(
                f"/api/instruments/{created['id']}/market-mapping",
                params={"verify": "true"},
                json=STOCK_PAYLOAD,
            )
            assert ambiguous.status_code == 422
            _assert_error_body(ambiguous.json(), "unprocessable")
            assert "ambiguous" in ambiguous.json()["error"]["message"]
            assert provider.discover_calls == 1
            assert client.get(f"/api/instruments/{created['id']}/market-mapping").json()[
                "state"
            ] == ("unmapped")
    finally:
        database.engine.dispose()
