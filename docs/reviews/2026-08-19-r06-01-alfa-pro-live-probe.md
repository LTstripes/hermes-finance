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
5. From the workspace `backend/` directory:

```text
uv run python -m hermes_finance.alfa_pro_probe --live
```

6. Handshake-only check (no client-data queries). Uses Origin `http://127.0.0.1:9`:

```text
uv run python -m hermes_finance.alfa_pro_probe --live --origin-handshake-only
```

7. Optional second `--live` run after a clean PRO restart, to compare `id_fingerprints` only.
8. If PRO can naturally sit at `ReadyToSign=false` without changing account permissions or sending trading commands, run `--live` in that state too. If not, leave `read_with_ready_to_sign_false: unresolved`.
9. Paste only the printed sanitized block into this file. Do not keep raw frames, logs, or payloads.

CI must not pass `--live`. The probe writes nothing to the Hermes database, backups, exports, or repository files.

Missing or unauthenticated PRO should fail calmly with `connection: fail` or `authenticated_read: fail`.

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
- `ClientOperationEntity`
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
ready_to_sign_observed: unresolved

accounts_count: unresolved
subaccounts_count: unresolved
iis_explicitly_classifiable: unresolved

positions_count: unresolved
positions_with_isin: unresolved
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

Record `FACT` only from the owner live run. Otherwise leave `UNRESOLVED`. Do not guess IIS from account numbers or names. Do not copy raw IDs, holdings, quantities, balances, prices, or JSON.

## Live questions (issue #71)

A–H remain unanswered until Phase B. Phase A does not observe Alfa PRO.

## Privacy

- No real Alfa credentials, account IDs, or owner portfolio data in this repository.
- Synthetic fixture: `backend/tests/fixtures/alfa_pro/synthetic_read_only.json`.
- Live stdout must stay counts/dates/field names/state labels/id fingerprints only.
- Do not commit live transcripts.
