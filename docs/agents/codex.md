# Codex adapter

[AGENTS.md](../../AGENTS.md) is the task entrypoint. This adapter contains only Codex-specific mechanics.

## Default Worker

The receiving coding session is the Worker unless explicitly assigned another role; no parent coordinator or extra implementation session is required.
Use the configured workspace root under the standing self-create policy. Local model/effort availability comes from runtime configuration, not repository aliases.

Portable role/root boundaries and the Owner-local registry are in [Owner machine layout](../OWNER_MACHINE_LAYOUT.md).
The real-machine inventory is Owner-only; agents use synthetic fixtures.

## Independent review

Give a separate Reviewer the pinned base/candidate, relevant issue/note excerpts, previous findings and existing check evidence.
A network-disabled Reviewer needs the literal relevant sources, not inaccessible URLs. Check packet completeness with cheap mechanics, not an extra model review.
Enforced read-only review needs a separate context/runtime with suitable permissions; a child inheriting writable rights does not prove isolation.
The review requirement does not require orchestration or a duplicate full test run.

## Explicit orchestration only

Optional queue mechanics are in `docs/AGENT_ORCHESTRATION.md`; do not activate them for an ordinary task.

## Local helpers

Load a relevant helper only when needed. Do not modify global/local skills, model defaults or installed configuration without an explicit request.
