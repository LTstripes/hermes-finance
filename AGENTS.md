# AGENTS.md — Hermes Finance

Universal project constitution. Read this before every task. Client-specific adapters live in [`docs/agents/`](docs/agents/) and must not weaken these rules.

## Sources of truth

When documents disagree, use this order:

1. [`docs/MASTER_SPEC.md`](docs/MASTER_SPEC.md) — business rules, product scope, architecture.
2. Accepted ADRs in [`docs/adr/`](docs/adr/) — normative contracts.
3. The active release or task document, when one exists.
4. [`docs/VERIFICATION_POLICY.md`](docs/VERIFICATION_POLICY.md) — how to verify.
5. [`docs/MODEL_ROUTING.md`](docs/MODEL_ROUTING.md) — roles, risk class, escalation.
6. [`docs/PROJECT_WIKI.md`](docs/PROJECT_WIKI.md) — durable project context.
7. Historical documents (`docs/history/HERMES_TASKS.md`, `docs/history/HERMES_START_PROMPT.md`, `docs/IDEA.md`, old release files) — historical context only.

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

When routing several tasks, give each task/agent its own separate copyable prompt. Never bundle unrelated launch prompts into one block.

## Preferred owner/integrator execution route

When the active owner/integrator surface has direct GitHub read/write access and can inspect GitHub Actions, it should complete repository-side work itself instead of using the owner as a human courier to another coding client or to the GitHub UI.

For a normal repository write task, prefer this guarded route:

1. read canonical GitHub `main` and capture its exact SHA;
2. create one isolated task branch from that exact baseline;
3. edit only the task branch and keep scope narrow;
4. open a PR and inspect the actual diff, scope and privacy boundary;
5. require the applicable PR CI/checks to complete successfully;
6. merge only when the integrator is authorized and the candidate is accepted;
7. read back canonical `main` after merge;
8. require canonical `push` CI on the exact merged `main` SHA before reporting integration complete.

Do **not** send the owner to Codex, another local agent, PowerShell or the GitHub UI merely to relay branch/file/PR/merge/release actions that the active integrator can already perform safely through GitHub.

Use a local development agent or another execution surface when it materially adds a capability the direct GitHub route does not provide, for example required local command execution, runtime/browser inspection, live provider work, binary/artifact manipulation, or an explicitly requested independent implementation/review. A relay is not a capability.

If a nonessential cleanup action is unavailable through the current connector, report the residual cleanup instead of shifting routine busywork to the owner. Never weaken safety or verification to avoid a hand-off.

For release publication, use the guarded repository-owned route in [`docs/RELEASE_AUTOMATION.md`](docs/RELEASE_AUTOMATION.md). When the integrator can create the control comment itself, the owner should not be asked to open GitHub or a local coding session only to trigger the release.

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

For a GitHub-native integrator without a local checkout, the equivalent requirement is to read canonical GitHub `main`, capture the exact baseline SHA, and create the isolated task branch from that SHA. Do not pretend a local sync command ran when no local checkout exists.

## One writer, isolated task branch

- One primary writer owns a write task.
- Use a dedicated task branch. Do not change `main` or other integration branches directly.
- Reviewers do not silently modify the candidate they are independently reviewing.
- Parallel work is allowed only when scopes are genuinely independent.

## Parallel task isolation — physical workspace invariant

- **Never run two active write or verification tasks in the same physical working tree, even when they use different Git branches.**
- One active write/verification task owns one physical working tree for the duration of that task's local edits, tests and final verification.
- Parallel tasks must use separately assigned Git worktrees or independent clones. Branch isolation alone is insufficient when two sessions share the same checkout directory.
- A second session must not switch, reset, pull or otherwise change the branch/HEAD of a working tree that another active task is using for implementation or verification.
- Read-only review may share GitHub repository state, but any local review whose result depends on checkout contents or local test execution requires its own assigned workspace when another task is active in the original tree.
- Creating a sibling worktree/clone under the canonical workspace root still requires explicit owner/integrator assignment under the workspace-root rules below.
- Prefer a dedicated independent clone rather than a worktree when a high-risk migration/runtime/live-provider task benefits from stronger filesystem isolation.
- Production runtime and owner preview/UAT/live-probe workspaces remain forbidden development-agent workspaces regardless of this parallelism rule.

