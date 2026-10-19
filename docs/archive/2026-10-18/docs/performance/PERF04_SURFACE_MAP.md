# PERF-04 — attribution product-surface map

> Status: non-normative discovery for issue #349. This document records the
> smallest truthful future API/DTO/UI path; it does not define attribution
> semantics, calculate a financial result, or authorize production changes.
>
> Observed at baseline `858d64c4c6777c33cf21201095240536d258db7c`.

## 1. Discovery conclusion

The smallest viable first slice is a backend-owned attribution read model with
a dedicated performance endpoint, followed by a thin frontend client/type and
a presentation-only panel on the existing Analytics page. A dedicated endpoint
is cleaner than extending the current XIRR/TWRR response: those DTOs describe a
single metric and already have strict shapes, while attribution has a different
dimensional grain and needs its own availability/provenance envelope.

The first slice should therefore be layered as follows:

1. Accept the PERF-04A/#346 attribution contract, including its dimensional
   grain, measures, source evidence, completeness rules, and stable states.
2. Add a backend-derived read model and a new endpoint (a path such as
   `/api/performance/attribution` is a naming candidate, not a contract). It
   should expose only contract-approved dimensions and measures, with explicit
   availability, quality, reason codes, and provenance where required.
3. Add the matching frontend type/client and render the returned facts using
   existing Analytics tables/charts or a small dedicated attribution panel.
   The frontend must format and present backend values only; it must not group,
   sum, allocate, or infer attribution.
4. Consider export/AI exposure as a later additive section after the attribution
   contract and export versioning decision are accepted. Do not repurpose the
   existing `investment_return` placeholder or current dashboard result fields.

The existing whole-portfolio XIRR/TWRR endpoints and current dashboard/export
contracts remain unchanged in this discovery slice.

## 2. Current API and DTO surfaces

| Surface | Current contract | Attribution fit and boundary |
| --- | --- | --- |
| XIRR | `GET /api/performance/xirr` returns `metric`, `scope`, `account_id`, `performance_currency`, nullable string `value`, `value_unit`, `annualized`, `period`, `availability`, `quality`, and `reason_codes`. | Useful as a neighboring performance surface and for period/scope conventions, but it is one metric response, not a dimensioned attribution response. The backend accepts an account scope; the frontend `PortfolioXirr` type currently narrows `scope` to `portfolio`. Do not silently use or widen that mismatch as part of PERF-04. |
| TWRR | `GET /api/performance/twrr` uses the same response envelope, with `annualized: false`; its backend scope also accepts portfolio or account. | Same boundary as XIRR. Existing values and prerequisite states can be linked from a future attribution view only when the accepted contract defines that relationship. |
| Performance availability | `GET /api/performance/availability` exposes scope, interval, performance currency, opening/closing valuation evidence, scope membership, cash and in-kind boundary coverage, external flows/boundaries, and separate XIRR/TWRR prerequisite states. It returns no return value. | Strong candidate for backend readiness/context alongside attribution. It is evidence, not an attribution calculator; a future attribution contract must consume it without redefining its states or turning unavailable evidence into zero. |
| Monthly dashboard | `GET /api/months/{month_id}/dashboard` returns `result_by_account` (`account_id`, name/type, `cash_income`, `unrealized_result`) and `result_by_instrument_class` (`instrument_type`, market value, cost basis, unrealized and realized result), plus allocation and warnings. | Existing tables/charts are useful presentation hosts, but these are current monthly monetary-result read models, not attribution. Adding an optional field could be compatible only after a contract decision; changing their meaning would break existing consumers and labels. |
| Capital composition | `GET /api/analytics/capital-composition` returns closed-month points, `reporting_month_id`, `snapshot_date`, asset-class allocations, totals, included debts, and net liquid capital. | Provides an existing `asset_class` presentation vocabulary and historical period keys. It has no performance contribution facts or instrument/account grain, so it cannot be treated as attribution. |
| Freshness/provenance | `GET /api/months/{month_id}/freshness-provenance` returns family/item statuses, source timestamps, coverage counts, account/instrument display names, and structured reasons. | Reuse the presentation pattern for quality/freshness context where the future contract needs it. Do not make freshness a performance measure or attach attribution semantics to a freshness family. |
| Month exports | `POST /api/months/{month_id}/export/markdown` and `/export/json` are existing report downloads assembled by backend services. | They are not the smallest first integration seam. Extending them would couple attribution to the month-report contract before its grain and availability are accepted. |
| AI Analysis Bundle | `POST /api/export/ai-analysis-bundle` (and JSON/Markdown variants) has strict versioned schemas, export-local refs, metric-level availability/precision/source/reason codes, and a `reporting_history` whose market-value-change/investment-return fields remain unavailable in v1. | A later optional `attribution` section could carry backend facts without changing existing meanings. It must use export-local refs, preserve unavailable versus zero, and follow the bundle's schema-version rules; it must not fill the existing unavailable return field speculatively. |
| Portfolio review package | `GET /api/export/portfolio-review-package` (JSON/Markdown downloads also exist) has profile-scoped sections, section status/reason codes/data, field states, and warnings. Its `dynamics` section explicitly does not invent period deltas or investment returns. | A later optional section is structurally possible and is cleaner than overloading `dynamics`. It should follow the package's additive section/version rules and remain read-only/backend-derived. |

