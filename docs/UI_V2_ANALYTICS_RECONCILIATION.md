# UI v2 Analytics/Home reconciliation

Initial audit: 2026-09-26. Final UI-parity source refresh: 2026-09-30. Parent: [#570](https://github.com/LTstripes/hermes-finance/issues/570). Tracker: [#554](https://github.com/LTstripes/hermes-finance/issues/554).

Status: common-tree source refresh for #572 at frozen code anchor `b05487b822252fad9d9ec7cf4410d6d96c91c8bb`. This combines accepted UI `17af4c29ed5ab02472c6f4378e59cf54fd7fa1aa` and Performance `47a798de5b979fcd50b5a9880330e2c3eef62b56`, preserving main `ee9faea0b49f08454c284deb0db926f8db981a9d`. #574's UI-source checkpoint and #641's Performance refresh were independently reviewed and accepted before this assembly. #570 remains open for common-tree validation acceptance; independent aggregate review, #572 Owner UAT and #573 retirement authorization remain separate pending gates. See [aggregate evidence/matrix](UI_V2_AGGREGATE_VERIFICATION.md) and [Owner runbook](UI_V2_OWNER_UAT.md).

## 1. Exact source state reviewed

- Canonical main and `integration/ui-v2-parity` at the initial audit: `10d545882041593f37d65cf8f56b42b3a18ccebd` (legacy source baseline below).
- Initial docs candidate: `e964717dfd24f51e371f8ed6302a7468abaad381`, draft PR #574. Its CI `36250120480` passed; that result does not cover subsequent commits.
- Performance staging at the initial audit: `435eac2979555a3574bafd8cbf1e7a6a00e5d640`, based on `f328c82b6c7c3af0f6cd436c7e1d408bb54a8885`.
- Relative to the split base, that Performance head adds only `docs/performance/PERFORMANCE_UI_V2_PLAN.md`; it is not the later canonical main plus implemented Phase A/B. No accepted Phase A/B implementation was present on that inspected staging head.
- #529–#535, #540 and #541 were open at the audit. This is dated evidence, not a claim that their status can never change.
- Previous docs refresh: `9ea4a63ec205f0a20dd5f9f9d5ca40eda09fb92d`, against `integration/ui-v2-parity@0f6791c32c4926be29103ad81b3826f22bb8842d`; CI `36623529216` SUCCESS. This remains dated evidence for that head.
- Previous UI-source checkpoint reviewed: `integration/ui-v2-parity@fb0c3b29cbf8e54df00cf7ee849a202b060de105`. The same #570 branch retains original matrix commits `e964717dfd24f51e371f8ed6302a7468abaad381` / `8fe0f33a6ab4cbbe95f90dcc799dbd2a31d2600e` and the previous refresh, and incorporates accepted staging ancestry. The PR diff against staging remains this document only.
- Accepted UI-parity outcomes on that staging tree: #552 Goals (PR #580), #553 Tax/IIS (PR #582 plus route reconciliation #584), #555–#558, #575 monetary result (accepted head `660895c1f7a87c59d7d2b2749423224445c42040`, staging merge `5638eeae858ddcf14a35637bbef45b561a3e4adb`), #559–#564 with shared #607 editor wiring, #565–#567, #568 IIS forms (accepted head `9c72ebd095fcf23b25abc217070e34749ee1274b`, staging merge `1be28feba70bc4f94aa2c4f996cf258d516db11f`), and #569 allocation detail (accepted head `a22cb77c4c61de9eb1e493d2a392fa66f8a77585`, leaf merge `5e8c66b6d714028daf55566aa669e7c0952f58c4`; route/link wiring accepted head `008a6409735c58af558dff1d5214293919dd8cb6`, staging merge `0f6791c32c4926be29103ad81b3826f22bb8842d`). These are source/acceptance records, not aggregate #572 UAT.
- Earlier separate Performance staging inspection: `a9198a46a9efedcf1e60f5628ff308ebe65952dc`. The accepted refresh `47a798de5b979fcd50b5a9880330e2c3eef62b56` now belongs to this common candidate's ancestry; section 8 distinguishes old evidence from the new assembly.
- #571: [independent lifecycle/data-integrity ACCEPT in PR #639](https://github.com/LTstripes/hermes-finance/pull/639#issuecomment-5899002497), exact candidate `f69d2603709a06ac483875415bef6fc247c347cc`, merged as `fb0c3b29cbf8e54df00cf7ee849a202b060de105`. Reviewer: Grok 4.7 / xAI / Grok Build CLI; candidate CI `36627209205` and UI comparison `36627209078` SUCCESS. Candidate ancestry and current native action/Edit/return source were checked; #572 still owns aggregate evidence and Owner UAT.
- Live launch refs matched the packet: UI `17af4c29ed5ab02472c6f4378e59cf54fd7fa1aa`, Performance `47a798de5b979fcd50b5a9880330e2c3eef62b56`, main `ee9faea0b49f08454c284deb0db926f8db981a9d`, including #621–#624. Merge `2dcd7336a6b2d75790399c694c66ac778e833082` retains both parents. Frozen code anchor `b05487b822252fad9d9ec7cf4410d6d96c91c8bb` adds bounded navigation/CI reconciliation; its tree is `56ebf6d952c288159b231b06b3bce75bf4996312`. Final code+docs candidate SHA/tree are returned in the PR evidence, not claimed to equal this anchor.

Source links below identify their exact baseline, current UI-parity staging or separate Performance staging SHA. `SOURCE MATCH` means a capability was found in source for the stated context, not runtime/e2e/UAT PASS. `ACCEPTED` identifies an Integrator-accepted slice on the stated staging branch, not final aggregate parity. `PARTIAL` means only some contexts/components match; `PENDING` identifies an existing implementation task; `OWNER DE-SCOPED` records an explicit bounded product decision; `RETIREMENT-ONLY` is intentional legacy routing retained until #573.

No product code, API, financial formula, data, route or Performance branch is changed by this document.

## 2. Semantic guardrails

1. **Monetary result for a reporting month is not XIRR/TWRR or profit earned during that month.** [Dashboard result service][S3] and [DTO/chart][S2] combine cash income recorded in the selected month with unrealized result from open-position snapshots. The latter is not the month-over-month change in unrealized result. Keep both components separately labelled; do not rename their displayed sum to "earned this month".
2. Account results and instrument-class results are not identical scopes. Cash events without an instrument can appear by account but not by class. A cash-income-only class has no current market/cost/unrealized evidence; preserve its null values and unavailable total, not invented zeros. Class grouping here is `instrument_type`, not a new Performance asset-class taxonomy. [S3]
3. Capital delta is a change of state, not investment return. Home/Capital already label the distinction; class transfers may change rows without increasing capital. [Home][S5], [Capital][S4]
4. The exact monetary bridge after external flows is not P&L, "earned" or class/instrument return attribution. Preserve the existing labels, exactness gate, scope, currency and interval. [Analytics][S1], [Capital][S4]
5. Allocation/concentration is not class performance. Risk allocation describes denominators, support, holdings and future payout/redemption concentration; #534/#535/#540 own future class-specific return rates. [Risk][S8], [Performance plan][S9]
6. Current v2 Home/Capital and Income planning use latest closed data; historical facts and draft work have separate destinations. D2 below approves not recreating the old global selected-month planning mode, not deleting local factual or workflow context. The new allocation detail has its own local month selector, including drafts; the monetary-result detail selects closed months only. [Allocation detail][S13], [Monthly result][S14]

## 3. Legacy /analytics capability matrix

| Legacy capability | Meaning/source on baseline | Native destination | Status | Follow-up / owner |
| --- | --- | --- | --- | --- |
| Capital composition over time | [Analytics][S1]: closed history, amount/share modes | [Capital][S4] history; [Reports][S7] contextual history | SOURCE MATCH | Preserve closed-report scope and gaps |
| Current allocation for a selected closed report | Selected dashboard `asset_allocation` | Latest closed: Capital; older closed: Reports | SOURCE MATCH | Context must remain visible |
| Global selected-draft analytics view | Legacy month selector accepts drafts | Do not recreate as a global confirmed-data analytics mode | OWNER DE-SCOPED D2 | Editor/close and separately scoped local tools remain |
| Monetary result by account | `result_by_account`: monthly cash income plus unrealized snapshot component | [Monthly result][S14] at `/v2/capital/monthly-result?month=<closed-id>&view=accounts`; linked from Capital/Reports | ACCEPTED #575 in staging | D1 KEEP; exact #575 head above; no rate conversion or aggregate UAT claim |
| Monetary result by instrument class | `result_by_instrument_class`; class cash-only nulls preserved | Same [monthly-result detail][S14], `view=classes` | ACCEPTED #575 in staging | #540 class return table is not a replacement; class/account cuts need not total identically |
| Exact bridge after external flows | Canonical attribution for a closed-snapshot interval | Capital PerformanceBlock, current adjacent closed pair | SOURCE MATCH for latest pair | Historical/richer periods are present in accepted #529/#531 detail |
| Portfolio XIRR | Annualized canonical return rate | Capital PerformanceBlock | SOURCE MATCH for latest pair | Period/account detail #529–#531 in the common tree |
| Portfolio TWRR | Canonical return over interval | Capital PerformanceBlock | SOURCE MATCH for latest pair | Diagnostics/capture #529–#533 in the common tree |
| Older closed-pair Performance selection | Legacy older closed-month choice changes bridge/XIRR/TWRR interval | [Performance detail][S17] on this common tree, with exact dates/account scope | ACCEPTED #529/#531 ancestry; aggregate verification required | D2 does not remove historical Performance periods; #541 aggregate/Owner gates remain open |
| Allocation by class/account, top positions | [RiskAllocationPage][S8] | [Capital allocation detail][S13] at `/v2/capital/allocation`, linked from Capital | ACCEPTED #569 + route wiring in staging | Local month context, canonical denominator/support; zero basis is distinct from partial coverage |
| Payout/redemption concentration and support matrix | Risk future-event concentration and support | Same [allocation detail][S13], including payout/redemption groups and support/limitations | ACCEPTED #569 + route wiring in staging | Preserve future window, denominator and exclusions; source presence is not #572 UAT |
| Open/create selected month actions | Legacy `/months` and `/months/:id` | Native month management/editor at `/v2/data/months` and `/v2/data/months/:monthId` | ACCEPTED #557/#558 + #559–#564/#607 and #571 wiring in staging | Exact native action/return mapping is delivered; #572 aggregate journey remains pending |
| `/analytics` route | Mixed history/result/performance surface | Capabilities split by meaning | RETIREMENT-ONLY | No blanket redirect while kept functions lack parity |

## 4. Legacy /v1 Dashboard capability matrix

[DashboardPage][S10] functions are split across native Home, Capital, Income and Reports, rather than copied as a second global dashboard.

| Legacy capability | Native destination | Status | Evidence / limitation |
| --- | --- | --- | --- |
| Liquid capital and change | Home/Capital | SOURCE MATCH for latest closed | Closed-report comparison, not investment return |
| Asset-class breakdown | Home/Capital/Reports | SOURCE MATCH for closed contexts | Historical facts remain |
| Capital history | Home/Capital | SOURCE MATCH | Canonical closed history |
| Passive actual/average/history | Home/Income | SOURCE MATCH for mapped facts | Income also selects factual closed-month breakdown; this does not make every legacy annotation identical |
| 12-month forecast and breakdown | Income | SOURCE MATCH for latest closed planning | Same canonical forecast through [IncomePlanSummary][S11]; methodology/help and all supporting fields still belong in aggregate verification |
| Cash-flow ladder/upcoming events | Income | SOURCE MATCH for latest closed planning | Principal distinct from passive income |
| Actual/forecast mandatory-expense coverage | Income | SOURCE MATCH for latest closed planning | Same canonical coverage service |
| Mortgage balance/capital coverage | Capital PropertyBlock | SOURCE MATCH when that latest-report block is rendered | Property block is conditional; do not assume every historical/draft/empty-property case has parity |
| Goal summary/progress and action | Home/Income summary; [native Goals detail][S15] accepted #552 | ACCEPTED in staging for assigned Goals scope | Retain local goal/as-of context, not a second global selector |
| Open/create/all months | Native `/v2/data/months` management and `/v2/data/months/:monthId` editor | ACCEPTED #557/#558 + #559–#564/#607 and #571 wiring in staging | Close CTA/Edit/return wiring accepted; #572 aggregate journey remains pending |
| Select arbitrary month and recompute whole Dashboard | No global v2 replacement planned | OWNER DE-SCOPED D2 | Current picture remains latest closed |
| Historical/draft forecast, coverage, ladder in that global mode | Do not recreate this global planning mode | OWNER DE-SCOPED D2 | Not a deletion of underlying APIs/history or local task contracts |
| Link to mixed Analytics | Split among Capital, Income, Reports, accepted #569/#575 details and common-tree Performance | RETIREMENT-ONLY | Only remove after kept capabilities and route handling are verified |

This is a source-backed mapped capability inventory, not proof that every legacy field/help/annotation or full workflow is replaced. #572 must check the accepted scope and surface any additional gaps; D2 is not a catch-all waiver for unrelated losses.

### Adjacent retained actions and current destinations

| Accepted slice | Native destination on UI-parity staging | Boundary still to verify |
| --- | --- | --- |
| #552 Goals and #553 Tax/IIS | [Goals][S15] and `/v2/income/tax-iis` | Local as-of/month meaning; neither is the old global selector |
| #568 IIS profile, contribution and type-A benefit writes | [Account catalogs][S16] at `/v2/data/catalogs?tab=accounts&account=<id>`; contextual Tax/IIS planner link | Account/tax-year lifecycle, fresh readback and ambiguous-write lock; reporting month is navigation context only |
| #555–#558, #559–#564 and #607, connected by accepted #571 | `/v2/data/months`, `/v2/data/months/:monthId` and accepted editor sections | #572 must verify the aggregate action/return/readiness journey |
| #565–#567, connected by accepted #571 | `/v2/data/alfa-baseline`, `/v2/data/payouts` forecast and statement-import actions | #572 must verify the aggregate import/apply/readback journey |
| #571 Monthly Close wiring | [Close action map][S21], [v2 Close][S22], [final review][S23] and native editor/management returns | Accepted candidate and merge above; real-backend acceptance harness is Worker evidence, with aggregate execution still required by #572 |

The #568 and #569 accepted heads and Integrator reviews are [PR #632](https://github.com/LTstripes/hermes-finance/pull/632#issuecomment-5895998111), [PR #631](https://github.com/LTstripes/hermes-finance/pull/631#issuecomment-5896980585) and [route wiring PR #635](https://github.com/LTstripes/hermes-finance/pull/635#issuecomment-5897149453). #575's separate financial/product review is [PR #588](https://github.com/LTstripes/hermes-finance/pull/588#issuecomment-5855115571). These slices and accepted #571 are present in current staging ancestry; #572 and #573 remain separate pending gates.

## 5. Route / period / scope contract

### Home and Capital

- `/v2` and `/v2/capital` show latest closed data. A newer draft is workflow context, not confirmed financial truth.
- Their current `month`/`step` handling contributes to a legacy return path; it does not select a historical main-data view. Do not pretend otherwise by changing only a link label. [Home][S5], [Capital][S4]
- Historical closed capital facts live in `/v2/reports/:monthId`; current latest closed is deliberately handled by Home/Capital rather than duplicated in the archive. [Reports][S7]
- Accepted #575, #569 and Performance #531 routes coexist on the frozen common tree. Shared App/entry union retains all three detail routes; Capital retains allocation/monthly-result links and the Performance summary/detail entry. Empty Home/Capital/Income actions lead to native `/v2/close`; Home's payouts/forecast action leads to native `/v2/income`. Explicitly labelled previous-interface links remain.

### Income

- `/v2/income` plans from latest closed. Its `month` selects factual passive-income breakdown, not historical/draft planning, goals or ladder. [Income][S6]
- D2 does not overload this parameter or remove legitimate local month/as-of selection in #552 Goals, #553 Tax/IIS, #556 Scenario Lab or #569 risk detail. Those task contracts remain unchanged.

### Monetary-result detail delivered by #575 on UI-parity staging

- `/v2/capital/monthly-result?month=<id>` is a local read-only closed-report selector, latest or older closed, not a global Home/Capital mode.
- No `month`: explicitly identify latest closed. Invalid/deleted/draft/reopened explicit target: explain, do not silently substitute latest closed.
- Bounded `view=accounts|classes`, correct back/refresh and native return. Exact-month links from historical Reports.
- [Registered route][S18] and [page][S14] use the existing Dashboard DTO only. No new financial formulas or class-return scope. This is accepted source on staging, not aggregate UAT.

### Allocation detail and IIS writes delivered on UI-parity staging

- [Allocation detail][S13] at `/v2/capital/allocation` has a local month selector (closed or draft) and canonical class/account allocation, top positions, payout/redemption concentration, support and exclusions. The [Capital link][S19] carries the latest closed month; this does not create a global Home/Capital historical mode. Explicit invalid/duplicate month and mismatched response fail closed in this detail.
- [IIS forms][S20] are reached through [account catalogs][S16] with an account identifier. They write the existing profile, contribution and type-A benefit records for the account/tax year, then confirm through fresh reads. The contextual link returns to the Tax/IIS planner. They are not a second tax planner or a reporting-month write model.

### Performance

- Accepted #529 owns exact period/scope/action contracts; accepted #531 supplies portfolio/account detail at `/v2/capital/performance` on this common tree.
- Accepted #532/#533 supply evidence preparation/capture on the same tree. Canonical CI retains `performance-real-backend.spec.ts`: unavailable -> XIRR-only -> explicitly observed synthetic PRE/POST -> TWRR, correction invalidation and stale-token rejection.
- Historical Performance periods remain required under the accepted Performance scope. D2 does not waive them.
- Phase B is separate class-return work: #534 contract is accepted, while #535/#540 implementation and #541 Checkpoint B remain open. Neither future #540 nor risk allocation replaces delivered #575 monetary results.

### Legacy compatibility

All existing routes remain during this work. D2 is an approved future scope reduction, not permission to redirect/delete now. At retirement, explicitly explain a de-scoped context or provide supported destinations; never silently render latest closed as the requested historical/draft result. [App routes][S12]

### Monthly Close wiring accepted and integrated: #571

Current [Close action map][S21] defines native paths for every guided action with `monthly-close-v2` origin: editor/general/positions under `/v2/data/months/:monthId`, native Alfa/payout/reconciliation/freshness tools, final review/close at `/v2/close`, and next-month management under `/v2/data/months`. The legacy-origin map remains for retained v1. [Final-review Edit links][S23] use the exact native month/section and return to the same Close step; CLOSED v2 review hides mutation links. [Editor][S24] and [month management][S25] retain return context, and [v2 Close][S22] validates workflow/final-review/outlook month identity while reusing the backend-owned lifecycle/readiness reads.

[PR #639's independent ACCEPT](https://github.com/LTstripes/hermes-finance/pull/639#issuecomment-5899002497) covers candidate `f69d2603709a06ac483875415bef6fc247c347cc`, integrated as `fb0c3b29cbf8e54df00cf7ee849a202b060de105`. Its [real-backend acceptance harness][S26] is now retained in required canonical CI via `playwright.monthly-close.config.ts`, with actual historical archive readback added on the common tree. `playwright.statement.config.ts` retains native statement import/apply/readback. Exact execution results belong to #572 PR/job evidence; registration/source presence alone is not a pass or Owner PASS.

## 6. Owner decisions — recorded 2026-09-26

Authority: [Integrator record of the actual Owner chat decision](https://github.com/LTstripes/hermes-finance/issues/570#issuecomment-5847307129). After the proposal to keep the monetary result and not reproduce the global historical/draft analytics mode, Owner replied: **«Да давай так и сделаем и идём дальше»**.

The linked note is an Integrator transcription of that instruction. Publishing through the Owner's GitHub connection does not itself constitute an independent Owner decision, review or UAT.

### D1 — KEEP approved; #575 delivered on UI-parity staging

- Preserve monetary result by account and instrument class in a compact Capital detail, using existing Dashboard API.
- Keep closed historical factual context and separate cash-income/month versus unrealized/snapshot meanings.
- No second XIRR/TWRR implementation, no new financial calculations, no artificial portfolio/class totals.
- The decision is unchanged. #575 was implemented, independently reviewed and accepted at `660895c1f7a87c59d7d2b2749423224445c42040`, then integrated into UI-parity staging at `5638eeae858ddcf14a35637bbef45b561a3e4adb`. Its aggregate behavior still needs #572 verification before retirement can use it as parity proof.

### D2 — bounded global-mode reduction approved

Do not reproduce the old global arbitrary-month selector that moves the entire Dashboard/Analytics/planning picture to an historical period or draft. Consequently there is no requirement to recreate the historical/draft forecast/coverage/ladder as that global dashboard mode.

Preserve:

- latest-closed confirmed Home/Capital/planning;
- closed historical facts in Reports, factual Income history and #575;
- draft editing/readiness/validation in native editor/close;
- existing local month/as-of contracts in Goals, Tax/IIS, Scenario and risk detail;
- historical Performance periods/scopes assigned to its own stream.

This does not authorize deleting stored history, APIs, financial logic, existing routes, or any unrelated capability. No speculative new draft-preview feature is introduced. If an implementation uncovers another missing local fact/action, retain it as a bounded gap rather than treating D2 as permission to drop it.

**Neither D1 nor D2 is permission to disable `/v1`, merge #574, self-accept #570, assert #572 UAT PASS or release.** The separate #573 Owner authorization remains required after the exact aggregate is verified.

## 7. Implementation ownership and dependencies

| Task | Role in reconciliation |
| --- | --- |
| #575 | Accepted D1 native monetary result on UI-parity staging; aggregate #572 verification still required |
| #552/#553 | Accepted Goals and Tax/IIS detail with their local context |
| #557/#558 + #559–#564/#607 | Accepted native month lifecycle, editor sections and shared leaf wiring |
| #565–#567 | Accepted native Alfa, forecast/calendar and statement-import actions |
| #568 | Accepted native IIS write forms in account catalogs |
| #569 | Accepted allocation/concentration leaf plus separate Capital route/link wiring |
| #529–#531 | Accepted Performance period/scope/diagnostics and portfolio/account UI in common-tree ancestry |
| #532/#533 | Accepted Performance evidence preparation/capture in common-tree ancestry |
| #534/#535/#540 | Accepted Phase B contract; backend/UI still open, not a substitute for #575 |
| #541 | Checkpoint A technical verification and Owner PASS recorded with stated limitation; refreshed release/integration gate remains; Checkpoint B open |
| #571 | **ACCEPTED / INTEGRATED:** candidate `f69d2603709a06ac483875415bef6fc247c347cc`, merge `fb0c3b29cbf8e54df00cf7ee849a202b060de105`; aggregate harness gate remains #572 |
| #572 | **PENDING:** common aggregate verification and Owner UAT, including #575, #571 and the exact D2 scope boundary |
| #573 | **PENDING:** separate v1-retirement decision packet and explicit Owner authorization |

#551 Income polish is an accepted neighbouring slice; #538 owns portfolio-source coverage metadata, with no React-side replacement rules here. Accepted #555 navigation is in the common ancestry. #574's earlier source refresh was accepted in [Integrator comment 5900263443](https://github.com/LTstripes/hermes-finance/pull/574#issuecomment-5900263443). This common-tree refresh still requires independent aggregate financial/product/lifecycle review and Integrator acceptance. D2 does not waive any additional capability.

## 8. Performance checkpoint: historical evidence and common assembly

At the initial audited baseline, main had a real portfolio bridge/XIRR/TWRR block for the adjacent latest closed pair, with existing unavailable messages. That was source parity for that interval only, not new account drill-down or evidence-entry capability. [Capital at the initial baseline](https://github.com/LTstripes/hermes-finance/blob/10d545882041593f37d65cf8f56b42b3a18ccebd/frontend/src/ui-v2/UiV2CapitalPage.tsx)

The earlier Performance staging `a9198a46a9efedcf1e60f5628ff308ebe65952dc` contained accepted #529–#533, historical membership #608/#610, #620 capture-context fix and #534 contract. [#541's accepted refresh](https://github.com/LTstripes/hermes-finance/issues/541#issuecomment-5900366386) records accepted head `95097f75174116f608f761f791d0ee500e9e56ca`, staged as `47a798de5b979fcd50b5a9880330e2c3eef62b56`, with main/#621–#624 ancestry and retained canonical real-backend journey. Old candidate CI/UI `36632951022` / `36632950943` passed; they do not verify this #572 candidate. The earlier [Owner disposition](https://github.com/LTstripes/hermes-finance/issues/541#issuecomment-5895015839) deferred representative real-history UAT and Stable/main smoke. That limitation persists. #535/#540 and Checkpoint B remain deferred; class returns/UI are not delivered.

The [#572 launch packet](https://github.com/LTstripes/hermes-finance/issues/572#issuecomment-5900360825) delegates one task-branch assembly of the exact accepted inputs. The common source anchor above preserves #621–#624 (including #624 merge `33a7f8b63ef0b13c31af471bed1c5da3cd787e9d`) and native editor/import/Close, allocation/monthly-result and interval Performance together. Both accepted histories remain. Independent integration review and actual Owner acceptance follow the Worker candidate; earlier Performance Owner PASS does not mark #572 PASS.

An unfinished new Phase B does not automatically block delivery of unrelated retained legacy capabilities. Conversely, its future table cannot be cited as a delivered replacement for old monetary-result fields. Re-read the actual accepted candidates before final reconciliation; do not copy the staging branch or rely on open issue promises.

## 9. Retirement refresh checklist

Before #573 can become READY_FOR_OWNER_DECISION:

- This refresh records accepted #571 and Performance Phase A on one common code anchor. Obtain independent review and Owner UAT on the exact final code+docs candidate designated by #541/#572 before any retirement decision.
- Verify delivered #575 on that aggregate, including closed historical context, cash-only nulls and accurate labels. Accepted staging source is not #572 aggregate UAT.
- Carry the D2 decision link forward; verify its narrow boundary without deleting local factual/Performance contexts.
- Verify other retained native destinations, including #552/#568/#569/editor and completed #571 Close wiring, plus additional gaps found by #572.
- Verify every required ordinary action without legacy dependence; list intentional v1 escape/fallback separately.
- Check query/hash/period/scope/back/refresh, invalid/deleted/reopened targets and explicit handling of de-scoped contexts.
- Keep null/unknown/partial distinct from zero/complete; do not conflate monetary result, capital state change, return rate and risk allocation.
- Obtain independent financial/product review of this refreshed matrix; preserve its evidence boundaries when reconciling the common aggregate.
- Run aggregate Owner UAT #572 on the same tree; obtain the separate #573 Owner permission before any removal implementation.

A green CI or the accepted D1/D2 scope decisions do not authorize removal. Legacy routes remain intact until the separate approved retirement PR.

## Source manifest

Legacy inventory references retain the initial audit SHA. Native UI and Performance references below pin common code anchor `b05487b822252fad9d9ec7cf4410d6d96c91c8bb`. This source anchor precedes the final documentation-only commit; final code+docs identity is reported in PR evidence. Source links do not claim independent aggregate ACCEPT or #572 Owner UAT.

[S1]: https://github.com/LTstripes/hermes-finance/blob/10d545882041593f37d65cf8f56b42b3a18ccebd/frontend/src/pages/AnalyticsPage.tsx
[S2]: https://github.com/LTstripes/hermes-finance/blob/10d545882041593f37d65cf8f56b42b3a18ccebd/frontend/src/components/charts/InvestmentResultChart.tsx
[S3]: https://github.com/LTstripes/hermes-finance/blob/10d545882041593f37d65cf8f56b42b3a18ccebd/backend/src/hermes_finance/services/dashboard.py
[S4]: https://github.com/LTstripes/hermes-finance/blob/b05487b822252fad9d9ec7cf4410d6d96c91c8bb/frontend/src/ui-v2/UiV2CapitalPage.tsx
[S5]: https://github.com/LTstripes/hermes-finance/blob/b05487b822252fad9d9ec7cf4410d6d96c91c8bb/frontend/src/ui-v2/UiV2Page.tsx
[S6]: https://github.com/LTstripes/hermes-finance/blob/b05487b822252fad9d9ec7cf4410d6d96c91c8bb/frontend/src/ui-v2/UiV2IncomePage.tsx
[S7]: https://github.com/LTstripes/hermes-finance/blob/b05487b822252fad9d9ec7cf4410d6d96c91c8bb/frontend/src/ui-v2/UiV2ReportPage.tsx
[S8]: https://github.com/LTstripes/hermes-finance/blob/10d545882041593f37d65cf8f56b42b3a18ccebd/frontend/src/pages/RiskAllocationPage.tsx
[S9]: https://github.com/LTstripes/hermes-finance/blob/b05487b822252fad9d9ec7cf4410d6d96c91c8bb/docs/performance/PERFORMANCE_UI_V2_PLAN.md
[S10]: https://github.com/LTstripes/hermes-finance/blob/10d545882041593f37d65cf8f56b42b3a18ccebd/frontend/src/pages/DashboardPage.tsx
[S11]: https://github.com/LTstripes/hermes-finance/blob/b05487b822252fad9d9ec7cf4410d6d96c91c8bb/backend/src/hermes_finance/services/income_plan_summary.py
[S12]: https://github.com/LTstripes/hermes-finance/blob/b05487b822252fad9d9ec7cf4410d6d96c91c8bb/frontend/src/app/App.tsx

[S13]: https://github.com/LTstripes/hermes-finance/blob/b05487b822252fad9d9ec7cf4410d6d96c91c8bb/frontend/src/ui-v2/UiV2CapitalAllocationPage.tsx

[S14]: https://github.com/LTstripes/hermes-finance/blob/b05487b822252fad9d9ec7cf4410d6d96c91c8bb/frontend/src/ui-v2/UiV2MonthlyResultPage.tsx

[S15]: https://github.com/LTstripes/hermes-finance/blob/b05487b822252fad9d9ec7cf4410d6d96c91c8bb/frontend/src/ui-v2/UiV2GoalsPage.tsx

[S16]: https://github.com/LTstripes/hermes-finance/blob/b05487b822252fad9d9ec7cf4410d6d96c91c8bb/frontend/src/ui-v2/UiV2DataCatalogsPage.tsx

[S17]: https://github.com/LTstripes/hermes-finance/blob/b05487b822252fad9d9ec7cf4410d6d96c91c8bb/frontend/src/ui-v2/UiV2CapitalPerformanceDetail.tsx

[S18]: https://github.com/LTstripes/hermes-finance/blob/b05487b822252fad9d9ec7cf4410d6d96c91c8bb/frontend/src/app/App.tsx

[S19]: https://github.com/LTstripes/hermes-finance/blob/b05487b822252fad9d9ec7cf4410d6d96c91c8bb/frontend/src/ui-v2/UiV2CapitalPage.tsx

[S20]: https://github.com/LTstripes/hermes-finance/blob/b05487b822252fad9d9ec7cf4410d6d96c91c8bb/frontend/src/ui-v2/UiV2IisAccountForms.tsx

[S21]: https://github.com/LTstripes/hermes-finance/blob/b05487b822252fad9d9ec7cf4410d6d96c91c8bb/frontend/src/components/month-close/navigation.ts

[S22]: https://github.com/LTstripes/hermes-finance/blob/b05487b822252fad9d9ec7cf4410d6d96c91c8bb/frontend/src/ui-v2/UiV2ClosePage.tsx

[S23]: https://github.com/LTstripes/hermes-finance/blob/b05487b822252fad9d9ec7cf4410d6d96c91c8bb/frontend/src/components/month-close/FinalMonthReview.tsx

[S24]: https://github.com/LTstripes/hermes-finance/blob/b05487b822252fad9d9ec7cf4410d6d96c91c8bb/frontend/src/ui-v2/UiV2MonthEditorPage.tsx

[S25]: https://github.com/LTstripes/hermes-finance/blob/b05487b822252fad9d9ec7cf4410d6d96c91c8bb/frontend/src/ui-v2/UiV2MonthsPage.tsx

[S26]: https://github.com/LTstripes/hermes-finance/blob/b05487b822252fad9d9ec7cf4410d6d96c91c8bb/frontend/e2e/monthly-close.acceptance.ts
