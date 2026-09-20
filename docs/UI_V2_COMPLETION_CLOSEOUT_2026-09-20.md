# UI v2 completion closeout — 2026-09-20

## Status

**COMPLETE / OWNER UAT PASS / INTEGRATED**

This document closes the opt-in UI v2 implementation/completion milestone before the separate controlled default-switch gate.

## Canonical evidence

- Pre-aggregate canonical main: `fe23ca1772a994a04ae74935c25c07c1432a1303`.
- Final frozen Owner-UAT aggregate: `edd6a32d94ba322badaea1cab804c4e5cc13574d`.
- Aggregate PR: #455.
- Owner verdict: **PASS**.
- Canonical main merge: `424ba7bf018c8e4ac01cfda825af7394a3068267`.
- Exact-main CI: #838 / run `35517935019` — **SUCCESS**.

The exact aggregate tree tested by the Owner was merged as a parent of the canonical main merge; it was not reconstructed after PASS.

## Completed functional slices

- #432 — catalogs + persistent mappings
  - accepted head: `c9abd5610566d1ed839d1d9e406b84f861d2a566`.
- #433 — exports + local backup/restore
  - accepted head: `270f70c1ec236fe73b18d06f276360524f18b589`;
  - independent safety review: **ACCEPT**.
- #434 — application settings + tax brackets + runtime diagnostics
  - accepted head: `d2d9983f006a901a0286050cf68ce96b1851ca93`.

S13 umbrella #429 is closed completed.

## Completed owner-UAT polish

- #444 — global «Наверх»: `8f010545e0f17dce4a219c411954fb05e3fb4bd8`.
- #445 — Russian terminology/copy audit: `707325b2f949ef40d4ae2156a10dd3a0200d3398`.
- #446 — Expected payouts hierarchy/alignment/order: `9d4ad980ba50ab54c926c6d8c1735b559bb43a99`.
- #447 — Reports archive spacing/action column: `892456d5c6d90b1f80223d965726a5adc3c84245`.
- #448 — Reconciliation copy deduplication/owner labels: `9040c8109052bf6463390207b56f0bebf8958354`.

All are closed completed after canonical integration.

## Restore safety outcome

#433 required several review iterations because restore can have an ambiguous network outcome after the database has already changed.

Final accepted UI safety behavior includes:

- exact backup target shown before confirmation;
- no restore POST before explicit owner confirmation;
- existing `{confirm:true}` backend contract preserved;
- pre-restore evidence shown only after confirmed success;
- previous evidence cleared before a new attempt;
- successful restore invalidates/refetches shared QueryClient state;
- confirmed backend rejection preserves good cached state;
- network/transport/body-read/malformed-success ambiguity is treated as **unknown**, not falsely as success or failure;
- unknown outcome performs safe QueryClient refresh without blind retry;
- one restore POST only;
- ConfirmDialog traps Tab/Shift+Tab focus;
- create-backup and restore mutations cannot overlap, including handler-level guards.

No new backup backend semantics were introduced.

## Integrator reconciliation notes

Parallel slices touched shared application-spine files. The milestone used the staged-integration contract from `AGENTS.md`.

Notable reconciliation:

- Catalogs + Files + App route/entry wiring and shared visual registration were combined by the Integrator;
- exact accepted child heads remain in staging ancestry;
- an accepted #433 `ConfirmDialog.tsx` focus-containment change was accidentally omitted during manual reconciliation, detected by aggregate/child Frontend CI, then restored exactly before final UAT;
- #444 received one formatter-only Integrator fix;
- #445 received bounded copy-fidelity fixes so unknown/unsupported states were not hidden by over-generic Russian labels.

## Owner UAT

Owner tested the frozen aggregate in isolated Preview/UAT and returned **PASS**.

UAT covered the complete v2 surface including Home, Capital, Income & Plans, Reports/history, Monthly Close and Data/App. Backup/restore testing was constrained to Preview/copy data, never canonical Stable production data.

No post-UAT code changes were made before canonical integration.

## What remains

The core implementation is complete. The only remaining UI v2 roadmap gate is #430:

1. comparative read-only v1/v2 audit;
2. blocker-only cleanup if truly required;
3. bounded default/root routing switch while preserving v1 rollback;
4. exact-SHA Owner UAT;
5. merge only after explicit Owner PASS.

This is **not** v1 retirement. Release publication/runtime promotion is also separate.

## Permanent boundaries

- local single-user Windows-first product;
- loopback-only runtime;
- no cloud/auth/telemetry/trading/background provider refresh;
- no new financial semantics in this milestone;
- v1 remains available until a separate retirement decision;
- canonical `main` remains the only release source.
