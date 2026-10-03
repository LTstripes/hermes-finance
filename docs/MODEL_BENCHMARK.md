# Model evidence journal — Hermes Finance

Protocol: `model-evidence-v1`, 2026-09-27. This is a dated observational journal, not a permanent model ranking or a release gate replacement.

Coordination/intake: [Finance #605](https://github.com/LTstripes/hermes-finance/issues/605). Paired journal: [Health-Check #210](https://github.com/LTstripes/Health-Check/issues/210) and its `docs/MODEL_BENCHMARK.md`.

## Source of truth and maintenance

The exact issue contract, candidate diff, CI, independent review and Integrator disposition remain authoritative. This document is their compact index. Discussion and new reports go to #605; the accepting Integrator updates this index and links the applicable execution-history entry. Do not create a second competing tracker or ask every Worker to edit shared journal files.

Record rejected, abandoned and still-pending attempts as well as successes. A correction changes an attempt's outcome, not its original first-pass result. Subsequent regressions/UAT failures are appended, never erased from the history. Historical grades already in #605 remain historical assessments until their exact source packets are indexed; they are not silently combined with this cohort.

### Owner-confirmed model identity

An explicit task-specific Owner report of the model used is sufficient to name that model in this journal. If the Worker reports `unknown`, `GPT-6` or `GPT-6 family` without a precise runtime ID, retain the Owner-confirmed model/effort label (for example **Sol High** or **Astra High**) as the case's model and mark its source **owner_reported**. A generic or unavailable runtime identity does not erase the Owner's confirmation.

Keep the raw Worker statement as a qualification where useful; do not manufacture a more specific backend model ID, provider, vendor or runtime-confirmation claim. An assistant recommendation alone is not execution evidence. A task-specific Owner selection followed by the corresponding delivery can establish the Owner-confirmed route; do not transfer that attribution to another task or to its Reviewer. If two explicit identities genuinely conflict, preserve both and flag the conflict rather than silently overwriting either.

This follows the compact runtime/Owner evidence rule already in `AGENTS.md`. Normal Worker/Reviewer handoffs still contain exactly `model` and `provider/client`; the Integrator records attribution confidence separately.

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

## Owner-confirmed attribution corrections — 2026-09-29

These are identity corrections for existing Finance cases, not new successful attempts or revised quality grades. They supersede earlier `assigned_only`, generic-family or `unknown` benchmark model labels where the Owner supplied the task-specific execution route. Source: Owner handoffs/confirmations in the Performance and Finance work chats, reconciled by the Integrator in [#605](https://github.com/LTstripes/hermes-finance/issues/605).

| Worker case | Model used for benchmark | Provider/client evidence | Owner confirmation and retained qualification |
| --- | --- | --- | --- |
| [#530 / PR #598](https://github.com/LTstripes/hermes-finance/pull/598), readiness projection | **Astra Medium** | Codex client; exact runtime ID not supplied in that handoff | Owner introduced the delivery as `astra med`; keep `owner_reported`, not runtime-confirmed. Accepted candidate `f21d020292b4b2b68d323a3e5ebbb6180d35eff4`. |
| [#532 / PR #604](https://github.com/LTstripes/hermes-finance/pull/604), Owner preparation | **Astra High** | Codex client; exact runtime ID not supplied in that handoff | Owner selected the Astra High route and returned the corresponding Astra delivery/fix. Accepted candidate `fdc812bce7640062d9b91d4bec393d7550762697`; raw runtime uncertainty remains a qualification, not the model label. |
| [#608 / PR #614](https://github.com/LTstripes/hermes-finance/pull/614), membership writer | **Astra High** | Codex desktop; provider was not confirmed in the Worker block | Owner explicitly confirmed `давай 608 и пока что Астре, да` for the Astra High launch, then supplied its delivery. Accepted candidate `f1456a6ef4132b7001bf6a6df7e847c774c18717`; raw Worker wording was `GPT-6 family`. The earlier Astra Pro chat gate analysis is a separate case, not this implementation. |
| [#621 / PR #626](https://github.com/LTstripes/hermes-finance/pull/626), month-delete invalidation | **Sol High** | Codex client | Owner supplied the delivery with `высылаю от сол хай` in Finance work chat. Candidate `1a491beb13175dd8f2187c17203a54a36800a107`. |
| [#622 / PR #633](https://github.com/LTstripes/hermes-finance/pull/633), month PATCH/Close | **Sol High** | OpenAI / Codex desktop | Owner confirmed `оба ушли сол хай` for #622/#623. Candidate `9a7d5f0a9d9f3128b19bf84c013835b3d0096f9b`; raw Worker label `GPT-6` does not supersede that confirmation. |
| [#623 / PR #634](https://github.com/LTstripes/hermes-finance/pull/634), evidence writes/Close | **Sol High** | OpenAI / Codex desktop | Same explicit Owner confirmation for the paired launch. Candidate `b0321fa3166e8c59672d16d6f9f17852ffa2a507`; raw Worker model `unknown` is retained only as a runtime-ID limitation. |
| [#624 / PR #637](https://github.com/LTstripes/hermes-finance/pull/637), ambiguous coverage | **Sol High** | OpenAI / Codex desktop | Owner explicitly says `сделал сол хай`. Candidate `9ac3f8a4bd07534e8d3aee3855ee263278005e02`; raw Worker wording `GPT-6 family`. Integrator preflight PASS, exact-head CI `36625063015` SUCCESS; independent semantics review **PENDING**, no final grade. |

Existing specific Muse/MiMo/Grok/DeepSeek labels and runtime-confirmed #565 metadata remain unchanged. #561 already names Sol High correctly. Do not resolve unrelated unknown cases merely by analogy: #607's requested Astra Medium route alone, without a separate Owner confirmation of execution, remains insufficient. Do not infer a launcher Worker model from a Reviewer identity. Health-Check cases belong to its own journal.

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

## UI-tail Owner-confirmed cases — 2026-09-29

Source: [#605 Owner-confirmation record](https://github.com/LTstripes/hermes-finance/issues/605#issuecomment-5898533940). The Owner explicitly reported `отдал оба сол хай` for #568/#569 and `оба ушли сол хай (они пишут неизвестно, в таких случаях доверяйся мне)` for #570/#571. All four Workers are **Sol High / OpenAI / Codex desktop**, attribution **owner_reported**. Their raw `unknown` or generic GPT-6 statements qualify runtime visibility; they do not replace the confirmed model label. This supersedes the earlier assigned-only/unknown attribution for these cases, without changing grades or counting duplicate successes.

| Worker case / profile | Baseline | Candidate history | Verified stage / evidence |
| --- | --- | --- | --- |
| [#568 / PR #632](https://github.com/LTstripes/hermes-finance/pull/632), medium-complexity high-risk IIS financial-write UI | `f27c33dff940315827d7b9231146945a43b16273` | First/accepted `9c72ebd095fcf23b25abc217070e34749ee1274b` | **A**, 0 substantive correction rounds, at staging integration. Grok 4.7 / xAI / Grok Build CLI independent ACCEPT. CI/UI `36606687426` / `36606687601` SUCCESS. Merge `1be28feba70bc4f94aa2c4f996cf258d516db11f`. Owner UAT/main pending #572. |
| [#569 / PR #631](https://github.com/LTstripes/hermes-finance/pull/631), medium-complexity medium-risk allocation/concentration presentation | `f27c33dff940315827d7b9231146945a43b16273` | First `2620ee7cafcf3ffe002e6480c024179f6a585a92` -> accepted `a22cb77c4c61de9eb1e493d2a392fa66f8a77585` | **B**, 1 substantive correction round, at staging integration. Fixed zero-basis/undefined-share wording and included-unallocated double-count implication. Grok 4.7 / xAI / Grok Build independent re-review ACCEPT. CI/UI `36616663581` / `36616663744` SUCCESS. Leaf merge `5e8c66b6d714028daf55566aa669e7c0952f58c4`; separate wiring PR #635 merge `0f6791c32c4926be29103ad81b3826f22bb8842d`. Owner UAT/main pending #572. |
| [#570 / PR #574](https://github.com/LTstripes/hermes-finance/pull/574), current medium-complexity docs refresh with high-risk financial/product interpretation | Refreshed against `0f6791c32c4926be29103ad81b3826f22bb8842d`; original matrix commits retained | Current refresh `9ea4a63ec205f0a20dd5f9f9d5ca40eda09fb92d` | **PENDING**, no final grade. CI `36623529216` SUCCESS. Independent financial/product review and final refresh after #571 remain pending. Sol attribution covers this refresh, not the earlier GitHub-native matrix authorship. |
| [#571 / PR #639](https://github.com/LTstripes/hermes-finance/pull/639), medium-complexity high-risk Monthly Close native wiring | `0f6791c32c4926be29103ad81b3826f22bb8842d` | First/accepted `f69d2603709a06ac483875415bef6fc247c347cc` | **A**, 0 substantive correction rounds, at staging integration. CI/UI `36627209205` / `36627209078` SUCCESS. Grok 4.7 / xAI / Grok Build CLI independent lifecycle/data-integrity ACCEPT. Merge `fb0c3b29cbf8e54df00cf7ee849a202b060de105`. Worker-reported real-backend Monthly Close harness is strong evidence but its exact acceptance spec was not executed by those CI/UI workflows; #572 must run it or an equivalent retained aggregate journey. Owner UAT/main pending #572. |

The separate attempted #571 Reviewer reported Astra Medium with a read-only runtime, but stopped before diff inspection over a callable external image-generation tool. Record **review not performed / tooling confounder**, not a Worker correction round, code rejection, independent ACCEPT or model quality grade. Do not transfer that Reviewer identity to the Sol Worker.

PR #635 shared route/link wiring was Integrator-authored. Its initial test asserted before async month loading completed; the test-only correction passed final CI/UI `36618769831` / `36618769838`. That Integrator test defect is not an extra Sol/#569 correction round.

Local checks remain Worker-reported unless independently inspected. Usage/cost/time are unknown; no additional telemetry is requested. The completed #568/#569/#571 cases and pending #570 case are not one homogeneous benchmark sample.

## Sol 6.1 version transition — 2026-09-30

Source: [Owner's version-specific confirmation in #605](https://github.com/LTstripes/hermes-finance/issues/605#issuecomment-5899778624). This later entry updates the stages below without retroactively renaming the 2026-09-29 work. Exact runtime IDs and public release metadata are not inferred from an Owner model label.

| Task / stage | Owner-confirmed execution | Exact identity / evidence | Disposition |
| --- | --- | --- | --- |
| #570 / PR #574, final UI-parity source refresh | **Sol 6.1 High / OpenAI / Codex desktop**, owner_reported | Previous Sol High refresh `9ea4a63ec205f0a20dd5f9f9d5ca40eda09fb92d` -> new head `f549bd8f7986178d488544349aed5347b64e16cf`; base `fb0c3b29cbf8e54df00cf7ee849a202b060de105`; CI `36633295520` SUCCESS | **PENDING**, independent financial/product review and common main/Performance/UI aggregate validation remain. Same task/document with an explicit model-version transition, not a pure single-model or from-scratch success. Earlier GitHub-native matrix authorship remains separate. |
| #541 Checkpoint A refresh / PR #641, cross-stream compatibility and retained browser evidence | **Sol 6.1 High / Codex desktop**, owner_reported; provider not independently disclosed | Candidate `95097f75174116f608f761f791d0ee500e9e56ca` incorporates Performance staging `a9198a46a9efedcf1e60f5628ff308ebe65952dc` and main `ee9faea0b49f08454c284deb0db926f8db981a9d`; CI/UI `36632951022` / `36632950943` SUCCESS; [Integrator preflight](https://github.com/LTstripes/hermes-finance/pull/641#issuecomment-5899638869) | **PENDING**, independent review still required. Read-only CLOSED predicate separated from writer-reserving mutation guard; canonical real-backend Performance journey added. This is one refresh/reconciliation case, not a new success for every previously accepted Performance leaf. |

Earlier #568/#569/#571 remain Sol High A/B/A at their staging stages. The #541 attempted reviewer stopped at runtime-isolation preflight before code inspection: no code verdict, no Worker correction round and no independent ACCEPT. Neither pending Sol 6.1 stage receives a final grade here; Owner UAT and release remain separate gates.

## Accepted dependency reviews — 2026-09-30

This entry supersedes the earlier pending dispositions for the two source/dependency stages above, not their historical attribution. Sources: [#605 review/outcome record](https://github.com/LTstripes/hermes-finance/issues/605#issuecomment-5900325881), [#574 Integrator ACCEPT](https://github.com/LTstripes/hermes-finance/pull/574#issuecomment-5900263443), [#641 Integrator ACCEPT](https://github.com/LTstripes/hermes-finance/pull/641#issuecomment-5900266444). The Owner supplied both independent review reports; local reviewer test results are not claimed as Integrator-executed.

| Case / role | Model and provider/client | Exact identity | Result at the named stage |
| --- | --- | --- | --- |
| #570 / #574 final UI-source refresh, Worker stage | Sol 6.1 High / OpenAI / Codex desktop, owner_reported; earlier Sol High and GitHub-native authors retained | Candidate `f549bd8f7986178d488544349aed5347b64e16cf` -> UI staging merge `17af4c29ed5ab02472c6f4378e59cf54fd7fa1aa`; CI `36633295520` SUCCESS | ACCEPTED source checkpoint. No review-required code/doc correction; not a pure Sol 6.1 from-scratch A or a duplicate independent success. #570 common-tree refresh/validation remains in #572. |
| #541 / #641 refresh/reconciliation, Worker | Sol 6.1 High / Codex desktop, owner_reported; provider not independently disclosed | Candidate `95097f75174116f608f761f791d0ee500e9e56ca` -> Performance staging merge `47a798de5b979fcd50b5a9880330e2c3eef62b56`; CI/UI `36632951022` / `36632950943` SUCCESS | **A at refreshed Phase A dependency/staging stage**, 0 substantive correction rounds after first handoff. #541 common-tree/Owner gates and Checkpoint B remain open; this does not grade all prior Performance leaves again. |
| #570 / #574 financial/product Reviewer | **DeepSeek V4.1 Flash / opencode-go / OpenCode CLI (Code Mode)**, Reviewer-reported via Owner | Exact docs `f549bd8f7986178d488544349aed5347b64e16cf` against UI `fb0c3b29cbf8e54df00cf7ee849a202b060de105` | Completed independent ACCEPT for source checkpoint only. Source links, meanings, D1/D2, native destinations and evidence boundaries checked; no common-aggregate/UAT/retirement approval. |
| #541 / #641 compatibility/data-integrity Reviewer | **DeepSeek V4.1 Flash / opencode-go (OpenCode)**, Reviewer-reported via Owner | Exact candidate `95097f75174116f608f761f791d0ee500e9e56ca` | Completed independent ACCEPT. Reviewer reports 54 tests PASS and both parameters of the new regression FAIL on pre-reconciliation merge `6add07fd`; retained real-backend CI journey and mutation guards checked. |

Both merged trees are exact-equivalent to the reviewed candidates. The all-event Actions lookup returned no new workflow for either staging merge SHA; no merge-SHA CI PASS is invented. The eventual #572 union needs its own frozen-tree CI, retained native import/Close/Performance journeys, independent integration review and Owner UAT.

Review qualification: the #641 report's 'only 3 files' wording refers to a restricted main-side preservation check, not the full main-to-candidate aggregate diff. The Integrator explicitly separated that scope from the accepted Performance feature set and the final 5-file reconciliation. This clarification caused no code change or Worker correction round. These two completed review cases are useful bounded-review evidence, not a universal reviewer ranking or proof of aggregate readiness.

## CI optimization pair — 2026-10-03

Source: the integration assignment for [#671 / PR #681](https://github.com/LTstripes/hermes-finance/pull/681) and [#668 / PR #682](https://github.com/LTstripes/hermes-finance/pull/682), plus each PR's Worker model-evidence block. GitHub had no review objects. The narrative record is `docs/EXECUTION_HISTORY.md`. No usage, cost or time was measured. These are CI/test-infrastructure cases, not financial-write cases.

| Case / role | Model and provider/client | Exact identity | Result at canonical integration |
| --- | --- | --- | --- |
| #671 / #681 Worker | **Grok 4.7 / xAI / Grok Build CLI**, worker-reported | Baseline `4a08d234b45b7780ccb6d5157bc203a1ad9ee553`; earlier `a8c7db477ba8f54b0f0f4dc8110e82dcf4afe187`; accepted `392a49f23f496f3b917a0b9b8232297556952fab`; merge `b962c4079019afbe34013371a8f0ffb2f95af362` | **A**. The follow-up is a three-line docstring, not a substantive correction round. Exact-head CI/UI `37135873996` / `37135874002` SUCCESS. Exact-main CI `37138732069` SUCCESS. |
| #671 Reviewer | **DeepSeek V4.1 Flash / OpenCode**, assignment-reported | ACCEPT on `392a49f23f496f3b917a0b9b8232297556952fab`. No GitHub review object. | Independent ACCEPT supplied for the integrated candidate. No review transcript was archived in the repository. |
| #668 / #682 Worker | **Grok 4.7 / xAI / Grok Build CLI**, worker-reported | Baseline `4a08d234b45b7780ccb6d5157bc203a1ad9ee553`; accepted `24b0d6eecde217512e264b3886cd37cdde911a64`; merge `12289d4b70a6faf78e274adbafb7a916ca2659c2` | **A**. One commit, 0 substantive correction rounds. Exact-head CI/UI `37135936715` / `37135936689` SUCCESS. Exact-main CI `37139674899` SUCCESS. |
| #668 Reviewer | **DeepSeek V4.1 Flash / OpenCode**, assignment-reported | ACCEPT on `24b0d6eecde217512e264b3886cd37cdde911a64`. No GitHub review object. | Independent ACCEPT supplied for the integrated candidate. No review transcript was archived in the repository. |

The #682 description wording fix did not change the candidate SHA and is not a Worker correction round. This is one sequential pair, not a blind model comparison. It does not grade either model outside these two infrastructure tasks, and it does not waive review for #669.

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

Worker and Reviewer handoffs use only the two-field `Model evidence` block from `AGENTS.md`: `model` and `provider/client`. Do not request usage/cost/time/delegate fields or pad the handoff with `unknown` telemetry. The Integrator may record genuinely available telemetry separately and records benchmark outcomes after review, keeping implementation and Reviewer attribution separate.

Only technical metadata, synthetic-safe summaries and source links belong here. Never include Owner finance/health values, DBs, credentials, private screenshots, raw provider payloads or unsanitized model transcripts. Controlled blind A/B requires a separate explicit assignment with identical contract/baseline and no candidate cross-reading; normal outcome logging does not activate it.
