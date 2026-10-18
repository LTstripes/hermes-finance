# Position historical class identity (C1 / #696)

## Writer inventory before schema changes

Traced on canonical main `1f3b3415a48819e0c48e08fc2b16e794aafec490`.

| Supported path | Source | C1 treatment |
| --- | --- | --- |
| Manual/API create | `services/positions.py::stage_create_position_snapshot`, `api/positions.py` | Capture the catalogue type as the new draft's explicit initial identity; `other` stays unknown. |
| Manual/API update | `services/positions.py::stage_update_position_snapshot` | Preserve evidence unless explicitly corrected/withdrawn in DRAFT. Existing month reservation and If-Match apply. |
| Broker baseline create/update | `services/broker_snapshot_apply.py::_stage_create/_stage_update` | Delegates to the same position writer; quantity updates preserve identity. No provider expansion. |
| Market quote apply | `services/positions.py::apply_snapshot_market_quote`, `services/quote_apply.py` | Price-only mutation preserves identity and requires DRAFT. |
| Month clone | `services/month_clone.py::_copy_positions` | Carry the source's persisted identity (including unknown) as a draft template, never reread catalogue type. Explicit correction is available before close. |
| Legacy Excel securities/gold import | `services/legacy_migration.py::_add_security_position/_add_gold_position` | Both direct constructors leave identity NULL: import-time catalogue/type mapping is not historical proof. |
| Position deletion with payout history | `services/positions.py::delete_position_snapshot` | Detach the same row to `archived_from_period`; preserve evidence. Without payout history the row is deleted. Requires DRAFT. |
| Month deletion with payout history | `services/reporting_months.py::delete_reporting_month`, `services/payout_provenance_lifecycle.py::archive_month_payout_history` | Detach referenced rows unchanged before deleting remaining month-owned rows. Requires DRAFT. |
| Close / Reopen | `services/reporting_months.py::close_reporting_month/reopen_reporting_month` | Freeze / unlock existing evidence; neither operation infers or replaces it. Repeated close cannot relabel rows. |
| SQLite backup / restore | `services/backups.py` | Online backup and whole-file restore preserve the column. Incompatible schemas are rejected. |
| Protected backup / recovery rehearsal | `services/protected_backups.py`, `services/recovery_rehearsal.py` | Whole-database recovery; forward Alembic upgrade leaves old evidence NULL. No row reconstruction from catalogue. |
| JSON export | `api/json_export.py::RawPositionSnapshot` | Export persisted nullable evidence. This is an export-only surface, not a supported restore/import writer. |

`PositionSnapshot(...)` constructors in production are confined to positions,
month clone and the two legacy import paths. Catalogue updates do not mutate snapshots.

## Minimal design

One nullable `PositionSnapshot.historical_instrument_type` uses the existing
`InstrumentType` vocabulary. NULL means unknown/unavailable; `other` is
unclassified and is represented as NULL. This is snapshot identity evidence,
not class valuation, crossing coverage or return eligibility.

Creation captures the initial draft identity. Clone carries the source identity
as the existing month-copy workflow's starting point; copying unknown cannot
make it exact. Catalogue edits, quote/quantity updates, Close and Reopen never
refresh it. A correction explicitly supplies a type through position PATCH;
explicit NULL withdraws evidence. A CLOSED row must first be reopened, corrected
and reclosed. Legacy rows can only gain evidence by an explicit correction;
reopening/reclosing alone does not repair history.

Class-only correction/withdrawal preserves the stored financial totals, including
legacy totals that do not round-trip through rounded per-unit prices. Supplying
financial inputs continues to use the existing position recalculation rules.

Migration 0045 adds the nullable checked column without any data UPDATE/default.
Downgrade succeeds while all evidence is NULL and fails closed if evidence would
be lost. Old-schema backups require the existing forward recovery route or are
rejected by same-schema restore.

Readers of C1 must use this persisted field and never fall back to the current
catalogue. Historical Performance account scope remains the existing
`AccountPerformanceScopeMembership`; current account flags are not evidence.
Existing portfolio/account valuations, returns and presentation groupings are
unchanged. No class-return API or C2/C3 read model is introduced.
