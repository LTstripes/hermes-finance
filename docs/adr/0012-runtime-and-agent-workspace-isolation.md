# ADR 0012 — Runtime and agent workspace isolation

- **Status:** Accepted
- **Date:** 2026-08-18
- **Release line:** post-0.5.0 process / workspace hygiene
- **Source task:** HYG-01
- **Related:** [`AGENTS.md`](../../AGENTS.md), [`docs/agents/`](../agents/)

## Problem

By 0.5.0 the original workspace had evolved from one Hermes checkout into a shared development environment:

- the old primary repository was also the production runtime;
- it contained a real `.env`, the live finance database, backups and other private assets;
- it acted as one common Git directory for 33 linked worktrees;
- multiple agents, reviews and benchmarks accumulated around that shared Git directory;
- development work and the owner runtime were insufficiently isolated.

A development agent that can see production secrets, the live database or owner exports can leak them into diffs, logs, prompts, tests or reports. Linked worktrees on a runtime checkout make that leak path structural.

## Decision

Separate the production runtime from all agent development environments.

Conceptually maintain:

- one production runtime clone;
- one independent clone per development agent.

All agent clones have independent Git directories. They are not worktrees of the runtime clone.

Runtime secrets and data live only in runtime storage.

Development agents must not access runtime data through copies or filesystem links, including:

- copies;
- symlinks;
- junctions;
- hardlinks;
- other filesystem indirection.

Machine-specific absolute paths are local configuration, not repository architecture. Tracked docs must not turn a local disk layout into a portable requirement.

The canonical shared source is the GitHub repository. Agent clones sync from canonical `main` as described in `AGENTS.md`.

## Consequences

- Production use happens from a runtime checkout that may contain ignored local runtime data.
- Implementation, review and benchmark work happen in clean agent clones.
- A write task uses a dedicated branch in the writer's clone.
- Reviewers do not silently edit the candidate they are independently reviewing.
- Runtime isolation is a hard invariant, not a convenience.

## Migration record

This is a historical record of the owner-side migration after 0.5.0. It does not include secret values, database contents or private financial data.

Local absolute paths under a machine-specific Finance root (for example a `D:\Finance\...` sibling-directory layout) were an implementation detail of that migration. They are **not** a portable repository requirement.

Summarized sequence:

1. Inventory-only audit of the shared checkout, linked worktrees and runtime assets.
2. Preservation triage of what must not be lost.
3. Preservation Seal of the state to keep.
4. Preservation of unique dirty Codex work, a special Grok/T-Invest research artifact, and the R04-02 benchmark source/tests.
5. Classification of dangling commits.
6. Creation of independent agent clones, each with its own Git directory.
7. Retirement of all 33 linked worktrees of the old shared checkout.
8. Creation of a clean runtime clone.
9. Verified migration of `.env`, the finance database, backups and private data into runtime storage only.
10. Local loopback runtime smoke on the new runtime clone.
11. Retirement of the old shared checkout.

## What this ADR does not decide

- Product financial semantics.
- Cloud, auth, VPS or multi-user deployment.
- Which agent vendor is primary.
- Exact local folder names on any machine.
