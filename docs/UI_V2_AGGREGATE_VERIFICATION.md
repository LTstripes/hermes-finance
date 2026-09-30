# UI / Performance common-tree verification — #572

Assignment: [Integrator launch packet](https://github.com/LTstripes/hermes-finance/issues/572#issuecomment-5900360825), 2026-09-30. One final-assembly Worker; no orchestration. This document is a verification inventory, not independent ACCEPT, READY_FOR_OWNER_UAT or Owner PASS.

## Identity and accepted ancestry

| Identity | Commit | Git tree |
| --- | --- | --- |
| Accepted UI baseline | `17af4c29ed5ab02472c6f4378e59cf54fd7fa1aa` | `d3112129f9aef0f942a1496905c6893d7884438c` |
| Accepted Performance input | `47a798de5b979fcd50b5a9880330e2c3eef62b56` | `7c42553ab0f11f92e36ca4586e9ea5ebb8cdf566` |
| Required canonical main ancestor | `ee9faea0b49f08454c284deb0db926f8db981a9d` | `8a61161ee8756885cb21e8a76f4f9c78480424b9` |
| Two-parent union | `2dcd7336a6b2d75790399c694c66ac778e833082` | `59e1aa79b54fb39ec77f928429bb70e7727573ef` |
| Frozen code/CI/spec anchor | `5d3819ad6ba9acd9d07555cbfc52968f5e3ccd06` | `ca763ecb54c99c79f58517e9ec5198afb3736117` |

The union's parents are the exact UI and Performance inputs. Required ancestry also includes accepted #568 `9c72ebd095fcf23b25abc217070e34749ee1274b`, #569 `a22cb77c4c61de9eb1e493d2a392fa66f8a77585`, #575 `660895c1f7a87c59d7d2b2749423224445c42040`, #571 `f69d2603709a06ac483875415bef6fc247c347cc`, #574 `f549bd8f7986178d488544349aed5347b64e16cf` and #641 `95097f75174116f608f761f791d0ee500e9e56ca`.

Final code+docs HEAD and its tree are returned in the PR/body and Worker report. They are descendants of the source anchor; this file cannot truthfully name its own commit. Native source references in [#570 reconciliation](UI_V2_ANALYTICS_RECONCILIATION.md) pin that anchor. Old leaf/staging CI is historical prerequisite evidence only.

## Shared-spine reconciliation

- Mechanical App/entry conflicts were resolved additively: allocation, monthly-result and Performance detail each keep their own route/lazy entry. No sibling was selected wholesale.
- Capital combines accepted allocation and monetary-result links with accepted Performance summary/detail. Monetary result is cash income for a reporting month plus separately labelled unrealized snapshot evidence; Performance uses exact snapshot dates, historical scope and backend-owned interval returns. Neither replaces the other.
- Main/#538 and #621–#624 source/coverage and lifecycle protections remain in ancestry. The union uses canonical readiness, preserves null/unknown/partial, and retains existing query keys. Mutation invalidation and restore invalidation retain Performance and Monthly Close reads; no financial calculation was added in React.
- Empty Home/Capital/Income close actions now go to `/v2/close`; Home's payouts/forecast action goes to `/v2/income`. Native Monthly Close origin/step/month query and editor return mapping are retained. Explicit legacy-origin routes still work.
- Required `g04-browser` CI job runs G04 and Performance, builds the production frontend, then runs the accepted statement and Monthly Close configs serially, with zero retries. Synthetic screenshots/traces are retained as `native-v2-real-backend-evidence`. Full Vitest uses `--maxWorkers=1` locally and in CI.
- Visual discovery adds existing month/editor/import/payout/IIS/allocation/Scenario specs. Allocation uses `/v2/capital/allocation` on the actual App route rather than the standalone leaf fixture. API-mocked visual evidence remains distinct from real-backend evidence.

## Job / spec / scenario matrix

Paths below are under `frontend/` unless another root is shown. A listed spec is a mapping, not a claim it ran; exact execution outcomes are recorded below and in final-head CI.

| Capability / boundary | Native route or action | Executable evidence / canonical job |
| --- | --- | --- |
| Default entry, Shell, route union, lazy failure | `/`, `/v2`, three Capital details; explicit v1 escape | `src/app/App.test.tsx`, `src/ui-v2/UiV2Shell.test.tsx`, `e2e/ui-v2-default-switch.spec.ts`; frontend / visual / UI evidence |
| Home confirmed picture; empty/first/zero/partial/error | `/v2` latest CLOSED; native close action | `src/pages/UiV2Page.test.tsx`, `e2e/ui-v2.visual.spec.ts`; frontend / visual |
| Capital state/history/holdings/coverage and returns | `/v2/capital`; no capital delta as return | `src/pages/UiV2CapitalPage.test.tsx`, `e2e/ui-v2.visual.spec.ts`; frontend / visual |
| Closed historical monetary result by account/class | `/v2/capital/monthly-result?month=<closed-id>&view=accounts|classes` | `src/pages/UiV2MonthlyResultPage.test.tsx`, `e2e/ui-v2.visual.spec.ts`; latest/older, zero/loss, cash-only nulls, account-only events, stale/reopened/restore identity |
| Allocation/concentration/support | `/v2/capital/allocation?month=<id>` | `src/ui-v2/UiV2CapitalAllocationPage.test.tsx`, `e2e/ui-v2-capital-allocation.spec.ts`; selected draft/closed, unsupported denominator, desktop/390px/keyboard; frontend / visual |
| Income facts/planning/forecast/ladder | `/v2/income`; historical facts remain local | `src/pages/UiV2IncomePage.test.tsx`, `e2e/ui-v2-income.visual.spec.ts`; frontend / visual; principal is not passive income |
| Goals CRUD/main/active/local as-of | `/v2/income/goals?month=<id>` | `src/pages/GoalsPage.test.tsx`, `src/app/App.test.tsx`, `e2e/ui-v2-income.visual.spec.ts`; frontend / visual |
| Tax/IIS planning and account write tools | `/v2/income/tax-iis`, `/v2/data/catalogs?tab=accounts&account=<id>` | `src/ui-v2/UiV2TaxIisPage.test.tsx`, `src/ui-v2/UiV2IisAccountForms.test.tsx`, `e2e/ui-v2-iis-forms.spec.ts`; account/year identity, readback, ambiguous lock, keyboard/390px |
| Months create/clone/delete/local selection | `/v2/data/months` | `src/ui-v2/UiV2MonthsPage.test.tsx`, `e2e/ui-v2-months.spec.ts`; frontend / visual; clone source lifecycle also in backend full |
| Six editor slices and dirty navigation | `/v2/data/months/:id?section=...` | `src/ui-v2/UiV2MonthEditorPage.test.tsx`, `UiV2MonthPositionsSection.test.tsx`, `UiV2MonthAssetsSection.test.tsx`, `UiV2MonthPayoutsSection.test.tsx`, `UiV2MonthBudgetSection.test.tsx`, `UiV2MonthLiabilities.test.tsx`; `e2e/ui-v2-month-editor.visual.spec.ts` (mocked API) |
| Native import/apply/authoritative persistence | `/v2/data/payouts?month=<id>#statement-import` | `e2e/statement-import.acceptance.ts` via `playwright.statement.config.ts`; **real backend**, temp SQLite/synthetic PDF, cancel, foreign-month row disabled, one keyboard write, reread/reload/duplicate, desktop/390px; `g04-browser` |
| Import failed/ambiguous/stale/CLOSED state | Native statement/Alfa tools | `src/ui-v2/UiV2StatementImportSection.test.tsx`, `src/ui-v2/UiV2AlfaBaselinePage.test.tsx`, `e2e/ui-v2-statement-import.spec.ts`; backend import/atomicity tests; frontend / visual / backend lanes |
| Forecast payouts and calendar | `/v2/data/payouts?month=<id>` | `src/ui-v2/UiV2PayoutForecastPage.test.tsx`, `e2e/ui-v2-payout-forecast.spec.ts`; frontend / visual; dated principal and passive income remain distinct |
| Monthly Close native edit/return/fresh final review | `/v2/close?month=<id>&step=final_review_close` | `e2e/monthly-close.acceptance.ts` via `playwright.monthly-close.config.ts`; **real backend**, persisted expense, fresh workflow read on return, dirty cancel/discard, failed write and mismatched read guards; `g04-browser` |
| Close/report/reopen; historical archive | Same close context, `/v2/reports/:id` | Same retained **real-backend** scenario: confirmation cancel, persisted CLOSED, hidden mutations, actual older archive after a later closed report, refresh, next-month return, explicit reopen; desktop/390px/keyboard |
| Repeat/stale/concurrent CLOSED/deleted/invalid target | Close and editor exact month | `src/pages/UiV2ClosePage.test.tsx`, `src/pages/MonthlyCloseWorkflowPage.test.tsx`, editor tests and real-backend deleted/duplicate query checks; backend close/write atomicity in full lanes |
| Reports/archive latest/draft/missing/coverage | `/v2/reports`, `/v2/reports/:id` | `src/pages/UiV2ReportsPage.test.tsx`, `src/pages/UiV2ReportPage.test.tsx`, `e2e/ui-v2.visual.spec.ts` and actual archive above |
| Performance unavailable -> XIRR-only -> observed PRE/POST -> TWRR | `/v2/capital/performance?start=...&end=...&scope=account&account_id=...` | `e2e/performance-real-backend.spec.ts`; **real backend**, public supported writes, temporary SQLite, no provider calls; correction invalidates coverage/captures, stale form gets 409, CLOSED write rejected, Back/refresh/390px/keyboard; `g04-browser` |
| Performance period/scope/error/null/zero/unsupported | Same detail; preparation hash/context | `src/ui-v2/UiV2CapitalPerformanceDetail.test.tsx`, `capitalPerformanceContext.test.ts`, existing preparation/capture component tests, `e2e/performance-preparation.visual.spec.ts`; frontend / visual; historical membership is explicit |
| Freshness/reconciliation/accounts/catalogs/mappings/settings/diagnostics | `/v2/data`, `/v2/data/reconciliation`, `/v2/data/catalogs`, `/v2/data/app` | `src/pages/UiV2DataSourcesPage.test.tsx`, `UiV2DataReconciliationPage.test.tsx`, `UiV2DataCatalogsPage.test.tsx`, `UiV2DataAppPage.test.tsx`, `e2e/ui-v2-data.visual.spec.ts`; frontend / visual; provider calls remain mocked/offline |
| Export/download/backup/restore | `/v2/data/files` | `src/pages/UiV2DataFilesPage.test.tsx`: exact restore confirmation/focus, failed/ambiguous results, no repeat, financial reads invalidated; monthly-result stale restore identity tests; real-backend Close scenario deletes/restores synthetic month then reloads |
| Scenario input/result/local month/export | `/v2/income/scenario-lab?month=<id>` | `src/ui-v2/UiV2ScenarioLabPage.test.tsx`, `e2e/ui-v2-scenario.spec.ts`; calculate, backend DTO/download, desktop/390px/keyboard/Back/refresh; frontend / visual; canonical financial service in backend full |
| Retained v1 and safety gates | Legacy routes remain | `e2e/g04-smoke.spec.ts` unchanged in required browser job; privacy, backend quality/full lanes, Windows timezone/production smoke, release safety and applicable launcher harness in canonical CI |

Full local backend and frontend gates cover all retained tests, including failure cases above. They do not turn an API-mocked component/visual test into real persisted financial evidence. The synthetic Close restore probe explicitly reloads after a confirmed backend restore; UI transport/ambiguous/failed restore behavior has component and backend coverage, not a claim of a real-history Owner restore.

## Ordinary links and deliberate legacy fallback

Ordinary close actions from empty Home/Capital/Income now stay native; Home's income/forecast action stays native. Native Close action maps and Final Review Edit links preserve exact month/step/section; current CLOSED review hides mutations.

Explicit previous-interface links remain in Shell's labelled legacy group, lazy load/error fallback, contextual v1 return, Capital's previous-interface calculations link, report/archive handoff, data freshness/reconciliation/catalog/settings handoff and no-month export/catalog help. Catalog's `Открыть месяцы` empty-state link is introduced by text explicitly saying `в предыдущем интерфейсе`. These are retained escape/help actions, not proof of retirement readiness. Legacy-origin `/months/:id/close#step` and `/accounts` imports remain intentional; native-origin Close uses only the accepted native map. D1 KEEP and D2's bounded global-selector reduction are unchanged; local facts/editor/Goals/Tax/Scenario/risk/Performance context remains.

## Execution evidence and remaining gates

Local evidence on navigation/CI commit `b83c98dee24e9d3364130cd244ae82b8f3ccef45`: lint/format/build and focused 145 tests passed; retained real-backend G04/Performance 2, statement import 1 and Monthly Close/archive/reopen/restore 1 passed locally before the documentation refresh. Exact local full-gate and final-head CI outcomes are returned in the PR evidence/report; absent/pending checks remain pending.

Independent integration/product/lifecycle review must use the exact final candidate in a separate read-only context. Owner runtime/data assignment is not supplied: [Owner runbook](UI_V2_OWNER_UAT.md) requires a separately approved representative-history copy and backup. No private-data testing occurred. Worker delivery cannot declare READY_FOR_OWNER_UAT, project ACCEPT or Owner PASS. Main/staging writes, release/version selection, production data promotion, Phase B and v1 retirement remain outside this task.

First expanded visual execution found six instances of the same strict locator ambiguity: `Выбран` matched both the exact selected-month badge and explanatory prose. The assertion now uses `exact: true`; it still requires the visible badge. Desktop and 390px focused retest passed. The first full execution also recorded `source_changed_during_check` because this documentation was written concurrently; it is not accepted as a stable full PASS. The required full visual gate is repeated after freezing code/config/docs. Checkout-only CRLF initially failed frontend format; LF normalization produced no bulk Git content diff, then the full format check passed.
