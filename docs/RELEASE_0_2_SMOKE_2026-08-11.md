# Release 0.2 — user smoke log — 2026-08-11

This file records findings from the owner-led manual smoke/backfill pass before the `v0.2.0` release tag.

The release tag remains held until R02-21 and the final release checkpoint/review are complete.

## Completed release work confirmed during smoke

- `R02-17` — DONE: tax brackets administration contract/API/UI. Merge `ffad69208cba1ca33db063f6250ef1712863f066`.
- `R02-20` — DONE: localization of user-facing UI/API errors. Merge `f6b2cb450c2e5ccf5d4fe53d8e803a20cf80b44d`.
- `R02-22` — DONE: numeric/quantity formatting + whole-stock quantity invariant. Final main `cdb439f68a6dade7a4801fbbcbcd5e97a70e5e6e`; exact push CI `31527275884` green.
- `R02-23` — DONE: optional actual-flow instrument starts/resets empty. Merge `6cfa1355f52102d1d734a8496a793753cbb66d65`; exact CI `31526151737` green.
- `R02-24` — DONE: backend-derived NDFL rate(s) in month editor. Merge `264408b4d7a600745ba26b2cc4085c968d19e96b`; exact CI `31526654331` green.

## Smoke finding 1 — historical month editor blocked by incomplete salary-tax history

**Observed:** opening an older draft month failed with `salary_tax_history_incomplete`, preventing data entry.

**Root cause:** `MonthDetailPage` loaded month data, income rows and `/summary` in one `Promise.all`. The expected fail-closed salary-tax summary error therefore rejected the entire editor load.

**Resolution:** the editor now treats only `salary_tax_history_incomplete` as an unavailable calculated-tax slice, keeps the month editable, renders calculated tax/net as unavailable, and preserves any previously stored salary tax rather than replacing it with zero. The backend salary-tax/opening-YTD contract was not weakened.

**Delivery:** PR #15, merge `83271d106ca1065ddf6778540065fe45c0e508cc`.

**Verification:** frontend/backend/privacy/Windows production smoke green on exact PR head before merge.

## Smoke finding 2 — populated draft month could not be deleted

**Observed:** a draft reporting month with entered data could not be deleted, while empty drafts could.

**Root cause:** the UI promised draft deletion, but direct month-owned rows use `ON DELETE RESTRICT`, and the reporting-month service attempted to delete only the parent `reporting_months` row.

**Resolution:** sanctioned draft deletion now removes direct reporting-month-owned rows first and then the draft month in one transaction. Database `RESTRICT` safeguards remain in place globally. Closed months remain undeletable unless explicitly reopened first.

**Delivery:** PR #16, merge `8a77ba92716f5f9b897c91d007e13e16814164b2`.

**Verification:** backend/frontend/privacy/Windows production smoke green on exact PR head before merge.

## Smoke finding 3 — main passive-income goal showed zero dividend component

**Observed:** owner expected newly entered July dividends to contribute to the rolling dividend forecast, while the Dashboard forecast/main goal remained zero for that component.

**Diagnostic:** Codex and Hermes independently performed read-only checks against the local `finance.db`. Both found no rows with `investment_cash_flows.flow_type=dividend`; the relevant actual flows were stored as `coupon`. The full chain therefore correctly remained zero for dividends.

**Owner resolution:** owner confirmed the payment had been entered using the wrong type. The calculation pipeline did not lose a non-zero dividend and no code change is required.

**Status:** R02-25 DONE as diagnostic resolution, not a product defect.

## Additional UX follow-ups from the same smoke

- R02-22/23/24 were implemented and verified before the release candidate.
- R02-26 automatic expected-payment population is DEFERRED; 0.2 documents the existing manual expected-flow workflow explicitly.


## Smoke finding 4 — passive-income Goal подменял текущее значение forecast-метрикой

**Статус:** R02-27 REVIEW.
**Наблюдение:** Dashboard показывал фактический passive income/rolling average по закрытым месяцам, а Goal при пустом expected-calendar учитывал только dividend average и игнорировал фактические deposit interest/coupons в `Текущем значении`.
**Root cause:** `goal_achievement` использовал `forecast_passive_income.monthly_total` вместо C03 actual rolling average.
**Решение:** Goal current/progress переводится на C03 actual average; C04 forecast остаётся отдельной прогнозной метрикой.
**Regression:** actual deposit interest + coupon + dividend при пустом expected calendar должны давать ненулевой Goal current value.

## Release handoff

R02-21 synchronizes version metadata, README/Wiki/CHANGELOG, canonical `RELEASE_0_2.md` status and this smoke record. The final `v0.2.0` tag remains blocked until the release gate and exact-candidate review are complete.
