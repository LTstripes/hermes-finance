"""Intent names source keys and predecessors, never asserts source safety."""

from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from hermes_finance.domain.historical_endpoints import Digest, Label, StrictModel

CONTRACT = "mybroker-section-disposition-v1"
Section = Literal["4_Transfers", "5_UFSR"]


class SectionDecision(StrictModel):
    section: Section
    expected_predecessor: Label | None = None


class SectionIntent(StrictModel):
    contract_version: Literal["mybroker-section-disposition-v1"]
    base_request_id: Label
    import_id: int = Field(gt=0, strict=True)
    reporting_month_id: int = Field(gt=0, strict=True)
    account_id: int = Field(gt=0, strict=True)
    sections: list[SectionDecision] = Field(min_length=1, max_length=2)

    @model_validator(mode="after")
    def unique_sections(self):
        if len({s.section for s in self.sections}) != len(self.sections):
            raise ValueError("duplicate_section")
        return self


class SectionConfirmation(SectionIntent):
    request_id: Label
    confirmation_digest: Digest


class SectionMapping(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["account", "instrument"]
    identity: str
    hermes_id: int = Field(gt=0)
    mapping_id: int = Field(gt=0)


class SectionBindings(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    base_request_id: Label
    base_fingerprint: Digest
    base_confirmation: Digest
    base_projection: Digest
    source_digest: Digest
    provider: Literal["alfa_mybroker"]
    original_sha256: Digest
    source_parser: Literal["mybroker-s1-v2"]
    money_linkage_version: Literal["mybroker-money-linkage-v1"] | None
    filename_digest: Digest
    filename_account: str
    source_accounts: list[str]
    covered_from: str
    covered_to: str
    month_identity: list[int | str] = Field(min_length=6, max_length=6)
    mappings: list[SectionMapping]
    metadata_parser: Literal["mybroker-section-metadata-v1"]
