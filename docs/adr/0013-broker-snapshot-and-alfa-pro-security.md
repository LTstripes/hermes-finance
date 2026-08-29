# ADR 0013 — Broker snapshot boundary and Alfa PRO security

**Status:** Accepted  
**Date:** 2026-08-19  
**Release line:** `r06` / 0.6.x  
**Task:** R06-02 / issue #74

## Context

ADR 0010 retained Alfa Investments PRO as a future broker-portfolio source but left the production boundary unresolved pending a live probe. R06-01 has now provided owner-only sanitized live evidence against Alfa PRO 5.26.5.572.

The useful observed path is a current-state broker snapshot, not a complete broker ledger:

- the local router at `ws://127.0.0.1:3366/router/` was reachable only while PRO was running;
- `#ConnectionState.Bus` produced `AuthStatus=2`; this is the usable authentication gate on the observed terminal;
- `ReadyToSign=true` was observed, proving that the terminal session can be trading-capable even while Hermes intends to read only;
- bus-gated allowlisted client reads returned accounts, subaccounts, sections, balances, positions and instrument metadata;
- all 29 observed positions had ISIN and complete observed account/subaccount/section/object references;
- observed snapshot data exposed quantity, broker valuation/price, accounting-price fields, NKD/accrued-interest fields and unrealized-result fields;
- provider identifiers for the observed accounts, subaccounts, instruments and operations were stable across one clean PRO restart;
- the bounded `ClientOperationEntity` initial load contained only three rows dated 2026-08-18 through 2026-08-19; this does not establish complete historical retention;
- the observed operation type values were numeric (`3`, `14`) while API v2.1 describes `IdOperationType` with the symbolic example `TRD`; their semantics are not accepted;
- a foreign web `Origin` could complete the local WebSocket handshake in the handshake-only test; no commands were sent from that test;
- no raw owner payload was persisted or printed and no trading method was invoked.

There is also a current-terminal compatibility fact: both tested ConnectionState `#Data.Query` request shapes returned undocumented SubscribeResponse error code `6`. The production auth gate therefore must not depend on those requests or guess the meaning of code `6`.

The product remains local, single-user and monthly. A CLOSED reporting month remains immutable until explicit reopen. External broker data must never silently overwrite Hermes data.

## Decision

### 1. Introduce a dedicated `BrokerSnapshotProvider` boundary

0.6 defines a provider-neutral read-only boundary for **current broker state**.

Conceptually:

```text
BrokerSnapshotProvider
    fetch_snapshot()
        -> BrokerSnapshot

BrokerSnapshot
    provider
    source_as_of
    accounts[]
    positions[]
    cash_balances[]
    warnings[]
    provenance
```

The exact Python DTO names may vary in R06-03, but the semantics are normative:

- a snapshot is an observation of current provider state at a known `source_as_of` time;
- it is not a reporting month by itself;
- it is not an authoritative historical transaction ledger;
- it performs no writes to Hermes persistence;
- it performs no reconciliation or apply by itself.

`MarketDataProvider`, `BrokerSnapshotProvider`, and future `BrokerStatementImporter` remain separate bounded contexts.

### 2. Alfa PRO authentication is bus-gated and fail-closed

The Alfa adapter must establish the session in this order:

1. connect only to the approved loopback router;
2. `listen` to `#ConnectionState.Bus`;
3. wait within a bounded overall deadline, treating a per-receive timeout as idle rather than successful completion;
4. observe `AuthStatus` from the bus;
5. issue client-data reads only after an actually observed `AuthStatus == 2`;
6. if status is missing, changes away from `2`, the socket fails, or the deadline expires, stop and return a non-applicable failure/unavailable result.

The adapter must **not** use ConnectionState `#Data.Query` as the production auth gate on the current compatibility contract. It must not translate undocumented error code `6` into an authentication state.

If authentication becomes non-`2` while a snapshot is being collected, the collection is not eligible for apply. A partial snapshot may be surfaced diagnostically only if it remains sanitized and clearly marked non-applicable.

### 3. Read-only safety is structural, not credential-scoped

