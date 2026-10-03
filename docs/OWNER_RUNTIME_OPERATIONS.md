# Hermes Finance — owner runtime operations

Current guide, synchronized 2026-10-03 after completed #679/#666 relocation. Publication is separate: [RELEASE_AUTOMATION](RELEASE_AUTOMATION.md), permanent #124. [OWNER_MACHINE_LAYOUT](OWNER_MACHINE_LAYOUT.md) owns the current roles and local mapping, including the active deployed Ops directory. Do not restart migration or reinstall Launcher from historical instructions.

## 1. Architecture in one sentence

Hermes uses separate explicit Prepare/Validate, deterministic Start, exact-SHA Test preparation, backup-first Stable release transition and guarded publication; no Launcher is required.

- Prepare/Validate: `scripts/prepare-runtime.ps1`.
- Start: `scripts/start-local.ps1`.
- Preview/UAT role in the persistent Test folder: `scripts/prepare-preview.ps1`.
- Stable release transition: `scripts/update-stable.ps1` from trusted Main/Control.
- Publication: guarded #124.

#313 composable-runtime redesign is complete. A failure in one operation does not automatically authorize Start, migration, Test mutation or release publication.

## 2. Current published Stable

Published and locally confirmed **v1.1.0**: `32c905cfc938fd1aeaeb67643eb6fa77e8644a64`; annotated tag object `9b402190bafc5d8415b217580da5e18ed35a6331`. Expected `/api/health` version is `1.1.0`. Release push CI `36776904188` and Guarded Release `36777962224` succeeded.

#572 is Owner PASS WITH DOCUMENTED LIMITATIONS. The later filesystem operation moved the same release, preserved DB identity/content/schema, recreated its path-bound Python environment with supported locked preparation and passed Start/readiness. It did not promote current main. [Release record](releases/1.1.0.md); [actual migration/closeout](https://github.com/LTstripes/hermes-finance/issues/679#issuecomment-5973182455).

At closeout, persistent Test retains `d282d09647f129cd83c99e14a10024901a1cf6da` and independent data. Re-preparation/isolation are reported; Test Start was not run simultaneously with Stable on port 8000. A remote docs merge updates neither local Main nor either runtime automatically.

## 3. Windows launcher

The installed local Launcher/config/shortcuts were removed by Owner decision. Do not repair/reinstall/test the shell merely to operate the new paths. Direct Start is the normal Owner route. Remaining repository source/package/tests/workflows are tracked by #629; removal must preserve shared runtime/recovery helpers, even when a helper or schema name contains `launcher`.

The old compact-shell/self-updater installation instructions are historical. [R09 closeout](R09_RUNTIME_RELEASE_CLOSEOUT_2026-09-17.md) retains why operations were separated; no new UI wrapper is authorized here.

## 4. Prepare an exact checkout

From the selected checkout, using its own scripts:

```powershell
$checkout = (Get-Location).Path
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\prepare-runtime.ps1 `
  -Checkout $checkout `
  -Prepare
```

Prepare installs/synchronizes locked dependencies, builds the production frontend and records ignored `.hermes-runtime-prepared.json` proof. It does not Start, follow main, move Git refs or mutate another checkout.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\prepare-runtime.ps1 `
  -Checkout $checkout `
  -Validate
```

Changed code/build/lock inputs or missing artifacts invalidate preparation. Windows console-script entry points may embed absolute interpreter paths: after an approved move, recreate/reprepare the environment at its destination using the exact release and locked dependencies. Do not hex-edit launchers, use permanent junctions, reuse a moved venv blindly or change DB identity to bypass readiness.

## 5. Deterministic Start

From an already prepared Stable or Test checkout:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-local.ps1
```

Start validates prepared proof, uses the assigned DB boundary, applies only the accepted guarded startup/schema semantics for that DB, binds `127.0.0.1:8000` and checks health. It does not install/build/update Git itself. Only one runtime owns port 8000; stop the owned runtime before switching to Test, never kill an unrelated process by port.

