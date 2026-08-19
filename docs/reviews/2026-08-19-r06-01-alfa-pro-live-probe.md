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

6. Bounded `#ConnectionState.Bus` observer. No `#Data.Query`, no client account/position/history queries. Overall window is `--deadline` (default 30s). `--read-timeout` only bounds one idle recv; it does not end the run:

```text
uv run --locked python -m hermes_finance.alfa_pro_probe --live --connection-state-bus-only
```

If a bus broadcast carries `AuthStatus`, stdout has `auth_status`, `auth_status_source: bus`, and `ready_to_sign_observed`. If the overall deadline elapses with no AuthStatus, those fields stay `unresolved` (not `fail`).

7. Bus-gated client read. Waits for `AuthStatus=2` from `#ConnectionState.Bus` (idle read timeouts do not end that wait). Only then sends the existing allowlisted client entity `#Data.Query` reads. No ConnectionState `#Data.Query`. ReadyToSign is observed only.

```text
uv run --locked python -m hermes_finance.alfa_pro_probe --live --bus-gated-client-read
```

If AuthStatus is missing or not `2` by the overall deadline, no account/position/history queries are sent.

8. Handshake-only check (no client-data queries). Default Origin is the unrelated web origin `https://example.invalid`:

```text
uv run --locked python -m hermes_finance.alfa_pro_probe --live --origin-handshake-only
```

Do not use a loopback Origin for this check. `--origin` may override only to another non-loopback http(s) web origin.

9. Optional second `--live --bus-gated-client-read` run after a clean PRO restart, with an owner-only compare file **outside** the repository/workspace:

```text
uv run --locked python -m hermes_finance.alfa_pro_probe --live --bus-gated-client-read --id-compare-store <outside-repo-file>
```

Run the same command twice (before and after restart). Stdout emits only `stable|changed|mixed|unresolved`. Do not paste, commit, or copy the compare file back to an agent clone.

10. If PRO can naturally sit at `ReadyToSign=false` without changing account permissions or sending trading commands, run `--bus-gated-client-read` in that state too. If not, leave `read_with_ready_to_sign_false: unresolved`.
11. Paste only the printed sanitized block into this file. Do not keep raw frames, logs, payloads, or ID-compare store contents.

CI must not pass `--live`. The probe writes nothing to the Hermes database, backups, exports, or repository files.

Missing PRO should fail calmly with `connection: fail`. Observed `AuthStatus` other than `2` is `authenticated_read: fail`, and client account/position/history queries are not sent. If the WebSocket connected but `AuthStatus` was never observed, `authenticated_read` and `auth_status` stay `unresolved`; that is not proof the terminal user session is unauthenticated. SubscribeResponse error codes are printed numerically only; official API v2.1 documents router codes 0 and 5, not SubscribeResponse codes, so do not translate them.

If a query errors or operation history hits the personal cap (2000 rows; other entities 500), history-depth dates stay `unresolved` and `collection_truncated` / `entity_query` say so.

ConnectionState acquisition:

On Alfa PRO 5.26.5.572, `#ConnectionState.Bus` observed `AuthStatus=2` in the bus-only owner run. Both ConnectionState `#Data.Query` shapes returned undocumented code `6`; do not add more request shapes and do not use them as the auth gate.

`--bus-gated-client-read` is the current-terminal evidence path: `listen` `#ConnectionState.Bus` only until `AuthStatus=2` or the overall deadline, treating per-recv timeout as idle. Client account/position/history `#Data.Query` is sent only after that observed `2`. ReadyToSign is observation-only.

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

Alfa PRO **5.26.5.572**, owner UI session with live market data and portfolio visible.

`2f7b75da4e864c3f63f0a69190e444128e81d504`:

- `connection: pass`
- documented typeless ConnectionState `#Data.Query`: error code `6`
- `AuthStatus` not observed
- `authenticated_read: fail` on that SHA must not be read as “user is unauthenticated”
- no client account/position/history rows were read

`d6025849cf5d908e992f5b3c4818eda8c46abbe2`:

- `connection: pass`
- `authenticated_read: unresolved`
- `auth_status: unresolved`
- documented typeless ConnectionState `#Data.Query`: error code `6`
- typed `Type=ConnectionState` fallback: error code `6`
- no `AuthStatus` from `#ConnectionState.Bus` during that bounded run
- no client account/position/history queries
- `routing_error: no`
- trading methods invoked: `NO`

`97e0be8a22809f877793d7c982bdff9015093060` (`--connection-state-bus-only`):

- `connection: pass`
- `auth_status: 2`
- `auth_status_source: bus`
- `ready_to_sign_observed: true`
- `#ConnectionState.Bus` usable; no `#Data.Query`; no client-data queries
- trading methods invoked: `NO`

Do not infer unauthenticated state from code `6`. Do not run restart-ID comparison until provider IDs have actually been collected. Do not change ReadyToSign or trading/signing settings for this investigation.

## Live questions (issue #71)

A–H remain unanswered until a new independent review ACCEPT and a new owner live run of this candidate. Phase A does not observe Alfa PRO.

## Privacy

- No real Alfa credentials, account IDs, or owner portfolio data in this repository.
- Synthetic fixture: `backend/tests/fixtures/alfa_pro/synthetic_read_only.json`.
- Default live stdout is counts, dates, field names, relationship coverage, query status, and state labels only.
- Do not commit live transcripts or `--id-compare-store` files.
