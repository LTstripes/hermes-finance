"""Source-intake-backed provisional account-period estimate; never actual return.

This is a separate, ephemeral scenario over broker-reported native EOD totals.
It is not S3, not Close, not exact XIRR/TWRR and not a financial receipt.  The
unchanged Decimal period-MWR kernel is reused; no new solver exists here.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, DecimalException, localcontext
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from hermes_finance.domain.xirr import XirrCashFlow, calculate_xirr
from hermes_finance.statement_import.mybroker import digest

METHOD = "broker_source_provisional_mwr_period_v1"
VERSION = "source_intake_provisional_v2"
CONTEXT_KIND = "broker_source_provisional_context_v1"
RESULT_KIND = "broker_source_provisional_result_v1"
MAX_CANDIDATES = 16

Choice = Literal[
    "native_totals_continuously",
    "use_displayed_schedule",
    "include_as_account_inflow",
    "exclude_from_external_schedule",
    "no_other_account_crossings",
    "no_additional_flow_or_adjustment",
    "native_totals_include_REPO_as_reported",
    "unparsed_rows_reflected_in_native_totals",
]
Slot = Literal[
    "native_basis",
    "schedule",
    "candidate",
    "remaining_crossings",
    "trades_money_basis",
    "repo_basis",
    "unparsed_basis",
]
Kopecks = Annotated[str, Field(pattern=r"^(0|-?[1-9][0-9]*)$")]
Fingerprint = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class ProvisionalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ProvisionalPosition(ProvisionalModel):
    source_reference: str
    isin: str
    ordinal: int
    beginning_quantity: str | None
    ending_quantity: str | None
    beginning_value: str | None
    ending_value: str | None
    beginning_value_kopecks: Kopecks | None
    ending_value_kopecks: Kopecks | None


class ProvisionalCash(ProvisionalModel):
    source_reference: str
    beginning_amount: str | None
    ending_amount: str | None
    beginning_kopecks: Kopecks | None
    ending_kopecks: Kopecks | None


class ProvisionalObserved(ProvisionalModel):
    """Observed native totals only; a value change is not a performance label."""

    positions_value_opening_kopecks: Kopecks | None
    cash_opening_kopecks: Kopecks | None
    total_opening_kopecks: Kopecks | None
    positions_value_closing_kopecks: Kopecks | None
    cash_closing_kopecks: Kopecks | None
    total_closing_kopecks: Kopecks | None
    reported_value_change_kopecks: Kopecks | None
    positions: tuple[ProvisionalPosition, ...]
    cash: ProvisionalCash | None


class ProvisionalFlow(ProvisionalModel):
    source_reference: str
    event_date: date
    signed_amount_kopecks: Kopecks
    source_amount: str
    provenance: Literal["assumed_native_incoming"] = "assumed_native_incoming"


class ProvisionalKnownPayout(ProvisionalModel):
    """Recognized coupon/NKD observation shown separately; never added to flows."""

    source_reference: str
    event_date: date
    kind: Literal["coupon_paid_candidate", "trade_paid_nkd_candidate"]
    source_amount: str
    amount_kopecks: Kopecks | None


class ProvisionalRequirement(ProvisionalModel):
    requirement_id: str
    subject: str
    slot: Slot
    source_references: tuple[str, ...]
    choices: tuple[Choice, ...]


class ProvisionalChoice(ProvisionalModel):
    requirement_id: str
    source_references: tuple[str, ...]
    choice: Choice


class ProvisionalAssumptions(ProvisionalModel):
    version: Literal["source_intake_provisional_v2"] = VERSION
    schedule_mode: Literal["explicit_empty", "dated"] | None = None
    selections: tuple[ProvisionalChoice, ...] = ()


class ProvisionalJournal(ProvisionalModel):
    intake_id: int
    head_seq: int
    manifest_digest: Fingerprint
    document_sha256: Fingerprint
    parser: str
    binding: Literal["hermes_account", "unbound"]
    finance_link_present: bool
    exceptions: tuple[str, ...]


class ProvisionalContext(ProvisionalModel):
    kind: Literal["broker_source_provisional_context_v1"] = CONTEXT_KIND
    method: Literal["broker_source_provisional_mwr_period_v1"] = METHOD
    scope: Literal["account", "native_source"] = "account"
    authority: Literal["provisional"] = "provisional"
    financial_authority: Literal["none"] = "none"
    currency: Literal["RUB"] = "RUB"
    annualized: Literal[False] = False
    intake_id: int
    account_id: int | None
    native_source_account: str | None
    t0: date
    t1: date
    journal: ProvisionalJournal
    observed: ProvisionalObserved
    candidates: tuple[ProvisionalFlow, ...]
    known_payouts: tuple[ProvisionalKnownPayout, ...]
    required_assumptions: tuple[ProvisionalRequirement, ...]
    hard_blockers: tuple[str, ...]
    limitations: tuple[str, ...]
    context_fingerprint: Fingerprint


class ProvisionalAlternative(ProvisionalModel):
    label: str
    scenario_result_kopecks: Kopecks
    scenario_rate_fraction: str
    included_candidate_references: tuple[str, ...]


class ProvisionalResult(ProvisionalModel):
    kind: Literal["broker_source_provisional_result_v1"] = RESULT_KIND
    method: Literal["broker_source_provisional_mwr_period_v1"] = METHOD
    scope: Literal["account", "native_source"] = "account"
    authority: Literal["provisional"] = "provisional"
    financial_authority: Literal["none"] = "none"
    currency: Literal["RUB"] = "RUB"
    annualized: Literal[False] = False
    status: Literal["provisional", "needs_assumptions", "blocked"]
    intake_id: int
    account_id: int | None
    native_source_account: str | None
    t0: date
    t1: date
    reported_value_change_kopecks: Kopecks | None
    scenario_result_kopecks: Kopecks | None
    scenario_rate_fraction: str | None
    assumed_schedule: tuple[ProvisionalFlow, ...]
    assumptions: ProvisionalAssumptions
    context: ProvisionalContext
    alternatives: tuple[ProvisionalAlternative, ...]
    limitations: tuple[str, ...]
    reason_codes: tuple[str, ...]
    context_fingerprint: Fingerprint
    assumption_fingerprint: Fingerprint
    result_fingerprint: Fingerprint


def _schedule(
    context: ProvisionalContext, assumptions: ProvisionalAssumptions
) -> list[ProvisionalFlow]:
    """Server-bound external schedule; a candidate is never selected implicitly."""
    supplied = {s.requirement_id: s for s in assumptions.selections}
    candidates = {c.source_reference: c for c in context.candidates}
    selected: list[ProvisionalFlow] = []
    for requirement in context.required_assumptions:
        if requirement.slot != "candidate":
            continue
        selection = supplied.get(requirement.requirement_id)
        if selection is None:
            continue
        if selection.choice == "include_as_account_inflow":
            flow = candidates.get(requirement.source_references[0])
            if flow is not None:
                selected.append(flow)
        elif selection.choice != "exclude_from_external_schedule":
            raise ValueError("provisional_candidate_choice_invalid")
    if len(candidates) != sum(r.slot == "candidate" for r in context.required_assumptions):
        raise ValueError("provisional_candidate_membership_invalid")
    return sorted(selected, key=lambda f: (f.event_date, f.source_reference))


def _numeric(context: ProvisionalContext, schedule: list[ProvisionalFlow], *, max_iterations: int):
    opening = context.observed.total_opening_kopecks
    closing = context.observed.total_closing_kopecks
    if (
        opening is None
        or closing is None
        or context.t0 >= context.t1
        or int(opening) <= 0
        or any(not context.t0 < f.event_date <= context.t1 for f in schedule)
    ):
        return None, None, ("provisional_numeric_basis_invalid",)
    solved = calculate_xirr(
        [
            XirrCashFlow(context.t0, -int(opening)),
            *(XirrCashFlow(f.event_date, -int(f.signed_amount_kopecks)) for f in schedule),
            XirrCashFlow(context.t1, int(closing)),
        ],
        max_iterations=max_iterations,
    )
    if solved.annualized_rate is None:
        return None, None, tuple(solved.reason_codes)
    try:
        with localcontext() as ctx:
            ctx.prec = 60
            period = (Decimal(1) + solved.annualized_rate) ** (
                Decimal((context.t1 - context.t0).days) / Decimal(365)
            ) - Decimal(1)
            if not period.is_finite():
                raise DecimalException
            rate = format(period, "f")
        rubles = str(
            int(closing) - int(opening) - sum(int(f.signed_amount_kopecks) for f in schedule)
        )
    except DecimalException:
        return None, None, ("not_computable_xirr_convergence_failed",)
    return rubles, rate, ()


def _flipped(
    context: ProvisionalContext,
    assumptions: ProvisionalAssumptions,
    *,
    max_iterations: int,
):
    """One source-grounded alternate only: the opposite interpretation of one candidate."""
    if len(context.candidates) != 1:
        return None
    requirement = next((r for r in context.required_assumptions if r.slot == "candidate"), None)
    if requirement is None:
        return None
    supplied = {s.requirement_id: s for s in assumptions.selections}
    current = supplied.get(requirement.requirement_id)
    if current is None:
        return None
    other = (
        "exclude_from_external_schedule"
        if current.choice == "include_as_account_inflow"
        else "include_as_account_inflow"
    )
    candidate = context.candidates[0]
    schedule = [candidate] if other == "include_as_account_inflow" else []
    try:
        rubles, rate, reasons = _numeric(context, schedule, max_iterations=max_iterations)
    except (DecimalException, ValueError):
        return None
    if reasons or rubles is None or rate is None:
        return None
    label = (
        "Альтернатива: кандидат исключён из внешних движений"
        if other == "exclude_from_external_schedule"
        else "Альтернатива: кандидат включён как внешнее поступление"
    )
    return ProvisionalAlternative(
        label=label,
        scenario_result_kopecks=rubles,
        scenario_rate_fraction=rate,
        included_candidate_references=tuple(f.source_reference for f in schedule),
    )


def evaluate_context(
    context: ProvisionalContext,
    assumptions: ProvisionalAssumptions,
    *,
    max_iterations: int = 256,
) -> ProvisionalResult:
    """Resolve only server-bound choices, then call the unchanged Decimal kernel."""
    reasons = set(context.hard_blockers)
    required = {r.requirement_id: r for r in context.required_assumptions}
    supplied: dict[str, ProvisionalChoice] = {}
    for selection in assumptions.selections:
        if selection.requirement_id in supplied:
            reasons.add("provisional_assumption_membership_invalid")
        supplied[selection.requirement_id] = selection
    if supplied.keys() - required.keys():
        reasons.add("provisional_assumption_membership_invalid")
    for key, selection in supplied.items():
        requirement = required.get(key)
        if requirement is not None and (
            selection.source_references != requirement.source_references
            or selection.choice not in requirement.choices
        ):
            reasons.add("provisional_assumption_membership_invalid")
    missing = required.keys() - supplied.keys()
    try:
        schedule = _schedule(context, assumptions)
    except ValueError as error:
        reasons.add(str(error))
        schedule = []
    if assumptions.schedule_mode is not None and (
        (assumptions.schedule_mode == "explicit_empty") != (not schedule)
    ):
        reasons.add("provisional_schedule_mode_invalid")
    ready = not missing and assumptions.schedule_mode is not None
    rubles = rate = None
    if ready and not reasons:
        rubles, rate, numeric_reasons = _numeric(context, schedule, max_iterations=max_iterations)
        reasons.update(numeric_reasons)
    status = (
        "blocked"
        if reasons
        else "provisional"
        if rubles is not None and rate is not None
        else "needs_assumptions"
    )
    if status != "provisional":
        rubles, rate = None, None
    alternatives: tuple[ProvisionalAlternative, ...] = ()
    if status == "provisional" and len(context.candidates) == 1:
        alternate = _flipped(context, assumptions, max_iterations=max_iterations)
        if alternate is not None:
            alternatives = (alternate,)
    payload = dict(
        status=status,
        scope=context.scope,
        intake_id=context.intake_id,
        account_id=context.account_id,
        native_source_account=context.native_source_account,
        t0=context.t0,
        t1=context.t1,
        reported_value_change_kopecks=context.observed.reported_value_change_kopecks,
        scenario_result_kopecks=rubles,
        scenario_rate_fraction=rate,
        assumed_schedule=tuple(schedule),
        assumptions=assumptions,
        context=context,
        alternatives=alternatives,
        limitations=context.limitations,
        reason_codes=tuple(sorted(reasons)),
        context_fingerprint=context.context_fingerprint,
        assumption_fingerprint=digest(assumptions.model_dump(mode="json")),
        result_fingerprint="0" * 64,
    )
    provisional = ProvisionalResult(**payload)
    return provisional.model_copy(
        update={
            "result_fingerprint": digest(
                provisional.model_dump(mode="json", exclude={"result_fingerprint"})
            )
        }
    )
