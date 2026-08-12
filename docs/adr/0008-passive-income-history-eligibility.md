# ADR 0008 — Passive-income history eligibility boundary

- **Status:** Accepted
- **Date:** 2026-08-12
- **Task:** R03-16

## Context

The accepted C03 contract in `MASTER_SPEC §10.5` calculates actual average net passive income from CLOSED reporting months: before 12 months are available it divides by the number of available CLOSED months, and afterwards it uses a rolling window of the latest 12 reporting months.

That contract correctly treats a real CLOSED month with zero passive income as a real zero. However, an existing installation may also contain early CLOSED reporting months created only to preserve salary/tax history before investment/passive-income tracking became complete. Those technical-history months can contain zero passive income even though zero does not mean "a fully tracked month with no passive receipts". Including them depresses the owner-facing average and the dividend-history component of the forecast.

Automatically dropping every zero month is invalid: a genuinely tracked month with no passive receipts must remain in the average. Per-month arbitrary exclusion checkboxes would solve the immediate symptom but create manual bookkeeping, weak provenance and inconsistent consumers.

R03-16 therefore introduces one explicit lower-bound setting for historical passive-income eligibility. This ADR changes only the historical eligibility contract. It does not change what counts as passive income inside an individual reporting month.

## Decision

### 1. One canonical global lower boundary

Introduce one logical application setting:

```text
passive_income_history_start_month: YYYY-MM | null
```

User-facing label:

```text
Учитывать пассивный доход начиная с
```

The value is a calendar reporting-month key, not a snapshot date and not a foreign key to a particular row. It is therefore valid even if that calendar month does not currently have a `reporting_month` record.

`null` means **no lower boundary**: all otherwise eligible historical months are considered. This is the backward-compatible legacy behavior.

The boundary is inclusive:

```text
(year, month) >= passive_income_history_start_month
```

### 2. Eligibility is independent of amount

A reporting month is eligible for historical passive-income calculations iff:

1. it satisfies the existing consumer's reporting-month scope;
2. its status is `closed`;
3. the boundary is `null`, or its `(year, month)` is on/after the configured boundary.

The amount does not affect eligibility.

Therefore:

- an eligible CLOSED month with `0 ₽` passive income **is included**;
- an eligible CLOSED month with negative net passive income **is included**;
- a pre-boundary CLOSED month is excluded even when it has non-zero passive income;
- DRAFT/open months are excluded;
- a reopened month immediately becomes ineligible until it is closed again;
- closing it again restores eligibility if it is on/after the boundary.

There is no per-month exclusion flag in 0.3.

### 3. Missing calendar months are not zeroes

The boundary does not create synthetic months.

If a calendar month has no CLOSED `reporting_month`, it contributes neither a zero nor a denominator slot. Gaps remain gaps.

The rolling window is the latest **12 eligible CLOSED reporting-month records**, ordered by `(year, month)`, not 12 calendar slots and not a calendar-year average.

Before 12 eligible CLOSED months exist:

```text
actual_passive_income_avg =
    sum(actual_net_passive_income for eligible available months)
    / count(eligible available months)
```

After 12 eligible CLOSED months exist, only the latest 12 eligible CLOSED months participate.

Money remains integer minor units / `Decimal` with `ROUND_HALF_UP`; binary `float` remains forbidden.

### 4. Backward compatibility and migration

R03-17 must add the persisted setting without silently changing existing results.

Normative migration/default behavior:

- existing databases migrate with `passive_income_history_start_month = null`;
- new databases also default to `null`;
- `null` preserves the pre-R03-17 calculation exactly;
- no migration infers a start month from existing data, first non-zero passive income, first position, salary history, file timestamps or private owner values;
- changing the boundary is an explicit owner action and may intentionally change historical averages/forecast components;
- clearing the setting returns to all-history eligibility.

Because the default leaves outputs unchanged, the migration itself does not reinterpret any existing CLOSED month.

### 5. One eligibility source for all derived historical passive-income consumers

The lower-bound selector must be implemented once in backend/application logic and reused. Frontend code must not reimplement the filter.

It applies to:

#### C03 actual passive-income rolling average

The canonical average uses only eligible CLOSED months before the existing last-12 calculation.

#### Passive-income Goal current value/progress

Per R02-27, passive-income Goal `current_value` and `progress_pct` use the C03 rolling average of actual net passive income. They therefore inherit the exact same eligibility boundary automatically. No separate Goal setting/filter is allowed.

R03-16 does not change capital-goal semantics or the goal-achievement trajectory contract.

#### C04 actual-dividend history component

The forecast's dividend component is based on actual net dividends from CLOSED months and reuses the same rolling-average semantics. The same eligibility boundary must be applied to those actual dividend months before the last-12 calculation.

This boundary does **not** filter forward-looking `expected_cash_flows` for coupons, deposit interest or other expected capital income. Their existing forecast-window contract remains unchanged.

#### Owner-facing passive-income history presentation

Any UI that presents a historical passive-income series specifically as the basis for the rolling average should use the backend-provided eligible history or clearly mark pre-boundary months as excluded. It must not visually imply that a pre-boundary month contributes to `N из 12`.

Per-month actual passive-income calculation remains available for older months; the boundary does not delete or rewrite historical rows.

