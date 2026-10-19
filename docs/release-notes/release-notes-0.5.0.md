# Hermes Finance 0.5.0

Owner-controlled future investment payout calendar on top of locally stored Hermes positions.

## Highlights

- Fetch T-Invest coupons, dividends and redemptions only after an explicit owner action.
- Preview first, then apply selected events. Nothing is written on page load or dashboard read.
- Local position quantity stays the source of truth. Broker holdings are not imported.
- Manual expected payments stay owner data and are never silently overwritten.
- Unresolved duplicates stay manual-only until the owner chooses otherwise.
- Applied provider coupons feed the existing 12-month forecast. Announced dividends stay on the calendar and do not replace historical dividend history. Principal redemption is cash, not passive income.
- Reaching an expected payment date does not create a realized cash flow.

## Runtime

Local Windows app on `127.0.0.1:8000`. No auth, cloud, VPS, telemetry or trading.

T-Invest access is read-only. Put a read-only token in the ignored repository-root `.env`. Do not commit it.

Provider amounts may remain approximate when personal tax or net certainty is unavailable.

## Upgrade

Create a backup, stop the app, update the tree, then start with `scripts/start-local.ps1`. Alembic applies the additive 0.5 payout tables without rewriting existing months, positions or manual expected flows.
