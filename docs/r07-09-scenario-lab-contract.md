# R07-09 — Scenario Lab v1 contract

Status: normative for issue #141 Scenario Lab v1 (ADVERSARIAL REVIEW VERDICT: ACCEPT).
Workstream: `integration/decision-support-v1`. Baseline: `49b290df5d407fafff05a8aac6e3c081fdd8ea45`.
This file is the canonical persistence of the full ACCEPT-ed draft reviewed reviewer-only; short issue #141 body is not normative.

## 1. Purpose

Deterministic read-only what-if tool for owner decisions without forecasting markets.
Scenario Lab shows impact of hypothetical shocks on metrics Hermes can compute defensibly
(liquid capital, allocation/concentration, goal gap, future cash flow) while preserving
distinction between income, capital value and redemption and without writing back
to reporting months or provider data.

## 2. Contract version and compatibility

- `scenario_lab.contract_version = "r07-09-v1"`
- `scenario_lab.calculation_version = "r07-09-v1"` (identical in v1; bump both on any semantic change)
- `scenario_lab.shock_schema_version = "v1"`
- Input and output are versioned. Unknown contract/calculation version MUST fail closed.
- `generated_at` (if present in envelope) MUST NOT affect semantic fingerprint.
- Same frozen base payload + same contract version + same normalized scenario input
  = same semantic output + same semantic fingerprint (deterministic replay invariant).

## 3. Common normative rules

- Read-only. No mutation of `ReportingMonth`, `PositionSnapshot`, `DepositSnapshot`,
  `CashBalance`, `Debt`, `Goal`, actual income, future cash-flow canonical data,
  provider state, or any other canonical financial state. Any write path is BLOCKER.
- No scenario persistence in canonical DB. No network calls, no provider refresh,
  no external FX, no market-price lookup, no write-back.
- Money: integer RUB kopecks at persistence boundary (`*_kopecks`), decimal strings
  for percentages/rates. No binary `float` in financial logic. `Decimal` + `ROUND_HALF_UP`
  at canonical rounding boundary.
- Base position valuation: only persisted canonical `PositionSnapshot.market_value_kopecks`
  of the selected reporting snapshot. Live/provider quotes forbidden.
- Only the selected `ReportingMonth.snapshot_date` is the valuation scope.
  Only rows with `include_in_capital` (or existing equivalent) participate in liquid-asset
  allocation; debts with `include_in_liquid_capital` participate in net capital.
  `PropertySnapshot` never enters liquid scope.
- Missing metadata stays `unknown`/`unavailable`, never guessed from ticker/name/ISIN/account/provider/notes.
- No probabilistic forecasts, recommendations, invented correlations, rebalancing,
  fund look-through, or expected returns.
- Deterministic, stable ordering for all collections (sort by stable keys).

## 4. Versioned Scenario Lab input/output surface (v1)

`ScenarioLabRequestV1`:

- `contract_version: "r07-09-v1"` (required)
- `reporting_month_id: int` — selects frozen snapshot
- `shock: ShockV1` — exactly ONE shock object (see §5)
- `target_scope` (optional, v1 default = all eligible positions/deposits in frozen payload;
  see §4.1, reviewer note 3)
- `generated_at?: datetime` — envelope meta, excluded from fingerprint

`ShockV1` (v1):

- Exactly one key from the supported set. v1 implements only `equity_drawdown`.
  Multiple/combined shock input MUST fail closed with code `unsupported_composition_v1`.
  Do not implement other shock types even partially in 141-A.

`ScenarioLabResponseV1` contains at minimum:

