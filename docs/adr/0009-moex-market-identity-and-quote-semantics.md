# ADR 0009 — MOEX market identity and quote semantics

- **Status:** Accepted
- **Date:** 2026-08-13
- **Task:** R04-01
- **Release:** 0.4.0

## Context

Hermes Finance 0.4 adds the first external read-only market-data integration. The existing model already has `Instrument.isin`, `Instrument.ticker`, `Instrument.moex_secid`, `PositionSnapshot.market_price_per_unit_kopecks`, `price_date`, `price_source=moex` and the invariant that closed reporting months are immutable until explicit reopen.

The integration must not silently invent an exchange identity, overwrite historical values, introduce FX conversion, change existing financial formulas, or treat a bond percentage quote as a RUB cash price.

The Moscow Exchange ISS exposes security/board metadata, current market data and historical trading results. MOEX documents `LAST` as the last-trade price, `PREVPRICE`/`PREVDATE` as the previous trading-session last price/date, `FACEVALUE` and `FACEUNIT`, and `QUOTEBASIS`, where `R` means cash per instrument and `F` means percent of face value. For bonds, historical `LASTPRICE` is documented as percent of face value.

There is also a data-usage constraint: the public ISS documentation describes unauthenticated delayed data, but MOEX usage-policy pages distinguish informational/individual display use from automated loading/processing and other contractual use. Therefore technical implementation may proceed behind an adapter, but production activation and release remain subject to a separate data-usage confirmation gate in §12.

## Decision

### 1. Scope of supported instruments in 0.4

Automatic MOEX quote refresh supports only:

- `stock`;
- `fund`;
- `bond`.

A candidate is eligible only when the quote can be represented in the application's existing RUB per-unit money model without FX conversion.

The following remain manual/unsupported in 0.4:

- `currency`;
- `gold`;
- `other`;
- any stock/fund/bond whose applicable quote or required face-value conversion is not RUB-compatible;
- frozen/unlisted/non-MOEX assets without a valid compatible board mapping.

Unsupported is a normal product state, not a system error. Manual prices remain a first-class workflow wherever `manual_price_allowed` permits them.

### 2. Canonical MOEX identity

`SECID` alone is not sufficient because one security can exist on more than one trading board and board semantics affect the quote.

The logical canonical external identity is:

```text
provider = "moex_iss"
engine
market
boardid
secid
```

For 0.4 the expected compatible market families are:

```text
stock/fund -> engine=stock, market=shares
bond       -> engine=stock, market=bonds
```

`ISIN` remains a validation/discovery attribute, not the whole identity. `ticker` is a human-facing hint, not a normative external key.

If a local instrument has an ISIN and the candidate MOEX security exposes a different ISIN, the candidate is a hard mismatch and must not be persisted automatically.

The existing `moex_secid` field may participate in migration/discovery, but a fully accepted mapping must include the board-aware logical identity above.

### 3. Mapping must be explicit

Discovery may propose candidates; it must not persist a guessed mapping as truth.

Logical mapping states are:

- `unmapped` — no accepted external identity;
- `mapped` — one explicit accepted MOEX identity;
- `excluded` — owner has explicitly disabled external quote refresh for this instrument.

If there are multiple compatible candidates/boards and no already accepted mapping, the result is `ambiguous` and requires owner choice.

An exclusion is reversible. It skips the instrument during refresh without deleting manual values. Implementations may preserve the last mapping while disabled, but disabled state must win over the mapping for refresh eligibility.

Exact persistence shape is owned by R04-03, but it must preserve all logical fields above and must not infer a mapping during migration.

### 4. Refresh is always target-date/as-of, never blindly "now"

Quote refresh targets one reporting month and therefore one valuation date.

Define:

```text
target_date = min(reporting_month.snapshot_date, current_date_in_Europe/Moscow)
```

A MOEX proposal is valid only when:

```text
price_date <= target_date
```

The integration must never apply a later quote to an earlier monthly snapshot.

For a current target trading day:

1. use a valid `LAST` trade on the accepted board when available;
2. otherwise fall back to the latest valid completed trading result on or before `target_date`.

For a historical target date:

1. use the latest valid historical trading-result price on the accepted board on or before `target_date`;
2. never forward-fill from a later day.

The client may search back at most 30 calendar days from `target_date`. If no valid quote exists in that window, status is `unavailable` and the manual price remains unchanged.

`price_date` is the MOEX trading date of the selected quote, not the local HTTP-fetch date and not an invented reporting-month date.

