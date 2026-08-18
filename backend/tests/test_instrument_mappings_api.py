"""API tests for instrument market-data mapping (R04-03)."""

import json
from collections.abc import Generator
from datetime import UTC, date, datetime
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
    QuoteKind,
    QuoteStatus,
    QuoteSuccess,
    RawPriceBasis,
)
from hermes_finance.market_data.moex_identity import market_identity_from_moex
from hermes_finance.persistence import Base

MAPPING_KEYS = {
    "instrument_id",
    "state",
    "identity",
    "instrument_isin",
    "legacy_moex_secid",
}
IDENTITY_KEYS = {"provider", "provider_instrument_id", "provider_venue_id"}
STOCK_PAYLOAD = {
    "provider": "moex_iss",
    "provider_instrument_id": "SBER",
    "provider_venue_id": "stock/shares/TQBR",
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
        "provider_instrument_id": "SBER",
        "provider_venue_id": "stock/shares/TQBR",
    }


def test_put_partial_identity_is_unprocessable(client: TestClient) -> None:
    created = _create_instrument(client)
    payload = dict(STOCK_PAYLOAD)
    del payload["provider_instrument_id"]
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
    assert excluded_again.json()["identity"]["provider_instrument_id"] == "SBER"


def test_exclusion_is_reversible(client: TestClient) -> None:
    created = _create_instrument(client)
    client.put(f"/api/instruments/{created['id']}/market-mapping", json=STOCK_PAYLOAD)
    client.put(f"/api/instruments/{created['id']}/market-mapping/exclusion")
    restored = client.delete(f"/api/instruments/{created['id']}/market-mapping/exclusion")
    assert restored.status_code == 200
    assert restored.json()["state"] == "mapped"
    assert restored.json()["identity"]["provider_venue_id"] == "stock/shares/TQBR"


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
    other = market_identity_from_moex(
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
                    identity=market_identity_from_moex(
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


T_INVEST_UID = "11111111-1111-1111-1111-111111111111"
T_INVEST_PAYLOAD = {
    "provider": "t_invest",
    "provider_instrument_id": T_INVEST_UID,
    "provider_venue_id": None,
}


def test_t_invest_identity_save_and_venue_rejected(client: TestClient) -> None:
    created = _create_instrument(client)
    rejected = client.put(
        f"/api/instruments/{created['id']}/market-mapping",
        json={**T_INVEST_PAYLOAD, "provider_venue_id": "TQBR"},
    )
    assert rejected.status_code == 422
    bypass = client.put(f"/api/instruments/{created['id']}/market-mapping", json=T_INVEST_PAYLOAD)
    assert bypass.status_code == 422
    _assert_error_body(bypass.json(), "unprocessable")
    assert "requires provider verification" in bypass.json()["error"]["message"]

    saved = client.put(
        f"/api/instruments/{created['id']}/market-mapping",
        json={**T_INVEST_PAYLOAD, "isin": "RU0009029540"},
    )
    assert saved.status_code == 200
    assert saved.json()["identity"] == {
        "provider": "t_invest",
        "provider_instrument_id": T_INVEST_UID,
        "provider_venue_id": None,
    }


def test_verify_true_accepts_exact_t_invest_uid(tmp_path: Path) -> None:
    database = create_database(tmp_path / "mapping_verify_t.db")
    Base.metadata.create_all(database.engine)
    identity = MarketIdentity(
        provider="t_invest",
        provider_instrument_id=T_INVEST_UID,
        provider_venue_id=None,
        isin="RU0009029540",
    )
    provider = RecordingProvider(
        DiscoverResult(
            status=QuoteStatus.OK,
            candidates=(
                DiscoverCandidate(identity=identity, instrument_kind=InstrumentType.STOCK),
            ),
        )
    )
    try:
        with TestClient(create_app(database, market_data_provider=provider)) as client:
            created = _create_instrument(client)
            verified = client.put(
                f"/api/instruments/{created['id']}/market-mapping",
                params={"verify": "true"},
                json=T_INVEST_PAYLOAD,
            )
            assert verified.status_code == 200
            assert verified.json()["identity"]["provider_instrument_id"] == T_INVEST_UID
            assert provider.discover_calls == 1
    finally:
        database.engine.dispose()


def test_discover_is_explicit_and_does_not_persist(tmp_path: Path) -> None:
    database = create_database(tmp_path / "mapping_discover.db")
    Base.metadata.create_all(database.engine)
    identity = MarketIdentity(
        provider="t_invest",
        provider_instrument_id=T_INVEST_UID,
        provider_venue_id=None,
        isin="RU0009029540",
    )
    provider = RecordingProvider(
        DiscoverResult(
            status=QuoteStatus.OK,
            candidates=(
                DiscoverCandidate(identity=identity, instrument_kind=InstrumentType.STOCK),
            ),
        )
    )
    try:
        with TestClient(create_app(database, market_data_provider=provider)) as client:
            created = _create_instrument(client)
            assert provider.discover_calls == 0
            mapping_before = client.get(f"/api/instruments/{created['id']}/market-mapping")
            assert mapping_before.json()["state"] == "unmapped"
            discovered = client.post(
                f"/api/instruments/{created['id']}/market-mapping/discover",
                json={"provider": "t_invest"},
            )
            assert discovered.status_code == 200
            body = discovered.json()
            assert body["status"] == "ok"
            assert body["candidates"][0]["provider_instrument_id"] == T_INVEST_UID
            assert body["candidates"][0]["provider_venue_id"] is None
            assert body["candidates"][0]["instrument_kind"] == "stock"
            assert "figi" not in json.dumps(body)
            assert provider.discover_calls == 1
            mapping_after = client.get(f"/api/instruments/{created['id']}/market-mapping")
            assert mapping_after.json()["state"] == "unmapped"
            assert mapping_after.json()["identity"] is None
    finally:
        database.engine.dispose()


def test_discover_projects_disambiguation_metadata_without_auto_select(
    tmp_path: Path,
) -> None:
    database = create_database(tmp_path / "mapping_discover_meta.db")
    Base.metadata.create_all(database.engine)
    first_uid = "aaaa1111-1111-4111-8111-111111111111"
    second_uid = "aaaa2222-2222-4222-8222-222222222222"
    provider = RecordingProvider(
        DiscoverResult(
            status=QuoteStatus.AMBIGUOUS,
            candidates=(
                DiscoverCandidate(
                    identity=MarketIdentity(
                        provider="t_invest",
                        provider_instrument_id=first_uid,
                        provider_venue_id=None,
                        isin="RU000SYNTH76",
                    ),
                    instrument_kind=InstrumentType.BOND,
                    name="ОФЗ 26248 основной",
                    ticker="SU26248",
                    class_code="TQOB",
                    exchange="MOEX",
                    api_trade_available=True,
                    position_uid="bbbb1111-1111-4111-8111-111111111111",
                ),
                DiscoverCandidate(
                    identity=MarketIdentity(
                        provider="t_invest",
                        provider_instrument_id=second_uid,
                        provider_venue_id=None,
                        isin="RU000SYNTH76",
                    ),
                    instrument_kind=InstrumentType.BOND,
                    name="ОФЗ 26248 внебиржевой контур",
                    ticker="SU26248OTC",
                    class_code="PSAU",
                    exchange="MOEX",
                    api_trade_available=False,
                    position_uid="bbbb2222-2222-4222-8222-222222222222",
                ),
            ),
        )
    )
    try:
        with TestClient(create_app(database, market_data_provider=provider)) as client:
            created = _create_instrument(
                client,
                name="Synthetic Bond",
                instrument_type="bond",
                isin="RU000SYNTH76",
            )
            discovered = client.post(
                f"/api/instruments/{created['id']}/market-mapping/discover",
                json={"provider": "t_invest"},
            )
            assert discovered.status_code == 200
            body = discovered.json()
            assert body["status"] == "ambiguous"
            assert len(body["candidates"]) == 2
            first = body["candidates"][0]
            assert first["provider_instrument_id"] == first_uid
            assert first["name"] == "ОФЗ 26248 основной"
            assert first["ticker"] == "SU26248"
            assert first["class_code"] == "TQOB"
            assert first["exchange"] == "MOEX"
            assert first["api_trade_available"] is True
            assert first["position_uid"] == "bbbb1111-1111-4111-8111-111111111111"
            dumped = json.dumps(body)
            assert "figi" not in dumped
            assert "Authorization" not in dumped
            mapping_after = client.get(f"/api/instruments/{created['id']}/market-mapping")
            assert mapping_after.json()["state"] == "unmapped"
            assert mapping_after.json()["identity"] is None
    finally:
        database.engine.dispose()


def test_discover_without_token_is_calm_and_leaks_nothing(tmp_path: Path) -> None:
    database = create_database(tmp_path / "mapping_discover_token.db")
    Base.metadata.create_all(database.engine)
    application = create_app(database)
    try:
        with TestClient(application) as client:
            created = _create_instrument(client)
            discovered = client.post(
                f"/api/instruments/{created['id']}/market-mapping/discover",
                json={"provider": "t_invest"},
            )
            assert discovered.status_code == 200
            body = discovered.json()
            assert body["status"] == "unavailable"
            assert "token" in (body["message"] or "").lower()
            assert "Authorization" not in json.dumps(body)
            assert "t." not in json.dumps(body)
    finally:
        database.engine.dispose()


def test_production_verify_moex_does_not_construct_moex_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hermes_finance.market_data import moex_iss

    def boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("MoexIssClient must not be constructed in production verify")

    monkeypatch.setattr(moex_iss, "MoexIssClient", boom)
    database = create_database(tmp_path / "mapping_verify_moex.db")
    Base.metadata.create_all(database.engine)
    try:
        with TestClient(create_app(database)) as client:
            created = _create_instrument(client)
            verified = client.put(
                f"/api/instruments/{created['id']}/market-mapping",
                params={"verify": "true"},
                json=STOCK_PAYLOAD,
            )
            assert verified.status_code == 422
            assert "production provider disabled" in verified.json()["error"]["message"]
            local = client.put(
                f"/api/instruments/{created['id']}/market-mapping",
                json=STOCK_PAYLOAD,
            )
            assert local.status_code == 200
            assert local.json()["state"] == "mapped"
    finally:
        database.engine.dispose()


def test_t_invest_candidate_isin_mismatch_is_unprocessable(client: TestClient) -> None:
    created = _create_instrument(client)
    mismatch = client.put(
        f"/api/instruments/{created['id']}/market-mapping",
        json={**T_INVEST_PAYLOAD, "isin": "RU0000000000"},
    )
    assert mismatch.status_code == 422
    _assert_error_body(mismatch.json(), "unprocessable")
    assert "isin mismatch" in mismatch.json()["error"]["message"]
    assert client.get(f"/api/instruments/{created['id']}/market-mapping").json()["state"] == (
        "unmapped"
    )


def test_t_invest_verify_rejects_wrong_uid_and_does_not_persist(tmp_path: Path) -> None:
    database = create_database(tmp_path / "mapping_verify_fail.db")
    Base.metadata.create_all(database.engine)
    provider = RecordingProvider(
        DiscoverResult(
            status=QuoteStatus.UNAVAILABLE,
            message="T-Invest instrument was not found",
        )
    )
    try:
        with TestClient(create_app(database, market_data_provider=provider)) as client:
            created = _create_instrument(client)
            rejected = client.put(
                f"/api/instruments/{created['id']}/market-mapping",
                params={"verify": "true"},
                json=T_INVEST_PAYLOAD,
            )
            assert rejected.status_code == 422
            _assert_error_body(rejected.json(), "unprocessable")
            assert "was not found among provider candidates" in rejected.json()["error"]["message"]
            assert provider.discover_calls == 1
            assert client.get(f"/api/instruments/{created['id']}/market-mapping").json()[
                "state"
            ] == ("unmapped")
    finally:
        database.engine.dispose()


class MappingThenPreviewProvider:
    def __init__(self, identity: MarketIdentity, quote: QuoteSuccess) -> None:
        self.identity = identity
        self.quote = quote
        self.discover_calls = 0
        self.fetch_calls = 0

    def discover_candidates(self, **kwargs: object) -> DiscoverResult:
        self.discover_calls += 1
        return DiscoverResult(
            status=QuoteStatus.OK,
            candidates=(
                DiscoverCandidate(identity=self.identity, instrument_kind=InstrumentType.STOCK),
            ),
        )

    def fetch_quote(self, identity: MarketIdentity, target_date: date) -> QuoteSuccess:
        self.fetch_calls += 1
        assert identity.provider == "t_invest"
        assert identity.provider_instrument_id == self.identity.provider_instrument_id
        assert target_date == date(2026, 8, 13)
        return self.quote

    def fetch_quotes(self, items: list[tuple[MarketIdentity, date]]) -> list[QuoteSuccess]:
        return [self.fetch_quote(identity, target_date) for identity, target_date in items]


def test_t_invest_mapping_then_quote_preview_happy_path(tmp_path: Path) -> None:
    database = create_database(tmp_path / "mapping_preview_happy.db")
    Base.metadata.create_all(database.engine)
    identity = MarketIdentity(
        provider="t_invest",
        provider_instrument_id=T_INVEST_UID,
        provider_venue_id=None,
        isin="RU0009029540",
    )
    quote = QuoteSuccess(
        identity=identity,
        instrument_kind=InstrumentType.STOCK,
        raw_price="15.00",
        raw_price_basis=RawPriceBasis.CASH_PER_UNIT,
        proposed_price_kopecks=1500,
        price_date=date(2026, 8, 13),
        quote_kind=QuoteKind.LAST,
        fetched_at_utc=datetime(2026, 8, 13, 12, 0, tzinfo=UTC),
        freshness_status=QuoteStatus.OK,
    )
    provider = MappingThenPreviewProvider(identity, quote)
    application = create_app(database, market_data_provider=provider)
    application.state.quote_preview_clock = lambda: date(2026, 8, 13)
    try:
        with TestClient(application) as client:
            month = client.post(
                "/api/months",
                json={"year": 2026, "month": 8, "snapshot_date": "2026-08-31"},
            )
            assert month.status_code == 201
            account = client.post(
                "/api/accounts",
                json={"name": "Synthetic Broker", "account_type": "brokerage"},
            )
            assert account.status_code == 201
            created = _create_instrument(client)
            discovered = client.post(
                f"/api/instruments/{created['id']}/market-mapping/discover",
                json={"provider": "t_invest"},
            )
            assert discovered.status_code == 200
            assert discovered.json()["status"] == "ok"
            assert discovered.json()["candidates"][0]["isin"] == "RU0009029540"
            assert client.get(f"/api/instruments/{created['id']}/market-mapping").json()[
                "state"
            ] == ("unmapped")

            saved = client.put(
                f"/api/instruments/{created['id']}/market-mapping",
                params={"verify": "true"},
                json={**T_INVEST_PAYLOAD, "isin": "RU0009029540"},
            )
            assert saved.status_code == 200
            assert saved.json()["state"] == "mapped"
            assert saved.json()["identity"]["provider"] == "t_invest"
            assert saved.json()["identity"]["provider_instrument_id"] == T_INVEST_UID

            position = client.post(
                "/api/positions",
                json={
                    "reporting_month_id": month.json()["id"],
                    "account_id": account.json()["id"],
                    "instrument_id": created["id"],
                    "quantity": "1",
                    "average_cost_per_unit": {"amount": "100.00", "currency": "RUB"},
                    "market_price_per_unit": {"amount": "10.00", "currency": "RUB"},
                    "price_date": "2026-08-01",
                    "price_source": "manual",
                },
            )
            assert position.status_code == 201
            preview = client.post(f"/api/months/{month.json()['id']}/quote-preview")
            assert preview.status_code == 200
            rows = preview.json()["rows"]
            assert len(rows) == 1
            assert rows[0]["status"] == "ok"
            assert rows[0]["identity"]["provider"] == "t_invest"
            assert rows[0]["identity"]["provider_instrument_id"] == T_INVEST_UID
            assert rows[0]["current_market_price_per_unit"] == {
                "amount": "10.00",
                "currency": "RUB",
            }
            assert rows[0]["proposed_market_price_per_unit"] == {
                "amount": "15.00",
                "currency": "RUB",
            }
            listed = client.get(f"/api/positions?month_id={month.json()['id']}")
            assert listed.status_code == 200
            frozen = listed.json()[0]
            assert frozen["market_price_per_unit"] == {"amount": "10.00", "currency": "RUB"}
            assert frozen["price_source"] == "manual"
            assert provider.discover_calls >= 2
            assert provider.fetch_calls == 1
    finally:
        database.engine.dispose()
