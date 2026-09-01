"""Framework-independent primitives for the monthly close workflow contract.

This module deliberately contains no persistence, API, or provider concerns.  The
workflow is a read model: its state is derived afresh from current domain facts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class GuidedCloseStepId(StrEnum):
    MONTH_SETUP = "month_setup"
    ALFA_BASELINE = "alfa_baseline"
    MARKET_QUOTES = "market_quotes"
    ACTUAL_PAYOUTS = "actual_payouts"
    FUTURE_PAYOUTS = "future_payouts"
    BROKER_RECONCILIATION = "broker_reconciliation"
    READINESS = "readiness"
    FINAL_REVIEW_CLOSE = "final_review_close"
    NEXT_MONTH_OUTLOOK = "next_month_outlook"


class GuidedCloseStepState(StrEnum):
    NOT_STARTED = "not_started"
    READY = "ready"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    WARNING = "warning"
    BLOCKED = "blocked"


class GuidedCloseApplicability(StrEnum):
    MANDATORY = "mandatory"
    CONDITIONAL = "conditional"
    NOT_APPLICABLE = "not_applicable"


class GuidedCloseGate(StrEnum):
    MUST_RESOLVE = "must_resolve"
    OWNER_DECISION = "owner_decision"
    ADVISORY = "advisory"
    NONE = "none"


class GuidedCloseActionId(StrEnum):
    OPEN_MONTH = "open_month"
    SET_SNAPSHOT_DATE = "set_snapshot_date"
    OPEN_ALFA_PREVIEW = "open_alfa_preview"
    OPEN_QUOTE_PREVIEW = "open_quote_preview"
    CHOOSE_STATEMENT_FILE = "choose_statement_file"
    OPEN_PAYOUT_BATCH_PREVIEW = "open_payout_batch_preview"
    OPEN_RECONCILIATION_PREVIEW = "open_reconciliation_preview"
    OPEN_FRESHNESS = "open_freshness"
    OPEN_FINAL_REVIEW = "open_final_review"
    CONFIRM_CLOSE = "confirm_close"
    OPEN_CASH_FLOW_LADDER = "open_cash_flow_ladder"
    CLONE_NEXT_MONTH = "clone_next_month"


class GuidedCloseReasonCode(StrEnum):
    """Stable workflow-owned reasons; authority-owned codes remain pass-through strings."""

    SNAPSHOT_DATE_REQUIRED = "snapshot_date_required"
    MONTH_CLOSED_READ_ONLY = "month_closed_read_only"
    BASELINE_NOT_APPLIED = "baseline_not_applied"
    BASELINE_SELECTED_ROWS_PRESENT = "baseline_selected_rows_present"
    BASELINE_POSITION_MISSING = "baseline_position_missing"
    BASELINE_QUANTITY_CHANGED = "baseline_quantity_changed"
    BASELINE_DATE_CHANGED = "baseline_date_changed"
    BASELINE_COVERAGE_NOT_PERSISTED = "baseline_coverage_not_persisted"
    NO_QUOTE_ELIGIBLE_POSITIONS = "no_quote_eligible_positions"
    QUOTE_MAPPING_MISSING = "quote_mapping_missing"
    QUOTE_COVERAGE_PARTIAL = "quote_coverage_partial"
    QUOTE_STALE = "quote_stale"
    QUOTE_UNAVAILABLE = "quote_unavailable"
    QUOTE_MANUAL_OVERRIDE = "quote_manual_override"
    QUOTE_NOT_APPLIED = "quote_not_applied"
    STATEMENT_NOT_IMPORTED = "statement_not_imported"
    STATEMENT_ACTIVE_ROWS_PRESENT = "statement_active_rows_present"
    STATEMENT_ROWS_RETRACTED = "statement_rows_retracted"
    STATEMENT_LINKED_FLOW_CHANGED = "statement_linked_flow_changed"
    STATEMENT_ZERO_RESULT_NOT_PERSISTED = "statement_zero_result_not_persisted"
    NO_PAYOUT_ELIGIBLE_POSITIONS = "no_payout_eligible_positions"
    PROVIDER_PAYOUT_ACTIVE_ROWS_PRESENT = "provider_payout_active_rows_present"
    PAYOUT_POSITION_MISSING = "payout_position_missing"
    PAYOUT_QUANTITY_CHANGED = "payout_quantity_changed"
    PAYOUT_MAPPING_CHANGED = "payout_mapping_changed"
    PAYOUT_RECONCILIATION_CHANGED = "payout_reconciliation_changed"
    PAYOUT_ZERO_RESULT_NOT_PERSISTED = "payout_zero_result_not_persisted"
    RECONCILIATION_NOT_RUN = "reconciliation_not_run"
    RECONCILIATION_TRANSIENT_MATCH = "reconciliation_transient_match"
    RECONCILIATION_DIFFERENCES = "reconciliation_differences"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    COMPATIBILITY_UNKNOWN = "compatibility_unknown"
    COMPATIBILITY_UNSUPPORTED = "compatibility_unsupported"
    OUTLOOK_NOT_AVAILABLE_UNTIL_CLOSED = "outlook_not_available_until_closed"
    NO_KNOWN_DATED_EVENTS = "no_known_dated_events"
    OUTLOOK_SECTION_UNAVAILABLE = "outlook_section_unavailable"
    FINAL_REVIEW_NOT_IN_CORE = "final_review_not_in_core"


class GuidedCloseActionTarget(StrEnum):
    OPEN_PANEL = "open_panel"
    INTERNAL_ROUTE = "internal_route"
    CONFIRM_CLOSE = "confirm_close"


class GuidedCloseCompletionBasis(StrEnum):
    DOMAIN_FACT = "domain_fact"
    BACKEND_READ = "backend_read"
    MONTH_CLOSED = "month_closed"


class GuidedCloseEvidenceScope(StrEnum):
    FULL_CURRENT_LOCAL_SCOPE = "full_current_local_scope"
    SELECTED_ROWS_ONLY = "selected_rows_only"
    TRANSIENT_SNAPSHOT = "transient_snapshot"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class GuidedCloseAction:
    id: GuidedCloseActionId
    label: str
    target: GuidedCloseActionTarget


@dataclass(frozen=True, slots=True)
class GuidedCloseStale:
    is_stale: bool = False
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GuidedCloseStep:
    id: GuidedCloseStepId
    order: int
    title: str
    state: GuidedCloseStepState
    applicability: GuidedCloseApplicability
    gate: GuidedCloseGate
    affects_close: bool
    why: str
    reason_codes: tuple[str, ...] = ()
    primary_action: GuidedCloseAction | None = None
    secondary_actions: tuple[GuidedCloseAction, ...] = ()
    completion_basis: GuidedCloseCompletionBasis | None = None
    evidence_scope: GuidedCloseEvidenceScope = GuidedCloseEvidenceScope.NONE
    evidence_version: str | None = None
    evidence_summary: dict[str, object] = field(default_factory=dict)
    stale: GuidedCloseStale = field(default_factory=GuidedCloseStale)
    diagnostics: dict[str, object] = field(default_factory=dict)


def derive_step_state(
    *,
    hard_blocked: bool = False,
    not_applicable: bool = False,
    stale_or_partial: bool = False,
    completed: bool = False,
    ready: bool = False,
) -> GuidedCloseStepState:
    """Apply the normative state precedence for one workflow step."""

    if hard_blocked:
        return GuidedCloseStepState.BLOCKED
    if not_applicable:
        return GuidedCloseStepState.SKIPPED
    if stale_or_partial:
        return GuidedCloseStepState.WARNING
    if completed:
        return GuidedCloseStepState.COMPLETED
    if ready:
        return GuidedCloseStepState.READY
    return GuidedCloseStepState.NOT_STARTED


def recommended_step_id(steps: tuple[GuidedCloseStep, ...]) -> GuidedCloseStepId | None:
    """Return the one earliest actionable recommendation, if one exists."""

    unresolved = {
        GuidedCloseStepState.BLOCKED,
        GuidedCloseStepState.WARNING,
        GuidedCloseStepState.READY,
        GuidedCloseStepState.NOT_STARTED,
    }
    for step in steps:
        if step.affects_close and step.state is GuidedCloseStepState.BLOCKED:
            return step.id
    for step in steps:
        if step.gate is GuidedCloseGate.MUST_RESOLVE and step.state in unresolved:
            return step.id
    for step in steps:
        if (
            step.state in {GuidedCloseStepState.WARNING, GuidedCloseStepState.READY}
            and step.primary_action is not None
        ):
            return step.id
    return None