## Runtime isolation — hard invariant

Production runtime data must never enter or be exposed to a development-agent workspace.

Agent and development clones must not contain or link to:

- a real `.env`;
- the real finance database;
- owner preview/UAT databases;
- SQLite sidecars;
- backups;
- `private/`;
- credentials or tokens;
- owner exports, documents or private payloads.

This prohibition includes copies, symlinks, junctions, hardlinks and other filesystem indirection.

The production runtime clone is never an agent development workspace. Owner preview/experiment runtimes and their UAT copies are also never agent workspaces. A future Windows launcher may select only prepared runtime profiles (checkout + code identity + data location), not an arbitrary Git branch against one database; see [`docs/adr/0014-launcher-runtime-profile-safety.md`](docs/adr/0014-launcher-runtime-profile-safety.md).

Do not put machine-specific absolute local paths into tracked repository docs.

## Workspace root discipline

- A development agent may write only inside its explicitly assigned clone or task workspace.
- Agents MUST NOT create, clone, move, rename or delete sibling directories under the canonical local workspace root unless the owner/integrator explicitly assigns that filesystem operation.
- Temporary repositories or workspaces outside the assigned agent clone require explicit owner/integrator instruction.
- Owner-only live/probe workspaces use the designated local `owner-probes/` root and are never agent workspaces. Development agents must not access, inspect or reuse them while they contain owner/live data.
- Machine-specific workspace-root paths and local placement remain untracked local configuration.

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
- Do not start the next task automatically.
- Do not do unrelated cleanup “while here”.
- If the contract is ambiguous or conflicts with `MASTER_SPEC` / an accepted ADR, stop and escalate. Do not guess.

## Verification

Follow [`docs/VERIFICATION_POLICY.md`](docs/VERIFICATION_POLICY.md).

Every task requires:

- proportional targeted checks;
- a final scope, diff and privacy review;
- exact checks reported truthfully;
- a final state read-back of `HEAD`, branch/remote and working tree, or the truthful GitHub-native equivalent when no local checkout exists.

Do not claim a full suite passed unless that suite actually ran and passed.

For an integrated GitHub-native task, PR checks are not the final proof by themselves: read back the merged `main` SHA and verify the canonical `push` CI/checks for that exact SHA when the repository workflow provides them.

## Delivery

A normal task worker may commit and push **its own task branch** when that is part of the assigned workflow.

These remain owner/integrator controlled unless explicitly delegated:

- merge to canonical branches;
- force-push;
- destructive reset or rebase;
- branch or tag deletion;
- release publication;
- repository settings.

Owner/integrator controlled does not mean owner-manual. An authorized integrator with direct GitHub capability should perform the permitted action itself rather than instructing the owner to click through GitHub or relay it through another agent.

## Documentation synchronization

### Accepted and integrated task

After a task is accepted and integrated, the accepting integrator must update any durable project documentation that task made stale. Update only documents that are materially affected.

### Published release

A published release is not documentarily closed until all four match released reality:

- `README.md`
- `CHANGELOG.md`
- `docs/PROJECT_WIKI.md`
- `docs/EXECUTION_HISTORY.md`

No document may continue to describe the published release as RC, candidate or unreleased.

## Completion report

After delivery side effects and the final read-back, send one report labelled **Canonical completion report**:

- task ID and status;
- baseline, branch and exact candidate SHA;
- work completed and changed files;
- exact checks and outcomes;
- limitations or questions;
- next backlog task, explicitly marked as not started.
