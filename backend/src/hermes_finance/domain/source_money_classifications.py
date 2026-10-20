"""Provisional upload-time money classification vocabulary."""

from typing import Literal

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
