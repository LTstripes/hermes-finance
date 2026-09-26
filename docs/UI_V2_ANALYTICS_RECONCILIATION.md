# UI v2 Analytics/Home reconciliation

Date: 2026-09-26. Parent: [#570](https://github.com/LTstripes/hermes-finance/issues/570). Tracker: [#554](https://github.com/LTstripes/hermes-finance/issues/554).

Status: initial source-backed parity matrix, updated with Owner D1/D2 scope decisions. Independent financial/product review remains pending. This is not final parity acceptance, Owner UAT or permission to remove v1. Refresh on the exact aggregate SHA after the relevant UI v2 and Performance implementations are accepted.

## 1. Exact source state reviewed

- Canonical main and `integration/ui-v2-parity`: `10d545882041593f37d65cf8f56b42b3a18ccebd` (source baseline below).
- Initial docs candidate: `e964717dfd24f51e371f8ed6302a7468abaad381`, draft PR #574. Its CI `36250120480` passed; that result does not cover subsequent commits.
- Performance staging at the initial audit: `435eac2979555a3574bafd8cbf1e7a6a00e5d640`, based on `f328c82b6c7c3af0f6cd436c7e1d408bb54a8885`.
- Relative to the split base, that Performance head adds only `docs/performance/PERFORMANCE_UI_V2_PLAN.md`; it is not the later canonical main plus implemented Phase A/B. No accepted Phase A/B implementation was present on that inspected staging head.
- #529–#535, #540 and #541 were open at the audit. This is dated evidence, not a claim that their status can never change.

Source links below are pinned to the exact source baseline. `SOURCE MATCH` means a capability was found in source for the stated context, not runtime/e2e/UAT PASS. `PARTIAL` means only some contexts/components match; `PENDING` identifies an existing implementation task; `OWNER DE-SCOPED` records an explicit bounded product decision; `RETIREMENT-ONLY` is intentional legacy routing retained until #573.

No product code, API, financial formula, data, route or Performance branch is changed by this document.

## 2. Semantic guardrails

1. **Monetary result for a reporting month is not XIRR/TWRR or profit earned during that month.** [Dashboard result service][S3] and [DTO/chart][S2] combine cash income recorded in the selected month with unrealized result from open-position snapshots. The latter is not the month-over-month change in unrealized result. Keep both components separately labelled; do not rename their displayed sum to "earned this month".
2. Account results and instrument-class results are not identical scopes. Cash events without an instrument can appear by account but not by class. A cash-income-only class has no current market/cost/unrealized evidence; preserve its null values and unavailable total, not invented zeros. Class grouping here is `instrument_type`, not a new Performance asset-class taxonomy. [S3][S3]
3. Capital delta is a change of state, not investment return. Home/Capital already label the distinction; class transfers may change rows without increasing capital. [Home][S5], [Capital][S4]
4. The exact monetary bridge after external flows is not P&L, "earned" or class/instrument return attribution. Preserve the existing labels, exactness gate, scope, currency and interval. [Analytics][S1], [Capital][S4]
5. Allocation/concentration is not class performance. Risk allocation describes denominators, support, holdings and future payout/redemption concentration; #534/#535/#540 own future class-specific return rates. [Risk][S8], [Performance plan][S9]
6. Current v2 Home/Capital and Income planning use latest closed data; historical facts and draft work have separate destinations. D2 below approves not recreating the old global selected-month planning mode, not deleting local factual or workflow context.

## 3. Legacy /analytics capability matrix

| Legacy capability | Meaning/source on baseline | Native destination | Status | Follow-up / owner |
| --- | --- | --- | --- | --- |
| Capital composition over time | [Analytics][S1]: closed history, amount/share modes | [Capital][S4] history; [Reports][S7] contextual history | SOURCE MATCH | Preserve closed-report scope and gaps |
| Current allocation for a selected closed report | Selected dashboard `asset_allocation` | Latest closed: Capital; older closed: Reports | SOURCE MATCH | Context must remain visible |
| Global selected-draft analytics view | Legacy month selector accepts drafts | Do not recreate as a global confirmed-data analytics mode | OWNER DE-SCOPED D2 | Editor/close and separately scoped local tools remain |
| Monetary result by account | `result_by_account`: monthly cash income plus unrealized snapshot component | `/v2/capital/monthly-result` assigned by #575, not implemented | PENDING #575 | D1 KEEP; no rate conversion |
| Monetary result by instrument class | `result_by_instrument_class`; class cash-only nulls preserved | Same #575 detail, class view | PENDING #575 | #540 class return table is not a replacement |
| Exact bridge after external flows | Canonical attribution for a closed-snapshot interval | Capital PerformanceBlock, current adjacent closed pair | SOURCE MATCH for latest pair | Historical/richer periods remain #529/#531 |
| Portfolio XIRR | Annualized canonical return rate | Capital PerformanceBlock | SOURCE MATCH for latest pair | Period/account detail #529–#531 |
| Portfolio TWRR | Canonical return over interval | Capital PerformanceBlock | SOURCE MATCH for latest pair | Diagnostics/capture #529–#533 |
| Older closed-pair Performance selection | Legacy older closed-month choice changes bridge/XIRR/TWRR interval | Current Capital uses latest pair only | PENDING #529/#531 | D2 does not remove historical Performance periods |
| Allocation by class/account, top positions | [RiskAllocationPage][S8] | Capital has current allocation, account buckets, top positions | PARTIAL | #569 full native detail |
| Payout/redemption concentration and support matrix | Risk future-event concentration and support | Not fully present in Capital | PENDING #569 | Preserve future window, denominator and exclusions |
| Open/create selected month actions | Legacy `/months` and `/months/:id` | Native month management/editor pending | PENDING #557/#558 and slices | Preserve exact month/action |
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
| Goal summary/progress and action | Home/Income summary; full Goals pending | PARTIAL / PENDING #552 | Retain local goal/as-of context, not a second global selector |
| Open/create/all months | Native month management/editor pending | PENDING #557/#558 and slices | Editor/close workflows remain |
| Select arbitrary month and recompute whole Dashboard | No global v2 replacement planned | OWNER DE-SCOPED D2 | Current picture remains latest closed |
| Historical/draft forecast, coverage, ladder in that global mode | Do not recreate this global planning mode | OWNER DE-SCOPED D2 | Not a deletion of underlying APIs/history or local task contracts |
| Link to mixed Analytics | Split among Capital, Income, Reports, #569/#575 and Performance | RETIREMENT-ONLY | Only remove after kept capabilities and route handling are verified |

This is the initial mapped capability inventory, not proof that every legacy field/help/annotation is replaced. #572 must check the accepted scope and surface any additional gaps; D2 is not a catch-all waiver for unrelated losses.

## 5. Route / period / scope contract

### Home and Capital

- `/v2` and `/v2/capital` show latest closed data. A newer draft is workflow context, not confirmed financial truth.
- Their current `month`/`step` handling contributes to a legacy return path; it does not select a historical main-data view. Do not pretend otherwise by changing only a link label. [Home][S5], [Capital][S4]
- Historical closed capital facts live in `/v2/reports/:monthId`; current latest closed is deliberately handled by Home/Capital rather than duplicated in the archive. [Reports][S7]
- Shared Capital/routes/entry/shell changes are Integrator-owned, reconciled with #555, #569, #575 and #531. No simultaneous competing authorities.

### Income

- `/v2/income` plans from latest closed. Its `month` selects factual passive-income breakdown, not historical/draft planning, goals or ladder. [Income][S6]
- D2 does not overload this parameter or remove legitimate local month/as-of selection in #552 Goals, #553 Tax/IIS, #556 Scenario Lab or #569 risk detail. Those task contracts remain unchanged.

### Monetary-result detail assigned to #575

- `/v2/capital/monthly-result?month=<id>` is a local read-only closed-report selector, latest or older closed, not a global Home/Capital mode.
- No `month`: explicitly identify latest closed. Invalid/deleted/draft/reopened explicit target: explain, do not silently substitute latest closed.
- Bounded `view=accounts|classes`, correct back/refresh and native return. Exact-month links from historical Reports.
- Existing Dashboard DTO only. No new financial formulas or class-return scope. This route is assigned work, not a currently registered capability.

### Performance

- #529 owns exact period/scope/action contracts; #531 owns portfolio/account detail and its stream routing.
- #532/#533 own accepted evidence/capture paths, not parity Workers.
- Historical Performance periods remain required under the accepted Performance scope. D2 does not waive them.
- Phase B is separate class-return work. Neither #540 nor risk allocation replaces #575 monetary results.

### Legacy compatibility

All existing routes remain during this work. D2 is an approved future scope reduction, not permission to redirect/delete now. At retirement, explicitly explain a de-scoped context or provide supported destinations; never silently render latest closed as the requested historical/draft result. [App routes][S12]

## 6. Owner decisions — recorded 2026-09-26

Authority: [Integrator record of the actual Owner chat decision](https://github.com/LTstripes/hermes-finance/issues/570#issuecomment-5847307129). After the proposal to keep the monetary result and not reproduce the global historical/draft analytics mode, Owner replied: **«Да давай так и сделаем и идём дальше»**.

The linked note is an Integrator transcription of that instruction. Publishing through the Owner's GitHub connection does not itself constitute an independent Owner decision, review or UAT.

### D1 — KEEP approved; implementation pending #575

- Preserve monetary result by account and instrument class in a compact Capital detail, using existing Dashboard API.
- Keep closed historical factual context and separate cash-income/month versus unrealized/snapshot meanings.
- No second XIRR/TWRR implementation, no new financial calculations, no artificial portfolio/class totals.
- Decision is settled; delivery is not. #575 needs implementation, exact-SHA evidence, independent review and inclusion in #572 before retirement can use it as parity proof.

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
| #575 | D1 native monetary result; required by #572/#573, independent of Performance Phase B |
| #552 | Full Goals detail/editing and local as-of context |
| #557/#558 + editor slices | Native month lifecycle and write actions |
| #569 | Full allocation/concentration detail and support |
| #529–#531 | Performance period/scope/diagnostics and portfolio/account UI |
| #532/#533 | Supported Performance evidence/capture |
| #534/#535/#540 | Phase B class-return contract/backend/UI, not #575 |
| #541 | Performance verification/UAT checkpoints |
| #571 | Full native Monthly Close wiring |
| #572 | Aggregate parity, including #575 and the exact D2 scope boundary |
| #573 | Separate v1-retirement decision packet and authorization |

#551/#553 remain separate neighbouring work. #538 owns portfolio-source coverage metadata; no React-side replacement rules here. #555 can proceed independently of this docs review, within its existing narrow navigation scope and verified workspace/spine assignment.

## 8. Performance checkpoint status at the initial audit

Current main has a real portfolio bridge/XIRR/TWRR block for the adjacent latest closed pair, with existing unavailable messages. That is source parity for that interval only, not new account drill-down or evidence-entry capability. [Capital][S4]

Phase A was not accepted on inspected Performance staging: #529 contract, #530 diagnostics, #531 period/account UI, #532 preparation, #533 observed PRE/POST capture, #541 checkpoint A. Phase B was likewise pending: #534 contract, #535 backend after scope acceptance, #540 class UI, #541 checkpoint B. [Plan][S9]

An unfinished new Phase B does not automatically block delivery of unrelated retained legacy capabilities. Conversely, its future table cannot be cited as a delivered replacement for old monetary-result fields. Re-read the actual accepted candidates before final reconciliation; do not copy the staging branch or rely on open issue promises.

## 9. Retirement refresh checklist

Before #573 can become READY_FOR_OWNER_DECISION:

- Confirm one exact parity aggregate SHA and accepted Performance heads/compatibility; record actual Phase A/B status.
- Verify implemented #575, including closed historical context, cash-only nulls and accurate labels. D1 approval is not delivery.
- Carry the D2 decision link forward; verify its narrow boundary without deleting local factual/Performance contexts.
- Verify other retained native destinations, including #552/#569/editor/close and additional gaps found by #572.
- Verify every required ordinary action without legacy dependence; list intentional v1 escape/fallback separately.
- Check query/hash/period/scope/back/refresh, invalid/deleted/reopened targets and explicit handling of de-scoped contexts.
- Keep null/unknown/partial distinct from zero/complete; do not conflate monetary result, capital state change, return rate and risk allocation.
- Obtain independent financial/product review of this matrix and later changes.
- Run aggregate Owner UAT #572 on the same tree; obtain the separate #573 Owner permission before any removal implementation.

A green CI or the accepted D1/D2 scope decisions do not authorize removal. Legacy routes remain intact until the separate approved retirement PR.

## Source manifest

These are immutable source references for the initial audit, not claims of runtime tests. Later accepted heads must replace/update the relevant evidence at aggregate refresh.

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
