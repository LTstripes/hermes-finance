# Source-intake instrument result — read-only conditional slice

Bounded first slice for [#891](https://github.com/LTstripes/hermes-finance/issues/891):
one visibly hypothetical per-instrument RUB/percent result from a durable saved
original, with the accepted #858 payouts and #862 executions reused read-only.
This contract does not authorize actual instrument performance, bonds or
changing-quantity return math.

`GET /api/broker-months/intakes/{intake_id}/instrument-result` recomputes one
saved `source_intake_v1` original and one ISIN inside it. Query parameters:
`isin`, `request_nonce`, and the three Boolean choices `no_unobserved_movements`,
`no_unobserved_payouts`, `no_other_costs_or_taxes` (default false). Responses use
`Cache-Control: no-store`. The endpoint is a GET: no journal revision, no
financial Apply and no second money ledger are required or written.

## What the number is

The observed block is the original's own native EOD facts for the ISIN position:
`beginning_value` (`previous_day_eod` basis at `covered_from − 1`) and
`ending_value` (`covered_to_eod` basis at `covered_to`), exact kopecks through
the shared Decimal discipline. The value change and its percent are reported
separately from the conditional total and are never labelled profit when the
quantity changed.

`P` is the exact supported net dividend sum once, from the unchanged #858 reader
inside the same coherent snapshot: every observed payout row must be
`included_in_known_net`, current and a dividend, and at least one event is
required. Embedded taxes and fees are shown as evidence and are never subtracted
a second time; an unknown tax breakdown stays NULL. `V1 − V0 + P` is computed
only when all three assumptions are explicitly selected and no hard blocker is
present. `actual_instrument_return` is always null and
`whole_period_completeness` always `unknown`.

The conditional total is unannualized (`percent_unit=percentage_points`,
`annualized=false`), uses Decimal precision 100 and no display rounding. For a
fixed holding 1000→900 with a proven 150 net dividend the result is `50.00` RUB,
fraction `0.05`, percent `5`.

## What stays NULL with a finite reason

- **Bonds**: `bond_dirty_basis_source_unproven`, `bond_nkd_basis=unknown`; no
  coupon or apparent value difference produces a number and no clean/dirty
  basis is invented. A separate accepted provenance contract is required.
- **Changed quantity / observed trades**: `quantity_changed_not_profit` and
  `changing_quantity_result_unavailable`. `V1 − V0 + P` does not apply; a dated
  cash-flow MWR needs its own reviewed contract. Observed source facts remain
  visible; the total is NULL.
- **Unattributed Money rows**: `money_economic_effect_unproven`. A stock
  dividend could hide in an unclassified posting; the slice has no authority to
  attribute or waive it, and no second payout is ever added.
- **Unproven payouts**: `proven_net_dividend_required`; absence of rows is never
  a zero. `net_distributions` stays NULL unless every observed row is fully
  supported.
- **Journal/identity**: unbound intake, missing/ambiguous ISIN proposal,
  unproven or conflicting currency, unmapped or mismatched instrument card,
  inactive account.
- **Source controls**: syntax/endpoint blockers, the accepted month controls
  (cash, quantity movement, trade readiness), unparsed sections, REPO,
  principal or in-kind flows, and overlapping same-account originals whose
  instrument economics disagree (`ambiguous_overlapping_originals`).

## Provenance and freshness

The response binds `intake.id`, `head_seq`, `manifest_digest`,
`document_sha256`, the covered period, the current finance-link state and the
journal exceptions, plus the exact position observation row reference. Repeated
GETs are recomputed against the current committed journal; a new revision
changes `head_seq` and the client suppresses the old result. `request_nonce`
binds a response to the caller's evaluation; `dependency_fingerprint` remains
null and is never a reusable completeness token.

## Desktop

The panel lives in the month-close source journal under the selected saved
original ("Условный результат бумаги из сохранённого оригинала"). No checkbox
is preselected; selection, assumption or original changes suppress the old
result. Actual performance is explicitly unavailable. Focused verification:

```text
backend: pytest tests/test_source_intake_result_service.py
frontend: npm test -- src/components/month-close/SourceIntakeInstrumentResult.test.tsx src/components/month-close/SourceIntakeJournal.test.tsx
frontend: npm run build
```