Readiness smoke:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-local.ps1 -ExitAfterReady
```

A source/version-preserving filesystem migration does not authorize a production schema/version upgrade. Normal future release startup follows that release's accepted schema contract.

## 6. Exact Preview/UAT preparation

The Preview role now uses one persistent Test location. Refresh that location through supported OPS03, not by creating a new top-level stand for every UAT or bypassing its existing-path protections.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\prepare-preview.ps1 `
  -CandidateSha <full-40-char-sha> `
  -PreviewCheckout <test-checkout-path> `
  -PreviewDataDirectory <isolated-test-data-path> `
  -PreviewDatabase <isolated-test-db-path> `
  -StableCheckout <stable-checkout-path> `
  -StableDataDirectory <stable-data-path> `
  -StableDatabase <stable-db-path> `
  -ControlCheckout <trusted-main-checkout>
```

OPS03 requires a full SHA, independent Git clone and physically separate Test data; it proves the Stable/Main/Test exclusions, composes candidate Prepare/Validate and leaves the exact candidate pinned. No follow-main, Start or direct migration occurs inside it. The historical parameter names remain unchanged; Main is the Control role, Test is Preview.

Populate Test only through an explicitly approved isolated copy/recovery/synthetic workflow. Never point Test at production SQLite or copy its data back to Stable. Retain needed Test artifacts before a deliberate refresh. No agent receives the private DB/.env/backup contents. Current Owner checks and exact UAT scopes are in [CURRENT_STATUS](CURRENT_STATUS.md).

## 7. Explicit Stable update

Run OPS02 from trusted canonical Main outside mutable Stable for one Owner-selected published immutable release:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\update-stable.ps1 `
  -StableCheckout <stable-checkout-path> `
  -TargetVersion X.Y.Z
