# Data Freshness and Provenance Center (R07-07)

**Status:** implementation contract for issue #139.  
**Endpoint:** `GET /api/months/{month_id}/freshness-provenance`  
**Assembly:** `hermes_finance.services.freshness_provenance.build_freshness_provenance_summary`

This is a read-only summary of **already persisted** provenance. It does not fetch
providers, refresh quotes, apply snapshots, or invent timestamps.

## Four clocks that must not be mixed

| Clock | Meaning | Used for freshness? |
|---|---|---|
| Source timestamp | Provider observation or event date that Hermes actually stored (`price_date`, `payment_date`, `event_date`, `fetched_at` when that is the observation) | Only when the family has a defined freshness rule |
| Import/apply time | When the owner accepted the data into Hermes | Never |
| Reporting month | Selected `year`/`month` plus `snapshot_date` | Identifies the slice; not a freshness clock |
| Local edit time | Hermes `updated_at` for manual rows | Never |

`generated_at` / `evaluated_on` are evaluation-clock inputs, not financial observations.

Quote valuation target is `min(snapshot_date, evaluated_on)` (ADR 0009). That target is
**not** the reporting month itself and **not** the apply timestamp.

## No universal score

The summary never emits a freshness percentage, index, or blended score. Families are
not averaged. A missing Alfa PRO observation timestamp does not pull quotes toward
“stale”. Manual rows do not enter a denominator.

## Family semantics

### `market_quotes`

Persisted `PositionSnapshot` rows for the selected month plus latest append-only
`position_quote_provenance` for that snapshot.

- Freshness is classified only for a **current** provider price source (`t_invest`, `moex`)
  that still has provenance with a `price_date`.
- Classifier: ADR 0009 `classify_freshness(quote_valuation_target_date, price_date)`.
  `ok` → `current`; 8..30 day gap → `stale`; >30 days → `unavailable`.
- A later manual override is current-source `manual`. Historical quote provenance remains
  visible as history and does **not** keep classifying the row as stale.
- Manual / `alfa_pdf` prices without a provider timestamp are `not_applicable`, never stale.
- Mapped-but-never-applied quotes are a coverage warning (`mapped_quote_not_applied`), not stale.
- `fetched_at` is the provider-read time. `applied_at` is owner apply. Neither is `price_date`.

### `t_invest_payouts`

Active applied T-Invest payout events for the month.

- `payment_date` is an event date, not a quote observation.
- Events are not classified current/stale by age. Family status is `not_applicable` when
  rows exist, `missing` when none exist.
- Latest revision supplies `fetched_at` (provider read) and `applied_at` (owner apply).

### `alfa_pro_positions`

Alfa PRO snapshot observations are **transient**. Hermes does not persist `source_as_of`
or broker-snapshot provenance after quantity apply (ADR 0013 persistence gate).

- Family status is always `unknown`.
- Reason `alfa_pro_observation_not_persisted`.
- `providers` is empty unless a persisted month-scoped audit marker already proves
  Alfa PRO participation. Capability/configuration alone must not list `alfa_pro`
  or contribute it to `multiple_providers`.
- Do not substitute `snapshot_date`, `updated_at`, or apply time as Alfa PRO freshness.

### `alfa_statement_payouts`

Active Alfa depository income-report events linked to this month’s investment cash flows.

- `event_date` / `record_date` are document event dates, not quote freshness.
- `applied_at` is import/apply time.
- Not classified current/stale by age.

### `manual_month_data`

Local month entries that Hermes already treats as owner-maintained: incomes, expenses,
savings, expected cash flows, and position snapshots whose current `price_source` is
`manual` or `alfa_pdf`.

- No provider timestamp → `not_applicable`, never stale.
- Local `updated_at` is reported only as `local_edit_time` when the table has it.

### `deposit_cash_snapshots`

Deposit snapshots and cash balances for the month.

- Locally entered. Freshness is `not_applicable` when rows exist, `missing` when none exist.
- Deposit `updated_at` is `local_edit_time` only. Cash balances have no edit timestamp;
  that absence is `source_timestamp_unavailable` / `local_edit_time` null, not stale.

## Status values

Per classifiable observation (`freshness_status` on an item):

- `current` — provider observation is within the family rule
- `stale` — provider observation is inside the stale window
- `unavailable` — observation exists but is outside the usable window (quotes >30 days)
- `unknown` — family/item cannot be classified (missing observation timestamp)
- `not_applicable` — no provider freshness rule applies
- `missing` — used on family coverage when the family has no rows (not on quote items)

Family `status` additionally allows `mixed` when classifiable quotes contain both
`current` and `stale`/`unavailable`.

## Reason codes

Stable machine codes for later Close Cockpit (#136) consumption. Severity here is
informational vs warning only. This endpoint never promotes a warning to a close blocker.

| Code | Typical severity | Meaning |
|---|---|---|
| `quote_current` | info | At least one applied quote is current vs valuation target |
| `quote_stale` | warning | At least one applied quote is stale vs valuation target |
| `quote_unavailable` | warning | Applied quote `price_date` is beyond the 30-day lookback |
| `quote_source_timestamp_inconsistent` | warning | Stored `price_date` is after the valuation target |
| `mapped_quote_not_applied` | warning | Refresh-eligible mapping exists, no current provider quote |
| `manual_source_no_provider_timestamp` | info | Manual/local value; not stale |
| `historical_quote_provenance_present` | info | Snapshot was overridden; old quote provenance kept |
| `payout_event_present` | info | Applied T-Invest payouts exist |
| `payout_none_for_month` | info | No applied T-Invest payouts in this month |
| `payout_not_freshness_classified` | info | Payout events are not quote-stale |
| `alfa_pro_observation_not_persisted` | info | Cannot classify Alfa PRO observation time |
| `statement_event_present` | info | Active statement events exist for the month |
| `statement_none_for_month` | info | No active statement events in this month |
| `statement_not_freshness_classified` | info | Statement events are not quote-stale |
| `manual_month_data_present` | info | Owner-maintained month rows exist |
| `manual_month_data_empty` | info | No manual month rows |
| `deposit_cash_present` | info | Deposit/cash snapshots exist |
| `deposit_cash_empty` | info | No deposit/cash snapshots |
| `deposit_cash_local_edit_only` | info | Only local edit time exists |
| `source_timestamp_unavailable` | info | This clock is absent; do not infer stale |
| `multiple_providers` | info | More than one provider appears in the selected month |

## Privacy and non-goals

- No raw provider payloads, tokens, document bytes, hashes, provider account/instrument
  UIDs, or filesystem paths.
- No background refresh or network on this path.
- Provenance tables remain append-only; this endpoint does not write.
- Close Cockpit (#136) should import these reason codes rather than re-derive quote
  freshness or treat apply time as observation time.
