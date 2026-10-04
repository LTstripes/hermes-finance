# Finance Dashboard — Project Wiki

Durable Hermes Finance context, synchronized **2026-10-04**. Moving state belongs to live GitHub and [CURRENT_STATUS](CURRENT_STATUS.md). Latest restart brief: [SESSION_CLOSEOUT_2026-10-04](SESSION_CLOSEOUT_2026-10-04.md). Dated closeouts and [EXECUTION_HISTORY](EXECUTION_HISTORY.md) retain historical evidence, not standing orders.

## 1. Product

Local single-user Windows-first monthly finance application: explicit Monthly Close, liquid capital/debts/history, investment performance versus external flows, actual/forecast passive income, cash-flow ladder/redemptions, risk/allocation, freshness/provenance/reconciliation, Goals/Tax/IIS/Scenario and a read-only AI Analysis Bundle.

It is not a trading/banking/accounting/tax system and does not invent precision absent from authoritative evidence. SQLite and normal `127.0.0.1:8000` remain local. No cloud account/auth/telemetry/trading or automatic provider refresh. The filesystem janitor is housekeeping, not provider/data automation.

## 2. Sources and execution

Follow [AGENTS](../AGENTS.md): MASTER_SPEC → accepted ADRs → active accepted task/contract. Verification, risk/routing and integration retain their own procedure owners. Main is the only canonical/release source; integration branches are staging.

One writing/local-verification task owns one physical workspace. **Worker prompts are short launch pointers, normally 5–10 lines**, referencing the issue/latest note rather than repeating requirements. This is an explicit Owner preference, not an invitation to recreate the rulebook on each handoff. [MODEL_ROUTING](MODEL_ROUTING.md) owns prompt/routing procedure.

Independent review follows risk, not file count. Use targeted checks and actual exact-candidate CI without redundant full suites at every handoff. Normal handoffs do not request/persist model/provider identity, benchmark grades or telemetry; model selection is routing only.

## 3. Release and development identity

Published release: **v1.2.0**, source `8a0cb257da6ca6a661eb5044d0dd72dac28d90fc`, annotated tag object `f9311d26c1aae7295361937096844f4dde615b55`. Release CI `37206069556` and Guarded Release `37206660242` succeeded. [Release record](releases/1.2.0.md).

The last locally confirmed Stable remains v1.1.0. Owner authorized v1.2.0 and received backup-first OPS02 instructions; completion of local installation is not recorded here. Publication is not installation. Last reported Test pin remains `d282d09647f129cd83c99e14a10024901a1cf6da`.

Development code milestone after #701: `8ae9ead35d6a988cd2e4c8d967a04bc2c27825a4`, canonical CI `37226437369` SUCCESS. **Class-return Phase 1 is integrated after v1.2.0 and is not in that published release.** Later documentation commits may advance main; they do not promote Stable/Test or move the release tag.

v1.2.0 contains the accepted #662 product wave, #667/#674, maintenance #663/#664/#665/#672, #668–#671 CI work and #629 Launcher retirement. Prior v1.1.0 remains at `32c905cfc938fd1aeaeb67643eb6fa77e8644a64`. Historical transition records: [R10](R10_RELEASE_CLOSEOUT_2026-09-21.md), [R09](R09_RUNTIME_RELEASE_CLOSEOUT_2026-09-17.md), [v1.1.0](releases/1.1.0.md).

## 4. Financial and privacy invariants

Backend/domain is authoritative. Money/rates use Decimal and integer minor units. CLOSED months are immutable until explicit Reopen; unknown/unavailable is not zero. Redemption principal is not passive income. Capital change, investment return, unrealized snapshot and monetary bridge are different claims.

Stable/Test data, real .env, credentials, backups and private exports never enter Git/CI/development artifacts. Explicit local operations remain bounded; ordinary Workers do not gain runtime access. Frontend state never authorizes hidden financial writes, automatic mapping or background provider calls.

## 5. Delivered foundations

### Owner workflow and Decision Support

Monthly Close and native v2 parity are delivered: months/editing, reports/Reopen, imports/Preview/Apply/readback, settings/diagnostics and retained /v1. #570/#571/#643 and #572 are complete; Owner acceptance retains documented provider/manual limitations.

Decision Support v1 includes the AI bundle, Monthly Close Cockpit, Cash-flow Ladder, Risk & Allocation, Freshness & Provenance, Reconciliation, current-state Tax/IIS, deterministic Insights and Scenario Lab. Scenario is deterministic/read-only, not probabilistic forecasting. AI `schema_version=1.3.0` is independent of application version.

References: [Decision Support](DECISION_SUPPORT_V1_CLOSEOUT_2026-09-09.md), [UI completion](UI_V2_COMPLETION_CLOSEOUT_2026-09-20.md), [default switch](UI_V2_DEFAULT_SWITCH_CLOSEOUT_2026-09-21.md), [post-release UAT](POST_RELEASE_UAT_CLOSEOUT_2026-10-03.md).

### Portfolio/account Performance

XIRR, exact TWRR, cash/in-kind boundary coverage, external/internal flow reconciliation, valuation/membership guards and PERF04A `value_change_after_external_flows` are delivered. XIRR is annualized, TWRR covers the selected period; availability is independent. PRE/POST evidence is never fabricated. Phase A UI/preparation is complete; #541/#528 are closed for coordination. [Performance v1](PERFORMANCE_V1_CLOSEOUT_2026-09-12.md).

### Asset-class returns — Phase 1

#534's original BLOCK ON EVIDENCE was correct for its September baseline. Its accepted October amendment enabled metric-specific sequencing, not weaker precision. #696/#698/#535/#540 now deliver the first exact no-crossing capability for whole-portfolio RUB stock/bond/gold.

