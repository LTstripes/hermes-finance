from enum import StrEnum


class AccountType(StrEnum):
    BROKERAGE = "brokerage"
    IIS = "iis"
    DEPOSIT = "deposit"
    SAVINGS = "savings"
    CASH = "cash"
    OTHER = "other"


class AccountStatus(StrEnum):
    ACTIVE = "active"
    FROZEN = "frozen"
    CLOSED = "closed"
    HIDDEN = "hidden"
