# Release 0.2 — user smoke log — 2026-08-11

This file records findings from the owner-led manual smoke/backfill pass before the `v0.2.0` release tag.

The release tag remains held until the smoke pass is complete and R02-21 synchronizes final release metadata/docs.

## Completed follow-ups

- `R02-17` — DONE in main: tax brackets administration contract/API/UI. Merge SHA: `ffad69208cba1ca33db063f6250ef1712863f066`.
- `R02-20` — DONE in main: localization of user-facing UI/API errors. Merge SHA: `f6b2cb450c2e5ccf5d4fe53d8e803a20cf80b44d`.

`docs/RELEASE_0_2.md` may still show stale `READY` statuses for these two rows until the final R02-21 release-doc synchronization. Code/CI state in `main` is authoritative for their implementation completion.

## Smoke finding 1 — historical month editor blocked by incomplete salary-tax history

**Observed:** opening an older draft month failed with `salary_tax_history_incomplete`, preventing data entry.

**Root cause:** `MonthDetailPage` loaded month data, income rows and `/summary` in one `Promise.all`. The expected fail-closed salary-tax summary error therefore rejected the entire editor load.

**Resolution:** the editor now treats only `salary_tax_history_incomplete` as an unavailable calculated-tax slice, keeps the month editable, renders calculated tax/net as unavailable, and preserves any previously stored salary tax rather than replacing it with zero. The backend salary-tax/opening-YTD contract was not weakened.

**Delivery:** PR #15, merge SHA `83271d106ca1065ddf6778540065fe45c0e508cc`.

**Verification:** frontend/backend/privacy/Windows production smoke green on exact PR head before merge.

## Smoke finding 2 — populated draft month could not be deleted

**Observed:** a draft reporting month with entered data could not be deleted, while empty drafts could.

**Root cause:** the UI promised draft deletion, but direct month-owned rows use `ON DELETE RESTRICT`, and the reporting-month service attempted to delete only the parent `reporting_months` row.

**Resolution:** sanctioned draft deletion now removes direct reporting-month-owned rows first and then the draft month in one transaction. Database `RESTRICT` safeguards remain in place globally. Closed months remain undeletable unless explicitly reopened first.

**Delivery:** PR #16, merge SHA `8a77ba92716f5f9b897c91d007e13e16814164b2`.

**Verification:** backend/frontend/privacy/Windows production smoke green on exact PR head before merge.

## Process

Further findings from the same manual smoke pass should be appended here until R02-21 performs the final `0.2.0` release metadata/docs/backlog synchronization. Any material new work discovered during smoke should become a bounded `R02-*` task before the release tag is created.
