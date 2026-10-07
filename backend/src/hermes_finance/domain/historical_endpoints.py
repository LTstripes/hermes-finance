"""Strict endpoint-only Owner claims. No user-supplied financial components."""

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Label = Annotated[str, Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EndpointClaims(StrictModel):
    provenance_kind: Literal["owner_attestation"]
    reference: Label
    account_id: int = Field(gt=0)
    valuation_date: date
    source_side: Literal["ending"]
    source_set_fingerprint: Digest
    inventory_complete: bool = Field(default=False, strict=True)
    other_components_absent: bool = Field(default=False, strict=True)
    rub_cash_complete_and_reconciled: bool = Field(default=False, strict=True)
    # Affirmative exact-row fingerprints, not instrument class assignments.
    rub_stock_basis_confirmed: list[Digest] = Field(default_factory=list, max_length=10000)


class EndpointIntent(StrictModel):
    operation: Literal["accept", "reaffirm", "revoke"] = "accept"
    account_id: int = Field(gt=0, strict=True)
    valuation_date: date
    source_import_id: int | None = Field(default=None, gt=0, strict=True)
    source_side: Literal["ending", "beginning"] = "ending"
    claims: EndpointClaims | None = None
    expected_revision: int | None = Field(default=None, gt=0, strict=True)
    reason_code: Literal["owner_withdrawal", "evidence_disputed"] | None = None

    @model_validator(mode="after")
    def shape(self):
        if self.operation == "revoke":
            if (
                self.expected_revision is None
                or self.reason_code is None
                or self.source_import_id is not None
                or self.claims is not None
            ):
                raise ValueError("revoke_shape_invalid")
        elif self.source_import_id is None or self.reason_code is not None:
            raise ValueError("acceptance_shape_invalid")
        return self


class EndpointApplyRequest(EndpointIntent):
    request_id: Label
    confirmation_digest: Digest


class AcceptanceEnvelope(StrictModel):
    contract_version: Literal["h1-a-ending-rub-v1"]
    intent: EndpointIntent
    source: dict
    bindings: list[dict]
    positions: list[dict]
    rub_cash: dict | None
    claims: EndpointClaims
    membership: list[dict]
    endpoint_c1: None = None
    dependencies: dict
