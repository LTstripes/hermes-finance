# #331 — AI Financial Review contract

**Status:** contract/design only. This document and its schema define the
follow-up implementation boundary; they do not add an assembler, endpoint,
frontend behavior, migration, provider call, cloud upload, or LLM call.

**Schema name:** `hermes.finance.ai_financial_review`

**Schema version:** `1.0.0`

**Normative schema:** [`ai_financial_review.schema.json`](ai_financial_review.schema.json)

**Synthetic fixture:** [`ai_financial_review.synthetic.json`](ai_financial_review.synthetic.json)

## 1. Purpose and product role

`hermes.finance.ai_financial_review` is the one canonical, full-scope export
that the owner should choose for a normal monthly review in ChatGPT or another
AI assistant. It is a deterministic, read-only handoff of Hermes facts and
owner-entered context. The JSON file is canonical; a future Markdown download
may be rendered from the same DTO in a later scope and must not have separate
financial semantics. Markdown is not part of the #331 implementation scope.

The existing contracts remain available during the transition:

| Existing export | Role after #331 | Use it when |
| --- | --- | --- |
| `hermes.finance.ai_analysis_bundle` | Compact semantic/source contract | Debugging the AI contract, coverage and reason codes, or inspecting the lowest-level export source. It is not the recommended monthly handoff. |
| `hermes.finance.portfolio_review_package` | Detailed portfolio-review envelope | Diagnosing allocation, concentration, freshness and profile-specific section states. Its full profile is a source for the canonical report. |
| Legacy/raw finance report | Technical compatibility export | Migration, troubleshooting or repository-specific investigation. It is not recommended for ordinary AI analysis. |

The recommended report has no concise/full selector. It is always the
owner-facing full review. Technical package profiles remain independent and do
not change the recommended choice.

## 2. Composition boundary

The implementation must compose existing authoritative builders/read models and
map them into this contract. It must not calculate a second financial model.

The intended source map is:

| Report section | Authoritative source and mapping rule |
| --- | --- |
| `current_capital`, `historical_dynamics`, `passive_income`, `future_cash_flows`, `current_portfolio`, `goals`, `iis_and_tax` | The full `portfolio_review_package` and its underlying `ai_analysis_bundle`; use the richer `cash_flow_after_allocations`, passive-income breakdown and salary facts from the bundle where the package projection is narrower. |
| `allocation_and_concentration` | Existing `risk_allocation` read model as already adapted by `portfolio_review_package`; preserve its support/coverage and export-local refs. |
| `current_portfolio.freshness` | Existing freshness/provenance summary and the bundle's valuation freshness fields. No universal freshness score is introduced. |
| `debts_and_real_estate` | Existing package context plus direct allowlisted debt/property read models for persisted rows and the #336 fields (`annual_rate`, due/end dates, mortgage rate). The report may expose facts that the old package did not project, but must not derive new debt or property semantics. |
| `user_context` | Persisted `monthly_comments` and explicitly owner-entered notes. Text is carried with provenance and is never parsed as a number or used in a calculation. |
| `budget_and_saving` | Persisted `saving_allocations`, actual `expense_entries`, and #336 `planned_budget_lines`. Plan-vs-actual rows use the exact `(period, category, expense_type)` key and are a side-by-side presentation only. |
| `data_quality`, `warnings`, `field_states` | Existing deterministic insights, coverage states and stable warning codes. Open evidence maps, raw diagnostics and provider payloads stay out of the export. |

The adapter uses an allowlist. It must not serialize ORM objects, API request
objects, provider DTOs or debug structures wholesale. Export-local refs such as
`acct-*`, `inst-*`, `debt-*`, `comment-*` and `expense-*` are deterministic
join keys inside one file; they are not database IDs, account numbers or
provider identifiers.

## 3. Top-level contract

The normative top-level shape is:

```text
schema_name
schema_version
metadata
scope
coverage
provenance_summary
sections
field_states
warnings
```

`sections` always contains the same named sections. A section has
`status`, sorted `reason_codes`, and `data`:

