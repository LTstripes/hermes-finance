# Model routing — roles, risk and escalation

> **Status:** obligatory project protocol.
> This file is provider-neutral. It defines roles, risk classes and escalation. It does **not** permanently select a vendor, model or reasoning level.

Specific providers and models are chosen by the owner or by local agent configuration **per task**, not by a repository-global hardcoded table.

Client-specific notes: [`docs/agents/`](agents/).

## Roles

| Role | Owns |
|---|---|
| **Primary** | Task interpretation and the final candidate. Accepts or rejects worker output against the actual diff, tests and contract. |
| **Worker** | Optional bounded implementation or research delegate. Does not self-accept. |
| **Reviewer** | Independently validates the result. Does not silently modify the candidate under independent review. |

A named owner start command assigns the task. It does not, by itself, lock a provider/model unless the owner or the task document says so.

Claim a provider/model identity only when it is runtime-confirmed. Worker summaries are context, not proof.

## Risk classes

### Low risk

Docs, bounded tests, cosmetic UI, mechanical changes.

Usually primary self-review or a lightweight independent review.

### Medium risk

Normal backend or frontend behavior, and API changes under established contracts.

Independent review when the change is cross-cutting or materially affects product behavior.

### High risk

Financial semantics, migrations, data reinterpretation, privacy/security, runtime or network boundaries, destructive repository operations, and new architecture.

Requires a strong primary and an independent reviewer. Escalate ambiguity **before** implementation.

### Benchmark / A-B mode

Only when explicitly requested:

- same baseline;
- isolated candidates;
- no candidate sees or copies the other before comparison;
- compare actual diffs, tests and evidence;
- preserve attribution and the result in `docs/EXECUTION_HISTORY.md`.

## Escalation

Stop and escalate instead of guessing when:

- the specification and the task conflict;
- money/rate units, rounding or the source of truth are undefined;
- a migration may lose or reinterpret existing data;
- private owner data would be required;
- a formula would change tax, return, passive income, capital or goal progress against the accepted contract;
- a test fails outside the declared scope;
- the task would add auth, cloud, telemetry, trading or other out-of-scope capability.

## What this file is not

This file is not:

- a ranking of vendors or models;
- a standing Hermes/Codex/Grok/Gemini roster;
- a historical phase B/C route table;
- a description of any one client's delegation mechanics.

Historical route tables remain in old release documents as history only.
