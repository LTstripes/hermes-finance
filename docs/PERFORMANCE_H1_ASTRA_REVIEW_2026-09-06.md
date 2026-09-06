# PERF-H1 Astra audit — accepted blocker addendum

> Date: 2026-09-06
> Baseline: `49b290df5d407fafff05a8aac6e3c081fdd8ea45`
> Parent reconciliation: #315

A final independent reviewer-only Astra audit confirmed the PERF-R0 roadmap
reconciliation and compatibility of H1-A..D with accepted R08, but found two
additional false-exact paths in the canonical baseline:

1. whole-portfolio effective-dated membership may change inside an otherwise
   gap-free interval, allowing opening and closing valuations to use different
   account compositions without a corresponding scope-transition value;
2. external cash-flow coverage currently becomes `COMPLETE` when no known
   blocking rows are found, without affirmative evidence that all owner cash
   boundary crossings were captured.

Direct baseline inspection confirmed both findings in
`services/performance_availability.py` and `services/valuation_points.py`.

The accepted minimum contract decisions are recorded in
`docs/PERFORMANCE_V1_RECONCILIATION_2026-09-06.md` as H1-E and H1-F:

- exact whole-portfolio performance requires stable membership throughout the
  requested closed interval until an accepted scope-transition valuation
  contract exists;
- exact performance requires affirmative cash-boundary history coverage per
  relevant account/interval; absence of rows and closed-month status are not
  proof of completeness;
- cash-boundary and in-kind coverage are independent attestations;
- existing R08 formulas are not redesigned.

The reviewer recommendation `FIX CONTRACT FIRST` is therefore satisfied by
PERF-H1 v3 before any implementation task begins.
