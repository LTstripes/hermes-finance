from enum import StrEnum


class InvestmentCashFlowType(StrEnum):
    INTEREST = "interest"
    COUPON = "coupon"
    DIVIDEND = "dividend"
    REDEMPTION = "redemption"
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    COMMISSION = "commission"
    TAX = "tax"
    REALIZED_PROFIT = "realized_profit"
    REALIZED_LOSS = "realized_loss"
    OTHER = "other"

    @property
    def counts_as_passive_income(self) -> bool:
        return self in {
            self.INTEREST,
            self.COUPON,
            self.DIVIDEND,
            self.OTHER,
        }


class ExpectedCashFlowType(StrEnum):
    COUPON = "coupon"
    DIVIDEND = "dividend"
    INTEREST = "interest"
    REDEMPTION = "redemption"
    OTHER = "other"

    @property
    def counts_as_passive_income(self) -> bool:
        return self is not self.REDEMPTION
