"""Explicit, original-proof-bound settlement decisions. No client money amounts."""

from typing import Literal

from pydantic import Field, model_validator

from hermes_finance.domain.historical_endpoints import Digest, Label, StrictModel


class SettlementClaims(StrictModel):
    reference: Label
    independent_event_reference: Label
    settlement_basis_reference: Label
    review_context_digest: Digest
    actual_is_exact_event: bool = Field(default=False, strict=True)
    full_event_settled_not_partial: bool = Field(default=False, strict=True)
    provider_identity_key: str | None = Field(default=None, min_length=1, max_length=128)
    exact_manual_row_is_same_event: bool = Field(default=False, strict=True)
    actual_and_forecast_are_distinct: bool = Field(default=False, strict=True)
    actual_independent_event_key: Label | None = None
    forecast_independent_event_key: Label | None = None


class PayoutIntent(StrictModel):
    contract_version: Literal["broker_payout_reconciliation_v1"]
    operation: Literal["link", "reaffirm", "retire", "distinct"]
    base_request_id: Label
    reporting_month_id: int = Field(gt=0, strict=True)
    account_id: int = Field(gt=0, strict=True)
    investment_cash_flow_id: int = Field(gt=0, strict=True)
    applied_payout_id: int | None = Field(default=None, gt=0, strict=True)
    expected_cash_flow_id: int | None = Field(default=None, gt=0, strict=True)
    predecessor_id: int | None = Field(default=None, gt=0, strict=True)
    claims: SettlementClaims | None = None

    @model_validator(mode="after")
    def shape(self):
        if self.operation == "retire" and self.predecessor_id is None:
            raise ValueError("retirement_requires_exact_relation")
        if (
            self.operation != "retire"
            and self.applied_payout_id is None
            and self.expected_cash_flow_id is None
        ):
            raise ValueError("settlement_requires_exact_forecast")
        if self.operation == "reaffirm" and self.predecessor_id is None:
            raise ValueError("reaffirmation_requires_exact_predecessor")
        if self.operation == "distinct" and self.predecessor_id is not None:
            raise ValueError("distinct_cannot_retire_a_link")
        return self


class PayoutConfirmation(PayoutIntent):
    request_id: Label
    confirmation_digest: Digest
