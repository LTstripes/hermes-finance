# AI Analysis Bundle contract

**Schema name:** `hermes.finance.ai_analysis_bundle`

**Current schema version:** `1.0.0`

**Normative schema:** [`ai_analysis_bundle.schema.json`](ai_analysis_bundle.schema.json)

**Synthetic example:** [`ai_analysis_bundle.synthetic.json`](ai_analysis_bundle.synthetic.json)

**R08 portfolio-review package:** [`PORTFOLIO_REVIEW_PACKAGE.md`](PORTFOLIO_REVIEW_PACKAGE.md)

The R08 package is the profiled owner-review output envelope built from this
`1.0.0` source contract. It adds explicit scope, section states, allocation and
freshness coverage without changing the financial meanings or creating a second
calculation model.

## Purpose and boundary

The AI Analysis Bundle is a deterministic, read-only export of the financial picture already
defined by Hermes Finance. It is intended for an explicit owner download and later, separate
submission to an AI assistant. Hermes does not send the bundle anywhere, call an LLM or cloud
API, persist an AI interpretation, or change financial data while generating it.

This contract does not introduce a financial model. A future exporter must call the existing
backend services and map their results. It must not reproduce formulas in an export service,
router, frontend component, or prompt. R07-01 defines only this contract, its synthetic fixture,
and validation; it does not define an endpoint, UI, or file-generation workflow.

## Representation rules

- Money is a decimal string in major RUB units, always with two fractional digits. JSON numbers
  are not used for money, rates, percentages, prices, or quantities.
- Every analytically optional metric carries `availability`, `precision`, `source`, and
  `reason_codes`. An unavailable value is `null`, has `precision=unknown`, and explains why.
- Actual and forecast breakdown components use the same metric shape as their totals. A missing
  component is unavailable; an exporter must not invent zero or retain a stale numeric placeholder.
- Missing calendar months are unknown history. They are listed in
  `coverage.missing_calendar_periods` and are never synthesized as zero-valued months.
- A draft month may be exported, but its values carry `draft_value` and the point has partial
  coverage. Draft months never enter eligible CLOSED-month historical averages.
- Export-local refs (`acct-*`, `inst-*`, `goal-*`, `flow-*`) exist only to join objects inside one
  bundle. They are deterministically assigned by the exporter and are not database IDs, provider
  IDs, account numbers, or credentials.
- Arrays have stable ordering. Reporting periods and rolling-average periods are ascending by
  `(year, month)`; accounts, instruments, and goals by export ref; positions by
  `(account_ref, instrument_ref)`; upcoming flows by `(expected_date, event_ref)`; warnings by
  `(severity, code, scope)`. The same persisted state, generation inputs, and `generated_at`
  produce byte-equivalent logical content after canonical JSON serialization.
- `generated_at` is an explicit generation input, not a financial observation. Financial
  freshness is expressed by snapshot, price, source-as-of, or event dates where Hermes really
  has them. The contract does not invent freshness timestamps.

## Normative semantic sources

