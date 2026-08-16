# R05-01 — live read-only T-Invest payout probe

- **Date:** 2026-08-17
- **Task:** issue #39 — R05-01 live read-only T-Invest payout probe + sanitized fixtures
- **Canonical baseline:** `r05 = b4ddea026a79a305bc61c9fe726712ef3065c8be`
- **Worker branch:** `r05-01-grok`
- **Candidate SHA:** `b04ceb4f8a8f2379c10f3246fe53c8b507bde79d`
- **Contract:** `docs/adr/0011-automatic-investment-payout-calendar.md`
- **Mode:** evidence gathering only. No payout calendar, schema, preview/apply or dashboard implementation.

## How the probe was run

Developer-only, explicit `--live`. Token read from ignored repository-root `.env` via `HERMES_FINANCE_T_INVEST_READ_ONLY_TOKEN`. Token, Authorization header and owner account/portfolio data were not printed or stored.

Command (from `backend/`):

```text
uv run python -I -m hermes_finance.market_data.t_invest_payout_probe --live --write-fixture --write-summary <local-untracked-summary>
```

The local summary path is not committed. CI does not run `--live`.

Network reached T-Invest without a VPN retry. Application networking was not changed.

## Methods actually called

Exact allowlisted methods observed on the successful evidence run:

1. `InstrumentsService/FindInstrument`
2. `InstrumentsService/GetInstrumentBy`
3. `InstrumentsService/BondBy`
4. `InstrumentsService/GetBondCoupons`
5. `InstrumentsService/GetBondEvents`
6. `InstrumentsService/GetDividends`

`request_count` on that run: **33** sequential HTTP calls. No fan-out/concurrency.

`forbidden_methods_called`: **empty**.

Not called (and refused by the probe allowlist):

- Accounts / Users account discovery
- Operations / GetPortfolio / GetPositions
- Orders / StopOrders
- Sandbox
- Transfer
- MarketDataService quote methods (`GetLastPrices`, `GetCandles`) — not needed for this payout probe

Production quote routing was not extended. `TInvestClient.request_payout_method()` accepts only `GetBondCoupons`, `GetBondEvents` and `GetDividends`.

## Public instruments used

No owner holdings, account IDs or private DB rows were used.

| Query | What resolved | Role |
|---|---|---|
| `SBER` | first 10 `FindInstrument` hits were all `INSTRUMENT_TYPE_BOND` (corporate-bond tickers, not the share) | failed share lookup |
| `GAZP` | share `GAZP` (`INSTRUMENT_TYPE_SHARE`) | empty `GetDividends` windows |
| `LKOH` | share `LKOH` | historical dividend shape |
| `SU26238` | OFZ bond ticker `SU26238RMFS4` | coupons + MTY |
| `SU29006` | OFZ-PK `SU29006RMFS2` | matured floater (`maturityDate` 2025-01-29) |
| `SU29014` | OFZ-PK `SU29014RMFS6` | matured floater (`maturityDate` 2026-03-25) |

Live UIDs/FIGI/ISIN were not copied into this report. Committed fixture identifiers are synthetic.

## FACT observations

Recorded only from the live read-only REST responses.

### 1. Token / method access

- The configured read-only token **can** call `GetBondCoupons`, `GetBondEvents` and `GetDividends`.
- All three accepted `instrumentId` = `instrument_uid` on the official REST path.

### 2. REST field shape

Observed JSON is **camelCase**.

`GetBondCoupons.events[]` keys seen: `couponDate`, `couponEndDate`, `couponNumber`, `couponPeriod`, `couponStartDate`, `couponType`, `figi`, `fixDate`, `payOneBond`.

`GetBondEvents.events[]` keys seen: `convertToFinToolId`, `couponEndDate`, `couponInterestRate`, `couponPeriod`, `couponStartDate`, `eventDate`, `eventNumber`, `eventTotalVol`, `eventType`, `execution`, `fixDate`, `instrumentId`, `moneyFlowVal`, `note`, `operationType`, `payDate`, `payOneBond`, `value`, and on MTY also `rateDate`.

