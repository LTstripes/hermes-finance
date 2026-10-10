# Agent orchestration — Hermes Finance

Integrator procedures and optional explicitly requested orchestration. Ordinary Workers do not need this entire file.
Shared authority/isolation rules remain in [AGENTS.md](../AGENTS.md); risk/review triggers are owned by `MODEL_ROUTING.md`.

## Roles

**Execution Orchestrator** is an optional execution-local coordinator, not the project Integrator.
**Delegate** is a bounded helper below a Worker/coordinator, not another self-accepting candidate owner.
Neither role acquires canonical integration authority; self-review is not independent review.

## Mode A — single Worker (default)

Owner/Integrator assigns one bounded issue → selected Worker produces the candidate → Integrator assesses actual diff/evidence and integrates when allowed.
Add an independent Reviewer only under risk policy or explicit instruction; confirmed blockers return to the same Worker.
A request for Codex, autonomous implementation, careful review or several task prompts is not a request for an unattended queue.

## Integrator-owned repository mechanics

With direct GitHub capability, the Integrator performs authorized repository mechanics rather than making the Owner relay commands.
Existing standing Owner authorization covers this standard flow without repeated approval:

1. Create/update the task issue, PR and repository metadata under the accepted assignment.
2. Inspect the exact candidate, scope/privacy, contract and required independent-review/UAT evidence.
3. Diagnose CI; make only clearly mechanical in-scope corrections on the task branch, without a concurrent writer.
4. Reuse valid evidence and rerun failed checks for an established mechanical/infrastructure cause; follow `VERIFICATION_POLICY.md`, not a second full-suite ritual.
5. Merge an accepted candidate after required PR CI/review/UAT, with an exact-head guard where supported.
6. Read back canonical main and verify its exact push CI before reporting integration complete.
7. Update only documentation whose meaning changed: current outcomes/gates in `CURRENT_STATUS.md`, durable concepts in
   `PROJECT_WIKI.md` or their owning procedure. Keep dated records intact; add a linked later receipt when needed.
   A handoff, CI poll or unchanged candidate does not require another Wiki/status/closeout edit.

Tool access alone grants no authority; the standing delegation above does. Workers cannot adopt it by changing their role label.
A post-review nonsemantic correction may retain earlier semantic review only after the Integrator proves the exact diff changes no executable/product/financial meaning.
Standard mechanics never authorize new product/financial semantics, architecture/invariants, migration/data reinterpretation,
privacy/runtime/network-boundary expansion, behavior-changing fixes outside accepted scope or missing review/UAT evidence.
Those cases return to the task/decision path; a green rerun does not replace a missing decision.
Force-push, destructive reset/rebase, branch/tag deletion, release publication and repository settings require their separate explicit authority.

<a id="linked-handoff-receipts"></a>
## Linked handoff receipts

Use the existing issue/PR and review/acceptance notes, not another process ledger.

- **Worker:** one concise delivery receipt with the AGENTS completion fields: exact baseline/target/candidate,
  branch/workspace identity, changed files/stat, actual checks and limitations, final Git read-back.
  Link existing CI/check evidence rather than copying logs or acceptance criteria into every handoff.
- **Reviewer:** link that candidate and inspected diff/check evidence; report findings or the bounded verdict,
  with unresolved source-access/check limits. A failed setup remains UNVERIFIED. Independent review follows MODEL_ROUTING.
- **Integrator:** link the Worker/review receipts and any required Owner UAT; state acceptance or remaining gates.
  Integration, when authorized, adds the actual merge SHA and exact-main CI. Delivery/review alone is not acceptance or merge authority.

Reference applicable earlier evidence with its original SHA/scope and the proved intervening diff.
Keep full logs in their existing evidence location; use links plus the conclusion in these receipts.

## Staged integration for parallel slices

Use temporary `integration/*` staging early when sibling tasks overlap shared application structure or must be Owner-UATed together; main remains the only release source.
- Each task retains its isolated child branch/workspace; Workers do not merge siblings or independently refresh from main.
- Integrate an exact accepted head promptly and run proportional integration smoke, not a mandatory extra full suite.
- Later candidates should use the current accepted staging context when practical or prove compatibility; baseline reconciliation is Integrator-owned.
- Shared routing/navigation/configuration reconciliation has one owner. Prefer leaf changes and additive/declarative registration where appropriate; no permanent list of UI filenames.
- Preserve each accepted task contract. A semantic conflict returns to an Integrator decision, not a Worker choosing which sibling wins.
- Owner UAT uses one exact aggregate SHA containing accepted slice ancestry, with its own required CI/evidence.
- Required financial/mutation/Monthly Close/restore/migration/runtime/provider review and Owner gates still apply before canonical main.
- After PASS, integrate that tested aggregate tree or a proven exact-equivalent tree, then verify exact-main push CI. Do not reconstruct an unproven aggregate after UAT.

## Mode B — experimental Codex `$delivery-loop` (explicit opt-in)

Only an explicit instruction to run the loop/orchestrated queue activates this mode. Mentioning, auditing or editing it is not activation.
Record the opt-in and a concrete coordination reason (independent workstreams, multiple repos/PRs, dependencies/context boundaries or an explicit experiment).
Importance, high risk and a need for review alone are not coordination reasons. An explicit experiment may still have one Worker.
The launch identifies repo/eligible issues, exact baselines/targets, branches, physical workspaces, queue mode and review requirement.

The root coordinates; after delegating implementation it does not become a second writer. Each Worker owns its frozen candidate and verification.
The root assesses the actual candidate; required independent review uses a separate Reviewer. Remediation returns to the same Worker.
One remediation cycle is the default; a second needs explicit authorization, with the existing absolute cap of two.
Internal outcomes are `INTERNAL_ACCEPT`, `FIXES_REQUIRED`, `BLOCKED` or `BLOCKED_FOR_INTEGRATION`; none equals project ACCEPT or permission to merge.

### Overhead budget

Start with one Worker and at most one independent Reviewer role. Extra writers/roles/replacement sessions need a concrete coordination benefit and explicit authorization.
Do not add readiness-only model turns, nested delegation, speculative explorers or reviewers-of-reviewers by default.
Use small environment checks and existing valid evidence; required safety/review gates are not waived for a session budget.
Normal completion does not require model/provider identity, usage telemetry or a phase-by-phase ledger.

## Queue policy

### Single

Implement/report the assigned task, then stop.

### Independent queue

Advance only through explicitly listed eligible tasks, each with its own branch/workspace and exact baseline, after the prior task reaches INTERNAL_ACCEPT.
An earlier candidate is not an implicit baseline for the next task; do not invent extra backlog work.

### Dependency / integration block

Without an authorized safe baseline/dependency strategy, a dependent task is BLOCKED_FOR_INTEGRATION.
Only that chain is blocked; unrelated listed tasks may continue. Do not invent stacked history or merge canonical/integration branches to bypass the block.

## Review triggers

Use MODEL_ROUTING risk policy; requiring review does not activate a queue or expand scope.

## Reporting

### Per-task report

Use the single completion contract in AGENTS.md. An explicit experiment may add measured experiment evidence, not compulsory unknown telemetry.

### Final queue report

List every authorized task, internal status, candidate SHA, review path and unresolved Integrator action. This is not batch project acceptance.

## Local Codex skills

Local `$delivery-loop`/helper skills are optional mechanics, not competing policy. Keep implicit loop invocation disabled.
Local paths, concrete model choices and config stay machine-local. Changes here do not silently modify installed skills/config.

## Invariants that automation does not weaken

The shared financial, privacy/runtime, workspace, authority and evidence boundaries apply unchanged to every execution mode.
