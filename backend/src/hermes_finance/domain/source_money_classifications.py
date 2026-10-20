"""Provisional upload-time money classification vocabulary."""

from typing import Literal

OPERATION_MAX_LENGTH = 256
NARRATIVE_MAX_LENGTH = 4096

MoneyClassification = Literal[
    "external_deposit",
    "external_withdrawal",
    "coupon",
    "dividend",
    "fee",
    "tax",
    "trade_settlement",
    "internal_transfer",
    "unknown",
]