`GetDividends.dividends[]` keys seen: `closePrice`, `createdAt`, `declaredDate`, `dividendNet`, `dividendType`, `lastBuyDate`, `paymentDate`, `recordDate`, `regularity`, `yieldValue`.

Money/Quotation objects use `{units, nano}` and MoneyValue also has `currency`.

No `dividendGross` field was present on observed dividend rows.

### 3. Timestamps / Moscow date

Observed coupon/event/dividend calendar timestamps were RFC3339 with `T00:00:00Z`.

For every observed date-only midnight-UTC sample, `moscow_calendar_date` equalled the UTC calendar date (`moscow_differs_from_utc_date_count = 0`).

### 4. `coupon_number` stability

On `SU26238` / `GetBondCoupons` (window 2026-07-18 … 2027-09-21):

- 2 rows
- `couponNumber` present on both (`11`, `12`); no missing/zero
- two identical fetches produced the same identity tuples

`couponType` on those rows: `COUPON_TYPE_FIX`. `payOneBond` was positive for both future coupons.

### 5. Floating coupons before fixation

No **future** floating coupon schedule was observed.

`SU29006` and `SU29014` have `floatingCouponFlag=true` but are already past maturity (2025-01-29 and 2026-03-25). After maturity, current `nominal` is a zero MoneyValue while `initialNominal` is non-zero.

Therefore future-floating amount representation (zero vs missing vs indicative) remains **UNRESOLVED**.

### 6. CPN vs `GetBondCoupons`

On the same `SU26238` near window:

- `GetBondCoupons`: 2 rows
- `GetBondEvents(EVENT_TYPE_CPN)`: 2 rows
- shared `payDate`/`couponDate` count: 2
- coupon-only / CPN-only: 0

`GetBondEvents` without type / `EVENT_TYPE_UNSPECIFIED` in the **near** window also returned only those two `EVENT_TYPE_CPN` rows (MTY is outside that window).

This supports ADR 0011: do **not** import `EVENT_TYPE_CPN` in parallel with `GetBondCoupons`.

### 7. Amortization / partial principal

No public amortizing bond with `amortizationFlag=true` and a future maturity was resolved in the bounded extra queries.

`SU26238` has `amortizationFlag=false` and a single `EVENT_TYPE_MTY` when the request window includes maturity.

Partial-amortization representation remains **UNRESOLVED**.

### 8. Ordinary MTY vs Bond nominal

For `SU26238`:

- `BondBy.maturityDate` = 2041-05-15T00:00:00Z
- `GetBondEvents(EVENT_TYPE_MTY)` over a window covering that maturity returned **one** event
- `eventNumber` = 1
- `eventDate` = `payDate` = 2041-05-15T00:00:00Z
- `realPayDate` absent
- `operationType` = `OM`
- `execution` = `E`
- `payOneBond` MoneyValue **matches** `BondBy.nominal` `{units: 1000, nano: 0, currency: rub}`

A near-horizon MTY request that **excludes** 2041 returns an empty `events` list, not an error.

### 9. Coupon/redemption cancellation signals

No cancelled coupon or MTY row was observed.

Observed `execution` on both CPN and MTY was `"E"`. Observed CPN `operationType` on the sanitized fixture is `"Фиксированный"`. MTY `operationType` is `"OM"`. `note` was empty.

Meaning of `E` / `OM` as cancel vs expected vs executed is **UNRESOLVED**.

### 10–13. Dividends

`GetDividends` with `instrumentId` + `from`/`to` succeeded on shares.

`GAZP` windows:

- near 2026-07-18…2027-09-21 → HTTP success, **empty list**
- wide 2026-02-18…2027-09-21 → empty list
- far future 2031-08-16…2031-10-15 → empty list
- history 2024-06-08…2026-08-17 → empty list

`LKOH` history 2024-06-08…2026-08-17 → **4 rows**, all with:

- `paymentDate` present
- `recordDate` present
- `declaredDate` present
- `lastBuyDate` present
- `dividendNet` `{currency, units, nano}`, non-zero
- `dividendType` empty string (not `Cancelled`, not `Regular Cash`)
- no shared `recordDate`
- `paymentDate − recordDate` in **10..15 calendar days** on these 4 rows

