# ADR 0011 — automatic investment payout calendar

- **Status:** Accepted
- **Date:** 2026-08-16
- **Release line:** 0.5 / `r05`
- **Baseline:** `17a02b25801f329721caa8b554de0320ef52cf7c`
- **Source task:** issue #35 — R05-00
- **Decision method:** blind architecture benchmark followed by canonical synthesis; see `docs/reviews/2026-08-16-r05-00-architecture-benchmark.md`.

## Context

Hermes Finance 0.4 added explicit owner-triggered T-Invest quote preview/apply with provider-neutral mapping, T-Invest `instrument_uid`, immutable provenance, `preview_changed`, mixed-success preview, no background refresh and no production MOEX fallback.

0.5 adds a future investment payout calendar derived from the owner's locally stored position snapshots. The feature covers bond coupons, principal redemptions/repayments, and dividends when T-Invest exposes sufficiently reliable future events.

This ADR does **not** import broker holdings, operations, accounts or orders. T-Invest is a read-only reference-data provider; Hermes positions remain local owner data.

## Decision summary

Hermes SHALL use a separate provider-payout bounded context rather than silently inserting provider rows into the existing owner-entered `expected_cash_flows` table.

The lifecycle is:

```text
owner click
  -> fetch provider data
  -> normalize provider events
  -> compare with applied provider events + manual expected flows
  -> preview
  -> explicit owner selection
  -> apply with provider/local re-read and preview_changed guard
  -> append-only revision/provenance
```

The dashboard SHALL merge countable manual expected flows with countable applied provider payouts at read time. Manual owner records remain first-class and are never silently overwritten, deleted or reclassified.

The current C04 passive-income forecast formula remains unchanged in 0.5: expected coupons can improve C04, announced provider dividends appear in the payout calendar but do not replace the historical dividend component, and principal redemption never counts as passive income.

## Non-negotiable invariants

1. Windows-only/local-only product; runtime remains `127.0.0.1:8000`.
2. No cloud/auth/telemetry.
3. External provider access only after an explicit owner action.
4. No background refresh, startup fetch, cron, polling or retry loop.
5. Production provider is T-Invest read-only. No MOEX production fallback.
6. No `Accounts`, `Operations`, `Orders`, `StopOrders`, `Sandbox`, `Transfer` or broker-portfolio import in R05.
7. Financial arithmetic uses `Decimal` and/or integer minor units with `ROUND_HALF_UP`; binary float is forbidden.
8. Closed reporting months are immutable until explicit reopen. Preview MAY read a closed month; apply MUST reject it.
9. Provider-derived expected events and actual realized investment cash flows are separate concepts. Reaching an expected payment date MUST NOT auto-create an actual cash flow.
10. Principal redemption/repayment is future cash flow, not passive income.
11. Existing manual expected flows are owner data and MUST NOT be silently overwritten, deleted, reclassified or merged by provider refresh.
12. Tokens, account IDs, private DB/export contents and full raw provider payloads MUST NOT be persisted for payout audit purposes.
13. Owner-facing provider failures MUST be sanitized; raw provider bodies/tokens/stacks are not returned to the browser.

## Existing local semantics that remain authoritative

The existing `expected_cash_flows` model is month-scoped and versioned, and its calendar already distinguishes coupon/dividend/interest/redemption/other. Redemption is included in total cash flow but excluded from passive income.

The current forecast formula remains:

```text
forecast_12m_net_passive_income =
    expected_deposit_interest_next_12m
  + expected_coupon_net_next_12m
  + expected_dividend_component_from_eligible_closed_actual_history
  + other_expected_capital_income
```

Expected dividend rows are intentionally not used by C04 today. R05 MUST NOT change that formula implicitly.

## Provider boundary

Introduce a provider-neutral payout boundary separate from quote retrieval.

A normalized provider event MUST contain only normalized/public event data needed for identity, classification, amount, dates, coverage and audit. The adapter MUST NOT own financial policy such as whether redemption counts as income or how manual duplicates are resolved.

Production routing in 0.5 is T-Invest only.

## Canonical event kinds

0.5 recognizes these normalized event kinds:

- `coupon`
- `dividend`
- `redemption`

Unsupported provider event kinds remain visible as `unsupported` when useful, but are not applied.

For T-Invest bond events specifically:

