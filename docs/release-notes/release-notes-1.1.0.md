# Hermes Finance 1.1.0

Hermes Finance 1.1.0 brings the accepted native monthly workflow and Performance Phase A together in the local single-user application. It packages the reviewed common tree from #642 and accepted changes since 1.0.0; release preparation changes version identity and documentation only.

## Native monthly workflow

- Native month management and editor sections cover the retained income, assets, positions, payouts, budget and liability operations.
- Alfa baseline, payout preparation and statement import retain explicit preview/apply, exact month identity and authoritative post-write rereads.
- Monthly Close actions and final-review Edit links stay in v2, preserve the exact month and close step, and return to refreshed server-owned readiness.
- Final review, explicit close, read-only historical reports and explicit reopen preserve existing lifecycle checks. Cancel, failed or ambiguous writes do not claim success.
- Goals, Tax/IIS planning, account-specific IIS forms, Scenario and data/application tools retain their accepted local context.

## Capital and Performance

- Capital links to native allocation/concentration detail and the selected closed month's monetary result by account or instrument class.
- Monetary result, unrealized snapshot, capital change, external-flow bridge and return rates remain different concepts. Unknown/null evidence is not turned into zero; redemption principal is not passive income.
- Performance Phase A provides portfolio/account period selection, XIRR/TWRR diagnostics and explicit data preparation with authoritative readback.
- Historical membership edits and observed valuation capture preserve existing finite-interval, stale-token, correction/invalidation and CLOSED boundaries. TWRR requires actual supporting PRE/POST evidence; the UI never manufactures missing history.
- Class-specific return rates remain outside this release. Allocation and the monetary-result class view are not substitutes for class returns.

## Correctness, recovery and regression protection

- Accepted post-1.0 data-integrity and coverage hardening is included, including month-delete invalidation, month-edit/Close atomicity, interval evidence/Close protection and ambiguity handling (#621–#624).
- Performance readiness uses the same CLOSED predicate without reserving a writer or ending its coherent read snapshot; mutation paths retain their write guard.
- Existing managed recovery-point, retention, isolated recovery rehearsal and post-restore state protections are retained.
- Canonical CI retains real synthetic backend journeys for import/apply/readback, Monthly Close/report/reopen/restore and Performance preparation/XIRR/PRE-POST/TWRR, alongside unit, visual, Windows and release-safety checks.

## Owner decision and operating boundary

The Owner explicitly authorized this release after technical and independent review, choosing to validate representative personal history during ordinary production use instead of repeating the same September entry in Preview. **No completed real-history Owner UAT is claimed.** The decision and subsequent observations are tracked in #572; publication is controlled by #643 and #124.

Before updating the working installation, stop the relevant Hermes runtime and use the supported backup-first Stable update operation for version 1.1.0. The updater validates one published annotated release, creates a verified SQLite backup before changing code, prepares and validates that exact checkout, and does not start the application. Start remains explicit and uses the existing database assignment.

The previous interface remains available at `/v1`. It shares the backend and database: it is an interface fallback, not a database rollback or a substitute for backup. Do not run destructive recovery experiments on the working database as part of ordinary acceptance.

## Unchanged scope

Hermes remains local-only, single-user, Windows-first and bound to `127.0.0.1:8000`, without cloud accounts, authentication, telemetry, trading or background provider refresh. Existing provider operations remain explicit Owner actions.

Not included: v1 retirement (#573), launcher removal (#629), new representative-demo tooling (#630), class-return implementation (#535/#540), or dashboard composition (#389). The launcher is not required for the supported update/start path.

Source and evidence: #642; `docs/UI_V2_AGGREGATE_VERIFICATION.md`; `docs/UI_V2_ANALYTICS_RECONCILIATION.md`; `docs/releases/1.1.0.md`; `docs/OWNER_RUNTIME_OPERATIONS.md`.
