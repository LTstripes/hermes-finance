# Hermes Finance Windows launcher

`HermesFinance.Launcher.exe` is the small Windows-first owner launcher defined by ADR 0014. It shows only locally configured runtime profiles; it does not list Git branches. The only Git mutation available to the owner is the explicit Preview update action described below.

## Build/package

Install the .NET 8 SDK, then run from this directory:

```powershell
.\package.ps1
```

The script runs the automated safety harness and publishes a self-contained single-file `win-x64` executable to `artifacts\win-x64\HermesFinance.Launcher.exe`. Build artifacts are ignored and must not be committed.

For an owner-facing install, run from this directory:

```powershell
.\install.ps1
```

This packages the launcher, copies it and its bundled read-only helpers to `%LOCALAPPDATA%\HermesFinance\launcher`, and creates/updates `Hermes Finance.lnk` on the Desktop and in the Start menu. The shortcuts never target a checkout, worktree or task artifact directory. Use `-SkipStartMenuShortcut` when only the Desktop shortcut is wanted. Release and synthetic tests may pass `-PackageDirectory` to install an already-built package and `-ShortcutDirectory` to keep the shortcut outside the real Desktop.

## Owner configuration

Copy the redacted example to the owner-local path below and replace only the placeholders with prepared owner runtime paths:

```text
%LOCALAPPDATA%\HermesFinance\launcher\config.json
```

The config may contain no secrets. Each profile names an independent checkout, data directory and database. `Stable` must exactly match `canonical_production`; Preview and Experiment must match none of it. Preview/Experiment databases that already exist require a matching `.hermes-data-identity.json` sidecar. For a fresh safe profile, the launcher writes the minimal sidecar only after the guarded startup reports health ready.

For an owner UAT copy, follow ADR 0014 §7: create/select a production backup by the existing backup mechanism, copy it only into the stopped Preview runtime, then write a `kind=preview` sidecar. This executable never copies Preview data back to Stable and never refreshes it implicitly.

## Normal owner use

For an already prepared Stable runtime, normal use is entirely through the packaged executable: open `HermesFinance.Launcher.exe` (or a Windows shortcut to it), select the green `STABLE · PRODUCTION` card, and click `Запустить`. Preview is shown as a visually separate violet `PREVIEW · ISOLATED` card with its own data-boundary label. No Git command or branch switching is part of normal use. The launcher validates the configured checkout/data tuple and starts only that prepared runtime.

The owner-facing view shows readiness, profile identity, data boundary, current/target code SHA and four concise checks: code identity, data boundary, locked dependencies and loopback service. Selecting a profile or clicking `Обновить проверку` runs the read-only preflight before startup. If either locked dependency environment is missing or stale, the single primary action becomes `Подготовить`; it runs the bundled selective preparation helper (`uv sync --locked`, `npm ci`) and does not start Hermes. `Исправить` is a separate explicit recovery action that force-runs both locked dependency operations, even when the read-only check currently reports ready. Only after preparation succeeds does `Запустить` become enabled; a normal Start never downloads or reinstalls dependencies.

For the configured Preview profile, the owner can click `Обновить Preview` or `Обновить и запустить`. The launcher rechecks the clean, conflict-free expected checkout, fetches only `origin/main`, displays the fetched target SHA, and fast-forwards only that Preview checkout to the target. A clean Preview already at `origin/main` is also accepted even when `expected_ref` still names the previous prepared release, so `config.json` does not need editing when main is unreleased. Dirty, conflicted, diverged or otherwise unexpected checkouts fail closed. The action never runs against Stable, never changes a database or data sidecar, and is never started in the background. `Обновить и запустить` is itself an explicit owner action: when the updated Preview needs dependencies, it may run selective preparation before the guarded startup; a plain `Запустить` never does.

`Открыть Hermes` is enabled only after the existing health probes emit the ready marker. While a profile is running, `Остановить` terminates the launched guarded startup process and its child process tree. `Запустить` becomes available again after the process exits. Preview development no longer requires a terminal for the canonical `origin/main` update path. Moving a Preview checkout to any other branch or commit remains outside the launcher and must be handled by the integrator.

The primary view never displays raw filesystem paths or process diagnostics. `Диагностика и логи` opens a separate technical layer for troubleshooting; it is opt-in and does not change preflight or startup behavior.

## Preconditions and failure handling

The launcher requires Git, `uv`, Node.js/npm, and the .NET runtime only at build time (the packaged executable is self-contained). It carries its read-only schema probe and dependency preparation/repair helper, so an older selected checkout need not contain either helper. Read-only dependency and schema probes use offline mode; network-capable `uv sync --locked`, `npm ci`, and Preview Git update operations occur only after the owner clicks the corresponding action. Before it invokes PowerShell, it rejects malformed/unknown config fields, tuple aliases to production, missing runtime layout, unexpected/dirty Stable or Preview Git state, linked worktrees, unsafe sidecars, unreadable/unknown/ahead SQLite schema, and a busy port 8000.

After a successful preflight it invokes only the selected checkout's existing guarded `scripts/start-local.ps1`. The bundled schema probe receives the selected checkout path and reads that checkout's Alembic graph; it never migrates the database. The launcher passes the resolved, validated profile database as the child-process `HERMES_FINANCE_DATABASE_PATH`, which takes precedence over a checkout `.env`; the startup script therefore cannot migrate a different database than the one the launcher checked. The script remains responsible for frontend build, migrations, loopback bind and its three health probes. The window streams dependency/startup logs, keeps the last launch status visible, and opens `http://127.0.0.1:8000` only after the guarded script reports readiness.

## Explicit Stable upgrade lifecycle

The launcher does not choose a release, pull Git or switch a checkout. For a Stable upgrade, the owner/integrator must first create a backup, stop Hermes, prepare the independent released checkout at its immutable expected tag, then run `install.ps1` from that prepared checkout if the packaged launcher itself needs updating. On the next Stable start, the launcher validates the exact tag, checks the selected database read-only, prepares only missing/stale locked dependencies, and lets the existing guarded startup perform its normal Alembic upgrade against that same validated Stable database. Preview data is never read or copied by this lifecycle.

## Synthetic UI smoke

The safety harness includes a synthetic-only visual mode. It loads no checkout, database, `.env`, sidecar or owner data:

```powershell
dotnet run --project .\HermesFinance.Launcher.SafetyTests\HermesFinance.Launcher.SafetyTests.csproj --configuration Release -- --synthetic-ui-smoke
```

Use it to inspect the Stable-ready, Preview-blocked and opt-in diagnostics states on Windows, then close the window normally.