- `EVENT_TYPE_MTY` is a redemption candidate;
- `EVENT_TYPE_CALL` is an offer/call event, not automatically a redemption cash flow;
- `EVENT_TYPE_CONV` is conversion, not a redemption cash flow;
- `EVENT_TYPE_CPN` MUST NOT be imported in parallel with `GetBondCoupons` unless a later live probe proves a non-duplicating use.

## Event identity

### General rule

Canonical identity is:

```text
(provider, instrument_uid, event_kind, identity_key)
```

For 0.5 `provider = t_invest`.

`instrument_uid` is the canonical T-Invest instrument identity accepted in ADR 0010. FIGI is not the canonical persisted payout identity.

A provider-native event identifier MAY replace/further qualify the natural key only after a live probe demonstrates that it exists and is stable across refreshes/revisions.

Mutable fields MUST NOT be part of identity merely for convenience. In particular, amount, owner quantity, tax estimate and normally payment date are revision data rather than identity data.

### Coupon identity

Preferred `identity_key`:

1. `n:{coupon_number}` when `coupon_number > 0`;
2. otherwise `p:{coupon_start_date}:{coupon_end_date}` only when both dates exist and the pair is unambiguous for the instrument;
3. otherwise the event is `ambiguous_identity` and MUST NOT be applied automatically.

`coupon_date`, amount, coupon type, quantity and tax do not enter identity.

### Dividend identity

Preferred `identity_key`:

1. a stable provider event ID, if a later live probe proves one exists and is stable;
2. otherwise `r:{record_date}`.

`dividend_type` MUST NOT be part of identity because provider state such as `Cancelled` is lifecycle/revision information for the same declared event, not necessarily a distinct payout.

If more than one distinct provider dividend for one instrument resolves to the same natural identity and no stable provider ID disambiguates them, the rows are `ambiguous_identity` and MUST NOT be applied automatically.

If neither stable provider ID nor `record_date` is available, the dividend is not automatically applyable.

### Redemption identity

Preferred source is `GetBondEvents` with `EVENT_TYPE_MTY`.

Preferred `identity_key`:

1. `mty:{event_number}` when `event_number > 0`;
2. otherwise `mty-date:{event_date}` only when the date is present and uniquely identifies one MTY event for the instrument;
3. otherwise `ambiguous_identity`.

A synthetic maturity event derived from `BondBy.maturity_date` plus nominal is **not** enabled by this ADR by default. R05-01 live probe MUST establish whether this is safe, and any later enabling MUST at minimum exclude perpetual bonds and handle amortizing bonds conservatively.

## Date semantics

All provider timestamps used as financial calendar dates MUST be converted through the project's Moscow calendar-date normalization and persisted/compared as date-only values where the business concept is a date rather than an instant.

### Coupon

- announcement/declaration: metadata only if present;
- `fix_date`: record/fix date, metadata only;
- `coupon_start_date` / `coupon_end_date`: coupon-period metadata and possible identity fallback;
- `coupon_date`: **canonical payout calendar date**.

If `coupon_date` is absent, Hermes MUST NOT invent the payout date from `coupon_end_date`; the row is tentative/incomplete and not applyable.

### Dividend

- `declared_date`: announcement date;
- `last_buy_date`: eligibility/ex-date-adjacent metadata, not payout date;
- `record_date`: owner registry/fix date and preferred natural identity anchor;
- `payment_date`: **canonical payout calendar date**.

If `payment_date` is absent, Hermes MAY show the event as tentative in preview but MUST NOT synthesize a date or apply it to the cash-flow calendar.

No rule such as `record_date + N business days` is part of 0.5.

### Redemption

For a validated MTY event:

1. `pay_date` is preferred calendar date when present;
2. otherwise `event_date` may be used if the live probe confirms its meaning for MTY events;
3. a `BondBy.maturity_date` fallback requires the explicit post-probe decision described above.

## Amount semantics

### General calculation

Provider amounts are normalized from exact MoneyValue/Quotation representations to Decimal without binary float.

For an applyable per-unit amount:

```text
total_amount = ROUND_HALF_UP(per_unit_decimal * exact_snapshot_quantity, 0.01 RUB)
```

Do not round the per-unit amount prematurely to kopecks and then multiply if that can change the final result. Provenance SHOULD retain the exact normalized per-unit decimal representation plus the final integer-kopek total.

R05 is RUB-only. Non-RUB payout events are `unsupported`; there is no FX conversion.

### Coupon

Use provider per-bond payout when present and valid. Do not derive a coupon from percentage/nominal when the authoritative per-unit payout is missing.

Unknown personal tax semantics remain unknown:

- expected tax = unknown/null;
- expected cash amount = provider announced amount;
- result is marked approximate for net-income purposes.

Floating/variable coupon rows with missing or clearly non-final payout amount are tentative until the live probe defines observed behavior.

### Dividend

T-Invest currently documents `dividend_net` as the dividend amount per security including currency. The field name MUST NOT be interpreted as proof of the owner's personal after-tax cash receipt.

0.5 stores/interprets it as the provider-announced per-unit payout amount unless the live probe establishes a stronger semantic contract.

Hermes MUST NOT fabricate 13%/15% or any other personal tax amount. Tax remains unknown; the UI must label the amount accordingly.

`Daily Accrual`, `Return of Capital` and other non-ordinary dividend types are not silently treated as ordinary passive-income dividends. They require explicit normalization rules or remain unsupported. `Return of Capital` is not passive income.

### Redemption

Use validated per-bond principal repayment from the MTY event when available.

Redemption is included in future cash flow and excluded from passive income.

Amortizing principal schedules require live-probe evidence; `amortization_flag` alone is not a sufficient schedule.

## Position quantity semantics

The driver of quantity is the `PositionSnapshot` for the **selected reporting month, account and instrument** on which the owner invoked payout preview.

Do not use:

- latest known quantity across arbitrary months;
- broker account holdings from T-Invest;
- a silently substituted later/earlier month.

Preview uses the exact selected snapshot quantity. On successful apply, quantity and total amount are frozen in the applied revision/provenance.

If the owner changes draft quantity afterward, existing applied totals do not silently recalculate. A later preview shows `revised` and an explicit apply is required.

If a position disappears after an earlier apply, the event is not auto-deleted. Preview may surface `position_gone`; owner action is required to dismiss/reconcile it.

Closed-month applied data is never rewritten by refresh of another month.

## Horizon and provider coverage

The owner-facing cash-flow horizon remains the existing 12-month interval from the selected reporting month's `snapshot_date`.

Provider request windows MAY be wider than the calendar horizon to accommodate provider filtering semantics, but they must be bounded and explicit.

Every successful provider fetch used for refresh comparison MUST produce coverage metadata sufficient to answer:

```text
method
instrument_uid
requested_from
requested_to
provider_filter_basis
successful/failed
```

### Coverage-aware missing rule

A previously applied event MUST NOT be labeled `missing_from_provider` merely because it is absent from a response.

`missing_from_provider` is valid only when all are true:

1. fetch for that exact instrument/method succeeded;
2. response was structurally valid;
3. the event's provider comparison/filter key lies inside the proven coverage of the request;
4. the event is absent from that successful covered response.

If network/auth/malformed/unknown-window conditions exist, no `missing_from_provider` inference is made.

This is especially important for dividends because T-Invest `GetDividends` filters requests by `record_date`, while Hermes calendars cash by `payment_date`.

`missing_from_provider` is a **derived refresh/preview state**, not automatic cancellation and not automatic database deletion. The last applied event remains active/countable unless the owner explicitly changes its lifecycle.

## Preview state machine

Preview is read-only. It MUST NOT mutate manual expected flows, applied provider payouts, reporting months or position snapshots.

Minimum row statuses:

- `new`
- `unchanged`
- `revised`
- `possible_manual_duplicate`
- `cancelled_by_provider` when cancellation is explicit and identity is stable
- `missing_from_provider` under the coverage-aware rule
- `tentative`
- `ambiguous_identity`
- `unsupported`
- `unavailable`
- sanitized provider/local `error`
- `position_gone` where applicable

Defaults:

- `new`: selectable; default selection MAY be true for clearly valid non-duplicate rows;
- `revised`: selectable only by explicit owner choice;
- `possible_manual_duplicate`: not selected by default;
- cancellation/missing/tentative/ambiguous/unsupported/error: not auto-selected.

## Apply and preview_changed

Apply is allowed only in draft/reopened months.

Apply is selective and transactional for the selected set. If any selected row fails validation, re-fetch consistency, persistence or provenance write, the entire selected set rolls back.

Before mutation, apply MUST re-read both:

1. current provider-normalized event data through the same normalization path used by preview;
2. current local position snapshot/quantity and any manual reconciliation state referenced by the selection.

The apply selection carries the preview fingerprint. Material fields include at minimum:

```text
provider
instrument_uid
event_kind
identity_key
canonical payment_date
exact normalized per-unit amount
currency
provider lifecycle/status relevant to counting
position_snapshot_id
reporting_month_id
account_id
instrument_id
exact quantity
manual duplicate/link target when an owner decision depends on it
```

