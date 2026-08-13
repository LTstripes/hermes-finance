# ADR 0010 — Market-data and broker-data provider strategy

**Status:** Accepted  
**Date:** 2026-08-13  
**Release line:** `r04` / 0.4.x

## Context

R04 originally used MOEX ISS as the primary technical market-data adapter. During the R04 data-usage review, current MOEX materials did not establish that the intended local single-user automated download/process/persist workflow is authorized without an applicable information-service agreement. The direct `moex_iss` adapter therefore remains valid technical work but is not the selected production market-data source for 0.4.

Two official broker APIs were then researched as alternatives: Alfa Investments PRO API and T-Invest API.

The application remains local-only, single-user, Windows, no cloud/auth/telemetry, and external data access remains explicit owner action only.

## Decision

### 1. T-Invest is the selected production market-data provider for 0.4

The production market-data path for 0.4 will use T-Invest API through a dedicated read-only adapter behind the existing `MarketDataProvider` boundary.

Reasons:

- official read-only token exists and cannot submit trading orders;
- token may be restricted to one account;
- remote API works without a desktop terminal running;
- stock, fund/ETF and bond market data are documented;
- historical daily candles support deterministic as-of lookup beyond the 30-day ADR window;
- bond market price semantics are documented as percent of nominal, with nominal and currency available through exact `MoneyValue`/`Quotation` values;
- official materials support downloading/storing market history for private statistics; redistribution/public retransmission remains outside Hermes Finance scope;
- API limits are far above the expected manual monthly refresh load.

Recommended T-Invest identity:

- provider: `t_invest`;
- canonical provider key: `instrument_uid`;
- validation/display attributes: ticker, class_code, ISIN;
- FIGI is not canonical because T-Invest documents it as legacy/deprecated for new integrations.

The current MOEX-shaped identity (`provider + engine + market + boardid + secid`) must not be perpetuated by stuffing T-Invest values into semantically incorrect fields. Before implementing the T-Invest adapter, R04 receives a small provider-neutral identity refactor.

### 2. Alfa PRO remains a planned broker-portfolio provider for Alfa accounts

Alfa PRO is not selected as the primary 0.4 market-data source, but it is retained as a valuable future `BrokerPortfolioProvider` for the owner's Alfa brokerage/IIS data.

Documented useful capabilities include:

- account/subaccount data;
- current positions and quantities;
- accounting/average-price-related fields;
- cash and broker valuation;
- accrued coupon/NKD;
- unrealized P/L;
- identifiers correlating positions with instruments;
- at least partial operation/trade data.

Important Alfa limitations:

- PRO terminal must be installed, running and authenticated during API use;
- API is a localhost WebSocket router (`ws://127.0.0.1:3366/router/`);
- no true API read-only scope is documented; the same socket exposes order methods;
- bond market-data Last/Close unit is not documented clearly enough for authoritative conversion;
- IIS-vs-ordinary-account classification is not documented as an explicit API field;
- private persistence of quotes/account payloads needs confirmation from Alfa under the applicable terms.

For the owner's workflow, launching PRO manually once per month is considered acceptable if it enables local portfolio reconciliation. No Alfa broker import is part of 0.4.

### 3. Market data and broker holdings are separate bounded contexts

A single Hermes instrument may have multiple provider projections.

Example conceptually:

```text
Hermes Instrument
  stable local identity / ISIN / ticker metadata

MarketData mapping
  provider = t_invest
  provider instrument key = instrument_uid
  -> current/historical market quote

BrokerPortfolio mapping
  provider = alfa_pro
  provider account/instrument identifiers
  -> actual account, position, quantity, broker valuation, NKD, cash
```

The market provider and broker provider must not be forced to share one identity schema.

Future broker integrations should use a separate boundary, e.g. `BrokerPortfolioProvider`, with provider-specific adapters such as:

- `AlfaProBrokerPortfolioProvider`;
- `TInvestBrokerPortfolioProvider`.

T-Invest broker data may later support T-Invest accounts, but it cannot read Alfa accounts; Alfa PRO cannot read T-Invest accounts.

## Provider-neutral identity requirement

The accepted R04-03 mapping schema was designed around MOEX board identity. That assumption is now too narrow.

Before the T-Invest adapter is implemented:

