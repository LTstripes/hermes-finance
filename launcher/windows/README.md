# Hermes Finance Windows launcher — thin owner shell

`HermesFinance.Launcher.exe` is the Windows owner entry point for **already prepared, explicitly configured runtimes**.

The launcher is intentionally small. It does not publish releases, select a newer release, follow `main`, fetch or switch Git refs, back up production data for an update, or prepare dependencies. Those operations belong to the accepted external OPS01/OPS02/OPS03 scripts.

## Owner model

The primary UI shows two distinct prepared profiles:

- **Stable · Production** — the configured production runtime and canonical production database;
- **Preview · Isolated** — an independent prepared checkout pinned to one exact configured commit, with isolated data only.

For each profile the launcher shows the exact local SHA/version, data boundary and readiness/running state.

Owner actions are deliberately limited to:

- **Обновить проверку** — local read-only preflight;
- **Запустить** — start the exact configured prepared runtime;
- **Открыть Hermes** — open `http://127.0.0.1:8000` after readiness;
- **Остановить** — stop only the launcher-owned process tree;
- **Диагностика и логи** — secondary technical details;
- **Настроить…** — select/rebind prepared Stable and Preview runtimes.

There is no `Обновить Stable`, `Обновить Preview`, `Обновить и запустить`, `Подготовить` or `Исправить` action in the launcher.

## Identity and data safety

Setup/reconfigure requires Stable `HEAD` to be pinned by exactly one local annotated `vX.Y.Z` tag and stores that release ref; Preview stores its exact local `HEAD` SHA. It does not fetch, discover a newer release or infer a moving target.

Normal refresh and Start require:

- checkout `HEAD` == configured exact identity;
- Stable checkout/data/database == canonical production tuple;
- Preview checkout/data/database are independent from production;
- Preview does not share Stable's Git common directory;
- Stable/Preview checkout is clean;
- existing Preview data has the expected sidecar identity;
- database aliases/hardlinks to production are rejected;
- schema compatibility is proven when dependencies are ready;
- `127.0.0.1:8000` is available or proven to belong to the launcher-owned process.

An identity mismatch fails closed. The fix happens outside the launcher: prepare/update the intended exact runtime, then explicitly reconfigure the profile.

## Dependency readiness

The launcher **checks** locked backend/frontend dependency readiness but does not install or repair dependencies.

If a runtime is not prepared:

1. run canonical OPS01 Prepare for that exact checkout;
2. return to the launcher;
3. press **Обновить проверку**;
4. Start becomes available only after the read-only checks pass.

Canonical operation:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\prepare-runtime.ps1 `
  -Checkout <checkout> `
  -Prepare
```

## Stable update and Preview preparation

Stable release transition remains external OPS02:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\update-stable.ps1 `
  -StableCheckout <stable-checkout> `
  -TargetVersion X.Y.Z
```

Exact Preview/UAT preparation remains external OPS03:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\prepare-preview.ps1 `
  -CandidateSha <full-40-char-sha> `
  -PreviewCheckout <preview-path> `
  -PreviewDataDirectory <isolated-data-path> `
  -PreviewDatabase <isolated-db-path> `
  -StableCheckout <stable-path> `
  -StableDataDirectory <stable-data-path> `
  -StableDatabase <stable-db-path>
```

After either operation, use **Настроить…** when the configured exact identity needs to be rebound.

## Build/package

From `launcher\windows`:

```powershell
.\package.ps1
```

Packaging runs the retained launcher safety harness and produces a self-contained `win-x64` executable.

The launcher package contains only launcher-owned assets:

- `HermesFinance.Launcher.exe`;
- `hermes-finance-cat.ico`;
- `launcher-schema-check.py`;
- `config.example.json`.

OPS01/OPS02 helpers are not bundled into the GUI launcher.

Install/reinstall:

```powershell
.\install.ps1
```

The installer copies the packaged launcher assets under `%LOCALAPPDATA%\HermesFinance\launcher` and creates Desktop / Start-menu shortcuts. Package/install never mutates Git state.

## Configuration

Default config:

`%LOCALAPPDATA%\HermesFinance\launcher\config.json`

Normal setup does not require hand-editing JSON. **Настроить…** asks the owner to select already prepared Stable/Preview checkout and data directories; Stable is bound to its local annotated release tag and Preview to its exact local SHA.

`config.example.json` intentionally contains placeholders and is documentation/package input, not a silently activated runtime config.

The config contains no secrets.

## Start/Stop ownership

Start invokes only the selected checkout's guarded `scripts/start-local.ps1` with the already validated database path and offline runtime semantics.

Launcher process ownership is fail-closed and bound to profile/checkouts/data/DB/HEAD plus process identity. Stop is available only for the process tree the launcher can prove it owns. An unrelated process occupying port 8000 is never stopped by the launcher.

## Synthetic safety evidence

The safety harness uses synthetic fixtures only and must not read owner databases, `.env`, backups or private exports.

Synthetic UI smoke:

```powershell
dotnet run --project .\HermesFinance.Launcher.SafetyTests\HermesFinance.Launcher.SafetyTests.csproj --configuration Release -- --synthetic-ui-smoke
```

Canonical PR CI and exact-main push CI remain the integration gates.

For the complete owner runtime model, see `docs/OWNER_RUNTIME_OPERATIONS.md`.
