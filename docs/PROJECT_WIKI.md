# Finance Dashboard — Project Wiki

Durable Hermes Finance context, synchronized **2026-10-03**. Current moving state belongs to GitHub and [CURRENT_STATUS](CURRENT_STATUS.md). Detailed milestones remain in [EXECUTION_HISTORY](EXECUTION_HISTORY.md), dated closeouts and Git history. This page is not a second task specification or a store for personal financial data.

## 1. Product

Local single-user Windows-first monthly finance application: explicit Monthly Close, liquid capital/debts/history, investment performance versus external flows, actual versus forecast passive income, cash-flow ladder/redemptions, risk/allocation, freshness/provenance/reconciliation, Goals/Tax/IIS/Scenario, and a read-only AI Analysis Bundle.

It is not a trading/banking/accounting/tax system and does not invent precision absent from authoritative evidence. SQLite and normal `127.0.0.1:8000` remain local. No cloud account/auth/telemetry/trading or automatic provider refresh. A scheduled filesystem janitor is housekeeping, not a new data/provider automation.

## 2. Sources and execution

Follow [AGENTS](../AGENTS.md): MASTER_SPEC → accepted ADRs → active accepted issue/contract. Verification, risk/routing and integration have their own linked policy owners. Live GitHub main is the only canonical/release source; integration branches are staging, never alternate mains.