No separate provider-level read-only credential/scope has been established for the observed PRO integration. The same authenticated terminal can be ready to sign trading instructions. Therefore Hermes read-only safety must exist **by construction**.

The production Alfa snapshot adapter must have:

- no public generic `send(channel, payload)` interface;
- a closed allowlist of router commands and channels;
- `request` only to `#Data.Query`;
- `listen` / `unlisten` only for explicitly approved data buses;
- a hard runtime rejection for every `#Order.*` channel before any send;
- no order, limit, cancel, transfer, signing, certificate-management or mutation DTO/service/helper;
- source-level and deterministic tests that keep the trading surface absent;
- sanitized errors that never dump provider frames or payloads.

`ReadyToSign` is observation-only. Hermes must never try to change it, create/sign certificates, or make snapshot reads contingent on manipulating signing state.

### 4. Minimize the production snapshot entity surface

R06-01 used a wider evidence surface. The production snapshot provider is narrower.

Approved snapshot entities are limited to the data required for current state:

- `ClientAccountEntity`;
- `ClientSubAccountEntity`;
- `SubAccountRazdelEntity`;
- `ClientPositionEntity`;
- `ClientBalanceEntity`;
- `AssetInfoEntity`, bounded to the provider object IDs needed by observed positions where possible.

`ClientOperationEntity` is **not part of the production snapshot contract** and must not be queried by default in R06-03. Its R06-01 use was evidence gathering only.

Order entities, order book, trade tape, archive/candles, trading limits, order services and all other non-allowlisted surfaces are outside this adapter.

Each live fetch is one-shot, bounded and owner-initiated. It must unlisten/close after collection and must not maintain or renew long-lived subscriptions in the background.

### 5. Snapshot financial values are observations with explicit semantics

The provider-neutral snapshot may expose, when available:

- position quantity;
- provider/broker unit price or valuation input;
- provider-reported market value;
- accounting/average-cost-related unit price;
- accrued interest / NKD;
- unrealized result;
- cash balance by account/subaccount/currency;
- provider field/source metadata required to explain provenance.

R06-03 must document and test the exact Alfa raw-field mapping before a field is promoted into one of these normalized semantics. A field name alone is not sufficient evidence of meaning.

Provider-reported market value and a Hermes-derived value must not silently replace one another. Reconciliation may compare them, but provenance must preserve which value came from the broker and which was calculated by Hermes.

Alfa values observed as JSON numbers must cross the provider boundary into exact domain representations without binary floating-point financial arithmetic. Financial amounts/prices/rates use `Decimal` or exact minor-unit representations according to existing Hermes rules; quantities also use a decimal-safe representation where the provider permits non-integer values. R06-03 must not build financial domain values from a binary `float` round-trip.

### 6. Hermes identity remains canonical; Alfa identity is a provider projection

A provider identifier is useful correlation metadata, not Hermes canonical identity.

For instruments:

- Hermes local `instrument_id` remains canonical inside the product;
- ISIN is the preferred cross-provider external identity when present;
- Alfa `IdObject` and related provider IDs may be retained as Alfa provenance/mapping metadata only under the persistence gate below;
- ticker/name are discovery/display hints and must not create a silent mapping;
- the observed `29/29` ISIN coverage is positive evidence for this strategy, not a permanent provider guarantee.

For accounts:

- Alfa account/subaccount/section IDs are provider identities;
- mapping to Hermes `accounts` is explicit owner-controlled mapping;
- one clean-restart stability observation is useful evidence but not a promise of stability across terminal upgrades, reinstallations, broker migrations or provider data resets;
- missing/changed provider identity must produce a reconciliation conflict, not silently remap an account.

### 7. IIS classification remains owner-controlled until semantics are accepted

R06-01 observed an `IIAType` field in live `ClientAccountEntity` field names, but Alfa PRO API v2.1 does not document that field or its values. Therefore its semantic meaning is `UNRESOLVED`.

Hermes must not infer IIS from:

- `IIAType` until an official accepted mapping exists;
- account numbers/codes;
- names or text substrings;
- section names/codes.

