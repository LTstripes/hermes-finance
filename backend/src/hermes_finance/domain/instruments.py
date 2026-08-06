from enum import StrEnum


class InstrumentType(StrEnum):
    STOCK = "stock"
    BOND = "bond"
    FUND = "fund"
    CURRENCY = "currency"
    GOLD = "gold"
    OTHER = "other"
