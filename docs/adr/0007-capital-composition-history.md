# ADR 0007 — Capital composition history v1

- **Status:** Accepted
- **Date:** 2026-08-12
- **Task:** R03-11

## Context

Hermes Finance 0.3 adds an Analytics screen that must show how the composition of liquid assets changes over time, not only the existing `liquid_capital_net` line.

The current dashboard already has two accepted sources that must remain canonical:

- `liquid_capital_for_month(...).liquid_capital_net` for net liquid capital;
- dashboard `asset_allocation` for the selected month, with classes `cash`, `deposits`, `stocks`, `bonds`, `gold_other`.

The current allocation groups positions by `instrument_type`: `stock` and `bond` are separate classes; all other instrument types plus `other_liquid_assets` are grouped into `gold_other`. The same `Account.include_in_capital` and snapshot valuation semantics used by current liquid-capital/allocation services apply.

R03-11 defines a read-only historical contract only. It must not alter the liquid-capital formula, accepted valuation semantics, account flags, debt semantics, or financial storage.

## Decision

### 1. History contains CLOSED reporting months only

Capital-composition history contains only `ReportingMonth.status == closed` months.

Draft months are excluded even if they currently contain positions or balances. Reopening a previously closed month removes it from this historical result until it is closed again, matching the existing meaning of closed-month history elsewhere in the application.

Returned points are ordered strictly by `(year ASC, month ASC)`.

### 2. Missing calendar months are unknown, not zero

The API returns one point per existing CLOSED reporting month and does not create synthetic reporting months.

If May and July are CLOSED while June is absent or draft, the result contains May and July only. June is **unknown history**, not a month of zero assets.

The frontend may insert a presentation-only gap marker with `null` chart coordinates so the visual series breaks at June. It must not insert zero-valued financial data, interpolate between May and July, or backfill June from either neighboring month.

### 3. Asset-class taxonomy is exactly the existing allocation taxonomy

The historical contract reuses these five classes in this canonical order:

1. `cash`
2. `deposits`
3. `stocks`
4. `bonds`
5. `gold_other`

No second classifier is introduced.

For every returned CLOSED month all five classes are emitted exactly once. A class with no rows in that known month is an explicit known zero for that class.

`gold_other` keeps the existing meaning: all position instrument types other than `stock` and `bond`, plus `other_liquid_assets`. R03-11 does not split gold, funds, currency or other instruments into new historical classes.

### 4. Per-month values reuse the existing accepted valuation semantics

Each historical point is calculated from that reporting month's own persisted snapshot data using the same source of truth as current `asset_allocation` and `liquid_capital_for_month`:

- cash: included cash balances for that reporting month;
- deposits: included deposit snapshot balances for that reporting month;
- stocks: included position snapshot market value where instrument type is `stock`;
- bonds: included position snapshot market value where instrument type is `bond`;
- gold/other: included position snapshot market value for all other instrument types plus `other_liquid_assets`.

All money remains RUB `MoneyValue` with decimal-string major units at the API boundary and integer kopecks / `RubleAmount` inside backend calculation paths.

Historical aggregation must not use a later month's prices, balances, positions or allocation to fill an earlier month.

R03-11 does not introduce new snapshotting of global account flags or reinterpret existing historical behavior; it reuses the currently accepted services and their semantics.

### 5. Asset stack and net capital are deliberately separate values

For each month the response exposes:

```text
liquid_assets_total = cash + deposits + stocks + bonds + gold_other
liquid_capital_net = liquid_assets_total - included_debts
```

`liquid_assets_total` is the stacked-area total and the denominator for the `%` composition view.

`liquid_capital_net` is the accepted net-capital metric from `liquid_capital_for_month`; it is shown as a separate total/net line or value.

The stack is therefore **not required to equal** `liquid_capital_net`. The difference is `included_debts`. Real estate and mortgage remain outside this contract exactly as in `MASTER_SPEC §10.1`.

The response also exposes `included_debts` so the UI can reconcile the difference without inventing a subtraction client-side:

```text
liquid_assets_total - included_debts = liquid_capital_net
```

R03-11 does not change which debts are included in liquid capital.

### 6. Percentage view uses the asset stack, never net capital

The `%` view represents the composition of liquid **assets**, not net capital after debts.

