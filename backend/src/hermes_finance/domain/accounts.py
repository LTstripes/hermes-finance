from enum import StrEnum
from typing import Final


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


LINKED_DEBT_ACCOUNT_TYPES: Final[frozenset[str]] = frozenset(
    {
        AccountType.CASH.value,
        AccountType.DEPOSIT.value,
        AccountType.SAVINGS.value,
    }
)
