# Fixed-holding stock WHAT-IF

Read-only slice for [#865](https://github.com/LTstripes/hermes-finance/issues/865),
under the [accepted stock-only amendment](https://github.com/LTstripes/hermes-finance/issues/865#issuecomment-6233624253).
This contract does not authorize actual instrument performance.

`GET /api/instruments/{id}/conditional-return` recomputes one brokerage/IIS account,
one historical RUB stock and exact EOD `(t0,t1]`. The three Boolean query choices
`no_unobserved_movements`, `no_unobserved_payouts`, `no_other_costs_or_taxes`
default to false. `request_nonce` binds a response to the caller's evaluation;
it is not evidence of source completeness. Responses use `Cache-Control: no-store`.

One outer `coherent_read_operation` owns the query-only committed snapshot.
`instrument_eod_observations` supplies #860 boundaries and nested #858 net
payouts; `known_instrument_trades` supplies #862 executions. Readers and
financial writers retain their existing authority. No new financial row,
schema, ledger, source parser, provider call or export is introduced.

DTO sections separate `observed`, `accepted_known`, `chosen_assumptions`,
`hard_blockers` and `hypothetical_result`. Only all three selected assumptions
and no hard blocker permit integer-kopeck `V1 - V0 + P`. P is the sum of the
canonical supported dividend ICF events once, preserving unknown tax breakdown
and already netted fees/taxes. The unannualized fraction and percentage-point
strings use Decimal precision 100 and no display rounding. A repeating fraction
is represented to that declared arithmetic precision, never through binary float.
For 1000→900 and net dividends 150, results are `50.00` RUB, fraction `0.05`,
percent `5`. Negative and exact-kopeck results follow the same formula.

Hard guards retain missing/stale EOD, changed identity/positive quantity,
incompatible currency, unproven/booked/conflicting payouts, native/accepted
executions and crossing/pending events, REPO/opaque transfers, principal,
persisted in-kind movements, source binding/integrity/disposition conflicts,
unparsed sections, source-calendar gaps and ambiguous overlapping originals.
The source inventory is inspected even when the accepted trade list is empty.
Account-scoped Money rows inside the period conservatively block with
`money_economic_effect_unproven`: this stock slice has no independent authority
to dismiss their economic effect or attribute them to a dividend. Even an
accepted unrelated cash subset is not a waiver. No source authority is rewritten.

Every bond is hard blocked with `bond_dirty_basis_source_unproven`, including
an artificial persisted `included` basis. All three result values remain null.
The three hypothetical assumptions can cover only unobserved events; they never
waive observed unsupported economics or assert complete inventory.

Always: `actual_instrument_return=null`, `whole_period_completeness=unknown`,
top-level `dependency_fingerprint=null`. #862's null fingerprint is preserved;
no reusable inventory certification is manufactured. Source/proof references
describe this read, not subsequent requests. A concurrent WAL commit is invisible
to the current coherent snapshot and is evaluated on the next request.

The existing Capital → Performance instrument selector contains the on-demand
panel. No checkbox is preselected. Selector/context/assumption changes, pending
refreshes, failed reads and mismatched nonce/method/nested scope suppress old
results. Nothing is persisted. Actual performance remains explicitly unavailable.

Focused verification:

```text
backend: pytest tests/test_instrument_what_if_service.py
frontend: npm test -- src/ui-v2/InstrumentWhatIf.test.tsx src/ui-v2/InstrumentCashIncome.test.tsx
frontend: npm run build
frontend: npx playwright test --config playwright.instrument-what-if.config.ts
```

The desktop journey starts only its own disposable fabricated database/backend
on loopback port 18865 (overridable), validates API parity, keyboard, 1440 width,
1280 width at 125% zoom, delayed A→B→A, failed reads and the blocked bond.
Installed Stable and Owner data are outside this verification path.