An optional exchange trade time may be returned as preview metadata, but the current persisted snapshot contract remains date-based.

### 5. Freshness policy

Freshness is a presentation/apply policy, not a financial formula.

Define quote age:

```text
age_days = target_date - price_date
```

Classification:

- `0..7` calendar days -> usable;
- `8..30` calendar days -> `stale`;
- older than 30 days -> no proposal / `unavailable`.

This deliberately handles ordinary weekends/holidays without requiring an exchange-calendar dependency in 0.4, while flagging illiquid or suspended instruments.

A stale proposal may be shown, but it is not selected for apply by default and requires explicit per-row owner selection. The UI must display its actual `price_date`.

### 6. Quote field semantics for stocks and funds

For a compatible stock/fund board:

- current-day primary raw field: `LAST`;
- historical raw field: the trading-result last/close value for that board/date, parsed according to the ISS history schema;
- bid/offer midpoint is never synthesized;
- `BID`, `OFFER`, indicative yields and unrelated reference fields are not fallback prices;
- settlement/quote currency must be RUB-compatible for the 0.4 write path.

The raw number is interpreted as cash RUB per one instrument only when the board metadata indicates a cash-per-instrument basis (`QUOTEBASIS=R`) or the applicable MOEX schema for the supported shares market defines the value as a monetary per-instrument price.

Non-positive, non-finite or structurally malformed prices are rejected as `malformed_response`.

### 7. Bond quote conversion is mandatory and exact

MOEX bond prices may be quoted as a percentage of face value. A percentage quote must never be written directly into `market_price_per_unit_kopecks`.

For a RUB bond with:

```text
QUOTEBASIS = F
FACEVALUE = face value of one security
raw_price = percent of face value
```

the proposed clean price per unit is:

```text
clean_price_rub = FACEVALUE * raw_price / 100
```

Conversion uses `Decimal` and the project financial rounding rule `ROUND_HALF_UP`, then stores integer kopecks.

Example with synthetic values:

```text
FACEVALUE = 1000.00 RUB
LAST/LASTPRICE = 97.25
proposed clean price = 972.50 RUB per bond
```

If `QUOTEBASIS=R`, the raw value is cash per instrument and no percentage conversion is performed.

Unknown quote basis, missing face value for `F`, or non-RUB face/settlement semantics -> `unsupported` or `malformed_response`; never guess.

### 8. Accrued interest is deliberately not automated in 0.4

MOEX exposes accrued-interest data, but 0.4 refresh updates only the existing clean `market_price_per_unit` proposal.

It must not silently overwrite `PositionSnapshot.accrued_interest_kopecks`.

Reason: the current snapshot model treats accrued interest as a separate additive value in market-value calculation, and automatically changing it would extend the financial/storage contract beyond the quote-only release.

Therefore for bonds:

- external proposal = clean price per unit;
- existing accrued-interest value remains unchanged;
- UI/provenance must not imply that the MOEX clean quote already includes the locally stored accrued interest.

Automatic accrued-interest sourcing, if wanted later, requires a separate task/contract.

### 9. Numeric parsing

External JSON numeric values must not introduce binary-float financial arithmetic.

Normative boundary rule:

- parse external numeric tokens/values into exact decimal representation immediately;
- if an HTTP/JSON library materializes a Python/JS float first, convert only from its textual representation and never perform financial arithmetic on the binary float;
- all bond conversion and RUB/kopeck conversion uses `Decimal` + `ROUND_HALF_UP`;
- frontend never recomputes the authoritative proposed monetary value.

### 10. Preview and error model

A batch refresh is allowed to partially succeed.

Per-instrument preview status set:

```text
ok
stale
unmapped
excluded
unsupported
ambiguous
unavailable
network_error
malformed_response
```

`ok` and explicitly selected `stale` rows are the only rows eligible for later apply.

One failed instrument must not erase successful proposals for other instruments.

A total transport failure may additionally produce a batch-level error, but local stored data remains unchanged.

No background retry loop, cron, daemon or startup fetch is allowed. Retry is an explicit owner action. R04-02 must use bounded HTTP timeouts and bounded request/concurrency behavior.

### 11. Draft/closed month semantics

Read-only preview may be requested explicitly for a closed month, but it must expose `apply_allowed=false`.

Actual apply:

- is allowed only for a `draft`/explicitly reopened reporting month;
- must pass the existing editable-month guard on the backend write boundary;
- never silently reopens or mutates a closed month.