- `contract_version`, `calculation_version`, `shock_schema_version`
- `reporting_month: { id, year, month, snapshot_date, status }`
- `base_fingerprint: string` (SHA-256 hex of frozen base payload, see §9)
- `semantic_fingerprint: string` (SHA-256 hex of normative semantic representation, no `generated_at`)
- `normalized_shock_input: { shock_type, drawdown_pct: decimal_string }`
- `normalized_target_scope: { selector, eligible_position_ids: [...], eligible_deposit_ids: [...] }`
- `assumptions: string[]` — stable sorted, e.g. `no_fund_lookthrough`, `no_fx`, `dividends_unchanged`
- `base: ScenarioMetrics`
- `stressed: ScenarioMetrics`
- `impact: ScenarioImpact`
- `row_applicability: { position_id -> applied|not_applicable|unknown }`
- `metric_support: { metric_key -> { status: supported|unknown|unavailable, reason_codes: string[] } }`
- `coverage: { total_positions, applied, not_applicable, unknown, known_scope_impact_kopecks }`
- `affected_canonical_refs: { reporting_month_id, position_ids: [...], account_ids: [...], instrument_ids: [...] }`
- `warnings: string[]`
- `generated_at?` echoed if supplied, not fingerprinted

`ScenarioMetrics` includes (where computable):

- `liquid_assets: MoneyValue`
- `liquid_capital_net: MoneyValue`
- `debts_included: MoneyValue` (unchanged)
- `allocation_by_asset_class: AllocationMetric` (or equivalent class breakdown)
- `allocation_by_account: AllocationMetric`
- `top_positions: ConcentrationMetric` (with `top_n` bounded 1..100, default 5)
- `capital_goals: { goal_id -> { current_value, gap, progress_pct } }[]`
- `per_position: { position_id -> { base_market_value, stressed_market_value, delta } }`
- `passive_income_effect: { status: unavailable, reason: no_deterministic_income_relationship }` (never 0)
- `future_cash_flow_rows: unchanged` (canonical rows, not recomputed)

Money/rates/percentages: kopecks integers on persistence side, decimal strings
with `FORMAT .2f` for output amounts/percentages, `ROUND_HALF_UP`. No binary float.

## 4.1 Target scope reproducibility (reviewer note 3 — normative)

If target scope is `all_eligible_deposits`, the eligibility set is frozen ONCE from the
frozen base payload of this scenario. It becomes part of `normalized_target_scope`
and the semantic fingerprint. It is NOT a dynamic selector re-evaluated against a later DB.

Concretely: `eligible_deposit_ids` is the sorted list of `DepositSnapshot.id` present in the
frozen snapshot with `Account.include_in_capital = true`. Same for positions.
The normalized scope is snapshotted, not re-queried.

## 5. Supported shock in 141-A

### 5.1 equity_drawdown (only shock in 141-A)

Input:

- `drawdown_pct: Decimal` as decimal string, `0 <= drawdown_pct <= 100` inclusive.
  Outside range MUST fail closed with reason `invalid_drawdown_pct` (or equivalent
  machine-readable code) and not produce a scenario result.
  Non-finite, non-decimal, or binary float representation MUST be rejected.

Semantics:

- Applicable only to authoritative `instrument_type = stock`.
- Formula for each applicable position:

```
stressed_market_value = base_market_value * (1 - drawdown_pct / 100)
```

  Computed in `Decimal` with `ROUND_HALF_UP` to whole kopecks.
  Example: base 100_000 kopecks (1 000.00 RUB), pct 20 => 80_000 kopecks.
  Must use project `Decimal`/minor-unit semantics and canonical rounding boundary;
  binary float forbidden.

- Deposits, cash, debts, bonds/funds/currency/gold/other, and any position with
  `not_applicable` remain `unchanged`.

### 5.2 Other shocks (explicitly out of scope for 141-A)

`fx_translation_shock`, `issuer_impairment`, `deposit_rate_assumption`,
`inflation_real_value`, combined/multi-shock semantics, issuer metadata, FX
normalization, fund look-through, rebalancing, dividend assumptions — MUST NOT
be implemented in 141-A. Receiving such input MUST return
`unsupported_composition_v1` (for multi-shock) or `unsupported_shock_type_v1`
(and never a partial result).

## 6. Frozen base adapter

Scenario Lab is built on top of existing canonical read semantics. No second
financial model for liquid capital, Risk & Allocation, or Goals.

Base position valuation is exactly `PositionSnapshot.market_value_kopecks` of
the chosen reporting snapshot, with existing `include_in_capital` semantics.
Forbidden: live/provider quotes, provider refresh, network, external FX,
independent market-price lookup, write-back.

