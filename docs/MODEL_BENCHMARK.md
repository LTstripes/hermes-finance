# Model evidence journal — Hermes Finance

Protocol: `model-evidence-v1`, 2026-09-27. This is a dated observational journal, not a permanent model ranking or a release gate replacement.

Coordination/intake: [Finance #605](https://github.com/LTstripes/hermes-finance/issues/605). Paired journal: [Health-Check #210](https://github.com/LTstripes/Health-Check/issues/210) and its `docs/MODEL_BENCHMARK.md`.

## Source of truth and maintenance

The exact issue contract, candidate diff, CI, independent review and Integrator disposition remain authoritative. This document is their compact index. Discussion and new reports go to #605; the accepting Integrator updates this index and links the applicable execution-history entry. Do not create a second competing tracker or ask every Worker to edit shared journal files.

Record rejected, abandoned and still-pending attempts as well as successes. A correction changes an attempt's outcome, not its original first-pass result. Subsequent regressions/UAT failures are appended, never erased from the history. Historical grades already in #605 remain historical assessments until their exact source packets are indexed; they are not silently combined with this cohort.

## One case, several attempts

A case is `(repository, issue, role, assigned baseline, initial candidate, execution route)`. Follow-up SHAs are attempts of the same case, not additional independent successes. Record Worker, Reviewer and research/critique roles separately. A model/provider/version switch or fallback chain is explicit; it cannot be credited as a pure single-model result.

| Field | What to record |
| --- | --- |
| Task | Repo/issue/PR, profile (UI, financial write, provider, research, review, etc.), complexity and risk separately |
| Execution | Actual model and provider/client reported for the task. Other runtime metadata is optional and recorded only when independently available. |
| Attribution | The Integrator may note whether model/provider identity was runtime-confirmed, Owner-reported, Worker-reported or otherwise uncertain; Workers are not required to supply a separate attribution field. |
| Identity | Assigned baseline, first candidate, reviewed candidates, accepted/merged SHA, source links |
| Quality | First-pass verdict, unique confirmed blockers, severity, escaped defects, scope discipline |
| Rework | Substantive correction rounds; formatting-only commits, duplicate review comments and unchanged-SHA reruns do not add rounds |
| Evidence | Actual targeted/full/API/browser/CI results; local-reported versus independently inspected; missing evidence explicit |
| Outcome | Candidate review, leaf merge, shared integration, independent review and Owner UAT are separate states |
| Cost/time | Measured tokens/API spend/quota, active work/review/test time and waiting time only when known; otherwise `unknown` |
| Confounders | Unclear assignment, missing review locator, scope change, resource contention, tool isolation or provider outage |

Do not count an incorrect reviewer finding as a model defect. Record an Integrator mistake separately. A green rerun proves that attempt passed, not the cause of an earlier failure. Subscription access is not zero resource cost; API list prices do not measure this run's cost.

### Result categories

Retain #605's A/B/C/D vocabulary only for a completed case at an explicitly named stage: A = accepted first substantive candidate; B = accepted after 1–2 bounded correction rounds; C = accepted after 3+ substantive rounds or material contract drift; D = abandoned/replaced implementation. `PENDING`, `BLOCKED` and `UNVERIFIED` are not D. State confounders beside the grade; no grade without a source-supported outcome. Do not manufacture plus/minus precision or an overall 100-point leaderboard.

For group summaries show numerator/denominator, task profile, client/provider and attribution coverage. Compare like-for-like risk/roles and list unresolved cases separately. Small, heterogeneous samples support provisional routing only, not claims such as 'MiMo equals Sol' or 'Muse is worse than Astra'. Five comparable cases are a useful next collection target, not a statistical guarantee.

## New task proposal

Add two recommendations to the existing short Owner card: **Codex option** (model + supported effort) and **external option** (model + provider/client). Explain preference/confidence in one sentence. Either option can be `not recommended yet` or unavailable; do not invent a candidate to fill the row. The Owner chooses based on access and workload; launch pins the chosen route. Required independent review does not depend on the price of the Worker.

Start new/anonymous/temporary-free models on bounded, noncritical work with synthetic inputs. Keep their dated route IDs distinct; do not guess the vendor behind an alias or assume a preview stays free. Do not add an application integration, telemetry collector or automatic evaluation queue.

## Resource-aware execution

One primary Worker; at most two genuinely independent writers in isolated assigned workspaces when resources permit. Only one heavyweight local verification process at a time across both projects and all clients: full Vitest, browser/Playwright, production build or substantial backend suites. Full local Finance Vitest uses `--maxWorkers=1` under the current laptop assignment; CI gates are unchanged. Record workload conditions, do not exclude failing tests or weaken assertions. Do not kill another task's or Owner runtime's processes. These scheduling limits are separate from model quality.

## Initial UI cohort — snapshot 2026-09-27

All six cases started at `85074def23452243830738d7e57f923d80c6f80d`, as leaf-only frontend implementations with high financial-write risk. Model attribution below is **Owner-reported**, not runtime-confirmed; exact provider/tier/effort and client versions are unknown unless separately recorded. No cross-model blind A/B was run. All first substantive candidates received FIXES REQUIRED.

| Case / PR | Owner-reported Worker | First candidate | Latest reviewed candidate | Completed substantive rework rounds | Observed disposition |
| --- | --- | --- | --- | --- | --- |
| [#559 / #599](https://github.com/LTstripes/hermes-finance/pull/599) income | OpenCode / MiMo 2.6 Flash; effort unknown | `0c22eb3f142918de515a9880c88af836845ac409` | `4c4c7ca98261aa74eb2420e32a2d4bd5337aa64e` | 1 | Leaf accepted/merged; partial-save retry duplication fixed |
| [#560 / #601](https://github.com/LTstripes/hermes-finance/pull/601) assets | OpenCode / MiMo 2.6 Flash; effort unknown | `32a2f0fc374fb77e83ccd4408453f5322d084e35` | `9841c896853f344fc5d547121c10ab9bbf7b0ce5` | 3 | Leaf accepted/merged; complete readback, exact rate rounding and safe create recovery fixed |
| [#561 / #597](https://github.com/LTstripes/hermes-finance/pull/597) positions | Codex / Sol High; runtime ID/effort unconfirmed | `155b7ab83d56836a5d6ff03bcdf74e0b34b8ba30` | `e3813db6306c8bb7b0712d617fb1a357b8f6e825` | 1 | Leaf accepted/merged; in-flight draft loss fixed |
| [#562 / #596](https://github.com/LTstripes/hermes-finance/pull/596) payouts | OpenCode / Muse Spark 1.3; tier/effort unknown | `b3b1cb637cb3ebcadd04999eb0585ff0476f8f70` | `82445c07577063ba31be180a0b8c6d47451ced93` | 3 | Leaf accepted/merged; lifecycle/readback fixes retained and 390px readability corrected |
| [#563 / #595](https://github.com/LTstripes/hermes-finance/pull/595) budget | OpenCode / Muse Spark 1.3; tier/effort unknown | `436081858060905111aaba42ab2c9b0b27ac5537` | `d4f30b11bd31af43843de1408f80ffd6b7058976` | 1 | Leaf accepted/merged; per-operation confirmation and draft preservation fixed |
| [#564 / #600](https://github.com/LTstripes/hermes-finance/pull/600) liabilities | OpenCode / MiMo 2.6 Flash; effort unknown | `61695417dd2d7bb93eeebb76fe8bc8f05cef6806` | `485eeb015c11813710766db1a874900905e78326` | 1 | Leaf accepted/merged; foreign reads and in-flight draft loss fixed |

Accepted leaf merges: #559 `a9cdfcb9eb8fc23cd4357e2cf3f66f6abd7444a8`; #560 `a02e6856a428ffb120f98e96d5577e08cfcf752c`; #561 `efdf53e1f4969b95d4898e118ad76ddfc323cba6`; #562 `b12406d47f329d845198ed2d8aaa98f914555b12`; #563 `7782c50306c567d5ee729dd2ca9c3354dd7a3f98`; #564 `7a303dcc19789ad686799c9e311b965eaa0ad395`.

Primary checkpoints: [#554 comment 5857743491](https://github.com/LTstripes/hermes-finance/issues/554#issuecomment-5857743491) and the later cohort closeout recorded in #605/#554. Final leaf acceptance comments: #560 `5858629016`, #562 `5858633388`.

All six final leaf candidates have successful exact-head CI/UI workflow pairs. Individual green workflows are not aggregate UI coverage. None of the six is marked Owner-UAT-complete here; shared editor wiring and aggregate verification remain separate. Active time, token usage, cost and escaped-defect counts are **unknown** for this cohort unless later recovered from client/runtime evidence; unknown is not zero.

Confounders: #560's first corrective prompt omitted part of an earlier review; do not blame that extra coordination solely on MiMo. Multiple local full suites competed for the laptop; full-suite failures and serialized passes are recorded, but infrastructure causality is not proven for every failure. #562's narrow table issue is inherited presentation debt surfaced by new evidence, not automatically a new functional regression. More than one review comment on the same candidate is one round, not two.

## Provisional use, not a leaderboard

This cohort supports continuing MiMo/Muse as bounded Workers under frozen contracts and strong review; both have delivered useful accepted leaf code. It does not establish equivalence with Sol/Astra, readiness for architecture/migrations, or superior review ability. Sol also required a fix on its one cohort task. Astra has no Worker case in this six-task cohort; the separate Performance observations in #605 must remain a separate profile until their evidence is indexed.

DeepSeek V4.1 Flash, LongCat 2.5 Preview and Space Bunny are Owner-available trial candidates, **not yet scored in this cohort**. Availability is checked at launch. For an anonymous alias, retain `provider/vendor unknown` where applicable. A future small read-only detail or contained UI/test task is preferable to starting on migrations, private provider state or the shared month-editor spine.

## Recent validated cases

### #607 — shared month-editor wiring

- implementation profile: shared frontend lifecycle integration;
- baseline: `b12406d47f329d845198ed2d8aaa98f914555b12`;
- candidate: `4e90f84397253d5ecf02c702710c0719ef5b7a73`;
- requested route: Codex / Astra Medium;
- actual implementation model/provider/effort: **unknown / unknown / unknown** (configuration was not treated as runtime proof);
- substantive fix rounds: **0**;
- Integrator preflight: PASS;
- independent Reviewer: **Grok 4.7**, runtime-confirmed by session system prompt, ACCEPT;
- staging merge: `5d1e0a9c15b9e1555d41d041a651fc22c55e6343`;
- result at staging integration stage: **A**;
- Owner UAT/main: pending #572;
- usage/cost/time: unknown.

Do not credit this implementation A to Astra because actual Worker identity was unavailable. Reviewer evidence may count for Grok 4.7 in the review profile.

### #565 — native Alfa baseline preview/apply

- implementation profile: high-risk import preview/apply frontend integration under an existing backend contract;
- baseline: `5d1e0a9c15b9e1555d41d041a651fc22c55e6343`;
- first candidate: `36cac90a7642427ddfd669f61c1337e5baa4ac59`;
- accepted candidate: `6f3299601b23d0d76b74c98a40939b1a1ad88d98`;
- actual Worker: **gpt-6-astra / medium**, runtime-confirmed by task turn metadata; provider not independently recorded;
- substantive fix rounds: **1**;
- first-pass blockers: explicit-month fail-closed and Monthly Close v2 native Alfa routing;
- final Integrator: ACCEPT;
- independent Reviewer: **Grok 4.7**, session-system-prompt identity, ACCEPT;
- exact-head CI/UI: `36396394916` / `36396394471` SUCCESS;
- staging merge: `aa139e8aa18ccfcb67203d3e0ae1dee1a08c4d38`;
- result at staging integration stage: **B**;
- Owner UAT/main: pending aggregate gate;
- usage/cost/time: unknown.

Interpretation: this is the first runtime-confirmed Astra Medium case in this journal on a high-risk existing import/write boundary. It supports Astra Medium for bounded lifecycle/integration work with a frozen backend contract, while independent import/data-integrity review remains required.

### #566 — native payout calendar + forecast preview/apply

- implementation profile: high-risk provider payout preview/apply frontend integration over existing backend contracts;
- baseline: `aa139e8aa18ccfcb67203d3e0ae1dee1a08c4d38`;
- first candidate: `27281860c841af51c1a4f5a180f0a38899b48271`;
- accepted candidate: `5029d13d10d3f40c74349e6dda2948044b960863`;
- Worker route: **OpenCode / opencode-go / muse-spark-1.3-contributor**;
- identity source: worker-reported for model/provider; requested xhigh was Owner-reported, runtime effort not independently confirmed;
- substantive correction rounds: **3**;
- confirmed correction themes: exact preview identity; authoritative payout/readiness readback; stale confirm/context lifetime; submitted/result cardinality; canonical manual-calendar representation via `linked_provider_payout_id`;
- final Integrator: ACCEPT;
- independent Reviewer: **Grok 4.7 / xAI**, runtime-confirmed, ACCEPT after one blocker/fix/re-review cycle;
- exact-head CI/UI: `36419509281` / `36419509314` SUCCESS on accepted candidate;
- task-specific Chromium desktop/390px evidence: Worker-reported local, not an exact-head CI job;
- staging merge: `f04353f1745a8c89f4994e9b0fd2c52e28c37a69`;
- result at staging integration stage: **C**;
- Owner UAT/main: pending aggregate gate;
- usage/cost/time: unknown.

Interpretation: Muse Spark successfully delivered the frozen-contract provider/apply feature, but required three substantive lifecycle/data-integrity correction rounds. This supports keeping it as a cost-effective bounded Worker when strong Integrator and independent Reviewer gates are available; it is not evidence to waive those gates on provider/apply work.

### #567 — native statement import

- implementation profile: high-risk private-file statement import / financial write frontend integration over existing backend contracts;
- baseline: `f04353f1745a8c89f4994e9b0fd2c52e28c37a69`;
- first candidate: `7655717f056b3fc74f2cdc547b2cb7dfda33c168`;
- accepted candidate: `495f99cf6ad93b7ee7916a4b4c6eaedb53d87ceb`;
- Worker route: **OpenCode / opencode-go / mimo-v2.6-flash**;
- identity source: **runtime_confirmed**; effort unknown;
- delegates/fallbacks: none;
- substantive correction rounds: **1**;
- confirmed correction themes: native selected-month scope over a canonical cross-month backend, exact statement-event/material post-apply proof, and fail-closed 5xx/network ambiguity handling;
- final Integrator: ACCEPT;
- independent Reviewer: **Grok 4.7 / xAI**, ACCEPT, no blockers;
- exact-head CI/UI: `36467058094` / `36467057893` SUCCESS;
- task-specific Chromium/real-backend evidence: Worker-reported local, not an exact-head CI job;
- staging merge: `f27c33dff940315827d7b9231146945a43b16273`;
- result at staging integration stage: **B**;
- Owner UAT/main: pending aggregate #572;
- usage/cost/time: unknown.

Interpretation: MiMo 2.6 Flash completed a private-file financial-import integration after one bounded correction round. This is stronger evidence than the earlier CRUD-only MiMo cases, but privacy/data-integrity review remains mandatory for this task profile.

## Lightweight case template

```text
case_id / role / profile / complexity / risk:
issue / PR / contract link / baseline:
model:
provider/client:
first SHA -> attempts -> accepted SHA:
first-pass verdict / substantive fix rounds / confirmed blockers:
scope / test & browser evidence / independent review:
leaf integration / aggregate integration / Owner UAT:
optional measured telemetry if independently available / confounders:
provisional use / avoid / next evidence needed:
```

Worker handoffs use the standard `Model evidence` block from `AGENTS.md` in both Finance and Health-Check. Exact usage/cost/time/delegate fields are reported only when exposed by the runtime; otherwise they are written as `unknown`. The Integrator records benchmark outcomes after review and keeps implementation and Reviewer attribution separate.

Only technical metadata, synthetic-safe summaries and source links belong here. Never include Owner finance/health values, DBs, credentials, private screenshots, raw provider payloads or unsanitized model transcripts. Controlled blind A/B requires a separate explicit assignment with identical contract/baseline and no candidate cross-reading; normal outcome logging does not activate it.
