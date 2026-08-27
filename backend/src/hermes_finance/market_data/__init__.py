"""Isolated read-only market-data provider boundary (R04-02)."""

from hermes_finance.market_data.capabilities import (
    MOEX_ISS_CAPABILITIES,
    T_INVEST_CAPABILITIES,
    ProviderCapabilities,
    ProviderCapability,
    ProviderCapabilityName,
    ProviderCapabilityStatus,
    all_provider_capabilities,
    provider_capabilities,
)
from hermes_finance.market_data.dto import (
    MOEX_ISS_PROVIDER,
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
    RejectedCandidate,
    market_identity_key,
)
from hermes_finance.market_data.moex_identity import (
    InvalidMoexIdentityError,
    MoexIdentityParts,
    decode_moex_venue,
    encode_moex_venue,
    market_identity_from_moex,
    moex_parts_from_identity,
)
from hermes_finance.market_data.moex_iss import MoexIssClient
from hermes_finance.market_data.moscow import MOSCOW_TZ, moscow_calendar_date
from hermes_finance.market_data.protocol import MarketDataProvider
from hermes_finance.market_data.quotation import quotation_to_decimal
from hermes_finance.market_data.routing import (
    MOEX_PRODUCTION_DISABLED_MESSAGE,
    ProductionMarketDataProvider,
    production_market_data_provider,
)
from hermes_finance.market_data.t_invest import (
    TOKEN_UNAVAILABLE_MESSAGE,
    TInvestClient,
    normalize_t_invest_uid,
    t_invest_identity,
)

__all__ = [
    "MOEX_ISS_PROVIDER",
    "MOEX_ISS_CAPABILITIES",
    "MOEX_PRODUCTION_DISABLED_MESSAGE",
    "MOSCOW_TZ",
    "T_INVEST_PROVIDER",
    "T_INVEST_CAPABILITIES",
    "TOKEN_UNAVAILABLE_MESSAGE",
    "DiscoverCandidate",
    "DiscoverResult",
    "InvalidMoexIdentityError",
    "MarketDataProvider",
    "MarketIdentity",
    "ProviderCapabilities",
    "ProviderCapability",
    "ProviderCapabilityName",
    "ProviderCapabilityStatus",
    "MoexIdentityParts",
    "MoexIssClient",
    "ProductionMarketDataProvider",
    "QuoteFailure",
    "QuoteKind",
    "QuoteResult",
    "QuoteStatus",
    "QuoteSuccess",
    "RawPriceBasis",
    "RejectedCandidate",
    "TInvestClient",
    "all_provider_capabilities",
    "decode_moex_venue",
    "encode_moex_venue",
    "market_identity_from_moex",
    "market_identity_key",
    "moscow_calendar_date",
    "moex_parts_from_identity",
    "normalize_t_invest_uid",
    "production_market_data_provider",
    "provider_capabilities",
    "quotation_to_decimal",
    "t_invest_identity",
]
