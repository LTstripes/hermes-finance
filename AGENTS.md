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

## One writer, isolated task branch

- One primary writer owns a write task.
- Use a dedicated task branch. Do not change `main` or other integration branches directly.
- Reviewers do not silently modify the candidate they are independently reviewing.
- Parallel work is allowed only when scopes are genuinely independent.

## Runtime isolation — hard invariant

Production runtime data must never enter or be exposed to a development-agent workspace.

Agent and development clones must not contain or link to:

- a real `.env`;
- the real finance database;
- SQLite sidecars;
- backups;
- `private/`;
- credentials or tokens;
- owner exports, documents or private payloads.

This prohibition includes copies, symlinks, junctions, hardlinks and other filesystem indirection.

The production runtime clone is never an agent development workspace.

Do not put machine-specific absolute local paths into tracked repository docs.

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
- a final state read-back of `HEAD`, branch/remote and working tree.

Do not claim a full suite passed unless that suite actually ran and passed.

## Delivery

A normal task worker may commit and push **its own task branch** when that is part of the assigned workflow.

These remain owner/integrator controlled unless explicitly delegated:

- merge to canonical branches;
- force-push;
- destructive reset or rebase;
- branch or tag deletion;
- release publication;
- repository settings.

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
