# R07-11A — Deterministic Insights Engine v1

**Status:** implementation contract for issue #178.
**Contract version:** `deterministic_insights_v1`
**Ruleset version:** `v1`
**Endpoint:** `GET /api/months/{month_id}/deterministic-insights`

The engine is a small read-only composition layer over accepted Hermes
contracts.  It does not recalculate their financial semantics.  The endpoint
uses only persisted local state and the caller's evaluation date; it never
calls a provider, performs network I/O, calls an LLM, predicts a future value,
or writes to the database.

## Response contract

The top level identifies the selected reporting month, evaluation clock, and
forecast version used by the cash-flow rules:

```json
{
  "contract_version": "deterministic_insights_v1",
  "ruleset_version": "v1",
  "forecast_version": "v1",
  "reporting_month_id": 12,
  "year": 2030,
  "month": 5,
  "status": "draft",
  "snapshot_date": "2030-05-12",
  "evaluated_on": "2030-05-12",
  "insights": []
}
```

Every emitted item has the same structured shape:

| Field | Meaning |
| --- | --- |
| `code` | Stable machine-readable rule code. Existing accepted reason codes are reused where possible. |
| `type` | Stable rule family, such as `freshness_warning` or `concentration`. |
| `severity` | `error`, `warning`, or `info`; this is attention priority, not a risk score. |
| `message` | Short owner-facing explanation. |
| `evidence` | Values returned by the accepted source service, including support/coverage state where relevant. Money and percentages remain exact strings. |
| `comparison_period` | Reserved for a future accepted comparison; `null` in v1 because no rule invents a comparison series. |
| `source` | Accepted service/read-model path that supplied the evidence. |
| `as_of` | Financial snapshot or valuation target date when the source defines one. |
| `provenance` | Optional source/provider references; no raw payloads or credentials. |
| `reason` | Stable explanation of the predicate that fired. |

The list is deterministic: `error`, then `warning`, then `info`, followed by
`code`, `source`, and `reason`.  A repeated call with the same persisted state,
evaluation date, and forecast version returns the same logical insight list.

## v1 rules

There are six small rule families.  Concentration has two additional sibling
codes because payout and redemption are different accepted cash-flow
components.

| Rule family | Emitted code(s) | Predicate and evidence | Accepted source |
| --- | --- | --- | --- |
| Close guard | Existing hard-guard code, currently `snapshot_date_required` | The authoritative close-readiness contract returns a hard blocker. | #136 `close_readiness` / `close_hard_guards` |
| Important freshness | Existing warning reason code, for example `quote_stale`, `quote_unavailable`, or `mapped_quote_not_applied` | A #139 family reason has warning severity. Informational missing-data reasons do not become warnings. | #139 `freshness_provenance` |
| Payout reconciliation | `unresolved_payout_reconciliation` | The accepted merged payout calendar has a positive unresolved manual/provider reconciliation count. This is an advisory warning and does not change close behavior. | #136/#137 `close_readiness` and `merged_payout_calendar` |
| Cash-flow concentration | `upcoming_payout_concentration`, `redemption_concentration` | The top accepted dated payout or redemption item is at least `50.00%` of that metric's exact denominator. Redemption remains principal. Approximate or degraded source data downgrades the item to `info`. | #137/#169 `risk_allocation` |
| Portfolio concentration | `portfolio_concentration` | The top persisted position is at least `50.00%` of the accepted liquid-assets denominator. This is descriptive concentration only, never a recommendation. | #169 `risk_allocation.top_positions` |
| Asset-class coverage | `partial_asset_class_coverage` | The accepted asset-class metric has a positive denominator and a positive `unallocated_amount`. No class is inferred from names, tickers, or provider identity. | #169 `risk_allocation.allocation_by_asset_class` |
| Salary-tax history | `salary_tax_history_incomplete` | #171 explicitly reports incomplete salary-tax history. Taxable YTD and threshold values remain unavailable. | #171 `tax_iis_planner.salary_tax` |

The table contains six rule families, while the cash-flow family can emit two
independent deterministic signals.  v1 intentionally does not add a generic
risk score, target drift, issuer/maturity inference, or a tax-threshold
proximity alert.  #171 exposes an exact distance to a configured threshold,
but v1 has no accepted owner-facing proximity threshold; adding one would be a
new policy decision rather than a safe interpretation of that DTO.

Missing or incomplete data follows the source contract: it suppresses a rule
when the required value is absent, or downgrades a signal to `info` when a
known subset is explicitly available.  The engine never substitutes zero,
guesses context, or relabels unavailable values.  The selected forecast
version is echoed in the response so that cash-flow signals remain auditable.

## Reconciliation and AI Analysis Bundle boundaries

The #170 normalized broker-reconciliation result is transient and is produced
only during an explicit provider preview.  It is not persisted.  The v1 GET
endpoint therefore does not call #170, cache its result, or emit a broker
reconciliation insight from absent data.  A future follow-up may pass an
already-built normalized result into a pure evaluator or add an additive
preview-response integration, without introducing persistence or background
provider work.

The AI Analysis Bundle remains schema `1.0.0` with strict allowlists and
version invariants.  Adding this endpoint's insight DTO to that bundle would
require an additive bundle schema/version decision, so v1 leaves the bundle
unchanged and records this as a follow-up boundary.

No frontend formulas, migrations, new persistence tables, or UI are part of
this slice.
