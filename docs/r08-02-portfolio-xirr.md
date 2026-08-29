# R08-02 — whole-portfolio XIRR

This document records the implementation contract for issue #146.  It
calculates money-weighted annualized return only after consuming the accepted
R08-01C availability result.  It does not redefine valuation, membership,
currency, legacy-flow, or transfer semantics from #145/#179/#190/#197.

## Read-only API

```text
GET /api/performance/xirr
    ?start_date=YYYY-MM-DD
    &end_date=YYYY-MM-DD
```

The first slice supports the whole `portfolio` only (an optional
`scope=portfolio` is accepted for symmetry with availability; account scope
and `account_id` are rejected).  `start_date` and
`end_date` are the exact persisted valuation dates used by R08-01C, and the
start must precede the end.

The response contains:

- `value`: an exact decimal string in annualized percentage points, or `null`;
- `value_unit: "percentage_points"` and `annualized: true`, so the UI does
  not need to infer or calculate the presentation unit;
- `period` with the requested boundary dates;
- `availability`, `quality`, and stable `reason_codes`.

## Cash-flow convention

The backend builds one investor-perspective series from authoritative R08-01C
evidence:

- opening valuation is negative;
- external contribution is negative;
- external withdrawal is positive;
- an in-scope portfolio transfer is omitted;
- closing valuation is positive.

All amounts remain integer RUB kopecks until the Decimal solver.  No capital
delta, legacy deposit/withdrawal row, expected event, provider payout, or
unresolved transfer is injected or reclassified.

## Fail-closed calculation

The solver uses the date-only XIRR equation with a 365-day year and a
deterministic bracketed Decimal search.  It returns a value only when exactly
one root converges.  Otherwise the response is unavailable with one of:

```text
not_computable_xirr_no_valid_root
not_computable_xirr_convergence_failed
not_computable_xirr_multiple_roots
```

Same-day ordering remains a TWRR-only limitation under the accepted #145 v2
contract; it does not block XIRR by itself.
