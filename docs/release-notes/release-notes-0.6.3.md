# Hermes Finance 0.6.3

Maintenance on top of 0.6.2. This release documents the already integrated M06-07, M06-08 and M06-09 work. It does not add a new product line, provider write path or trading behavior.

## Dashboard and payout readability (M06-07)

- Dashboard cards distinguish passive-income fact, forecast/goal and mandatory-expense coverage instead of duplicating one KPI.
- Actual mandatory-expense coverage is calculated in the backend/domain with `Decimal` and `ROUND_HALF_UP`, and remains distinct from forecast coverage.
- Mortgage context is visible without the old hidden extra-metric interaction.
- Actual payout rows use instrument/company as the primary visual anchor and account as secondary context.
- Statement retract/edit/delete semantics remain unchanged.

## Deposit-interest forecast (M06-08)

- Selected-month persisted `DepositSnapshot.expected_monthly_interest_kopecks` values are summed and annualised as monthly estimate × 12.
- This automatic deposit component is explicitly approximate: maturity and rate changes are not modeled.
- Manual expected `interest` remains additive.
- Forecast breakdown exposes deposits, coupons, dividend component and other income.
- Existing T-Invest coupon/dividend/redemption counting semantics remain unchanged.
- Forecast and dashboard read paths remain read-only and do not call providers or the network.

## T-Invest batch refresh and payout calendar (M06-09)

- `Проверить все позиции T-Invest` is an explicit owner-triggered batch preview.
- `Проверить изменённые` remains explicit for local frozen-quantity mismatch where applicable.
- Position quantity changes do not trigger automatic provider/network refresh in the background.
- Apply remains a separate explicit action with the accepted per-payout semantics, including re-fetch and preview-changed guards; batch preview does not imply cross-position atomic Apply.
- Single-position preview remains supported.
- Payout calendar month disclosure is obvious; expanded rows show instrument/company first, account second, source/provenance, amount and redemption-as-capital context.
- `Ручные ожидаемые выплаты` is clearly manual-only/additive and follows the merged calendar in DOM order.

## Safety contract

- No new Alembic revision; the canonical head remains `0029_statement_event_retract`.
- No cloud, auth, telemetry, trading or provider write operations were added.
- No raw provider payload or raw Alfa PDF persistence, OCR or persistent Alfa account mapping was added.
- CLOSED write guards, statement-specific auditable retract and generic-flow provenance protection remain in force.
- The application remains Windows-first, local and loopback-only at `127.0.0.1:8000`.
