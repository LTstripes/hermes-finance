"""H2-A1 accepts semantics only; financial facts always come from S1."""

from typing import Literal

from pydantic import Field, model_validator

from hermes_finance.domain.historical_endpoints import Digest, Label, StrictModel

SOURCE_CASH_PROVENANCE = "owner_attested_source_cash_history"
COMPATIBLE_FLOW_CONTRACT = "h2-a1-owner-rub-v2"


class MoneyOccurrence(StrictModel):
    import_id: int = Field(gt=0, strict=True)
    section: Literal["money"] = "money"
    ordinal: int = Field(ge=0, strict=True)


class OwnerCashClaims(StrictModel):
    provenance_kind: Literal["owner_attested_source_row"]
    reference: Label
    source_set_fingerprint: Digest
    review_context_digest: Digest
    direction: Literal["contribution", "withdrawal"]
    original_row_identifiable: bool = Field(default=False, strict=True)
    posted_cash_date_confirmed: bool = Field(default=False, strict=True)
    signed_cash_convention_confirmed: bool = Field(default=False, strict=True)
    owner_capital_crossing: bool = Field(default=False, strict=True)
    not_income_tax_promotion_or_internal_cash: bool = Field(default=False, strict=True)
    not_settlement_or_commission: bool = Field(default=False, strict=True)
    cash_not_in_kind: bool = Field(default=False, strict=True)
    not_tracked_account_transfer: bool = Field(default=False, strict=True)
    counterparty_outside_account_boundary: bool = Field(default=False, strict=True)
    complete_occurrence_set_is_one_event: bool = Field(default=False, strict=True)


CLAIMS = tuple(
    name for name, field in OwnerCashClaims.model_fields.items() if field.annotation is bool
)


class OwnerFlowIntent(StrictModel):
    evidence_version: Literal["h2-a1-owner-rub-v1", "h2-a1-owner-rub-v2"] = "h2-a1-owner-rub-v1"
    operation: Literal["accept", "corroborate", "reaffirm", "revoke"] = "accept"
    account_id: int | None = Field(default=None, gt=0, strict=True)
    seed: MoneyOccurrence | None = None
    flow_id: Label | None = None
    expected_revision: int | None = Field(default=None, gt=0, strict=True)
    claims: OwnerCashClaims | None = None
    reason_code: Literal["attestation_withdrawn", "evidence_disputed"] | None = None

    @model_validator(mode="after")
    def shape(self):
        if self.operation == "revoke":
            if (
                self.flow_id is None
                or self.expected_revision is None
                or self.reason_code is None
                or self.account_id is not None
                or self.seed is not None
                or self.claims is not None
            ):
                raise ValueError("revoke_shape_invalid")
        else:
            if self.account_id is None or self.seed is None or self.reason_code is not None:
                raise ValueError("acceptance_shape_invalid")
            if (self.flow_id is None) != (self.expected_revision is None):
                raise ValueError("target_revision_required")
            if self.operation != "accept" and self.flow_id is None:
                raise ValueError("existing_target_required")
        return self


class OwnerFlowApplyRequest(OwnerFlowIntent):
    request_id: Label
    confirmation_digest: Digest