The existing Hermes account type / IIS profile remains the source of truth through explicit owner mapping. A later narrow ADR/task may accept an official provider mapping if evidence becomes available.

### 8. Reconciliation preview is mandatory before persistence/apply

The flow is:

```text
Alfa PRO
  -> AlfaProBrokerSnapshotProvider
  -> immutable in-memory BrokerSnapshot
  -> reconciliation preview
  -> owner selects/accepts changes
  -> selective apply
```

There is no direct provider-to-database write path.

Preview must surface at least:

- matched/unmatched accounts;
- matched/unmatched instruments;
- provider-only and Hermes-only positions;
- quantity differences;
- cash differences;
- provider valuation/accounting-price/NKD/unrealized differences where supported;
- source timestamp and provider provenance;
- incomplete/error/truncation state.

No missing provider row may silently delete a Hermes position. No provider-only row may silently create or map an instrument/account.

Any future apply is explicit, selective and transactional. A CLOSED reporting month cannot be changed by broker sync; the owner must explicitly reopen it first under the existing month lifecycle rules.

### 9. Current snapshot and historical broker ledger are deliberately separated

`ClientOperationEntity` must not be treated as the source of truth for payouts, taxes, commissions, deposits, withdrawals or complete historical activity.

Reasons:

- the official v2.1 entity is described as operations/trades;
- the live bounded initial load was only three rows over two dates;
- no accepted date-filter/pagination/retention contract has been established;
- live numeric operation type IDs `3` and `14` have no accepted official mapping in this ADR;
- the same short observed operation set surviving one restart proves only restart persistence of that observed set, not historical completeness.

Historical cash activity therefore belongs to a separate future `BrokerStatementImporter` based on broker reports/statements or another later accepted authoritative contract.

R06-03 must not write `ClientOperationEntity` rows into `investment_cash_flows`.

### 10. Browser/frontend must never proxy the Alfa router

The foreign-Origin handshake acceptance from R06-01 is a threat-model fact, not by itself a vulnerability finding.

Consequences for Hermes are normative:

- Alfa WebSocket communication occurs only in backend/server-side code;
- the frontend never receives a raw Alfa WebSocket URL, generic channel proxy, raw provider frame or provider credential/session primitive;
- a future UI may expose only a high-level explicit owner action such as “read broker snapshot” and a sanitized reconciliation result;
- localhost request-security protections remain governed by ADR 0004;
- broker sync must not create a browser-accessible generic tunnel to local trading services.

### 11. Persistence is gated and minimized

Raw Alfa frames/payloads are never persisted as a normal product feature and are never logged.

The legal/terms basis for persistent storage of Alfa private API-derived broker data remains `NEEDS_CONFIRMATION`. Until that gate is explicitly resolved:

- R06-03 may implement transient read-only acquisition and normalized in-memory DTOs;
- R06-04 may implement in-memory reconciliation/preview;
- persistence of provider IDs/mappings or selected Alfa-derived snapshot values must not silently become accepted merely because the technical adapter works;
- R06-05 selective apply is blocked from release acceptance if the required persistence permission remains unresolved.

If persistence becomes accepted, store only the minimum normalized/provenance fields required for owner mapping, reconciliation and audit. Do not store raw provider payloads “for debugging”.

### 12. Compatibility failures are explicit; no speculative protocol fallback

The PRO terminal updates automatically and API documentation may lag observed terminal behavior. Therefore compatibility failures must fail safely.

The adapter must not respond to undocumented errors by trying arbitrary request shapes/channels. New compatibility behavior requires:

- official documentation/example evidence or a deliberately bounded owner-only probe;
- synthetic tests;
- independent review when the network/security boundary changes.

Observed code `6` remains an opaque provider SubscribeResponse code in this architecture.

## Provider-neutral status expectations

R06-03 may choose exact class/enum names, but callers must be able to distinguish at least:

- successful complete snapshot;
- provider unavailable / terminal not running;
- authentication unresolved or not authorized;
- compatibility/protocol error;
- partial/incomplete snapshot;
- malformed provider response.