Capital-history/analytics eligibility is unrelated and remains unchanged.

### 6. Existing consumer upper-bound/as-of semantics are not redefined here

R03-16 defines only the new **lower eligibility boundary**. If a consumer already has an accepted upper/as-of scope, it keeps that scope and applies the lower boundary inside it.

R03-17 must not use this task as permission to redesign historical as-of semantics of Dashboard/Goals/exports beyond what their existing contracts require.

### 7. UI and read-contract metadata

R03-17 must expose enough backend-derived metadata for UI/help text without recalculating financial logic in React.

At minimum the relevant read result(s) must make available:

```text
count_months
is_complete_12m
configured_start_month: YYYY-MM | null
months_used: ordered reporting-month keys, or equivalent backend-derived window metadata
```

The UI may summarize this as, for example:

```text
Среднее за 5 закрытых месяцев из 12 · учёт с мая 2026
```

or, with no boundary:

```text
Среднее за 5 закрытых месяцев из 12 · вся доступная история
```

When zero eligible CLOSED months exist, the UI must state that there are no closed months in the selected accounting period; it must not describe that state as a measured `0 ₽` month.

The setting belongs to Settings/financial-method preferences (or an equivalent single canonical settings surface). The same setting must not be duplicated independently on Dashboard and Goals.

### 8. Boundary changes do not mutate reporting data

Updating or clearing `passive_income_history_start_month`:

- does not open/close/reopen reporting months;
- does not alter `investment_cash_flows`, deposit snapshots or income rows;
- does not rewrite previously stored monthly passive-income inputs;
- only changes which already-readable historical CLOSED months are eligible for derived historical metrics.

## Normative examples

### Example A — technical salary history before real passive tracking

CLOSED months and actual passive income:

```text
Jan  0
Feb  0
Mar  0
Apr  0
May  10 000
Jun  0
Jul  20 000
```

Configured boundary:

```text
2026-05
```

Eligible months are May, Jun, Jul. June is a genuine eligible zero.

```text
average = (10 000 + 0 + 20 000) / 3 = 10 000
count_months = 3
```

Jan-Apr do not participate.

### Example B — more than 12 eligible months

There are 14 eligible CLOSED months on/after the boundary.

Only the chronologically latest 12 eligible CLOSED records participate. The first two eligible records fall out of the rolling window.

### Example C — gap, draft and reopen

Boundary is `2026-05`.

```text
May  CLOSED  10 000
Jun  missing
Jul  DRAFT   15 000
Aug  CLOSED  20 000
```

Window initially contains May and Aug only:

```text
count_months = 2
average = 15 000
```

If Jul is CLOSED, it joins the eligible window. If May is then reopened, May immediately disappears until reclosed. June never becomes an implicit zero.

### Example D — boundary after all closed history

If the boundary is later than every CLOSED reporting month:

```text
count_months = 0
is_complete_12m = false
```

The UI reports no eligible closed history. No month is fabricated and no stored data is changed.

### Example E — dividend forecast component

Pre-boundary months contain no reliable dividend tracking. On/after the boundary, eligible CLOSED months have actual net dividends:

```text
May  3 000
Jun  0
Jul  9 000
```

The C04 dividend average uses these three eligible months, including June's genuine zero, and annualises that average according to the existing forecast contract. Pre-boundary technical-history months do not depress the dividend component.

## Rejected alternatives

### Exclude every zero passive-income month

Rejected because a genuine tracked zero month is financially meaningful and must remain in the denominator.

### Per-month `exclude_from_average` checkbox

Rejected for 0.3 because it creates recurring manual bookkeeping, weakens provenance and makes cross-consumer consistency harder. A future need would require a separate contract.

### Calendar-year average

Rejected. The product metric remains rolling history, not YTD/calendar-year passive income.

### Automatically infer the first reliable month

Rejected. The application cannot safely infer historical completeness from non-zero income, positions, salary presence or timestamps without risking silent reinterpretation.

## Implementation requirements for R03-17

R03-17 may choose the physical persistence shape (for example normalized year/month fields or an equivalent validated representation) but must preserve the single logical `YYYY-MM | null` setting and all semantics above.

Required tests include:

1. migration of an existing database preserves `null` and pre-change result;
2. pre-boundary CLOSED month excluded;
3. boundary month included (inclusive comparison);
4. eligible CLOSED zero included;
5. eligible negative month included;
6. missing month not converted to zero;
7. DRAFT/reopened excluded and reclosed month returns;
8. fewer than 12 divides by actual eligible count;
9. more than 12 keeps latest 12 eligible CLOSED records;
10. clearing boundary restores all-history behavior;
11. passive-income Goal current/progress uses the same filtered C03 result;
12. dividend component uses the same filtered eligible CLOSED history;
13. expected coupon/interest/other forecast flows are unaffected by the boundary;
14. backend provides count/window metadata; frontend does no independent financial filtering;
15. only synthetic fixtures are used.

## Consequences

The owner can distinguish incomplete historical bookkeeping from a genuine zero-income month with one stable setting instead of maintaining exclusions month by month. Existing installations remain unchanged until the owner explicitly chooses a start period. Once chosen, C03 actual average, passive-income Goal current/progress and C04 dividend-history component share one backend eligibility source.