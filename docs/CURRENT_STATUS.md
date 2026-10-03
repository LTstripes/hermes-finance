# Hermes Finance — current status

Canonical Owner/Integrator checkpoint, synchronized **2026-10-03** after publication of Owner-selected **1.1.0**. Publication is complete; local installation and real-history acceptance remain separate facts. The independently verified publication identity and final evidence are recorded in [release control #643](https://github.com/LTstripes/hermes-finance/issues/643).

## Current delivery

The accepted native UI/editor/import/Monthly Close work and Performance Phase A are now together on canonical main, not separate unfinished product branches.

- Accepted common head: `8c85fe687898b8e2f2d036680cebf0a003cf813c`, tree `a3678a65efb8dafc1971284d301be7cb6e40f64f`.
- #642 main integration: `73d348f614cb82b10f2e48992612f650deb88e33`, exact reviewed tree preserved.
- #640 historical model-journal integration / preparation baseline: `e16d53a2f64ceebe9d5e59ab2866ac6740692e14`; only 43 journal lines differ from the accepted common head.
- Baseline canonical push CI `36772665643`: SUCCESS. Version preparation and its final-main CI have separate identities in #643.
- Accepted UI input `17af4c29ed5ab02472c6f4378e59cf54fd7fa1aa` and Performance input `47a798de5b979fcd50b5a9880330e2c3eef62b56` remain in ancestry with prior main `ee9faea0b49f08454c284deb0db926f8db981a9d`.
- Independent common-tree review: DeepSeek V4.1 Flash / OpenCode — ACCEPT; [Integrator acceptance](https://github.com/LTstripes/hermes-finance/pull/642#issuecomment-5918859039).

The original split-branch September 28 checkpoint is historical, not the current task list. Its full detail is preserved in [the prior status snapshot](https://github.com/LTstripes/hermes-finance/blob/e16d53a2f64ceebe9d5e59ab2866ac6740692e14/docs/CURRENT_STATUS.md), [the dated UI checkpoint](UI_V2_PARITY_CHECKPOINT_2026-09-28.md) and [execution history](EXECUTION_HISTORY.md).

## Owner acceptance and release identity

Owner explicitly approved main integration and release before repeating representative-history Preview UAT, then selected **1.1.0**. [Recorded exception](https://github.com/LTstripes/hermes-finance/issues/572#issuecomment-5919067817): **OWNER_AUTHORIZED_UAT_DEFERRAL**, not Owner PASS. This applies to this delivery only; CI, independent review, guarded publication, backup-first update and data isolation remain required. #572 stays open for the actual ordinary-use observation.

**1.1.0 is published** (2026-09-30). Independently verified identity: released commit `32c905cfc938fd1aeaeb67643eb6fa77e8644a64`, release tree `7f5a3198fa650b71545550301063c9afd887f8f8`; annotated tag `v1.1.0`, tag object `9b402190bafc5d8415b217580da5e18ed35a6331`, peeling exactly to the released commit; published GitHub Release `Hermes Finance 1.1.0`. Release preparation PR #644 accepted head `f4de8e39217ee0ec73b2524433940674247461f7`; exact-main push CI `36776904188`: SUCCESS; guarded Release run `36777962224`: SUCCESS. Full evidence: [release control #643](https://github.com/LTstripes/hermes-finance/issues/643).

Publication is complete, but **local Stable update, Start and real-history acceptance are still outstanding Owner operations** and are not claimed here. The predecessor **v1.0.0**, code `caf4fdad99cc02f5bc171ec3b1d726b8516ad45e`, annotated tag `f99ee8ecac1acde7f559d92ee8f45ddcfcdfaa47`, remains historical evidence for that version; its proven Owner UAT/OPS02/Start/data continuity are not 1.1.0 acceptance. See [1.1.0 release record](releases/1.1.0.md) and [publication notes](release-notes-1.1.0.md).

The current aggregate draft UAT wave ([PR #662](https://github.com/LTstripes/hermes-finance/pull/662), targeting `main` from `integration/post-release-uat-wave`) is **not merged and not part of published 1.1.0**; its Owner UAT is pending and it must not be described as released or accepted.

## Completed scope in the common main tree

### Native UI parity

Accepted #551–#571, #575 and shared #607 wiring are incorporated. This includes native month management/editor sections, Alfa and statement imports, payouts, IIS account forms, Goals/Tax/Scenario, allocation/concentration, selected-month monetary result and the complete native Close action/return/readiness/review/close/report/reopen route.

#570's common-source matrix is **CLOSED/COMPLETED**. D1 keeps monetary result by account/instrument class; D2 intentionally omits the old global historical/draft planning selector while preserving local context and historical facts. This is not permission to discard unrelated legacy functions.

`/` remains primary v2; `/v2` and native detail URLs remain valid. `/v1` and explicit legacy escape routes remain available. They share the same backend/database and do not constitute database rollback.

### Performance Phase A

Portfolio/account XIRR/TWRR detail, explicit history preparation, finite historical membership corrections, observed valuation capture, readiness diagnostics and stale/CLOSED/material-correction invalidation are incorporated. #641 refresh reconciles read-only readiness with #623 writer-reserving mutation guards and retains the real-backend preparation -> XIRR-only -> observed PRE/POST -> TWRR journey.

Unknown evidence remains unavailable, never fabricated. Existing allocation and monetary instrument-class tables are not class-specific returns. #535/#540 are deferred; #541 remains open for its separate later scope and actual real-history observations.

### Correctness and recovery

The post-Astra #484–#498 and #536–#539 wave is complete, including atomic financial writes, coherent reads, clone/correction/coverage guards and financial completeness. Later #621–#624 fixes are also in main. [Hardening closeout](DATA_INTEGRITY_HARDENING_CLOSEOUT_2026-09-27.md).

Owner durability #417 is complete: managed recovery points, pair-scoped retention, isolated DR and Windows disposition hardening, post-restore month reload, ambiguous restore handling and explicit plaintext synced-filesystem mode. #543 is accepted follow-up hardening, not a reopening of #417. [Durability closeout](OWNER_DURABILITY_CLOSEOUT_2026-09-25.md).

### Regression evidence

Accepted common-head CI `36676404532`: SUCCESS, 17 jobs; frontend 1023 passed, visual 249 passed / 78 intentional skips. UI comparison `36676404593`: 91 passed. Canonical CI actually ran G04/Performance 2, native import/readback 1 and Monthly Close/archive/reopen/restore 1 real-backend tests, zero retries. Synthetic fixture comparisons and Worker-local precursor runs remain separately labelled in [the manifest](UI_V2_AGGREGATE_VERIFICATION.md).

## Owner's next operation

One supported production update to **1.1.0**, then ordinary September-close use rather than duplicate full entry in a Preview copy. From an assigned trusted control checkout, use `scripts/update-stable.ps1` for exactly 1.1.0 with the known Stable and database paths. The operation verifies publication/current identity and backup before mutation, prepares/validates the target and stops. `scripts/start-local.ps1` is a separate explicit Start. No automatic update, runtime start or private-data access occurs from a GitHub merge.

Backup first. Verify version and continuity before entry. Check the real month/edit/save/return/readiness/close/report and Performance contexts; report actual PASS/FAIL/NOT TESTED, not private values or files. Do not invent PRE/POST observations or run destructive restore drills on the working DB.

#572 stays **OPEN** for the deferred actual Owner result; no remaining implementation is implied by that status. [Owner runtime operations](OWNER_RUNTIME_OPERATIONS.md) remain canonical. The older Preview runbook remains usable for isolated tests, but its compulsory pre-release sequence is superseded for this delivery by the explicit Owner exception.

## Remaining product directions — not launched

- #573: separate v1-retirement decision and later removal scope, after applicable evidence and explicit Owner authorization. Not a prerequisite for this release with v1 retained.
- #629: launcher removal/simplification work remains separate; direct runtime operations already work without it.
- #630: reusable representative synthetic testing/demo data, not access to Owner data.
- #535/#540: class-return evidence/contracts and implementation; no averaging or summing portfolio/account returns to invent classes.
- #389: configurable dashboard/report composition after current UI stabilization.
- #127, #528 and #554 remain coordinating umbrellas; #124 is permanent release infrastructure. No backlog task starts automatically from this list.

## Persistent invariants and historical foundations

Local single-user Windows-first application; only `127.0.0.1:8000`, local SQLite, no cloud/auth/telemetry/trading/background provider refresh. Money uses Decimal/integer-minor-unit contracts, CLOSED is immutable until explicit reopen, frontend is not financial truth. Owner data/.env/backups/credentials/exports never enter development workspaces. Provider calls remain explicit Owner actions.

Existing accepted foundations remain: Decision Support v1, Scenario Lab, deterministic Insights backend, Performance v1 and bounded account/internal-transfer decomposition, with no unsupported instrument/FX/realized attribution. Runtime responsibilities remain separated: Prepare/Validate, deterministic Start, exact Preview, explicit backup-first Stable update, guarded Release; launcher is only a shell.

Historical evidence: [Decision Support](DECISION_SUPPORT_V1_CLOSEOUT_2026-09-09.md), [Performance v1](PERFORMANCE_V1_CLOSEOUT_2026-09-12.md), [bounded decomposition](performance/PERF04B_COMPONENT_ATTRIBUTION_CONTRACT.md), [runtime v0.9.0](R09_RUNTIME_RELEASE_CLOSEOUT_2026-09-17.md), [v1.0.0 closeout](R10_RELEASE_CLOSEOUT_2026-09-21.md), [UI default switch](UI_V2_DEFAULT_SWITCH_CLOSEOUT_2026-09-21.md). Their historical Owner PASS is not copied to the new release.

Normative sources: `AGENTS.md`, `docs/MASTER_SPEC.md`, accepted ADRs, `docs/VERIFICATION_POLICY.md`, `docs/RELEASE_AUTOMATION.md`. Model attribution/history: `docs/MODEL_BENCHMARK.md` and #605.