The API layer maps backend results into Pydantic DTOs with
`ConfigDict(extra="forbid")` on the performance, dashboard, analytics, and
availability models. This makes a dedicated response shape the lower-risk
compatibility seam for a new multidimensional contract.

## 3. Identifiers and available joins

The current client can already address the main persisted entities:

| Entity or grain | Existing client-visible fields | Sufficiency for future attribution |
| --- | --- | --- |
| Account | `id`, `name`, `account_type`, `status`, `external_code`, `include_in_capital`, `include_in_returns`. | Sufficient as an application-level account key and display fallback. The attribution contract still needs to decide whether account inclusion and historical membership are facts in the result or only prerequisites. |
| Instrument | `id`, `name`, `instrument_type`, `isin`, `ticker`, `moex_secid`, `currency`, and lifecycle/price flags. | Sufficient to navigate or label an instrument in the local application. `instrument_type` is not the same field as the analytics `asset_class`; no implicit mapping is safe. |
| Position | `reporting_month_id`, `account_id`, `instrument_id`, quantity, cost/market values, price date/source, and update metadata. | Supplies existing joins for a point-in-time position view. It does not by itself provide an attribution contribution or historical return event. |
| Investment flow | `reporting_month_id`, `account_id`, optional `instrument_id`, flow type/date, gross/tax/commission/net amounts, currency, source, and optional statement link. | Supplies existing local joins and event facts. A future contract must state which flows are in its grain and how availability/provenance is represented; this document does not decide that. |
| External flow | `id`, reporting month, `account_id`, event date, exact boundary amount/currency, direction/kind, scope membership, transfer link/status, and scope classifications. | Useful for performance evidence and drill-down. The current response does not expose `instrument_id`; adding one or linking it to attribution is a contract decision, not a surface-map assumption. |
| Asset class | `asset_class` strings in capital-composition/allocation DTOs; current UI labels cover `cash`, `deposits`, `stocks`, `bonds`, and `gold_other`. | Sufficient as a current display bucket only. A future attribution contract must define whether asset class is a dimension, a derived classification, or out of scope. |
| Export identity | AI bundle uses deterministic `acct-*`, `inst-*`, and `flow-*` refs local to one export. | Correct for export joins and privacy. These refs are not database IDs, provider IDs, account numbers, or credentials; an export must not substitute raw persisted IDs. |

## 4. Frontend consumers and presentation patterns

### Analytics page

`frontend/src/pages/AnalyticsPage.tsx` currently loads:

- capital-composition history for the closed-month stacked area chart;
- a selected-month dashboard for allocation and investment-result drill-down;
- XIRR and TWRR for the interval between adjacent closed snapshots.

The page already provides loading, API-error, empty, and unavailable states. The
performance cards show a value only when the backend says `availability`
`available` and the value is non-null. Unavailable XIRR/TWRR reasons are mapped
to owner-facing messages; raw reason-code strings are not displayed as the main
copy.

### Existing charts/tables

`InvestmentResultChart` is the closest visual host because it already renders
account rows and instrument-class rows. Its account bars show cash income and
unrealized result; its instrument-class table shows realized and unrealized
result. It also states that the displayed result is not a return calculation.
`AssetAllocationChart` and `CapitalCompositionChart` provide the existing asset
class vocabulary and exact string-based money formatting, while chart-number
conversion is kept at the visualization boundary.

