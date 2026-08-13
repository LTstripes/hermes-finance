# T-Invest market data (0.4)

Hermes Finance uses **T-Invest** as the production market-data source for owner-triggered quote preview. Direct MOEX ISS stays in the repository as a reference adapter and is not called in production.

Alfa PRO / broker portfolio import is future work and is not implemented here.

## What this does

After a local read-only token is configured, you can:

1. open an instrument;
2. press **Найти в T-Invest**;
3. choose one candidate and save the mapping;
4. press **Обновить котировки** in a reporting month;
5. inspect the preview. Nothing is applied to snapshots in this task.

There is no background refresh and no trading.

## Token

You need a T-Invest / T-Bank brokerage account, even an empty one.

1. Open the official token page: <https://developer.tbank.ru/invest/intro/intro/token>
2. Create a **read-only** token. Do **not** create Full Access. Do **not** create Transfer access.
3. Put it only in the local ignored `.env` file:

```env
HERMES_FINANCE_T_INVEST_READ_ONLY_TOKEN=
```

4. Restart the local Hermes backend after changing the token.

The token never belongs in Git, the SQLite database, the browser, API responses, logs, tests, or reports.

Hermes cannot prove that a pasted token is read-only without calling forbidden trading methods. The guarantee on our side is documentation plus a client that implements **no** order, cancel, replace, sandbox-trading, or money-transfer methods.

## Preview

Quote preview remains an explicit button. A missing token fails calmly and does not fall back to MOEX. An old `moex_iss` mapping stays readable; production does not call MOEX for it. Remapping to T-Invest is an explicit owner action.
