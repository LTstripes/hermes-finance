# #336 — Financial context completeness: data contract

Status: **contract for review**. Contract-only stage — no implementation,
no migration, no code changes in this commit.

Parent: #331 (unified AI financial review). Roadmap: #127.

This document is normative for the #336 implementation slice. Where it
conflicts with `MASTER_SPEC.md` MVP statements (§11.10–§11.11), this contract
wins for the #336 scope after acceptance; `MASTER_SPEC.md` §§9.14–9.17 and
§§11.9–11.11 are updated at implementation time, not in this commit.

## 0. Scope boundary

#336 adds **only missing owner-entered structured facts**:

- mortgage annual rate;
- debt APR/rate + due/end dates;
- month-local planned budget, separate from actuals.

Already persisted facts (`saving_allocations.destination`/`notes`, IIS
lifecycle fields, exact ISIN, position cost/price fields) are **not** part of
#336 — #331 consumes them as-is.

Hard non-goals (from #336): mortgage amortization schedule, automatic
credit-card interest computation, bank sync, credit scoring, envelope /
zero-based budgeting subsystem, any change to financial formulas.

If implementation reveals that planned budget or liability terms need a
separate subsystem (scheduler, amortization engine, budget rollover rules),
**STOP** and split instead of growing this issue.

## 1. Mortgage rate (`property_snapshots`)

- New nullable column `mortgage_annual_rate_basis_points INTEGER NULL`
  with `CHECK (mortgage_annual_rate_basis_points >= 0)`.
- `NULL` = unknown. `0` = real zero rate. The value is never derived from
  monthly payment, mortgage balance, estimated value, or notes.
- Month-local snapshot field on the existing `property_snapshots` row.
  No separate mortgage/property profile table: one source of truth per
  reporting month. Rate history is read from successive monthly snapshots.
- Storage: integer basis points. API: `mortgage_annual_rate: str | None` —
  decimal percent string via the existing `PercentageRate` value object
  (same representation as deposit `annual_rate`). Domain math in `Decimal`;
  no binary float at any layer.
- Clone (`month_clone.py`): copied like the other permanent property state
  (value, balance, payment). A mortgage rate is a stable term, not an event.

## 2. Debt terms (`debts`)

- New nullable `annual_rate_basis_points INTEGER NULL`
  with `CHECK (annual_rate_basis_points >= 0)`.
  `NULL` = unknown, `0` = real 0%. Covers credit-card APR and other-debt
  annual rates with one field; no per-type rate semantics.
- New nullable `next_due_date DATE NULL`: the nearest obligatory payment
  date **as known at the month's `snapshot_date`**, when applicable.
  Informational anchor ("when must I pay next"), not a scheduler input.
- New nullable `contract_end_date DATE NULL`: maturity / contract end,
  when applicable.
- The two dates are never merged: separate columns, separate API fields,
  separate UI inputs. A debt may carry either, both, or neither.
- Missing stays `NULL`. No invented defaults (in particular, no
  end-of-month or +30-days guess for `next_due_date`).
- API: `annual_rate: str | None` (`PercentageRate`), `next_due_date:
  date | None`, `contract_end_date: date | None` (ISO dates).
- Clone: `annual_rate_basis_points` and `contract_end_date` are copied
  (stable terms). `next_due_date` is **cleared** on clone: it is event-like
  (cf. the salary `received_at` clearing precedent in `month_clone.py`),
  and carrying a past due date into a new month would be stale data.
  The owner confirms/sets it in the draft month. See §10.1.

## 3. Planned budget (new month-local table)

Actual `expense_entries` and `saving_allocations` are never treated as a
budget. The plan lives in a separate table so actuals can never be
misread as plan and vice versa:

- New table `planned_budget_lines`: `id`, `reporting_month_id` (FK
  `reporting_months.id`, `ondelete="RESTRICT"`), `category`
  (`String(128)`, same shape as `expense_entries.category`),
  `expense_type` (`mandatory` / `comfortable` / `other`, same check
  constraint values as `expense_entries`), `planned_amount_kopecks`
  (`BigInteger`, `CHECK >= 0`), `notes` (`String(2000)`, nullable).
- Expense-side plan only. The saving-intent side already exists:
  `saving_allocations` rows (copied month to month, plan/fact per
  MASTER_SPEC §9.15) serve as the saving plan; no second saving-plan
  table.
- Optional: month close never requires planned lines. An empty plan is
  valid and means "no plan entered", not "plan is zero".
- Plan-vs-actual matching key: exact `(category, expense_type)` match
  against `expense_entries`. Unmatched plan lines and unmatched actuals
  are reported side by side, never force-joined. Residual cash-flow
  comparison built on top is #331 presentation over authoritative
  actuals; it introduces no new financial formula here.
- Clone: copied as a draft starting point (precedent: mandatory expenses
  are copied). See §10.2.
- Closed month: immutable through the existing `_guard` path (§5).

## 4. `0 != unknown` (global rule)

- Every new numeric/date fact in §1–§3 is nullable at storage, service,
  and API layers. `NULL`/`None` = unknown/unentered. `0` / a real date =
  an explicit owner statement.
- UI renders unknown distinctly from zero (e.g. "не указано" vs "0 %");
  unknown never blocks month close.
- Migration rule: `ADD COLUMN ... NULL`. All pre-existing rows receive
  `NULL` (unknown). Backfilling `0`, payment-derived rates, or any other
  guess is forbidden. Downgrade drops the added columns.

## 5. History / close / clone semantics

- All #336 facts are month-local snapshots on draft-or-closed month rows.
- Closed-month immutability is unchanged: all new create/update/delete
  service paths must call the existing `require_editable_reporting_month`
  / `require_editable_child_month` guards (`services/_guard.py`,
  "closed reporting month must be reopened before editing"). Explicit
  reopen remains the only way to edit a closed month.
- Clone source may be draft or closed (existing rule); the target is
  always a new draft; the operation stays single-transaction
  (all-or-nothing), extended with the §1–§3 copy rules.
- #331 history reads closed months as stored. Missing #336 facts in
  history are `unavailable` + reason codes, never `0.00`. No change to
  eligible-history rules (ADR 0008 untouched).

## 6. Storage / API exactness

- Money: `BigInteger` kopecks at storage; `MoneyValue` API objects via
  `RubleAmount` (decimal string, two fraction digits). Same as all
  existing money fields.
- Rates: `Integer` basis points at storage; `PercentageRate` API percent
  string with two fraction digits (deposit `annual_rate` precedent).
  `ROUND_HALF_UP` on parse, exact `Decimal` in domain. #336 introduces
  no derived/calculated fields — pure owner-entered capture — so no new
  rounding paths appear.
- Dates: `Date` columns, ISO-8601 API dates. No datetime/timezone
  semantics for due/end dates.
- No binary `float` for these values in domain, storage, API DTOs, export
  builders, or frontend math. New DTOs use `extra="forbid"`; length and
  nonnegativity validation mirrors the existing debt/property/expense
  endpoints (422 on violation).

## 7. Consumption by #331

- #331 includes §1–§3 facts through its own versioned schema bump (owned
  by #331, not here): `debts[].annual_rate`, `debts[].next_due_date`,
  `debts[].contract_end_date`, `property.mortgage_annual_rate`,
  a `planned_budget[]` section, and plan-vs-actual comparison only where
  both sides are authoritative.
- Missing/unconfigured facts keep availability semantics in the existing
  style (`available` / `unavailable` + stable reason codes, cf.
  `ai_analysis_bundle`); zero and unknown stay distinct per §4.
- Arrays keep stable ordering (by `id`). Free-text `notes` are never
  parsed for numbers and never feed calculations.

## 8. UI / owner workflow

- New fields are edited inline in the existing month sections (debts,
  property, expenses area for the plan). No separate technical screen.
- Optional values are never required to close a month. Unknown is
  visually and semantically distinct from `0` (§4).

## 9. Tests at implementation (not in this contract commit)

Implementation must add: contract/repository/API tests for 0-vs-null
rates, due/end date separation and nullability, migration no-guess
(pre-existing rows read back `NULL`), clone semantics (rate copied, due
date cleared, plan copied), and closed-month immutability of the new
paths; plus frontend tests for editing and unknown-vs-0 display.

## 10. Open decisions for review

1. `next_due_date` cleared on clone (chosen, §2) vs copied as-is.
   Clearing follows the salary `received_at` precedent but asks the
   owner to re-confirm monthly. Copying is less friction but risks
   stale past dates posing as current obligations.
2. Planned budget copied on clone as draft (chosen, §3) vs starting
   empty each month. Copying matches the mandatory-expenses precedent;
   starting empty forces conscious planning but adds monthly friction.
3. Plan-vs-actual key is exact `(category, expense_type)` (chosen, §3)
   vs category-only vs an explicit plan-line link id. Exact pair is
   minimal (no new FK); a link id is more precise but a bigger model.
4. Mortgage rate is month-local (chosen, §1) vs a global mortgage
   profile. Month-local keeps one truth source and free history; a
   profile would need sync rules between profile and snapshots.
5. Rate checks are `>= 0` only (chosen, mirroring deposits) — no upper
   sanity cap. Flag if review wants one; symmetry with deposits says no.
