"""Bounded exact certificates for positive roots of the ACT/365 polynomial.

Descartes subdivision counts disjoint open cells and their rational boundaries.
Exhausting a resource limit proves nothing: callers must report numerical failure.
No rounded NPV or finite scan is used to establish uniqueness.
"""

from dataclasses import dataclass
from functools import reduce
from math import gcd

_MAX_DEGREE = 8192
_MAX_BITS = 16384
_MAX_WORK = 2_000_000
_MAX_NODES = 512
_MAX_EVALUATION_BITS = 1_000_000


class CertificationLimit(Exception):
    """The exact calculation cannot finish within its numerical budget."""


@dataclass(frozen=True)
class RootCertificate:
    count: int  # 0, 1, or 2 meaning at least two distinct positive roots.
    exact_point: tuple[int, int] | None = None


def _primitive(p):
    while p and p[-1] == 0:
        p.pop()
    while p and p[0] == 0:
        p.pop(0)  # zero roots are outside z>0
    if not p:
        raise CertificationLimit
    content = reduce(gcd, p)
    return [v // content for v in p]


def _variation(p):
    signs = [v > 0 for v in p if v]
    return sum(a != b for a, b in zip(signs, signs[1:]))


class _Budget:
    def __init__(self):
        self.work = 0
        self.nodes = 0

    def charge(self, work=0):
        self.work += work
        if self.work > _MAX_WORK:
            raise CertificationLimit

    def check(self, p):
        if len(p) - 1 > _MAX_DEGREE or max(abs(v).bit_length() for v in p) > _MAX_BITS:
            raise CertificationLimit

    def shift(self, p):
        """Exact P(1+u), Horner form, with allocation bounds checked first."""
        n = len(p) - 1
        self.charge(n * (n + 1) // 2)
        if max(abs(v).bit_length() for v in p) + n + n.bit_length() > _MAX_BITS:
            raise CertificationLimit
        result = [p[-1]]
        for value in reversed(p[:-1]):
            result = (
                [result[0] + value]
                + [result[i - 1] + result[i] for i in range(1, len(result))]
                + [result[-1]]
            )
        self.check(result)
        return _primitive(result)


def _matrix(values):
    if max(v.bit_length() for v in values) > _MAX_BITS:
        raise CertificationLimit
    content = reduce(gcd, values)
    return tuple(v // content for v in values)


def positive_root_certificate(coefficients):
    """Prove zero/one/multiple distinct positive roots, or raise a limit.

    z=(1+r)^(-g/365) is a bijection. Integer Mobius maps carry exact rational
    subdivision boundaries back to z, permitting fully certified tangencies.
    A known root is never accepted while another unresolved cell remains.
    """
    budget = _Budget()
    p = _primitive(list(coefficients))
    budget.check(p)
    pending = [(p, (1, 0, 0, 1))]
    count, point = 0, None
    while pending:
        p, matrix = pending.pop()
        budget.nodes += 1
        if budget.nodes > _MAX_NODES:
            raise CertificationLimit
        # Remove every unit factor, but count this distinct boundary only once.
        boundary = False
        while len(p) > 1 and sum(p) == 0:
            budget.charge(len(p))
            boundary = True
            q = [p[-1]]
            for coefficient in reversed(p[1:-1]):
                q.append(coefficient + q[-1])
                if abs(q[-1]).bit_length() > _MAX_BITS:
                    raise CertificationLimit
            p = _primitive(list(reversed(q)))
        if boundary:
            a, b, c, d = matrix
            num, den = a + b, c + d
            common = gcd(num, den)
            point = (num // common, den // common)
            count += 1
        variations = _variation(p)
        if variations <= 1:
            count += variations
            if variations:
                point = None
            if count >= 2:
                return RootCertificate(2)
            continue
        if count >= 2:
            return RootCertificate(2)

        # Balance constant/leading magnitude before splitting; a heuristic only.
        n = len(p) - 1
        k = (abs(p[0]).bit_length() - abs(p[-1]).bit_length()) // n
        if k:
            shifts = [k * i if k > 0 else -k * (n - i) for i in range(n + 1)]
            if max(abs(v).bit_length() + s for v, s in zip(p, shifts)) > _MAX_BITS:
                raise CertificationLimit
            a, b, c, d = matrix
            if max(v.bit_length() for v in matrix) + abs(k) > _MAX_BITS:
                raise CertificationLimit
            p = _primitive([v << s for v, s in zip(p, shifts)])
            matrix = _matrix((a << max(k, 0), b << max(-k, 0), c << max(k, 0), d << max(-k, 0)))
            budget.charge(n + 1)
            if sum(p) == 0:
                pending.append((p, matrix))
                continue
        a, b, c, d = matrix
        # (0,1): u=1/(1+w). (1,infinity): u=1+w. Interiors disjoint.
        left = budget.shift(list(reversed(p)))
        right = budget.shift(p)
        pending.append((left, _matrix((b, a + b, d, c + d))))
        pending.append((right, _matrix((a, a + b, c, c + d))))
    return RootCertificate(count, point)


def polynomial_from_dates(normalised):
    offsets = [(day - normalised[0][0]).days for day, _ in normalised]
    day_gcd = reduce(gcd, offsets)
    degree = offsets[-1] // day_gcd
    if degree > _MAX_DEGREE:
        raise CertificationLimit
    p = [0] * (degree + 1)
    for offset, (_, amount) in zip(offsets, normalised):
        if abs(amount).bit_length() > _MAX_BITS:
            raise CertificationLimit
        p[offset // day_gcd] = amount
    return _primitive(p), day_gcd


def rational_sign(p, numerator, denominator):
    """Sign of denominator^degree*P(numerator/denominator), exact integers."""
    if numerator <= 0 or denominator <= 0:
        raise CertificationLimit
    degree = len(p) - 1
    estimated_bits = (
        degree * max(numerator.bit_length(), denominator.bit_length())
        + max(abs(v).bit_length() for v in p)
        + degree.bit_length()
        + 2
    )
    if estimated_bits > _MAX_EVALUATION_BITS:
        raise CertificationLimit
    result, power = p[-1], 1
    for coefficient in reversed(p[:-1]):
        power *= denominator
        result = result * numerator + coefficient * power
    return (result > 0) - (result < 0)


def validates_candidate(p, day_gcd, log_rate, tolerance):
    """Exact rational enclosure rejects rounded Decimal NPV phantom zeroes.

    Radius gives log-rate error < tolerance with 25% rounding margin. Primitive
    coefficients below 2^16384 bound roots between 1/(1+2^16384) and 1+2^16384;
    precision60 exp/argument rounding is far below the smallest relative radius
    (0.75e-28/365). No floating-point signs enter this proof.
    """
    from decimal import Decimal

    scale = Decimal(day_gcd) / Decimal(365)
    z = (-log_rate * scale).exp()
    radius = Decimal("0.75") * tolerance * scale
    bounds = (z * (1 - radius), z * (1 + radius))
    if not all(v.is_finite() and v > 0 for v in bounds) or bounds[0] >= bounds[1]:
        return False
    # Check before Decimal.as_integer_ratio can allocate an enormous power10.
    if any(abs(v.adjusted()) + len(v.as_tuple().digits) > _MAX_BITS for v in bounds):
        raise CertificationLimit
    signs = [rational_sign(p, *v.as_integer_ratio()) for v in bounds]
    return signs[0] == 0 or signs[1] == 0 or signs[0] != signs[1]