- `included` means the authoritative source is available;
- `partial` means the source is present but has explicit gaps or approximate
  values;
- `unavailable` means the source cannot provide an authoritative value and
  `data` is `null`.

An empty array inside an `included` section means that the available source has
no persisted rows. It is not a synonym for an unavailable section.

The required sections are:

1. `current_capital` — selected-period liquid assets, included debt, liquid
   capital net, property equity, a separate `cash_flow_after_allocations` KPI,
   and `total_net_worth` only when an authoritative aggregate exists.
2. `historical_dynamics` — ordered month points with capital, actual passive
   income and breakdown, active income, mandatory expenses, saving allocations,
   cash flow after allocations, property equity and only authoritative return
   fields.
3. `current_portfolio` — accounts, instruments, positions, deposits, cash,
   exact ISIN/ticker where stored, acquisition cost/cost basis, selected price,
   price date/source and freshness/provenance.
4. `allocation_and_concentration` — asset-class/account allocation and accepted
   concentration read models, including support states and export-local refs.
5. `passive_income` — actual history path, rolling actual average, current
   breakdown and forecast with its existing assumptions/warnings.
6. `future_cash_flows` — coupons, dividends, interest, redemptions/principal,
   dates, tax semantics, approximation flags and calendar totals.
7. `goals` — target/current/gap/progress/deadline and supportable projection
   state for each goal.
8. `debts_and_real_estate` — debt rows, rates and dates, property snapshots,
   mortgage rate/payment/balance, property equity, coverage and data-quality
   warnings.
9. `iis_and_tax` — IIS type/opening/eligible-close dates, contributions,
   benefits, result semantics and salary-tax coverage.
10. `user_context` — monthly comments plus owner-entered entity notes with
    `source=persisted_user_note`.
11. `budget_and_saving` — saving destinations/amounts/notes, actual expense
    lines, #336 planned budget lines, and side-by-side plan-vs-actual rows.
12. `data_quality` — deterministic insights and the report-level quality
    summary; warnings and unavailable/partial paths are also repeated in the
    canonical top-level `warnings`/`field_states` lists.

## 4. Financial and availability invariants

- Money, rates, percentages and quantities use the existing exact string
  representations. No JSON floating-point financial values are introduced.
- `null`/`unavailable`/`unknown` never becomes `0.00`. A persisted explicit zero
  remains an exact zero. This applies to capital, rates, dates, plans, tax data,
  and every metric.
- Missing calendar history is unknown and remains listed in
  `scope.missing_calendar_periods`; it is never synthesized as a zero month.
- A draft month is provisional and never enters the eligible CLOSED-month
  rolling average. Its history point remains marked partial/provisional.
- `liquid_capital_net` excludes real estate and mortgage. `property_equity` is
  a separate reference metric. `cash_flow_after_allocations` is a derived
  monthly surplus and is never labelled as physical cash; persisted cash is
  reported only under the portfolio cash balances.
- Passive income keeps existing semantics: salary, cashback, contributions,
  withdrawals, redemption principal and unrealized price growth are excluded;
  persisted net amounts are not taxed or commissioned twice.
- Redemption remains principal. A provider-announced amount with unknown
  personal tax remains approximate and is never labelled personal net income.
- `market_value_change` and cash-flow-adjusted `investment_return` are
  unavailable unless an accepted authoritative aggregate exists. Liquid-capital
  movement is not relabelled as return.
- The report includes an exact stored ISIN when present and universal position
  fields for gold and other instruments. Gold does not get a parallel formula.
- Free text is context, not a structured financial fact. Numbers in comments or
  notes must not affect calculations, matching, coverage or warnings.
- Plan-vs-actual uses the exact `(period, category, expense_type)` key. A
  missing side is `null`; an explicit zero is a money object with `amount` set
  to `"0.00"`. No variance or budget formula is invented by this contract.
- #336 facts are consumed as already implemented in current `main`: `0%` is a
  real fact, `null` is unknown, planned budget is separate from actuals, and
  missing optional values do not block export.

## 5. Provenance and privacy

`metadata.source_contracts` pins the source schemas used by the adapter:

