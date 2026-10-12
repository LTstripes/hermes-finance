"""Specific source-bound decisions; cash facts cannot be supplied by the client."""

from typing import Literal

from pydantic import Field, model_validator

from hermes_finance.domain.historical_endpoints import Digest, Label, StrictModel
from hermes_finance.domain.historical_owner_flows import MoneyOccurrence, OwnerFlowIntent


class CouponClaims(StrictModel):
    reference: Label
    review_context_digest: Digest
    actual_coupon_payment: bool = Field(default=False, strict=True)
    exact_row_instrument_link: bool = Field(default=False, strict=True)
    complete_occurrence_set_is_one_event: bool = Field(default=False, strict=True)
    existing_target_is_same_payment: bool = Field(default=False, strict=True)


class TradeCashClaims(StrictModel):
    reference: Label
    review_context_digest: Digest
    exact_row_settled_buy_link: bool = Field(default=False, strict=True)
    complete_occurrence_set_is_one_event: bool = Field(default=False, strict=True)
    nkd_separately_posted: bool = Field(default=False, strict=True)
    fee_separately_charged: bool = Field(default=False, strict=True)
    native_total_basis_independently_proved: bool = Field(default=False, strict=True)
    native_total_basis: Literal["includes_paid_nkd", "excludes_paid_nkd"]


class StockFeeClaims(StrictModel):
    proof_variant: Literal["stock_buy_separate_fee_v1"]
    reference: Label
    basis_reference: Label
    review_context_digest: Digest
    exact_row_settled_buy_link: bool = Field(default=False, strict=True)
    complete_occurrence_set_is_one_event: bool = Field(default=False, strict=True)
    fee_separately_charged: bool = Field(default=False, strict=True)
    native_total_basis_independently_proved: bool = Field(default=False, strict=True)
    native_total_basis: Literal["excludes_separate_fee"]


class MoneyDecision(StrictModel):
    role: Literal["coupon", "account_funding", "trade"]
    seed: MoneyOccurrence
    operation: Literal["accept", "corroborate", "reaffirm"] = "accept"
    instrument_id: int | None = Field(default=None, gt=0, strict=True)
    investment_cash_flow_id: int | None = Field(default=None, gt=0, strict=True)
    coupon_claims: CouponClaims | None = None
    owner_flow_intent: OwnerFlowIntent | None = None
    trade_id: int | None = Field(default=None, gt=0, strict=True)
    expected_trade_revision: int | None = Field(default=None, gt=0, strict=True)
    # Keep the legacy field and dump shape: old request hashes include nulls.
    trade_claims: TradeCashClaims | StockFeeClaims | None = None

    @model_validator(mode="after")
    def shape(self):
        if self.role != "trade" and any(
            value is not None
            for value in (self.trade_id, self.expected_trade_revision, self.trade_claims)
        ):
            raise ValueError("trade_fields_require_trade_role")
        if self.role == "trade" and any(
            value is not None
            for value in (
                self.instrument_id,
                self.investment_cash_flow_id,
                self.coupon_claims,
                self.owner_flow_intent,
            )
        ):
            raise ValueError("trade_cannot_be_payout_or_owner_flow")
        if self.role == "coupon" and self.owner_flow_intent is not None:
            raise ValueError("coupon_cannot_be_owner_flow")
        if self.role == "account_funding" and any(
            value is not None
            for value in (self.instrument_id, self.investment_cash_flow_id, self.coupon_claims)
        ):
            raise ValueError("owner_flow_cannot_be_coupon")
        return self


class MoneyIntent(StrictModel):
    contract_version: Literal["broker_money_v1"]
    base_request_id: Label
    reporting_month_id: int = Field(gt=0, strict=True)
    account_id: int = Field(gt=0, strict=True)
    money_decisions: list[MoneyDecision] = Field(default_factory=list, max_length=1000)


class MoneyConfirmation(MoneyIntent):
    request_id: Label
    confirmation_digest: Digest
