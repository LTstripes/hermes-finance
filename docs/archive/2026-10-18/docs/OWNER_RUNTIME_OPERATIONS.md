# Hermes Finance — owner runtime operations

Current guide; Stable identity checkpoint refreshed **2026-10-16** after accepted HONOR v1.3.0 deployment. Publication is separate: [RELEASE_AUTOMATION](RELEASE_AUTOMATION.md), permanent #124. [OWNER_MACHINE_LAYOUT](OWNER_MACHINE_LAYOUT.md) owns the roles and Owner-local mapping, including active Ops. Do not rerun the completed migration or reinstall Launcher from historical instructions.

## 1. Architecture in one sentence

Hermes uses separate explicit Prepare/Validate, deterministic Start, exact-SHA Test preparation, backup-first Stable release transition and guarded publication; no Launcher is required.

- Prepare/Validate: `scripts/prepare-runtime.ps1`.
- Start: `scripts/start-local.ps1`.
- Preview/UAT role in the persistent Test folder: `scripts/prepare-preview.ps1`.
- Stable release transition: `scripts/update-stable.ps1` from trusted Main/Control.
- Publication: guarded #124.

#313 composable-runtime redesign is complete. A failure in one operation does not automatically authorize Start, migration, Test mutation or release publication.

## 2. Current published and installed Stable (2026-10-16)

