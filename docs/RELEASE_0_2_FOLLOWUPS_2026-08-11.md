# Release 0.2 — owner smoke follow-ups — 2026-08-11

These bounded follow-ups were discovered during the owner-led manual backfill/UI smoke before the `v0.2.0` tag. R02-21 synchronizes their final state into the canonical release record.

## R02-22 — Consistent numeric formatting and position quantity semantics

**Priority:** P2  
**Status:** DONE

### Outcome

- user-facing position quantity no longer exposes persistence padding such as `64.000000`;
- whole quantities are shown without meaningless trailing zeroes and with readable grouping;
- `stock` quantity is enforced as a positive whole number (`>= 1`) on frontend and backend/API boundary;
- fractional quantities remain allowed for instrument types where the existing contract permits them;
- no persistence precision migration and no financial arithmetic moved into React.

**Delivery:** commits `a93f2265d22c0c24b88a332d7dfa718c9391de7a`, `fe455bce85d38fde27d03e1c2c19cd07aaca8d85`, `cdb439f68a6dade7a4801fbbcbcd5e97a70e5e6e`.  
**Verification:** exact main push CI `31527275884` green.

## R02-23 — Optional instrument starts empty for actual investment flows

**Priority:** P2  
**Status:** DONE

### Outcome

- new actual-flow draft starts with optional instrument = `—`;
- after creating an actual flow the optional instrument resets to empty;
- account convenience default remains;
- expected-flow instrument remains required and unchanged.

**Delivery:** PR #18, merge `6cfa1355f52102d1d734a8496a793753cbb66d65`.  
**Verification:** exact PR CI `31526151737` green across backend/frontend/privacy/Windows production smoke.

## R02-24 — Show salary tax bracket/rate in the month editor

**Priority:** P2  
**Status:** DONE

### Outcome

The existing month-summary API already exposed backend `salary_tax.parts` with `rate_bps`, so no tax formula/API semantic change was required.

- normal salary shows the backend-derived current applied/marginal rate;
- a payment crossing a threshold shows all applied rates and the marginal rate after the payment;
- incomplete salary-tax history shows no invented rate;
- frontend does not infer a rate from gross/tax or perform tax arithmetic.

**Delivery:** PR #19, merge `264408b4d7a600745ba26b2cc4085c968d19e96b`.  
**Verification:** exact PR CI `31526654331` green across backend/frontend/privacy/Windows production smoke.

## R02-25 — Passive-income goal current value / dividend forecast diagnostic

**Priority:** P1  
**Status:** DONE — no code defect reproduced

### Observation and resolution

The owner initially expected July dividend data to feed the rolling dividend component, while Dashboard showed `0` for the forecast/main-goal current value.

Two independent read-only diagnostics (Codex and Hermes) followed the full chain and found:

- zero `investment_cash_flows` rows with `flow_type=dividend`;
- the relevant owner-entered flows were classified as `coupon`;
- therefore every closed-month dividend bucket was legitimately zero;
- dividend average, expected dividend component and forecast/goal dividend contribution remained zero without any layer dropping a non-zero dividend.

The owner confirmed the input classification mistake. **No code fix is required.** The contract remains: actual dividends stay in the month received; forecast dividend component uses the average actual net dividends from available closed months, up to rolling 12.

## R02-26 — Expected payments calendar population/source UX

**Priority:** P2  
**Status:** DEFERRED — non-blocking follow-up after 0.2

### 0.2 contract

The 12-month calendar is built from persisted `expected_cash_flows`. In 0.2 rows are entered manually through “Новая ожидаемая выплата”. The application does not generate coupon/dividend/redemption schedules automatically from current portfolio positions or MOEX.

README/CHANGELOG/Wiki explicitly document this manual workflow for 0.2.

### Future contract required before implementation

- choose authoritative source(s): instrument metadata/MOEX/import/other;
- define provenance and manual-vs-generated row identity;
- define refresh/version/reconciliation semantics;
- never silently overwrite or ambiguously duplicate manual rows.

## Release handling

- R02-22, R02-23 and R02-24 are DONE;
- R02-25 is DONE as a diagnostic resolution with no code change;
- R02-26 is explicitly DEFERRED and non-blocking for 0.2;
- R02-21 owns final version/docs/backlog synchronization and release-candidate review preparation.
