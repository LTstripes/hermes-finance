# R06-01 — bounded read-only Alfa PRO live probe

- **Task:** issue #71 — Phase A tooling + owner-only Phase B live evidence
- **Frozen task baseline:** `1acef7a05af1340197b2b2cd870dfa3542c4039a`
- **Worker branch:** `r06-01-grok`
- **Candidate SHA:** fill after the task-branch commit
- **Official API:** Alfa Investments PRO WebSocket API v2.1  
  `https://alfadt.servicecdn.ru/alfadt/ad5/Alfa-Investments-Pro-API.pdf`
- **Mode:** evidence gathering only. No `BrokerPortfolioProvider`, persistence, API/UI, apply, PDF importer, background sync, or trading.

Phase A implements the probe and deterministic tests. Phase B is owner-only. This document is the sanitized evidence template; live FACT lines stay `unresolved` until the owner run.

## Owner live-run (Phase B)

Do this only after independent review of the exact candidate SHA.

1. Copy or check out that SHA into an **owner-controlled temporary probe workspace**.
2. Keep that workspace outside every agent development clone and outside the production runtime clone.
3. Do not copy `.env`, `finance.db`, backups, exports, or private files into an agent clone.
4. Start Alfa PRO, log in, leave the terminal running. Hermes does not supply credentials.
5. From the workspace `backend/` directory, using the frozen lockfile:

```text
uv run --locked python -m hermes_finance.alfa_pro_probe --live
```

6. Handshake-only check (no client-data queries). Default Origin is the unrelated web origin `https://example.invalid`:

```text
uv run --locked python -m hermes_finance.alfa_pro_probe --live --origin-handshake-only
```

Do not use a loopback Origin for this check. `--origin` may override only to another non-loopback http(s) web origin.

7. Optional second `--live` run after a clean PRO restart, with an owner-only compare file **outside** the repository/workspace:

```text
uv run --locked python -m hermes_finance.alfa_pro_probe --live --id-compare-store <outside-repo-file>
```

Run the same command twice (before and after restart). Stdout emits only `stable|changed|mixed|unresolved`. Do not paste, commit, or copy the compare file back to an agent clone.

8. If PRO can naturally sit at `ReadyToSign=false` without changing account permissions or sending trading commands, run `--live` in that state too. If not, leave `read_with_ready_to_sign_false: unresolved`.
9. Paste only the printed sanitized block into this file. Do not keep raw frames, logs, payloads, or ID-compare store contents.

CI must not pass `--live`. The probe writes nothing to the Hermes database, backups, exports, or repository files.

Missing PRO should fail calmly with `connection: fail`. Observed `AuthStatus` other than `2` is `authenticated_read: fail`, and client account/position/history queries are not sent. If the WebSocket connected but `AuthStatus` was never observed, `authenticated_read` and `auth_status` stay `unresolved`; that is not proof the terminal user session is unauthenticated. SubscribeResponse error codes are printed numerically only; official API v2.1 documents router codes 0 and 5, not SubscribeResponse codes, so do not translate them.

If a query errors or operation history hits the personal cap (2000 rows; other entities 500), history-depth dates stay `unresolved` and `collection_truncated` / `entity_query` say so.

ConnectionState acquisition (read-only, before any client-data query):

1. `listen` `#ConnectionState.Bus`.
2. Documented API v2.1 §4 request: `#Data.Query` payload `{Init: true, Subscribe: true}` (no `Type`). Keep this request as evidence even if it errors.
3. Bounded drain; bus broadcasts may supply `AuthStatus` without proving the Init query succeeded.
4. Only if `AuthStatus` is still missing: one compatibility `#Data.Query` using official SubscribeRequest fields (API v2.1 §3.3) with `Type: ConnectionState` plus `Init`/`Subscribe`. This is not a translation of any error code.
5. Client account/position/history queries remain blocked until `AuthStatus=2` is actually observed.

## Channels the probe may send

Allowlisted only:

- router `listen` / `unlisten` on `#ConnectionState.Bus` and `#Data.Bus.<allowlisted entity>`
- router `request` on `#Data.Query`

Allowlisted entities:

- `ClientAccountEntity`
- `ClientSubAccountEntity`
- `SubAccountRazdelEntity`
- `ClientPositionEntity`
- `ClientBalanceEntity`
- `ClientOperationEntity` (personal-history cap 2000)
- `AssetInfoEntity` (position `IdObject` keys only, bounded)

Hard-denied at send time: every channel whose name starts with `#Order.`, including the documented trading channels. There is no public generic `send(channel, payload)`.

Not implemented and not queried: archive/candles, order book, trade tape, order entities, limit/enter/cancel, signing.

Default endpoint: `ws://127.0.0.1:3366/router/`. Non-loopback hosts are rejected before connect.

## Sanitized evidence (fill only after owner live run)

```text
alfa_pro_version: unresolved
api_doc_version: 2.1
connection: unresolved
authenticated_read: unresolved
auth_status: unresolved
auth_status_source: unresolved
ready_to_sign_observed: unresolved
collection_truncated: unresolved
routing_error: unresolved
routing_error_code: unresolved

accounts_count: unresolved
subaccounts_count: unresolved
razdels_count: unresolved
iis_explicitly_classifiable: unresolved
subaccounts_with_account_ref: unresolved
razdels_with_account_ref: unresolved
razdels_with_subaccount_ref: unresolved

positions_count: unresolved
positions_with_isin: unresolved
positions_with_account_ref: unresolved
positions_with_subaccount_ref: unresolved
positions_with_razdel_ref: unresolved
positions_with_object_ref: unresolved
cash_balance_entities_count: unresolved
snapshot_fields: []

operations_count: unresolved
oldest_operation_date: unresolved
newest_operation_date: unresolved
observed_operation_types: []
non_trade_ledger_events_observed: unresolved

ids_after_restart:
  accounts: unresolved
  subaccounts: unresolved
  instruments: unresolved
  operations: unresolved

read_with_ready_to_sign_false: unresolved
foreign_origin_websocket_handshake: unresolved

raw_payload_saved: no
private_values_printed: no
trading_methods_invoked: no
```

Record `FACT` only from the owner live run. Otherwise leave `UNRESOLVED`. Do not guess IIS from account numbers, names, or field-name substrings. Do not copy raw IDs, holdings, quantities, balances, prices, JSON, or ID digests. Do not guess SubscribeResponse error-code meanings.

## Previous owner live SHA (not this candidate)

Reviewed live SHA `2f7b75da4e864c3f63f0a69190e444128e81d504` on Alfa PRO **5.26.5.572**, owner UI session with live market data and portfolio visible:

- `connection: pass`
- documented ConnectionState `#Data.Query` `{Init:true, Subscribe:true}`: `ConnectionState=error`, provider code `6`
- `AuthStatus` not observed
- `authenticated_read: fail` on that SHA must not be read as “user is unauthenticated”
- no client account/position/history rows were read
- `routing_error: no`
- foreign Origin handshake: `accepted`
- trading methods invoked: `NO`

Do not run restart-ID comparison until provider IDs have actually been collected. Do not change ReadyToSign or trading/signing settings for this investigation.

## Live questions (issue #71)

A–H remain unanswered until a new independent review ACCEPT and a new owner live run of this candidate. Phase A does not observe Alfa PRO.

## Privacy

- No real Alfa credentials, account IDs, or owner portfolio data in this repository.
- Synthetic fixture: `backend/tests/fixtures/alfa_pro/synthetic_read_only.json`.
- Default live stdout is counts, dates, field names, relationship coverage, query status, and state labels only.
- Do not commit live transcripts or `--id-compare-store` files.
