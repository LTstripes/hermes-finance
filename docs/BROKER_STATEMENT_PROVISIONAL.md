# Source-intake provisional account estimate

Contract: [Owner decision in #839, 2026-10-18](https://github.com/LTstripes/hermes-finance/issues/839#issuecomment-6253883555),
with the integrated strict account WHAT-IF remaining separate
([`BROKER_STATEMENT_WHAT_IF.md`](BROKER_STATEMENT_WHAT_IF.md)). The related
durable journal is [`SOURCE_INTAKE.md`](SOURCE_INTAKE.md).

This slice answers one product question: a deliberately provisional RUB return
for one saved MyBroker source-intake period, without a financial `SOURCE`
receipt, `Apply`, accepted H2 evidence or a Close. It is read-only. It does not
change strict S3, `can_apply`, Close, financial tables or the source-intake
journal writer.

## Input and observed layer

One saved `source_intake_v1` journal entry, its exact unchanged original bytes
and filename, plus the journal's own original-bound parser facts. The server
verifies the original SHA-256, byte length and filename digest, and reproduces
the journal grammar (native linkage enabled or the frozen legacy grammar) from
the bytes. A parser or original mismatch refuses; it does not silently
reinterpret the saved journal.

The observed operands are the broker-reported native EOD values of every
recognized security plus the separate single RUB currency row:

```text
V0 = sum(position.beginning_value) + rub_money.beginning_amount
V1 = sum(position.ending_value)   + rub_money.ending_amount
reported_value_change = V1 - V0
t0 = covered_from - 1 day, t1 = covered_to
```

`reported_value_change` is an observed broker-reported value change, not a
performance label, return, P&L or taxable income.

The estimate only proceeds when both totals are defensible:

- one active supported RUB brokerage/IIS account bound by the journal;
- `endpoint_basis` is `previous_day_eod` / `covered_to_eod`;
- every recognized position has both beginning and ending values, exactly
  convertible to integer kopecks and non-negative;
- exactly one RUB currency row with both amounts, exactly convertible and
  non-negative;
- no `position_row_unclassified`, no endpoint conflicts and no ambiguous cash;
- every recognized source account alias resolves to the selected journal
  account (or is explicitly unbound by the journal rules).

Otherwise the context shows the independently valid per-row observations and a
hard blocker, with both totals and the return unavailable. It does not
fabricate a percentage. A missing beginning quantity is disclosed as a
limitation but does not invalidate a present beginning value.

## Explicit scenario layer

No choice is selected automatically. The context exposes the complete finite
set of requirements and exact source-reference membership:

1. **Native basis** — model the same account continuously using both native
   EOD totals without valuation or cost adjustments.
2. **Recognized incoming candidate** — for each recognized
   `account_cash_in_candidate`, choose `include_as_account_inflow` (dated at the
   native posting date) or `exclude_from_external_schedule`. Excluding does not
   delete the observed row. The current reader recognizes only the bounded
   `из АО …` incoming pattern; it is not a generic deposit/withdrawal
   classifier.
3. **Schedule** — explicitly choose a dated schedule (`dated`) or an
   explicitly empty one (`explicit_empty`); omitted/null is not empty.
4. **Remaining crossings** — explicitly state that within the scenario the
   selected account has no other boundary crossings beyond the displayed dated
   schedule. This is a hypothetical statement, not proof of completeness and
   not `coverage_complete=true`.
5. **Recognized trades/Money/pending** — commissions, accrued interest (NKD),
   coupons, trade settlements and pending trades give no additional investor
   flow or endpoint adjustment in this native-total model. Amounts are never
   set to zero, and coupons/NKD are not added again. Recognized coupon/NKD
   observations are displayed separately.
6. **REPO** — when REPO is observed in recognized trades or structural native
   references, explicitly choose `native_totals_include_REPO_as_reported`. The
   calculation is conditional: REPO amount, custody basis and economic effect
   remain unknown and null.
7. **Unparsed/opaque rows** — when the parser reports material unparsed
   sections/rows, explicitly assume that they are already reflected in the
   broker-reported native totals and add no separate modeled cash, asset or
   liability effect. Their economic meaning and amount remain unknown; they are
   still visible in the journal and limitations.

Unknown future diagnostics, a second effective account, unsupported cash
semantics, capacity overflow or invalid assumption membership are hard
blockers. More than 16 recognized incoming candidates is a capacity blocker;
they are not truncated.

## Mathematics

The unchanged Decimal XIRR kernel and the same S3 period conversion are reused
at precision 60. For a selected external amount `Ei > 0` entering the account:

```text
investor vector = -V0@t0, -Ei@ti, +V1@t1
internal root   = annualized ACT/365 root
published rate  = (1 + root) ^ ((t1 - t0).days / 365) - 1
scenario result = V1 - V0 - sum(Ei)
```

Only the finite period fraction is returned; `annualized=false`. No annual
return, confidence interval or “actual” quality is published. No-root,
root-ambiguity, convergence and non-finite guards remain fail-closed.

Synthetic reference (30 days): `V0 = 10,000.00`, one `+1,000.00` candidate on
day 15, `V1 = 11,211.00`.

```text
reported value change = 1,211.00 RUB (not a return)
include candidate     =   211.00 RUB / 2.01% for the period
exclude candidate     = 1,211.00 RUB / 12.11% for the period
10,000 × 1.0201 + 1,000 × 1.01 = 11,211
```

Include/exclude are two labelled scenarios, not confidence bounds on actual
performance. When exactly one candidate exists, the opposite interpretation is
returned as a clearly labelled alternative; with zero or multiple candidates no
automatic alternative is invented.

## HTTP and desktop

All routes are POST multipart under `/api/broker-statement-provisional`:

| Route | Required fields beyond unchanged `file`, `intake_id`, `expected_manifest_digest` |
| --- | --- |
| `/context` | None |
| `/evaluate` | JSON `assumptions`, `expected_context_fingerprint` |
| `/export` | Same plus `expected_result_fingerprint` |

Unexpected/duplicate fields and query parameters are 422. Missing intake is
404. Original/manifest/context/result staleness is a typed 409 without a numeric
result. Responses are `Cache-Control: no-store`; XML and financial values are
not logged. Export re-reads the original and journal, recomputes the same full
result DTO and is never a persisted token or rate-only download.

The panel lives inside the existing source-intake journal under
`/v2/capital/...` month review. It uses the page-memory original. It shows the
observed RUB component values and source lexemes, the reported value change, the
recognized candidates/payouts, every required choice, the chosen scenario RUB,
the nonannualized period percentage and all limitations. Changing the intake,
original or any choice immediately hides the old result and disables export.
The panel is explicitly `authority=provisional`; it is not S3, Close, financial
Apply, AI actual export or a stored scenario.

## Reproducible synthetic verification

```powershell
uv run --project backend pytest backend/tests/test_statement_import_broker_statement_provisional.py
npm test --prefix frontend -- BrokerProvisionalEstimate.test.tsx SourceIntakeJournal.test.tsx
npm run build --prefix frontend
```

The backend suite independently checks the reference equation, signs, loss,
explicit-empty versus missing schedule, source values/kopecks, real journal
composition, candidate capacity, REPO/unparsed/pending assumptions, stale
original/manifest/context, API field guards, full export agreement and zero DML
against all tables. The desktop suite checks no default assumptions, observed
versus scenario separation, edit invalidation, late-response rejection, full
JSON export and the required original.

Synthetic correctness is not Owner-real numeric acceptance. Real source data can
still be blocked by missing/ambiguous endpoints, account binding, unsupported
cash semantics or other hard evidence, and the provisional figure never becomes
actual S3/Close/XIRR/TWRR.
