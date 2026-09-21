# Orchestration benchmark — 2026-09-21

## Decision and scope

Default bounded implementation to one Worker. Add independent review under the existing risk policy. Preserve full orchestration as experimental and explicit opt-in only.

This is a workflow experiment on one historical frontend issue, not project acceptance of either product candidate and not proof that orchestration never helps. No candidate is selected for integration. The routing change is reversible through a future explicit policy decision.

## Exact evidence

- Task: [#367 — Monthly Close step navigation](https://github.com/LTstripes/hermes-finance/issues/367).
- Common baseline: `9cdcabdd0ea4d11664bc51d3a585ff23ccfdb5be`.
- A: branch `bench/367-single-worker`, candidate `188c941904428b708d161140d9fd380f79861e0c`.
- B: branch `bench/367-orchestrator-clean`, candidate `291cd069f1f9fc2b62c20d1bb77b3614d71016b1`.
- Primary task records: `01a0c0b5-1c1e-71b2-8144-6095eba53739` (A) and `01a0c0b5-6c18-71b1-b63d-6015d51a2151` (B).

The review inspected both task records and the actual baseline-to-candidate Git diffs. Product suites were not rerun during this workflow-policy review. Test outcomes below are attributed to the recorded runs, not new verification. The supplied historical control PR #368 was not needed or inspected; similarity to it is not a scoring criterion.

| Dimension | A: single Worker | B: Orchestrator |
| --- | --- | --- |
| Task duration from recorded turn metadata | 21m 50.528s | 62m 34.037s |
| Human interventions after launch, reported | 0 | 0 |
| Finished committed candidate, reported | Yes | Yes |
| Root model sessions | 1 | 1 |
| Delegated model sessions, reported | 0 | 5: 2 Workers, 2 candidate reviews, 1 reviewer readiness turn |
| Total model sessions including root | 1 | 6 |
| Role handoffs, reported | 0 | 4 |
| Candidate cycles / abandoned lineages | 1 / 0 | 2 / 1 |
| Independent candidate review | None | Yes; no code blockers reported |
| Final targeted frontend tests, reported | 11 passed | 10 passed |
| Final full frontend tests, reported | 407 passed with extended timeout | 406 passed with extended timeout |
| Full synthetic visual audit, reported | 46 passed, 2 skips | 43 passed, 2 skips |

The observed wall-time ratio was about 2.86. Five delegated sessions in B must not be compared with A's one total session as if those were the same measure. Token usage/cost was not established and must not be inferred from duration or session count.

## What the actual diffs establish

A changes five files. It adds a stable target on the current-action panel, scrolls actionable steps there, and retains row navigation for steps without a primary action. It adds an explicit non-actionable deep-link test, asserts no additional component fetch, and adds a synthetic browser regression checking both heading/CTA viewport visibility and absence of mutating requests. The three browser viewports in the report are desktop sizes; this is not narrow/mobile evidence.

B changes two files. It points hash-selected steps at the current panel and extends the existing component test for scroll target, selected state and CTA route. Its final diff has no new browser regression or dedicated non-actionable regression. Fewer changed files is a smaller implementation surface, but is not evidence of greater correctness. The broader audit does not substitute for a dedicated click-to-visible-CTA browser assertion.

Both preserve the existing hash selection and action routing code and leave backend/financial/provider code untouched. The candidates differ for non-actionable steps; this review does not declare B's behavior a blocker without a stronger requirement. There is no demonstrated product-quality improvement sufficient to justify full orchestration for this bounded task.

## Useful review and confounders

B's independent review caught a historical benchmark isolation violation: the first Worker queried a post-baseline code graph. That lineage was discarded and a fresh Worker repeated implementation from the permitted baseline. This is useful benchmark-integrity evidence, not a product bug found and fixed by orchestration. The final review also noted partial heading occlusion by the sticky header without reporting a CTA-visibility blocker.

The discarded lineage accounts for some overhead, so the full 62 minutes cannot be treated as the intrinsic cost of every orchestrated run. The model mixes also differ, and one run is not a statistical estimate. Both reports include formatting/environment caveats; test counts alone do not measure test quality.

Independent review remains valuable and can follow a single Worker without the full orchestration process. That third route was **not benchmarked** here; its latency, cost and defect yield remain unknown.

## Follow-up experiment

Only run another experiment on explicit request. Compare three separately isolated arms: single Worker, single Worker plus independent Reviewer, and full orchestration. Keep the issue, full baseline, acceptance criteria, tool/environment availability, verification requirements and delivery boundary fixed. Record model/effort where actually observable and control or disclose model differences.

Carry historical-source restrictions into every participant's initial assignment. If a graph is newer than the allowed baseline, skip it before any symbol query and use baseline source. Do not expose candidates to each other or the historical solution before evaluation is complete.

Report total and delegated model sessions separately, human interventions, product defects found, review-induced corrections, duplicated work, abandoned lineages, phase/wall time, and measured usage when available. Include failed attempts in total cost and disclose benchmark-specific recovery separately. Rerun enough representative bounded and genuinely multi-workstream tasks before considering any automatic orchestration policy. Keep automatic invocation off unless that later policy change is explicitly authorized.
