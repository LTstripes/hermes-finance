# Model routing — roles, risk and escalation

Provider-neutral routing and review policy. Role ownership is defined in [AGENTS.md](../AGENTS.md#roles).
Read this file when selecting an execution/review route or resolving risk, not as a second implementation manual.

## Roles

Select capability per task, not a permanent vendor/model/effort roster.
Independent review uses a separate context without implementation ownership; Worker self-review is not independent evidence.

## Risk classes

| Risk | Surface | Review |
| --- | --- | --- |
| Low | Docs, bounded tests, cosmetic UI, mechanical changes | Integrator diff review is normally enough; separate review only when requested or a concrete risk warrants it. |
| Medium | Backend/frontend behavior or APIs under established contracts | Capable Worker; independent review when cross-cutting/material behavior, an explicit request or execution findings warrant it. |
| High | Financial meaning, migration/data reinterpretation, privacy/security, runtime/network, destructive Git operations, new architecture | Strong Integrator and independent Reviewer; resolve contract ambiguity before implementation. |

A faster/newer model never lowers the required review/UAT bar. Newly discovered risk may raise review requirements, not silently expand scope.
Do not add a Reviewer or coordinator merely because the task uses more than one file or includes tests.
Reviewers use the candidate's actual diff and verified check evidence; verification locality/repeats are owned by `VERIFICATION_POLICY.md`.

## Escalation

Escalate undefined money/rate units, rounding or financial source of truth; potentially lossy migrations;
private-data requirements; changed tax/return/income/capital/goal semantics; new scope/architecture or an out-of-scope contract failure.
Ordinary implementation choices under a defined contract remain the Worker's responsibility.

## Owner task proposal

Propose in plain Russian:
1. Name and concrete result/value in one or two sentences.
2. Complexity (небольшая / средняя / сложная) with reason; state risk separately.
3. A concrete Codex model/available effort and an external model/provider/client alternative, with brief preference/confidence. Do not invent availability.
4. Only the required independent review and Owner/private actions, with their reason.
5. One short copyable launch: repo/issue/note, role, exact baseline/target, task branch/workspace policy, intended result and authorized delivery.

The issue/accepted contract holds acceptance criteria; do not duplicate it in the prompt.
**Owner preference: normally 5–10 lines for a Worker launch or remediation prompt.** Link the exact issue/review note instead of copying its requirements, test matrix or invariants. New-session prompts point to the latest closeout and pending decisions, not a second project manual. Longer prompts require a specific request or genuinely missing authoritative scope.
Use standing workspace self-create where applicable; do not invent a root, SHA or missing safety-critical authorization.
Choose one execution route at launch. An alternative may be unavailable/not recommended; say so rather than manufacture a choice.

Model choice is routing only. Normal task handoffs do not request or persist runtime model/provider identity, benchmark grades or usage telemetry.

<a id="codex-local-orchestration"></a>
## Execution modes

Ordinary execution is one Worker; special queue/delegation mechanics live only in `AGENT_ORCHESTRATION.md`.
Local configuration selects models; routing policy neither activates orchestration nor grants canonical integration authority.

## What this file is not

Not a vendor ranking, client skill/config manual or permission for an execution coordinator to self-integrate.
