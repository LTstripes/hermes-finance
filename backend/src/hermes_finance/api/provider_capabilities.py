"""Static market-provider capability diagnostics."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from hermes_finance.market_data.capabilities import (
    ProviderCapabilities,
    ProviderCapabilityStatus,
    all_provider_capabilities,
)

router = APIRouter(prefix="/api/market-data", tags=["market-data"])


class ProviderCapabilityOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    status: ProviderCapabilityStatus
    limitations: list[str]


class ProviderCapabilitiesOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    supported_instrument_types: list[str]
    capabilities: list[ProviderCapabilityOut]
    limitations: list[str]


def _response(profile: ProviderCapabilities) -> ProviderCapabilitiesOut:
    return ProviderCapabilitiesOut(
        provider=profile.provider,
        supported_instrument_types=[item.value for item in profile.supported_instrument_types],
        capabilities=[
            ProviderCapabilityOut(
                name=item.name.value,
                status=item.status,
                limitations=list(item.limitations),
            )
            for item in profile.capabilities
        ],
        limitations=list(profile.limitations),
    )


@router.get(
    "/providers/capabilities",
    response_model=list[ProviderCapabilitiesOut],
)
def provider_capabilities_endpoint() -> list[ProviderCapabilitiesOut]:
    """Describe routing support without constructing a provider or doing I/O."""

    return [_response(profile) for profile in all_provider_capabilities()]