Any material mismatch produces `preview_changed`, performs zero writes, and requires a new explicit preview. Apply MUST NOT silently use the newly fetched values instead.

## Revision and disappearance semantics

### Provider changes amount/date

Same stable identity + changed material attributes => `revised`.

Owner apply creates a new append-only revision/provenance record. Earlier revision data is retained.

### Explicit provider cancellation

If the provider explicitly communicates cancellation for the same stable identity, preview shows `cancelled_by_provider`. Only explicit owner apply moves the applied payout lifecycle to cancelled. History remains.

### Provider omission

Omission alone never deletes/cancels. Under proven coverage it may produce `missing_from_provider`; otherwise no missing inference is made.

### Event reappears

If the same identity reappears, it becomes `unchanged` or `revised`. There is no delete/recreate cycle.

### Identity changes

If the provider changes data such that the stable identity no longer matches and equivalence cannot be proved, Hermes represents old `missing` plus new `new`. It MUST NOT heuristic-auto-merge identities.

## Manual reconciliation

Manual `expected_cash_flows` remain untouched owner data.

Provider refresh MUST NOT change a manual row's:

- amount/tax/net;
- date;
- flow type;
- notes;
- confirmation state;
- source;
- existence.

### Duplicate candidate

`possible_manual_duplicate` is a warning, not identity.

A provider event is a duplicate candidate only within the same reporting month/account/instrument/flow type and when dates are sufficiently close for a plausible match. The implementation may use a deterministic conservative window, but amount MUST NOT be required for duplicate matching because provider vs manual tax/rounding semantics can differ.

If multiple manual candidates match, reconciliation is ambiguous and no automatic link is created.

### Owner actions

For a duplicate candidate, 0.5 supports explicit outcomes:

- **Skip provider:** no provider apply.
- **Keep both:** provider is applied and both are deliberately countable; the UI warns before apply.
- **Link/reconcile:** both records remain auditable, but exactly one counting survivor is selected. Default survivor is manual unless owner explicitly selects provider.

R05 MUST NOT automatically replace/archive/delete a manual row as part of provider apply. Existing manual CRUD remains the only direct owner-edit/delete path for manual records.

An unresolved duplicate that the owner has not explicitly chosen to keep both MUST NOT silently double-count. The safe default is manual-only counting until resolution.

## Persistence semantics

Exact SQL table names are implementation details, but the model has three logical concepts.

### Applied provider payout

Month/account/instrument/position scoped applied state containing at minimum:

- provider + provider instrument UID;
- event kind + stable identity key;
- current active lifecycle (`active`, `cancelled`, `dismissed` as needed);
- canonical payment date;
- frozen quantity;
- exact normalized per-unit source amount representation;
- final total integer-kopek amount;
- currency;
- approximation/amount-basis metadata;
- first applied timestamp;
- optional explicit manual reconciliation relation.

One provider identity may be applied separately to two accounts because quantities differ.

A uniqueness invariant MUST prevent duplicate applied copies of the same provider identity within one reporting-month/account/instrument scope.

### Payout revision/provenance

Append-only record on each successful new/revised/cancellation apply containing enough data to audit what the owner accepted:

- applied payout reference;
- revision kind;
- provider identity;
- dates;
- per-unit amount representation;
- frozen quantity;
- final totals;
- relevant provider status/type metadata;
- fetched timestamp;
- applied timestamp.

Do not store full raw provider payloads.

### Manual reconciliation relation

An explicit relation may link one applied provider payout to one manual expected-flow row and record the counting decision. It MUST NOT mutate the manual row merely by creating the link.

## Dashboard semantics

### A. Future cash-flow calendar

The 12-month calendar is the union of:

1. countable manual `expected_cash_flows` for the selected forecast version;
2. countable applied provider payouts for the selected reporting month.

The calendar distinguishes:

- coupon
- dividend
- interest (manual/deposit scope)
- redemption
- other

`total_net` / future cash inflow includes redemption.

`passive_net` excludes redemption.

An active event temporarily `missing_from_provider` remains counted at the last owner-applied value, with a visible warning, because omission is not evidence of cancellation.

Duplicate/reconciliation state determines one vs two countable rows; there must be no hidden accidental double count.

### B. Forecast passive income (C04)

R05 preserves the accepted C04 formula.

