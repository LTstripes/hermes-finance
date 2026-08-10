# ADR 0003 — Income cash-flow inclusion

- **Status:** Accepted
- **Date:** 2026-08-10
- **Task:** R02-18

## Context

`income_entries` already stores two independent booleans:

- `include_in_cash_flow`;
- `include_in_passive_income`.

The persistence/API default for `include_in_cash_flow` is `true`, but the current monthly cash-balance assembler ignores that flag and sums `salary`, `bonus`, `side_income` and `cashback` by type. At the same time, `IncomeType.OTHER` with `include_in_passive_income=false` is absent from the current cash-balance formula entirely.

R02-04 established a separate invariant: only `IncomeType.OTHER` may have `include_in_passive_income=true`. This ADR does not change that passive-income contract.

## Decision

### 1. Meaning of `include_in_cash_flow`

`include_in_cash_flow` is the normative inclusion switch for whether **that `IncomeEntry.net_amount` contributes to `monthly_cash_balance`**.

- `true` — the entry contributes to monthly cash balance according to the matrix below;
- `false` — the entry does not contribute to monthly cash balance.

The flag affects only the monthly cash-balance calculation. It does **not** remove the row from storage and does not change unrelated analytics such as salary-tax history, normalized bonus, or actual passive-income classification.

### 2. `OTHER` non-passive income gets an explicit cash-balance bucket

`IncomeType.OTHER` with:

- `include_in_passive_income=false`;
- `include_in_cash_flow=true`

is ordinary non-passive cash income and contributes to a new explicit `other_income` cash-balance bucket.

It must not be relabeled as `side_income` and must not be placed in the passive-income bucket.

The cash-balance domain/API breakdown therefore gains `other_income` as a `MoneyValue`/`RubleAmount` field.

### 3. `OTHER` passive income is counted exactly once

For `IncomeType.OTHER` with `include_in_passive_income=true`, the entry remains part of the actual passive-income metric defined by R02-04.

For monthly cash balance:

- if `include_in_cash_flow=true`, its amount contributes **only through the cash-balance `passive_income` subtotal**;
- if `include_in_cash_flow=false`, it remains visible in actual passive-income analytics but is excluded from monthly cash balance.

It must never also be added to `other_income`.

Consequently, `CashBalanceBreakdown.passive_income` means the passive-income amount that is eligible for monthly cash flow. It may be lower than the dashboard's full `passive_income_actual` when an `OTHER` passive income row explicitly has `include_in_cash_flow=false`.

Passive sources that are not `IncomeEntry` rows (for example deposit snapshots and valid investment cash flows) have no `include_in_cash_flow` flag and keep their existing cash-balance behavior.

### 4. Type/flag matrix

| Income type | `include_in_cash_flow` | `include_in_passive_income` | Passive-income metric | Monthly cash balance |
|---|---:|---:|---|---|
| `salary` | `true` | `false` | no | `salary_net` |
| `salary` | `false` | `false` | no | excluded |
| `bonus` | `true` | `false` | no | `bonus_net` |
| `bonus` | `false` | `false` | no | excluded |
| `side_income` | `true` | `false` | no | `side_income_net` |
| `side_income` | `false` | `false` | no | excluded |
| `cashback` | `true` | `false` | no | `cashback` |
| `cashback` | `false` | `false` | no | excluded |
| `other` | `true` | `false` | no | `other_income` |
| `other` | `false` | `false` | no | excluded |
| `other` | `true` | `true` | yes, `other_capital_income` | `passive_income`, exactly once |
| `other` | `false` | `true` | yes, `other_capital_income` | excluded |

For `salary`, `bonus`, `side_income` and `cashback`, `include_in_passive_income=true` remains invalid under R02-04 and is not a valid matrix state.

### 5. Normative monthly cash-balance formula

After R02-19:

```text
monthly_cash_balance =
    included_salary_net
  + included_bonus_net
  + included_side_income_net
  + included_cashback
  + included_other_income_net
  + included_passive_income
  - mandatory_expenses
  - other_recorded_expenses
  - saving_allocations
```

Where `included_*` for `IncomeEntry` sources means `include_in_cash_flow=true`, and `included_passive_income` excludes only passive `IncomeEntry.OTHER` rows whose `include_in_cash_flow=false` while preserving all other canonical passive-income sources.

### 6. Write contract

No new write-time incompatibility is introduced between the two flags beyond R02-04.

In particular, `OTHER + include_in_passive_income=true + include_in_cash_flow=false` is valid: the row is passive income for analytics but intentionally excluded from monthly cash balance.

Existing create defaults remain unchanged:

- `include_in_cash_flow=true`;
- `include_in_passive_income=false`.

### 7. Backward compatibility and closed months

R02-19 must not add a migration that rewrites existing income rows or guesses new flag values.

Existing persisted booleans are taken at face value:

- rows with `include_in_cash_flow=true` keep participating according to their type;
- rows with `include_in_cash_flow=false` begin to be correctly excluded from cash balance;
- existing `OTHER + passive=false + cash_flow=true` rows begin to contribute through `other_income`.

The current month editor writes `include_in_cash_flow=true` for its salary/bonus/side-income/cashback rows, so ordinary rows created through the existing UI are expected to keep the same cash-balance inclusion behavior.

Closed-month rows remain immutable. Because cash balance is a derived read-time calculation rather than a persisted monthly total, historical cash-balance output may change for closed months that already contain one of the affected flag combinations. This is an intentional formula correction, not a data rewrite.

To make that change observable, R02-19 must advance the externally reported monthly-summary/dashboard `calculation_version` from `v1` to `v2` (or the next canonical version if it has already advanced before implementation).

### 8. Implementation constraints for R02-19

R02-19 should:

- filter `salary`/`bonus`/`side_income`/`cashback` cash-balance sums by `include_in_cash_flow=true`;
- add the `other_income` field to cash-balance input, breakdown and API DTO;
- sum `OTHER + passive=false + cash_flow=true` into `other_income`;
- include `OTHER + passive=true + cash_flow=true` through `passive_income` only;
- exclude `OTHER + passive=true + cash_flow=false` from the cash-balance passive subtotal without removing it from actual passive-income metrics;
- preserve the R02-04 source-of-truth and deposit-interest invariants;
- update `MASTER_SPEC.md` §10.9 and relevant cash-balance contract/docstrings to the accepted formula before R02-19 is marked DONE;
- advance the public monthly-summary/dashboard calculation version;
- use integer kopecks/`RubleAmount` only; no binary float;
- avoid DB migration unless an implementation-only schema need is independently proven (none is required by this contract).

Exposing `include_in_cash_flow` as a new user-facing control in the month editor is **not required by R02-19**. That is a separate UI choice; R02-19 is responsible for making the already persisted/API-visible flag semantically correct.

## Required regression tests for R02-19

At minimum:

1. type/flag matrix for all five income types;
2. each active income type with `include_in_cash_flow=false` contributes zero to cash balance;
3. `OTHER + passive=false + cash_flow=true` contributes to `other_income` exactly once;
4. `OTHER + passive=true + cash_flow=true` contributes to `passive_income` exactly once and not `other_income`;
5. `OTHER + passive=true + cash_flow=false` remains in `passive_income_for_month()` but is absent from monthly cash balance;
6. deposit snapshot and valid investment passive flows remain included as before;
7. cash-balance breakdown sum equals total;
8. closed-month read uses the new semantics without mutating stored rows;
9. reported calculation version advances.

## Consequences

This makes the existing `include_in_cash_flow` field meaningful, gives non-passive `OTHER` income a truthful place in the breakdown, and keeps cash-flow inclusion independent from passive-income classification. The cost is a small public DTO expansion (`other_income`) and an explicit calculation-version change.