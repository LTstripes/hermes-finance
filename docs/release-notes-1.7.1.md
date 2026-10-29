# Hermes Finance 1.7.1

Hermes Finance **1.7.1** combines the source-bound bond endpoint reader from
[#984](https://github.com/LTstripes/hermes-finance/pull/984) with the Returns read
efficiency and Month workflow changes from
[#986](https://github.com/LTstripes/hermes-finance/pull/986). The packaging change
synchronizes release identity and notes; dependency resolutions, application
logic and migration sources are unchanged relative to those integrated changes.
Current publication, installation and acceptance state belongs to
[CURRENT_STATUS](CURRENT_STATUS.md).

## Changes since v1.7.0

The ordinary instrument API and Returns overview/detail can consume one explicitly
configured, trusted read-only evidence file. An accepted decision must match the
physical database, complete current source/revision set and exact original,
row, side and date. Only matching bond endpoints use the reported dirty value
as economic value, once; a separate unknown accrued-interest component stays
NULL. Other reports and periods do not inherit acceptance.

Missing, prepared, revoked, invalid or mismatched evidence leaves UNKNOWN.
The file is read afresh for each operation, with no fallback from a configured
invalid file to older evidence. No HTTP input can supply or accept the file.
Cash, flow, cost, quantity, currency, conflict and completeness guards remain
independent; root account reconciliation, H1 and financial writers retain their
existing authority. This does not establish full account or all-time returns,
exact XIRR/TWRR, financial balances or Close readiness.

Returns reuses verified source views only within one coherent read and avoids
unused history projections in selected-period overview/detail requests. It adds
no persistent cache; the ordinary source reader retains its full-history default.
Refreshing the page avoids the redundant request cascade while retaining stale,
error and currentness handling. When CLOSED periods exist, an unscoped entry
selects the accepted portfolio and latest CLOSED month. Explicit source/history
links retain their basis, dates and NULL reasons. Category checkboxes preserve
keyboard focus, URL, Reload and rapid Back navigation. These changes do not make
unsupported rates computable or combine source-only sums with deposit interest.

Month keeps XML upload/review in Broker statements. Payouts uses saved financial
DRAFT positions for the existing explicit T-Invest forecast action and saved
calendar; source-only Save does not create that financial DRAFT. Both source
lists use the selected month/account scope, with historical/partial overlaps
collapsed separately. An explicitly uploaded wrong-period original remains
available for its mismatch explanation. Source selection follows the newest
confirmed revision while preserving month/account and pending-recovery guards.
Source observations, accepted actual payouts and forecasts remain distinct.

## Update, activation and recovery

Updating from v1.7.0 retains schema **0066_actual_payout_links**. This release
adds no migration or table and does not rewrite originals or financial records.
Use [O3](OWNER_RUNTIME_OPERATIONS.md#o3): verify the guarded annotated publication,
bind the owned Stable process and existing physical database, retain a fresh
verified backup with its producing code, and use the stock backup-first update
with an explicit DatabasePath and disjoint backup directory. Target
Prepare/Validate and Start remain separate operations. Reuse accepted unchanged
code/schema evidence without repeating an aggregate Test or migration.

Evidence activation is a separate authorized operation under
[C7](ARCHITECTURE_AND_CONTRACTS.md#c7) and [O1](OWNER_RUNTIME_OPERATIONS.md#o1).
Recheck the exact original comparison, accepted decision, physical database and
current revisions before configuring the private file. A mismatch must not be
repaired by silently rebinding it. Removal or atomic revocation affects subsequent
reads; restoring an older accepted file requires a new trusted activation.

Finish with short health/version, physical binding, data-continuity and bounded
reader checks. On failed or uncertain Start, stop only the owned runtime and
preserve the database, backup and evidence. Do not retry blindly, downgrade or
overwrite the live database with a cross-schema backup. Provider calls, source
imports, financial Apply, payouts and Close are outside this update.
