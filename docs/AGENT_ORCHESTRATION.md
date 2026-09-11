# Agent orchestration — Hermes Finance

> **Status:** project-facing execution contract. Local client configuration implements this contract but does not override repository policy.

This project supports two execution modes. The authoritative task specification remains the active GitHub issue, accepted ADR/contract and explicit Integrator notes under the precedence in `AGENTS.md`.

## Roles

- **Owner** — product direction and owner-only/private/live UAT decisions.
- **Integrator** — normally ChatGPT/Lera. Owns project-level decomposition and routing, authoritative issue/notes, final `ACCEPT / FIXES REQUIRED / REJECT`, GitHub integration/merge, and durable history/docs.
- **Execution Orchestrator** — optional execution-local coordinator. In Codex `$delivery-loop` mode this is the strong root session. It may plan, delegate, review, remediate and coordinate an explicitly authorized queue, but it does not own project acceptance or canonical integration.
- **Worker** — one accountable implementation writer for one candidate. A Worker does not self-accept.
- **Delegate** — bounded helper below an Orchestrator or Worker. It does not self-accept or acquire implicit canonical ownership.
- **Reviewer** — independent validator when project routing, an explicit request, or justified in-task risk requires one. A Reviewer does not silently modify the candidate.

Root/Orchestrator review is useful but is not called **independent review**. Independent review means a separate review context/runtime with no implementation ownership of the candidate under review.

## Mode A — manual / brokered execution

Normal flow:

`Owner -> Integrator -> authoritative issue -> short launch prompt -> selected Worker -> completion report -> Integrator GitHub review -> FIXES REQUIRED / ACCEPT / REJECT -> Integrator integration`

Examples:

- `дай задачу для Grok` -> manual Grok Worker prompt;
- `дай задачу для Hermes` -> manual Hermes Worker prompt;
- `дай задачу для <model/client>` -> manual single-Worker prompt unless the owner explicitly asks for orchestration;
- `Codex без оркестрации` -> Codex acts as a normal single Worker.

The launch prompt is locator/execution context, not a second specification.

## Mode B — Codex `$delivery-loop`

Owner intent:

- `дай задачу для Codex` -> orchestrated single-task route by default;
- `дай серию задач для Codex` -> explicitly bounded queue route;
- `Codex без оркестрации` -> Mode A.

The launch packet must identify the repo, issue/task list, exact baseline for every task, target/integration context, task branch, physical workspace, queue mode and review requirement.

In orchestrated mode:

1. the root acts as **Execution Orchestrator**;
2. implementation is delegated to the locally configured **Worker**;
3. after delegation the root does not duplicate the same write work;
4. the Worker verifies and returns exact candidate evidence;
5. the root reviews the actual diff/check evidence;
6. a separate independent Reviewer is used when `MODEL_ROUTING.md`, an explicit Integrator/owner request, or a justified risk discovered during execution requires one;
7. justified risk may increase the review bar inside the existing task, but scope/contract expansion still requires STOP + Integrator re-scope;
8. remediation is bounded to at most two automatic cycles;
9. internal verdicts are `INTERNAL_ACCEPT`, `FIXES_REQUIRED`, `BLOCKED`, or `BLOCKED_FOR_INTEGRATION`;
10. `INTERNAL_ACCEPT` is execution evidence only and never equals project `ACCEPT`.

Canonical/integration merge remains Integrator-controlled unless the launch packet explicitly delegates that operation.

## Queue policy

### Single

One task is implemented, internally reviewed, reported and then the run stops.

### Independent queue

The Execution Orchestrator may advance only through tasks explicitly listed in the launch packet. Each task has its own task branch, physical writer workspace and exact assigned baseline. A previous candidate is never an implicit baseline for the next task.

A task must reach `INTERNAL_ACCEPT` before the Orchestrator advances to the next eligible item.

### Dependency / integration block

If task B requires task A to be integrated first and no explicit safe dependency/baseline strategy was supplied, B becomes `BLOCKED_FOR_INTEGRATION`.

That status blocks the affected dependency chain, **not the whole queue**. The Orchestrator may continue unrelated explicitly listed eligible tasks.

It must not invent stacked history, merge an integration branch, or pull new work from the backlog to fill the queue.

## Review triggers

Independent review is required when any of these applies:

1. project risk/routing policy requires it;
2. the Owner or Integrator explicitly requests it;
3. execution reveals a justified risk that under project policy raises the review requirement.

The third case does not authorize requirement invention. If the risk implies architecture, financial meaning or accepted-scope changes, STOP and return to the Integrator.

## Reporting

### Per-task report

Each Worker/internal task result must include exact task ID, baseline, branch/workspace, candidate SHA, changed areas, exact checks/outcomes, blockers/limitations and final working-tree state when local.

### Final queue report

An orchestrated queue additionally returns one summary containing every listed task and its final internal state (`INTERNAL_ACCEPT`, `BLOCKED`, `BLOCKED_FOR_INTEGRATION`, etc.), candidate SHA where applicable, review path used and unresolved Integrator actions.

The final queue report is not a batch project acceptance.

## Local Codex skills

Local Codex may provide `$delivery-loop` and a thin `hermes-finance` helper skill. Their filesystem paths, model assignments and runtime mechanics are machine-local and are not tracked here.

- `$delivery-loop` owns generic orchestration mechanics.
- `hermes-finance`, when present, may help select Finance-specific verification procedures.
- Neither skill overrides `AGENTS.md`, `MASTER_SPEC`, ADRs, the active issue, `VERIFICATION_POLICY.md` or `MODEL_ROUTING.md`.
- Permanent financial semantics belong in repository sources of truth, not in local skills.

## Invariants that automation does not weaken

All existing branch/workspace isolation, private-runtime prohibition, one-writer discipline, exact-money rules, closed-month semantics, verification requirements, STOP conditions and canonical-main controls remain unchanged.