These components can be reused after a contract is accepted, but they must not
calculate attribution totals or derive a contribution from chart coordinates,
capital deltas, cost basis, or the existing realized/unrealized fields.

### Quality and reason presentation

The Freshness & Provenance page presents family status, coverage counts,
source/timestamp context, and human-readable reasons. The Analytics page uses
reason-code classification only to choose a safe explanatory message. A future
attribution panel should follow the same pattern: backend supplies the state and
stable reason codes; the frontend supplies labels and accessible presentation.

## 5. Plausible future attribution surfaces

The required fields below are structural needs only. They are not proposed
financial definitions. PERF-04A/#346 must decide the meaning, unit, scope, and
eligibility of every measure.

| Candidate surface | Contract fields it would need | Existing identifiers/DTOs | Endpoint vs extension | Compatibility/test impact | Backend/frontend boundary |
| --- | --- | --- | --- | --- | --- |
| Dedicated performance attribution endpoint **(recommended first)** | Period and scope; contract-defined dimension key/label; backend-derived measure(s); exact representation/unit; availability; quality/precision; stable reason codes; source/provenance; deterministic item ordering; optional totals only if the contract defines them. | Account and instrument IDs are available in local APIs; asset class is currently a string bucket; external-flow evidence is available separately. | New endpoint is cleaner because attribution has a different grain from single XIRR/TWRR metrics and avoids changing strict existing DTOs. | Add backend contract/endpoint tests and a frontend client/type test when implemented. Existing XIRR/TWRR consumers remain unchanged. | Backend selects, joins, validates, and derives all facts. Frontend renders, formats, filters only where the contract explicitly permits, and links to existing entities. |
| Existing Analytics page/panel | Same response fields as the dedicated endpoint plus presentation labels and empty/loading/unavailable states; no new client-side financial fields. | Existing `AnalyticsPage` state and panel primitives are sufficient for a first read-only presentation. | UI should consume the dedicated endpoint; extending current XIRR/TWRR calls would conflate metric and attribution responses. | Add component/client contract coverage for available, unavailable, partial, and empty states; preserve current XIRR/TWRR tests. | No client-side grouping, sums, period math, or classification. |
| Dashboard result panel | Would require an explicitly additive, contract-defined attribution field and a clear distinction from `cash_income`, realized result, and unrealized result. | `result_by_account` and `result_by_instrument_class` have useful keys but insufficient semantics. | Lower-risk as a later optional projection than as the first endpoint; do not relabel current fields. | `extra="forbid"` DTOs and existing chart/table snapshots/types require coordinated backend/frontend changes. | Backend owns the optional facts; existing result charts remain unchanged unless the contract explicitly adds a separate series/table. |
| AI Analysis Bundle | Optional versioned section; export-local account/instrument/flow refs; period/scope; backend-derived measures; metric/section availability, precision, source, reason codes, and warnings/field states as appropriate. | Existing bundle refs and state envelopes are sufficient structurally. | Additive optional section in a minor schema version is the likely compatible shape, subject to schema-owner approval. Never overload `reporting_history[].kpis.*.investment_return`. | Update JSON schema, synthetic fixture/contract tests, exporter mapping, and consumers; preserve major-version dispatch and unavailable/null rules. | Backend assembles one canonical export; frontend only downloads/displays it. |
| Portfolio review package | Optional section ID/requested section; section status/data/reason codes; field states; package-local refs; compatible metadata/calculation-version entry. | Existing section envelope and `dynamics`/`positions` source map are reusable. | Additive section is cleaner than changing `dynamics`, which explicitly avoids invented returns. | Update section enum, schema, profiles, package tests, and Markdown rendering together; preserve omitted/unavailable distinctions. | Backend assembles; frontend displays/downloads. No package-side calculation. |
| Freshness/provenance detail | Only if the accepted contract requires evidence context: source kind, observed/evaluation dates, coverage/status, and reason codes. | Existing family/item DTOs provide the presentation pattern but not attribution measures. | Keep separate from the attribution measure endpoint; link or embed only contract-approved evidence. | Avoid changing freshness meanings; add focused presentation coverage only if a real field is introduced. | Backend owns evidence status; frontend owns human-readable labels. |

## 6. Compatibility and privacy risks

1. **Existing scope asymmetry.** Backend XIRR/TWRR response models accept
   portfolio and account scope, while the frontend XIRR type currently declares
   portfolio only. This should be resolved or explicitly deferred by the
   Integrator; PERF-04 must not silently fix it.
