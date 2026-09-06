"""Pure domain for Scenario Lab v1 (r07-09).

Deterministic, no I/O, no DB. Implements equity_drawdown semantics
exactly as per docs/r07-09-scenario-lab-contract.md and provides the
deposit_rate_assumption rate-normalization helpers used by 141-B.

Only supported shocks in this slice are equity_drawdown and
deposit_rate_assumption. All other shocks or multi-shock composition
must fail with unsupported_composition_v1.

Money: integer kopecks, percentages as Decimal strings, ROUND_HALF_UP.
Rate normalization for deposit_rate_assumption delegates to the canonical
:mod:`hermes_finance.domain.values` ``PercentageRate`` contract instead of
duplicating its basis-point semantics.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from enum import StrEnum

from hermes_finance.domain.values import PercentageRate

CONTRACT_VERSION = "r07-09-v1"
CALCULATION_VERSION = "r07-09-v1"
SHOCK_SCHEMA_VERSION = "v1"

SUPPORTED_INSTRUMENT_TYPES = frozenset({"stock", "bond", "fund", "currency", "gold", "other"})


class ShockType(StrEnum):
    EQUITY_DRAWDOWN = "equity_drawdown"
    DEPOSIT_RATE_ASSUMPTION = "deposit_rate_assumption"


class DepositTargetSelector(StrEnum):
    ALL_ELIGIBLE_DEPOSITS = "all_eligible_deposits"
    DEPOSIT_IDS = "deposit_ids"


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


def _canonical_string_from_decimal(pct: Decimal) -> str:
    """Lossless canonical fixed-point string without context rounding.

    - strip leading '+'
    - strip trailing zeros and trailing dot
    - canonical zero to "0"
    - uses string manipulation, never Decimal.normalize() which rounds >28 digits
    """
    # Use fixed-point rendering to avoid exponent; preserves exact value
    s = format(pct, "f")
    # strip leading '+'
    if s.startswith("+"):
        s = s[1:]
    # Remove trailing zeros after decimal point
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    # Handle empty, sign-only, or negative zero
    if s in ("", "-", "-0"):
        s = "0"
    elif s.startswith("-"):
        # After stripping, "-0.00" becomes "-0" -> canonical "0"
        try:
            if Decimal(s) == 0:
                s = "0"
        except Exception:
            s = "0" if s in ("-0", "-") else s
    else:
        try:
            if Decimal(s) == 0:
                s = "0"
        except Exception:
            pass
        if s == "-0":
            s = "0"
    # Edge: string like "000" without dot stays "000" -> Decimal("000")==0 -> already "0"
    # For non-zero leading zeros, Decimal will normalize on reconstruction, but keep s as is?
    # Ensure canonical string has no leading '+' and no trailing exponent
    return s


def canonical_drawdown_pct(pct: Decimal) -> Decimal:
    """Lossless canonical Decimal: 20 == 20.0 == 20.00 -> same value, 20.001 distinct.

    Implemented via string manipulation, not Decimal.normalize() which may round
    when context precision is 28.
    """
    s = _canonical_string_from_decimal(pct)
    return Decimal(s)


def normalize_drawdown_pct(pct: Decimal) -> str:
    """Lossless canonical string: equivalent numerics map to same string."""
    return _canonical_string_from_decimal(pct)


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
    """Compute stressed value: base * (1 - pct/100) rounded HALF_UP to kopecks.

    Context-independent: precision is derived from operands (significant digits of
    canonical pct + digits of base_kopecks + guard). Entire expression
    100-pct, /100, *base is executed under that localcontext. Final rounding
    is a single quantize ROUND_HALF_UP at the kopeck boundary.
    """
    if not isinstance(base_kopecks, int) or isinstance(base_kopecks, bool):
        raise TypeError("base_kopecks must be int")
    if base_kopecks < 0:
        raise ValueError("base_kopecks must be >=0")
    if isinstance(drawdown_pct, float):
        raise ValueError("invalid_drawdown_pct: binary float not allowed")
    if not isinstance(drawdown_pct, Decimal):
        raise TypeError("drawdown_pct must be Decimal")
    if not drawdown_pct.is_finite():
        raise ValueError("invalid_drawdown_pct: not finite")
    # Derive precision from operands: significant digits of canonical pct + digits of base + guard
    canonical_str = _canonical_string_from_decimal(drawdown_pct)
    sig_part = canonical_str.replace("-", "").replace(".", "").lstrip("0")
    sig_digits = len(sig_part) if sig_part else 1
    digits_base = len(str(abs(base_kopecks))) if base_kopecks != 0 else 1
    guard = 10
    prec = sig_digits + digits_base + guard
    # Guard against excessively small prec (minimum 28 to cover typical 28-digit contexts)
    if prec < 28:
        prec = 28
    with localcontext() as ctx:
        ctx.prec = prec
        ctx.rounding = ROUND_HALF_UP
        factor = (Decimal(100) - drawdown_pct) / Decimal(100)
        raw = Decimal(base_kopecks) * factor
        # Single rounding at kopeck boundary only
        quantized = raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(quantized)


# ---- deposit_rate_assumption rate helpers (141-B) ----
#
# Rate semantics are intentionally delegated to ``PercentageRate`` so the
# deposit-rate shock does not grow a parallel basis-point model. The only
# added work is the parse/validation of the absolute annual rate (NaN,
# Infinity, negative and binary-float inputs are rejected) and the
# context-independent Decimal guard around the basis-point conversion.

# Context-independent guard for the basis-point conversion.
# Delegated to PercentageRate which is now exact integer/rational.
_RATE_PARSER_PRECISION = 40  # kept for reference, not used as semantic bound

def parse_assumed_annual_rate_pct(raw: object) -> Decimal:
    """Parse and validate an absolute annual rate (percentage points).

    Binary float is rejected. NaN, Infinity and negative values are
    rejected. The returned ``Decimal`` is canonicalized via
    :func:`canonical_drawdown_pct` so equivalent inputs collapse to a
    single canonical representation (independent of any ambient
    ``decimal`` precision).

    Raises ``ValueError`` with a code-prefixed message.
    """
    if isinstance(raw, bool):
        raise ValueError("invalid_assumed_rate_pct: must be decimal string or int")
    if isinstance(raw, int):
        raw = str(raw)
    if isinstance(raw, float):
        raise ValueError("invalid_assumed_rate_pct: binary float not allowed")
    if isinstance(raw, Decimal):
        pct = raw
    elif isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            raise ValueError("invalid_assumed_rate_pct: empty")
        try:
            pct = Decimal(raw)
        except InvalidOperation as e:
            raise ValueError("invalid_assumed_rate_pct: not a decimal") from e
    else:
        raise ValueError("invalid_assumed_rate_pct: unsupported type")
    if not pct.is_finite():
        raise ValueError("invalid_assumed_rate_pct: not finite")
    if pct < Decimal("0"):
        raise ValueError("invalid_assumed_rate_pct: negative rate not allowed")
    return canonical_drawdown_pct(pct)


def canonical_assumed_rate_basis_points(rate_pct: Decimal) -> int:
    """Convert an absolute annual rate to integer basis points.

    Delegates to the canonical :class:`PercentageRate` contract which is
    now exact rational (no fixed precision bound).
    """
    if isinstance(rate_pct, float):
        raise ValueError("invalid_assumed_rate_pct: binary float not allowed")
    if not isinstance(rate_pct, Decimal):
        raise TypeError("rate_pct must be Decimal")
    if not rate_pct.is_finite():
        raise ValueError("invalid_assumed_rate_pct: not finite")
    if rate_pct < Decimal("0"):
        raise ValueError("invalid_assumed_rate_pct: negative rate not allowed")
    return PercentageRate.from_decimal(rate_pct).basis_points


def normalized_rate_string(basis_points: int) -> str:
    """Deterministic canonical decimal string for a basis-point rate.

    Uses :class:`PercentageRate.to_api` so the Scenario Lab never holds
    its own basis-point/percentage-point mapping.
    """
    if not isinstance(basis_points, int) or isinstance(basis_points, bool):
        raise TypeError("basis_points must be int")
    return PercentageRate(basis_points).to_api()


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
