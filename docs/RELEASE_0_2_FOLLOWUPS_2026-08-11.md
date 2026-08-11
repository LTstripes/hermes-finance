# Release 0.2 — owner smoke follow-ups — 2026-08-11

These bounded follow-ups were discovered during the owner-led manual backfill/UI smoke before the `v0.2.0` tag. They are temporary release working cards and must be synchronized into `docs/RELEASE_0_2.md` by R02-21 before release.

## R02-22 — Consistent numeric formatting and position quantity semantics

**Priority:** P2  
**Status:** READY  
**Suggested owner:** Lera / Luna-class frontend implementation; backend validation review if quantity invariant changes

### Problem

Numeric grouping is inconsistent between input/display surfaces. Position quantities render persistence precision such as `64.000000` even for whole-unit instruments.

### Scope

- use consistent Russian digit grouping for user-facing monetary/large-number displays;
- define safe input formatting behavior without converting exact decimal strings through binary float;
- position quantity display must trim meaningless trailing zeroes and group the integer part;
- stock quantity must be a positive whole number (`>= 1`) in both UI and backend/API validation;
- preserve fractional quantities for instrument types where they are legitimate (for example currency/gold/funds/other unless a stricter contract already exists);
- add regression tests for large exact values and whole/fractional quantities.

### Non-goals

- no persistence precision migration;
- no financial arithmetic in React.

## R02-23 — Optional instrument starts empty for actual investment flows

**Priority:** P2  
**Status:** READY  
**Suggested owner:** Lera

### Problem

In “Новая фактическая выплата”, `Инструмент (необязательно)` is currently preselected to the first active instrument even though the field is optional. This makes accidental attribution easy.

### Acceptance

- new actual-flow draft starts with instrument = empty/`—`;
- after creating an actual flow, the optional instrument resets to empty;
- expected-flow instrument remains required and may keep its existing behavior;
- focused frontend regression.

## R02-24 — Show salary tax bracket/rate in the month editor

**Priority:** P2  
**Status:** SPECIFIED  
**Suggested route:** Sol primary / bounded implementation / Terra review

### Problem

The salary editor shows calculated tax/net but not which progressive НДФЛ rate(s) were applied to the current salary payment.

### Contract direction

- backend remains source of truth; frontend must not infer the bracket from gross/tax;
- reuse `SalaryTaxResult.parts` / bracket rates;
- expose a compact API summary such as applied rate(s) and current marginal rate;
- if one payment crosses a threshold, UI must show that multiple rates were applied rather than lying with one percentage;
- distinguish marginal bracket from effective tax percentage if both are shown.

### Acceptance

- normal payment shows the current applied/marginal rate in Russian UI;
- threshold-crossing payment clearly shows both applied rates;
- no binary-float tax calculation in frontend.

## R02-25 — Passive-income goal current value / dividend forecast smoke blocker

**Priority:** P1  
**Status:** BLOCKED on read-only local-data reproduction  
**Suggested route:** Lera contract/review + Hermes local read-only diagnostic, then implementation owner chosen from root cause

### Observation

Owner added actual July dividends and closed historical months, but Dashboard “Основная цель” still displayed `Текущее значение = 0 ₽ / 0%` while warning that the dividend component was estimated from closed months.

### Existing contract

- actual dividend stays entirely in the month when it was received;
- forecast passive income annualises the average actual net dividends from closed months;
- the passive-income goal current value consumes `forecast_passive_income.monthly_total`.

Therefore, if a closed month contains a correctly classified actual dividend, a zero goal current value requires investigation; it must not be papered over in the frontend.

### Diagnostic acceptance

Read-only local diagnostic must report for the selected Dashboard month:

1. the actual `investment_cash_flows` dividend row(s) and net amount;
2. `passive_income_for_month(...).breakdown.dividends` for each relevant closed month;
3. closed months included by the forecast;
4. dividend average/months used;
5. forecast annual/monthly total and breakdown;
6. `/api/goals/summary` current value for the main goal;
7. exact first layer where a non-zero dividend becomes zero.

No DB writes or data repair during diagnosis.

## R02-26 — Expected payments calendar population/source UX

**Priority:** P2  
**Status:** SPECIFIED; not a correctness blocker for 0.2 if manual workflow is explicitly documented  
**Suggested route:** Sol contract / later implementation

### Current behavior

The 12-month calendar is built from persisted `expected_cash_flows`. In 0.2 these rows are entered manually in “Новая ожидаемая выплата”; the application does not currently generate coupon/dividend/redemption schedules automatically from portfolio positions.

### Follow-up direction

- make the manual source/workflow explicit in UI/docs for 0.2;
- separately decide whether future automatic population comes from instrument metadata, MOEX schedules, statement/import data, or another bounded source;
- define refresh/version semantics before any automatic overwrite of user-entered forecasts;
- never mix generated and manual rows ambiguously.

## Release handling

- R02-23 is a safe pre-release UX hotfix candidate.
- R02-22 and R02-24 are bounded pre-release polish tasks if time permits.
- R02-25 is a release blocker until the observed `0 ₽` is explained as either correct input state or fixed defect.
- R02-26 may remain a documented manual workflow for 0.2 and move to the next release if owner accepts it.
- R02-21 must synchronize these outcomes, the main release backlog, version metadata, README/Wiki/CHANGELOG, and the final smoke log before `v0.2.0`.
