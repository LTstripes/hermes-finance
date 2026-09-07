"""Owner-facing read-only Scenario Lab API and deterministic JSON export (#329).

Exposes the accepted Scenario Lab v1 engine (``equity_drawdown``,
``deposit_rate_assumption``, ``inflation_real_value`` and the canonical
``fx_translation_shock`` baseline) through two read-only surfaces that
share ONE envelope adapter, so the normal JSON response and the
downloadable export cannot drift:

- ``POST /api/months/{month_id}/scenario-lab`` — evaluation envelope;
- ``POST /api/months/{month_id}/scenario-lab/export`` — the same
  envelope as an ``application/json`` attachment (owner download /
  later AI handoff).

The API layer never re-implements Scenario formulas, applicability,
support, fingerprints or frozen-base logic: it only adapts
:func:`hermes_finance.services.scenario_lab.evaluate_scenario_lab`
results. No DB writes, no provider/network calls, no Scenario run
persistence. Machine-readable Scenario error codes are surfaced by the
unified ``api.errors`` handlers (422 with the service ``code``;
reporting-month lookups map to 404 ``reporting_month_not_found``).
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from hermes_finance.api.settings import session_for_request
from hermes_finance.services.scenario_lab import ScenarioLabEvaluation, evaluate_scenario_lab

router = APIRouter(prefix="/api/months", tags=["scenario-lab"])


class ScenarioLabShockRequest(BaseModel):
    """Exactly one Scenario Lab shock payload plus optional evaluation controls.

    ``extra="forbid"`` rejects malformed/unknown request fields. The shock
    payload is passed verbatim to the service: composition, unsupported
    shock types and invalid shock-specific inputs remain the service's
    deterministic decisions and surface through the unified error
    envelope with their machine-readable codes. Only the optional
    ``top_n`` evaluation control is exposed; no implementation or DB
    controls are reachable from the API.
    """

    model_config = ConfigDict(extra="forbid")

    shock: dict[str, Any] = Field(
        description="exactly one supported Scenario Lab shock payload, e.g. "
        '{"equity_drawdown": {"drawdown_pct": "10"}}'
    )
    top_n: int | None = Field(
        default=None,
        ge=1,
        le=100,
        description="optional top-positions count for allocation surfaces (service default 5)",
    )


def scenario_lab_evaluation_payload(evaluation: ScenarioLabEvaluation) -> dict[str, Any]:
    """Canonical envelope adapter shared by the response and the export.

    A plain recursive projection of the accepted
    :class:`~hermes_finance.services.scenario_lab.ScenarioLabEvaluation`
    dataclass: no parallel financial model, no binary floats (money is
    ``int`` kopecks + ``str`` amounts, rates are ``str``), no reordering
    of semantic content. ``generated_at`` stays ``None`` for these
    endpoints, so the envelope is fully deterministic and nothing
    time-derived can enter the semantic fingerprint.
    """
    return asdict(evaluation)


def _evaluate_scenario_lab_for_request(
    session: Session,
    month_id: int,
    request_body: ScenarioLabShockRequest,
) -> ScenarioLabEvaluation:
    if request_body.top_n is None:
        return evaluate_scenario_lab(session, month_id, request_body.shock)
    return evaluate_scenario_lab(session, month_id, request_body.shock, top_n=request_body.top_n)


@router.post("/{month_id}/scenario-lab", response_model=dict[str, Any])
def evaluate_month_scenario(
    month_id: int,
    request_body: ScenarioLabShockRequest,
    session: Session = Depends(session_for_request),
) -> dict[str, Any]:
    """Evaluate one Scenario Lab shock for a reporting month (read-only)."""
    evaluation = _evaluate_scenario_lab_for_request(session, month_id, request_body)
    return scenario_lab_evaluation_payload(evaluation)


@router.post("/{month_id}/scenario-lab/export")
def export_month_scenario(
    month_id: int,
    request_body: ScenarioLabShockRequest,
    session: Session = Depends(session_for_request),
) -> Response:
    """Deterministic JSON export of the same evaluation envelope.

    The body is the exact output of
    :func:`scenario_lab_evaluation_payload` serialized canonically
    (sorted keys, no floats). The filename derives from the reporting
    month and shock type only and is metadata: it never alters the
    semantic payload or fingerprint.
    """
    evaluation = _evaluate_scenario_lab_for_request(session, month_id, request_body)
    payload = scenario_lab_evaluation_payload(evaluation)
    month = evaluation.reporting_month
    shock_type = evaluation.normalized_shock_input["shock_type"]
    filename = f"scenario_lab_{month['year']:04d}-{month['month']:02d}_{shock_type}.json"
    return Response(
        content=json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": "application/json; charset=utf-8",
        },
    )