2. **Different dimensions are not interchangeable.** `account_id`,
   `instrument_id`, `instrument_type`, and `asset_class` occur at different
   grains. A string or label mapping must not be treated as an accepted
   attribution classification without a contract decision.
3. **Current result is not attribution.** Account cash income/unrealized result
   and instrument-class realized/unrealized result are existing dashboard facts,
   not a new performance contribution measure. Reusing their labels would create
   a semantic compatibility break.
4. **Strict DTOs and schemas.** Backend response models use `extra="forbid"`,
   frontend types are explicit, and both export contracts validate shapes. Any
   additive extension needs coordinated contract, schema, client, and test
   changes; a dedicated endpoint minimizes the initial blast radius.
5. **Unavailable versus zero.** Existing export and performance contracts keep
   unavailable values null/unknown and preserve explicit zero. An attribution
   consumer must not fill missing history, missing membership, missing valuation,
   or missing evidence with zero.
6. **Historical coverage.** Closed/draft status, missing calendar periods,
   snapshot dates, and fail-closed availability are already visible patterns.
   Attribution cannot assume that adjacent points or a present position prove a
   complete historical contribution.
7. **Export privacy.** Export-local refs are safe join keys; database IDs,
   provider IDs, raw payloads, credentials, local paths, and private diagnostics
   must remain outside the export contract.
8. **Reason-code UX.** New stable reasons need owner-facing labels or a safe
   generic fallback. The frontend should never invent a new availability state
   from a reason-code substring.

## 7. Minimal layering recommendation

```text
accepted PERF-04A/#346 contract
          |
          v
backend attribution read model + dedicated endpoint
          |
          +--> Analytics client/type --> presentation-only panel/table/chart
          |
          +--> optional AI bundle section (versioned, later)
          |
          +--> optional portfolio-review section (versioned, later)
```

The endpoint and read model should be implemented before export integration so
there is one backend-derived source for UI and export projections. If export is
needed, both export packages should project the same accepted facts rather than
recompute them. Existing XIRR/TWRR, dashboard result, capital-composition, and
freshness contracts remain separate consumers.

## 8. Unresolved Integrator questions

These are intentionally left open because answering them would define financial
semantics or expand scope:

- What is the accepted PERF-04A attribution grain and which measures are in its
  first contract: account, instrument, asset class, flow, or another dimension?
- Which availability, quality, provenance, and completeness states are required
  for an attribution item and for an aggregate response?
- Should the first contract expose local application IDs, display-only labels,
  or another approved identity vocabulary? Export must use export-local refs.
- Is the existing backend/frontend XIRR scope asymmetry intentional, and should
  it be addressed in a separate task?
- Should attribution be exportable in the first implementation, or remain an
  Analytics-only projection until the AI bundle and portfolio-review package
  owners approve their additive schema changes?

No production code, schema, migration, API, UI, formula, test, provider, or
runtime change is part of this document.

## 9. Repository evidence anchors

- Performance DTOs and routes: `backend/src/hermes_finance/api/portfolio_xirr.py`,
  `portfolio_twrr.py`, and `performance_availability.py`.
- Dashboard and analytics DTOs: `backend/src/hermes_finance/api/dashboard.py` and
  `backend/src/hermes_finance/api/analytics.py`.
- Entity DTOs: `backend/src/hermes_finance/api/accounts.py`, `instruments.py`,
  `positions.py`, `investment_flows.py`, and `external_flows.py`.
- Frontend performance client/types: `frontend/src/api/performance.ts` and
  `frontend/src/api/types.ts`.
- Frontend consumers: `frontend/src/pages/AnalyticsPage.tsx`,
  `frontend/src/components/charts/InvestmentResultChart.tsx`,
  `AssetAllocationChart.tsx`, `CapitalCompositionChart.tsx`, and
  `frontend/src/pages/FreshnessProvenancePage.tsx`.
- Export contracts: `docs/AI_ANALYSIS_BUNDLE.md`,
  `docs/ai_analysis_bundle.schema.json`, `docs/PORTFOLIO_REVIEW_PACKAGE.md`,
  and `docs/portfolio_review_package.schema.json`.
- Performance source-of-truth boundary: `docs/PERFORMANCE_V1_RECONCILIATION_2026-09-06.md`
  and `docs/r08-01c-performance-availability.md`.