One writing/local-verification task owns one physical workspace. Short prompts locate the issue and baseline; do not copy a second specification. Independent review follows risk, not file count. Use targeted checks plus actual exact-candidate CI without repeating full suites at every handoff. Normal handoffs no longer request model/provider evidence, benchmark grades or telemetry (#669/#605 decision). Model choice remains a routing recommendation.

## 3. Release and development identity

Published/local Stable is **v1.1.0**, source `32c905cfc938fd1aeaeb67643eb6fa77e8644a64`, annotated tag object `9b402190bafc5d8415b217580da5e18ed35a6331`. Release push CI `36776904188` and Guarded Release `36777962224` succeeded. #572 is Owner PASS WITH DOCUMENTED LIMITATIONS, not universal provider or real-history returns availability.

Development main includes the post-release #662 six-slice product wave, #663/#664/#665 maintenance, #672/#674 follow-ups, #680 migration tooling, #684 layout closeout, #685 janitor, and the merged #671/#668/#669 test optimizations. Checkpoint before this docs sync: `8eb991fc81ebbe63917a9ca1ea204762129c9019`, main CI `37150791634` SUCCESS. It is not a new release and does not promote local Stable.

Historical v1.0.0 remains at `caf4fdad99cc02f5bc171ec3b1d726b8516ad45e`, tag object `f99ee8ecac1acde7f559d92ee8f45ddcfcdfaa47`. Historical v0.9.0 and the accepted release-transition evidence are unchanged: [R10](R10_RELEASE_CLOSEOUT_2026-09-21.md), [R09](R09_RUNTIME_RELEASE_CLOSEOUT_2026-09-17.md), [v1.1.0](releases/1.1.0.md).

## 4. Financial and privacy invariants

Backend/domain is authoritative. Money/rates use Decimal/integer minor units, not binary-float financial semantics. CLOSED months are immutable until explicit reopen. Unknown/unavailable is not zero. Redemption principal is not passive income; capital change, investment return, unrealized snapshot and monetary bridge are different values.

Stable/Test data, real .env, credentials, backups and private exports never enter Git/CI/development artifacts. The explicitly authorized local-operations exception is bounded; it does not grant ordinary Workers unrestricted runtime access. Frontend state never authorizes hidden financial writes, auto-mapping or background provider calls.

## 5. Delivered foundations

### Owner workflow and Decision Support

Monthly Close and native v2 parity are delivered, including month management/editing, reports/reopen, imports/explicit Apply/readback, settings/diagnostics and the retained /v1 fallback. #570/#571/#643 and #572 are complete.

Decision Support v1 includes AI Analysis Bundle, Monthly Close Cockpit, Cash-flow Ladder, Risk & Allocation, Freshness & Provenance, Reconciliation, current-state Tax/IIS, deterministic Insights and Scenario Lab. Scenario is deterministic/read-only, not probabilistic forecasting. AI `schema_version=1.3.0` is independent of application 1.1.0.

References: [Decision Support](DECISION_SUPPORT_V1_CLOSEOUT_2026-09-09.md), [UI completion](UI_V2_COMPLETION_CLOSEOUT_2026-09-20.md), [default switch](UI_V2_DEFAULT_SWITCH_CLOSEOUT_2026-09-21.md).

### Performance

Portfolio/account XIRR, exact TWRR, cash-boundary coverage, external/internal flows, transit/transfer reconciliation, valuation/membership/in-kind guards and PERF04A `value_change_after_external_flows` are delivered. XIRR is annualized; TWRR is for the selected period. Availability is metric-specific. Real PRE/POST history cannot be fabricated to turn an unavailable rate into an exact one.

Phase A portfolio/account UI and data preparation are delivered. #541 retains remaining verification/Phase B scope. #535/#540 class returns are not inferred from allocation or money-result class tables. [Performance v1 closeout](PERFORMANCE_V1_CLOSEOUT_2026-09-12.md).

### Component attribution boundary

#396 accepted PARTIAL GO; #400/PR #402 implemented the backend-only identity:

```text
B_portfolio = Σ B_account + Σ T_internal_transfer
```

B is the existing money bridge, not return/profit/P&L. No partial exact split or residual bucket is allowed. `100 -> 99` without accepted reconciliation evidence remains unavailable; S>D needs transfer-specific fee/commission/tax evidence; D>S remains unavailable. Same-currency FX-spread alone does not authorize T, and cross-currency gaps remain unavailable. API/UI exposure is a separate decision.

Instrument/class, price-vs-FX, realised/unrealised, lots/cost basis, causal attribution and additive XIRR/TWRR contributions require their own accepted evidence. [Canonical contract](performance/PERF04B_COMPONENT_ATTRIBUTION_CONTRACT.md).

### Integrity and recovery

#484–#498/#536–#539 and later #621–#624 preserve atomic financial writes, coherent reads, statement/transfer/salary/month-clone conflict handling, source provenance/coverage, real cash identity, and Performance evidence invalidation. Missing accounts are not zero-filled. #509 closeout remains accepted at `b6f3ff1aff93f06ae0a563ba8704b91086a80924`, main CI `36306845860` SUCCESS. [Integrity closeout](DATA_INTEGRITY_HARDENING_CLOSEOUT_2026-09-27.md).

#417 is complete: #459 managed recovery publisher, #460 per-protection-pair retention, #461 isolated DR plus Windows fixes, #462 read-state reload, #475 truthful ambiguous restore outcomes, #511/#524 Owner-found recovery fixes, and #527 explicit plaintext synced-filesystem mode. The actual Owner publication/off-device visibility/isolated DR passed; #543/PR #547 later hardened CLI/retention without reopening #417. [Durability closeout](OWNER_DURABILITY_CLOSEOUT_2026-09-25.md).

## 6. Current runtime and folder roles

#679/#666 are CLOSED COMPLETE. The operational result is already accepted: Stable/Main/persistent Test moved, production continuity/readiness preserved, legacy remnants removed, local Launcher removed, janitor deployed. Do not restart migration because older reports say BLOCKED/STOPPED.

Portable names: `stable`, `main`, `test`, `owner`, `workspaces/<client>/<task>`. Control is the Main role; Preview is the Test role. Absolute roots stay in Owner-local configuration. The [machine-layout document](OWNER_MACHINE_LAYOUT.md) is the single role-map authority, including the **separate active Ops installation outside the Hermes root**. Outside-root location alone is not deletion permission.

Direct composable operations remain:

- OPS01: `scripts/prepare-runtime.ps1` Prepare/Validate;
- deterministic Start: `scripts/start-local.ps1`;
- OPS02: `scripts/update-stable.ps1`, explicit backup-first immutable release transition;
- OPS03: `scripts/prepare-preview.ps1`, exact-SHA isolated Test preparation;
- publication: guarded #124, separate from local update/Start.

A moved Windows Python environment may retain old interpreter paths; recreate its generated environment/entry points with the exact release's supported locked preparation without rewriting the production DB. Stable remains the published release, not whatever is currently main.

Local Launcher/config/shortcuts have been deleted and repository Launcher
source/package/tests/jobs are retired by #629. Do not reinstall the shell as
a prerequisite. Shared backup-first update, prepared-runtime, recovery and
`RuntimeConfig` identity/exclusion helpers were preserved; recovery and cleanup
exclusion inputs use the direct-operations runtime inventory defined in
[OWNER_RUNTIME_OPERATIONS §13](OWNER_RUNTIME_OPERATIONS.md#13-protected-off-site-recovery-points-and-dr-rehearsal)
([example](runtime-inventory.example.json)). Earlier #298/#311/#312 self-update
and #585/#586 compact-shell details are historical, not a new development direction.

[Owner runtime operations](OWNER_RUNTIME_OPERATIONS.md) contain current commands and recovery boundaries. #313 composable-runtime redesign remains complete.

## 7. Housekeeping

The Finance janitor from #685 runs daily at 12:00 local, Apply, retention 7 days, against the fixed four client roots only. Active/young/dirty/private/wrong-origin/unknown or unique local work is preserved. Accepted generated-cache and no-follow guards remain; arbitrary ignored material is not disposable by name.

Deployment read-back and one dry-run passed: 8 preserved, 0 removed. The first scheduled deletion has not been observed in this closeout. [Janitor contract/deployment](WORKSPACE_JANITOR.md). The one-time #679 permission to discard identified legacy history is not standing authority to delete future unknown folders, Ops, external recovery destinations or other projects.

## 8. Next work, not an automatic queue

The post-release six-slice wave is accepted, not a task list to repeat. #667 code is integrated, but no later focused Owner retest is invented. Historical quote PASS is not live #645 same-day LAST evidence. #646 remains a separate Alfa transport question.

The parallel test stream has merged #671/#681 concurrency, #668/#682 fixed-viewport deduplication, #669/#683 exact-head evidence deduplication and #670 docs-only fast path. #629 retires the Launcher CI jobs on top of that fast path and keeps full canonical main/release gates. Recheck live ownership before changing workflows further.

Recommended next technical candidate after #629 is one frozen Test refresh for the remaining narrow Owner checks if selected. Deferred: #630 representative fixture, SQLite date-binding warnings, OpenAPI/pyright pilots, branch inventory, #535/#540 class returns and #389 composer. #573 /v1 retirement is not authorized. #124 is permanent infrastructure; #127/#528/#554 coordinate decisions.

Full restart brief and source evidence: [SESSION_CLOSEOUT_2026-10-03](SESSION_CLOSEOUT_2026-10-03.md). Dated historical documents retain their original evidence; they do not supersede later accepted results.
