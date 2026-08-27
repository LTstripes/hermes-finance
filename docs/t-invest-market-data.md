# T-Invest market data (0.4) and payouts (0.5)

Hermes Finance uses **T-Invest** as the production read-only source for owner-triggered quote preview and, in 0.5, future investment payout events. Direct MOEX ISS stays in the repository as a reference adapter and is not called in production.

Alfa PRO current snapshot and the accepted Alfa depository income-payment PDF import are 0.6 product paths; they are documented in `docs/releases/0.6.0.md` and `docs/release-notes-0.6.0.md`. This file remains the T-Invest quote/payout guide.

## What this does

After a local read-only token is configured, you can:

1. open an instrument;
2. press **Найти в T-Invest**;
3. choose one candidate and save the mapping;
4. press **Обновить котировки** in a reporting month;
5. inspect the preview. Nothing is applied to snapshots in this task.

There is no background refresh and no trading.

## Provider capabilities

The local diagnostics endpoint `GET /api/market-data/providers/capabilities`
exposes the registered market-provider profiles without constructing a client or
calling a remote service. Each capability is marked `production_enabled`,
`verification_only` or `unsupported`, with supported instrument types and
limitations. T-Invest payout/calendar support is represented by its separate
owner-triggered payout adapter; Alfa PRO broker snapshots are not part of this
market-data contract.

## Token

You need a T-Invest / T-Bank brokerage account, even an empty one.

1. Open the official token page: <https://developer.tbank.ru/invest/intro/intro/token>
2. Create a **read-only** token. Do **not** create Full Access. Do **not** create Transfer access.
3. Put it only in the ignored repository-root `.env` file (next to `.env.example`, not in `backend/`):

```env
HERMES_FINANCE_T_INVEST_READ_ONLY_TOKEN=
```

Hermes always reads `<repository-root>/.env`, including when `scripts/start-local.ps1` starts the backend from the `backend/` directory. Process environment variables still override the file.

4. Restart the local Hermes backend after changing the token.

The token never belongs in Git, the SQLite database, the browser, API responses, logs, tests, or reports.

Hermes cannot prove that a pasted token is read-only without calling forbidden trading methods. The guarantee on our side is documentation plus a client that implements **no** order, cancel, replace, sandbox-trading, or money-transfer methods.

## Preview

Quote preview remains an explicit button. A missing token fails calmly and does not fall back to MOEX. An old `moex_iss` mapping stays readable; production does not call MOEX for it. Remapping to T-Invest is an explicit owner action.

## Payouts (0.5)

Future coupons, dividends and redemptions are fetched only after an explicit owner preview. Hermes positions remain local: there is no broker portfolio/account import. Apply freezes the quantity from the local `PositionSnapshot` and never edits manual expected-flow rows. Unresolved duplicates stay manual-only. Provider coupons may feed C04; provider dividends stay calendar-visible and do not change the historical C04 dividend component; redemption is cash flow, never passive income. Reaching an event date does not create a realized investment cash flow. Startup, dashboard and month reads do not call T-Invest.

## Live probe (developer only)

CI never runs this. From `backend/`:

```text
uv run python -m hermes_finance.market_data.t_invest_probe --live
```

The quote probe reads only `HERMES_FINANCE_T_INVEST_READ_ONLY_TOKEN` from the ignored repository-root `.env`. It calls FindInstrument, GetInstrumentBy, BondBy, GetLastPrices and GetCandles. It does not call Accounts, Operations, Orders, Sandbox or Transfer. It does not write a mapping or a monthly snapshot. Optional `--write-fixture` stores a sanitized public payload under `backend/tests/fixtures/t_invest/`.

Payout-event evidence (R05-01) is a separate developer-only probe:

```text
uv run python -m hermes_finance.market_data.t_invest_payout_probe --live
```

It may call only `FindInstrument`, `GetInstrumentBy`, `BondBy`, `GetBondCoupons`, `GetBondEvents` and `GetDividends`. It does not implement the payout calendar, apply events, or call account/portfolio/trading APIs. Optional `--write-fixture` writes `backend/tests/fixtures/t_invest/official_payout_shape.json`.

## Troubleshooting the live probe

On the owner's Windows environment, the official T-Invest API was unreachable while a VPN was active and the same probe succeeded after the VPN was disabled. If the live probe has a network/connection failure, retry once with the VPN disabled before diagnosing the adapter. This is troubleshooting guidance for the observed environment, not an application networking requirement.

If authentication is rejected, verify that the token is a current **read-only** T-Invest token. The owner-side acceptance probe succeeded after an invalid/rejected token was reissued. Never print or paste the token into logs, reports, GitHub issues, or chat.

`--write-fixture` is optional and is not needed for a routine owner acceptance probe. Use it only when intentionally refreshing the sanitized deterministic fixture after an official API shape change; review the generated public fixture before committing it.
