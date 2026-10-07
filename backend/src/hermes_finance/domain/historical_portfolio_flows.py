"""H2-B1 semantic attestations; no caller-supplied financial replacement."""

from datetime import date
from typing import Annotated, Literal

from pydantic import Field, model_validator

from hermes_finance.domain.historical_endpoints import Digest, Label, StrictModel


class RosterEntry(StrictModel):
    account_id: int = Field(gt=0, strict=True)
    disposition: Literal["tracked", "not_yet_opened", "no_longer_tracked", "not_investment_account"]
    reference: Label
    historical_disposition_confirmed: bool = Field(default=False, strict=True)


class DatedRosterClaims(StrictModel):
    provenance_kind: Literal["owner_attested_dated_roster"]
    reference: Label
    event_date: date
    catalogue_account_ids: list[Annotated[int, Field(gt=0, strict=True)]] = Field(max_length=10000)
    entries: list[RosterEntry] = Field(max_length=10000)
    review_context_digest: Digest
    complete_historical_roster: bool = Field(default=False, strict=True)
    no_omitted_historical_tracked_account: bool = Field(default=False, strict=True)
    all_account_identities_resolved: bool = Field(default=False, strict=True)
    included_accounts_rub_confirmed: bool = Field(default=False, strict=True)

    @model_validator(mode="after")
    def unique_accounts(self):
        if (
            any(type(a) is not int or a <= 0 for a in self.catalogue_account_ids)
            or len(set(self.catalogue_account_ids)) != len(self.catalogue_account_ids)
            or len({e.account_id for e in self.entries}) != len(self.entries)
        ):
            raise ValueError("roster_account_ids_invalid")
        return self


class OutsideUniverseClaims(StrictModel):
    provenance_kind: Literal["owner_attested_source_row"]
    reference: Label
    flow_id: Label
    flow_revision_id: int = Field(gt=0, strict=True)
    source_set_fingerprint: Digest
    review_context_digest: Digest
    original_movement_and_counterparty_identifiable: bool = Field(default=False, strict=True)
    counterparty_outside_entire_tracked_universe: bool = Field(default=False, strict=True)
    not_routed_as_tracked_account_transfer: bool = Field(default=False, strict=True)
    exact_owner_boundary_amount_confirmed: bool = Field(default=False, strict=True)
    no_inseparable_fee_tax_or_gross_net: bool = Field(default=False, strict=True)


ROSTER_CLAIMS = tuple(
    name for name, field in DatedRosterClaims.model_fields.items() if field.annotation is bool
)
OUTSIDE_CLAIMS = tuple(
    name for name, field in OutsideUniverseClaims.model_fields.items() if field.annotation is bool
)


class PortfolioFlowIntent(StrictModel):
    operation: Literal["accept", "reaffirm", "revoke"] = "accept"
    flow_id: Label
    expected_flow_revision: int = Field(gt=0, strict=True)
    # Zero explicitly means no portfolio revision exists yet.
    expected_portfolio_revision: int = Field(ge=0, strict=True)
    roster: DatedRosterClaims | None = None
    outside: OutsideUniverseClaims | None = None
    reason_code: Literal["attestation_withdrawn", "evidence_disputed"] | None = None

    @model_validator(mode="after")
    def shape(self):
        if self.operation == "revoke":
            if (
                self.expected_portfolio_revision == 0
                or self.reason_code is None
                or self.roster is not None
                or self.outside is not None
            ):
                raise ValueError("revoke_shape_invalid")
        elif self.reason_code is not None:
            raise ValueError("acceptance_shape_invalid")
        if self.operation == "reaffirm" and self.expected_portfolio_revision == 0:
            raise ValueError("existing_portfolio_revision_required")
        return self


class PortfolioFlowApplyRequest(PortfolioFlowIntent):
    request_id: Label
    confirmation_digest: Digest
