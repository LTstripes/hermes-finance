"""Cash-boundary completeness evidence for exact performance."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class CashBoundaryCoverageState(StrEnum):
    """Whether owner cash crossings are affirmatively accounted for."""

    COMPLETE = "complete"
    UNKNOWN = "unknown"


# Some callers use the shorter status vocabulary used by availability payloads.
CashBoundaryCoverageStatus = CashBoundaryCoverageState


@dataclass(frozen=True, slots=True)
class CashBoundaryCoverageEvidence:
    """Sanitized persisted evidence for one account and covered interval."""

    id: int
    account_id: int
    covered_from: date
    covered_to: date
    state: CashBoundaryCoverageState
    provenance_kind: str
    provenance_reference: str | None


@dataclass(frozen=True, slots=True)
class CashBoundaryCoverage:
    """Coverage assessment for the accounts required by one interval."""

    status: str
    account_ids: tuple[int, ...]
    evidence: tuple[CashBoundaryCoverageEvidence, ...] = ()
    missing_or_incomplete_account_ids: tuple[int, ...] = ()
    reason_codes: tuple[str, ...] = ()

    @property
    def is_complete(self) -> bool:
        return not self.reason_codes
