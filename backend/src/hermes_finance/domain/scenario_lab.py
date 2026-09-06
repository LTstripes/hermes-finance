"""Pure domain for Scenario Lab v1 (r07-09).

Deterministic, no I/O, no DB. Implements equity_drawdown semantics
exactly as per docs/r07-09-scenario-lab-contract.md.

Only supported shock in 141-A is equity_drawdown. All other shocks
or multi-shock composition must fail with unsupported_composition_v1.

Money: integer kopecks, percentages as Decimal strings, ROUND_HALF_UP.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import StrEnum

CONTRACT_VERSION = "r07-09-v1"
CALCULATION_VERSION = "r07-09-v1"
SHOCK_SCHEMA_VERSION = "v1"

SUPPORTED_INSTRUMENT_TYPES = frozenset({"stock", "bond", "fund", "currency", "gold", "other"})


class ShockType(StrEnum):
    EQUITY_DRAWDOWN = "equity_drawdown"


class RowApplicability(StrEnum):
    APPLIED = "applied"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


class MetricSupportStatus(StrEnum):
    SUPPORTED = "supported"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class NormalizedShockInput:
    shock_type: str
    drawdown_pct: str  # decimal string normalized to 2 decimals for fingerprint? keep exact
    drawdown_pct_decimal: Decimal


@dataclass(frozen=True, slots=True)
class MetricSupport:
    status: MetricSupportStatus
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PerPositionImpact:
    position_id: int
    base_market_value_kopecks: int
    stressed_market_value_kopecks: int
    delta_kopecks: int
    applicability: RowApplicability


def parse_drawdown_pct(raw: object) -> Decimal:
    """Parse and validate drawdown_pct. Raises ValueError with code in message."""
    if isinstance(raw, bool):
        raise ValueError("invalid_drawdown_pct: must be decimal string or number")
    if isinstance(raw, (int, float)):
        # forbid float per financial exactness; accept int as decimal
        if isinstance(raw, float):
            raise ValueError("invalid_drawdown_pct: binary float not allowed")
        raw = str(raw)
    if isinstance(raw, Decimal):
        pct = raw
    elif isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            raise ValueError("invalid_drawdown_pct: empty")
        try:
            pct = Decimal(raw)
        except InvalidOperation as e:
            raise ValueError("invalid_drawdown_pct: not a decimal") from e
    else:
        raise ValueError("invalid_drawdown_pct: unsupported type")
    if not pct.is_finite():
        raise ValueError("invalid_drawdown_pct: not finite")
    if pct < Decimal("0") or pct > Decimal("100"):
        raise ValueError("invalid_drawdown_pct: out of range 0..100")
    return pct


def canonical_drawdown_pct(pct: Decimal) -> Decimal:
    """Lossless canonical Decimal: 20 == 20.0 == 20.00 -> same value, 20.001 distinct."""
    # Use normalize to strip trailing zeros without losing precision.
    # Decimal('20.00').normalize() -> 2E+1 -> format 'f' -> '20' but value stays 20.
    # Keep the numeric value identical; string form is derived separately.
    # For integers, normalize may produce exponent; quantize not needed.
    # We return the numeric canonical value (same arithmetic value) without quantization.
    # Using normalize preserves precision for non-trailing-zero cases.
    try:
        # Normalize removes trailing zeros; for 0 we keep 0
        n = pct.normalize()
    except Exception:
        n = pct
    # For values like 20.00, normalize gives 2E+1; keep numeric equivalence
    # Ensure -0 becomes 0
    if n == 0:
        return Decimal(0)
    return n

def normalize_drawdown_pct(pct: Decimal) -> str:
    # Lossless canonical string: equivalent numerics map to same string.
    # Use canonical Decimal then format 'f' to remove exponent.
    c = canonical_drawdown_pct(pct)
    # format with 'f' removes scientific notation; also remove trailing zeros already via normalize
    s = format(c, "f")
    # Ensure plain decimal without exponent, and without unnecessary plus sign
    # normalize already stripped trailing zeros, so "20.10" -> "20.1"
    return s


def classify_applicability(instrument_type: object) -> RowApplicability:
    if not isinstance(instrument_type, str):
        return RowApplicability.UNKNOWN
    v = instrument_type.strip()
    if not v:
        return RowApplicability.UNKNOWN
    if v not in SUPPORTED_INSTRUMENT_TYPES:
        return RowApplicability.UNKNOWN
    if v == "stock":
        return RowApplicability.APPLIED
    return RowApplicability.NOT_APPLICABLE


def stressed_market_value_kopecks(base_kopecks: int, drawdown_pct: Decimal) -> int:
    """Compute stressed value: base * (1 - pct/100) rounded HALF_UP to kopecks."""
    if not isinstance(base_kopecks, int) or isinstance(base_kopecks, bool):
        raise TypeError("base_kopecks must be int")
    if base_kopecks < 0:
        raise ValueError("base_kopecks must be >=0")
    # Decimal arithmetic
    factor = (Decimal(100) - drawdown_pct) / Decimal(100)
    raw = Decimal(base_kopecks) * factor
    # quantize to 0
    return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def canonical_json_hash(obj: object) -> str:
    canonical = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def semantic_fingerprint_payload(
    *,
    contract_version: str,
    calculation_version: str,
    shock_schema_version: str,
    reporting_month: dict,
    base_fingerprint: str,
    normalized_shock: dict,
    normalized_target_scope: dict,
    assumptions: list[str],
    base: dict,
    stressed: dict,
    impact: dict,
    row_applicability: dict,
    metric_support: dict,
    coverage: dict,
    affected_refs: dict,
) -> str:
    payload = {
        "affected_canonical_refs": affected_refs,
        "assumptions": sorted(assumptions),
        "base": base,
        "base_fingerprint": base_fingerprint,
        "calculation_version": calculation_version,
        "contract_version": contract_version,
        "coverage": coverage,
        "impact": impact,
        "metric_support": metric_support,
        "normalized_shock_input": normalized_shock,
        "normalized_target_scope": normalized_target_scope,
        "reporting_month": reporting_month,
        "row_applicability": row_applicability,
        "shock_schema_version": shock_schema_version,
        "stressed": stressed,
    }
    return canonical_json_hash(payload)