```

Optional `-DatabasePath`, `-BackupDirectory` and `-ControlCheckout` retain their supported meanings. The updater proves current Stable and target annotated publication, makes a verified SQLite backup before Git/ref mutation, fetches only the selected tag, pins the exact peeled commit, runs target Prepare/Validate and stops.

It never selects latest, follows main, updates Test, starts Hermes, runs DB migration, publishes a tag/release or automatically rolls back/downgrades. Publication, local update and Start remain separate Owner actions.

## 8. Proven real OPS02 example

The first real `v0.8.2 -> v0.9.0` transition and subsequent Start/data-continuity PASS remain recorded in [R09_RUNTIME_RELEASE_CLOSEOUT_2026-09-17](R09_RUNTIME_RELEASE_CLOSEOUT_2026-09-17.md). They are historical proof, not current version instructions.

## 8A. Second real owner transition — v1.0.0

The `v0.9.0 -> v1.0.0` backup-first transition, exact-SHA UAT, publication, production Start and data-continuity PASS remain in [R10_RELEASE_CLOSEOUT_2026-09-21](R10_RELEASE_CLOSEOUT_2026-09-21.md). Current Stable is v1.1.0; dated predecessors are not pending updates.

## 9. Normal future release sequence

Prepare one exact canonical candidate → isolated Test UAT → Owner acceptance → guarded publication through #124 → independent tag/release read-back → stop owned Stable → explicit backup-first OPS02 → target pin/preparation read-back → explicit Start → health/version and data-continuity check.

Do not call a GitHub merge a release or a runtime update. Filesystem relocation and janitor deployment do not promote code versions.

## 10. Failure handling

Diagnose the failing bounded operation and preserve the existing backup/error evidence. Do not improvise DB rebinding, refs, runtime profile JSON, another version or an unsafe retry. Ambiguous restore/write outcomes are not success or confirmed failure and must not be blindly replayed. During a relocation, a failed Stable readiness check is resolved or rolled back before unrelated legacy deletion.

An authorized local operations Worker executes the bounded workflow and reports sanitized results; the Owner is not assigned repeated JSON/PowerShell diagnostic relays. That exception does not grant ordinary development tasks runtime access. Existing exact-release/privacy guards remain authoritative.

## 11. Launcher state after #585 / #586

#585 path-gating and #586 compact shell are historical implementation evidence. Local removal is complete; #629 repository retirement remains pending. No further Launcher installation or UX work is implied. Shared direct startup, backup, prepared-runtime and recovery contracts remain in force until their consumers are deliberately reconciled.

## 12. Safety reminders

Stable/Main/Test/Owner and active Ops are protected, including deployed Ops outside the Hermes root. Do not treat all outside-root folders as old workspaces. Test is isolated from Stable, and main is not a production runtime. No private payloads in Git/CI/Worker artifacts. Stable updates are explicit, backup-first and release-pinned. Normal runtime remains loopback-only.

Daily housekeeping is separate from runtime operations: [WORKSPACE_JANITOR](WORKSPACE_JANITOR.md). The accepted deployment is daily 12:00 local/Apply/7 days, not a new provider refresh or release task. One dry-run passed; future automatic results must be read from the local report, not inferred from deployment.

## 13. Protected off-site recovery points and DR rehearsal

The accepted publisher/rehearsal contracts are unchanged. [ADR 0017](adr/0017-protected-offsite-backup-and-recovery.md) and [Owner durability closeout](OWNER_DURABILITY_CLOSEOUT_2026-09-25.md) are authoritative. The detailed pre-closeout runbook is retained [at its pinned version](https://github.com/LTstripes/hermes-finance/blob/8eb991fc81ebbe63917a9ca1ea204762129c9019/docs/OWNER_RUNTIME_OPERATIONS.md#13-protected-off-site-recovery-points-and-dr-rehearsal); its old current-version/Launcher-install sections are not today's setup instructions.

### Modes and Owner preconditions

`protection_state=protected`, `protection_mode=external_encrypted_destination_v1`, `format_version=1` requires an already opened/mounted readable/writable Owner-managed encrypted container/volume and independently available recovery material. Hermes does not validate/authenticate the key. A plain synced directory is not encrypted merely because it synchronizes.

The separately Owner-accepted pair is `owner_accepted_plaintext` / `synced_filesystem_destination_v1`. It supports an ordinary synced filesystem destination without claiming protected-at-rest encryption. Do not reclassify existing encrypted attestations. Any other pair fails closed. Aliases remain `protected-destination` and `synced-filesystem-destination`.

For either mode the destination must not alias production, Stable/Test/development, local backups or an ambiguous/reparse-linked path. Owner selects and attests the appropriate mode outside Git. Credentials, recovery material and private paths/payloads remain local. Local publication/read-back does not prove cloud delivery; off-device visibility is a separate Owner fact.

### Publication sequence

Use the existing bounded publisher explicitly from its own trusted producing checkout:

```powershell
uv run --project backend --locked hermes-finance-protected-backup `
  --database <trusted-local-database> `
  --destination <already-opened-protected-destination> `
  --checkout <trusted-producing-checkout> `
  --protection-state protected `
  --protection-mode external_encrypted_destination_v1
```

For an accepted ordinary synced directory use `--protection-state owner_accepted_plaintext --protection-mode synced_filesystem_destination_v1`. The optional checkout is an identity guard for the executing producer, not a selector for fabricated SHA/schema. Producer SHA and Alembic revisions are derived from the actual checkout and consistent snapshot.

The command locks the destination, creates a consistent SQLite online-backup snapshot, stages uniquely, verifies manifest/hashes/schema/migration identity, exposes atomically on the same filesystem and reads back the final artifact before claiming `published=true`. It reports bounded state/identity/size/time, not payloads or cloud delivery.