No **future** declared dividend (payment after 2026-08-17) was observed in the probed windows.

`GetDividends` on the OFZ bond was **not** an empty list: it failed as `malformed` (unexpected 4xx after `instrumentId`-only retry).

`dividend_net` is a per-security MoneyValue. No tax / withholding / personal-net field was observed. No personal-tax inference is made.

### 14. Fetch window (`record_date` vs `payment_date`)

Official proto says `GetDividends` filters by `record_date`. Observed LKOH rows that have both dates show payment 10–15 calendar days after record.

That is **not** a licence to synthesize `record_date + N`. It is only an observed lag on 4 historical rows of one share.

`GAZP` empty near/wide windows show that a 12-month payment-horizon request can legally return no rows even when the method works.

A later adapter still needs an explicit bounded request window plus coverage metadata (ADR 0011). A universal offset is **UNRESOLVED**.

### 15. Empty schedule appearance

- Share + far-future window: success + `dividends: []`
- Share + `GetBondCoupons`: `malformed` (not an empty coupon list)
- Bond + `GetDividends`: `malformed`
- Bond + MTY window with no maturity inside: success + `events: []`

Empty **list** and **error** both occur; they are not interchangeable.

### 16. `instrument_uid`

All three payout methods accepted REST `instrumentId` set to the T-Invest instrument UID on successful share/bond calls.

`FindInstrument` query `SBER` did **not** surface the share in the first 10 rows; those rows were bonds. Share lookup must not take the first hit blindly.

### 17. Owner-click practicality

33 sequential allowlisted calls completed with the existing 20s/5s/10s timeouts. No retry loop.

A later month-level refresh that does Find+BondBy+coupons+events+dividends per mapped instrument should stay sequential and bounded. This run is not a load test.

### 18. Synthetic maturity fallback

For this non-perpetual, non-amortizing OFZ, BondBy maturity + current nominal **coincided** with the single MTY `payDate` / `payOneBond`.

That is **not** enough to enable a synthetic fallback in product code:

- amortizing bonds were not observed
- perpetual bonds were not observed
- MTY is omitted (empty list) if the request window misses maturity
- `execution`/`operationType` semantics are unknown

ADR 0011 remains: synthetic maturity stays **disabled**.

## UNRESOLVED

1. Future floating-coupon amount before fixation (no live future floater).
2. Partial principal amortization schedule (`amortizationFlag` path not observed).
3. Whether `execution=E` / `operationType=OM` means expected, executed, or something else.
4. Coupon/MTY explicit cancellation, if any.
5. `dividendType=Cancelled` appearance (no cancelled row found).
6. Whether more than one distinct dividend can share one `record_date` (not seen on LKOH’s 4 rows).
7. Whether **future declared** dividends populate `payment_date` before pay day (no future declared row found).
8. Why `GetDividends` on a bond and `GetBondCoupons` on a share are `malformed` rather than empty lists.
9. Safe universal `GetDividends` look-back/look-ahead around a payment horizon; only a 10–15 day historical lag on one name is known.
10. How to discover the SBER *share* via `FindInstrument` when the first page is all SBER bonds.
11. `dividendType` empty vs documented `Regular Cash` — whether empty is normal for RU shares.

## Sanitized fixture

`backend/tests/fixtures/t_invest/official_payout_shape.json`

- synthetic UIDs/tickers/FIGI/ISIN/names only
- representative coupon, CPN, MTY and dividend field shapes
- empty `GetDividends` / `GetBondCoupons` lists
- no token, Authorization, account, portfolio or owner payload
- no full raw provider dump

## Confirmation

- No payout calendar/API/UI/migration was added.
- `origin/r05` was not modified by this worker.
- Forbidden account/trading methods were not called.
- FACT above is only what the live allowlisted REST calls returned.

## Follow-up

R05-02 (domain identity/date/amount/coverage) can now treat as evidence:

- coupon identity `n:{coupon_number}` is viable on the probed OFZ
- CPN is a duplicate of `GetBondCoupons`
- MTY must be requested with a window that covers `maturityDate`
- dividends need share-kind resolution and a wider `record_date` window than the cash calendar
- empty list ≠ error
- synthetic maturity still not enabled
