# Hermes Finance Windows launcher

HermesFinance.Launcher.exe is a quiet owner-facing shell for configured,
already-prepared runtime profiles. It presents Stable production and isolated
Main/Preview profiles, exact version/SHA identity, data boundary, readiness
and running state.

The launcher owns only local profile status/preflight, read-only dependency
readiness, Start, Stop, Open Hermes, setup/reconfigure and secondary
diagnostics/logs. Ordinary Start and status refresh never fetch, fast-forward,
follow moving refs, switch Git refs, install dependencies, publish releases,
create backups or mutate Stable. Dependency preparation remains the external
OPS01 operation; Stable release transition remains OPS02; Preview/UAT
preparation remains OPS03.

Stable always uses the configured canonical production tuple. Main/Preview and
Experiment must use an independent checkout and isolated data; production data
is rejected fail closed. The launcher never receives owner databases, backups,
.env files, credentials or private payloads.

## Build and install

From this directory:

    .\package.ps1
    .\install.ps1

Packaging produces a self-contained win-x64 executable and bundles only the
approved local helpers. Installation creates shortcuts beside the installed
launcher; shortcuts never target a checkout or task artifact. Use
-SkipStartMenuShortcut and synthetic -PackageDirectory/-ShortcutDirectory
options for smoke tests.

## Normal owner workflow

1. Open the installed launcher and select Stable or isolated Preview. Selection runs a read-only preflight.
2. When the state is Готов, press Запустить.
3. If the state is Нужна подготовка, run the external OPS01 Prepare workflow, then use the recheck action.
4. When the state is Работает, press Открыть Hermes. Остановить is the small secondary action and only stops a launcher-owned process.
5. Настроить… is for a missing or invalid config, not the ordinary daily path.

Diagnostics/logs stay hidden until requested. Raw paths and database
filenames are not shown in the primary view.

## Verification

The retained launcher safety harness is synthetic/private-safe and covers
profile identity, production/isolated data boundaries, read-only dependency readiness,
process actions, owner-facing UI state and package/install guards. CI runs the
canonical package/install chain only when launcher-relevant paths change.
That chain still executes the in-process scenarios before publish. Those
scenarios are not copies of the outer smoke: the outer smoke owns the
published and installed files, the self-contained layout, the shortcut target,
and a clean worktree; the in-process scenarios own profile, process, data, and
UI fail-closed behavior. Unrelated frontend or financial changes skip the
heavy job and do not delete those scenarios. Run:

    dotnet run --project .\HermesFinance.Launcher.SafetyTests\HermesFinance.Launcher.SafetyTests.csproj --configuration Release
    .\..\..\scripts\tests\test-windows-launcher-package.ps1

Synthetic UI smoke:

    dotnet run --project .\HermesFinance.Launcher.SafetyTests\HermesFinance.Launcher.SafetyTests.csproj --configuration Release -- --synthetic-ui-smoke

All test data is synthetic. No owner/private runtime is needed.
