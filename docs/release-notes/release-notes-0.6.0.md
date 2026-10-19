# Hermes Finance 0.6.0

Owner-triggered Alfa PRO current snapshot and a narrow Alfa depository income-payment PDF import on top of the local Hermes month model.

## Highlights

- Refresh a current Alfa PRO snapshot only after an explicit owner action, and only against the local Alfa PRO loopback router.
- Map provider accounts and instruments transiently for that review. Mapping is not persisted.
- Provider Price, UchPrice, NKD and P&L are evidence for comparison. They are never silent authoritative writes. Quantity and other local fields change only for rows the owner explicitly selects.
- Import only the accepted standardized Alfa depository income-payment PDF family (`Отчет о произведенных выплатах доходов по ценным бумагам`). The owner selects a local PDF. Parsing uses the text layer only; there is no OCR.
- The flow is Inspect → transient mapping → Prepare → explicit selected Apply. The exact same PDF is idempotent and duplicate-protected.
- If a manual cash-flow candidate already exists, Hermes requires an explicit `create_separate` or `link_existing` decision. Nothing is auto-picked.
- CLOSED and missing-month operations fail atomically and never auto-reopen a closed month.
- No raw PDF, full extracted text, original path/filename, beneficiary private data or private provider payload is persisted or logged.
- No account, instrument or reporting month is created automatically from provider or report data.

## Runtime

Local Windows app on `127.0.0.1:8000`. No auth, cloud, VPS, telemetry or trading.

Alfa PRO is used only while the local terminal is running. There is no background provider refresh and no browser → Alfa WebSocket.

T-Invest quotes and payouts remain owner-triggered and read-only, as in 0.4/0.5.

This is not generic brokerage or bank transaction import.

## Upgrade

Create a backup, stop the app, update the tree, then start with `scripts/start-local.ps1`. Alembic applies the additive 0.6 statement tables without rewriting existing months, positions or manual expected flows.