For a class:

```text
share_pct = class_amount / liquid_assets_total * 100
```

The backend does not need to return precomputed percentages in v1. The frontend may derive display percentages from exact money strings/kopecks using the existing exact-money helper path; binary floating-point arithmetic must not be used for financial sums or the authoritative denominator.

If `liquid_assets_total == 0`, percentage values are unavailable (`null`/`—` in presentation) rather than divided by zero.

Chart libraries may receive converted numeric coordinates only after exact financial amounts/totals have already been established, following the existing Recharts boundary convention.

### 7. API shape

Use a separate analytics endpoint because this is a cross-month dataset and does not conceptually depend on a selected dashboard month:

```text
GET /api/analytics/capital-composition
```

Canonical response shape:

```json
{
  "asset_classes": ["cash", "deposits", "stocks", "bonds", "gold_other"],
  "points": [
    {
      "reporting_month_id": 42,
      "year": 2026,
      "month": 7,
      "snapshot_date": "2026-07-31",
      "allocation": [
        {"asset_class": "cash", "amount": {"amount": "100000.00", "currency": "RUB"}},
        {"asset_class": "deposits", "amount": {"amount": "400000.00", "currency": "RUB"}},
        {"asset_class": "stocks", "amount": {"amount": "300000.00", "currency": "RUB"}},
        {"asset_class": "bonds", "amount": {"amount": "700000.00", "currency": "RUB"}},
        {"asset_class": "gold_other", "amount": {"amount": "200000.00", "currency": "RUB"}}
      ],
      "liquid_assets_total": {"amount": "1700000.00", "currency": "RUB"},
      "included_debts": {"amount": "100000.00", "currency": "RUB"},
      "liquid_capital_net": {"amount": "1600000.00", "currency": "RUB"}
    }
  ]
}
```

No selected `month_id` parameter is required in v1. The dataset is the complete closed-month history available in the local database.

### 8. One source of truth for current and historical allocation

R03-12 must not duplicate the current `_asset_allocation` formula in a second router/service.

Implementation should extract or promote one reusable backend allocation function/service that accepts `(session, reporting_month_id, liquid_capital_result)` and returns the existing five-class allocation. Both:

- selected-month Dashboard `asset_allocation`; and
- `/api/analytics/capital-composition`

must call that same source.

The analytics router only maps the service DTO to API models; no financial aggregation belongs in the router.

### 9. Known zero vs unknown history

These cases are normative:

- CLOSED month exists, no stock positions in that month → `stocks = 0` and the point still contains the `stocks` class;
- CLOSED month exists and all asset classes are empty → the month exists with five zeros, `liquid_assets_total = 0`, and percentage view is unavailable;
- calendar month has no CLOSED `reporting_month` → no point exists for that month; frontend displays a gap, never five zeros;
- future month data must never be copied backward to fill any missing historical point.

## Synthetic examples

### Example A — all classes present

```text
cash         100 000 ₽
deposits     400 000 ₽
stocks       300 000 ₽
bonds        700 000 ₽
gold_other   200 000 ₽
----------------------
assets     1 700 000 ₽
debts        100 000 ₽
net        1 600 000 ₽
```

The stacked chart reaches `1 700 000 ₽`; the net-capital line/value is `1 600 000 ₽`.

### Example B — known zero class

```text
cash         120 000 ₽
deposits     450 000 ₽
stocks             0 ₽
bonds        800 000 ₽
gold_other   230 000 ₽
----------------------
assets     1 600 000 ₽
debts         50 000 ₽
net        1 550 000 ₽
```

`stocks` is returned explicitly as zero because the CLOSED month is known; the other four classes still sum to the stack total.

### Example C — calendar gap

May and July are CLOSED, June is draft or absent:

```text
points = [May, July]
```

The API does not synthesize June. A chart adapter may place a null June gap only to stop visual interpolation.

## Consequences

- R03-12 can implement the API without inventing aggregation semantics.
- Dashboard and Analytics share one five-class allocation source of truth.
- The stacked graph answers "what were my liquid assets made of?" while the net-capital value continues to answer "what remained after included debts?".
- `%` composition remains mathematically meaningful because debts are not used as the denominator of asset shares.
- No migration or stored historical backfill is required for v1.
- No existing financial formula changes.