C1 uses persisted historical position identity, not current catalogue type; legacy NULL remains unknown. C2/C3 require explicit Owner no-crossing and both full endpoint inventory claims over the historical Performance account universe. Stored RUB market values, including existing accrued-interest semantics, are the valuation basis; mutable catalogue currency is not historical proof. Reopen/corrections revoke or invalidate dependent evidence.

The read-only API uses existing numerical primitives: two endpoint cash flows for XIRR and no boundaries for TWRR. Frontend Accounts/Classes view preserves dates/presets, zero/loss, independent metric states and safe provenance. Deposits are visible as unsupported. Numerical limits are not missing-data instructions.

**This is not complete automated class history.** Purchases/sales/distributions, deposits, FX and flow-bearing TWRR remain outside Phase 1. A class-attestation UI and automatic legacy C1 repair are not delivered. The current screen reads existing evidence; a visible table does not promise percentages on personal history. Owner UAT is still pending.

Sources: [class contract](performance/ASSET_CLASS_RETURNS_CONTRACT.md), [C1](performance/POSITION_CLASS_IDENTITY.md), [endpoint evidence](performance/CLASS_NO_CROSSING_ENDPOINTS.md), [API](performance/CLASS_RETURNS_API.md).

### Component attribution remains separate

#396/#400/PR #402 accepted a backend-only identity:

```text
B_portfolio = Σ B_account + Σ T_internal_transfer
```

B is the existing monetary bridge, not return/profit/P&L. No partial exact split or residual bucket. `100 -> 99` without accepted reconciliation remains unavailable; S>D needs transfer fee/commission/tax evidence; D>S remains unavailable. Same-currency FX spread alone does not authorize T; cross-currency gaps remain unavailable. API/UI exposure is a separate decision.

Class XIRR/TWRR does not implement additive class contributions, causal/price-vs-FX attribution, lots or realised/unrealised attribution. [PERF04B contract](performance/PERF04B_COMPONENT_ATTRIBUTION_CONTRACT.md).

### Integrity and recovery

#484–#498/#536–#539 and #621–#624 preserve atomic writes, coherent reads, statement/transfer/salary/month-clone conflict handling, source coverage and stale-evidence invalidation. Missing accounts are not zero-filled. [Integrity closeout](DATA_INTEGRITY_HARDENING_CLOSEOUT_2026-09-27.md).

#417's managed recovery publication/read-back, bounded retention, isolated DR and truthful outcomes are complete, including later #543/#547 CLI/retention hardening. Encrypted and separately Owner-accepted plaintext synced-filesystem modes remain distinct; a synchronized folder is not automatically encrypted or proven off-device. [Durability closeout](OWNER_DURABILITY_CLOSEOUT_2026-09-25.md).

## 6. Runtime and housekeeping

#679/#666 migration/legacy cleanup and janitor deployment are COMPLETE. Do not restart inventory/migration/restore/client setup because old notes say BLOCKED. Portable roles are `stable`, `main`, `test`, `owner`, `workspaces/<client>/<task>`; absolute roots stay local. Control is Main; Preview is persistent Test.

The separate **active Ops installation outside the Hermes root** is protected. Outside-root is not deletion permission. [Machine layout](OWNER_MACHINE_LAYOUT.md) owns the map.

Direct operations: OPS01 Prepare/Validate, deterministic `start-local.ps1`, OPS02 backup-first published-release update, OPS03 exact-SHA Test preparation. #124 guarded publication is separate from installation/Start. Only one owned runtime uses port 8000. Do not make Stable follow main.

Installed and repository Launcher removal is complete. Shared backup/update/recovery/RuntimeConfig protections remain; do not reinstall the shell. Direct inventory inputs are defined in [OWNER_RUNTIME_OPERATIONS §13](OWNER_RUNTIME_OPERATIONS.md#13-protected-off-site-recovery-points-and-dr-rehearsal) and [the example](runtime-inventory.example.json). #313 redesign and earlier Launcher experiments are historical.

Janitor schedule: daily 12:00 local, Apply, retention 7 days, fixed client roots. Young/active/dirty/private/unknown/unique work is preserved. Deployment plus 8-PRESERVE/0-delete dry-run are recorded, not a guarantee of first scheduled deletion. [Janitor](WORKSPACE_JANITOR.md).

## 7. Next work

**#702 is the next selected read-only research task:** actual statement sources/coverage, minimal class-boundary events and a proposed statement-backed XIRR path for one report family. It is independent of docs and Owner UAT. No implementation is authorized by research completion; the next Integrator reviews the proposal first.

Owner plans UAT tomorrow or in the next few days; development need not wait. The class screen requires an exact post-#701 candidate, not v1.2.0. The missing evidence-entry/legacy-identity UI needs an explicit product path, not Owner SQL/JSON/PowerShell chores. Do not repeat the full #662 UAT.

#646: the Trading core UI can be switched Online on 3366 and a read-only token exists, but Hermes still reports unrecognized protocol. A token handshake is a hypothesis, not established wire evidence. Owner chose a several-day/about-week wait before support; Alfa is optional for statement research. No provider fix or automatic monitoring is claimed.

#389 composer is deferred; #124/#554 are permanent release/coordination endpoints. #630/#573/#127 are closed not-planned and /v1 stays. CI optimization #668–#671/#629 is complete; #691 was NO-GO with no delivery. Other optional test/cleanup pilots are not an active queue. [CI/test closeout](history/CI_TEST_OPTIMIZATION_CLOSEOUT_2026-10-04.md).

Latest restart brief: [SESSION_CLOSEOUT_2026-10-04](SESSION_CLOSEOUT_2026-10-04.md). Historical documents retain their dated facts rather than being rewritten as current evidence.
