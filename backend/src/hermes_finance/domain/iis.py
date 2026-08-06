from enum import StrEnum


class TaxBenefitStatus(StrEnum):
    PLANNED = "planned"
    SUBMITTED = "submitted"
    RECEIVED = "received"
    REJECTED = "rejected"

    @property
    def counts_as_received(self) -> bool:
        return self is TaxBenefitStatus.RECEIVED
