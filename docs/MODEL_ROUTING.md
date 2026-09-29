# Model routing — roles, risk and escalation

> **Status:** obligatory project protocol.
> This file is provider-neutral. It defines roles, risk classes and escalation. It does **not** permanently select a vendor, model or reasoning level.

Specific providers and models are chosen by the Owner/Integrator or by local agent configuration **per task**, not by a repository-global hardcoded table.

Client-specific notes: [`docs/agents/`](agents/). Execution-mode semantics: [`docs/AGENT_ORCHESTRATION.md`](AGENT_ORCHESTRATION.md).

## Roles

Role ownership and the prohibition on self-acceptance are defined in [`AGENTS.md`](../AGENTS.md#roles). This document owns capability, risk/review and escalation decisions; it does not redefine the roles.

Model identity must be runtime-confirmed. Independent review requires a separate review context without implementation ownership. A fast implementation model never lowers the financial, migration, privacy or runtime review bar.

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

Default bounded execution is one Worker owning investigation, implementation, verification and the authorized candidate. Independent review follows the risk classes above without requiring an Execution Orchestrator; confirmed blockers return to the same Worker.

Orchestration is experimental and explicit opt-in only. Local Codex configuration may provide an Orchestrator for an expressly requested coordinated run or experiment under the activation gate in `AGENT_ORCHESTRATION.md`. Task importance, high risk, frontend plus tests, or a need for review never activates it automatically. The project cares about role separation and effective evidence, not the current model names.

`INTERNAL_ACCEPT` from local orchestration is execution evidence only. Final project acceptance remains with the Integrator.

## Manual execution remains supported

Grok, Hermes, Codex and other clients act as single Workers by default under the same project roles. Client-specific routing is chosen per task. A request to run `$delivery-loop` or an explicit request for orchestrated execution is the exception; mentioning, reviewing or editing orchestration is not a request to run it.

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

## Owner task proposal

Use this format when proposing a task to the Owner, in plain Russian:

1. **Название.**
2. **Что изменится и зачем:** one or two concrete sentences.
3. **Сложность:** небольшая / средняя / сложная, with a short reason. Complexity describes implementation effort; state **Риск** separately using this project's risk/review policy.
4. **Исполнитель:** offer a concrete **Codex option** (model and supported effort) and an **external option** (model and provider/client), with one sentence on preference/confidence. Select one route at launch. An alternative may be unavailable or not recommended for this risk; do not invent one. Report the actually used model only from runtime evidence.
5. **Независимое ревью / действия владельца:** only the required review or private/manual gate, with its reason.
6. One copyable start prompt, normally 5–8 lines and about 100 words or less: repo/issue and applicable note, Worker role, target and exact baseline, assigned branch, workspace policy, intended result and authorized delivery. An absolute workspace path is optional when the standing self-create authorization in `AGENTS.md` applies. Requirements and acceptance criteria remain in the authoritative issue/contract.

Do not invent an available model, baseline, workspace root or permission to make the card look complete. When the configured local workspace root is known, the standing `AGENTS.md` self-create rule is the permission: the Worker creates `workspaces/<agent>/<task>/` itself and does not ask the Owner for a per-task absolute path. Resolve only genuinely missing safety-critical assignment, unknown/ambiguous workspace root, path collision or contract information before writes. A short prompt does not waive any required gate. An explicitly orchestrated launch additionally follows `AGENT_ORCHESTRATION.md`; this format does not activate it.

## Evidence-backed routing

Use the dated [model evidence journal](MODEL_BENCHMARK.md) and [#605](https://github.com/LTstripes/hermes-finance/issues/605), paired with Health-Check's journal. Record real task outcomes without rerunning tasks merely to accumulate scores. Routine logging is not activation of blind A/B or an agent queue.

The Integrator records role/profile, complexity/risk, actual model + provider/client, baseline/candidate/verdict, substantive correction rounds and source evidence. Model/provider attribution confidence may be added by the Integrator when known. Usage/cost/time/delegate telemetry is optional and recorded only when independently available; Workers are not asked to manufacture repeated `unknown` fields. Infrastructure contention and assignment/review mistakes are separate from model defects. A leaf merge is not aggregate parity or Owner UAT.

Prefer the least expensive suitable execution route with sufficient evidence, not the cheapest name regardless of risk. Trial/anonymous routes start on bounded noncritical tasks. No historical grade or model switch waives independent financial/lifecycle review. One primary Worker and one heavyweight local verification process at a time is the current resource-aware default; separate physical workspaces remain mandatory and CI gates are unchanged.
