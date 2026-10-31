# AGENTS.md — Hermes Finance

Read the current issue and latest applicable accepted Integrator notes, then only the five-book sections needed for this task.

- Product/user journey: [P](docs/MASTER_SPEC.md).
- Financial/data/API/source authority: [C](docs/ARCHITECTURE_AND_CONTRACTS.md).
- Roles/risk/scope: [D1](docs/DEVELOPMENT.md#d1); workspace/bootstrap: [D2](docs/DEVELOPMENT.md#d2); implementation: [D3](docs/DEVELOPMENT.md#d3); checks/review: [D4](docs/DEVELOPMENT.md#d4); delivery/document maintenance: [D5](docs/DEVELOPMENT.md#d5); optional client mechanics: [D6](docs/DEVELOPMENT.md#d6).
- Runtime/release/backup/recovery: [O](docs/OWNER_RUNTIME_OPERATIONS.md).
- Current code/release/installed/UAT/next decisions: [S](docs/CURRENT_STATUS.md), the only changing status document.

<a id="roles"></a>
## Roles and critical boundaries

Owner decides product direction/private UAT; Integrator owns acceptance and authorized integration; Worker owns one candidate without self-acceptance; Reviewer independently assesses it without implementation ownership. Tool access is not authority.

Hermes is a local single-user Windows app, loopback by default. Financial logic uses Decimal, integer minor units and ROUND_HALF_UP, never binary float. CLOSED months require explicit Reopen. Frontend is not financial authority. Preserve UNKNOWN/NULL/zero distinctions, source/receipt/currentness/writer/Close boundaries in C.

User-facing screens lead with useful numbers, graphs and actions. Keep technical
provenance and codes out of the ordinary path; explain a material gap once in
plain language. Do not repeat caveats or render empty blocks. An instrument has
its own page with on-entry loading and a return to the previous filters. P owns
the detailed product rules; green checks never imply Owner UX acceptance.

Owner-requested relevant data reads and ordinary presentation follow D1; secrets never enter output, real payloads never enter tracked code/CI. Reads do not authorize data writes, runtime operations or publication. Task-specific restrictions take precedence.

<a id="default-execution-mode"></a><a id="task-prompt-authority"></a>
## Scope

Default one accountable Worker completes the assigned result. Routine reversible implementation choices proceed; stop only at a concrete contract/authority failure or material scope expansion (D1). No implicit queue or model accounting.

<a id="sync-before-a-new-task"></a><a id="one-writer-isolated-task-branch"></a>
<a id="parallel-task-isolation--physical-workspace-invariant"></a>
## Workspace

Fetch/pin authorized baseline. One active writer/local verification task owns one physical checkout under its configured client root. Self-create one fresh unique task checkout under known standing authority; never switch/reset/clean siblings or runtime roots. Use installed lifecycle Create/Bind/CheckActive and local claim; unavailable-helper fallback is in D2. Check ownership before writing/testing and delivery.

<a id="canonical-main-and-integration-workstreams"></a><a id="preferred-ownerintegrator-execution-route"></a>
<a id="staged-integration-for-parallel-slices"></a><a id="documentation-synchronization"></a>
<a id="accepted-and-integrated-task"></a><a id="published-release"></a>
## Delivery

Worker may commit/push its assigned branch. Main alone is canonical/releasable; staging is not release. Merge, force-push, destructive Git/ref operations, release and settings remain Owner/Integrator-controlled unless explicitly delegated. D5 owns exact-head guarded integration, PR CI, exact-main push CI and affected-document maintenance.

## Verification and completion

Use D4's proportional checks and actual exact-candidate evidence; required independent review/UAT remains independent. Never report pending checks as passed. Return exact baseline/target/candidate, branch/workspace, changed files/stat, actual checks/limits and final HEAD/remote/working-tree readback. Use existing issue/PR receipts, no new ledger. CBM is optional; no used/skipped report, compulsory index or model telemetry.

Historical AGENTS provenance: [pre-consolidation rules](https://github.com/LTstripes/hermes-finance/blob/ae302939d8f6fea4c0b15d854d62a8289c007502/AGENTS.md). Archived client adapters are history; D6 is the current routing home.
