# UI v2 parity session checkpoint — 2026-09-28

This document is the durable handoff between Integrator sessions. It records accepted staging state and the remaining bounded tail without changing product/runtime semantics.

## Exact checkpoints

- Canonical `main` at checkpoint creation: `453dd6db68e069028d130060ce18e08bc3bbff64`.
- UI parity staging: `integration/ui-v2-parity@f27c33dff940315827d7b9231146945a43b16273`.
- Performance staging: `integration/performance-ui-v2@a9198a46a9efedcf1e60f5628ff308ebe65952dc`.
- Published Stable remains immutable `v1.0.0`; this checkpoint does not publish or promote anything.

A later docs-only merge may advance `main` without changing either staging checkpoint above.

## Completed UI parity wave

The editor/import wave is integrated into `integration/ui-v2-parity`:

- #551 Income polish — complete.
- #552 Goals v2 — complete.
- #553 Tax/IIS planner v2 — complete.
- #555 navigation cleanup — complete.
- #556 Scenario Lab v2 — complete.
- #557 month management — complete.
- #558 native month-editor shell — complete.
- #559–#564 month-editor leaves — complete and issue states corrected to CLOSED.
- #607 shared accepted leaf wiring — complete.
- #565 Alfa baseline native preview/apply — complete.
- #566 payout calendar + forecast preview/apply — complete.
- #567 statement import native workflow — complete.
- #575 monthly monetary result by account/class — complete.

#567 final accepted candidate: `495f99cf6ad93b7ee7916a4b4c6eaedb53d87ceb`; exact-head CI `36467058094` and UI comparison `36467057893` SUCCESS; independent Grok 4.7 import/privacy/data-integrity review ACCEPT. Merge staging checkpoint: `f27c33dff940315827d7b9231146945a43b16273`.

## Remaining UI parity tail

Only the following bounded parity/gate work remains:

1. **#568 — IIS write forms.** Existing profile/contribution/deduction operations only; no new tax semantics.
2. **#569 — Capital allocation/concentration detail.** Read-only presentation over existing risk-allocation DTO.
3. **#570 — Analytics/Home reconciliation docs.** Draft PR #574 exists but is stale against old staging and needs independent financial/product review plus final refresh on the final aggregate.
4. **#571 — native Monthly Close wiring.** Final shared-spine routing/readiness integration after accepted leaf destinations, including applicable #568 links.
5. **#572 — aggregate parity verification + Owner UAT.** One exact aggregate, synthetic real-backend evidence, capability matrix and short isolated Preview UAT.
6. **#573 — v1 retirement decision gate only.** Remains BLOCKED until #570/#572/Performance reconciliation and explicit Owner authorization. It does not remove v1 by itself.

## Performance dependency remaining

Performance Phase A UI/data workflow work is substantially integrated. Open Phase B/aggregate items:

- #535 — class-return backend/API over accepted #534 contract;
- #540 — compact class-return UI over accepted #535;
- #541 — final Performance aggregate/Owner-UAT checkpoint; Checkpoint A work has already progressed, but the issue stays open until the required final milestone/re-scope decision.

Performance umbrella #528 stays open until the retained milestone is complete.

## Recommended next-session sequencing

Do not auto-launch work. Owner chooses order.

A compact default plan is:

`(#568 || #569) + (#535 -> #540) -> #570 final refresh -> #571 -> #541/#572 -> #573 owner decision`

Parallel notation means scope compatibility only; local resource rule still allows only one heavyweight local verification process at a time across Finance and Health-Check.

## Owner actions still pending

- No Owner UAT is required immediately at this checkpoint.
- Aggregate Owner UAT is intentionally deferred to #572, after the remaining parity slices and accepted Performance compatibility are present on one exact tree.
- #573 requires a separate explicit Owner decision before any v1 retirement implementation is authorized.
- Stable/release promotion remains separate from all parity staging work.

## Model evidence snapshot

Validated recent implementation cases:

- #565 — Astra Medium, runtime-confirmed; staging-stage **B** after one bounded correction round.
- #566 — Muse Spark 1.3 / OpenCode, Worker-reported model identity; staging-stage **C** after three substantive correction rounds; Grok 4.7 independent review ACCEPT.
- #567 — MiMo 2.6 Flash / OpenCode, runtime-confirmed; staging-stage **B** after one bounded correction round; Grok 4.7 independent review ACCEPT.
- #607 — staging-stage **A**, but implementation model identity was not runtime-proven and must not be attributed to Astra.

The benchmark remains observational, role/risk-specific and not a universal leaderboard.

## Session restart rule

A new Integrator session should treat GitHub as authoritative, independently read current `main`, both staging branches and open issues before launching anything. This file is a checkpoint, not a substitute for live GitHub state.
