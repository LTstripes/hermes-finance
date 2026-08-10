# ADR 0005 — Goal achievement forecast v1

- **Status:** Accepted
- **Date:** 2026-08-10
- **Task:** R02-12

## Context

R02-11 made `goals` the canonical runtime source of truth and introduced explicit persisted main-goal selection. R02-12 must now define what a user-facing "forecast date of goal achievement" means before backend code is allowed to produce one.

The current application has trustworthy point-in-time and 12-month derived metrics, but it does **not** have a canonical future growth trajectory for capital or passive income. In particular, there is no persisted contract for regular future contributions, expected capital growth/return, reinvestment assumptions, future portfolio changes, future growth of passive income beyond the existing 12-month passive-income forecast, or a linear/exponential trend model.

Inventing those inputs inside R02-12 would turn an implementation detail into financial semantics without an owner-approved contract.

The existing canonical metrics relevant here are:

- `forecast_passive_income(...).monthly_total` for monthly net passive-income goal progress;
- `liquid_capital_for_month(...).liquid_capital_net` for liquid-capital state;
- `ReportingMonth.snapshot_date` as the as-of date for a reporting snapshot;
- `goals.target_date` as a user-entered desired deadline, **not** a forecast input.

## Decision

### 1. Forecast method is explicitly versioned

R02-12 introduces a separate goal-achievement method version:

```text
goal_achievement_v1
```

This is independent from the dashboard/monthly-summary `calculation_version` and from the expected-cash-flow `forecast_version`.

R02-12 does **not** change an existing financial formula, so it must not bump the global monthly-summary `calculation_version` merely for adding this new derived result.

### 2. v1 does not invent a future growth trajectory

`goal_achievement_v1` is deliberately conservative.

For a goal whose current canonical metric can be resolved:

- if `current_value >= target_value`, the goal is considered **achieved as of the selected reporting snapshot**;
- the returned `estimated_achievement_date` is the selected `ReportingMonth.snapshot_date`;
- this means "the goal is met at this snapshot, therefore no later than this date" and does **not** claim to identify the historical first-crossing date;
- if `current_value < target_value`, v1 returns no future date because the application has no canonical trajectory model.

The below-target result must therefore be:

```text
estimated_achievement_date = null
reason_code = "no_trajectory_model"
```

The backend must not extrapolate from recent history, assume regular contributions, assume a return rate, or use `target_date` as if it were a prediction.

### 3. Goal-type / calculation-mode support matrix

The forecast is determined by the pair `(goal_type, calculation_mode)`, not by a free-form interpretation of the goal name.

| Goal type | Calculation mode | Current metric | v1 achievement-date behavior |
|---|---|---|---|
| `passive_income` | `monthly_net_passive_income` | canonical `forecast_passive_income(...).monthly_total` | supported current-state check; future date is `null` when below target |
| `capital` | `liquid_capital_net` | canonical `liquid_capital_for_month(...).liquid_capital_net` | supported current-state check; future date is `null` when below target |
| `expense_coverage` | any | — | unsupported in v1 |
| `mortgage_coverage` | any | — | unsupported in v1 |
| `other` | any | — | unsupported in v1 |
| `passive_income` / `capital` | any other mode | — | unsupported calculation mode |

Coverage goal types are unsupported because the current `goals.target_value_kopecks` storage/API is a money value, while coverage is naturally percentage/ratio semantics. R02-12 must not silently reinterpret money as a percentage. A future typed-target contract may enable those goal types.

### 4. Canonical passive-income metric

For `passive_income + monthly_net_passive_income`, R02-12 must reuse:

```text
forecast_passive_income(session, reporting_month_id, forecast_version).monthly_total
```

This is the same forward-looking monthly value already used by `coverage_and_goals()` for the main passive-income goal progress.

R02-12 must **not** switch goal progress/date logic to trailing actual average, a single month's actual passive income, expected-calendar monthly spikes, or a new independently calculated passive-income value.

The result carries through the canonical passive-income forecast's `is_approximate` and warnings so the UI can distinguish an estimate with limited inputs from a clean estimate.

### 5. Canonical capital metric

For `capital + liquid_capital_net`, current value is:

```text
liquid_capital_for_month(session, reporting_month_id).liquid_capital_net
```

No trend is inferred from historical capital points in v1.

### 6. Exact progress and remaining amount

For supported modes, backend returns:

```text
remaining_amount = max(target_value - current_value, 0)
```

and:

```text
progress_pct = current_value / target_value * 100
```

`progress_pct` uses `Decimal`, is quantized to `0.01`, and uses the existing financial `ROUND_HALF_UP` convention.

If `target_value == 0`, `progress_pct = null` to preserve the existing safe-zero-denominator behavior. A nonnegative current metric still means the zero target is achieved.

Money arithmetic uses integer kopecks / `RubleAmount`; binary `float` is forbidden.

### 7. Inactive goals

An inactive goal is not actively tracked and therefore has no achievement forecast.

For inactive goals:

```text
status = "inactive"
estimated_achievement_date = null
reason_code = "goal_inactive"
current_value = null
remaining_amount = null
progress_pct = null
```

No financial calculator needs to run solely for an inactive goal.

### 8. Unsupported goals and modes

For unsupported goal types:

```text
status = "unsupported"
reason_code = "unsupported_goal_type"
```

For a supported goal type with a noncanonical `calculation_mode`:

```text
status = "unsupported"
reason_code = "unsupported_calculation_mode"
```

In both cases:

- `estimated_achievement_date = null`;
- `current_value = null`;
- `remaining_amount = null`;
- `progress_pct = null`;
- the API includes a short user-displayable warning.

R02-12 must not change the R02-11 write contract to reject existing free-form calculation modes. Unsupported modes remain readable and are reported honestly.

### 9. `target_date` is a deadline, not a model input

`Goal.target_date` remains the user's desired/declared target date.

R02-12 does not use `target_date` to manufacture `estimated_achievement_date`, assume the goal will be achieved by the requested deadline, or derive a required monthly return/contribution from it.

The UI may later compare the declared target date with a non-null forecast, but that comparison is outside the v1 forecast formula.

### 10. Normative result contract

The pure domain/service result must expose enough information that React performs no financial calculation:

```text
GoalAchievementForecastResult
- goal_id: int
- reporting_month_id: int
- as_of_date: date
- method_version: "goal_achievement_v1"
- source_forecast_version: string | null
- status: "achieved" | "not_projectable" | "inactive" | "unsupported"
- reason_code: string | null
- current_value: RubleAmount | null
- target_value: RubleAmount
- remaining_amount: RubleAmount | null
- progress_pct: Decimal | null
- estimated_achievement_date: date | null
- is_approximate: bool
- warnings: tuple[str, ...]
```

For supported active goals:

- `status="achieved"` when `current_value >= target_value`;
- `status="not_projectable"` when `current_value < target_value`;
- `reason_code=null` when achieved;
- `reason_code="no_trajectory_model"` when below target.

`source_forecast_version` is populated only for the passive-income mode; capital has `null` because it does not consume the expected-cash-flow forecast.

### 11. API contract

Keep the R02-11 CRUD DTOs and write endpoints unchanged.

Add a read-only bulk summary endpoint for R02-13:

```text
GET /api/goals/summary
    ?reporting_month_id=<required int>
    &include_inactive=<bool, default false>
    &forecast_version=<string, default current canonical forecast version>
```

The response is a list of goal records plus a nested backend-derived `achievement_forecast` object matching the normative result contract. Money uses the existing `MoneyValue` decimal-string shape; percentages are decimal strings; dates are ISO dates.

Because the existing router already has `GET /api/goals/{goal_id}`, the static `/summary` route must be registered before the dynamic `/{goal_id}` route (or otherwise be structured so `summary` cannot be shadowed and parsed as a goal id).

The endpoint must compute shared source metrics once per request where practical (for example one passive-income forecast and one liquid-capital result), not once per goal via an N+1 calculator loop.

Existing `GET /api/goals`, `GET /api/goals/{id}`, `POST`, `PATCH`, and `DELETE` remain source-of-truth CRUD endpoints and do not require a reporting month.

### 12. Historical/read-time behavior

The forecast is derived read-time output for the explicitly selected `reporting_month_id` and uses that month's `snapshot_date` as `as_of_date`.

R02-12 inherits existing canonical source-service behavior. It must not rewrite closed months or persist an achievement date.

No new DB column or migration is required.

### 13. Warnings and failure behavior

The API must distinguish:

- a supported goal that is below target but lacks a trajectory (`no_trajectory_model`);
- an unsupported goal type/mode;
- an inactive goal;
- a supported passive-income result that is approximate or carries upstream forecast warnings.

A missing reporting month or missing goal follows existing API not-found/error conventions; it is not represented as a successful forecast with `null` fields.

## Required regression tests for R02-12

At minimum:

1. passive-income canonical mode, current forecast below target → exact current/progress/gap, `date=null`, `no_trajectory_model`;
2. passive-income canonical mode at/above target → `status=achieved`, date equals `snapshot_date`;
3. passive-income result carries upstream approximation/warnings and requested `forecast_version`;
4. capital `liquid_capital_net` below target → `date=null`, no historical trend extrapolation;
5. capital at/above target → achieved at snapshot date;
6. zero target → achieved, `progress_pct=null`, no divide-by-zero;
7. inactive goal → no calculators/current value/date and `goal_inactive`;
8. `expense_coverage`, `mortgage_coverage`, `other` → `unsupported_goal_type`;
9. passive/capital with unknown `calculation_mode` → `unsupported_calculation_mode`;
10. percent rounding is `Decimal` to `0.01` with `ROUND_HALF_UP`;
11. remaining amount never becomes negative;
12. bulk summary endpoint returns backend-derived values as decimal strings and respects `include_inactive`;
13. multiple passive-income goals reuse the same canonical passive forecast semantics rather than independently recalculating a different metric;
14. existing R02-11 CRUD/main-selection behavior remains unchanged;
15. no migration is introduced.

## Consequences

v1 intentionally prefers an honest missing future date over a precise-looking but invented extrapolation. It still gives R02-13 everything required to render useful goal state: current value, target, progress, remaining amount, quality warnings, and a machine-readable explanation for "нет прогноза".

A future `goal_achievement_v2` may add a real future trajectory only after the owner explicitly defines its inputs, for example regular contributions, expected return/reinvestment assumptions, or another deterministic projection source.