# Hermes Finance — 2026-10-09 checkpoint and next assignments

This is a dated restart record. Start with live main/PR/issues/CI, [CURRENT_STATUS](CURRENT_STATUS.md) and latest [#554](https://github.com/LTstripes/hermes-finance/issues/554); newer explicit Owner decisions supersede this snapshot. Do not infer local runtime changes from GitHub commits.

## Verified at preparation

- Canonical main `65f1e811971019e2eadda6b20657eb2b86edaf7b`; exact push CI [37956819377](https://github.com/LTstripes/hermes-finance/actions/runs/37956819377) SUCCESS. The later docs-only refresh has its own PR and post-main CI; check them live.
- Published v1.2.0 source `8a0cb257da6ca6a661eb5044d0dd72dac28d90fc`. Prior local Stable checkout matched it; separate production Start/data-continuity confirmation is unrecorded. Owner declined a redundant standalone check. No release/Stable update requested now.
- #736/#738 delivered in #740 with separate source/diagnostic Test UAT and post-main CI PASS. #741 H0 speed accepted; actual read-only Test replies 0.538s/0.524s with unchanged DB/report/source reads.
- #743 remains OPEN; #744 DRAFT at `20c2c4d45832b3c94a15de8720240815fcba705b`. Product [37946758389](https://github.com/LTstripes/hermes-finance/actions/runs/37946758389) and UI [37946758362](https://github.com/LTstripes/hermes-finance/actions/runs/37946758362) SUCCESS, independent [5471760064](https://github.com/LTstripes/hermes-finance/pull/744#pullrequestreview-5471760064) ACCEPT for UAT.
- Owner's direct PowerShell OPS03 reported PASS for that final head with DB_unchanged=true, schema 0054 retained. Test was started and desktop tables/diagnostics/Files screenshots reviewed. Final expanded preparation form and both v2 month links/Back are still unconfirmed. Local process state is time-sensitive: recheck, do not assume stopped or start a competing runtime.
- Full Owner-local financial audit: 10 accounts, 803 read-only checks, 2,637 source numbers and 124 S2 facts without detected mismatch; 18 report responses retained. All 770 return contexts were unavailable. This is fidelity/arithmetic PASS, **not** real XIRR completeness.

## Owner choices

Desktop/laptop only (#746); no mobile design, 390px UAT or phone feature requirement. **Remove obsolete mobile-only tests/data/checks first**, via #747. Real Test screenshots with ordinary finance values are allowed in the authorized assistant/local UAT under #745. No special viewer or repeated image consent. Secrets/full DB/broker sources remain off public Git/CI.

The next financial result is **one independently verified real brokerage-account XIRR for 2026-08-31→2026-09-30** where evidence permits. Do not rebuild two years/all classes first. Existing monthly Performance may be sufficient; H1/H2 is a fallback, not a universal additional gate. TWRR PRE/POST is independent and must not hold up valid account XIRR.

Prior exact account-alias pair decisions stay valid and private; no generic suffix normalization. A designated empty source is excluded only while empty. Adding old instruments/shortening a period does not undo accepted Skip. Any correction/non-impact proof must be separately source-backed and accepted. Reuse #715 S2-B instead of inventing a duplicate Money contract, only if it blocks the chosen interval.

## Work order / no wasted waiting

1. **#747 — first code task, start from live main after this docs refresh.** Remove mobile duplicate test runs and unused mobile-only expected data; migrate unique financial/real-backend/keyboard behavior to desktop. No application/financial changes. It no longer waits for #744.
2. **#749 — may run alongside #747.** One bounded Owner-local read-only task, reusing the existing audit: choose account, exact input schedule, independent XIRR if complete, and one consolidated source-bound acceptance/repair package. No writes, attestation, new repo code, mobile run or second heavy suite. Not another 770-context audit.
3. **#748 — implement after #747 merge.** Repair missing account-readiness rows without inventing historical inclusion or returns. Can proceed alongside the later financial work in a separate workspace.
4. **#744 — frozen pending remaining desktop Owner UAT.** Integrator owns one reconciliation of its shared visual test after #747. Preserve new desktop checks; do not reintroduce phone variants. A new test/executable head needs its own applicable gates; do not claim automatic acceptance.

No concurrent writers to one checkout; one heavyweight local verification process across projects. No extra broad backlog or model benchmarking. A short safe local action is given directly as one/two PowerShell commands; do not spin up Codex or repeat permission failures just for that.

## Gate definitions for the next report

**UI result:** actual final candidate form/readability/navigation with no unintended writes. Correct unavailable values are a valid UI state.

**Financial result:** same-account/same-interval source-backed values and flows, independent mathematical verification, supported explicit acceptance where required, then real Hermes API/UI numeric XIRR. A private reference alone is not app delivery; missing source facts stay unknown. Any real financial acceptance/CLOSED Reopen requires its own exact Owner permission, not this task-planning request.

**Repository result:** required exact-candidate review/CI, guarded integration and independent exact-main CI. Stable publication/deployment is separate. #709 remains OPEN until its financial outcome is accepted.

Launch prompts stay short (5–10 lines): repo/issue, live baseline, role/result, bounds and delivery. State difficulty and recommended model/effort only when selecting an executor; never request runtime model evidence.