**Published:** [Hermes Finance v1.3.0](https://github.com/LTstripes/hermes-finance/releases/tag/v1.3.0), annotated tag object `13e727903c18484b8ff817f0b16f71664060c1d3` → exact commit `a9c88266fffe26e83688c52fc8f425b04fa14812`. [Exact post-main push CI #38933101012](https://github.com/LTstripes/hermes-finance/actions/runs/38933101012) and [Guarded Release #38937979090](https://github.com/LTstripes/hermes-finance/actions/runs/38937979090) completed SUCCESS.

**HONOR Stable installed and left running (Owner-local Operator evidence):** [final #836 release/UAT technical closeout](https://github.com/LTstripes/hermes-finance/issues/836#issuecomment-6222421447) attests one stock backup-first OPS02, one normal stock Start against the **same original physical production database**, guarded `0044→0058_broker_money_ownership` migration, health version 1.3.0, nine preserved CLOSED months, SQLite integrity OK/FK0 and read-only API/UI/reload PASS. This local runtime cannot be inspected directly via GitHub; a checkout or CI PASS alone is not a production health claim. The Owner's financial-semantic UAT is intentionally limited, even with a successful installation.

**Rollback:** accepted managed pre-upgrade 0044 recovery point, separate restore evidence and stock OPS02's verified additional SQLite 0044 backup remain preserved; pair old v1.2.0 code with the **matching 0044 database**, never open a migrated 0058 database with old code. [#838](https://github.com/LTstripes/hermes-finance/issues/838) remains OPEN for unverified off-device/TECNO recovery and inherited broad agent Modify ACL. Local/synced-filesystem publication/readback is **not** proof of off-device visibility or encryption.

Historical releases and earlier runtime states, including v1.1.0, remain in [v1.1.0 record](releases/1.1.0.md), [#679 migration closeout](https://github.com/LTstripes/hermes-finance/issues/679#issuecomment-5973182455) and [v1.2.0 release record](releases/1.2.0.md). They do not describe today's HONOR Stable. Preserve Test/Owner/Ops as separate roles and never infer Test's present version from an earlier dated acceptance.

## 3. Windows launcher — retired

The installed local Launcher/config/shortcuts were removed by Owner decision,
and #629 retired the remaining repository source/package/tests/workflows.
Do not repair/reinstall/test the shell merely to operate the new paths.
Direct Start is the normal Owner route. Shared backup-first update,
prepared-runtime, recovery rehearsal and `RuntimeConfig` identity/exclusion
helpers were preserved, even where a helper or schema name still mentions
`launcher`. Recovery and cleanup exclusion inputs use the direct-operations
runtime inventory defined in section 13 ([example](../../../schemas/runtime-inventory.example.json));
no Launcher shell, config UI or installation is involved.

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
  -TargetVersion X.Y.Z `
  -DatabasePath <verified-absolute-production-sqlite-path> `
  -BackupDirectory <verified-disjoint-backup-directory>
```

`-ControlCheckout` remains an optional parameter pointing to a separately verified trusted Control/Main. The updater's optional-path code defaults to its **Process environment selector or `Stable/data/finance.db`**, not to the contents of `Stable/.env`. Therefore, for the installed HONOR layout, **explicit `-DatabasePath` matching the accepted existing physical production database is mandatory in the actual operation**; choose a separate verified `-BackupDirectory` as shown. The updater proves current Stable and target annotated publication, makes and verifies a SQLite backup before Git/ref mutation, fetches only the tag, pins the exact peeled commit, runs target Prepare/Validate and stops. Do not run a new OPS02 against already installed Stable solely to confirm this documentation.

It never selects latest, follows main, updates Test, starts Hermes, runs DB migration, publishes a tag/release or automatically rolls back/downgrades. Publication, local update and Start remain separate Owner actions.

## 8. Proven real OPS02 example

The first real `v0.8.2 -> v0.9.0` transition and subsequent Start/data-continuity PASS remain recorded in [R09_RUNTIME_RELEASE_CLOSEOUT_2026-09-17](R09_RUNTIME_RELEASE_CLOSEOUT_2026-09-17.md). They are historical proof, not current version instructions.

## 8A. Second real owner transition — v1.0.0

The `v0.9.0 -> v1.0.0` backup-first transition, exact-SHA UAT, publication, production Start and data-continuity PASS remain in [R10_RELEASE_CLOSEOUT_2026-09-21](R10_RELEASE_CLOSEOUT_2026-09-21.md). These are historical predecessor states; today's installed Stable is stated in §2 above.

## 9. Normal future release sequence

Prepare one exact canonical candidate → isolated Test UAT → Owner acceptance → guarded publication through #124 → independent tag/release read-back → stop owned Stable → explicit backup-first OPS02 → target pin/preparation read-back → explicit Start → health/version and data-continuity check.

Do not call a GitHub merge a release or a runtime update. Filesystem relocation and janitor deployment do not promote code versions.

## 10. Failure handling

Diagnose the failing bounded operation and preserve the existing backup/error evidence. Do not improvise DB rebinding, refs, runtime profile JSON, another version or an unsafe retry. Ambiguous restore/write outcomes are not success or confirmed failure and must not be blindly replayed. During a relocation, a failed Stable readiness check is resolved or rolled back before unrelated legacy deletion.

An authorized local operations Worker executes the bounded workflow and reports sanitized results; the Owner is not assigned repeated JSON/PowerShell diagnostic relays. That exception does not grant ordinary development tasks runtime access. Existing exact-release/privacy guards remain authoritative.

## 11. Launcher state after #585 / #586 and #629

#585 path-gating and #586 compact shell are historical implementation evidence.
Local removal is complete and #629 retired the repository source/package/tests/jobs.
No further Launcher installation or UX work is implied. Shared direct startup,
backup, prepared-runtime and recovery contracts remain in force; their
`RuntimeConfig`/`launcher-production-backup` inputs follow the direct-operations
runtime inventory defined in section 13, not the deleted shell.

## 12. Safety reminders

Stable/Main/Test/Owner and active Ops are protected, including deployed Ops outside the Hermes root. Do not treat all outside-root folders as old workspaces. Test is isolated from Stable, and main is not a production runtime. No private payloads in Git/CI/Worker artifacts. Stable updates are explicit, backup-first and release-pinned. Normal runtime remains loopback-only.

Daily housekeeping is separate from runtime operations: [WORKSPACE_JANITOR](WORKSPACE_JANITOR.md). The accepted deployment is daily 12:00 local/Apply/7 days, not a new provider refresh or release task. One dry-run passed; future automatic results must be read from the local report, not inferred from deployment.

## 13. Protected off-site recovery points and DR rehearsal

The accepted publisher/rehearsal contracts are unchanged. [ADR 0017](../../../adr/0017-protected-offsite-backup-and-recovery.md) and [Owner durability closeout](OWNER_DURABILITY_CLOSEOUT_2026-09-25.md) are authoritative. The detailed pre-closeout runbook is retained [at its pinned version](https://github.com/LTstripes/hermes-finance/blob/8eb991fc81ebbe63917a9ca1ea204762129c9019/docs/OWNER_RUNTIME_OPERATIONS.md#13-protected-off-site-recovery-points-and-dr-rehearsal); its old current-version/Launcher-install sections are not today's setup instructions.

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

All variables are explicitly verified Owner-local values. For plaintext use the matching accepted pair. Target profile/data/database must not already exist. The `-RuntimeConfig` argument takes an Owner-local JSON file following [runtime-inventory.example.json](../../../schemas/runtime-inventory.example.json): `version` 1, `canonical_production` plus `profiles` entries each carrying absolute local `checkout`/`data_dir`/`database` paths, exactly one `stable` profile whose three paths equal `canonical_production`. The Owner creates and keeps that file outside Git at an Owner-local path, passes its explicit path on every rehearsal invocation, and never commits it with real paths. A missing, unreadable, non-version-1, incomplete or non-canonical inventory fails closed before any target is touched. Do not reinstall the GUI just to satisfy an unexplained missing reference.

The repository wrapper proves Git/boundaries before its first uv run, establishes its checkout-local environment, pins mutable preparation outputs and owns descendants under a deadline. Do not bypass it with an inherited-environment uv command. Source/target descriptors and snapshot identity are rechecked through preparation/start. A failed or ambiguous mutated target is not reused. Synthetic rehearsal is not Owner UAT or proof of cloud delivery.

### Restore read-state requirement

After in-app restore, reread the month list from the restored DB. Keep the selected ID only if it exists; otherwise use the supported restored fallback or clear selection. Do not expose a stale pre-restore month as current (#462/#502). Confirmed-negative versus ambiguous restore outcomes retain #475 semantics.

### Owner completion evidence

#417 closed after the 2026-09-25 plaintext managed publication/read-back, separate off-device visibility and clean isolated DR all passed, including `source_unchanged=true`, `readiness=verified`, `schema_relationship=same_revision`. #543 hardening did not reopen it. A future rehearsal needs a fresh managed point and new isolated target, not a repetition mandated by docs editing.

## References

- [CURRENT_STATUS](CURRENT_STATUS.md), [SESSION_CLOSEOUT_2026-10-03](SESSION_CLOSEOUT_2026-10-03.md)
- [OWNER_MACHINE_LAYOUT](OWNER_MACHINE_LAYOUT.md), [WORKSPACE_JANITOR](WORKSPACE_JANITOR.md)
- [R09 closeout](R09_RUNTIME_RELEASE_CLOSEOUT_2026-09-17.md), [R10 closeout](R10_RELEASE_CLOSEOUT_2026-09-21.md)
- [Owner durability closeout](OWNER_DURABILITY_CLOSEOUT_2026-09-25.md), [ADR 0017](../../../adr/0017-protected-offsite-backup-and-recovery.md)
- #380/#385 OPS01, #386/#393 OPS02, #404/#407 OPS03, #124 publication, #629 Launcher retirement (repository source retired; direct operations preserved)
