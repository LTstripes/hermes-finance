# ADR 0006: Tax brackets administration and historical safety

- Status: Accepted
- Date: 2026-08-11
- Task: R02-17

## Context

Hermes Finance already calculates progressive salary tax from persisted `tax_brackets` rows. The current persistence model stores one set per calendar `year`, while salary-tax calculation for a reporting month dynamically reads the set for that year. A naive row-level CRUD UI could therefore change the calculated tax of an already closed reporting month.

R02-17 must make tax rules editable without allowing silent historical reinterpretation. The application is a local single-user analytical tool, so v0.2 does not need a general legal-rule engine or a full audit ledger.

This ADR is normative for R02-17.

## Decision

### 1. Version and effective period

For v0.2, the configuration unit is one complete tax-bracket rule set per calendar tax year.

- `tax_brackets.year` is the rule-set version/effective key.
- A set for year `Y` is effective from `Y-01-01` through `Y-12-31`.
- Mid-year versions/effective dates are not modeled in v0.2.
- If a future legal change requires two scales inside one calendar year, that requires a new schema/ADR; the UI must not pretend that the current year-only model can represent it.

### 2. Source classification

The API exposes a semantic source label for the effective values:

- `official_default` — the effective set exactly matches the built-in official progressive scale used by Hermes Finance;
- `manual_configuration` — the effective set differs from that scale.

This is a classification of the effective values, not a historical audit trail of who changed them.

The API also exposes `contract_version = "tax_brackets_year_v1"`.

### 3. Historical lock

A tax year is mutable only while it has no `reporting_month` with status `closed`.

If at least one closed reporting month exists in that year:

- create/update/delete/replace operations for the year fail closed;
- the API returns HTTP 409 with machine code `tax_brackets_year_locked`;
- the response identifies the closed months that lock the year;
- existing rules remain unchanged.

A `draft` month does not lock the year.

To deliberately change rules for a year that already contains closed months, the owner must explicitly reopen all closed months in that year first. That makes the historical recalculation visible and intentional; after the months are closed again, the year is locked again.

### 4. Public mutation is whole-set replacement

R02-17 does not expose public row-by-row bracket CRUD.

The public write operation replaces the complete set for one year atomically. This avoids intermediate invalid configurations and makes the user's intent explicit.

A valid complete set must:

- contain at least one bracket;
- start at exactly `0` kopecks;
- contain non-negative thresholds;
- be strictly contiguous: no gaps and no overlaps;
- have a finite upper bound on every bracket except the final one;
- have an open-ended final bracket (`threshold_to = null`);
- use integer basis-point rates in the range `0..10000` inclusive;
- use exact integer kopecks / `MoneyValue` decimal strings; binary float is forbidden.

Replacement happens in one transaction. Validation or lock failure leaves the previous set untouched.

### 5. Read behavior and defaults

`GET /api/tax-brackets/{year}` returns the effective complete set for the year.

If no rows exist yet, the API may project the built-in official default set without requiring a write. Salary-tax calculation may continue to persist defaults through its existing compatibility path.

The response includes:

- tax year;
- effective-from/effective-to dates;
- source classification;
- contract version;
- whether the year is mutable;
- closed months that lock it;
- the ordered bracket list.

### 6. Salary-tax calculation

R02-17 does not change the progressive-tax formula, opening-YTD contract, or known-month rules.

For a reporting month, salary tax still uses the effective bracket set for that reporting month's calendar year.

Changing a mutable year's brackets changes draft calculations for that year immediately. Closed months prevent such a change until explicitly reopened.

### 7. UI

Tax-bracket administration lives in Settings.

The UI must:

- show the selected tax year and its effective period;
- show whether values are the official default or a manual configuration;
- show all ranges and rates in user-facing Russian labels;
- allow editing only when `mutable=true`;
- explain that closed months lock a tax year;
- show the locking months when immutable;
- submit the complete set in one save operation;
- surface validation/409 errors without exposing raw internal identifiers as the primary message.

### 8. Audit expectations for v0.2

No general immutable change-history table is added in v0.2.

Historical safety is provided by:

1. year-scoped rule sets;
2. whole-set atomic replacement;
3. explicit API/UI source/effective-period metadata;
4. hard lock whenever closed reporting months exist.

If later releases need multiple legal versions per year, author identity, or an immutable change ledger, that is a separate persistence design.

## Rejected alternatives

### Allow editing closed years and rely on the user to remember

Rejected: monthly summaries are derived dynamically, so this silently rewrites historical tax semantics.

### Snapshot all tax brackets into every reporting month

Rejected for v0.2: larger persistence change than needed. The closed-year lock provides deterministic historical safety for the single-user workflow.

### Add arbitrary effective dates now

Rejected: the current model and calculation select rules by calendar year. Pretending to support arbitrary effective dates without changing the calculation model would be misleading.

### Public row-level CRUD

Rejected: it permits temporary gaps/overlaps and makes safe validation of the effective scale harder.

## Required regressions

1. default year returns a complete official set and source metadata;
2. complete manual replacement on a year with only draft/no months succeeds;
3. replacement is atomic and rejects gaps, overlaps, non-zero first threshold, non-open final bracket, invalid rates and invalid money;
4. any closed month in the year causes `tax_brackets_year_locked` and leaves data unchanged;
5. reopening all closed months makes the year mutable again;
6. salary tax for a draft month uses the newly saved set;
7. existing opening-YTD and salary-tax history regressions stay green;
8. Settings UI shows source/effective period, lock state and validation errors;
9. no binary-float financial calculation is introduced in frontend or backend.
