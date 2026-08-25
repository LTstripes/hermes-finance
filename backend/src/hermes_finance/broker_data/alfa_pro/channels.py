"""Production Alfa PRO snapshot allowlist. Narrower than the R06-01 probe.

Official API: Alfa Investments PRO WebSocket API v2.1
(https://alfadt.servicecdn.ru/alfadt/ad5/Alfa-Investments-Pro-API.pdf).
Historical operation entities and every trading/mutation channel are absent.
"""

from __future__ import annotations

from typing import Final

API_DOC_VERSION: Final = "2.1"
DEFAULT_ENDPOINT: Final = "ws://127.0.0.1:3366/router/"
ORDER_CHANNEL_PREFIX: Final = "#Order."

ALLOWED_ROUTER_COMMANDS: Final = frozenset({"listen", "unlisten", "request"})
ALLOWED_REQUEST_CHANNELS: Final = frozenset({"#Data.Query"})

ALLOWED_ENTITY_TYPES: Final = frozenset(
    {
        "ClientAccountEntity",
        "ClientSubAccountEntity",
        "SubAccountRazdelEntity",
        "ClientPositionEntity",
        "ClientBalanceEntity",
        "AssetInfoEntity",
    }
)

REQUIRED_SNAPSHOT_ENTITIES: Final = (
    "ClientAccountEntity",
    "ClientSubAccountEntity",
    "SubAccountRazdelEntity",
    "ClientPositionEntity",
    "ClientBalanceEntity",
)

ALLOWED_BUS_CHANNELS: Final = frozenset(
    {"#ConnectionState.Bus", *(f"#Data.Bus.{name}" for name in ALLOWED_ENTITY_TYPES)}
)

ENTITY_PRIMARY_KEY: Final = {
    "ClientAccountEntity": "IdAccount",
    "ClientSubAccountEntity": "IdSubAccount",
    "SubAccountRazdelEntity": "IdRazdel",
    "ClientPositionEntity": "IdPosition",
    "ClientBalanceEntity": "DataId",
    "AssetInfoEntity": "IdObject",
}


class ForbiddenAlfaChannel(RuntimeError):
    """Raised when a trading/order or otherwise non-allowlisted channel is requested."""


def is_order_channel(channel: str) -> bool:
    return channel.casefold().startswith(ORDER_CHANNEL_PREFIX.casefold())


def bus_channel_for_entity(entity_type: str) -> str:
    if entity_type not in ALLOWED_ENTITY_TYPES:
        raise ForbiddenAlfaChannel(f"refusing unlisted Alfa entity type: {entity_type}")
    return f"#Data.Bus.{entity_type}"


def assert_router_send_allowed(command: str, channel: str) -> None:
    """Hard-fail trading channels first, then require an explicit allowlist hit."""

    if is_order_channel(channel):
        raise ForbiddenAlfaChannel("refusing forbidden Alfa trading channel")
    if command not in ALLOWED_ROUTER_COMMANDS:
        raise ForbiddenAlfaChannel(f"refusing unlisted Alfa router command: {command}")
    if command in {"listen", "unlisten"} and channel not in ALLOWED_BUS_CHANNELS:
        raise ForbiddenAlfaChannel(f"refusing unlisted Alfa bus channel: {channel}")
    if command == "request" and channel not in ALLOWED_REQUEST_CHANNELS:
        raise ForbiddenAlfaChannel(f"refusing unlisted Alfa request channel: {channel}")
