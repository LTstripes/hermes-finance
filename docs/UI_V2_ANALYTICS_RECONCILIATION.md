# UI v2 Analytics/Home reconciliation

Initial audit: 2026-09-26. Refreshed: 2026-09-29. Parent: [#570](https://github.com/LTstripes/hermes-finance/issues/570). Tracker: [#554](https://github.com/LTstripes/hermes-finance/issues/554).

Status: source-backed matrix refreshed against accepted UI-parity staging. Independent financial/product review of this docs candidate remains pending. #571 Monthly Close wiring is still open; #570 stays open for one final refresh after #571 acceptance on the exact aggregate used by #572. This is not final aggregate parity, Owner UAT or permission to remove v1.

## 1. Exact source state reviewed

- Canonical main and `integration/ui-v2-parity`: `10d545882041593f37d65cf8f56b42b3a18ccebd` (source baseline below).
- Initial docs candidate: `e964717dfd24f51e371f8ed6302a7468abaad381`, draft PR #574. Its CI `36250120480` passed; that result does not cover subsequent commits.
- Performance staging at the initial audit: `435eac2979555a3574bafd8cbf1e7a6a00e5d640`, based on `f328c82b6c7c3af0f6cd436c7e1d408bb54a8885`.
- Relative to the split base, that Performance head adds only `docs/performance/PERFORMANCE_UI_V2_PLAN.md`; it is not the later canonical main plus implemented Phase A/B. No accepted Phase A/B implementation was present on that inspected staging head.
- #529–#535, #540 and #541 were open at the audit. This is dated evidence, not a claim that their status can never change.
- Current UI-parity staging reviewed here: `integration/ui-v2-parity@0f6791c32c4926be29103ad81b3826f22bb8842d`. The #570 draft branch originally ended at `8fe0f33a6ab4cbbe95f90dcc799dbd2a31d2600e`; this refresh merges the accepted staging ancestry into the same branch while retaining both original matrix commits. The PR diff against staging remains this document only.
- Accepted UI-parity outcomes on that staging tree: #552 Goals (PR #580), #553 Tax/IIS (PR #582 plus route reconciliation #584), #555–#558, #575 monetary result (accepted head `660895c1f7a87c59d7d2b2749423224445c42040`, staging merge `5638eeae858ddcf14a35637bbef45b561a3e4adb`), #559–#564 with shared #607 editor wiring, #565–#567, #568 IIS forms (accepted head `9c72ebd095fcf23b25abc217070e34749ee1274b`, staging merge `1be28feba70bc4f94aa2c4f996cf258d516db11f`), and #569 allocation detail (accepted head `a22cb77c4c61de9eb1e493d2a392fa66f8a77585`, leaf merge `5e8c66b6d714028daf55566aa669e7c0952f58c4`; route/link wiring accepted head `008a6409735c58af558dff1d5214293919dd8cb6`, staging merge `0f6791c32c4926be29103ad81b3826f22bb8842d`). These are source/acceptance records, not aggregate #572 UAT.
- Performance staging separately reviewed at `integration/performance-ui-v2@a9198a46a9efedcf1e60f5628ff308ebe65952dc`. Its status is in section 8; it is not merged into the UI-parity staging tree.

Source links below identify their exact baseline, current UI-parity staging or separate Performance staging SHA. `SOURCE MATCH` means a capability was found in source for the stated context, not runtime/e2e/UAT PASS. `ACCEPTED` identifies an Integrator-accepted slice on the stated staging branch, not final aggregate parity. `PARTIAL` means only some contexts/components match; `PENDING` identifies an existing implementation task; `OWNER DE-SCOPED` records an explicit bounded product decision; `RETIREMENT-ONLY` is intentional legacy routing retained until #573.

No product code, API, financial formula, data, route or Performance branch is changed by this document.

## 2. Semantic guardrails

1. **Monetary result for a reporting month is not XIRR/TWRR or profit earned during that month.** [Dashboard result service][S3] and [DTO/chart][S2] combine cash income recorded in the selected month with unrealized result from open-position snapshots. The latter is not the month-over-month change in unrealized result. Keep both components separately labelled; do not rename their displayed sum to "earned this month".
2. Account results and instrument-class results are not identical scopes. Cash events without an instrument can appear by account but not by class. A cash-income-only class has no current market/cost/unrealized evidence; preserve its null values and unavailable total, not invented zeros. Class grouping here is `instrument_type`, not a new Performance asset-class taxonomy. [S3][S3]
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
| Exact bridge after external flows | Canonical attribution for a closed-snapshot interval | Capital PerformanceBlock, current adjacent closed pair | SOURCE MATCH for latest pair | Historical/richer periods remain #529/#531 |
| Portfolio XIRR | Annualized canonical return rate | Capital PerformanceBlock | SOURCE MATCH for latest pair | Period/account detail #529–#531 |
| Portfolio TWRR | Canonical return over interval | Capital PerformanceBlock | SOURCE MATCH for latest pair | Diagnostics/capture #529–#533 |
| Older closed-pair Performance selection | Legacy older closed-month choice changes bridge/XIRR/TWRR interval | [Performance detail][S17] accepted on separate Performance staging, not on this UI-parity tree | ACCEPTED #529/#531 in Performance staging; cross-stream reconciliation pending | D2 does not remove historical Performance periods; #541 gate remains open |
| Allocation by class/account, top positions | [RiskAllocationPage][S8] | [Capital allocation detail][S13] at `/v2/capital/allocation`, linked from Capital | ACCEPTED #569 + route wiring in staging | Local month context, canonical denominator/support; zero basis is distinct from partial coverage |
| Payout/redemption concentration and support matrix | Risk future-event concentration and support | Same [allocation detail][S13], including payout/redemption groups and support/limitations | ACCEPTED #569 + route wiring in staging | Preserve future window, denominator and exclusions; source presence is not #572 UAT |
| Open/create selected month actions | Legacy `/months` and `/months/:id` | Native month management/editor at `/v2/months` and `/v2/months/:monthId` | ACCEPTED #557/#558 + #559–#564/#607 in staging | Exact month/action and closed/read-only rules remain; full Close journey is #571 |
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
| Open/create/all months | Native `/v2/months` management and `/v2/months/:monthId` editor | ACCEPTED #557/#558 + #559–#564/#607 in staging | Full Close CTA/readiness journey remains #571 |
| Select arbitrary month and recompute whole Dashboard | No global v2 replacement planned | OWNER DE-SCOPED D2 | Current picture remains latest closed |
| Historical/draft forecast, coverage, ladder in that global mode | Do not recreate this global planning mode | OWNER DE-SCOPED D2 | Not a deletion of underlying APIs/history or local task contracts |
| Link to mixed Analytics | Split among Capital, Income, Reports, accepted #569/#575 details and separate Performance staging | RETIREMENT-ONLY | Only remove after kept capabilities and route handling are verified |

This is a source-backed mapped capability inventory, not proof that every legacy field/help/annotation or full workflow is replaced. #572 must check the accepted scope and surface any additional gaps; D2 is not a catch-all waiver for unrelated losses.

### Adjacent retained actions and current destinations

| Accepted slice | Native destination on UI-parity staging | Boundary still to verify |
| --- | --- | --- |
| #552 Goals and #553 Tax/IIS | [Goals][S15] and `/v2/income/tax-iis` | Local as-of/month meaning; neither is the old global selector |
| #568 IIS profile, contribution and type-A benefit writes | [Account catalogs][S16] at `/v2/data/catalogs?tab=accounts&account=<id>`; contextual Tax/IIS planner link | Account/tax-year lifecycle, fresh readback and ambiguous-write lock; reporting month is navigation context only |
| #555–#558, #559–#564 and #607 | `/v2/months`, `/v2/months/:monthId` and accepted editor sections | Separate #571 must connect all Close actions, return paths and readiness to these destinations |
| #565–#567 | `/v2/data/alfa-baseline`, `/v2/data/payouts` forecast and statement-import actions | #571 must verify full Close CTA/return/readiness journey |

The #568 and #569 accepted heads and Integrator reviews are [PR #632](https://github.com/LTstripes/hermes-finance/pull/632#issuecomment-5895998111), [PR #631](https://github.com/LTstripes/hermes-finance/pull/631#issuecomment-5896980585) and [route wiring PR #635](https://github.com/LTstripes/hermes-finance/pull/635#issuecomment-5897149453). #575's separate financial/product review is [PR #588](https://github.com/LTstripes/hermes-finance/pull/588#issuecomment-5855115571). These accepted slices are present in staging ancestry; #571, #572 and #573 remain separate gates.

## 5. Route / period / scope contract

### Home and Capital

- `/v2` and `/v2/capital` show latest closed data. A newer draft is workflow context, not confirmed financial truth.
- Their current `month`/`step` handling contributes to a legacy return path; it does not select a historical main-data view. Do not pretend otherwise by changing only a link label. [Home][S5], [Capital][S4]
- Historical closed capital facts live in `/v2/reports/:monthId`; current latest closed is deliberately handled by Home/Capital rather than duplicated in the archive. [Reports][S7]
- Accepted #575 and #569 links/routes are present in this staging tree. Performance #531 remains on its separate staging branch; future shared Capital/routes/entry/shell reconciliation is Integrator-owned.

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

- Accepted #529 owns exact period/scope/action contracts; accepted #531 supplies portfolio/account detail and its stream routing on Performance staging.
- Accepted #532/#533 supply evidence preparation/capture there, not on the UI-parity staging tree.
- Historical Performance periods remain required under the accepted Performance scope. D2 does not waive them.
- Phase B is separate class-return work: #534 contract is accepted, while #535/#540 implementation and #541 Checkpoint B remain open. Neither future #540 nor risk allocation replaces delivered #575 monetary results.

### Legacy compatibility

All existing routes remain during this work. D2 is an approved future scope reduction, not permission to redirect/delete now. At retirement, explicitly explain a de-scoped context or provide supported destinations; never silently render latest closed as the requested historical/draft result. [App routes][S12]

### Remaining Monthly Close gap: #571

The accepted editor/import destinations exist, but current [Close action map][S21] still falls back to legacy `/months/:id`, `/accounts` and `/payouts` for several actions, while only selected actions have native v2 destinations. That source check is enough to keep #571 open, not enough to pronounce the whole journey broken or complete. #571 must reconcile each CTA and final-review “Edit” return with exact month/step, confirmed writes and fresh readiness, then supply its required synthetic journey and independent lifecycle review. #570 needs its final aggregate refresh after that acceptance.

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
| #529–#531 | Accepted Performance period/scope/diagnostics and portfolio/account UI on separate staging |
| #532/#533 | Accepted Performance evidence preparation/capture on separate staging |
| #534/#535/#540 | Accepted Phase B contract; backend/UI still open, not a substitute for #575 |
| #541 | Checkpoint A technical verification and Owner PASS recorded with stated limitation; refreshed release/integration gate remains; Checkpoint B open |
| #571 | **OPEN:** full native Monthly Close action/return/readiness wiring remains the UI-parity gap |
| #572 | Aggregate parity, including #575 and the exact D2 scope boundary |
| #573 | Separate v1-retirement decision packet and authorization |

#551 Income polish is an accepted neighbouring slice; #538 owns portfolio-source coverage metadata, with no React-side replacement rules here. Accepted #555 navigation is already in the staging ancestry. #570 stays open for one final exact-aggregate refresh after #571 is accepted; no additional capability is silently waived by D2.

## 8. Performance checkpoint: initial audit and current separate staging

At the initial audited baseline, main had a real portfolio bridge/XIRR/TWRR block for the adjacent latest closed pair, with existing unavailable messages. That was source parity for that interval only, not new account drill-down or evidence-entry capability. [Capital][S4]

That was the **2026-09-26 initial audit**, not the current state. At the 2026-09-29 recheck, Performance staging is `a9198a46a9efedcf1e60f5628ff308ebe65952dc`: #529–#533 and the #534 contract are accepted there. [#541 Checkpoint A record](https://github.com/LTstripes/hermes-finance/issues/541#issuecomment-5875528250) reports technical verification, independent re-review and exact-head CI/UI evidence. The later [Owner disposition](https://github.com/LTstripes/hermes-finance/issues/541#issuecomment-5895015839) is PASS with an explicit real-data limitation and deferred Stable/main smoke; an empty Preview did not prove representative historical values. #541 remains open. #535/#540 and Checkpoint B are open. [Performance detail][S17] is source on that separate branch, not yet reconciled into the UI-parity aggregate.

The [release-gate follow-up](https://github.com/LTstripes/hermes-finance/issues/541#issuecomment-5895050559) paused canonical publication on data-integrity prerequisites. At this recheck #622/#623 are closed, #624 is still open; a refreshed exact Performance aggregate and affected verification are needed before treating Checkpoint A as a canonical integration candidate. Owner PASS does not erase that source/integration boundary.

An unfinished new Phase B does not automatically block delivery of unrelated retained legacy capabilities. Conversely, its future table cannot be cited as a delivered replacement for old monetary-result fields. Re-read the actual accepted candidates before final reconciliation; do not copy the staging branch or rely on open issue promises.

## 9. Retirement refresh checklist

Before #573 can become READY_FOR_OWNER_DECISION:

- After #571 acceptance, refresh this matrix once against the exact parity aggregate SHA and accepted Performance heads/compatibility; record actual Phase A/B status.
- Verify delivered #575 on that aggregate, including closed historical context, cash-only nulls and accurate labels. Accepted staging source is not #572 aggregate UAT.
- Carry the D2 decision link forward; verify its narrow boundary without deleting local factual/Performance contexts.
- Verify other retained native destinations, including #552/#568/#569/editor and completed #571 Close wiring, plus additional gaps found by #572.
- Verify every required ordinary action without legacy dependence; list intentional v1 escape/fallback separately.
- Check query/hash/period/scope/back/refresh, invalid/deleted/reopened targets and explicit handling of de-scoped contexts.
- Keep null/unknown/partial distinct from zero/complete; do not conflate monetary result, capital state change, return rate and risk allocation.
- Obtain independent financial/product review of this refreshed matrix and its final aggregate update.
- Run aggregate Owner UAT #572 on the same tree; obtain the separate #573 Owner permission before any removal implementation.

A green CI or the accepted D1/D2 scope decisions do not authorize removal. Legacy routes remain intact until the separate approved retirement PR.

## Source manifest

These are immutable source references for the initial audit, the accepted UI-parity staging or the separate Performance staging as shown by their SHA. They are not claims of runtime tests or #572 aggregate UAT. The final #570 refresh must repin relevant links to the accepted aggregate.

[S1]: https://github.com/LTstripes/hermes-finance/blob/10d545882041593f37d65cf8f56b42b3a18ccebd/frontend/src/pages/AnalyticsPage.tsx
[S2]: https://github.com/LTstripes/hermes-finance/blob/10d545882041593f37d65cf8f56b42b3a18ccebd/frontend/src/components/charts/InvestmentResultChart.tsx
[S3]: https://github.com/LTstripes/hermes-finance/blob/10d545882041593f37d65cf8f56b42b3a18ccebd/backend/src/hermes_finance/services/dashboard.py
[S4]: https://github.com/LTstripes/hermes-finance/blob/10d545882041593f37d65cf8f56b42b3a18ccebd/frontend/src/ui-v2/UiV2CapitalPage.tsx
[S5]: https://github.com/LTstripes/hermes-finance/blob/10d545882041593f37d65cf8f56b42b3a18ccebd/frontend/src/ui-v2/UiV2Page.tsx
[S6]: https://github.com/LTstripes/hermes-finance/blob/10d545882041593f37d65cf8f56b42b3a18ccebd/frontend/src/ui-v2/UiV2IncomePage.tsx
[S7]: https://github.com/LTstripes/hermes-finance/blob/10d545882041593f37d65cf8f56b42b3a18ccebd/frontend/src/ui-v2/UiV2ReportPage.tsx
[S8]: https://github.com/LTstripes/hermes-finance/blob/10d545882041593f37d65cf8f56b42b3a18ccebd/frontend/src/pages/RiskAllocationPage.tsx
[S9]: https://github.com/LTstripes/hermes-finance/blob/435eac2979555a3574bafd8cbf1e7a6a00e5d640/docs/performance/PERFORMANCE_UI_V2_PLAN.md
[S10]: https://github.com/LTstripes/hermes-finance/blob/10d545882041593f37d65cf8f56b42b3a18ccebd/frontend/src/pages/DashboardPage.tsx
[S11]: https://github.com/LTstripes/hermes-finance/blob/10d545882041593f37d65cf8f56b42b3a18ccebd/backend/src/hermes_finance/services/income_plan_summary.py
[S12]: https://github.com/LTstripes/hermes-finance/blob/10d545882041593f37d65cf8f56b42b3a18ccebd/frontend/src/app/App.tsx

[S13]: https://github.com/LTstripes/hermes-finance/blob/0f6791c32c4926be29103ad81b3826f22bb8842d/frontend/src/ui-v2/UiV2CapitalAllocationPage.tsx

[S14]: https://github.com/LTstripes/hermes-finance/blob/0f6791c32c4926be29103ad81b3826f22bb8842d/frontend/src/ui-v2/UiV2MonthlyResultPage.tsx

[S15]: https://github.com/LTstripes/hermes-finance/blob/0f6791c32c4926be29103ad81b3826f22bb8842d/frontend/src/ui-v2/UiV2GoalsPage.tsx

[S16]: https://github.com/LTstripes/hermes-finance/blob/0f6791c32c4926be29103ad81b3826f22bb8842d/frontend/src/ui-v2/UiV2DataCatalogsPage.tsx

[S17]: https://github.com/LTstripes/hermes-finance/blob/a9198a46a9efedcf1e60f5628ff308ebe65952dc/frontend/src/ui-v2/UiV2CapitalPerformanceDetail.tsx

[S18]: https://github.com/LTstripes/hermes-finance/blob/0f6791c32c4926be29103ad81b3826f22bb8842d/frontend/src/app/App.tsx

[S19]: https://github.com/LTstripes/hermes-finance/blob/0f6791c32c4926be29103ad81b3826f22bb8842d/frontend/src/ui-v2/UiV2CapitalPage.tsx

[S20]: https://github.com/LTstripes/hermes-finance/blob/0f6791c32c4926be29103ad81b3826f22bb8842d/frontend/src/ui-v2/UiV2IisAccountForms.tsx

[S21]: https://github.com/LTstripes/hermes-finance/blob/0f6791c32c4926be29103ad81b3826f22bb8842d/frontend/src/components/month-close/navigation.ts