1. introduce a provider-neutral canonical market identity contract;
2. preserve explicit owner mapping and no-silent-auto-map behavior;
3. preserve existing MOEX mappings without fabricating T-Invest mappings;
4. keep ISIN/ticker/class-code-like values as validation/discovery/display metadata, not necessarily the canonical provider key;
5. keep R04-04 preview and R04-05 UI behavior provider-neutral;
6. do not use field-name aliases that duplicate T-Invest `class_code` into both `market` and `boardid` merely to satisfy the old schema.

The exact storage shape is an implementation decision for the dedicated identity-refactor task, but it must represent both:

- MOEX ISS board-aware identity;
- T-Invest `instrument_uid` identity;

without semantic lying.

## R04 sequence after this decision

The active development sequence is:

1. **R04-05A — provider-neutral market identity refactor**;
2. **R04-05B — T-Invest read-only market-data adapter**;
3. read-only live probe with owner-generated T-Invest read-only token, if available;
4. **R04-06 — explicit selective apply + immutable provenance**;
5. later R04 polish/regression/release tasks.

R04-06 must not start before the production market adapter contract is integrated.

## Security decisions

### T-Invest

- Hermes Finance must use a **read-only** T-Invest token only;
- never request/store a full-access or transfer-capable token for market refresh;
- token must never be committed, logged or included in fixtures/reports;
- credential storage is local-only and outside tracked repository data;
- no order/transfer API is implemented by the market adapter.

### Alfa PRO

If/when a broker adapter is implemented:

- implement read/query channels only;
- do not implement `#Order.Enter.Query`, `#Order.Cancel.Query` or other trading mutations;
- localhost-only transport does not replace the missing provider-level read-only scope, so this limitation remains explicit;
- broker data must go through reconciliation/preview before changing Hermes monthly snapshots.

## Data ownership and persistence

- T-Invest market data may be used as the selected private market source under the researched official API/storage model; no redistribution/public service is introduced.
- Direct MOEX ISS production use remains gated unless an applicable agreement/permission is recorded.
- Alfa private persistence remains `NEEDS_CONFIRMATION` before a production broker-data import is accepted.
- External data never silently overwrites a monthly snapshot.

## Consequences for existing R04 work

- R04-02 MOEX provider remains as an adapter/reference implementation, but not the selected production source.
- R04-03 mapping needs provider-neutral evolution before T-Invest implementation.
- R04-04 preview service remains conceptually reusable because it consumes the provider boundary.
- R04-05 mapping/preview UI remains conceptually reusable; labels/forms may need identity-shape adjustments.
- R04-06 apply/provenance remains deferred until R04-05A/R04-05B are integrated.

## Research summary

### Alfa PRO probe

Decision: **CONDITIONAL GO** as a combined technical source; retained primarily as future broker-data provider.

Key unresolved points: no read-only scope, required running terminal, bond quote unit ambiguity, persistence terms confirmation, IIS classification, no live probe yet.

### T-Invest probe

Decision: **GO — primary market provider** and **GO — future broker provider for T-Invest accounts**.

Key characteristics: official read-only token, remote API, deterministic stock/fund/bond market semantics, historical as-of capability, local storage evidence, account/IIS/positions/operations APIs, no terminal dependency.

## References

- ADR 0009: `docs/adr/0009-moex-market-identity-and-quote-semantics.md`
- MOEX gate record: GitHub issue #24
- T-Invest developer portal: `https://developer.tbank.ru/invest`
- T-Invest token docs: `https://developer.tbank.ru/invest/intro/intro/token`
- T-Invest market-data docs: `https://developer.tbank.ru/invest/services/quotes/head-marketdata`
- T-Invest market-data FAQ/bond semantics: `https://developer.tbank.ru/invest/services/quotes/faq_marketdata/`
- T-Invest historical data: `https://developer.tbank.ru/invest/intro/intro/load_history`
- T-Invest official API/SDK repository: `https://github.com/RussianInvestments/investAPI`
- Alfa PRO product page: `https://alfabank.ru/make-money/investments/pro-terminal/`
- Alfa Investments PRO API v2.1 PDF: `https://alfadt.servicecdn.ru/alfadt/ad5/Alfa-Investments-Pro-API.pdf`
- Alfa brokerage regulation index: `https://alfabank.ru/make-money/investments/help/docs/`

## Non-goals

This ADR does not implement:

- T-Invest adapter;
- Alfa broker import;
- T-Invest broker import;
- account reconciliation;
- quote apply;
- order/trading functionality;
- background synchronization.
