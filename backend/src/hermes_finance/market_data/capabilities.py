"""Static provider capability profiles for routing and diagnostics.

Capability metadata is deliberately separate from provider resolution. Reading a
profile never constructs a client and never performs network I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from hermes_finance.domain import InstrumentType
from hermes_finance.market_data.dto import MOEX_ISS_PROVIDER, T_INVEST_PROVIDER


class ProviderCapabilityName(StrEnum):
    """Operations a provider family may expose to Hermes."""

    INSTRUMENT_DISCOVERY = "instrument_discovery"
    CURRENT_QUOTES = "current_quotes"
    HISTORICAL_QUOTES = "historical_quotes"
    PAYOUT_CALENDAR = "payout_calendar"
    POSITIONS = "positions"
    SNAPSHOTS = "snapshots"


class ProviderCapabilityStatus(StrEnum):
    """Whether a capability may be used in production or only for verification."""

    PRODUCTION_ENABLED = "production_enabled"
    VERIFICATION_ONLY = "verification_only"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class ProviderCapability:
    name: ProviderCapabilityName
    status: ProviderCapabilityStatus
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", ProviderCapabilityName(self.name))
        object.__setattr__(self, "status", ProviderCapabilityStatus(self.status))
        normalized = tuple(item.strip() for item in self.limitations if item.strip())
        object.__setattr__(self, "limitations", normalized)


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    """Capability profile for one provider family.

    ``payout_calendar`` describes the separate payout-provider adapter when one
    exists; it does not add payout methods to ``MarketDataProvider``. Broker
    positions and snapshots remain separate bounded contexts.
    """

    provider: str
    supported_instrument_types: tuple[InstrumentType, ...]
    capabilities: tuple[ProviderCapability, ...]
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        provider = self.provider.strip().lower()
        if not provider:
            raise ValueError("provider must not be empty")
        object.__setattr__(self, "provider", provider)
        object.__setattr__(
            self,
            "supported_instrument_types",
            tuple(InstrumentType(item) for item in self.supported_instrument_types),
        )
        names = tuple(item.name for item in self.capabilities)
        if len(names) != len(set(names)):
            raise ValueError("provider capabilities must not contain duplicate names")
        object.__setattr__(
            self, "limitations", tuple(item.strip() for item in self.limitations if item.strip())
        )

    def capability(self, name: ProviderCapabilityName | str) -> ProviderCapability:
        requested = ProviderCapabilityName(name)
        for capability in self.capabilities:
            if capability.name is requested:
                return capability
        raise KeyError(f"provider capability is not declared: {requested.value}")

    def supports(
        self,
        name: ProviderCapabilityName | str,
        *,
        production: bool = True,
    ) -> bool:
        status = self.capability(name).status
        if production:
            return status is ProviderCapabilityStatus.PRODUCTION_ENABLED
        return status in {
            ProviderCapabilityStatus.PRODUCTION_ENABLED,
            ProviderCapabilityStatus.VERIFICATION_ONLY,
        }


_COMMON_MARKET_LIMITATIONS = (
    "Reads are explicit owner-triggered actions; no background refresh is provided.",
)

T_INVEST_CAPABILITIES = ProviderCapabilities(
    provider=T_INVEST_PROVIDER,
    supported_instrument_types=(InstrumentType.STOCK, InstrumentType.FUND, InstrumentType.BOND),
    capabilities=(
        ProviderCapability(
            ProviderCapabilityName.INSTRUMENT_DISCOVERY,
            ProviderCapabilityStatus.PRODUCTION_ENABLED,
        ),
        ProviderCapability(
            ProviderCapabilityName.CURRENT_QUOTES,
            ProviderCapabilityStatus.PRODUCTION_ENABLED,
        ),
        ProviderCapability(
            ProviderCapabilityName.HISTORICAL_QUOTES,
            ProviderCapabilityStatus.PRODUCTION_ENABLED,
        ),
        ProviderCapability(
            ProviderCapabilityName.PAYOUT_CALENDAR,
            ProviderCapabilityStatus.PRODUCTION_ENABLED,
            ("Payout retrieval is a separate read-only adapter.",),
        ),
        ProviderCapability(
            ProviderCapabilityName.POSITIONS,
            ProviderCapabilityStatus.UNSUPPORTED,
            ("Market data does not import broker positions.",),
        ),
        ProviderCapability(
            ProviderCapabilityName.SNAPSHOTS,
            ProviderCapabilityStatus.UNSUPPORTED,
            ("Market data does not create or mutate local snapshots.",),
        ),
    ),
    limitations=_COMMON_MARKET_LIMITATIONS
    + ("Only exchange-listed RUB-compatible stock, fund and bond semantics are supported.",),
)

MOEX_ISS_CAPABILITIES = ProviderCapabilities(
    provider=MOEX_ISS_PROVIDER,
    supported_instrument_types=(InstrumentType.STOCK, InstrumentType.FUND, InstrumentType.BOND),
    capabilities=(
        ProviderCapability(
            ProviderCapabilityName.INSTRUMENT_DISCOVERY,
            ProviderCapabilityStatus.VERIFICATION_ONLY,
        ),
        ProviderCapability(
            ProviderCapabilityName.CURRENT_QUOTES,
            ProviderCapabilityStatus.VERIFICATION_ONLY,
        ),
        ProviderCapability(
            ProviderCapabilityName.HISTORICAL_QUOTES,
            ProviderCapabilityStatus.VERIFICATION_ONLY,
        ),
        ProviderCapability(
            ProviderCapabilityName.PAYOUT_CALENDAR,
            ProviderCapabilityStatus.UNSUPPORTED,
        ),
        ProviderCapability(
            ProviderCapabilityName.POSITIONS,
            ProviderCapabilityStatus.UNSUPPORTED,
        ),
        ProviderCapability(
            ProviderCapabilityName.SNAPSHOTS,
            ProviderCapabilityStatus.UNSUPPORTED,
        ),
    ),
    limitations=(
        "Direct MOEX ISS production use is disabled; this adapter is verification-only.",
        "Verification uses explicit calls and never enables production fallback.",
    ),
)

_PROVIDER_CAPABILITIES = {
    T_INVEST_PROVIDER: T_INVEST_CAPABILITIES,
    MOEX_ISS_PROVIDER: MOEX_ISS_CAPABILITIES,
}


def provider_capabilities(provider: str) -> ProviderCapabilities | None:
    """Return a static profile, or ``None`` for a provider not registered yet."""

    return _PROVIDER_CAPABILITIES.get(provider.strip().lower())


def all_provider_capabilities() -> tuple[ProviderCapabilities, ...]:
    """Return registered profiles in stable provider-id order."""

    return tuple(_PROVIDER_CAPABILITIES[name] for name in sorted(_PROVIDER_CAPABILITIES))
