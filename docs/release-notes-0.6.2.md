# Hermes Finance 0.6.2

Maintenance on top of 0.6.1. The 0.6 product scope stays local, owner-triggered and loopback-only. This release documents already integrated statement retract and month-editor layout polish.

## Statement retract

- Wrongly applied Alfa statement payouts can be undone with an auditable `active | retracted` lifecycle and an append-only `retract` revision.
- A statement-created payout retract removes its financial effect and keeps audit evidence.
- A linked-existing retract only detaches statement provenance. The original manual flow stays.
- After retract, the same statement can be imported again with a corrected mapping.
- CLOSED and missing-month operations fail closed.
- Owner UI: `Отменить импорт` and `Отвязать выписку`.
- Generic investment-flow delete does not silently destroy statement provenance.

## Month editor and statement review

- Targeted month tables (deposits, positions, debts, property) no longer show an unnecessary desktop horizontal scrollbar when there is enough space.
- Position inline-edit is a dedicated readable grid with compact Save/Cancel.
- Alfa prepared-import review is denser: instrument+ISIN, account, event+date, class badge, concise decision text for simple new rows.
- The actual-payout accent line no longer crosses the date.

## Safety contract (unchanged except documented retract)

- No OCR.
- No persistent raw Alfa/provider payload.
- No persistent Alfa account mapping.
- Apply is explicit and selected-row only.
- Duplicate and idempotency guards remain.
- CLOSED and missing-month operations fail closed and never auto-reopen.
- Retract is statement-specific and auditable.
- No provider or trading semantic change.
- Canonical Alembic head remains `0029_statement_event_retract`. This prep task does not add a new migration.

## Runtime

Local Windows app on `127.0.0.1:8000`. No auth, cloud, VPS, telemetry or trading.

T-Invest quotes and payouts remain owner-triggered and read-only. Alfa PRO is used only while the local terminal is running.

## Upgrade

Create a backup, stop the app, update the tree, then start with `scripts/start-local.ps1`. The launcher applies Alembic, including already-merged `0029_statement_event_retract`.
