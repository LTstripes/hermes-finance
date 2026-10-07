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
    [&scope=portfolio|account]
    [&account_id=<id>]
```

`start_date` and `end_date` are the exact persisted valuation dates used by
R08-01C, and the start must precede the end.

`scope` is `portfolio` (the default) or `account`.  Portfolio scope rejects an
`account_id`; account scope requires an explicit `account_id`, and any other
combination is a validation error.  Account scope was added for #146 and is
called as:

```text
GET /api/performance/xirr
    ?start_date=YYYY-MM-DD
    &end_date=YYYY-MM-DD
    &scope=account
    &account_id=<id>
```

The response contains:

- `value`: an exact decimal string in annualized percentage points, or `null`;
- `value_unit: "percentage_points"` and `annualized: true`, so the UI does
  not need to infer or calculate the presentation unit;
- `scope` and the `account_id` it describes (`null` at portfolio scope);
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

Account scope reuses the same translation and solver.  Opening and closing
valuations are the requested account's own boundary points, and each flow is
classified for that account: a contribution to the account is negative and a
withdrawal from it is positive.  A fully linked transfer between two in-scope
accounts remains `INTERNAL_TRANSFER` at portfolio scope, but is a withdrawal
for the source account and a contribution for the destination account.  A flow
belonging to any other account is `NOT_IN_SCOPE` and never enters the series.

All amounts remain integer RUB kopecks until the Decimal solver.  No capital
delta, legacy deposit/withdrawal row, expected event, provider payout, or
unresolved transfer is injected or reclassified.

## Account scope (#146)

Account scope extends the accepted R08-02 pipeline instead of adding a second
one.  It consumes `performance_availability_for_interval(scope=account,
account_id=...)`, the accepted external-flow classification and the same XIRR
solver.  When an input is missing or ambiguous the result stays
`NOT_COMPUTABLE` with the existing fail-closed reason codes: no flow,
valuation, membership or in-kind fact is inferred, approximated or backfilled.
Portfolio scope semantics and reason codes are unchanged.

## Fail-closed calculation

### Historical source bridge (#734)

When month-owned XIRR prerequisites are available, the existing path takes
precedence unchanged. Otherwise the same route and `xirr_for_interval` can consume
effective H1/H2 evidence. Both boundaries must be accepted exact account/date EOD
RUB endpoints; a source boundary is never mixed with a month-owned boundary.
Portfolio totals sum both endpoints for every historically included account,
using the existing gap-free dated membership and membership-transition gates.
Current account inclusion flags cannot supply that universe.

Each required account needs effective H2-A2 COMPLETE coverage for the exact
`[start_date + 1 day, end_date]` window, bound to the compatible H2-A1 ledger.
The shared COMPLETE assessor accepts a gap-free, nonoverlapping union of adjacent
effective source-aware rows; it does not require one row for the whole window.
Gaps, UNKNOWN/retired rows, overlaps and source-free assertions remain refusals.
The existing in-kind and currency gates remain affirmative. Each effective H2-A1
event with `start_date < event_date <= end_date` enters once with the same investor
sign convention. Portfolio events additionally require effective H2-B1 EXTERNAL
authority; explicit NOT_IN_SCOPE adds no amount. Unknown authority or suspected
tracked-account transfers block. Existing portfolio transit safety also applies
at the requested boundaries. No pairing or netting is introduced.

The complete read uses one committed snapshot. Every read revalidates the frozen
endpoint, flow, coverage and portfolio authority through their existing lifecycle
readers. Retired, revoked or invalidated evidence remains unavailable after old
amounts are restored. Evidence refusal precedes solver execution; an eligible
series uses the unchanged solver and retains its numerical reason codes.

No intermediate month-end, ReportingMonth creation, ledger/schema change or
financial write is required. The month-owned availability API, class returns and
TWRR keep their existing evidence requirements; H3 does not promote them.
The existing readiness projection presents final H3 XIRR independently of legacy
monthly availability/TWRR. Ineffective historical endpoints, ineffective account
flows and unknown portfolio-flow authority have specific source-required
diagnostics, with no supported in-page repair action implied.

### Numerical limitations

The solver uses the date-only XIRR equation with a 365-day year and a
deterministic bracketed Decimal search.  Before accepting a visible bracket,
it applies an exact sign-variation certificate: with
`z = (1 + rate) ** (1 / 365)`, the equation is a polynomial in positive `z`.
Histories with more than one coefficient sign change cannot prove a unique
positive root and remain unavailable.  A value is returned only when this
certificate permits at most one root and that root converges.  Otherwise the
response is unavailable with one of:

```text
not_computable_xirr_no_valid_root
not_computable_xirr_convergence_failed
not_computable_xirr_root_ambiguity
```

Same-day ordering remains a TWRR-only limitation under the accepted #145 v2
contract; it does not block XIRR by itself.
