# AGENTS.md — Hermes Finance

Universal project constitution. Read this before every task. Client-specific adapters live in [`docs/agents/`](docs/agents/) and must not weaken these rules.

## Read by task type

Read this constitution and the current issue/applicable Integrator notes once at task start; refresh them when the assignment or authoritative facts change. Read detailed sources by need, not as a mandatory whole-repository tour:

- Docs/process-only: affected documents and their referenced policy sections; no product-wide architecture/test inventory.
- Implementation/bugfix: the relevant contract/architecture and affected source/tests, plus the verification policy below.
- Financial/data semantics, restore, migration, privacy or runtime boundaries: the governing spec/ADRs and applicable review/UAT gates before changing that boundary.
- Task routing/proposal: `docs/MODEL_ROUTING.md`; client mechanics: only the relevant `docs/agents/` adapter.
- An explicitly requested orchestration/queue: the relevant `docs/AGENT_ORCHESTRATION.md` section; reading it does not activate the loop.

Use already-read unchanged context. Historical task catalogs are not standing orders. Within the authorized task, perform routine reversible investigation, edits, synthetic checks and permitted delivery without repeated approval; scope/product/security/data decisions and canonical integration retain their existing owners.

## Sources of truth

When documents disagree, use this order:

1. [`docs/MASTER_SPEC.md`](docs/MASTER_SPEC.md) — business rules, product scope, architecture.
2. Accepted ADRs in [`docs/adr/`](docs/adr/) — normative contracts.
3. The active release or task document, when one exists.
4. [`docs/VERIFICATION_POLICY.md`](docs/VERIFICATION_POLICY.md) — how to verify.
5. [`docs/MODEL_ROUTING.md`](docs/MODEL_ROUTING.md) — roles, risk class, escalation.
6. [`docs/AGENT_ORCHESTRATION.md`](docs/AGENT_ORCHESTRATION.md) — execution modes and project-facing orchestration contract.
7. [`docs/PROJECT_WIKI.md`](docs/PROJECT_WIKI.md) — durable project context.
8. Historical documents (`docs/history/HERMES_TASKS.md`, `docs/history/HERMES_START_PROMPT.md`, `docs/IDEA.md`, old release files) — historical context only.

Do not treat old release-execution notes as current standing orders.

## Task prompt authority

The current GitHub issue, accepted contract and applicable Integrator notes define the task under the source precedence above. A launch prompt is a locator and execution assignment, not a second specification. Update the authoritative issue/note when requirements change.

