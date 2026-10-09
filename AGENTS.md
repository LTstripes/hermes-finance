# AGENTS.md — Hermes Finance

Shared project rules. Read once at task start; reuse unchanged context.

## Read by task type

Start with the current issue and applicable Integrator notes, then only the sources needed for the task:
- Docs/process: affected text and the policies it actually changes.
- Implementation: relevant contract, source/tests and the matching [verification policy](docs/VERIFICATION_POLICY.md) section.
- Financial/data/runtime/privacy changes: governing spec/ADRs and applicable review/UAT gates.
- Task routing: [MODEL_ROUTING](docs/MODEL_ROUTING.md). Integration or an explicitly requested queue: [AGENT_ORCHESTRATION](docs/AGENT_ORCHESTRATION.md).
Client adapters in `docs/agents/` contain client mechanics only; they do not add another mandatory reading tour or override these rules.

## Sources of truth

Product precedence: `docs/MASTER_SPEC.md` → accepted `docs/adr/` contracts → active release/task contract.
The current GitHub issue and accepted Integrator notes specify the assignment under those boundaries.
A launch prompt locates that assignment; it is not a second specification. Record changed requirements in the authoritative issue/note.
Verification, risk/review and integration procedures have the respective owners linked above; task-specific stricter gates still apply.
`docs/PROJECT_WIKI.md` is durable context. Historical task catalogs, experiments and old release notes are not standing orders.

## Roles

- **Owner**: product direction and private/live UAT decisions.
- **Integrator**: task routing, authoritative notes, project acceptance, authorized integration and affected durable docs/history.
- **Worker**: one accountable writer for one candidate; no self-acceptance or automatic next task.
- **Reviewer**: independent candidate assessment without implementation ownership; does not silently edit the candidate.
A role is not a GitHub account. Worker self-review is not independent review; optional coordinator/helper roles are defined only in the orchestration procedure.

<a id="default-execution-mode"></a><a id="task-prompt-authority"></a>
## Scope discipline

Default: one Worker takes the assigned result through investigation, implementation, verification and authorized delivery.
Choose implementation details, add necessary regressions and fix task-caused defects without repeated approval for routine reversible steps.
Do not add unrelated cleanup or invent backlog work. Queues/orchestration require explicit opt-in.
Stop for a conflicting/undefined contract, new financial meaning, architecture/invariant expansion, protected-data access or materially larger scope.
Ordinary engineering choices inside the accepted contract are not scope expansion; do not turn them into approval gates.

## Product and privacy invariants

- Local single-user Windows app, normal endpoint `127.0.0.1:8000`; loopback by default. No cloud, auth, telemetry or trading without an explicit scope decision.
- Money and rates are exact: no binary `float` in financial logic; `Decimal` calculations, integer minor-unit money storage, `ROUND_HALF_UP`.
- CLOSED reporting months are immutable until explicit reopen. The frontend is not the financial source of truth.

## Runtime isolation — pragmatic Owner-approved privacy

Credentials, access tokens, API keys, recovery material, real `.env`, production/Test/UAT databases and SQLite sidecars, backups, full private provider/broker exports and other reconstructive datasets are **not ordinary code fixtures**. Do not place them in tracked Git, public issues/PRs, CI artifacts or code-only test fixtures, or bypass this boundary with copies, symlinks, junctions, hardlinks or reused runtime mounts. Automated tests and CI use fabricated data. Secrets are never deliberately exposed in screenshots, issue comments or agent handoffs.

**Real UI screenshots are allowed in Owner-authorized UAT.** Displayed balances, deposit amounts, asset holdings, performance values, dates and other ordinary personal-finance facts are *not* credentials and do not by themselves trigger a privacy blocker. An assigned Owner-local UAT operator and its authorized AI worker may inspect actual Test screen content and screenshots with normal browser capture, local image viewer and assistant/model vision tooling, including sending real screenshots to the authorized assistant conversation when helpful. Screenshots may be held temporarily in local untracked/ignored UAT scratch for visual diagnosis. Do not require a special protected viewer, obligatory monetary redaction or a fresh Owner confirmation for every image. Preserve the Owner's deliberate risk choice; the repository is public.