- applied provider coupon: eligible to contribute like an expected coupon, subject to duplicate/reconciliation counting rules;
- applied provider dividend: shown in the cash-flow calendar but **does not** replace/add to the C04 dividend component in formula version v1;
- redemption: never contributes;
- actual `investment_cash_flows`: remain separate and do not become expected rows.

A future formula that substitutes announced dividends for some historical-average months requires a separate explicit financial-contract change/version and is outside R05-00.

## Failure model

Provider failures reuse the sanitized 0.4 philosophy.

At minimum distinguish:

- `token_unavailable` / auth failure;
- provider network/timeout/5xx;
- malformed response;
- unsupported event/instrument/currency;
- unmapped/excluded instrument;
- provider data unavailable;
- `preview_changed` on apply.

Mixed-success preview is allowed: one instrument's failure does not discard valid rows from other instruments.

For apply, selected rows are one transaction. A failure in any selected row rolls back the selected set.

Manual expected-flow entry remains available in editable months regardless of provider/token/network state.

Retry is a new explicit owner action only.

## Migration and backward compatibility

0.5 migration MUST be additive/fail-safe.

- Existing `expected_cash_flows` rows remain unchanged and retain current CRUD, unique constraints, `forecast_version`, `source_as_of_date` and semantics.
- Do not backfill existing manual rows into provider identities.
- Do not fetch T-Invest during Alembic upgrade.
- Prefer new provider-payout/revision/reconciliation tables rather than overloading the existing manual-row uniqueness contract.
- Existing calendar/C04 readers may be refactored behind a merged read model, but their accepted financial semantics remain covered by regression tests.
- Existing expected dividends remain ignored by C04 v1.
- Month clone MUST NOT silently copy applied provider payout provenance as if it were newly accepted for the new month. New month's payout state is derived by a new owner-triggered preview/apply against its copied positions.

## FACT vs live-probe gate

### FACT from accepted Hermes 0.4

- T-Invest is the production external provider; `instrument_uid` is canonical.
- T-Invest token is local ignored configuration and never belongs in Git/DB/browser/logs/reports.
- Existing live probe currently calls only accepted read-only instrument/market-data methods.
- Quote preview/apply is explicit-only, no background refresh, T-Invest-only production apply, mixed-success preview, immutable provenance and `preview_changed`.
- Position quantity is local `Decimal` in `PositionSnapshot`.
- Existing expected-flow calendar is 12 months from reporting-month snapshot date.
- C04 uses expected coupon/interest/other plus historical actual dividend component; expected dividends and redemptions are excluded from C04 v1.

### FACT from current official T-Invest InstrumentsService documentation

As checked on 2026-08-16:

- `GetBondCoupons` exists and its request period is filtered by `coupon_date` (coupon payout date).
- `Coupon` documents `coupon_date`, `coupon_number`, optional `fix_date`, `pay_one_bond`, `coupon_type`, `coupon_start_date`, `coupon_end_date`, `coupon_period`.
- `GetDividends` exists and its request period is filtered by `record_date`.
- `Dividend` documents `dividend_net` (amount per security including currency), `payment_date`, `declared_date`, `last_buy_date`, `dividend_type`, `record_date`, `regularity`, `created_at` and other reference fields. `dividend_type` includes `Cancelled` and `Return of Capital` among possible values.
- `GetBondEvents` exists with event types `CPN`, `CALL`, `MTY`, `CONV` and documents `event_number`, event/fix/pay dates, `pay_one_bond`, `execution`, `operation_type`, coupon-period fields and other metadata.
- bond reference data exposes `maturity_date`, `floating_coupon_flag`, `perpetual_flag`, `amortization_flag` and nominal data.

### REQUIRES LIVE READ-ONLY PROBE BEFORE APPLY SEMANTICS ARE FINAL

R05-01 MUST use only read-only InstrumentsService calls (plus already accepted read-only lookup helpers if necessary) and answer, with sanitized public fixtures where useful:

