# Hermes Finance — owner runtime operations

> Owner-facing operational guide for the current post-OPS01/OPS02 architecture.
>
> This is not a release checklist. Release publication remains documented in `docs/RELEASE_AUTOMATION.md` and controlled through permanent issue #124.

## 1. Architecture in one sentence

Hermes Finance no longer asks one launcher state machine to own release discovery, Git mutation, backup, dependency preparation and runtime startup.

The accepted model is composable:

- launcher = owner-facing profile/status/start/stop shell;
- Prepare/Validate = `scripts/prepare-runtime.ps1`;
- deterministic Start = `scripts/start-local.ps1`;
- Stable release switch = `scripts/update-stable.ps1`;
- release publication = guarded GitHub Release flow (#124).

## 2. Current published Stable

Current published Stable is **v0.8.2**.

The published release predates OPS01/OPS02. The new composable operations are canonical on development `main` and will first exist inside a future published target release when that release is cut from canonical `main`.

Do not move production Stable to development `main` merely to exercise the new scripts.

## 3. Existing Windows launcher

The launcher is still valid for its bounded role:

- show current Stable/Preview profile identity/status;
- start/stop the currently configured runtime;
- open Hermes after health is ready;
- provide owner-facing diagnostics/status;
- install/package shortcuts.

It is **not** the canonical Stable release updater.

If the current v0.8.2 launcher is already installed, it can be opened from the existing Desktop/Start menu shortcut and used for ordinary current-profile Start/Stop.

If it needs reinstalling from the published Stable checkout:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\launcher\windows\install.ps1
```

Do not use the legacy launcher self-update experiment as release-update evidence.

## 4. Prepare an exact checkout

For a checkout that contains OPS01:

```powershell
$checkout = (Get-Location).Path
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\prepare-runtime.ps1 `
  -Checkout $checkout `
  -Prepare
```

Prepare:

- installs/synchronizes only locked dependencies needed for that exact checkout;
- builds the production frontend;
- writes ignored `.hermes-runtime-prepared.json` proof;
- does not start Hermes;
- does not move Git refs;
- does not follow `main`;
- does not mutate another checkout.

Validate the existing prepared proof:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\prepare-runtime.ps1 `
  -Checkout $checkout `
  -Validate
```

If code, lock/build inputs or required artifacts changed, validation fails closed and owner explicitly prepares again.

## 5. Deterministic Start

From an already prepared checkout:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-local.ps1
```

The ordinary Start path:

- validates prepared-runtime proof;
- validates the selected runtime/database boundary;
- runs accepted guarded startup/migration semantics for that selected DB;
- binds only `127.0.0.1:8000`;
- performs health checks;
- does not run dependency sync/build/Git update itself.

Short smoke that exits after ready:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-local.ps1 -ExitAfterReady
```

## 6. Explicit Stable update

Use this only for a real owner-selected published immutable target release.

The command must be launched from a trusted **control checkout outside the mutable Stable checkout**:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\update-stable.ps1 `
  -StableCheckout <stable-checkout-path> `
  -TargetVersion X.Y.Z
```

Optional parameters:

- `-DatabasePath <absolute-path>` — explicit production SQLite path;
- `-BackupDirectory <path>` — explicit backup directory;
- `-ControlCheckout <path>` — explicit trusted control checkout.

The updater proves the published annotated target before mutation, performs a verified SQLite backup before Git/ref/worktree mutation, fetches only the selected tag, pins Stable to the exact target commit, runs the target release's Prepare + Validate, then stops.

It never:

- chooses latest automatically;
- follows `main`;
- updates Preview;
- starts Hermes;
- runs DB migration;
- creates a release/tag;
- performs automatic rollback/downgrade.

## 7. First real OPS02 UAT

The OPS02 implementation and CI are accepted, but the real Stable release-to-release owner operation is still pending.

Reason: there has not yet been a newer real published Stable release after OPS02 landed.

The correct first production UAT is:

1. prepare and publish the next genuine Stable release from canonical `main` through the guarded release flow;
2. leave current production Stable on v0.8.2 until the owner explicitly starts the update operation;
3. from a trusted control checkout run `update-stable.ps1` targeting that exact published version;
4. verify backup evidence and exact target pinning;
5. verify target Prepare/Validate succeeded;
6. explicitly start the target runtime;
7. verify runtime version/health and owner data continuity;
8. record owner PASS/FAIL in #313.

Do not publish a throwaway version merely to test this.

## 8. What can safely be tested before the next release

Safe now:

- current launcher Start/Stop against its current pinned v0.8.2 profile;
- launcher package/install smoke;
- Prepare/Validate/Start on non-production checkout with synthetic or isolated UAT data;
- repository synthetic update tests and temporary real-Git smoke already exercised in CI;
- a no-op/read-only inspection of current release state where it does not mutate Stable.

Not a substitute for the pending owner gate:

- targeting the same already-installed v0.8.2 version;
- running updater only on a synthetic checkout;
- moving production Stable to unreleased `main`;
- manually editing launcher expected refs to make a new checkout look accepted.

## 9. Launcher future

#313 intentionally remains open.

Next accepted runtime direction is to build the remaining small operations first, then decide whether launcher wrapping creates enough owner value.

The next bounded candidate is exact Preview/UAT preparation pinned to one explicit candidate SHA. A Preview/UAT session must not silently follow newer `main` while owner UAT is in progress.

Only after the composable operations are proven should the project decide whether launcher should become a thin wrapper around them.

## 10. Safety reminders

- Production Stable data is never an agent/dev workspace.
- Preview/UAT uses a separate checkout and isolated DB copy/synthetic DB.
- Do not point arbitrary branches at the production DB.
- Do not expose production `.env`, DB, backups, exports or credentials to development agents.
- Stable update must remain explicit, backup-first and immutable-release based.
- Ordinary runtime remains loopback-only.

## References

- #313 — launcher/runtime redesign parent
- #380 / PR #385 — OPS01 Prepare + deterministic Start
- #386 / PR #393 — OPS02 explicit Stable update
- `docs/CURRENT_STATUS.md`
- `docs/RELEASE_AUTOMATION.md`
- `scripts/prepare-runtime.ps1`
- `scripts/start-local.ps1`
- `scripts/update-stable.ps1`
