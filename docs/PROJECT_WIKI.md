# Finance Dashboard — Project Wiki

Durable context updated **2026-10-09**. Moving identities, results and pending actions belong to [CURRENT_STATUS](CURRENT_STATUS.md), live GitHub and [#554](https://github.com/LTstripes/hermes-finance/issues/554). Restart from [SESSION_CLOSEOUT_2026-10-09](SESSION_CLOSEOUT_2026-10-09.md). Earlier closeouts and [EXECUTION_HISTORY](EXECUTION_HISTORY.md) preserve dated evidence, not standing assignments.

## Product and current outcome

Local single-user personal finance application on a Windows laptop: Monthly Close, liquid capital/debts/history, investment performance versus external flows, actual/forecast passive income, future cash flows, risk/allocation, source reconciliation, Goals/Tax/IIS/Scenario and read-only exports. SQLite and normal `127.0.0.1:8000` remain local. No trading, cloud account/auth, telemetry or automatic provider refresh.

**Desktop-only:** Owner decision #746 excludes phone UI, 390px/mobile design and mobile Owner UAT. Normal laptop resizing, keyboard/focus and browser zoom remain important. Owner now requests physical removal of obsolete mobile-only tests/fixtures/checks in **#747, first implementation priority**, not merely a policy note. Preserve unique financial scenarios on desktop; do not delete shared assertions or production CSS blindly. [Master Spec](MASTER_SPEC.md#52-среда-запуска), [verification](VERIFICATION_POLICY.md#12-ui-платформа-и-визуальная-приёмка).

**Financial priority:** first independently verified account XIRR on one short real brokerage interval, initially 2026-08-31→2026-09-30, through #749 under #709. A displayed empty table, source import or green test is not that result. The broader two-year reconstruction and class/TWRR extensions follow a proven first account outcome.

## Execution and authority

Follow [AGENTS](../AGENTS.md): MASTER_SPEC → accepted ADRs → active contract; [integration](AGENT_ORCHESTRATION.md), [verification](VERIFICATION_POLICY.md) and [routing](MODEL_ROUTING.md) retain their own responsibilities. Main alone is canonical/releasable. One accountable writer and one physical task workspace; no sibling-tree edits. Integrator performs authorized GitHub review/merge/status mechanics directly. Required independent review is a separate assessment, not a compulsory repeat of every test.

Worker launch prompts are short (normally 5–10 lines), pointing to a real issue. Difficulty/model/effort are route choices, not Model evidence, provider logging or model benchmarks. Simple Owner-local actions should be supplied as brief PowerShell commands instead of starting Codex for a trivial step. Permission errors are not execution; never bypass safety or loop indefinitely on the same failure.

One heavyweight local verification process at a time, including other projects. #747 code/test cleanup can run alongside #749's narrowly read-only financial input preparation, not alongside another full-suite process. #748 starts after #747 merge. #744 is frozen awaiting desktop UAT; Integrator reconciles its shared visual-test file once, retaining new desktop assertions without resurrecting removed mobile variants.

## Release and runtime identity

Published **v1.2.0** resolves to `8a0cb257da6ca6a661eb5044d0dd72dac28d90fc`; [release record](releases/1.2.0.md). Later preflight confirmed the Owner's Stable checkout at that code SHA, but a separate production Start/health/data-continuity completion record is not established. Do not repeatedly claim only v1.1.0 is installed or make a declined standalone version check an active Owner chore.

Development main includes post-v1.2.0 class evidence/UI, S1/S2, H0–H3, #740 REPO/Skip, #741 H0 speed, #745 screenshot policy and #746 desktop scope. Main merges are not local deployments. Current pending UX PR is #744; its exact Test pin and CI/UAT distinction are in CURRENT_STATUS. Do not assume the protected Test follows main.

v1.2.0 contained #662's accepted product wave and follow-ups, CI maintenance and #629 Launcher retirement. Earlier [R10](R10_RELEASE_CLOSEOUT_2026-09-21.md), [R09](R09_RUNTIME_RELEASE_CLOSEOUT_2026-09-17.md) and [v1.1.0 record](releases/1.1.0.md) are historical. Export schema versions are independent of application release versions.

## Financial truth and privacy

Backend/domain is authoritative. Money/rates use Decimal and integer minor units. CLOSED months require explicit Reopen for corrections. Unknown is not zero; redemption principal is not passive income; capital change, investment return, unrealized valuation and the monetary bridge are different quantities.

Credentials, real .env, full SQLite/sidecars/backups and original broker exports do not belong in code clones, public Git or CI. **Authorized real Test UI screenshots with ordinary finance values may be viewed by the local UAT agent and private assistant through normal tools** under #745/AGENTS. No special viewer or repeated monetary-redaction approval gate. Do not automatically publish them publicly. Runtime/financial-write permission is separate from screenshot inspection.

## Delivered foundations and remaining financial boundaries

### Owner workflow and Decision Support

Monthly Close and native v2 months/editor/reports, import Preview→Apply→readback, settings, diagnostics and explicit v1 escape are delivered. #572 Owner acceptance has documented limitations; no repeat of the entire completed workflow is required for each UI patch. Decision Support includes AI review exports, cash-flow ladder, risk/allocation, freshness, reconciliation, Tax/IIS, insights and deterministic Scenario Lab.

References: [Decision Support](DECISION_SUPPORT_V1_CLOSEOUT_2026-09-09.md), [UI completion](UI_V2_COMPLETION_CLOSEOUT_2026-09-20.md), [default switch](UI_V2_DEFAULT_SWITCH_CLOSEOUT_2026-09-21.md), [post-release UAT](POST_RELEASE_UAT_CLOSEOUT_2026-10-03.md).

### Account/portfolio and historical Performance

Existing Performance includes XIRR, exact TWRR, external/internal flows, cash/in-kind coverage, valuation/membership evidence and a separate monetary bridge. XIRR is annualized; TWRR covers the selected period and requires appropriate PRE/POST boundaries when flows occur. Their availability is independent. [Performance closeout](PERFORMANCE_V1_CLOSEOUT_2026-09-12.md).

`services/portfolio_xirr.py` first uses the ordinary accepted monthly availability path, then historical H1/H2 fallback. Do not demand new historical records for every selected monthly interval without checking which path is applicable. Do not combine incompatible sides or count both imported and existing representations of one fact.

#740 source import/Skip diagnostics and #741 H0 inventory-speed UAT passed on protected Test. A subsequent no-write audit found no numeric discrepancy in its checked source/ledger facts, but every sampled real return remained unavailable. That is not an unimplemented solver; missing accepted financial inputs and independent source barriers remain. #749 must identify exact present/unaccepted/missing facts for one account and prepare a source-bound acceptance package, not repeat the whole audit.

Relevant archived Skip is not cleared by age, current holdings, a shorter interval or merely creating an instrument. Exact prior source-account alias decisions remain reusable, not a general suffix heuristic. Skip→Map and same-account non-impact require a separately accepted correction/proof route. #715's existing S2-B fee/event contract should be reused only where it actually blocks the selected account. No autonomous financial attestation follows a research/UX authorization.

### Class returns

#696/#698/#535/#540 introduced the first exact no-crossing whole-portfolio RUB stock/bond/gold subset under the amended #534 contract. Historical position C1 is not current catalogue type. Class-wide endpoint inventory and interval no-crossing are separate explicit evidence; legacy unknown remains unknown. No-crossing XIRR uses two endpoint flows and TWRR uses its no-boundary path. General crossings, deposits/savings, FX and flow-bearing class TWRR are not universally supported.

#705/#706 added bounded C1/no-crossing preparation UI; #743/#744 improve its usability but do not populate evidence or compute returns. Endpoint assertions may deliberately remain true with unknown/revoked interval coverage without making rates available. CLOSED/revisions/material invalidation stay guarded.

Contracts: [class returns](performance/ASSET_CLASS_RETURNS_CONTRACT.md), [historical C1](performance/POSITION_CLASS_IDENTITY.md), [C2/C3](performance/CLASS_NO_CROSSING_ENDPOINTS.md), [API](performance/CLASS_RETURNS_API.md).

### Attribution, integrity and recovery

PERF04B's backend identity remains `B_portfolio = Σ B_account + Σ T_internal_transfer`. B is not return/profit/P&L; no fabricated residual, rate summation or exact decomposition from insufficient transfer evidence. Lots, causal price/FX attribution and additive class contributions are separate. [Contract](performance/PERF04B_COMPONENT_ATTRIBUTION_CONTRACT.md).

Atomic writes, coherent reads, source/transfer/month-clone conflicts and stale-evidence invalidation remain required. Missing accounts are not zero-filled. [Integrity closeout](DATA_INTEGRITY_HARDENING_CLOSEOUT_2026-09-27.md).

Managed recovery retains encrypted and explicitly accepted plaintext/synced-filesystem modes, bounded retention, separate restore rehearsal and truthful local/off-device evidence. A synchronized directory is not automatically encrypted or proven off-device. [Durability closeout](OWNER_DURABILITY_CLOSEOUT_2026-09-25.md).

## Runtime and housekeeping

#679/#666 relocation/legacy cleanup and janitor deployment, #629 Launcher retirement and #313 runtime separation are complete. Preserve Stable/Main/Test/Owner, active Ops (including its separate outside-root installation), backups and other tasks. Do not repeat inventory/migration or delete workspaces because an old note says BLOCKED. [Layout](OWNER_MACHINE_LAYOUT.md).

Use supported Prepare/Validate, Start, backup-first release-pinned OPS02 and exact-SHA Test OPS03. Only one runtime owns port 8000; identify the owned runtime instead of killing by port. The documented interactive stop is Ctrl+C in its owning console; `start-local.ps1` can perform forced child cleanup, so do not label every stop purely graceful. A private old helper name is not proof of safe behavior.

#124 guarded publication remains separate from local update/Start. Never copy Test DB back into Stable. RuntimeConfig/example and [runtime operations](OWNER_RUNTIME_OPERATIONS.md) remain governing procedures; old dated release pins therein are historical.

The [janitor](WORKSPACE_JANITOR.md) has a recorded daily 12:00 local schedule, retention 7 days and preservation of young/active/dirty/private/unknown work. Prior deployment/dry-run evidence is not a guarantee of future deletions. Existing CI optimization history is complete except the newly Owner-prioritized #747 mobile cleanup; #691 remains NO-GO, not an invented delivery.

## Remaining backlog and resumption

#747 first; #749's one-account financial work alongside it; #748 account-row display after #747; #744 desktop UAT/integration remains separate. #709 stays OPEN until actual real financial acceptance. #711/#714 are future source-first expansion, #646 awaits a supported Alfa token contract (no guessed protocol/provider calls), #389 composer deferred. #124/#554 are operational control/coordination; /v1 remains intentional.

See [CURRENT_STATUS](CURRENT_STATUS.md) for exact SHAs, CI versus local UAT and Owner actions, and [2026-10-09 checkpoint](SESSION_CLOSEOUT_2026-10-09.md) before resuming. Nothing in this documentation authorizes a release, Stable update, database mutation or implicit financial confirmation.
