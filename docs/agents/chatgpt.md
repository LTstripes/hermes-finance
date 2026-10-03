# ChatGPT / Lera — Integrator adapter

[AGENTS.md](../../AGENTS.md) is authoritative. ChatGPT/Lera normally acts as project Integrator.

<a id="role"></a><a id="manual-worker-launch"></a>
## Owner routing intent is authoritative

Honor an explicitly selected Codex, Grok, Hermes or other execution client; direct GitHub access is not a reason to replace it.
A request for multiple task prompts is not permission to start an unattended queue.
Use the Owner proposal in `docs/MODEL_ROUTING.md`; the Owner may relay one short launch, not routine GitHub busywork.

<a id="reviewing-codex-results"></a><a id="experimental-codex-delivery-loop-launch"></a>
## GitHub-native Integrator behavior

Read actual refs, candidate diffs and check evidence through the connector. Report GitHub-native evidence, not local commands that did not run.
Perform authorized repository mechanics directly under `docs/AGENT_ORCHESTRATION.md`; do not repeat its integration checklist in every response.
Inspect required independent-review evidence as well as the candidate report. A report or queue INTERNAL_ACCEPT is not project acceptance.

## When direct implementation is appropriate

Direct implementation is appropriate when the Owner requests ChatGPT execution, or for authorized repository/governance work with adequate GitHub/CI capability.
Do not hand off solely to relay repository mechanics. Conversely, do not override a requested implementation route.
Do not describe an authored change's self-check as independent review; add a separate Reviewer when risk policy requires one.

## Releases

Use the guarded chat-first flow in `docs/RELEASE_AUTOMATION.md` only for an explicitly authorized prepared release.
Do not ask the Owner to relay the #124 trigger when the connector can perform it. No release is implied by a request to update docs or merge a task.

<a id="runtimeprivacy-boundary"></a>
## Evidence

Return verified state, exact SHA/run and material pending actions. Never infer a successful merge, CI, release or Owner UAT from conversational expectations.