A partial/incomplete snapshot is not eligible for selective apply unless a later contract explicitly defines safe field-level applicability. Required snapshot entity errors, truncation or loss of authenticated state fail closed.

## Consequences

### Positive

- Alfa can provide a useful current portfolio snapshot without becoming a trading integration.
- The provider boundary is reusable for future brokers.
- Current holdings stay separate from historical cash-flow truth.
- ISIN-led reconciliation fits the observed live portfolio well without trusting provider IDs as canonical.
- A malicious/accidental caller cannot select an arbitrary Alfa router channel through the adapter.
- Preview and CLOSED-month rules prevent silent historical rewrites.

### Costs / limitations

- PRO must be running and authenticated for each explicit owner sync.
- `ReadyToSign` may be true; provider-level least privilege is therefore weaker than T-Invest read-only-token integrations.
- IIS classification remains manual/owner-mapped.
- provider-ID stability beyond the observed restart is not guaranteed.
- operation-history completeness and operation-type semantics remain unresolved.
- persistence/legal permission remains a release gate for applying Alfa-derived data.
- automatic/background sync is deliberately not part of this contract.

## R06 implementation sequence after this ADR

1. **R06-03 — Alfa PRO snapshot adapter**: transient, read-only, bus-auth-gated implementation of this boundary; no persistence/apply.
2. **R06-04 — snapshot reconciliation + preview**: explicit account/instrument mapping and diff; still no silent apply.
3. **R06-05 — selective apply + provenance**: only after the persistence/legal gate is resolved and with CLOSED-month protection.
4. **R06-06+ — statement/report feasibility and importer** for historical payouts/taxes/commissions/deposits/withdrawals.

## Unresolved items

- official semantics/value mapping of live `ClientAccountEntity.IIAType`;
- official semantics/value mapping of live numeric `ClientOperationEntity.IdOperationType` values such as `3` and `14`;
- complete operation-history retention/pagination contract;
- read behavior with naturally occurring `ReadyToSign=false`;
- behavior while terminal is unauthenticated/offline and during reconnect beyond the documented state model;
- persistent-storage permission/terms for Alfa-derived private broker data (narrowly addressed for owner-confirmed mapping identity, selected quantity, and baseline provenance by [ADR 0016](0016-owner-approved-alfa-baseline-and-broker-mappings.md); raw payloads remain forbidden);
- provider-ID stability across terminal upgrades/reinstall/provider-side migrations.

These are recorded as unknowns and must not be guessed by R06-03.

## Relationship to ADR 0010

ADR 0010 remains accepted for the broader market-data versus broker-data provider strategy. This ADR supersedes its Alfa-specific “future broker provider” uncertainty where R06-01 now supplies live evidence and defines the normative 0.6 snapshot/security boundary.

## Relationship to ADR 0016

ADR 0016 is the contract-first follow-up for persistent broker-identity mappings and an owner-approved current-state quantity baseline. Until its implementation slices land, production mapping remains request-scoped and transient as specified here. ADR 0016 does not reopen trading channels, operation-history import, or raw-payload persistence.

## References

- ADR 0004 — localhost request security: `docs/adr/0004-localhost-request-security.md`
- ADR 0010 — market-data and broker-data provider strategy: `docs/adr/0010-market-and-broker-provider-strategy.md`
- R06-01 issue #71 and accepted owner-live evidence
- R06-01 sanitized probe review: `docs/reviews/2026-08-19-r06-01-alfa-pro-live-probe.md`
- Alfa Investments PRO product page: `https://alfabank.ru/make-money/investments/pro-terminal/`
- Alfa Investments PRO WebSocket API v2.1: `https://alfadt.servicecdn.ru/alfadt/ad5/Alfa-Investments-Pro-API.pdf`

## Non-goals

This ADR does not implement:

- the production Alfa adapter;
- database schema/migrations for broker mappings/provenance;
- reconciliation/apply code;
- UI/API endpoints;
- statement/PDF parsing;
- operation-type interpretation;
- trading/order/signing functionality;
- background synchronization.
