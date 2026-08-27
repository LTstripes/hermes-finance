"""Tests for the explicit provider capability contract (R07-T04)."""

from pathlib import Path

from fastapi.testclient import TestClient

from hermes_finance.database import create_database
from hermes_finance.main import create_app
from hermes_finance.market_data.capabilities import (
    MOEX_ISS_CAPABILITIES,
    T_INVEST_CAPABILITIES,
    ProviderCapabilityName,
    ProviderCapabilityStatus,
    all_provider_capabilities,
    provider_capabilities,
)
from hermes_finance.market_data.routing import DisabledMoexVerificationProvider
from hermes_finance.persistence import Base


def test_registered_profiles_make_production_and_verification_boundaries_explicit() -> None:
    profiles = {profile.provider: profile for profile in all_provider_capabilities()}

    assert set(profiles) == {"moex_iss", "t_invest"}
    t_invest = profiles["t_invest"]
    assert t_invest.supports(ProviderCapabilityName.INSTRUMENT_DISCOVERY)
    assert t_invest.supports(ProviderCapabilityName.CURRENT_QUOTES)
    assert t_invest.supports(ProviderCapabilityName.HISTORICAL_QUOTES)
    assert t_invest.supports(ProviderCapabilityName.PAYOUT_CALENDAR)
    assert not t_invest.supports(ProviderCapabilityName.POSITIONS)
    assert not t_invest.supports(ProviderCapabilityName.SNAPSHOTS)

    moex = profiles["moex_iss"]
    assert not moex.supports(ProviderCapabilityName.CURRENT_QUOTES)
    assert moex.supports(ProviderCapabilityName.CURRENT_QUOTES, production=False)
    assert (
        moex.capability(ProviderCapabilityName.CURRENT_QUOTES).status
        is ProviderCapabilityStatus.VERIFICATION_ONLY
    )


def test_provider_instances_expose_static_profiles_without_changing_routing() -> None:
    assert DisabledMoexVerificationProvider().capabilities is MOEX_ISS_CAPABILITIES
    assert provider_capabilities(" T_INVEST ") is T_INVEST_CAPABILITIES
    assert provider_capabilities("alfa_pro") is None


def test_capabilities_endpoint_is_static_and_does_not_need_database_or_network(
    tmp_path: Path,
) -> None:
    database = create_database(tmp_path / "capabilities.db")
    Base.metadata.create_all(database.engine)
    try:
        with TestClient(create_app(database)) as client:
            response = client.get("/api/market-data/providers/capabilities")

        assert response.status_code == 200
        profiles = {item["provider"]: item for item in response.json()}
        assert set(profiles) == {"moex_iss", "t_invest"}
        assert profiles["t_invest"]["supported_instrument_types"] == [
            "stock",
            "fund",
            "bond",
        ]
        t_invest_capabilities = {
            item["name"]: item for item in profiles["t_invest"]["capabilities"]
        }
        assert t_invest_capabilities["current_quotes"]["status"] == "production_enabled"
        assert t_invest_capabilities["positions"]["status"] == "unsupported"
        assert profiles["moex_iss"]["capabilities"][1]["status"] == "verification_only"
    finally:
        database.engine.dispose()