Mapping is instrument-level reference configuration and may be edited independently of historical month values, but editing mapping never rewrites historical snapshots.

### 12. Data-usage / production-activation gate

Technical architecture and parser work are allowed to proceed before production activation, but the product must not assume that unauthenticated delayed ISS automatically grants every intended automated-use right.

Before R04-06 is accepted for real live apply, and again before 0.4 release, the owner/reviewer must record one of:

1. the applicable MOEX terms/service explicitly permit this local single-user button-triggered usage; or
2. the owner has obtained/accepted the appropriate MOEX information service/terms; or
3. the production provider is changed to another source whose terms permit the intended use.

Until that gate is recorded:

- R04-02 may implement the provider adapter, deterministic parsers, mocked/public synthetic fixtures and a developer-only bounded live probe;
- no startup/background fetch;
- no release claim that live automated MOEX refresh is production-authorized;
- normal stable `main` remains unaffected.

This is a data-source usage gate, not a change to the local-only/no-auth architecture.

### 13. Minimal immutable provenance on apply

Changing an instrument mapping later must not rewrite the meaning of an already applied historical quote.

Every externally applied quote must retain immutable minimal provenance logically equivalent to:

```text
provider = moex_iss (or accepted replacement provider)
engine
market
boardid
secid
raw_price_kind
raw_price_basis
raw_price_decimal
converted_price_kopecks
price_date
fetched_at_utc
position_snapshot_id / target
```

Do not persist the full raw provider payload.

`PositionSnapshot.price_source=moex` and `price_date` remain part of the normal snapshot contract. The exact additional storage representation is deferred to R04-06, but it must be snapshot/apply-specific rather than reconstructed from the instrument's current mapping.

### 14. R04-02 implementation boundary

R04-02 implements only the read-only provider boundary and deterministic parsing. It does **not** add DB migrations, application endpoints, UI, apply logic or snapshot writes.

Required logical operations:

```text
discover_candidates(query / secid / isin) -> candidate identities
fetch_quote(identity, target_date) -> normalized quote result
```

Normalized successful result contains at least:

```text
identity
instrument_kind
raw_price
raw_price_basis
proposed_price_kopecks
price_date
quote_kind
fetched_at_utc
freshness_status
```

The adapter must be replaceable without changing the financial domain/service layer that consumes the normalized DTO later.

### 15. R04-02 minimum regression matrix

Use synthetic/public non-personal fixtures. CI must not depend on live MOEX availability.

Cover at minimum:

1. RUB stock, cash-per-unit quote -> exact kopecks;
2. RUB fund -> exact kopecks;
3. RUB bond, `F` quote -> percent-of-face conversion;
4. bond `R` quote -> cash-per-unit path;
5. missing current `LAST` -> prior valid trading result <= target date;
6. weekend/holiday-like gap <= 7 days -> usable with actual prior `price_date`;
7. 8..30 day gap -> stale;
8. no valid quote in 30 days -> unavailable;
9. ISIN mismatch -> hard rejection of candidate;
10. ambiguous boards -> ambiguous, no silent selection;
11. unsupported/non-RUB semantics -> unsupported;
12. malformed/non-positive quote -> malformed response;
13. timeout/network failure -> deterministic network error;
14. partial batch results do not discard successful rows.

A live developer probe, if implemented, must be opt-in and must not be required by CI.

## Consequences

- R04 remains quote-only and does not grow into FX, accrued-interest automation, cash-flow generation or trading.
- Historical monthly valuation cannot accidentally receive a future quote.
- Bond prices are converted correctly instead of treating a percentage as RUB.
- Mapping ambiguity is owner-visible and never silently persisted.
- Manual/frozen assets remain usable when external data is unavailable.
- The external provider can be replaced if MOEX data-usage terms do not fit the intended production workflow.
- R04-02 can now be implemented without inventing market/financial semantics.

## External basis reviewed for this ADR

Reviewed 2026-08-13 against official Moscow Exchange material:

- MOEX ISS programming interface / delayed market-data description;
- MOEX market-data field descriptions for `LAST`, `PREVPRICE`, `PREVDATE`, `FACEVALUE`, `FACEUNIT`, `QUOTEBASIS` and board/security identity;
- MOEX description of bond historical `LASTPRICE` as percentage of face value;
- MOEX market-data usage policy / individual and automated-use product pages.

External terms are intentionally treated as a release gate because they may change independently of this repository.