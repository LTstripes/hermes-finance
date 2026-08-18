# Codex adapter

This file is a Codex client adapter. It does not replace [`AGENTS.md`](../../AGENTS.md).

## Local orchestration stays local

Repository docs define project constraints and expected outcomes.

Internal Codex orchestration and role assignment are controlled by the owner's local Codex Project/settings. At the start of a task, before choosing internal roles or delegation, Codex should load and apply those local Project settings for:

- primary;
- workers / subagents;
- reviewer roles;
- internal delegation.

Do **not** duplicate or hardcode those local Codex settings into this Git repository.

Do not hardcode current internal model names if they are machine-, account- or runtime-specific.

## Repository policy still governs

Regardless of local Codex settings, this repository still governs:

- scope;
- isolation;
- privacy;
- verification;
- branch and delivery behavior.

See [`AGENTS.md`](../../AGENTS.md) and [`docs/MODEL_ROUTING.md`](../MODEL_ROUTING.md).
