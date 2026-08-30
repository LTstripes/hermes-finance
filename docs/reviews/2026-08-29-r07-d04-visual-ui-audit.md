# R07-D04 visual UI audit (#200)

## Contract and acceptance mapping

| Acceptance condition | Check |
| --- | --- |
| Primary owner routes stay inside the document viewport | `npm run audit:visual` checks document width, bounded panels/controls, clipped controls, and table-scroll containers at 1366×768, 1440×900, and 1920×1080. |
| Dense tables may scroll locally without widening the page | Reconciliation and month-position routes use synthetic long labels, identifiers, amounts, and rows; the harness permits overflow only inside `.table-wrap`. |
| Owner-facing UI does not expose implementation fields | The harness rejects known internal enum/reason/field names in visible text. Targeted component tests cover tax/IIS, risk allocation, reconciliation, and export copy. |
| Evidence is deterministic and private-data safe | `frontend/e2e/visual-fixtures.ts` contains synthetic-only data. Screenshots are written to ignored `.visual-audit/<viewport>/` folders. No owner database, provider runtime, or `.env` is required. |
| Loading, empty, and error states remain usable | Dedicated isolated pages capture all three states at 1440×900 and run the same bounds/leakage checks. |

## Route matrix

| Route/view | Synthetic stress | Result |
| --- | --- | --- |
| Dashboard | Long money values and 12-month history | Pass at all viewports |
| Analytics | Dense composition/history values | Pass at all viewports |
| Risk allocation | Long labels, unavailable dimensions, internal reason inputs | Pass; raw reason/source fields removed from visible copy |
| Freshness | Mixed freshness/provenance states | Pass at all viewports |
| Reconciliation | Explicit preview, eight dense rows, long provider identifiers, diagnostics | Pass; table scroll remains local and diagnostics are collapsed |
| Months | Twelve reporting periods | Pass at all viewports |
| Month positions | Long account/instrument names in selects and forms | Pass; controls shrink inside the grid |
| Payouts | Empty deterministic state | Pass at all viewports |
| Accounts and instruments | Ten accounts, twelve instruments, IIS sub-sections | Pass at all viewports |
| Goals | Empty deterministic state | Pass at all viewports |
| Tax and IIS | Long account name, threshold values, warning-code inputs | Pass; owner copy uses readable labels |
| Export and backups | Long filenames, large sizes, AI bundle guidance | Pass; internal schema fields removed and backup columns separated |
| Settings | Complete tax-bracket and settings fixtures | Pass at all viewports |

## Findings and fixes

| Severity | Finding | Resolution |
| --- | --- | --- |
| High | Reconciliation table min-content widened the document at 1366 and 1440. | Grid/panel/table wrappers now permit shrinking; the wide table scrolls only inside its wrapper. |
| High | Long account/instrument options widened the month-position form, including at 1920. | Editor-grid children and controls now use zero minimum width and bounded full width. |
| Medium | Tax/IIS, risk allocation, reconciliation, and export exposed raw reason codes, field names, IDs, or backend terminology. | Known values are translated, unknown values use neutral owner copy, local IDs are hidden, and technical diagnostics are collapsed. |
| Low | Backup-table headers and values visually touched at 1440. | Backup columns received scoped spacing and safe wrapping. |

## Evidence

- Full audit: 40 passed, 2 expected viewport skips (the state suite is intentionally captured once at 1440×900).
- Route screenshots: `.visual-audit/1366x768/`, `.visual-audit/1440x900/`, `.visual-audit/1920x1080/`.
- State screenshots: `.visual-audit/1440x900/state-loading.png`, `state-empty.png`, and `state-error.png`.
- Representative dense evidence: `reconciliation.png`, `month-positions.png`, and `export.png` in each viewport folder.

## Safety note and boundary

An optional in-app-browser smoke was stopped immediately when the local Vite proxy resolved a pre-existing non-synthetic local API. It was not used as evidence; no actions were submitted and no screenshot was retained. All retained audit fixtures and screenshots are synthetic. This task does not change financial semantics, backend code, database schema, migrations, or runtime/provider behavior. Issue #201 is not started.
