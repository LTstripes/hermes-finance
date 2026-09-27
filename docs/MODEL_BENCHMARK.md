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
| Execution | Client/version, requested model/effort, actual runtime model ID/provider/effort, fallback/delegates |
| Attribution | `runtime_confirmed`, `owner_reported`, `worker_reported`, `assigned_only`, or `unknown`; a model-picker label is not runtime proof |
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
| [#560 / #601](https://github.com/LTstripes/hermes-finance/pull/601) assets | OpenCode / MiMo 2.6 Flash; effort unknown | `32a2f0fc374fb77e83ccd4408453f5322d084e35` | `79f7b7b3286f9db49581b499485f4d72423bd972` | 2 | Pending: new rate confirmation disagrees with canonical basis-point rounding; known-success create recovery needs protection |
| [#561 / #597](https://github.com/LTstripes/hermes-finance/pull/597) positions | Codex / Sol High; runtime ID/effort unconfirmed | `155b7ab83d56836a5d6ff03bcdf74e0b34b8ba30` | `e3813db6306c8bb7b0712d617fb1a357b8f6e825` | 1 | Leaf accepted/merged; in-flight draft loss fixed |
| [#562 / #596](https://github.com/LTstripes/hermes-finance/pull/596) payouts | OpenCode / Muse Spark 1.3; tier/effort unknown | `b3b1cb637cb3ebcadd04999eb0585ff0476f8f70` | `b75f339f274e40873d55ca5f53507438191cf412` | 2 | Prior lifecycle/readback fixes confirmed; mobile readability gate pending |
| [#563 / #595](https://github.com/LTstripes/hermes-finance/pull/595) budget | OpenCode / Muse Spark 1.3; tier/effort unknown | `436081858060905111aaba42ab2c9b0b27ac5537` | `d4f30b11bd31af43843de1408f80ffd6b7058976` | 1 | Leaf accepted/merged; per-operation confirmation and draft preservation fixed |
| [#564 / #600](https://github.com/LTstripes/hermes-finance/pull/600) liabilities | OpenCode / MiMo 2.6 Flash; effort unknown | `61695417dd2d7bb93eeebb76fe8bc8f05cef6806` | `485eeb015c11813710766db1a874900905e78326` | 1 | Leaf accepted/merged; foreign reads and in-flight draft loss fixed |

Accepted leaf merges: #559 `a9cdfcb9eb8fc23cd4357e2cf3f66f6abd7444a8`; #561 `efdf53e1f4969b95d4898e118ad76ddfc323cba6`; #563 `7782c50306c567d5ee729dd2ca9c3354dd7a3f98`; #564 `7a303dcc19789ad686799c9e311b965eaa0ad395`.

Primary checkpoint: [#554 comment 5857743491](https://github.com/LTstripes/hermes-finance/issues/554#issuecomment-5857743491). Current remaining findings: [#560 comment 5858294059](https://github.com/LTstripes/hermes-finance/pull/601#issuecomment-5858294059), [#562 comment 5858296630](https://github.com/LTstripes/hermes-finance/pull/596#issuecomment-5858296630).

All latest reviewed candidates have successful CI/UI workflow pairs; the two pending cases were checked against their exact SHAs. Individual green workflows are not aggregate UI coverage. None of the six is marked Owner-UAT-complete here. The four accepted leaves are still unwired in the checkpoint. Active time, cost and escaped-defect counts are **unknown**, not zero.

Confounders: #560's first corrective prompt omitted part of an earlier review; do not blame that extra coordination solely on MiMo. Multiple local full suites competed for the laptop; full-suite failures and serialized passes are recorded, but infrastructure causality is not proven for every failure. #562's narrow table issue is inherited presentation debt surfaced by new evidence, not automatically a new functional regression. More than one review comment on the same candidate is one round, not two.

## Provisional use, not a leaderboard

This cohort supports continuing MiMo/Muse as bounded Workers under frozen contracts and strong review; both have delivered useful accepted leaf code. It does not establish equivalence with Sol/Astra, readiness for architecture/migrations, or superior review ability. Sol also required a fix on its one cohort task. Astra has no Worker case in this six-task cohort; the separate Performance observations in #605 must remain a separate profile until their evidence is indexed.

DeepSeek V4.1 Flash, LongCat 2.5 Preview and Space Bunny are Owner-available trial candidates, **not yet scored in this cohort**. Availability is checked at launch. For an anonymous alias, retain `provider/vendor unknown` where applicable. A future small read-only detail or contained UI/test task is preferable to starting on migrations, private provider state or the shared month-editor spine.

## Lightweight case template

```text
case_id / role / profile / complexity / risk:
issue / PR / contract link / baseline:
client + requested model/effort:
actual model/provider/effort + attribution source (or unknown):
first SHA -> attempts -> accepted SHA:
first-pass verdict / substantive fix rounds / confirmed blockers:
scope / test & browser evidence / independent review:
leaf integration / aggregate integration / Owner UAT:
measured time/cost (or unknown) / confounders:
provisional use / avoid / next evidence needed:
```

Only technical metadata, synthetic-safe summaries and source links belong here. Never include Owner finance/health values, DBs, credentials, private screenshots, raw provider payloads or unsanitized model transcripts. Controlled blind A/B requires a separate explicit assignment with identical contract/baseline and no candidate cross-reading; normal outcome logging does not activate it.
