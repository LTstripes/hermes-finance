# Hermes Finance 0.6.1

Maintenance UX on top of 0.6.0. The 0.6 product scope is unchanged: owner-triggered Alfa PRO snapshot and the narrow Alfa depository income-payment PDF import remain as they were.

## Month editor

- Deposit and table actions live in the shared three-dot overflow menu.
- Manual investment flows, expenses, savings, debts and property/mortgage now have Edit actions that use the existing PATCH contracts.
- Position valuation provenance is in a compact HelpTip/details control.
- Dense month tables use tighter spacing.

## Quotes and Alfa statement review

- Quote preview is denser and readable. Proposed price and quote date are grouped. Secondary provenance and long guidance sit behind accessible detail.
- Transient Alfa PDF mappings stay only while the import panel remains mounted. There is an explicit reset. No persistent Alfa provider mapping is stored.
- An explicit owner action can save a statement ISIN into canonical `Instrument.isin` only when that field is empty or already matches. A conflicting non-empty ISIN is never overwritten. T-Invest mapping is a separate identity.
- Prepared statement rows show account, instrument, event, date, gross, tax, net and classification instead of opaque row IDs.
- Candidate reconciliation shows the same kind of evidence. Safe `select all ready` and clear-selection controls skip duplicate and unready rows.

## Safety contract (unchanged)

- No OCR.
- No persistent raw Alfa/provider payload.
- No persistent Alfa account mapping.
- Apply is explicit and selected-row only.
- Duplicate and idempotency guards remain.
- CLOSED and missing-month operations fail closed and never auto-reopen.
- No provider or trading semantic change.
- No schema migration.

## Runtime

Local Windows app on `127.0.0.1:8000`. No auth, cloud, VPS, telemetry or trading.

T-Invest quotes and payouts remain owner-triggered and read-only. Alfa PRO is used only while the local terminal is running.

## Upgrade

Create a backup, stop the app, update the tree, then start with `scripts/start-local.ps1`. There is no new Alembic revision in 0.6.1.
