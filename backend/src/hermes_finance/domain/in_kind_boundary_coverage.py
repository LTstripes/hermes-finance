"""Explicit in-kind boundary completeness and movement evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class InKindBoundaryCoverageState(StrEnum):
    """Whether all transferable non-cash movements are affirmatively known."""

    COMPLETE = "complete"
    UNKNOWN = "unknown"


InKindBoundaryCoverageStatus = InKindBoundaryCoverageState


class InKindMovementKind(StrEnum):
    """Explicit movement markers; none carries a synthesized cash amount."""

    EXTERNAL_IN = "external_in"
    EXTERNAL_OUT = "external_out"
    INTERNAL_TRANSFER = "internal_transfer"


@dataclass(frozen=True, slots=True)
class InKindBoundaryCoverageEvidence:
    """Sanitized persisted evidence for one account and covered interval."""

    id: int
    account_id: int
    covered_from: date
    covered_to: date
    state: InKindBoundaryCoverageState
    provenance_kind: str
    provenance_reference: str | None


@dataclass(frozen=True, slots=True)
class InKindMovementEvidence:
    """A known non-cash movement marker with no valuation or cash amount."""

    id: int
    reporting_month_id: int
    event_date: date
    source_account_id: int | None
    destination_account_id: int | None
    movement_kind: InKindMovementKind
    instrument_id: int | None
    quantity: str | None
    provenance_kind: str
    provenance_reference: str | None


@dataclass(frozen=True, slots=True)
class InKindBoundaryCoverage:
    """Coverage assessment for accounts required by one performance interval."""

    status: str
    account_ids: tuple[int, ...]
    evidence: tuple[InKindBoundaryCoverageEvidence, ...] = ()
    missing_or_incomplete_account_ids: tuple[int, ...] = ()
    known_movements: tuple[InKindMovementEvidence, ...] = ()
    reason_codes: tuple[str, ...] = ()

    @property
    def is_complete(self) -> bool:
        return not self.reason_codes
