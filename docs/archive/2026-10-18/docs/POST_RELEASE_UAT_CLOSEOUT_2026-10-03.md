# Post-release UAT and maintenance closeout — 2026-10-03

This dated execution record complements CURRENT_STATUS and the existing model journal/tracker #605. It records delivered work, Owner evidence and follow-ups; it is not a release or a new financial contract.

## Product aggregate and authorization

- Published Stable remains v1.1.0 at `32c905cfc938fd1aeaeb67643eb6fa77e8644a64`.
- Owner-tested isolated Preview: `d282d09647f129cd83c99e14a10024901a1cf6da`; tree `cf39e2c933f78691e7ec0db14872f640df903ec5`.
- Aggregate #662 CI `37108969114` and direct-head UI `37108969154`: SUCCESS.
- Owner completed UAT and explicitly authorized main integration, documentation/data closeout and the three maintenance PRs: [comment 5967980369](https://github.com/LTstripes/hermes-finance/pull/662#issuecomment-5967980369).
- Disposition: **OWNER PASS WITH DOCUMENTED UX FOLLOW-UPS**.
- Main integration #662: `a0396e9971be119038b8c28d29398191449b0c0c`, exact tested tree preserved. Canonical push CI `37114728212` includes successful relevant jobs; path-only/launcher skips are not claimed as executed probes.

| Issue / source PR | Accepted source head |
| --- | --- |
| #647 / #652 | `4805789f4514f5718294693e70966edb654e59e3` |
| #651 / #653 | `736de53af3da039f4fd5aac11ec3a923554b9674` |
| #648 / #655 | `40942c5adf816b581e55a7f77c0a40469776cbd9` |
| #645 / #657 | `d2a89dd2b5e874c9914f24cfe0ba9619f0dac5e4` |
| #649 / #660 | `823ad3a33eb3413ec6dd8a1d0ffc77690afd7af6` |
| #650 / #656 | `d290f0a93aeace364933cc2f95d1d8c8e26d7eec` |

No reconstruction from untested sibling tips was performed after UAT. Original source PRs #652/#653 are already represented in the aggregate ancestry; closing their redundant open PR records does not delete their branches or change the implementation.

## Owner evidence: exact scope and limits

Owner reported success for local reread/selected-month navigation, debt rename/cancel/save/readback, Settings/Diagnostics navigation, Sources, Alfa exception-first presentation, historical quote preview/apply, future payouts, direct final review/close, another historical month and the linked-pair explanation. This is the supplied route, not a claim that every negative/concurrency/viewport case was exercised live.

- Block 1's confusing Select/open actions, latest-report intermediary and unreadable primary link remain **#667**. Owner's later authorization permits integration with these documented follow-ups; it does not erase the findings.
- Block 11 requested removing the repeated «вне сравнимых пар» qualifier from Home row labels. **#672** is copy-only; residual amounts, linked-pair details, exact reconciliation, incomplete-coverage notices and no-repayment-source inference stay unchanged.
- September's historical quote path does not test qualifying Moscow-today LAST. Live Q645-C1 remains **NOT TESTED**; synthetic expiry/single-claim/context/atomicity evidence is separate.
- Alfa UI PASS does not prove that the terminal transport recovered after its update or establish a vendor-wide root cause. **#646 stays open**.
- Viewing individual payout controls or cancelling a debt-link form is not a live duplicate Apply/link/unlink write test.
- No new PRE/POST history, universal XIRR/TWRR availability, all-provider completeness, protected-backup delivery or destructive restore acceptance is asserted.

Owner screenshots, balances, account names, databases, local paths and tokens are not included in this record or its fixtures.

## Grok triage and maintenance disposition

Triage source: [#554 comment 5967214608](https://github.com/LTstripes/hermes-finance/issues/554#issuecomment-5967214608).

| Proposal | Disposition |
| --- | --- |
| Finish #645/#650 before one aggregate UAT | Delivered through #662; do not recreate tasks |
| Version/current docs and AI export status | #663; original stale #572/local-install claims corrected by Integrator, schema version 1.3.0 retained |
| LF policy and supported Node | #665, candidate `8b6f53d81687758ee4cacc0288d25449f04fca46`, integrated at `fa2d98f1b7e386bac5af587a9ab1af1d9ec6fb27`; CI `37111377609` / UI `37111377606` SUCCESS |
| Pin Actions | #664, candidate `883a395b96c85230f3c20769966472f35619c18b`, integrated at `bc48b32012fd5b20e84f0389d9b7c93582d54fa8`; CI `37111320012` / UI `37111319843` SUCCESS |
| Replace release trigger with workflow_dispatch | Not adopted: explicit guarded owner issue-comment #124 is intentional |
| sqlite3 date-adapter warnings | P3 targeted binding investigation; no blanket warning suppression or changed date/lock semantics. The aggregate persistence lane showed 164 warnings; the suggested total 1956 was not independently recounted |
| Generate all TS types / introduce pyright | Optional bounded pilots, not an immediate wholesale migration or mandatory gate |
| Delete 329 merged branches / enable auto-deletion | Not authorized. First inventory and canonical ancestry/dependency proof; count not verified. Separate from filesystem cleanup #666 |

Node 22.23.1 is the tested/recommended toolchain. The engines range is compatibility, not a claim of tests on every allowed major. The negative engine probe used an unsatisfiable range; it did not reproduce the original Node-20 silent-test symptom. Actions pinning preserved upstream versions, triggers, permissions, filters and release guards.

## Model evidence index for tracker #605

Attribution below is **Owner-reported delivery unless otherwise qualified**, not independently proven runtime telemetry. Recommendations alone are not execution evidence. Costs/tokens and exact active durations were not measured. No cross-model blind benchmark was performed.

| Task / role | model | provider/client | Observed result / qualification |
| --- | --- | --- | --- |
| #647 Worker | unknown | unknown / Codex desktop | Accepted technical candidate; Owner UAT exposed the bounded month-list UX findings now #667. Do not label first-pass product-perfect |
| #651 contract research | GPT-6 Astra Pro | OpenAI / ChatGPT | Identified cross-month identity gate; bounded stable-Account grouping accepted after independent contract review |
| #651 contract Reviewer | Grok 4.7 | xAI / Grok Build CLI | ACCEPT of frozen presentation contract, not implementation/merge authority |
| #651 Worker | unknown | unknown | Accepted fixed-set backend/Home decomposition |
| #651 implementation Reviewer | gpt-6-astra | OpenAI / Codex | Medium effort reported; independent financial/product review ACCEPT |
| #648 Worker | Sol High | unknown / Codex desktop | Explicit Owner confirmation retained despite raw unknown identity; exact backend model ID unconfirmed. Sequential payout flow and writer-reserved revalidation accepted; reported three hours is anecdotal, not measured active time |
| #648 Reviewer | gpt-6-astra | OpenAI / Codex | Medium effort reported; independent evidence/financial review accepted |
| #645 Worker | gpt-6.1-sol | openai / Codex Desktop | Q645-C1 implementation accepted with exact-head CI/UI |
| #645 Reviewer | gpt-6-astra | openai / Codex app-server | Independent financial/privacy review reported no blockers |
| #649 Worker | DeepSeek V4.1 Flash | opencode-go / OpenCode CLI | Initial independent FIXES REQUIRED then ACCEPT after remediation; not a first-candidate-perfect result |
| #650 original UI route | Muse Spark 1.3 Contributor | unknown | Session-context label only, not runtime-confirmed; later intermediate identities unknown. Mixed-route outcome, not a pure Muse benchmark |
| #650 reconciliation/CSS remediation | gpt-6.1-sol | openai / Codex Desktop | Owner confirms Sol 6.1 High; final candidate accepted after real layout fix and corrected vertical-scroll test assumption |
| #663 Worker | DeepSeek V4.1 Flash | opencode-go / OpenCode | Useful version/docs candidate; Integrator corrected obsolete #572/Stable/UAT claims before integration |
| #664 Worker | Grok 4.7 | xAI / Grok Build CLI | Mechanical action pinning accepted; upstream refs and exact CI independently read |
| #665 Worker | DeepSeek V4.1 Flash | opencode-go / OpenCode | Small LF/Node guard candidate accepted; install-hint alignment belongs to closeout |
| Owner-copy/docs Integrator | GPT-6 Astra Pro | OpenAI / ChatGPT | GitHub-native mechanical correction and durable closeout; no local full-suite or runtime access claimed |

#650 confounders must remain explicit: the original edit/link browser assertions were replaced twice and restored; staging conflicts and local/CI environment constraints were separate from model quality. The Integrator's claim that viewport-ratio zero alone proved horizontal overflow was too strong. The final accepted diff allows normal vertical scrolling and fixes intrinsic-width containment; no financial lifecycle changed. Do not count every formatting commit, repeated review note or CI wait as an independent substantive model defect.

Required independent review and Owner UAT are not replaced by green CI or a model label. The journal's existing historical cases/grades are not rewritten by this cohort.

## Next operational work

First #666: protect clearly named Stable/Control/Preview roots and isolate disposable per-task workspaces. Begin with synthetic-tested inventory tooling/design and Owner-run local metadata collection, never agent inspection of private runtime contents. Stable remains a published release; control/main is not production. Local root registry/signage must stay machine-local; repository docs use variables/examples. No relocation/deletion until the exact manifest, backup and Owner approval are established.

#667 can be a separate frontend-only follow-up in parallel if ownership and the single-heavyweight-process limit are respected. #629 launcher removal, #630 demo stand, #535/#540 class returns, #573 v1 retirement and #389 composer remain separately scoped choices. No next task or unattended queue starts from this record.

Publication and local runtime upgrade are not performed by this closeout. Exact-candidate and exact-main CI must be read back on the actual final merged commits before reporting final integration complete.
