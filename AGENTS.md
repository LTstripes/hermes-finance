# AGENTS.md — Hermes Finance

Universal project constitution. Read this before every task. Client-specific adapters live in [`docs/agents/`](docs/agents/) and must not weaken these rules.

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

The active GitHub issue, accepted ADR/contract, and explicit Integrator note are the task specification. They contain scope, acceptance criteria and guardrails subject to the source-of-truth precedence above.

A launch prompt sent to a coding agent is **locator/execution context only**, not a second copy of the specification. By default it should contain only:

- issue number/link;
- assigned task branch and physical workspace;
- exact baseline/current integration SHA when relevant;
- instruction to read this `AGENTS.md`, the issue and any Integrator note/accepted contract;
- instruction to run the required checks, commit/push only the task branch, and return the exact final SHA.

Do not duplicate or rewrite the issue's requirements in the launch prompt. If requirements change, amend the authoritative issue/contract/Integrator note instead of changing them only in chat.

For a manual multi-agent comparison, give each candidate its own separate prompt. For an explicitly authorized Codex `$delivery-loop` queue, one queue launch packet may list several tasks only under the isolation/dependency rules in `docs/AGENT_ORCHESTRATION.md`.

## Roles

- **Owner** — product direction and owner-only/private/live UAT decisions.
- **Integrator** — normally ChatGPT/Lera. Owns project-level task decomposition/routing, authoritative issue/notes, final project `ACCEPT / FIXES REQUIRED / REJECT`, GitHub integration/merge and durable history/docs.
- **Execution Orchestrator** — optional execution-local coordinator. May plan, delegate, internally review/remediate and coordinate an explicitly authorized queue. It does not own project acceptance or canonical integration.
- **Worker** — one accountable implementation writer for one candidate. Does not self-accept.
- **Delegate** — bounded helper below an Orchestrator/Worker. Does not self-accept.
- **Reviewer** — independently validates a candidate and does not silently modify it.

Root/Orchestrator self-review is not called independent review. See `docs/MODEL_ROUTING.md` and `docs/AGENT_ORCHESTRATION.md`.

## Preferred owner/integrator execution route

When the active Integrator surface has direct GitHub read/write access and can inspect GitHub Actions, it should complete **Integrator-owned repository mechanics** itself instead of using the Owner as a human courier to GitHub, PowerShell or another client.

That includes issue/branch/PR/review/merge/history actions the Integrator can safely perform.

This principle does **not** override an explicit Owner choice of implementation surface. If the Owner asks for Grok, Hermes, Codex, a specific model/client, or a Codex `$delivery-loop` queue, prepare that execution route and keep GitHub plumbing with the Integrator where possible.

For a direct GitHub-native repository write explicitly assigned to the Integrator, prefer this guarded route:

1. read canonical GitHub `main` and capture its exact SHA;
2. create one isolated task branch from that exact baseline;
3. edit only the task branch and keep scope narrow;
4. open a PR and inspect the actual diff, scope and privacy boundary;
5. require the applicable PR CI/checks to complete successfully;
6. merge only when the Integrator is authorized and the candidate is accepted;
7. read back canonical `main` after merge;
8. require canonical `push` CI on the exact merged `main` SHA before reporting integration complete.

Use a local development Worker when implementation benefits from local command execution, runtime/browser inspection, an explicitly requested external model/client, independent implementation/review, or other capability/direct routing the Integrator is not supposed to replace.

If a nonessential cleanup action is unavailable through the current connector, report the residual cleanup instead of shifting routine GitHub busywork to the Owner. Never weaken safety or verification to avoid a hand-off.

For release publication, use the guarded repository-owned route in [`docs/RELEASE_AUTOMATION.md`](docs/RELEASE_AUTOMATION.md).

Client-specific behavior for ChatGPT is documented in [`docs/agents/chatgpt.md`](docs/agents/chatgpt.md).

## Sync before a new task

In a **clean** development clone, before starting a new task:

```powershell
git fetch origin
git switch main
git pull --ff-only origin main
git status --short
```

Do not switch, reset or pull over unfinished task work.

A write task starts from current canonical `main` unless the task explicitly pins another baseline.

For a GitHub-native Integrator without a local checkout, the equivalent requirement is to read canonical GitHub `main`, capture the exact baseline SHA, and create the isolated task branch from that SHA. Do not pretend a local sync command ran when no local checkout exists.

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

## Parallel task isolation — physical workspace invariant

- **Never run two active write or verification tasks in the same physical working tree, even when they use different Git branches.**
- One active write/verification task owns one physical working tree for the duration of that task's local edits, tests and final verification.
- Parallel tasks must use separately assigned Git worktrees or independent clones. Branch isolation alone is insufficient when two sessions share the same checkout directory.
- A second session must not switch, reset, pull or otherwise change the branch/HEAD of a working tree that another active task is using for implementation or verification.
- Read-only review may share GitHub repository state, but any local review whose result depends on checkout contents or local test execution requires its own assigned workspace when another task is active in the original tree.
- Creating a sibling worktree/clone under the canonical workspace root still requires explicit Owner/Integrator assignment under the workspace-root rules below.
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

- A development agent may write only inside its explicitly assigned clone or task workspace.
- Agents MUST NOT create, clone, move, rename or delete sibling directories under the canonical local workspace root unless the Owner/Integrator explicitly assigns that filesystem operation.
- Temporary repositories or workspaces outside the assigned agent clone require explicit Owner/Integrator instruction.
- Owner-only live/probe workspaces use the designated local `owner-probes/` root and are never agent workspaces. Development agents must not access, inspect or reuse them while they contain Owner/live data.
- Machine-specific workspace-root paths and local placement remain untracked local configuration.

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
- Private financial data never enters Git, tests, logs, prompts or reports.

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

For implementation work, the normal verification sequence is targeted checks during iteration, one full relevant harness before Worker handoff, then package/install smoke as the final gate when packaging or installation is in scope. Canonical PR CI and exact-main push CI remain mandatory when the task is integrated.

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

A normal Worker returns a per-task completion report with:

- task ID and status;
- baseline, branch/workspace and exact candidate SHA;
- work completed and changed files;
- exact checks and outcomes;
- limitations/questions/blockers;
- final working-tree state when local.

An orchestrated queue additionally returns one final queue report listing every authorized task, its final internal state, candidate SHA where applicable, review path and unresolved Integrator action. That queue report is not a batch project acceptance.

After Integrator-owned delivery side effects and final canonical read-back, the Integrator may issue the **Canonical completion report** for the integrated project result.