Only after a verified replacement exists does retention keep the newest 12 verified managed points of the same protection pair. A mixed destination keeps 12 per pair; plaintext cannot remove encrypted-mode points or vice versa. No age expiry in v1. Unknown/partial/corrupt/foreign files remain untouched. Retention failure is separate from successful publication; a failed next run preserves the newest verified point. Do not replace the supported workflow with an improvised raw DB/archive copy.

### Isolated recovery rehearsal

Select one readable managed point matching the requested protection pair and one explicit full recovery SHA. Use a clean detached independent code checkout and a fresh Owner-only target, not Stable/Test/development, a source/local-backup alias, linked/reparse path or prior failed target.

The wrapper verifies managed name/manifest/full snapshot hashes, producer SHA/revisions, protection pair and SQLite integrity/foreign keys. Schema must be `same_revision` or one supported unambiguous forward upgrade. Ahead/divergent/downgrade/unknown graphs are refused before target mutation. It preserves the source artifact, rechecks code identity before restore/migration/Start, checks structural counts and composes exact checkout Prepare/Validate/readiness.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File (Join-Path $recoveryCheckout "scripts\recovery-rehearsal.ps1") `
  -RecoveryCheckout $recoveryCheckout `
  -RecoveryPoint $recoveryPoint `
  -RecoverySha $recoverySha `
  -ControlCheckout $controlCheckout `
  -RuntimeConfig $runtimeConfig `
  -TargetProfile $targetProfile `
  -TargetData $targetData `
  -TargetDatabase $targetDatabase `
  -ProtectionState protected `
  -ProtectionMode external_encrypted_destination_v1
```

All variables are explicitly verified Owner-local values. For plaintext use the matching accepted pair. Target profile/data/database must not already exist. The runtime-config argument remains an exclusion input of the accepted helper even if its type/name mentions Launcher; use a supported current mapping, never an obsolete deleted shell file or a guessed replacement. #629 must preserve/reconcile this consumer before deleting shared profile/schema helpers. Do not reinstall the GUI just to satisfy an unexplained missing reference.

The repository wrapper proves Git/boundaries before its first uv run, establishes its checkout-local environment, pins mutable preparation outputs and owns descendants under a deadline. Do not bypass it with an inherited-environment uv command. Source/target descriptors and snapshot identity are rechecked through preparation/start. A failed or ambiguous mutated target is not reused. Synthetic rehearsal is not Owner UAT or proof of cloud delivery.

### Restore read-state requirement

After in-app restore, reread the month list from the restored DB. Keep the selected ID only if it exists; otherwise use the supported restored fallback or clear selection. Do not expose a stale pre-restore month as current (#462/#502). Confirmed-negative versus ambiguous restore outcomes retain #475 semantics.

### Owner completion evidence

#417 closed after the 2026-09-25 plaintext managed publication/read-back, separate off-device visibility and clean isolated DR all passed, including `source_unchanged=true`, `readiness=verified`, `schema_relationship=same_revision`. #543 hardening did not reopen it. A future rehearsal needs a fresh managed point and new isolated target, not a repetition mandated by docs editing.

## References

- [CURRENT_STATUS](CURRENT_STATUS.md), [SESSION_CLOSEOUT_2026-10-03](SESSION_CLOSEOUT_2026-10-03.md)
- [OWNER_MACHINE_LAYOUT](OWNER_MACHINE_LAYOUT.md), [WORKSPACE_JANITOR](WORKSPACE_JANITOR.md)
- [R09 closeout](R09_RUNTIME_RELEASE_CLOSEOUT_2026-09-17.md), [R10 closeout](R10_RELEASE_CLOSEOUT_2026-09-21.md)
- [Owner durability closeout](OWNER_DURABILITY_CLOSEOUT_2026-09-25.md), [ADR 0017](adr/0017-protected-offsite-backup-and-recovery.md)
- #380/#385 OPS01, #386/#393 OPS02, #404/#407 OPS03, #124 publication, #629 repository Launcher retirement
