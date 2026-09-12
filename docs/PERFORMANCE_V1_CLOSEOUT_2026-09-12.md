# Performance v1 closeout — 2026-09-12

## Status

Performance v1 is accepted and integrated into canonical `main`.

- Parent roadmap: #127
- Owner UAT: #358 — PASS, closed completed
- Canonical integration task: #360
- Canonical integration PR: #361
- Accepted staging source: `83cca45da5dcc307623a7b79056fea65bc46c48f`
- Final PR head after comment-only migration-header correction: `81c623039aef4202811f42134bdda0e51f81494e`
- Canonical merged `main`: `8b7ecfa9df1283799046d3deccecf272f614796d`
- Exact-head PR CI: run `34691683103` — success
- Exact-main push CI: run `34692212060` — success
- Independent high-risk integration review: ACCEPT

Published Stable remains `0.8.2`; this closeout advances development `main` only and is not a release publication.

## Delivered scope

Performance v1 adds the accepted whole-portfolio and selected-account performance surface while preserving fail-closed evidence semantics:

- portfolio and account XIRR;
- portfolio and account exact TWRR;
- stable scope-membership and boundary-evidence gates;
- explicit cash-boundary coverage;
- transfer reconciliation and asynchronous-transit safety for portfolio scope;
- account transfer-leg semantics without imposing portfolio-only transit gates;
- in-kind boundary coverage and fail-closed known in-kind movement handling;
- endpoint same-day valuation/flow ordering fail-closed behavior;
- PERF04A aggregate selected-scope value bridge: monetary value change after external flows, not return/profit attribution;
- exact zero remains distinct from unavailable/null;
- thin Analytics presentation with owner-facing `РЕЗУЛЬТАТ` label and explicit `Это изменение стоимости, а не доходность.` disclaimer.

## Owner UAT

Owner UAT ran against an isolated scratch copy of real owner data; production data remained untouched and was not exposed to development agents.

The observed portfolio and representative account cases correctly failed closed where current historical evidence was incomplete. XIRR, TWRR and the PERF04A value bridge returned unavailable/null rather than fabricating an exact value or displaying unavailable as zero. The final Analytics presentation was accepted by the owner after the `PERF04A` implementation-code eyebrow was replaced with `РЕЗУЛЬТАТ`.

Synthetic automated coverage remains authoritative for edge cases that were not naturally present in the owner scratch dataset, including endpoint same-day ordering, internal-transfer reconciliation/transit and in-kind cases.

## Canonical integration and migration reconciliation

Performance staging split from the post-v0.8.2 baseline while other accepted work advanced `main`. #360 reconciled both histories rather than replacing either side.

The resulting development migration chain is linear:

`0036_broker_baseline_provenance`
→ `0037_336_financial_context`
→ `0038_cash_boundary_coverage`
→ `0039_transfer_reconciliation_evidence`
→ `0040_in_kind_boundary_coverage`

The integration preserved the current-main #336 schema and the Performance migrations. The final migration-header follow-up changed documentation only so `Revises:` matches the executable `down_revision`; it did not change migration behavior.

Local integration verification reported 24 migration/startup tests, 1800 full-backend tests and 405 frontend tests green, plus Ruff, frontend lint/typecheck/build, privacy and diff checks. A whole-checkout local Biome format command continued to report baseline-wide CRLF normalization diagnostics without writing changes; exact-head GitHub frontend formatting checks were green.

## Explicitly deferred

Performance v1 does **not** implement component attribution or profit decomposition. These remain future contract/work:

- instrument or asset-class attribution;
- realised/unrealised P&L decomposition;
- trade/lot/cost-basis attribution;
- event-explanation attribution;
- component attribution exports.

Future work starts from canonical `main`, not from the retired Performance staging line.