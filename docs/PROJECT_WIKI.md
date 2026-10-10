# Finance Dashboard - Project Wiki

Durable product and execution concepts. [CURRENT_STATUS](CURRENT_STATUS.md) is the maintained project checkpoint;
live task issues and accepted Integrator notes own assignments. [#554](https://github.com/LTstripes/hermes-finance/issues/554)
is the coordination entrypoint. Dated closeouts and [EXECUTION_HISTORY](EXECUTION_HISTORY.md) retain historical evidence,
not a second live work order. Edit this Wiki when its meaning changes, not to copy a new SHA, CI run or task priority.

## Product and execution

Hermes is a local single-user Windows finance app for laptop/desktop browsers. Ordinary window sizing, zoom and keyboard
remain supported; phone design/UAT is outside the product target. SQLite and the normal loopback endpoint stay local.
No cloud account/auth/telemetry/trading or automatic provider refresh follows from ordinary development.

[AGENTS](../AGENTS.md) owns shared authority and isolation; MASTER_SPEC → accepted ADRs → active accepted contract
is product precedence. One Worker owns one physical task checkout. The issue/note holds acceptance criteria;
short launch prompts locate it. [MODEL_ROUTING](MODEL_ROUTING.md) owns risk and review;
[VERIFICATION_POLICY](VERIFICATION_POLICY.md) owns proportional checks and evidence reuse.
Required independent review, project acceptance and Owner UAT remain separate from green CI.
[AGENT_ORCHESTRATION](AGENT_ORCHESTRATION.md#linked-handoff-receipts) owns linked handoffs and authorized integration.

## Release and runtime identity

Canonical main, published release, installed Stable and persistent Test are different identities.
A main merge does not install software, migrate a protected database, refresh Test or move a release tag.
Exact-candidate PR CI and exact-main push CI prove their own candidates; local runtime/data continuity needs its own evidence.
Published-release records live in [releases](releases/1.2.0.md); current identities and remaining gates live in CURRENT_STATUS.
Export schema versions are independent of application versions.

## Financial truth and Owner data

Backend/domain is authoritative. Money/rates use Decimal and integer minor units. CLOSED months need explicit Reopen for
corrections. Unknown is not zero; redemption principal is not passive income. Capital change, investment return,
unrealized valuation and the monetary bridge are different quantities.

[OWNER_DATA_WORKFLOW](OWNER_DATA_WORKFLOW.md) defines authorized reads/presentation and separate write/runtime/publication
boundaries. Relevant Owner-requested reads and ordinary private UAT screenshots do not require repeated per-value approval.
Credentials stay out of outputs; real datasets/.env/SQLite/sidecars/backups/broker exports stay out of tracked code and CI.
Automated tests use synthetic data. This general workflow never supplies authority missing from a task's explicit bounds.

## Delivered foundations and financial boundaries

### Owner workflow and Decision Support

Monthly Close and native v2 months/editor/reports, import Preview→Apply→readback, settings, diagnostics and explicit v1 escape
are delivered. Prior Owner acceptance has documented limitations; each UI patch does not require repeating the entire route.
Decision Support includes AI review exports, cash-flow ladder, risk/allocation, freshness, reconciliation, Tax/IIS,
insights and deterministic Scenario Lab.

References: [Decision Support](DECISION_SUPPORT_V1_CLOSEOUT_2026-09-09.md),
[UI completion](UI_V2_COMPLETION_CLOSEOUT_2026-09-20.md), [default switch](UI_V2_DEFAULT_SWITCH_CLOSEOUT_2026-09-21.md),
[post-release UAT](POST_RELEASE_UAT_CLOSEOUT_2026-10-03.md).

### Account/portfolio and historical Performance

Performance includes XIRR, exact TWRR, external/internal flows, cash/in-kind coverage, valuation/membership evidence
and a separate monetary bridge. XIRR is annualized; TWRR covers the selected period and needs appropriate PRE/POST boundaries
when flows occur. Availability is independent. [Performance closeout](PERFORMANCE_V1_CLOSEOUT_2026-09-12.md).

`services/portfolio_xirr.py` tries the accepted monthly path before historical H1/H2 fallback.
Do not combine incompatible endpoints or count both imported and existing representations of one fact.
Parsed source fidelity, arithmetic and successful import do not establish complete accepted return inputs.
A private reference is distinct from the same source-backed numeric result in Hermes API/UI.

Archived Skip is not cleared by age, current holdings or a shorter interval. Prior exact source-account alias decisions
remain reusable, not a generic suffix heuristic. Catalogue/mapping preparation and append-only correction are separate actions;
accepted Skip→Map requires fresh Preview against post-preparation revisions, immutable original evidence and independent readback.
Eligibility does not automatically grant endpoint, cash-flow, fee, membership or completeness claims.
[Disposition contract](MYBROKER_INSTRUMENT_DISPOSITIONS.md) and the active accepted correction contract own these details.
No research or UX authorization supplies financial attestation authority.

### Class returns

The first exact subset is no-crossing whole-portfolio RUB stock/bond/gold. Historical position C1 is not current catalogue type.
Class-wide endpoint inventory and interval no-crossing are separate explicit evidence; legacy unknown remains unknown.
No-crossing XIRR uses two endpoint flows; TWRR uses its no-boundary path. General crossings, deposits/savings, FX and
flow-bearing class TWRR are not universally supported. Preparation UI does not populate evidence automatically.
CLOSED/revision/material invalidation remain guarded.

Contracts: [class returns](performance/ASSET_CLASS_RETURNS_CONTRACT.md), [historical C1](performance/POSITION_CLASS_IDENTITY.md),
[C2/C3](performance/CLASS_NO_CROSSING_ENDPOINTS.md), [API](performance/CLASS_RETURNS_API.md).

### Attribution, integrity and recovery

PERF04B's backend identity remains `B_portfolio = Σ B_account + Σ T_internal_transfer`.
B is not return/profit/P&L; no fabricated residual or exact decomposition from insufficient transfer evidence.
Lots, causal price/FX attribution and additive class contributions are separate. [Contract](performance/PERF04B_COMPONENT_ATTRIBUTION_CONTRACT.md).
Atomic writes, coherent reads, source/transfer/month-clone conflicts and stale-evidence invalidation remain required.
Missing accounts are not zero-filled. [Integrity closeout](DATA_INTEGRITY_HARDENING_CLOSEOUT_2026-09-27.md).

Managed recovery retains encrypted and explicitly accepted plaintext/synced-filesystem modes, bounded retention,
separate restore rehearsal and truthful local/off-device evidence. A synchronized directory is not automatically encrypted
or proven off-device. [Durability closeout](OWNER_DURABILITY_CLOSEOUT_2026-09-25.md).

## Runtime and housekeeping

Portable roles are Stable/Main/Test/Owner and client task workspaces. Preserve active Ops, backups and other tasks.
Historical relocation, cleanup and Launcher retirement do not authorize new inventory, deletion or client reconfiguration.
[Layout](OWNER_MACHINE_LAYOUT.md) owns the map; [runtime operations](OWNER_RUNTIME_OPERATIONS.md) own supported operations.

Prepare/Validate, Start, backup-first release-pinned OPS02 and exact-SHA Test OPS03 remain distinct operations.
Only one runtime owns port 8000; identify the owned runtime instead of killing by port. Interactive stop is Ctrl+C in
its owning console; `start-local.ps1` may perform forced child cleanup. Never copy Test DB back into Stable.
Guarded publication is separate from local update/Start.

The [janitor](WORKSPACE_JANITOR.md) preserves young/active/dirty/private/unknown work. Its dated deployment/dry-run
does not prove future deletion outcomes. [CI history](history/CI_TEST_OPTIMIZATION_CLOSEOUT_2026-10-04.md) retains measured
deliveries; new work needs its current assignment, not a historical queue.