Implementation MUST compose/reuse canonical read models (`liquid_capital`,
`risk_allocation`, `goal_achievement` etc.) via adapter/projection, not by
copying formulas into a second independent model. Where existing architecture
requires an adapter, the adapter is a minimal deterministic projection that
does not change financial semantics.

## 7. Applicability (normative mapping)

Determined solely by authoritative `Instrument.instrument_type` enum persisted on
`instruments` joined to `PositionSnapshot.instrument_id`. No inference from
ticker/name/ISIN/account/provider/notes. No fund look-through.

| Stored `instrument_type` | Applicability for `equity_drawdown` |
|---|---|
| `stock` | `applied` |
| `fund` | `not_applicable` |
| `bond` | `not_applicable` |
| `currency` | `not_applicable` |
| `gold` | `not_applicable` |
| `other` | `not_applicable` |
| missing / null / not in enum | `unknown` |

Row-level `applicability` is reported for every included position (stable order).

### FX reporting currency edge case (reviewer note 1 — normative)

For FX shocks: if `target_currency == reporting_currency`, then FX shock applicability
to that reporting-currency exposure is `not_applicable` with value `unchanged`.
This is not FX translation. (Structural placeholder for future FX shock; in 141-A
this rule has no operative effect beyond documenting the invariant.)

### Inflation same-month example (reviewer note 2 — normative, non-semantic)

Do not change the inflation real-value formula. Add acceptance example/test:
when `months_ahead = 0`, `real_value = nominal_value`.

## 8. Propagation (full coverage, canonical reuse)

When coverage is complete (no `unknown` rows), recompute through existing
canonical semantics:

- liquid assets
- liquid capital (`total_assets - included_debts`)
- asset allocation (by explicit type / dashboard classes, canonical grouping)
- account allocation (by `account_id`, with `unassigned_cash` handling per canonical)
- top-position concentration (rank by stressed value, stable IDs)
- capital Goal current value / gap / progress (reuse `goal_achievement` domain;
  current value = stressed `liquid_capital_net`; target unchanged)
- per-position impact (`stressed - base`, applicability)

Debts remain `unchanged` (do not shock debts).

Do not copy canonical formulas into a new model if reuse/composition is possible.

Future cash-flow rows (`ExpectedCashFlow`), redemption/principal, and deposit
balance principal remain unchanged by equity drawdown.

## 9. Passive income and future cash flow

Equity price drawdown MUST NOT automatically change:

- dividend cash flow
- coupon cash flow
- redemption/principal
- deposit income
- historical actual passive income
- canonical future cash-flow rows

For any passive-income effect without deterministic canonical relationship,
return:

```
support: unavailable
reason: no_deterministic_income_relationship
```

Never return `0` in place of `unavailable`. Dividends/coupons/redemption in
canonical future rows are echoed unchanged.

## 10. Unknown propagation

Row applicability values: `applied`, `not_applicable`, `unknown`.
Metric support values: `supported`, `unknown`, `unavailable`.

If `coverage.unknown > 0` and the unknown row is potentially affected (type unknown,
could be stock), then:

- `known_scope_impact` (sum of deltas for `applied` rows) MAY be calculated and returned;
- `coverage` MUST be visible (`total/ applied / not_applicable / unknown` and
  `known_scope_impact_kopecks`, plus unknown reason codes);
- Full aggregate stressed metrics (stressed liquid assets/capital, allocations,
  concentration, capital goal aggregates) MUST NOT be emitted as `supported`/`exact`.
  Their `metric_support.status` is `unknown` with reason `instrument_type_not_authoritative`
  (or equivalent). Implementations MUST NOT silently treat the unknown row as
  unchanged and declare exact full stressed capital.

Example (normative):

Base: stock 1000.00 (100_000k), missing-type position 400.00 (40_000k)
Shock -20%
Known-scope impact: -200.00 (-20_000k)
Unknown row could be stock (would be -80) or not. So exact full stressed capital
is not knowable; system must report `unknown` support, expose coverage, and may
report known-scope impact separately. It MUST NOT return 1_200.00 as exact.

Aggregation precedence for metric support (deterministic):
`unavailable` > `unknown` > `supported`; reason codes sorted.

