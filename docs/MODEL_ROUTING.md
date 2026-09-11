# Model routing — roles, risk and escalation

> **Status:** obligatory project protocol.
> This file is provider-neutral. It defines roles, risk classes and escalation. It does **not** permanently select a vendor, model or reasoning level.

Specific providers and models are chosen by the Owner/Integrator or by local agent configuration **per task**, not by a repository-global hardcoded table.

Client-specific notes: [`docs/agents/`](agents/). Execution-mode semantics: [`docs/AGENT_ORCHESTRATION.md`](AGENT_ORCHESTRATION.md).

## Roles

| Role | Owns |
|---|---|
| **Integrator** | Project-level task decomposition/routing, authoritative task notes, final project acceptance/rejection, GitHub integration and merge. |
| **Execution Orchestrator** | Optional execution-local planning, delegation, internal review/remediation and explicitly authorized queue coordination. Does not own project acceptance. |
| **Worker** | One accountable implementation candidate. Does not self-accept. |
| **Delegate** | Optional bounded helper below an Orchestrator/Worker. Does not self-accept. |
| **Reviewer** | Independently validates the result without silently modifying the candidate. |

A named Owner start command assigns the requested execution route. It does not permanently lock a provider/model unless the Owner, Integrator, task document or local client configuration says so.

Claim a provider/model identity only when it is runtime-confirmed. Worker summaries are context, not proof.

Root/Orchestrator self-review is not independent review. Independent review means a separate review context/runtime without implementation ownership of the candidate under review.

Observed routing note: fast/low-cost models can be appropriate for bounded UI, documentation and deterministic test work. That does not lower the review bar: financial contract semantics, migrations, reconciliation, tax/performance meaning, privacy and runtime boundaries require strong Integrator review and, when this policy requires it, independent review regardless of builder model.

## Risk classes

### Low risk

Docs, bounded tests, cosmetic UI, mechanical changes.

Usually Integrator review is enough. A separate independent reviewer is optional unless explicitly requested or justified risk appears.

### Medium risk

Normal backend or frontend behavior and API changes under established contracts.

Use a capable Worker. Independent review is appropriate when the change becomes cross-cutting, materially affects product behavior, is explicitly requested, or execution reveals a justified risk that raises the review bar.

### High risk

Financial semantics, migrations, data reinterpretation, privacy/security, runtime or network boundaries, destructive repository operations, and new architecture.

Requires a strong Integrator and an independent Reviewer. Escalate ambiguity **before** implementation.

A justified risk discovered during execution may raise the review requirement within the existing task, but it does not authorize scope expansion. Architecture/contract/financial-meaning changes still require STOP + Integrator re-scope.

## Codex local orchestration

Repository policy specifies required capability and review level, not permanent local Codex model IDs.

Local Codex configuration may use a strong root Execution Orchestrator with a cheaper scoped Worker and a separate read-only Reviewer. The project cares about role separation and effective evidence, not the current model names.

`INTERNAL_ACCEPT` from local orchestration is execution evidence only. Final project acceptance remains with the Integrator.

## Manual execution remains supported

Grok, Hermes, manual Codex and other clients may act as Workers under the same project roles. Client-specific routing is chosen per task. Codex orchestration is an explicit exception to the normal single-Worker interpretation when the Owner/Integrator requests `$delivery-loop` or a Codex orchestrated route.

## Benchmark / A-B mode

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
- private Owner data would be required;
- a formula would change tax, return, passive income, capital or goal progress against the accepted contract;
- a test fails outside the declared scope in a way that suggests a contract/integration problem;
- the task would add auth, cloud, telemetry, trading or other out-of-scope capability;
- a bounded task now requires architecture/contract expansion.

## What this file is not

This file is not:

- a ranking of vendors or models;
- a permanent Hermes/Codex/Grok/Gemini roster;
- a description of one client's local skill/config syntax;
- a license for an Execution Orchestrator to self-integrate accepted work.

Historical route tables remain historical only.