| Bundle area | Authoritative Hermes source | Required interpretation |
|---|---|---|
| Reporting period and status | `ReportingMonth` and reporting-month lifecycle | `closed` is immutable history; `draft` remains provisional. |
| Liquid assets and net capital | `liquid_capital_for_month` and `asset_allocation_for_month` / ADR 0007 | `liquid_assets_total - included_debts = liquid_capital_net`; real estate and mortgage are outside liquid capital. |
| Actual passive income | `passive_income_for_month` | Deposit actual interest + coupon net + dividend net + other capital income net. Cashback, active income, deposits, withdrawals, redemption, and price growth are excluded. Persisted net amounts are not taxed or commissioned twice. |
| Rolling actual average | `passive_income_average` / ADR 0008 | Last at most 12 eligible CLOSED records on/after the configured history boundary. Missing or draft months do not enter the denominator. |
| Passive-income forecast | `forecast_passive_income` | Expected interest/coupons/other plus the actual CLOSED-month dividend component. Expected dividends are not added again. Redemption remains principal and is excluded. Persisted deposit monthly estimates are annualized by the current approximate method and labelled accordingly. |
| Main passive-income goal | persisted `goals` plus `build_goal_achievement_summary` | Current value is the rolling actual average after R02-27, not the C04 forecast. A below-target future date remains `not_projectable` when no trajectory exists. |
| Monthly cash context | `cash_balance_for_month`, `actual_net_for_month`, expense and saving services | Active income, cashback, passive income, expenses, and saving allocations retain their existing cash-flow inclusion semantics. |
| Market value change / return | no accepted aggregate service currently exists | Both fields stay unavailable in v1. A consumer may inspect point-in-time valuations, but must not relabel liquid-capital delta as market value change or market value change as investment return. |
| Current portfolio | the selected reporting month's persisted accounts, instruments, position/deposit snapshots, and cash balances | Locally persisted valuation fields remain authoritative for the export. Provider observations are provenance, not silent replacements for Hermes identity or valuation semantics. |
| Debt and property | debt, property, liquid-capital, and mortgage services | Included short-term debt affects liquid capital; mortgage/property remain reference context. Property equity is separate. |
| IIS | `iis_result` plus persisted IIS profile, contributions, and benefit states | Only received tax benefits increase the result with benefit. Planned/submitted remain separate; rejected does not increase either result. Redemption and contributions are not income. |
| Salary tax | `calculate_salary_tax` and salary-tax opening context | YTD/bracket values appear only if backend calculation succeeds with complete known history. `salary_tax_history_incomplete` is an unavailable state, never an assumed zero. |
| Upcoming cash flows | `merged_payout_calendar` / ADR 0011 | Manual/provider reconciliation decides which row counts. Provider totals with unknown personal tax remain provider-announced approximate amounts, never labelled net. An unresolved duplicate uses the existing safe manual-only behavior. Calendar total, non-principal calendar amount total, and principal total are separate. |
| Provenance | persisted manual/provider/statement provenance already accepted by Hermes | `manual`, `t_invest`, `alfa_pro`, and `alfa_statement` are reported only where meaningful. Raw protocol payloads and provider correlation IDs are excluded. |

The historical `actual_history_metric_path` is a path, not a duplicate series. A consumer reads
actual passive-income history from `reporting_history[].kpis.passive_income_actual`. This prevents
the same actual totals from being summed once from reporting history and again from a second copy.

## Counting rules for upcoming flows

`upcoming_cash_flows.items` is the owner-visible merged calendar. Three fields make the two
different totals unambiguous:

- `included_in_calendar_total` says whether the row is present in the merged cash calendar;
- `included_in_passive_income_forecast` says whether the row feeds the current forecast formula;
- `forecast_treatment` explains `included`, `represented_by_historical_component`, or
  `excluded_principal`.

The neutral `amount` field is interpreted only together with `amount_semantics` and
`personal_tax_status`:

- `owner_expected_net` means the owner-entered expected tax is known/accounted in the amount;
- `owner_expected_amount_tax_unknown` remains approximate and carries
  `personal_tax_unknown`;
- `provider_announced_amount_tax_unknown` is the provider-announced total, not a promise of
  personal net income; it is always approximate and carries `personal_tax_unknown`;
- `principal` applies to redemption and has tax status `not_applicable` for passive-income
  classification.

Therefore:

- coupon, interest, and other expected capital income may be included in the forecast;
- expected dividends remain useful calendar events but use
  `represented_by_historical_component` because the forecast already annualizes actual dividend
  history;
- redemption uses `excluded_principal` and never increases passive income;
- `calendar_total = non_principal_calendar_amount_total + principal_total`;
- duplicate resolution is explicit and never permits a provider/manual pair to count twice by
  accident.

The JSON Schema validates shape and states. Targeted tests additionally validate monetary
reconciliation and the counting rules because JSON Schema is not an arithmetic engine.

## Coverage, approximation, and warnings

Coverage is reported twice on purpose:

- `coverage.domains` summarizes whether each analytical domain is complete, partial, or
  unavailable across the bundle;
- a section or metric reports its local availability and reason codes.

`precision=exact` means the value is an exact representation of its authoritative persisted or
backend-derived source. It does not claim the underlying manual estimate is objectively current.
Approximate forecast methods use `precision=approximate` and a warning code. `unknown` is reserved
for unavailable values.

Warnings contain a stable machine code, severity, scope, and concise owner-safe explanation.
They must not contain stack traces, SQL, filesystem paths, private payload fragments, credentials,
or debug dumps.

## Current portfolio selection

The exporter records both the selected `reporting_period` and `selection_reason`. The preferred
R07-02 behavior is `latest_closed`, because it provides a stable current analytical snapshot while
still retaining later draft months in `reporting_history`. If no closed month exists, an exporter
may select `latest_available`, must preserve its `draft` status, and must mark coverage partial.
No later price, quantity, or balance may be backfilled into an earlier reporting snapshot.

## Versioning and compatibility

`schema_version` follows SemVer:

- patch: clarification or validation correction that does not change valid instance meaning;
- minor: backward-compatible optional fields, optional sections, or additive enum values;
- major: removal/rename, changed requiredness, changed units, changed counting/source semantics,
  or another change that can alter an existing consumer's interpretation.

Consumers must dispatch on the major version. A consumer supporting major `1` must ignore unknown
optional fields after validating the instance with the schema declared by that instance. The
checked-in `1.0.0` schema is intentionally strict (`additionalProperties=false`) to detect exporter
leaks and typos; a later minor version publishes its matching strict schema rather than weakening
the old schema. New required fields or new financial meanings require major `2`.

`metadata.calculation_versions` is also an allowlisted object. v1 accepts only
`monthly_summary`, `passive_income_forecast`, and `goal_achievement`; it is not an extension map
for arbitrary runtime metadata.

Fields are required when their semantic state must always be known. Potentially absent financial
values are not omitted: they use the explicit unavailable shape. An optional application version
is represented as `null` when it cannot be obtained safely.

No schema registry or remote lookup is required. The exported file identifies the version, and
Hermes ships the matching schema with the application.

## Privacy and intentional exclusions

The bundle is intentionally rich in user-approved financial information, but it excludes
technical and low-value identifiers. A future exporter must use an allowlist mapping and must not
serialize ORM objects, provider DTOs, request objects, or debug structures wholesale.

Excluded fields and data include:

- API tokens, secrets, passwords, cookies, credentials, certificates, and session primitives;
- `.env` values, database/backup/export paths, filesystem paths, hostnames, and local router URLs;
- raw Alfa/T-Invest/statement protocol payloads, frames, uploaded documents, hashes, stack traces,
  SQL, and debugging payloads;
- database primary keys, reporting-month IDs, raw account numbers/external codes, provider account
  or subaccount IDs, provider instrument UIDs/identity keys, reconciliation row IDs, and import
  session IDs;
- notes/comments and free-form provider text by default; a later explicitly reviewed contract may
  add a bounded owner-selected narrative field;
- unrealized market value change relabelled as return, inferred IIS classification, guessed tax
  brackets/YTD, fabricated freshness, or inferred missing-month zeroes.

Application and formula version strings are allowed because they help interpretation and do not
expose local infrastructure. Instrument ISIN/ticker and human-readable account/instrument names
are allowed because they materially improve analysis of an explicitly exported financial file.

## R07-02 implementation constraints

Issue #129 may implement assembly/export on top of this contract, subject to independent review.
It must:

1. remain a read-only query path with no cloud or LLM call;
2. map only allowlisted fields into dedicated DTOs;
3. reuse the authoritative services in the table above;
4. assign deterministic export-local refs and stable ordering;
5. validate the generated instance against the declared schema before offering it for download;
6. add integration tests proving no persistence writes and no technical-secret fields;
7. keep UI/download behavior, filename, and explicit owner action in #129 scope rather than
   retrofitting them into R07-01.