## 11. Deterministic semantic output and fingerprint

The service MUST produce a deterministic semantic representation sufficient for
export. Minimum fields included in fingerprint input (stable ordering, sorted keys):

- `contract_version`, `calculation_version`, `shock_schema_version`
- `reporting_month: { id, year, month, snapshot_date, status }`
- `base_fingerprint` (frozen base payload hash)
- `normalized_shock_input` (shock_type, drawdown_pct as decimal string)
- `normalized_target_scope` (selector + sorted eligible IDs)
- `assumptions` (sorted)
- `base` outputs (amounts as kopecks integers + decimal strings for percentages)
- `stressed` outputs (same)
- `impact` (delta amounts)
- `row_applicability` (sorted by position_id)
- `metric_support` (sorted by metric key)
- `reason_codes` (sorted)
- `coverage` (counts + known_scope_impact)
- `affected_canonical_refs` (sorted)

Money/rates/percentages use deterministic `Decimal`/minor-unit representation;
percentages as decimal strings (`"20.00"`). No binary float.

`generated_at` MUST NOT be included in fingerprint input. Semantic fingerprint
is SHA-256 hex of JSON canonical form: `json.dumps(obj, sort_keys=True,
separators=(',',':'), ensure_ascii=False)`. Implementation MUST document and
implement this canonicalisation exactly.

Invariant (normative):

```
same frozen base payload
+ same scenario lab contract version
+ same normalized scenario input
= same semantic output + same semantic fingerprint
```

Replay MUST be identical (byte-for-byte fingerprint, decimal-string exactness).

## 12. Strict read-only

Scenario evaluation MUST NOT mutate:

- `ReportingMonth`
- `PositionSnapshot`
- `DepositSnapshot`
- `CashBalance`
- `Goal`
- actual income
- future cash-flow canonical data
- provider state
- any other canonical financial state

Any write path is BLOCKER. No scenario persistence in canonical DB.
Tests MUST assert `no DB mutation`; production/Preview DB MUST NOT be used;
no real owner secrets.

## 13. Explicitly out of scope for 141-A (and for this contract slice)

- Scenario Lab UI/polish
- `fx_translation_shock`
- `issuer_impairment`
- `deposit_rate_assumption`
- `inflation_real_value` (except the single same-month example/test in §7)
- combined/multi-shock semantics (must fail as `unsupported_composition_v1`)
- DB schema expansion for future shocks
- issuer metadata / FX translation metadata
- fund look-through
- rebalancing
- dividend assumptions
- market forecasting, expected returns, probabilities, correlations
- provider refresh / network access
- unrelated refactors

If implementation of 141-A requires any of the above, STOP and report a scope
conflict to the integrator (Lera). Do not decide for the integrator.

## 14. Tests and verification (binding)

See `VERIFICATION_POLICY.md` and `AGENTS.md`. This task MUST cover at minimum:

1. clean stock drawdown; 2. 0% drawdown; 3. 100% drawdown; 4-8. fund/bond/gold/currency/other → not_applicable;
9. missing/invalid type → unknown; 10. unknown potentially affected row blocks exact aggregate but keeps known-scope impact/coverage;
11. debts unchanged; 12-15. liquid capital / asset allocation / account allocation / top-position concentration propagation;
16. capital Goal current/gap/progress propagation; 17. passive-income effect = unavailable/no_deterministic_income_relationship, not 0;
18-21. dividends/coupons/redemption/canonical future cash-flow rows unchanged;
22. deterministic replay identical fingerprint; 23. generated_at does not change fingerprint;
24. combined shock rejected as unsupported_composition_v1; 25-26. invalid drawdown below 0 / above 100 rejected;
27. explicit no-DB-mutation; 28. no network/provider calls during evaluation.

Targeted tests first, then one full relevant harness per `AGENTS.md`/`VERIFICATION_POLICY.md`,
and `git diff --check` must PASS.

## 15. Reviewer notes disposition

The three notes in the task prompt are normative additions to the ACCEPT-ed draft
as captured in §4.1, §7 and §7 (FX edge, inflation example, all_eligible_deposits).
No other semantic changes to the ACCEPT-ed contract are made.
