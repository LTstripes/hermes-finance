"""Ephemeral hypothetical account model; never actual return or financial evidence."""

from datetime import date
from decimal import Decimal, DecimalException, localcontext
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from hermes_finance.domain.broker_statement_return import BrokerStatementReturn, StatementEndpoint
from hermes_finance.domain.xirr import XirrCashFlow, calculate_xirr
from hermes_finance.statement_import.mybroker import digest

METHOD = "broker_statement_what_if_mwr_period_v1"
VERSION = "account_native_what_if_v1"
Choice = Literal[
    "native_totals_continuously",
    "use_displayed_schedule",
    "include_as_account_inflow",
    "exclude_from_external_schedule",
    "no_other_account_crossings",
    "no_additional_flow_or_adjustment",
    "no_additional_channel_effect",
]


class WhatIfModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class AssumptionRequirement(WhatIfModel):
    requirement_id: str
    subject: str
    slot: Literal["native_basis", "schedule", "remaining_crossings", "money_basis", "residual"]
    source_references: tuple[str, ...]
    choices: tuple[Choice, ...]


class AssumptionChoice(WhatIfModel):
    requirement_id: str
    source_references: tuple[str, ...]
    choice: Choice


class StatementWhatIfAssumptions(WhatIfModel):
    version: Literal["account_native_what_if_v1"] = VERSION
    schedule_mode: Literal["explicit_empty", "dated"] | None = None
    selections: tuple[AssumptionChoice, ...] = ()


class WhatIfFlow(WhatIfModel):
    source_reference: str
    event_date: date
    signed_amount_kopecks: str = Field(pattern=r"^(0|-?[1-9][0-9]*)$")
    provenance: Literal["accepted_h2", "assumed_native_incoming"]


class WhatIfObserved(WhatIfModel):
    opening: StatementEndpoint | None
    closing: StatementEndpoint | None
    capital_delta_kopecks: str | None


class StatementWhatIfContext(WhatIfModel):
    kind: Literal["broker_statement_what_if_context_v1"] = "broker_statement_what_if_context_v1"
    method: Literal["broker_statement_what_if_mwr_period_v1"] = METHOD
    scope: Literal["account"] = "account"
    account_id: int
    request_id: str
    t0: date
    t1: date
    observed: WhatIfObserved
    actual_result: BrokerStatementReturn
    diagnostic_inventory: dict[str, Any]
    fixed_schedule: tuple[WhatIfFlow, ...]
    optional_candidate: WhatIfFlow | None
    required_assumptions: tuple[AssumptionRequirement, ...]
    hard_blockers: tuple[str, ...]
    limitations: tuple[str, ...]
    context_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class StatementWhatIfResult(WhatIfModel):
    kind: Literal["broker_statement_what_if_result_v1"] = "broker_statement_what_if_result_v1"
    method: Literal["broker_statement_what_if_mwr_period_v1"] = METHOD
    scope: Literal["account"] = "account"
    authority: Literal["hypothetical"] = "hypothetical"
    currency: Literal["RUB"] = "RUB"
    annualized: Literal[False] = False
    status: Literal["hypothetical", "needs_assumptions", "blocked"]
    account_id: int
    request_id: str
    t0: date
    t1: date
    scenario_result_kopecks: str | None
    scenario_rate_fraction: str | None
    assumed_schedule: tuple[WhatIfFlow, ...]
    assumptions: StatementWhatIfAssumptions
    context: StatementWhatIfContext
    actual_result: BrokerStatementReturn
    limitations: tuple[str, ...]
    reason_codes: tuple[str, ...]
    context_fingerprint: str
    assumption_fingerprint: str
    result_fingerprint: str


def evaluate_context(context, assumptions, *, max_iterations=256):
    """Resolve only server-bound finite choices, then call the unchanged Decimal kernel."""
    reasons = set(context.hard_blockers)
    required = {r.requirement_id: r for r in context.required_assumptions}
    supplied = {s.requirement_id: s for s in assumptions.selections}
    if len(supplied) != len(assumptions.selections) or supplied.keys() - required.keys():
        reasons.add("what_if_assumption_membership_invalid")
    for key, selection in supplied.items():
        requirement = required.get(key)
        if requirement and (
            selection.source_references != requirement.source_references
            or selection.choice not in requirement.choices
        ):
            reasons.add("what_if_assumption_membership_invalid")
    missing = required.keys() - supplied.keys()
    schedule = list(context.fixed_schedule)
    optional = context.optional_candidate
    if optional:
        selection = supplied.get("candidate")
        if selection and selection.choice == "include_as_account_inflow":
            schedule.append(optional)
    schedule.sort(key=lambda f: (f.event_date, f.source_reference))
    if assumptions.schedule_mode is not None:
        if (assumptions.schedule_mode == "explicit_empty") != (not schedule):
            reasons.add("what_if_schedule_mode_invalid")
    ready = not missing and assumptions.schedule_mode is not None
    rate, rubles = None, None
    if ready and not reasons:
        opening, closing = context.observed.opening, context.observed.closing
        if (
            opening is None
            or closing is None
            or opening.total_value_kopecks is None
            or closing.total_value_kopecks is None
            or context.t0 >= context.t1
            or any(not context.t0 < f.event_date <= context.t1 for f in schedule)
        ):
            reasons.add("what_if_numeric_basis_invalid")
        else:
            solved = calculate_xirr(
                [
                    XirrCashFlow(context.t0, -opening.total_value_kopecks),
                    *(XirrCashFlow(f.event_date, -int(f.signed_amount_kopecks)) for f in schedule),
                    XirrCashFlow(context.t1, closing.total_value_kopecks),
                ],
                max_iterations=max_iterations,
            )
            if solved.annualized_rate is None:
                reasons.update(solved.reason_codes)
            else:
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
                        closing.total_value_kopecks
                        - opening.total_value_kopecks
                        - sum(int(f.signed_amount_kopecks) for f in schedule)
                    )
                except DecimalException:
                    reasons.add("not_computable_xirr_convergence_failed")
    status = "blocked" if reasons else "hypothetical" if rate is not None else "needs_assumptions"
    if status != "hypothetical":
        rate, rubles = None, None
    payload = dict(
        status=status,
        account_id=context.account_id,
        request_id=context.request_id,
        t0=context.t0,
        t1=context.t1,
        scenario_result_kopecks=rubles,
        scenario_rate_fraction=rate,
        assumed_schedule=tuple(schedule),
        assumptions=assumptions,
        context=context,
        actual_result=context.actual_result,
        limitations=context.limitations,
        reason_codes=tuple(sorted(reasons)),
        context_fingerprint=context.context_fingerprint,
        assumption_fingerprint=digest(assumptions.model_dump(mode="json")),
    )
    provisional = StatementWhatIfResult(**payload, result_fingerprint="")
    return provisional.model_copy(
        update={
            "result_fingerprint": digest(
                provisional.model_dump(mode="json", exclude={"result_fingerprint"})
            )
        }
    )
