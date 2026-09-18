# Hermes Finance — owner runtime operations

> Owner-facing operational guide for the proven post-R09 architecture.
>
> This is not a release checklist. Publication remains documented in `docs/RELEASE_AUTOMATION.md` and controlled through permanent issue #124.

## 1. Architecture in one sentence

Hermes Finance uses small composable owner operations instead of one launcher state machine owning release discovery, Git mutation, backup, dependency preparation and runtime startup.

Accepted model:

- launcher = owner-facing profile/status/Start/Stop shell;
- Prepare/Validate = `scripts/prepare-runtime.ps1`;
- deterministic Start = `scripts/start-local.ps1`;
- exact Preview/UAT = `scripts/prepare-preview.ps1`;
- Stable release transition = `scripts/update-stable.ps1`;
- release publication = guarded GitHub Release flow (#124).

This full chain was owner-proven on the real `v0.8.2 -> v0.9.0` transition on 2026-09-17.

## 2. Current published Stable

Current published Stable is **v0.9.0**.

Release/source code identity:

`c90a842ec5e85fc5ac0de4aedd5d7fd14c09ae36`

Annotated tag object:

`07c06d44f8b780e721be346a21909ca02585d57d`

The tag peels exactly to the release/source SHA above.

Owner acceptance:

- OPS03 exact-SHA Preview/UAT: PASS;
- guarded publication: PASS;
- OPS02 Stable update `v0.8.2 -> v0.9.0`: PASS;
- production readiness smoke: PASS;
- `/api/health` version `0.9.0`: PASS;
- owner data continuity: PASS.

Detailed evidence: `docs/R09_RUNTIME_RELEASE_CLOSEOUT_2026-09-17.md`.

## 3. Windows launcher

The launcher is still valid and intentionally familiar for its bounded role:

- show Stable/Preview profile identity/status;
- ordinary Start/Stop;
- open Hermes after health is ready;
- diagnostics/status presentation;
- installed shortcuts/package shell.

It is **not** the canonical Stable release updater.

That is the main architectural change: safety-critical release/update semantics are no longer hidden inside a second launcher-owned state machine.

Install/reinstall from the currently selected published Stable checkout:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\launcher\windows\install.ps1
```

Do not use the legacy launcher self-update experiment as release-update evidence.

## 4. Prepare an exact checkout

```powershell
$checkout = (Get-Location).Path
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\prepare-runtime.ps1 `
  -Checkout $checkout `
  -Prepare
```

Prepare:

- installs/synchronizes locked dependencies for that exact checkout;
- builds the production frontend;
- writes ignored `.hermes-runtime-prepared.json` proof;
- does not start Hermes;
- does not move Git refs;
- does not follow `main`;
- does not mutate another checkout.

Validate existing proof:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\prepare-runtime.ps1 `
  -Checkout $checkout `
  -Validate
```

If code, lock/build inputs or required artifacts changed, validation fails closed and the owner explicitly prepares again.

## 5. Deterministic Start

From an already prepared checkout:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-local.ps1
```

Ordinary Start:

- validates prepared-runtime proof;
- uses the explicitly selected runtime/database boundary;
- runs accepted guarded startup/migration semantics for that DB;
- binds only `127.0.0.1:8000`;
- performs health checks;
- does not run dependency sync/build/Git update itself.

Readiness smoke that exits automatically:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-local.ps1 -ExitAfterReady
```

## 6. Exact Preview/UAT preparation

Use OPS03 when testing one unreleased candidate SHA before publication.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\prepare-preview.ps1 `
  -CandidateSha <full-40-char-sha> `
  -PreviewCheckout <preview-checkout-path> `
  -PreviewDataDirectory <isolated-preview-data-path> `
  -PreviewDatabase <isolated-preview-db-path> `
  -StableCheckout <stable-checkout-path> `
  -StableDataDirectory <stable-data-path> `
  -StableDatabase <stable-db-path> `
  -ControlCheckout <trusted-control-checkout>
```

OPS03:

- requires one explicit full 40-character SHA;
- creates/uses an independent Preview clone with its own Git directory;
- proves Preview/Stable/control checkout separation;
- proves Preview DB cannot alias production DB;
- composes candidate Prepare + Validate;
- leaves Preview pinned to the selected SHA;
- does not follow newer `main`;
- does not Start or directly migrate.

For owner UAT, populate Preview only with a verified physical copy/synthetic DB after the isolation boundary is prepared. Never point Preview at production SQLite.

The first real release UAT for `v0.9.0` passed on exact SHA `c90a842ec5e85fc5ac0de4aedd5d7fd14c09ae36`.

## 7. Explicit Stable update

Use only for one real owner-selected **published immutable release**.

Run from a trusted control checkout outside mutable Stable:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\update-stable.ps1 `
  -StableCheckout <stable-checkout-path> `
  -TargetVersion X.Y.Z
```

Optional parameters:

- `-DatabasePath <absolute-path>` — explicit production SQLite path;
- `-BackupDirectory <path>` — explicit backup directory;
- `-ControlCheckout <path>` — explicit trusted control checkout.

The updater:

1. proves current Stable identity;
2. proves the target is a published annotated release;
3. creates a verified SQLite backup before Git/ref/worktree mutation;
4. fetches only the selected tag;
5. proves the fetched annotated tag/code identity;
6. pins Stable to the exact target commit;
7. runs target Prepare + Validate;
8. stops.

It never:

- chooses latest automatically;
- follows `main`;
- updates Preview;
- starts Hermes;
- runs DB migration;
- creates a tag/release;
- performs automatic rollback/downgrade.

## 8. Proven real OPS02 example

First real owner transition:

`v0.8.2 -> v0.9.0`

Verified owner evidence:

- source HEAD: `a22542d7b20ebdf34e38384004162d409f163ab3` / tag `v0.8.2`;
- verified backup id: `finance_backup_20260917T144656192481Z`;
- target HEAD: `c90a842ec5e85fc5ac0de4aedd5d7fd14c09ae36`;
- `v0.9.0^{}` peeled locally to the same SHA;
- production DB hash unchanged by OPS02 before explicit Start;
- target Prepare + Validate passed;
- no application Start or DB migration occurred inside OPS02.

Then owner explicitly ran deterministic Start:

- readiness smoke: PASS;
- health: `status=ok`, `version=0.9.0`;
- owner data continuity: PASS.

This is the canonical evidence that the release-transition flow works on a real owner Stable runtime.

## 9. Normal future release sequence

For a normal future Stable release:

1. prepare one exact candidate on canonical `main`;
2. use OPS03 for isolated exact-SHA owner UAT;
3. owner PASS;
4. publish that same exact code identity through #124;
5. independently verify annotated tag + peeled commit + published Release;
6. stop Stable runtime;
7. use OPS02 to update Stable to the selected version;
8. verify target exact pin + backup evidence;
9. explicitly Start Stable;
10. verify health/version and owner data continuity.

Publication, Stable mutation and Start are intentionally separate actions.

## 10. Failure handling

If any operation fails:

- do not improvise by manually editing launcher profile JSON or refs;
- do not repoint Preview/Stable DB paths to bypass guards;
- do not retry with another commit/version unless the failure is understood;
- preserve the verified backup and error output;
- diagnose the bounded operation that failed.

The architecture is designed so an update failure does not automatically imply Start, migration, Preview mutation or release publication.

## 11. Launcher future

The runtime redesign parent #313 is complete after the successful real `v0.8.2 -> v0.9.0` owner transition.

Future launcher work is optional:

- thin UX wrappers over accepted owner operations may be valuable;
- diagnosis/recovery may be added as bounded operations if real owner pain justifies them;
- do **not** rebuild the old monolithic launcher updater/state machine.

## 12. Safety reminders

- Production Stable data is never an agent/dev workspace.
- Preview/UAT uses a separate checkout and isolated DB copy/synthetic DB.
- Do not point arbitrary branches at the production DB.
- Do not expose production `.env`, DB, backups, exports or credentials to development agents.
- Stable update remains explicit, backup-first and immutable-release based.
- Ordinary runtime remains loopback-only.

## 13. Protected off-site recovery points and DR rehearsal

The supported v1 mode is `external_encrypted_destination_v1`. The configured
destination must be the writable view of an Owner-managed encrypted
container/volume that the Owner has already successfully opened or mounted
and that is readable and writable by the supported workflow. Its encrypted
backing storage is synchronized off-device.
An ordinary Google Drive, OneDrive, Dropbox, Syncthing, NAS, or other synced
folder is not protected merely because it synchronizes. Hermes proves local
publication and read-back, not cloud delivery.

The managed publisher is an explicit Owner command; it does not perform cloud
delivery, retention deletion, restore, or disaster-recovery rehearsal. Do not
improvise a raw database copy or archive operation.

### Owner preconditions

Before a real run, the Owner must attest outside Git that:

1. the existing encrypted container/volume is already successfully
   opened/mounted and is readable and writable;
2. recovery material is available independently of the backed-up laptop; and
3. the destination is not production data, a Stable/Preview/development
   checkout, the normal local backup directory, or an ambiguous/reparse-linked
   path.

Hermes records only:

```text
protection_state=protected
protection_mode=external_encrypted_destination_v1
format_version=1
```

Hermes does not validate or authenticate the key or recovery material.
Independent availability of recovery material remains an Owner-controlled UAT
gate. Keys, credentials, full private paths, financial values, and raw
recovery payloads must never enter Git, CI, logs, or Worker workspaces.

### Publication sequence

From a trusted prepared checkout, invoke the bounded publisher explicitly:

```powershell
uv run --project backend --locked hermes-finance-protected-backup `
  --database <trusted-local-database> `
  --destination <already-opened-protected-destination> `
  --checkout <trusted-producing-checkout> `
  --protection-state protected `
  --protection-mode external_encrypted_destination_v1
```

The command emits only privacy-safe machine-readable `created`, `verified`,
`published`, `read_back`, and `action_required` state plus destination alias,
format/protection identity, artifact size, and creation time. A
successful `published=true` result requires final read-back verification. The
command does not accept caller-supplied producer SHA or Alembic revisions;
those are derived from the trusted checkout and consistent snapshot.

Follow this sequence:

1. validate the already-mounted, readable/writable protected boundary and
   acquire its exclusive publication lock;
2. create a consistent SQLite snapshot through the accepted online-backup
   path;
3. stage under the destination's unique incomplete name;
4. validate manifest/hashes, SQLite integrity, foreign keys, and
   schema/migration identity;
5. atomically expose the exact managed final name on the same filesystem;
6. read back and fully verify the final artifact;
7. report `published`/`verified` only after read-back succeeds;
8. retain the newest 12 verified managed recovery points, with no age-based
   expiry/deletion in v1, only after that verified replacement exists.

Interrupted, stale, corrupt, foreign, or unknown files are never recovery
points and are never eligible for retention. A failed next run must preserve
the newest verified point. Lock contention and ambiguous destination identity
fail closed.

### Isolated recovery rehearsal

The supported rehearsal obtains the protected artifact and independently held
recovery material after the encrypted container/volume has already been
opened/mounted and is readable. The Owner explicitly selects one immutable
full 40-character recovery Git SHA and an independent checkout pinned exactly
to it; a branch/ref-only, ambiguous, dirty, or non-independent checkout is
not eligible. The selected recovery SHA may differ from the producer SHA when
the schema compatibility gate accepts a forward upgrade. Then:

1. verifies the manifest, hashes, producer full SHA, exactly sorted source
   Alembic revision set, protection state, container readability, SQLite
   integrity, and foreign keys before any target mutation; Hermes does not
   validate or authenticate the key or recovery material;
2. loads the selected checkout's Alembic graph and supported head set and
   accepts only `same_revision` (source set equals supported heads) or one
   unambiguous supported `forward_upgrade` path from source set to those
   heads;
3. rejects unknown, ahead, divergent, downgrade-required, ambiguous, or
   multiple unsupported schema paths before target mutation;
4. restores only into a fresh isolated Finance checkout/profile/data/database
   boundary;
5. rejects Stable, Preview, development workspaces, source/local-backup
   aliases, reparse/linked paths, non-empty targets, and conflicting targets;
6. preserves the source recovery artifact unchanged;
7. re-reads the selected checkout SHA and clean state immediately before the
   restore write; if migration occurs, performs a new re-check immediately
   before migration; and if Start occurs, performs another new re-check
   immediately before Start. Any identity change fails closed before target
   mutation where possible and never proceeds to migration/Start;
8. validates broad non-private structural counts;
9. composes ADR 0014 schema-preflight with the exact-checkout
   Prepare/Validate and deterministic Start/readiness path; and
10. confirms the restored application can read months and core financial
   surfaces.

Successful privacy-safe rehearsal evidence binds the managed artifact
identity/hashes, producer SHA, sorted source revision set, selected recovery
SHA, selected checkout head set, accepted relationship, and resulting
readiness/schema/code identity. It contains no financial values, private
paths, secrets, or recovery material.

Never overwrite Stable, restore through an arbitrary code/schema path, or
claim cloud delivery or Owner UAT from a local synthetic rehearsal.

### Restore read-state requirement

After a successful existing in-app restore, the month list must reload from
the restored database. Keep the selected month only if its ID exists in the
restored list; otherwise select the allowed restored fallback or clear the
selection when the list is empty. A stale pre-restore month list or ID must
not remain visible as current. The focused implementation is tracked by
#462; this runbook does not add a second UI state system.

### Owner completion gates

Real use remains Owner-controlled and requires all of the following after
synthetic implementation acceptance:

- one protected, destination-read-back-verified recovery point in the
  intended off-device workflow;
- independently held recovery material; and
- one clean isolated disaster-recovery rehearsal.

Failure keeps the prior verified point and its evidence. Preserve the failure
output and action required; do not bypass the protection or isolation guards.

## References

- #313 — completed launcher/runtime redesign parent
- #380 / PR #385 — OPS01 Prepare + deterministic Start
- #386 / PR #393 — OPS02 explicit Stable update
- #404 / PR #407 — OPS03 exact-SHA Preview/UAT
- #408 / PR #409 — v0.9.0 release preparation
- #124 — permanent guarded Release Control
- #410 — non-blocking v0.9.0 Release-description cleanup
- `docs/CURRENT_STATUS.md`
- `docs/R09_RUNTIME_RELEASE_CLOSEOUT_2026-09-17.md`
- `docs/RELEASE_AUTOMATION.md`
- `scripts/prepare-runtime.ps1`
- `scripts/start-local.ps1`
- `scripts/prepare-preview.ps1`
- `scripts/update-stable.ps1`
- [`ADR 0017`](adr/0017-protected-offsite-backup-and-recovery.md) — protected off-site recovery-point and isolated-DR contract
