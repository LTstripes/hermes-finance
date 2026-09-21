# UI v2 default-switch closeout — 2026-09-21

## Status

**COMPLETE / OWNER UAT PASS / DEFAULT SWITCH INTEGRATED**

This document closes the final controlled UI v2 cutover after the implementation/completion milestone recorded on 2026-09-20.

## Canonical evidence

- pre-cutover canonical main after restore-safety integration: `a11c1b3580ffa2dad0b6bd7f19fe6d2dae2e6fba`;
- frozen Owner-UAT switch candidate: `09649bb1d71d6bdff636bb6becbf16d9f0cd5083`;
- PR: #474;
- Owner verdict: **PASS**;
- canonical default-switch merge: `583f9167ae14509202ef47978e7b9f20180e188d`;
- exact-main CI: #872 / run `35573224359` — **SUCCESS**;
- exact candidate CI: `35572421231` — SUCCESS;
- exact candidate UI comparison evidence: `35572421160` — SUCCESS.

The Owner-tested switch tree was merged without post-UAT code changes.

## Final route contract

After the cutover:

- `/` renders the primary UI v2 Home;
- `/v1` renders the previous UI Dashboard inside the existing legacy AppLayout;
- `/v2` remains valid;
- all existing `/v2/...` deep links remain valid;
- legacy routes/editors such as `/months/...`, `/accounts`, `/analytics`, `/goals`, `/export`, `/settings` and related workflows keep their historical URLs;
- permanent version rollback to `/v1` is distinct from contextual legacy returns;
- contextual month/editor returns preserve month, step, query and fragment context.

V1 is not retired.

## Gate A — comparative audit

The independent read-only comparative review found no product-gap project required before cutover.

It did require the candidate to:
- define a durable explicit legacy home;
- remove the old assumption that `/` meant v1;
- preserve contextual legacy handoffs;
- keep a rollback route available during lazy-load/error states;
- preserve keyboard/narrow usability;
- prove passive navigation does not trigger provider calls or mutations.

Gate A verdict: **ACCEPT**.

## Gate B — bounded switch candidate

The switch stayed frontend-only and preserved all financial/provider/backup/runtime/persistence semantics.

The candidate added:
- `/` -> v2 default entry;
- `/v1` -> legacy Dashboard;
- corrected legacy Dashboard navigation;
- explicit primary/previous-interface copy;
- permanent `UI v1` rollback link;
- separate contextual previous-interface return;
- loading/error fallback escape;
- direct-entry/reload/history/narrow/keyboard/passive-navigation regressions.

The new switch browser spec was explicitly added to the canonical UI evidence runner and made baseURL/port-safe before Gate B acceptance.

## Restore-safety reconciliation before cutover

Independent audit found a separate current-main safety defect while cutover was pending: a restore could replace the live database and then fail while building response metadata, while UI v2 could misclassify the HTTP 5xx as a confirmed failure.

#475 / PR #477 resolved this before the final switch candidate was frozen.

Accepted restore contract:
- confirmed pre-mutation negative outcomes remain distinct;
- possibly-mutated/post-boundary outcomes use machine-readable `restore_outcome_ambiguous`;
- ambiguous UI state claims neither success nor failure;
- no pre-restore success evidence is shown for ambiguity;
- shared QueryClient reads are refreshed;
- one restore POST only; no blind retry;
- cleanup cannot overwrite an already-classified ambiguous outcome.

Independent safety re-review: **ACCEPT**.

#475 accepted candidate:
`676b330b59deb4abea89f7807af8b382a1ac4c87`

Canonical #475 merge:
`a11c1b3580ffa2dad0b6bd7f19fe6d2dae2e6fba`

Exact-main CI:
#869 / `35571951532` — SUCCESS.

## Final Owner UAT

Owner tested exact switch SHA:

`09649bb1d71d6bdff636bb6becbf16d9f0cd5083`

UAT covered the default v2 entry, explicit `/v1` rollback, retained `/v2`, main v2 sections, contextual legacy handoffs, browser history/deep links, narrow/keyboard access and passive-navigation safety.

Owner verdict: **PASS**.

## Roadmap closeout

#430 is closed completed.

Parent core UI v2 roadmap #387 is closed completed.

The core UI v2 product is now accepted as the primary development-main owner interface.

## What remains separate

- #476 — one deterministic real-backend synthetic G04 browser regression gate;
- #460 — bounded verified protected-backup retention;
- #461 — isolated disaster-recovery rehearsal;
- #462 — focused legacy Export/Backup post-restore month-state reload;
- #389 — future configurable dashboards;
- v1 retirement — only through a later explicit task if real-use evidence shows the legacy rollback/editors are no longer needed;
- release publication / Stable promotion — separate from development-main acceptance.

## Permanent boundaries

- local single-user Windows-first product;
- loopback-only runtime;
- no cloud/auth/telemetry/trading/background provider refresh;
- no new financial semantics introduced by the cutover;
- provider/network actions remain explicit owner actions;
- v1 remains available until a separate retirement decision;
- canonical GitHub `main` remains the only release source.
