# Hermes Finance Windows launcher

`HermesFinance.Launcher.exe` is the small Windows-first owner launcher defined by ADR 0014. It shows only locally configured runtime profiles; it does not list Git branches and never changes Git state.

## Build/package

Install the .NET 8 SDK, then run from this directory:

```powershell
.\package.ps1
```

The script runs the automated safety harness and publishes a self-contained single-file `win-x64` executable to `artifacts\win-x64\HermesFinance.Launcher.exe`. Build artifacts are ignored and must not be committed.

## Owner configuration

Copy the redacted example to the owner-local path below and replace only the placeholders with prepared owner runtime paths:

```text
%LOCALAPPDATA%\HermesFinance\launcher\config.json
```

The config may contain no secrets. Each profile names an independent checkout, data directory and database. `Stable` must exactly match `canonical_production`; Preview and Experiment must match none of it. Preview/Experiment databases that already exist require a matching `.hermes-data-identity.json` sidecar. For a fresh safe profile, the launcher writes the minimal sidecar only after the guarded startup reports health ready.

For an owner UAT copy, follow ADR 0014 §7: create/select a production backup by the existing backup mechanism, copy it only into the stopped Preview runtime, then write a `kind=preview` sidecar. This executable never copies Preview data back to Stable and never refreshes it implicitly.

## Preconditions and failure handling

The launcher requires Git, `uv`, Node dependencies already usable by the profile's existing `scripts/start-local.ps1`, and the .NET runtime only at build time (the packaged executable is self-contained). Before it invokes PowerShell, it rejects malformed/unknown config fields, tuple aliases to production, missing runtime layout, unexpected/dirty Stable or Preview Git state, linked worktrees, unsafe sidecars, unreadable/unknown/ahead SQLite schema, and a busy port 8000.

After a successful preflight it invokes only the selected checkout's existing guarded `scripts/start-local.ps1`. It passes the resolved, validated profile database as the child-process `HERMES_FINANCE_DATABASE_PATH`, which takes precedence over a checkout `.env`; the startup script therefore cannot migrate a different database than the one the launcher checked. The script remains responsible for frontend build, migrations, loopback bind and its three health probes. The window streams startup errors and opens `http://127.0.0.1:8000` only after the guarded script reports readiness.
