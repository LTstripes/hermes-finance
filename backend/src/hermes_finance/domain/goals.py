from enum import StrEnum


class GoalType(StrEnum):
    PASSIVE_INCOME = "passive_income"
    CAPITAL = "capital"
    EXPENSE_COVERAGE = "expense_coverage"
    MORTGAGE_COVERAGE = "mortgage_coverage"
    OTHER = "other"
