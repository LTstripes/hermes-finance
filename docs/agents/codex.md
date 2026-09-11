# Codex adapter

This file is a Codex client adapter. It does not replace [`AGENTS.md`](../../AGENTS.md).

Repository policy defines project constraints and acceptance. Local Codex configuration defines local models, subagents, skills and runtime mechanics.

See [`docs/AGENT_ORCHESTRATION.md`](../AGENT_ORCHESTRATION.md).

## Mode A — manual Worker

When the launch explicitly requests `Codex без оркестрации` or otherwise assigns Codex as a single Worker:

- Codex acts as the **Worker**;
- read `AGENTS.md`, the issue and relevant accepted contract/spec;
- implement only the assigned task;
- use the assigned task branch/workspace;
- run required checks;
- commit/push only the task branch when required;
- do not self-accept;
- do not merge canonical/integration branches unless explicitly delegated;
- return the project completion evidence.

## Mode B — `$delivery-loop` Execution Orchestrator

When the launch explicitly invokes `$delivery-loop` or requests the default orchestrated Codex route, the root session acts as **Execution Orchestrator**.

The root must:

- load project policy before local orchestration mechanics;
- validate issue, exact baseline, branch/workspace, queue mode and review requirement;
- delegate implementation to the locally configured Worker;
- not duplicate delegated write work after delegation;
- wait for the Worker and inspect the actual candidate/diff/check evidence;
- invoke a separate read-only independent Reviewer when project routing requires it, when the Owner/Integrator requests it, or when justified execution risk raises the review requirement;
- stop for Integrator re-scope if that risk implies architecture, contract or financial-meaning expansion;
- use at most two automatic remediation cycles;
- return only internal verdicts such as `INTERNAL_ACCEPT`, `FIXES_REQUIRED`, `BLOCKED`, or `BLOCKED_FOR_INTEGRATION`;
- never equate `INTERNAL_ACCEPT` with project `ACCEPT`;
- never acquire implicit merge authority.

A reviewer that inherits write capability from the parent runtime is not evidence of enforced independent read-only review. Use the owner's locally configured review mechanism that actually enforces the intended isolation.

## Queue behavior

The root may advance automatically only through an explicitly authorized queue.

For independent tasks:

- each task has its own branch/workspace/baseline;
- each task reaches `INTERNAL_ACCEPT` before the next eligible task starts;
- the previous candidate is not an implicit baseline for the next task.

If a task requires prior integration and no explicit dependency strategy was provided, mark it `BLOCKED_FOR_INTEGRATION`. That blocks the affected dependency chain, not unrelated explicitly listed tasks.

Return both per-task evidence and one final queue summary.

## Local skills

The local Codex environment may expose:

- `$delivery-loop` for generic orchestration;
- a thin `hermes-finance` helper for Finance-specific verification guidance.

These are execution helpers only. They must not duplicate or override repository sources of truth. Local filesystem paths, current model IDs and reasoning settings must not be hardcoded into this repository.

## Repository policy still governs

Regardless of local Codex settings, this repository controls:

- scope and source-of-truth precedence;
- workspace/branch isolation;
- financial and privacy invariants;
- verification;
- STOP/re-scope conditions;
- canonical integration authority.
