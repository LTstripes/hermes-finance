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

## Normal owner use

For an already prepared Stable runtime, normal use is entirely through the packaged executable: open `HermesFinance.Launcher.exe` (or a Windows shortcut to it), select `Hermes Finance — Stable`, and click `Запустить`. No Git command or branch switching is part of normal Stable use. The launcher validates the configured checkout/data tuple and starts only that prepared runtime.

While a profile is running, `Остановить` terminates the launched guarded startup process and its child process tree. `Запустить` becomes available again after the process exits. Preview development may still require an integrator to move the Preview checkout to a newly accepted commit; the launcher deliberately never performs Git updates itself.

## Preconditions and failure handling

The launcher requires Git, `uv`, Node dependencies already usable by the profile's existing `scripts/start-local.ps1`, and the .NET runtime only at build time (the packaged executable is self-contained). The packaged launcher also carries its read-only schema probe, so an older selected checkout need not contain `scripts/launcher-schema-check.py`. Before it invokes PowerShell, it rejects malformed/unknown config fields, tuple aliases to production, missing runtime layout, unexpected/dirty Stable or Preview Git state, linked worktrees, unsafe sidecars, unreadable/unknown/ahead SQLite schema, and a busy port 8000.

After a successful preflight it invokes only the selected checkout's existing guarded `scripts/start-local.ps1`. The bundled schema probe receives the selected checkout path and reads that checkout's Alembic graph; it never migrates the database. The launcher passes the resolved, validated profile database as the child-process `HERMES_FINANCE_DATABASE_PATH`, which takes precedence over a checkout `.env`; the startup script therefore cannot migrate a different database than the one the launcher checked. The script remains responsible for frontend build, migrations, loopback bind and its three health probes. The window streams startup errors and opens `http://127.0.0.1:8000` only after the guarded script reports readiness.
