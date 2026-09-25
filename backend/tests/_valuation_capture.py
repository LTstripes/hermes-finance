"""Synchronous synthetic capture helper for existing valuation tests."""

from __future__ import annotations

from sqlalchemy.orm import Session

from hermes_finance.persistence import ObservedValuationPoint
from hermes_finance.services.valuation_boundaries import create_observed_valuation_point as _save
from hermes_finance.services.valuation_material_signature import material_signature_for_boundary


def create_observed_valuation_point(session: Session, **kwargs: object) -> ObservedValuationPoint:
    if "expected_material_signature" not in kwargs:
        kwargs["expected_material_signature"] = material_signature_for_boundary(
            session,
            external_flow_id=kwargs.get("external_flow_id"),  # type: ignore[arg-type]
            boundary_group_id=kwargs.get("boundary_group_id"),  # type: ignore[arg-type]
        )
    return _save(session, **kwargs)