Use the [Owner task proposal](docs/MODEL_ROUTING.md#owner-task-proposal) format when handing a task to the Owner. The launch identifies the issue/note, assigned branch and workspace policy, exact baseline/target, intended result and authorized delivery. An absolute workspace path is optional when the client has a known configured workspace root and the standing self-create rule below applies. Missing safety-critical information must still be resolved before writes.

One bounded task defaults to one Worker; independent review follows risk policy and does not activate orchestration. Only an explicit orchestration/queue request uses `docs/AGENT_ORCHESTRATION.md` and its listed eligible tasks.

## Roles

- **Owner** — product direction and owner-only/private/live UAT decisions.
- **Integrator** — normally ChatGPT/Lera. Owns project-level task decomposition/routing, authoritative issue/notes, final project `ACCEPT / FIXES REQUIRED / REJECT`, GitHub integration/merge and durable history/docs.
- **Execution Orchestrator** — optional execution-local coordinator. May plan, delegate, internally review/remediate and coordinate an explicitly authorized queue. It does not own project acceptance or canonical integration.
- **Worker** — one accountable implementation writer for one candidate. Does not self-accept.
- **Delegate** — bounded helper below an Orchestrator/Worker. Does not self-accept.
- **Reviewer** — independently validates a candidate and does not silently modify it.

Root/Orchestrator self-review is not called independent review. See `docs/MODEL_ROUTING.md` and `docs/AGENT_ORCHESTRATION.md`.

## Default execution mode

Bounded implementation defaults to one Worker owning investigation, implementation, verification and the authorized PR-ready candidate. The current coding session can be that Worker; this does not require a parent Orchestrator or a spawned implementation agent.

Independent review is added separately when risk policy or an explicit request requires it. Confirmed blockers return to the same Worker. A review requirement does not activate orchestration.

`$delivery-loop` is experimental and explicit opt-in only. Generic requests to use Codex, implement autonomously, review carefully or prepare a series of tasks do not activate it. Multiple workstreams or high risk do not activate it automatically either. See the activation gate in `docs/AGENT_ORCHESTRATION.md`.

## Preferred owner/integrator execution route

An authorized Integrator with direct GitHub capability performs its repository mechanics instead of making the Owner relay commands. The normative guarded workflow and limits of standing authorization are in [`AGENT_ORCHESTRATION.md`](docs/AGENT_ORCHESTRATION.md#integrator-owned-repository-mechanics). Direct access does not grant merge/release authority or override an explicit Owner choice of implementation client.

Standing routine authority never includes semantic/product/financial changes, migrations/data reinterpretation, privacy/runtime boundary expansion, destructive Git operations, repository settings or missing review/UAT gates. Such decisions retain their explicit Owner/Integrator route. A Worker cannot adopt Integrator authority from this paragraph.

Release publication uses [`RELEASE_AUTOMATION.md`](docs/RELEASE_AUTOMATION.md); ChatGPT mechanics are in [`docs/agents/chatgpt.md`](docs/agents/chatgpt.md).

## Sync before a new task

Fetch current canonical refs and pin the exact authorized baseline before creating an isolated task branch/worktree. A new write task starts from current `main` unless the task explicitly assigns another baseline. Verify the actual root and working-tree state; never switch/reset/pull over unfinished work or touch Owner runtime for setup.

A GitHub-native Integrator records the exact canonical SHA and creates the isolated task branch there; report this truthfully instead of claiming local sync commands ran. Keep the assigned baseline during implementation unless the project/task compatibility decision requires a refresh.

## One writer, isolated task branch

- One Worker owns one write candidate.
- Use a dedicated task branch. Do not change `main` or other integration branches directly.
- Reviewers do not silently modify the candidate they are independently reviewing.
- Parallel work is allowed only when scopes are genuinely independent.
- An Execution Orchestrator does not become a second writer after delegating implementation.

## Canonical main and integration workstreams

- `main` is the only canonical source of truth and the only release source.
- A long-lived `integration/*` branch is a staging/coordination line, never an alternate main and never a release source.
- Each implementation task still uses its own short-lived child branch and separate physical workspace. Workers do not merge `main` or other workers.
- The Integrator may incorporate accepted `main` changes into an integration branch when compatibility requires it; do not churn branches merely because `main` advanced.
- An integration milestone reaches `main` only after its own review, CI and applicable UAT gates pass.

## Staged integration for parallel slices

Use an explicit `integration/*` staging branch **at the start of a multi-slice milestone**, not only after every sibling PR is finished, when several accepted tasks are expected to touch shared application spine files or must be owner-UATed together.

Rules:

- `main` remains canonical and release-only; the staging branch is temporary coordination state.
- Each Worker still writes only its isolated task branch/workspace and does not merge siblings.
- After Integrator `ACCEPT` of a task, integrate that exact accepted head into the milestone staging branch promptly and run a proportional integration smoke. Do not defer all semantic conflict resolution until the final owner-UAT aggregate.
- Later sibling Workers should finish against the current milestone integration context when practical: refresh/reconcile their task branch with the latest accepted staging head before final handoff, or explicitly prove compatibility with it. Do not silently replace their original task contract with staging-only behavior.
- The Integrator owns shared spine reconciliation. Files such as application route registries, `UiV2Entry`, `UiV2Shell`, shared month-selection/navigation helpers and shared visual-test registration must not become independently authoritative in several sibling PRs. Workers should prefer leaf pages/components/tests; central route/navigation union is reconciled by one Integrator-owned commit when multiple slices overlap.
- When a shared configuration can be made additive/declarative (for example route metadata or visual-spec discovery), prefer that design so new slices do not repeatedly edit one central list.
- Owner UAT for a milestone runs on one exact aggregate SHA that contains the ancestry of all accepted slice heads and has its own CI/evidence. The exact aggregate tree the Owner tested is the integration candidate; do not reconstruct a different tree after PASS.
- High-risk flows (financial mutation, Monthly Close, backup/restore, migrations, runtime/provider actions) remain gated from canonical `main` until their required owner UAT/review passes even if lower-risk sibling pages are already accepted.
- After owner PASS, integrate the proven aggregate tree or an exact-equivalent tree with explicit proof; then require canonical `main` push CI on the merged SHA.
- If milestone integration reveals a semantic conflict rather than a mechanical merge conflict, stop and resolve it as an Integrator decision against the accepted task contracts. Do not let a Worker choose which sibling contract wins.

## Parallel task isolation — physical workspace invariant

- **Never run two active write or verification tasks in the same physical working tree, even when they use different Git branches.**
- One active write/verification task owns one physical working tree for the duration of that task's local edits, tests and final verification.
- Parallel tasks must use separately assigned Git worktrees or independent clones. Branch isolation alone is insufficient when two sessions share the same checkout directory.
- A second session must not switch, reset, pull or otherwise change the branch/HEAD of a working tree that another active task is using for implementation or verification.
- Read-only review may share GitHub repository state, but any local review whose result depends on checkout contents or local test execution requires its own assigned workspace when another task is active in the original tree.
- Creating a sibling worktree/clone under the canonical workspace root requires either an explicit per-task assignment or the standing self-create authorization in the workspace-root rules below.
- Prefer a dedicated independent clone rather than a worktree when a high-risk migration/runtime/live-provider task benefits from stronger filesystem isolation.
- Production runtime and Owner preview/UAT/live-probe workspaces remain forbidden development-agent workspaces regardless of this parallelism rule.

## Runtime isolation — hard invariant

Production runtime data must never enter or be exposed to a development-agent workspace.

Agent and development clones must not contain or link to:

- a real `.env`;
- the real finance database;
- Owner preview/UAT databases;
- SQLite sidecars;
- backups;
- `private/`;
- credentials or tokens;
- Owner exports, documents or private payloads.

This prohibition includes copies, symlinks, junctions, hardlinks and other filesystem indirection.

The production runtime clone is never an agent development workspace. Owner preview/experiment runtimes and their UAT copies are also never agent workspaces. The Windows launcher may select only prepared runtime profiles (checkout + code identity + data location), not an arbitrary Git branch against one database; see [`docs/adr/0014-launcher-runtime-profile-safety.md`](docs/adr/0014-launcher-runtime-profile-safety.md).

Do not put machine-specific absolute local paths into tracked repository docs.

## Workspace root discipline

- A development agent may write only inside its explicitly assigned clone/task workspace or a task workspace it created under the standing authorization below.
- Agents MUST NOT move, rename, delete or repurpose sibling directories under the canonical local workspace root. Creating one new isolated task workspace is allowed only by explicit per-task assignment or the standing self-create authorization below.
- Temporary repositories or workspaces outside the configured canonical workspace root require explicit Owner/Integrator instruction.
- Owner-only live/probe workspaces use the designated local `owner-probes/` root and are never agent workspaces. Development agents must not access, inspect or reuse them while they contain Owner/live data.
- Machine-specific workspace-root paths and local placement remain untracked local configuration.

### Standing self-create authorization

For an ordinary development task, if the launch pins the exact baseline/target and task identity/branch, and the executing client can identify the configured local workspace root, the Owner/Integrator grants standing authority to create **one new isolated task worktree or clone** under that root using `workspaces/<agent>/<task>/`. The Worker must do this itself and **must not ask the Owner for an absolute workspace path merely because the launch omitted one**.

This standing authorization is limited:

- create a fresh task directory only; never reuse an active workspace;
- never switch/reset/pull the branch of another task's working tree;
- never touch Stable, Preview/UAT, production runtime, `owner-probes/`, private data locations or another active task;
- do not delete, move or clean up sibling workspaces under this authorization;
- if the intended path already exists, the configured workspace root is genuinely unknown/ambiguous, the root is inaccessible, or safe creation would require leaving the configured root, stop and ask the Owner/Integrator;
- a task may still require an explicitly assigned independent clone/path when its issue or launch says so, especially for migration/runtime/live-provider boundaries.

For future local task placement, use the portable hierarchy `workspaces/<agent>/<task>/`.
An agent root groups that client's task workspaces but is not itself a shared mutable working tree. Temporary verification artifacts belong under assigned scratch roots: `scratch/pytest/`, `scratch/verification/`, or `scratch/uv-cache/`. Remove a task workspace only after its final Git state has been verified and the cleanup is Owner/Integrator controlled.

## Product and privacy invariants

Keep these permanent. Detailed financial semantics live in `MASTER_SPEC.md` and accepted ADRs; do not re-derive them here.

- Local single-user product.
- Bind only to loopback by default.
- No cloud, auth, telemetry or trading without an explicit scope decision.
- Money and rates must be exact: no binary `float` in financial logic.
- Use `Decimal` in domain calculations, integer minor units in persistence, `ROUND_HALF_UP`.
- A closed reporting month is immutable until explicit reopen.
- The frontend is not the financial source of truth.
- Credentials, tokens, secrets, real `.env` files, production/Preview databases,
  backups, full private owner exports/provider payloads and other reconstructive
  private datasets never enter development/agent artifacts (Git, tests, logs,
  prompts, worker/review reports) or workspaces, and are never exposed to
  development agents. Local owner-runtime exports/reports generated by Hermes
  for the owner are not prohibited.
- Avoid publishing individual financial values unnecessarily; redact or abstract
  them where practical. An isolated scalar amount in an issue, document or
  comment is normally a P3 hygiene/backlog cleanup item, not automatically a
  critical security incident or release blocker, unless its context materially
  raises sensitivity or reconstructive risk.
- Do not rewrite Git history solely to remove historical scalar amounts without
  explicit Owner authorization.

## Scope discipline

- Do only the assigned task.
- A normal Worker does not start the next task automatically.
- An Execution Orchestrator may advance only to the next **explicitly listed eligible task** when an authorized `$delivery-loop` queue is active and the prior task reached `INTERNAL_ACCEPT`.
- The Orchestrator must not discover/invent extra backlog work. `BLOCKED_FOR_INTEGRATION` blocks only the affected dependency chain; unrelated explicitly listed eligible tasks may continue.
- Do not do unrelated cleanup “while here”.
- If the contract is ambiguous or conflicts with `MASTER_SPEC` / an accepted ADR, stop and escalate. Do not guess.
- If a bounded or microfix starts requiring new architecture, invariants, test infrastructure, financial meaning, or materially more surface than accepted, **STOP**. Report the expansion, root cause and options; the Integrator must explicitly re-scope before implementation continues.

## Verification

Follow [`docs/VERIFICATION_POLICY.md`](docs/VERIFICATION_POLICY.md).

Every task requires:

- proportional targeted checks;
- a final scope, diff and privacy review;
- exact checks reported truthfully;
- a final state read-back of `HEAD`, branch/remote and working tree, or the truthful GitHub-native equivalent when no local checkout exists.

For implementation work, the normal verification sequence is targeted checks during iteration, one full relevant harness before Worker handoff, then package/install smoke as the final gate when packaging or installation is in scope. Canonical PR CI and exact-main push CI remain mandatory when the task is integrated. Do not use the launcher Stable self-update as a proven canonical release path: until the #313 redesign is accepted, prefer small composable Owner operations and the documented recovery path.

Do not claim a full suite passed unless that suite actually ran and passed.

For an integrated GitHub-native task, PR checks are not the final proof by themselves: read back the merged `main` SHA and verify the canonical `push` CI/checks for that exact SHA when the repository workflow provides them.

Independent review is required when `docs/MODEL_ROUTING.md` says so, when the Owner/Integrator explicitly requests it, or when justified execution risk raises the review bar under that policy. A separate Reviewer is required for evidence to count as independent review.

## Delivery

A normal task Worker may commit and push **its own task branch** when that is part of the assigned workflow.

These remain Owner/Integrator controlled unless explicitly delegated:

- merge to canonical branches;
- force-push;
- destructive reset or rebase;
- branch or tag deletion;
- release publication;
- repository settings.

Owner/Integrator controlled does not mean Owner-manual. An authorized Integrator with direct GitHub capability should perform permitted repository actions itself rather than instructing the Owner to click through GitHub.

`INTERNAL_ACCEPT` from an Execution Orchestrator does not authorize canonical/integration merge.

## Documentation synchronization

### Accepted and integrated task

After a task is accepted and integrated, the accepting Integrator must update any durable project documentation that task made stale. Update only documents that are materially affected.

### Published release

A published release is not documentarily closed until all four match released reality:

- `README.md`
- `CHANGELOG.md`
- `docs/PROJECT_WIKI.md`
- `docs/EXECUTION_HISTORY.md`

No document may continue to describe the published release as RC, candidate or unreleased.

## Completion reporting

A normal Worker returns one concise per-task completion report with:

- task/issue ID and status;
- **Model evidence** using the common fields below;
- baseline, target integration branch, task branch/workspace and exact candidate SHA;
- work completed, key files and exact `git diff --stat` additions/deletions when available;
- exact checks and outcomes;
- deviations, limitations, blockers and relevant execution confounders (for example resource contention);
- final working-tree state and remote/HEAD read-back when local.

Use this compact block in every Worker handoff:

```text
Model evidence
client/runtime: <name + version if exposed>
requested model/effort: <value or unknown>
actual model/provider/effort: <runtime-reported value or unknown>
identity source: runtime_confirmed | worker_reported | owner_reported | assigned_only | unknown
delegates/fallbacks: <chain or none/unknown>
usage: input=<n|unknown>; cached_input=<n|unknown>; output=<n|unknown>; reasoning=<n|unknown>; total=<n|unknown>
reported cost/credits: <exact runtime/billing value or unknown>
reported active/elapsed time: <exact runtime value or unknown>
```

Usage fields are evidence only when the executing client/runtime exposes exact counters. Do not estimate token counts, infer subscription cost, convert public list prices into a claimed run cost, or treat unavailable counters as zero. If the normal runtime does not expose a field, write `unknown`; lack of telemetry is not a Worker defect. Report only aggregate counters/metadata; never include private prompts, secrets or hidden reasoning.

Workers/Execution Orchestrators do **not** edit `docs/MODEL_BENCHMARK.md` or the benchmark tracker to grade themselves. The Integrator records accepted, rejected, pending and abandoned attempts centrally after source/evidence review and keeps Worker, Reviewer and research roles separate.

An orchestrated queue additionally returns one final queue report listing every authorized task, its final internal state, candidate SHA where applicable, review path and unresolved Integrator action. That queue report is not a batch project acceptance.

After Integrator-owned delivery side effects and final canonical read-back, the Integrator may issue the **Canonical completion report** for the integrated project result.
