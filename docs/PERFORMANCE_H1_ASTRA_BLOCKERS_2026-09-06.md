# PERF-H1 Astra blockers — reviewer provenance

This reviewer-only note records the two Astra blockers that materially changed
PERF-H1 after Spark had accepted H1 v2.

Canonical baseline inspected by the integrator:
`49b290df5d407fafff05a8aac6e3c081fdd8ea45`.

## Confirmed blocker 1 — changing portfolio membership

Current interval coverage checks gap-free effective-dated history, but does not
require the membership value to stay constant. Opening and closing valuations
select included accounts independently by date. A known `false -> true` or
`true -> false` transition can therefore change the valuation composition
without an external/scope-transition value and be mistaken for return.

Accepted decision: until a separate scope-transition valuation contract exists,
whole-portfolio exact performance requires one constant membership state for
each historically relevant account throughout the requested closed interval.

## Confirmed blocker 2 — unaffirmed cash-boundary completeness

Current external-flow coverage returns `COMPLETE` when no blocking explicit or
legacy rows are found. There is no independent proof that all owner cash
contributions/withdrawals were actually captured.

Accepted decision: exact performance requires affirmative cash-boundary history
coverage per relevant account/interval, established by explicit owner
attestation or a future accepted authoritative import/source contract. Closing a
month and absence of rows never constitute that attestation.

The normative contract is H1-E/H1-F in
`docs/PERFORMANCE_V1_RECONCILIATION_2026-09-06.md`.