Real screenshots/DOM dumps should **not be automatically committed or published** as public GitHub/CI evidence; use synthetic fixtures for committed visual tests, and summarize real UAT findings in normal language. Harmless individual financial values are not automatically treated as incidents. The Owner may expressly choose to publish a specific image/value, but normal UAT authorization is not blanket permission for public posting of whole private datasets.

**Runtime integrity remains independent of screenshot privacy.** Ordinary implementation stays in its isolated code checkout; do not inspect/copy real database files or reuse Stable/Test data as code fixtures. An explicitly assigned Owner-local UAT/operations worker may inspect the real UI and conduct only the authorized Test preparation, isolation/backup/readiness and read-only visual actions. This is not permission to migrate DBs, write financial assertions, reopen CLOSED months, modify Stable, publish releases, or reconfigure existing clients without the applicable explicit authorization. Preserve applicable ADR 0012/0014 and operations/verification gates for actual runtime mutations.

No machine-specific absolute paths in tracked files.

<a id="sync-before-a-new-task"></a><a id="one-writer-isolated-task-branch"></a>
<a id="parallel-task-isolation--physical-workspace-invariant"></a>
## Workspace root discipline

Fetch canonical refs and pin the authorized baseline: current `main` unless explicitly assigned otherwise; keep it unless compatibility requires refresh.
One active writing or local-verification task owns one physical worktree/clone, not merely a different branch. Never switch/reset/pull another task's tree.
GitHub-only review needs no local clone; local review/tests need their own isolated workspace when the original tree is active.
Write only in the assigned task workspace. Do not move, clean, delete or repurpose sibling directories, Owner runtime or other active workspaces.

Each execution client uses one Owner-configured machine-local workspace root. Create each task below that root as `<issue>-<slug>`; concrete absolute roots stay local and are never tracked. Do not inspect or edit another client's physical workspace by default: inspect sibling work through GitHub PRs/remote refs, or use an explicitly assigned independent review clone/path.

### Standing self-create authorization

With a known configured root and pinned task/branch/baseline/target, create one fresh `workspaces/<agent>/<task>/` worktree/clone yourself.
Do not ask for an absolute path just because the launch omitted it. Ask only for a genuine unknown/inaccessible root, path collision or boundary crossing.
An explicitly assigned independent clone/path takes precedence. Out-of-root work needs authorization; high-risk isolation may require an independent clone.
Use assigned scratch roots for temporary checks/caches. Workspace deletion remains Owner/Integrator-controlled after final Git-state verification.

<a id="canonical-main-and-integration-workstreams"></a><a id="preferred-ownerintegrator-execution-route"></a>
## Delivery

A Worker may commit/push its own assigned task branch; no direct writes to `main`/integration branches or merging sibling/main changes independently.
`main` alone is canonical and releasable; `integration/*` is staging. Merge, force-push, destructive reset/rebase, branch/tag deletion, release and repo settings
remain Owner/Integrator-controlled unless explicitly delegated. A Worker cannot adopt Integrator authority from tool access.
An authorized Integrator performs permitted repository mechanics directly; existing standing integration authorization is not revoked by this document.
<a id="staged-integration-for-parallel-slices"></a><a id="documentation-synchronization"></a>
<a id="accepted-and-integrated-task"></a><a id="published-release"></a>
Staged integration and affected-document closeout belong to the integration procedure; release-specific closeout belongs to `docs/RELEASE_AUTOMATION.md`.

## Verification

Use the matching policy section, focused evidence and the existing CI; do not automatically repeat full suites for every handoff or role change.
Review final scope/diff/privacy and report actual checks, not inferred passes. Required independent review and Owner UAT are not replaced by green tests.
Integration requires successful exact-candidate PR CI and canonical exact-main push CI; never describe pending checks as completed.

## Completion reporting

Return one concise report: issue/status; baseline/target, branch/workspace and exact candidate SHA; changed files/diff stat;
actual checks and results; material limitations/blockers; final local HEAD/remote/working-tree read-back, or the truthful GitHub-native equivalent.

Normal handoffs do not request or record model/provider identity, benchmark grades or usage telemetry.
Keep new operational detail in its existing procedure, not as another copy here. Change this file for shared boundaries, authority or the minimum task entrypoint.
