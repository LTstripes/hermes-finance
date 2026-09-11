# Hermes adapter

This file is a Hermes client adapter. It does not replace [`AGENTS.md`](../../AGENTS.md).

## Manual Worker route

In the normal Hermes route, the Hermes session receiving the task is the accountable **Worker** for the final candidate.

If it delegates to bots/subagents, those helpers are **Delegates** unless the launch contract explicitly assigns another role.

The Worker must:

- follow root `AGENTS.md`, the assigned issue/contract and exact baseline/branch/workspace;
- keep Delegates inside task scope;
- ensure simultaneous writers use isolated branches/workspaces;
- select/assemble the final candidate before returning it to the Integrator;
- report the actual Delegate/fallback chain;
- never self-accept or merge canonical/integration branches without explicit authority.

## No permanent provider/model lock

The repository defines role requirements and risk/escalation expectations. It does **not** permanently select a Hermes provider, model or reasoning level.

Provider/model/reasoning and optional Delegate/Reviewer choices are resolved at task launch when needed and may change between tasks.

Claim actual provider/model identity only when runtime-confirmed.

Do not modify shared Hermes defaults merely to satisfy one task unless explicitly asked.

## Relationship to Codex orchestration

Codex `$delivery-loop` is a Codex-local execution mechanism. Hermes does not need to use it.

Hermes remains a first-class manual Worker route under the same project `Owner / Integrator / Worker / Delegate / Reviewer` vocabulary and project review bar.

## Workspace isolation

A Hermes development workspace must never contain or link to production runtime data. See [`AGENTS.md`](../../AGENTS.md) and [`docs/adr/0012-runtime-and-agent-workspace-isolation.md`](../adr/0012-runtime-and-agent-workspace-isolation.md).

## Handoff

Commit/push only the assigned task branch when required and return the project Worker completion report. Final project `ACCEPT / FIXES REQUIRED / REJECT` remains with the Integrator.