- `hermes.finance.ai_analysis_bundle` `1.2.0`;
- `hermes.finance.portfolio_review_package` `1.0.0`.

The metadata also records the integrated `#336` financial-context contract by
name, without pretending that it is a separate calculation schema.

Allowed owner context is limited to persisted monthly comments and explicitly
stored notes on exported owner facts. The report excludes tokens, credentials,
cookies, database/backup/export paths, local host/router details, database IDs,
raw account/external codes, provider IDs, raw protocol payloads, uploaded
documents, stack traces, SQL and open-ended diagnostic evidence.

## 6. Versioning and compatibility

`schema_version` follows SemVer:

- patch: clarification or validation correction without changing valid-instance
  meaning;
- minor: additive optional fields/sections or backward-compatible enum values;
- major: removal/rename, changed requiredness/units, changed source meaning or
  changed financial counting semantics.

Consumers dispatch on the major version and validate the exact schema declared
by the file. The v1 contract is strict (`additionalProperties=false` in the
normative schema) so exporter leaks and typos fail early. Existing bundle and
package versions are not silently mutated by this report.

The canonical recommended export is one JSON file. A future Markdown export,
if added, must be generated from the same read-only snapshot and must not have
separate financial semantics. Generation must not persist an export, refresh a
provider, send data to a cloud/LLM service or alter the database.

## 7. Export-page hierarchy contract

The future Export-page implementation must make the choice obvious in this
order:

### 7.1 Recommended block — first export content

Label/badge: **Рекомендуется для AI-анализа**

Title: **Полный финансовый отчёт для AI**

Copy:

> Рекомендуемый вариант для ежемесячного анализа. Содержит капитал,
> динамику, портфель, распределение и концентрацию, доходы, цели, долги,
> недвижимость, будущие выплаты, качество данных, план накоплений и ваши
> комментарии.

Primary CTA: **Выгрузить отчёт для AI (JSON)**

The block must state that the file contains financial data, is created locally,
is not sent automatically, and should be checked before manual upload. A small
preview may show the selected period, covered history, section states and warning
count without recomputing any value. There is no Markdown companion or
secondary AI-report CTA in the #331 implementation scope; Markdown remains a
future/out-of-scope option.

### 7.2 Additional/technical exports — collapsed and secondary

Use a `<details>`/secondary panel titled **Дополнительные / технические
выгрузки**. Every item must explain what it contains, how it differs, when to
use it and when not to choose it:

- **AI Analysis Bundle** — compact semantic KPI/coverage/reason-code source;
  use for contract debugging, not for the ordinary monthly handoff.
- **Portfolio Review Package / Full** — detailed investment review with
  allocation, concentration, freshness and section states; use for portfolio
  diagnostics, while the recommended report already includes its useful data.
- **Concise Portfolio Review Package** — profile-limited diagnostic view; use
  only when a deliberately smaller technical package is needed.
- **Legacy/raw finance export** — compatibility/debugging dump; use for
  migration or investigation, not for ordinary AI analysis.

Backup/restore remains a separate lower-priority local-database section and is
not presented as an AI export.

### 7.3 Future UI acceptance boundary

The implementation slice must add frontend coverage for the hierarchy and
copy: the recommended block appears before additional exports, has one primary
CTA, every technical export has a purpose/difference explanation, and the local
no-cloud warning is visible. This contract task intentionally does not add that
frontend behavior.

## 8. Follow-up implementation checklist

The next implementation must add schema validation and a synthetic regression
covering, at minimum:

1. a monthly comment containing a number, proving the text is preserved but not
   used as an authoritative value;
2. a bond with exact ISIN;
3. a gold position with average acquisition cost/cost basis and current price;
4. a saving allocation with destination and note;
5. IIS type/opening/eligible-close metadata;
6. one #336 zero rate and one unknown rate;
7. an unentered planned budget that is not serialized as a zero budget;
8. a missing historical month and an unavailable aggregate that remain unknown.

The follow-up must prove read-only generation, stable ordering, no technical
secret fields, and unchanged behavior of the three existing export families.
