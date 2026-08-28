from enum import StrEnum


class ExternalFlowDirection(StrEnum):
    """Direction of an owner boundary movement for one tracked account."""

    CONTRIBUTION = "contribution"
    WITHDRAWAL = "withdrawal"


class ExternalFlowKind(StrEnum):
    """Explicit boundary-flow kind stored alongside its direction."""

    EXTERNAL_CONTRIBUTION = "external_contribution"
    EXTERNAL_WITHDRAWAL = "external_withdrawal"

    @property
    def direction(self) -> ExternalFlowDirection:
        if self is self.EXTERNAL_CONTRIBUTION:
            return ExternalFlowDirection.CONTRIBUTION
        return ExternalFlowDirection.WITHDRAWAL


class ExternalFlowScope(StrEnum):
    PORTFOLIO = "portfolio"
    ACCOUNT = "account"


class ExternalFlowScopeMembership(StrEnum):
    """Owner-asserted v1 membership evidence for a historical flow."""

    UNKNOWN = "unknown"
    STABLE_IN_SCOPE = "stable_in_scope"
    STABLE_OUT_OF_SCOPE = "stable_out_of_scope"


class ExternalFlowClassification(StrEnum):
    EXTERNAL_CONTRIBUTION = "external_contribution"
    EXTERNAL_WITHDRAWAL = "external_withdrawal"
    INTERNAL_TRANSFER = "internal_transfer"
    UNRESOLVED = "unresolved"
    NOT_AUTHORITATIVE = "not_authoritative"
    NOT_IN_SCOPE = "not_in_scope"


class ExternalTransferStatus(StrEnum):
    UNRESOLVED = "unresolved"
    RESOLVED = "resolved"


# Short aliases keep the vocabulary usable at both the boundary-flow and
# transfer-link level without introducing a second set of enum values.
BoundaryFlowDirection = ExternalFlowDirection
BoundaryFlowKind = ExternalFlowKind
TransferLinkStatus = ExternalTransferStatus
