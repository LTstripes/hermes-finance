# Hermes adapter

This file is a Hermes client adapter. It does not replace [`AGENTS.md`](../../AGENTS.md).

## No permanent provider/model lock

The repository defines role requirements and risk/escalation expectations. It does **not** permanently select a Hermes provider, model or reasoning level.

For a concrete task, the owner or task launch may specify or approve:

- primary;
- optional worker;
- reviewer;
- provider / model;
- reasoning level.

These may change between tasks.

Claim an actual provider/model identity only when it is runtime-confirmed.

Do not modify shared Hermes defaults merely to satisfy one task unless explicitly asked.

## Workspace isolation

A Hermes development workspace must never contain or link to production runtime data. See [`AGENTS.md`](../../AGENTS.md) and [`docs/adr/0012-runtime-and-agent-workspace-isolation.md`](../adr/0012-runtime-and-agent-workspace-isolation.md).
