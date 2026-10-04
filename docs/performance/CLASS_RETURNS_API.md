# Exact no-crossing class returns (#535 Phase 1C)

**Status: accepted and integrated** via #700; read-only UI consumer #540/#701 is also integrated. This is post-v1.2.0 development. Canonical milestone and pending Owner UAT: [session closeout](../SESSION_CLOSEOUT_2026-10-04.md).

`GET /api/performance/class-returns?asset_class=stock&start_date=2030-01-31&end_date=2031-01-31`

This combined read-only endpoint supports `stock`, `bond` and `gold` over the
portfolio-wide historical Performance account universe, in RUB only. It consumes
the accepted [class endpoint eligibility](CLASS_NO_CROSSING_ENDPOINTS.md) result
once, under that reader's coherent committed snapshot. It does not reconstruct
evidence, select nearby dates or change portfolio/account `PerformanceScope`.
No new schema, writes, provider calls or result cache are introduced by #535.

## Response

- `asset_class`, `historical_account_ids`: requested class and accepted historical universe.
- `requested_period`: requested `start_date` / `end_date`.
- `actual_covered_period`: exact observed endpoint dates, each nullable when missing;
  dates alone do not assert eligibility or complete coverage.
- `performance_currency`, `valuation_basis`: accepted currency and
  `persisted_rub_market_value_kopecks`. The declared basis describes the supported
  valuation contract; unavailable/unsupported evidence does not supply a value.
  Stored bond accrued-interest semantics are consumed unchanged, exactly once.
- `coverage_state`, `coverage_provenance`: safe #698 evidence fields, including
  Owner provenance, explicit opening/closing inventory claims and revisions.
  Internal material signatures are not exposed. Owner attestation remains an
  attestation, not independent statement verification.
- `eligibility_status`: `eligible`, `unavailable` or `unsupported`, unchanged from #698.
- `evidence_reason_codes`: deterministic #698 reasons, unchanged.
- Independent `xirr` / `twrr` objects: `availability` (`available` / `not_computable`),
  `quality` (`exact` / `unavailable`), `value` (decimal string or null),
  `value_unit=percentage_points`, `annualized`, `reason_codes`, `reason_source`.

`reason_source=evidence` means eligibility blocked calculation: neither solver
was called and both metrics carry the evidence reasons. Unsupported capability
is distinguished by `eligibility_status=unsupported`. For eligible evidence,
solver reasons propagate unchanged with `reason_source=solver`; a successful
metric has no reasons and a null reason source. Evidence and numerical reasons
must never be presented as the same missing-data instruction.

Dates use the existing date-only API convention. Missing/malformed query dates
and unordered/empty intervals return the existing 422 error response.
Unsupported class names return a normal evidence response with
`unsupported_class`, rather than coercing them into a supported class.

## Exact metric construction

Only `eligible` intervals reach the unchanged numerical primitives:

```python
calculate_xirr((
    XirrCashFlow(actual_opening_date, -opening_value_kopecks),
    XirrCashFlow(actual_closing_date, closing_value_kopecks),
))
calculate_twrr(opening_value_kopecks, closing_value_kopecks, boundaries=())
```

No intermediate flows, ExternalFlow reuse, capital deltas, current allocation,
#575 monetary results, class boundary rows or PRE/POST observations are created.
Exact internal same-class transfers affect the accepted aggregate endpoints
only. C4 is vacuous for this affirmatively proven no-crossing subset.

Solver fractional rates are multiplied by Decimal 100 at the response adapter.
XIRR is annualized; TWRR is the whole-period return. Availability and quality are
preserved independently from each solver, without fallback or rounding to zero.

For a 365-day interval, positive 1000 → 1100 supports approximately +10% XIRR
(within existing solver tolerance) and exact +10% TWRR. A shorter interval keeps
TWRR +10% but annualizes XIRR. Flat positive values support 0; positive losses
support negative returns. Zero opening makes both solvers unavailable; positive
opening and zero closing gives unavailable XIRR and exact −100% TWRR. These are
numerical outcomes with complete evidence, not evidence gaps.

Two endpoint flows have at most one sign variation, so ROOT_AMBIGUITY normally
does not arise here. Generic reason propagation preserves it or future solver
limitations without invented flows or changed numerical semantics.

## Delivered UI and remaining boundary

The existing Performance detail now presents Accounts/Classes with exact-date
presets, independent rates/reasons, safe provenance and responsive keyboard
support. `deposit` remains a truthful unsupported row. This UI reads the API;
it does not create class attestations or repair legacy C1 evidence.

Statement-backed crossings, FX, deposits/savings and instrument-level returns
remain outside this slice. #702 researches the next proposed statement-backed
contract without changing this API. Owner UAT and any new release/local update
remain separate from technical integration.
