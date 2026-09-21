# Hermes Finance v1.0.0

Hermes Finance 1.0.0 is the cohesive UI v2 + proven local production-lifecycle milestone.

## What is included

### UI v2 becomes the primary owner interface

- `/` opens the accepted UI v2 «Мои финансы» experience;
- `/v1` remains an explicit previous-interface rollback home;
- existing legacy editors/deep links remain available where intentionally retained;
- Home, Capital, «Доход и планы», Reports/history, native Monthly Close and «Данные и приложение» are integrated as one owner-facing product;
- Data/App includes sources/freshness, read-only reconciliation, catalogs/mappings, exports, local backup/restore, settings, tax brackets and runtime diagnostics;
- final owner-facing copy, layout polish and long-page navigation are included.

The default switch passed comparative review and exact-SHA Owner Preview/UAT before integration.

### Restore/recovery safety

- restore results distinguish confirmed negative outcomes from potentially mutated/ambiguous outcomes;
- `restore_outcome_ambiguous` is machine-readable;
- ambiguous restore UI never falsely claims success or failure and never blind-retries;
- cleanup cannot overwrite an already-classified ambiguous result;
- protected recovery-point publication supports an explicitly attested `external_encrypted_destination_v1` mounted filesystem destination with staged verification and destination read-back;
- bounded verified retention keeps the newest verified Hermes-managed recovery points while failing closed around unknown, foreign, partial or corrupt artifacts.

### Proven local runtime lifecycle

The release keeps the already proven local lifecycle:

- explicit Prepare/Validate;
- deterministic Start;
- exact-SHA isolated Preview/UAT;
- backup-first update to one owner-selected immutable published Stable release;
- guarded annotated-tag/GitHub Release publication.

Hermes remains single-user, local-only and bound to `127.0.0.1:8000`.

## Release boundary

This version packages accepted work already integrated on canonical development `main`; release preparation itself changes version identity and release documentation only.

Not included in this release:

- #461 isolated disaster-recovery rehearsal;
- #462 legacy Export/Backup post-restore month-state reload;
- #476 real-backend G04 browser CI gate;
- v1 retirement;
- cloud account/auth/VPS/public hosting;
- background provider refresh or trading/provider-write automation.

V1 remains intentionally available as a rollback/legacy layer.

## Owner acceptance and installation

### Owner OPS03 Preview/UAT — PASS

Exact tested code:

`caf4fdad99cc02f5bc171ec3b1d726b8516ad45e`

Owner verified the candidate in isolated Preview/UAT with isolated copied owner data before publication.

### Guarded publication — PASS

- `v1.0.0` published 2026-09-21;
- annotated tag object: `f99ee8ecac1acde7f559d92ee8f45ddcfcdfaa47`;
- tag peels exactly to `caf4fdad99cc02f5bc171ec3b1d726b8516ad45e`;
- Guarded Release run `35580890145`: SUCCESS;
- GitHub Release is published, non-draft and non-prerelease.

### Production Stable transition — PASS

Owner completed the real backup-first OPS02 transition:

`v0.9.0 -> v1.0.0`

After explicit Stable Start on the production database, owner returned **PASS Stable** and confirmed real working data continuity.

Detailed lifecycle evidence: `docs/R10_RELEASE_CLOSEOUT_2026-09-21.md`.
