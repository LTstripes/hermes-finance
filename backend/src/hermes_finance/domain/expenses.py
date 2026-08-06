from enum import StrEnum


class ExpenseType(StrEnum):
    MANDATORY = "mandatory"
    COMFORTABLE = "comfortable"
    OTHER = "other"
