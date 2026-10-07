"""H2-A2 review intent; inventory and financial facts are server-owned."""

from datetime import date
from typing import Literal

from pydantic import Field, model_validator

from hermes_finance.domain.historical_endpoints import Digest, Label, StrictModel


class SourceCashClaims(StrictModel):
    reference: Label
    review_context_digest: Digest
    all_report_channels_disclosed: bool = Field(default=False, strict=True)
    full_interval_no_omitted_crossing: bool = Field(default=False, strict=True)
    every_owner_crossing_enumerated: bool = Field(default=False, strict=True)
    source_and_legacy_conflicts_resolved: bool = Field(default=False, strict=True)
    zero_owner_cash_crossings: bool = Field(default=False, strict=True)


CLAIMS = (
    "all_report_channels_disclosed",
    "full_interval_no_omitted_crossing",
    "every_owner_crossing_enumerated",
    "source_and_legacy_conflicts_resolved",
)


class SourceCashIntent(StrictModel):
    operation: Literal["accept", "reaffirm", "revoke"] = "accept"
    account_id: int | None = Field(default=None, gt=0, strict=True)
    opening_date: date | None = None
    closing_date: date | None = None
    coverage_id: int | None = Field(default=None, gt=0, strict=True)
    expected_revision: int | None = Field(default=None, ge=0, strict=True)
    claims: SourceCashClaims | None = None
    reason_code: Literal["attestation_withdrawn", "evidence_disputed"] | None = None

    @model_validator(mode="after")
    def shape(self):
        if self.operation == "revoke":
            if (
                self.coverage_id is None
                or self.expected_revision is None
                or self.reason_code is None
                or self.account_id is not None
                or self.opening_date is not None
                or self.closing_date is not None
                or self.claims is not None
            ):
                raise ValueError("revoke_shape_invalid")
        else:
            if (
                self.account_id is None
                or self.opening_date is None
                or self.closing_date is None
                or self.opening_date >= self.closing_date
                or self.reason_code is not None
            ):
                raise ValueError("acceptance_shape_invalid")
            if (self.coverage_id is None) != (self.expected_revision is None):
                raise ValueError("target_revision_required")
            if self.operation == "reaffirm" and self.coverage_id is None:
                raise ValueError("existing_target_required")
        return self


class SourceCashApplyRequest(SourceCashIntent):
    request_id: Label
    confirmation_digest: Digest
