from enum import StrEnum


class InstrumentType(StrEnum):
    STOCK = "stock"
    BOND = "bond"
    FUND = "fund"
    CURRENCY = "currency"
    GOLD = "gold"
    OTHER = "other"


class MarketMappingState(StrEnum):
    UNMAPPED = "unmapped"
    MAPPED = "mapped"
    EXCLUDED = "excluded"
