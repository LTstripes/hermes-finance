# UI v2 Analytics/Home reconciliation

Date: 2026-09-26. Parent: [#570](https://github.com/LTstripes/hermes-finance/issues/570). Tracker: [#554](https://github.com/LTstripes/hermes-finance/issues/554).

Status: initial source-backed parity matrix. It is intentionally not the final v1-retirement acceptance. The matrix must be refreshed on the exact aggregate SHA after the Performance UI stream has accepted implementation and after the UI v2 parity slices it references have landed.

## 1. Exact source state reviewed

UI v2 parity planning source:

- canonical main: 10d545882041593f37d65cf8f56b42b3a18ccebd
- integration/ui-v2-parity: 10d545882041593f37d65cf8f56b42b3a18ccebd
- all legacy/v2 source statements below refer to that exact tree unless another SHA is named.

Performance stream at this review:

- integration/performance-ui-v2 head: 435eac2979555a3574bafd8cbf1e7a6a00e5d640
- that commit is based on f328c82b6c7c3af0f6cd436c7e1d408bb54a8885
- compared with current main, the branch contains one stream-only commit and is behind current main; the only stream-only file is docs/performance/PERFORMANCE_UI_V2_PLAN.md
- #529–#535, #540 and #541 are still open. There is no accepted Phase A or Phase B implementation on that staging head to treat as parity evidence.

Therefore this document distinguishes:

- CURRENT VERIFIED — capability exists on the reviewed main tree.
- EXISTING TASK PENDING — a bounded task already owns the missing native surface.
- GAP / OWNER DECISION — legacy capability has no verified native replacement and must not disappear silently.
- RETIREMENT-ONLY — intentional legacy escape/fallback remains until the separate retirement gate.

No Performance branch content is merged or copied by this document.

## 2. Semantic guardrails

The following concepts are not interchangeable:

1. Monthly monetary investment result is not XIRR/TWRR.
   - frontend/src/api/types.ts defines AccountResultPoint as cash_income plus unrealized_result.
   - backend/src/hermes_finance/services/dashboard.py builds account result from net cash income plus unrealized position result for one reporting month.
   - the class result carries market value, cost basis, unrealized result and realized cash result for one reporting month.
   - this is a RUB monetary snapshot result, not a return rate.

2. Capital delta is not investment performance.
   - UI v2 Home/Capital already labels the closed-report capital change as state change, not investment return.
   - moving value between asset classes can change class rows without increasing total capital.

3. Performance attribution bridge is not P&L/return attribution.
   - VALUE_BRIDGE_LABEL is the exact monetary change after external flows for an evidence-backed interval.
   - it must not be renamed to profit, earned, class return or instrument attribution.

4. Risk allocation/concentration is not class performance.
   - /api/analytics/risk-allocation describes allocation, concentration, denominators, support and future payout/redemption concentration.
   - #534/#535/#540 own a different future question: supported class-specific return rates.

5. UI v2 currently treats confirmed closed data as the default financial picture.
   - /v2 and /v2/capital use the latest closed report.
   - /v2/reports/:monthId is the historical closed-report surface.
   - /v2/income uses the latest closed report for planning data; its month query selects the factual passive-income breakdown, not a historical planning context.
   - legacy /v1 and /analytics allow broader selected-month behaviour, including draft-month snapshots. That difference requires an explicit retirement decision.

## 3. Legacy /analytics capability matrix

| Legacy capability | Exact meaning/source | Native destination on reviewed main | Status | Follow-up / owner |
| --- | --- | --- | --- | --- |
| Capital composition over time | AnalyticsPage uses getCapitalComposition and CapitalCompositionChart over closed history | /v2/capital composition history; /v2/reports/:monthId contextual history | CURRENT VERIFIED | Keep v2 closed-report contract |
| Current allocation by class for a selected closed report | AnalyticsPage loads the selected month dashboard and renders dashboard.asset_allocation | latest closed: /v2/capital; older closed: /v2/reports/:monthId | CURRENT VERIFIED for closed reports | Draft selection is covered separately below |
| Current allocation for a selected draft | Legacy selector accepts drafts and getDashboard(monthId) can render the draft snapshot | no confirmed-data native analytics destination | GAP / OWNER DECISION | Decide whether draft analytics is intentionally retired or needs a bounded preview in editor/close |
| Monthly result by account | dashboard.result_by_account = cash income plus unrealized result, in money, for one reporting month | no v2 surface renders this result | GAP / OWNER DECISION | Proposed bounded follow-up: Capital → monthly monetary result, using existing Dashboard API; do not fold into XIRR/TWRR |
| Monthly result by instrument class | dashboard.result_by_instrument_class = market/cost/unrealized plus realized cash result for one reporting month | no v2 surface renders this result | GAP / OWNER DECISION | Same proposed follow-up; #540 class return table is not a replacement |
| Exact monetary bridge after external flows | getPerformanceAttribution for the interval between two closed snapshots | /v2/capital PerformanceBlock renders the same attribution API for the current adjacent closed pair | CURRENT VERIFIED for current adjacent pair | Broader period UX belongs to #529/#531 |
| Portfolio XIRR | annualized money-weighted return from the canonical performance API | /v2/capital PerformanceBlock | CURRENT VERIFIED for current adjacent pair | Period/account detail pending #529–#531 |
| Portfolio TWRR | return over selected evidence-backed interval from canonical performance API | /v2/capital PerformanceBlock | CURRENT VERIFIED for current adjacent pair | Diagnostics/capture/period UX pending #529–#533 |
| Older closed-pair performance selection | selecting an older closed month in /analytics changes the closed pair used for bridge/XIRR/TWRR | current /v2/capital is latest closed pair only | EXISTING TASK PENDING | #529 contract + #531 UI must define supported periods/scopes before retirement |
| Allocation by class/account, top positions | /analytics/risk-allocation uses getRiskAllocation | /v2/capital already exposes current allocation, account buckets and top positions | PARTIAL | #569 owns the full compact native detail |
| Payout concentration, redemption concentration and support matrix | RiskAllocationPage exposes future-event concentration plus support metadata | not fully present in /v2/capital | EXISTING TASK PENDING | #569 |
| Open/create selected month actions | AnalyticsPage links to /months or /months/:id | native month management/editor not yet complete | EXISTING TASK PENDING | #557/#558 and subsequent editor slices |
| Legacy /analytics route itself | mixed historical capital, monthly result, risk/performance links | no one-to-one replacement is desirable; capabilities are split by meaning | RETIREMENT-ONLY | Redirect/removal only after matrix has no unresolved gaps |

## 4. Legacy /v1 Dashboard capability matrix

The old dashboard is not one feature. Its functions have already split naturally across Home, Capital and Income.

| Legacy dashboard capability | Native destination | Status | Evidence / caveat |
| --- | --- | --- | --- |
| Liquid capital and month-over-month change | /v2 Home and /v2/capital | CURRENT VERIFIED for latest closed report | v2 uses confirmed closed-report comparison and explicitly labels change as non-performance |
| Asset-class breakdown | /v2 Home, /v2/capital, /v2/reports/:monthId | CURRENT VERIFIED for closed reports | historical closed detail is available in Reports |
| Capital history | /v2 Home and /v2/capital | CURRENT VERIFIED | both use canonical closed-report history |
| Passive income actual / average / history | /v2 Home and /v2/income | CURRENT VERIFIED | /v2/income also allows explicit factual closed-month selection |
| 12-month passive-income forecast and breakdown | /v2/income | CURRENT VERIFIED for latest closed planning context | IncomePlanSummary composes the same canonical forecast service; no frontend formula recreation |
| Cash-flow ladder / upcoming events | /v2/income | CURRENT VERIFIED for latest closed planning context | native Income uses the canonical cash-flow ladder service and keeps redemption principal separate from income |
| Mandatory-expense coverage, actual and forecast | /v2/income | CURRENT VERIFIED for latest closed planning context | same canonical coverage service |
| Mortgage balance and capital coverage | /v2/capital PropertyBlock | CURRENT VERIFIED for latest closed report | property/mortgage remains separate from liquid capital |
| Goal summary / progress | /v2 Home and /v2/income have summary cards | PARTIAL | full native goal detail/editing and selected as-of context are owned by #552 |
| Goal action from dashboard | currently still points to legacy /goals | EXISTING TASK PENDING | #552 |
| Open/create/all months actions | legacy /months routes | EXISTING TASK PENDING | #557/#558 and editor slices |
| Select any reporting month and recompute the whole dashboard | legacy /v1 supports arbitrary selected month, including draft | no equivalent global v2 context selector | GAP / OWNER DECISION | see section 6 |
| Historical/draft forecast, coverage and ladder for the arbitrarily selected month | legacy dashboard computes these for selected month | /v2/income intentionally plans from latest closed only | GAP / OWNER DECISION | do not claim parity merely because latest-closed Income exists |
| Link to Analytics | legacy mixed destination | split among /v2/capital, /v2/income, Reports, #569 and Performance work | RETIREMENT-ONLY | redirect only after remaining gaps are resolved |

## 5. Route / period / scope contract that must survive integration

These rules are present on the reviewed main tree and should be preserved unless a later accepted task changes them explicitly.

### /v2 — Home

- Data picture is latest closed report.
- A newer draft is a workflow action/banner, not the displayed financial truth.
- Historical report navigation goes through /v2/reports.
- It is not a general selected-month dashboard.

### /v2/capital

- Main content is latest closed report.
- Current PerformanceBlock uses the adjacent closed pair derived from closed-report history.
- Query month/step handling currently participates in the legacy return path; it does not turn Capital into a selected historical month view.
- Historical closed detail belongs to /v2/reports/:monthId.
- Shared Capital route/spine changes must be reconciled with #531 and #569 by the Integrator.

### /v2/reports/:monthId

- Historical closed report only.
- Draft is rejected as a historical report.
- Latest closed report is intentionally represented by current Home/Capital rather than duplicated as an archive page.
- The report contains capital values/composition/history/holdings/top positions, but it does not currently restore the legacy monthly monetary result by account/class.

### /v2/income

- Planning context is the latest closed report.
- The month query controls the factual passive-income report selection among closed months.
- It does not change forecast, coverage, goals or ladder to an arbitrary historical/draft planning month.
- #551 may polish copy/order; #552/#553/#556 add Goals/Tax/Scenario native destinations without changing Performance semantics.

### Performance future contract

- #529 owns the exact period/scope/navigation contract.
- #531 owns the portfolio/account native Performance detail and shared routing in its stream.
- #532/#533 own evidence preparation/capture only after accepted contracts.
- Phase B #534/#535/#540 is class-return work. It does not replace the legacy monthly monetary result table.

## 6. Explicit Owner decisions still required

### D1 — monthly monetary result by account and class

Current finding: real legacy capability, no native equivalent.

It should not be silently dropped and must not be relabelled as Performance.

Recommended bounded follow-up, not created by #570:

- owner stream: integration/ui-v2-parity
- proposed destination: a compact Capital detail such as “Денежный результат месяца”
- data: existing getDashboard(reportingMonthId).result_by_account and result_by_instrument_class
- views: “По счетам / По классам”
- units: money only; keep realized cash income and unrealized result separate, with total only where current semantics support it
- no XIRR/TWRR, no new formulas, no attribution, no new backend contract unless a real gap is found
- closed-report context first; any draft support depends on D2.

Until Owner either accepts this follow-up or explicitly accepts removal of the capability, v1 retirement is blocked.

### D2 — arbitrary month / draft analytics and planning

Legacy /v1 and /analytics permit a global month selector. UI v2 intentionally separates:

- confirmed financial picture: latest closed;
- historical facts: Reports / factual Income history;
- draft work: close/editor workflow.

Product recommendation for the retirement decision: do not recreate the old global selector merely for visual parity. Prefer to retire historical/draft forecast and coverage views if Owner confirms they are not needed, while preserving:

- closed historical facts in Reports;
- factual income history in Income;
- draft editing/readiness in native month editor/close;
- any specifically valuable draft preview as a narrow editor/close block rather than making Home/Capital look confirmed.

If Owner wants historical/draft planning parity, create a separate bounded task with explicit period semantics. It must not silently overload /v2/income?month= because that parameter currently means factual income selection.

D2 must be recorded explicitly before #573; absence of a replacement is not evidence that the capability was intentionally retired.

## 7. Existing tasks that close known gaps

| Task | Reconciliation role |
| --- | --- |
| #552 | Full native Goals detail/editing and as-of context |
| #557/#558 + editor slices | Native month lifecycle/editor replacing legacy open/create/edit actions |
| #569 | Full allocation/concentration detail including payout/redemption concentration and support |
| #529–#531 | Performance period/scope/diagnostics plus portfolio/account UI |
| #532/#533 | Supported evidence correction/capture for Performance Phase A |
| #534/#535/#540 | Phase B class returns, only after explicit accepted contract |
| #541 | Performance aggregate verification/UAT checkpoints |
| #571 | Final native Monthly Close wiring |
| #572 | Aggregate UI v2 parity verification and Owner UAT |
| #573 | Separate v1-retirement decision gate |

#551 and #553 are neighbouring UI v2 work but do not prove Analytics/Home parity by themselves. #538 remains the owner of portfolio-source coverage beside owner-facing capital values and must not be reimplemented here.

## 8. Performance Phase A / Phase B status at this review

### Current main

The existing /v2/capital PerformanceBlock already shows:

- exact monetary attribution bridge when available;
- portfolio XIRR;
- portfolio TWRR;
- one adjacent interval between two closed reports;
- honest unavailable reasons from existing message mapping.

This is a real current capability and can replace the matching latest-pair part of legacy Analytics.

### Phase A — not yet accepted in the Performance staging reviewed here

Open plan:

- #529 period/scope/action contract
- #530 metric-specific diagnostics
- #531 portfolio/account Performance detail
- #532 evidence preparation
- #533 PRE/POST capture
- #541 checkpoint A

Until accepted candidates exist, #570 must not claim account drill-down, richer period selection or write/capture workflow as implemented.

### Phase B — not yet accepted

Open plan:

- #534 class-return contract
- #535 backend/API after explicit scope acceptance
- #540 class UI
- #541 checkpoint B

Phase B being unfinished does not automatically block retirement of unrelated legacy functions. However any legacy function that would otherwise disappear still needs a verified replacement or explicit Owner de-scope.

In particular, result_by_instrument_class is monthly monetary result and is not satisfied by a future class-return table.

## 9. Retirement refresh checklist

Before #573 can become READY_FOR_OWNER_DECISION, refresh this document or an equivalent exact-SHA matrix and verify:

- one exact integration/ui-v2-parity aggregate SHA;
- accepted Performance exact SHA(s) and their ancestry/compatibility with the UI v2 parity aggregate;
- accepted #569 and #552 destinations where applicable;
- D1 resolved: native monetary-result replacement or explicit Owner de-scope;
- D2 resolved: explicit decision on arbitrary historical/draft planning analytics;
- ordinary v2 navigation no longer depends on /analytics or /v1 for required actions;
- intentional “previous interface” escape/fallback is listed separately from required product navigation;
- deep link/back/refresh retain period/scope identity;
- no selected historical/draft request is silently replaced by latest closed;
- null/unknown/partial remain distinct from zero/complete;
- monetary result, state change, return rate and risk allocation remain separately labelled;
- aggregate Owner UAT #572 is performed on the same reviewed tree.

A green Performance CI, existence of a similar-looking card, or closure of this documentation task is not by itself evidence that /v1 can be removed.
