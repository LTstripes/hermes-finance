# Hermes Finance 1.10.0

This release collects the month-close, returns and maintenance work merged after 1.9.4.

## Month close and broker sources

- Simple broker sources intake (#1012, #1029): the month view accepts the broker
  XML statement and its PDF companion in one place. The PDF is recorded in the
  source-intake journal as a safe record (hash, account, period, status); the file
  itself and its text are not stored.
- Confirmations survive an unchanged Reopen (#1013): reopening a month without
  changing its sources keeps the existing confirmations.
- Money preparation API (#1030) for the broker money review.
- Month-close warnings instead of blocks (#1010).

## Returns

- Returns pages consolidated into `/v2/returns` (#1007).
- Total result broken down into payouts, price/trades and costs (#1008).
- Accepted coupon/dividend income (net, tax, coverage) shown on returns (#1028).
- October source returns and AI export coverage (part of #1016).

## Interface and maintenance

- Single reason-code dictionary for UI messages (#1035).
- Redundant service copy and unused components removed (#1015, #1006).
- Alfa Pro feature removed: code, UI, API, tests and docs (#1036).
- CI runs e2e and visual jobs only when their paths change (#1046); local
  check scripts gained selective modes (#1039).

No schema migration is included; stored amounts and receipt formats are unchanged.