1. Does the owner's read-only token permit `GetBondCoupons`, `GetBondEvents`, and `GetDividends`?
2. What exact REST/SDK field shapes and timestamp representations are observed?
3. Does Moscow date conversion preserve provider-intended financial dates?
4. Is `coupon_number` stable across repeated fetches and common revisions? Do zero/missing numbers occur?
5. How are future floating coupons represented before the amount is fixed (zero, missing, indicative, other)?
6. Does `GetBondEvents(CPN)` duplicate `GetBondCoupons`, and should it remain excluded?
7. How are partial principal amortizations represented in `GetBondEvents`? Are multiple MTY events used, and how do `operation_type`/`value`/`pay_one_bond` behave?
8. For ordinary full maturity, how does MTY `pay_one_bond` relate to current bond nominal?
9. How do explicit cancellations appear for coupons/redemptions, if at all?
10. For dividends, is `payment_date` commonly populated for future declared rows?
11. Can more than one distinct dividend row share one `record_date` for the same instrument?
12. Does `Cancelled` remain in the feed or can cancelled dividends disappear entirely?
13. What operational interpretation is safe for `dividend_net`; no personal-tax assumption may be made without evidence.
14. What request window is needed because `GetDividends` filters by record date while the Hermes calendar filters by payment date?
15. How does an empty schedule appear: successful empty list or an error state?
16. Are instrument UID requests accepted consistently for these methods, or are there legacy FIGI-only behaviors?
17. What bounded sequential/concurrent request pattern is safe for an explicit owner click across the mapped positions of one month?
18. Can a synthetic maturity fallback ever be enabled safely, and under which non-amortizing/non-perpetual constraints?

The live probe MUST NOT call Accounts, Operations, Orders, StopOrders, Sandbox, Transfer or any trading/account endpoint.

CI MUST NOT run live provider requests.

## Follow-up task decomposition

Recommended order:

1. **R05-01 — live read-only T-Invest payout probe + sanitized fixtures.** Close the provider unknowns above before persistence/apply semantics harden.
2. **R05-02 — payout domain contract in code.** Provider-neutral DTO/protocol; identity, coverage, date/amount normalization, statuses, fingerprints; pure deterministic tests.
3. **R05-03 — T-Invest payout adapter.** Implement bounded `GetBondCoupons` / validated redemption path / dividends behind the provider-neutral protocol using sanitized fixtures.
4. **R05-04 — applied payout persistence + append-only revisions/reconciliation schema.** Additive migration only; preserve manual rows.
5. **R05-05 — preview/diff service.** Mixed success, coverage-aware missing, duplicate warnings, zero writes.
6. **R05-06 — selective apply + preview_changed.** Refetch/re-read, atomic selected-set transaction, closed-month guard, immutable revisions.
7. **R05-07 — manual duplicate/reconciliation actions.** Safe default manual-only counting until explicit keep-both/link choice.
8. **R05-08 — calendar + C04 integration.** Merge manual/provider read model; provider coupons can improve C04; provider dividends calendar-only in v1; redemption excluded from passive income.
9. **R05-09 — frontend payout sync/preview/calendar UX.** Explicit button, diff states, warnings, closed read-only presentation.
10. **R05-10 — failure/manual fallback UX.** Sanitized failures, token/network distinction, no background retry.
11. **R05-11 — regression/docs/release gate.** Migration safety, closed-month immutability, duplicate counting, Windows smoke, privacy/network boundary, docs/metadata.

Task numbering MAY be refined in the release backlog without changing this ADR's semantics.

## Rejected alternatives

### Put provider events directly into existing `expected_cash_flows`

Rejected as the primary 0.5 persistence design because the current manual table's uniqueness/version/source semantics are owner-flow oriented. Overloading it creates avoidable collision/overwrite and migration risk. A merged read model is safer than a merged write model.

### Dynamic quantity recomputation on every dashboard read

Rejected because it makes previously owner-applied expected cash silently change after position edits and weakens audit/closed-month reasoning. Quantity is frozen per apply revision; refresh/apply is explicit.

### Auto-delete on provider omission

Rejected. Provider omission is not cancellation and may be caused by request-window semantics or temporary data issues.

### Use mutable dividend type in identity

Rejected because provider lifecycle values such as `Cancelled` could change the identity of the same declared event.

### Invent missing payout dates

Rejected. No `record_date + N` or coupon-period-end payout synthesis in 0.5.

### Change C04 dividend formula implicitly

Rejected. Announced provider dividends improve the cash-flow calendar first. Replacing the historical dividend component requires a separately versioned financial decision.

## References

- issue #35 — R05-00 automatic investment payout calendar contract
- ADR 0010 — market and broker provider strategy
- `docs/t-invest-market-data.md`
- `backend/src/hermes_finance/services/expected_cash_flows.py`
- `backend/src/hermes_finance/services/forecast_passive_income.py`
- `backend/src/hermes_finance/services/quote_apply.py`
- T-Invest official InstrumentsService documentation: `GetBondCoupons`, `GetDividends`, `GetBondEvents`, and instrument messages as checked 2026-08-16.
