# R08-AI01 — Portfolio review package contract

**Status:** first bounded slice for [issue #237](https://github.com/LTstripes/hermes-finance/issues/237).

**Contract:** `hermes.finance.portfolio_review_package` version `1.0.0`.

**Normative schema:** [`portfolio_review_package.schema.json`](portfolio_review_package.schema.json)

**Synthetic fixture:** [`portfolio_review_package.synthetic.json`](portfolio_review_package.synthetic.json)

## Scope of this slice

This slice records the gap audit, freezes the transport contract, and provides the
local owner-triggered portfolio-review handoff. It adds a read-only package
endpoint, a human-readable companion report, and a preview/download UI. It does
not upload data, call a cloud service or LLM, persist an export, or refresh a
provider.

The existing `hermes.finance.ai_analysis_bundle` `1.0.0` contract remains unchanged
and remains the source contract for the first adapter. The review package is one
new output contract, not a second financial model: its sections deliberately reuse
the existing bundle's money, availability, provenance, payout-counting, and
closed-month semantics. A later assembler maps existing DTOs/read models into this
contract without recalculating them.

## Gap audit against the current AI Analysis Bundle

| Review need | Current `ai_analysis_bundle` v1.0.0 | R08 package decision |
| --- | --- | --- |
| Owner-selected concise/full output | One required, full-shaped export; no profile or requested scope | Require `profile` and a scope with requested sections |
| Direct capital answer | Liquid capital is available inside each history point, but a consumer must locate the selected period | Add a selected-period `capital` section; keep total net worth unavailable until an accepted aggregate exists |
| Positions usable without opening Hermes | Rich current positions exist, with local refs and valuation metrics | Reuse the same refs, account/instrument allowlist, exact metrics, and valuation provenance in `positions` |
| Dynamics | `reporting_history` is authoritative and already preserves gaps/draft status | Expose it as an explicit `dynamics` section; do not invent period deltas or investment returns |
| Allocation/concentration | Accepted read models exist in the separate Risk & Allocation surface, but are absent from the bundle | Add a full-profile `allocation` section with export-local refs and sanitized support states |
| Passive income | Actual history, rolling average, and forecast semantics are strong and already separated | Reuse the existing actual/forecast DTO meanings and payout double-counting rules |
| Future payments | Merged calendar and principal/tax semantics are already explicit | Reuse the existing calendar item shape and totals; provider-announced tax-unknown amounts remain approximate, not net |
| Freshness | Point provenance and warning codes exist, but the family status/evaluation clock is only in the Freshness & Provenance endpoint | Add a `freshness` family summary using the accepted six family statuses; never emit a universal score |
| Unavailable evidence | Metric-level unavailable values are supported; absent whole sections have no contract state | Every section has `included`, `partial`, `unavailable`, or `omitted` state; unavailable metrics remain `null` with `precision=unknown` |
| Omitted evidence | No profile-driven omission ledger | `omitted` sections carry `data=null`, a reason code, and a stable field-state path |
| Deterministic insights | A separate endpoint exists and its `evidence` object is intentionally open | Reserve a typed, sanitized optional section; no arbitrary evidence map, raw diagnostics, IDs, or provider payloads |
| Privacy boundary | Existing export has strict allowlists and excludes technical/private fields | Keep export-local refs only; prohibit IDs, paths, tokens, raw payloads, credentials, and free-form diagnostics |

The current bundle is therefore a good financial source, but not yet a stable
review handoff: a reviewer would otherwise have to know which history point is
current, call a second endpoint for freshness/allocation, infer which empty or
missing values are unavailable, and guess what a concise profile intentionally
left out.

## Profile semantics

Both profiles have the same top-level shape. Section state is never inferred from
an absent JSON key.

| Section | `concise` | `full` |
| --- | --- | --- |
| `capital` | Included selected-period capital summary | Included selected-period capital summary |
| `positions` | Included current positions and valuation | Included current positions, cash, deposits, and valuation/provenance |
| `dynamics` | Included ordered history and explicit gaps | Included ordered history and explicit gaps |
| `passive_income` | Included actual/average/forecast | Included actual/average/forecast and full breakdown |
| `future_cash_flows` | Included totals and dated items | Included totals and dated items |
| `freshness` | Included family status and coverage | Included family status and coverage |
| `allocation` | Omitted by profile unless a later concise policy opts in | Included when the accepted risk-allocation read model is available |
| `context` (goals, debt/property, IIS/tax) | Omitted by profile | Included when each source is available; individual metrics can still be unavailable |
| `deterministic_insights` | Omitted by profile | Included only as the typed, sanitized insight shape; unavailable/omitted is explicit if not assembled |

The contract allows a full profile to mark a source `unavailable` when Hermes has
no authoritative value. `omitted` means the owner/profile intentionally did not
request the field. These states are different and must not be collapsed into an
empty array or zero.

## State and privacy rules

- A section envelope always contains `status`, sorted unique `reason_codes`, and
  `data`. `included`/`partial` requires non-null data; `unavailable`/`omitted`
  requires `data: null`.
- Money, rates, percentages, and quantities are strings. No binary JSON floats
  are part of the contract.
- `money_metric` and `ratio_metric` carry the authoritative value, availability,
  precision, source, and reason codes. An unavailable metric is `null` with
  `precision=unknown`; it is never a guessed zero.
- `field_states` records unavailable or omitted non-metric paths and section
  paths. Metric-local availability remains the source of truth for metric fields.
- `freshness.evaluated_on` and `metadata.generated_at` are evaluation/generation
  clocks, not financial observations. Quote freshness uses the accepted
  `quote_valuation_target_date`; no apply time or local edit time is substituted.
- Current and historical financial semantics come from existing services/read
  models. The package does not calculate a net-worth sum, return, tax, forecast,
  concentration, or freshness score in the exporter.
- Provenance is limited to the existing safe source/provider vocabulary. Export
  refs such as `acct-*`, `inst-*`, and `flow-*` are local join keys, not database
  or provider identifiers.
- Warnings are short owner-safe messages. They contain no tokens, credentials,
  local paths, database IDs, SQL, stack traces, raw provider payloads, or private
  diagnostics.

## Authoritative source map

| Package section | Existing source/read model | Boundary |
| --- | --- | --- |
| `capital` | `liquid_capital_for_month`, `property_equity` | Liquid capital remains separate from property equity and mortgage |
| `positions` | current `ai_analysis_bundle` projection over account/instrument/position/deposit/cash snapshots | Provider observations do not replace Hermes valuation or identity |
| `dynamics` | `reporting_history` from the current bundle and historical batch/read models | Missing months stay unknown; no fabricated deltas/returns |
| `passive_income` | `passive_income_for_month`, `passive_income_average`, `forecast_passive_income` | Actual, forecast, dividend-history component, and redemption remain distinct |
| `future_cash_flows` | `merged_payout_calendar` | Calendar total, non-principal total, and principal total remain separate |
| `freshness` | `build_freshness_provenance_summary` | Family statuses and reason codes are carried over; no provider call |
| `allocation` | `risk_allocation` / dashboard allocation DTOs | DB/provider IDs are replaced by export-local refs or omitted |
| `context` | existing goals, debt/property, IIS/tax read models | Received benefits only affect actual IIS result; incomplete salary history stays unavailable |
| `deterministic_insights` | `build_deterministic_insights` | Only the closed typed projection is safe for this contract; open evidence maps are not copied |

## Versioning and follow-ups

`schema_version` follows SemVer. A minor version may add optional sections or
profile-compatible fields; a major version is required for changed requiredness,
units, counting semantics, or source meaning. Consumers dispatch on the major
version and must validate the exact schema identified by the package.

The package endpoint is available at `GET /api/export/portfolio-review-package`
for an explicit local preview. `GET /api/export/portfolio-review-package/json`
and `/markdown` download the same assembled DTO as JSON or a human-readable
Markdown companion. The owner UI exposes concise/full profile selection, section
status preview, and both downloads from the Export screen. Synthetic assistant
evaluation remains fixture-based and does not use owner data. Owner UAT with real
local data remains separate and no real package belongs in Git.
