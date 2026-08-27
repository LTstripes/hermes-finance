# ADR 0014 — Launcher runtime-profile safety contract

- **Status:** Accepted
- **Date:** 2026-08-26
- **Release line:** `r07` desktop / launcher track
- **Source task:** R07-D01, parent roadmap #127
- **Implementation follow-up:** R07-D02 / issue #144
- **Related:** [`AGENTS.md`](../../AGENTS.md), [ADR 0001](0001-architecture.md), [ADR 0004](0004-localhost-request-security.md), [ADR 0012](0012-runtime-and-agent-workspace-isolation.md)

## Problem

Daily production start still requires a manual PowerShell invocation of `scripts/start-local.ps1`. The desired owner UX is a small Windows launcher with named choices, for example:

```text
Hermes Finance

● Stable
○ 0.7 Preview
○ Experiment

[ Запустить ]
```

The unsafe reading of that UX is “pick a Git branch, then start the app against the same `finance.db`”. That reading is forbidden.

The failure mode that must not be possible:

```text
experimental / preview checkout
        ↓
production finance.db
        ↓
alembic upgrade head
```

`scripts/start-local.ps1` plus `hermes-finance-api` currently apply Alembic to whatever database that checkout’s settings resolve to, then serve `127.0.0.1:8000`. A branch selector inside one runtime checkout would make schema mutation of production data an ordinary accident.

This ADR defines the safety contract. It does not ship an executable.

## Decision

A launcher **profile** is a prepared runtime tuple, not a branch name:

```text
profile = checkout + code identity + runtime configuration + data location
```

The launcher may start only a configured profile. It must not run `git checkout`, `git switch`, `git reset` or `git pull` as part of Start. Profiles point at **already created independent checkouts**. Git mutation of those checkouts remains an owner/integrator operation outside the daily Start button.

Existing guarded startup remains the process that actually boots the app:

- production-like profiles invoke that checkout’s `scripts/start-local.ps1`;
- the launcher adds validation **before** that script runs;
- `scripts/dev.ps1` (Vite `127.0.0.1:5173`) stays a development tool for agent clones. It is not a launcher profile.

Secrets stay in each checkout’s gitignored `.env`. They never appear in launcher config.

Machine-specific absolute paths are local configuration. Tracked docs must not freeze a disk letter or folder name as portable architecture (ADR 0012).

## 1. Profile model

Exactly one profile may have `type=stable`. Preview and experiment profiles may exist in any number, each with its own checkout and data.

### 1.1 Stable

| Field | Rule |
|---|---|
| Checkout | The canonical production runtime clone |
| Data | That clone’s ignored runtime data, including the real owner database |
| Startup | Existing `scripts/start-local.ps1` |
| Network | Loopback `127.0.0.1:8000` |
| Migrations | Inherit current production behaviour: `hermes-finance-api` runs `alembic upgrade head` on **this** database only |
| Git | Launcher inspects identity; it does not change it |

Stable is the only profile allowed to open production data.

### 1.2 Preview

Example display name: `0.7 Preview`.

| Field | Rule |
|---|---|
| Checkout | A separate independent clone, not a worktree of production |
| Data | A dedicated owner-only UAT database |
| Source of data | Empty, synthetic, or an **explicit** owner UAT copy from a production backup |
| Production DB | Never opened, never linked, never migrated |
| Schema | May be at a different Alembic head than production |
| Network | Same v1 bind as Stable; see process rules |

Preview exists so the owner can exercise a future line on realistic private data without giving that data to agents and without mutating production.

### 1.3 Experiment

| Field | Rule |
|---|---|
| Checkout | A separate independent clone on a specific prepared feature/task ref |
| Data | Sandbox / synthetic database by default |
| Production / UAT data | No access |
| Purpose | Try a prepared experimental checkout without production consequences |

An experiment profile is still an **owner runtime**, not an agent workspace. Agent development continues in clean clones with pytest temp databases.

## 2. Folder and checkout model

Conceptual owner-only layout. Names are examples, not repository requirements:

```text
<owner-runtime-root>/
  stable/                      # production runtime clone
    .env                       # secrets; gitignored
    data/finance.db            # production DB; gitignored
    data/.hermes-data-identity.json
    data/backups/              # production backups; gitignored
  preview-0.7/                 # independent clone
    data/finance.db            # UAT copy or dedicated preview DB
    data/.hermes-data-identity.json
  experiment-<id>/             # independent clone
    data/finance.db            # sandbox
    data/.hermes-data-identity.json
```

`<owner-runtime-root>` is local owner configuration. It may sit in the same family of locations as today’s production runtime clone and `owner-probes/`. It is never an agent workspace.

Rules:

1. Each profile checkout is an independent Git clone with its own Git directory.
2. Preview and experiment checkouts must not be linked worktrees of the Stable checkout.
3. Default database path remains checkout-relative: `data/finance.db`, matching `Settings.database_path`. v1 does not need `HERMES_FINANCE_DATABASE_PATH` if that default is used.
4. Filename `finance.db` is **not** an identity. Several profiles will have a file of that name.
5. No junction, symlink, hardlink or other indirection from a preview/experiment data path to production data.
6. Agents must not receive production, preview/UAT or experiment owner databases, `.env`, backups or private payloads.

Launcher config lives outside Git, in a per-user local directory. The portable location is:

```text
%LOCALAPPDATA%\HermesFinance\launcher\config.json
```

## 3. Profile configuration

Minimal JSON. No secrets. No cloud endpoints. Unknown fields fail closed.

```json
{
  "version": 1,
  "canonical_production": {
    "checkout": "<absolute-stable-checkout>",
    "data_dir": "<absolute-stable-data-dir>",
    "database": "<absolute-stable-database>"
  },
  "profiles": [
    {
      "id": "stable",
      "display_name": "Stable",
      "type": "stable",
      "checkout": "<absolute-stable-checkout>",
      "expected_ref": "refs/tags/v0.6.3",
      "data_dir": "<absolute-stable-data-dir>",
      "database": "<absolute-stable-database>",
      "open_browser": true
    },
    {
      "id": "preview-0.7",
      "display_name": "0.7 Preview",
      "type": "preview",
      "checkout": "<absolute-preview-checkout>",
      "expected_ref": "origin/r07",
      "data_dir": "<absolute-preview-data-dir>",
      "database": "<absolute-preview-database>",
      "open_browser": true
    },
    {
      "id": "experiment-example",
      "display_name": "Experiment",
      "type": "experiment",
      "checkout": "<absolute-experiment-checkout>",
      "expected_ref": "<prepared-commit-or-branch>",
      "data_dir": "<absolute-experiment-data-dir>",
      "database": "<absolute-experiment-database>",
      "open_browser": true
    }
  ]
}
```

Normative fields:

| Field | Meaning |
|---|---|
| `version` | Config schema version. v1 understands only `1`. |
| `canonical_production.*` | Singleton production identity. Required. |
| `id` | Stable profile key. |
| `display_name` | Owner-facing label. |
| `type` | `stable` \| `preview` \| `experiment`. |
| `checkout` | Absolute path to that profile’s independent clone. |
| `expected_ref` | Tag, branch or exact commit the checkout must currently resolve to. |
| `data_dir` | Absolute directory that owns the database and sidecar. |
| `database` | Absolute SQLite path. Must be inside `data_dir`. |
| `open_browser` | If true, open `http://127.0.0.1:8000` after health succeeds. |

v1 does **not** make host or port per-profile knobs. Bind is always `127.0.0.1:8000`. A future config that sets another host is invalid. A future config that sets another port is invalid in v1.

`HERMES_FINANCE_T_INVEST_READ_ONLY_TOKEN` and any other secret remain in the checkout `.env` loaded by existing `Settings`. Launcher config must not copy them.

## 4. Production data protection

Do not trust the name `finance.db`. Identity is the **conjunction** of the checks below. Any one failure fails closed.

### 4.1 Canonical production registry

Launcher config declares exactly one production checkout, data directory and database. Those three paths are resolved before comparison.

`type=stable` may start only if its checkout/data/database match that singleton after resolution.

`type=preview` and `type=experiment` may start only if none of their checkout, data directory or database match that singleton after resolution.

### 4.2 Resolved location identity

For every compared file or directory:

1. reject if the path does not exist when it is required to exist;
2. expand user and make it absolute;
3. recursively resolve reparse points (symlinks, junctions, directory junctions);
4. reject `..` escape out of the declared checkout or data directory;
5. compare the resolved path strings case-insensitively on Windows;
6. if both sides exist as files, also compare Win32 file identity (`dwVolumeSerialNumber` + `nFileIndexHigh` / `nFileIndexLow`) so a hardlink to production is detected even when the path strings differ.

Preview/experiment fail if their database file identity equals the canonical production database.

### 4.3 Checkout Git identity

Read Git from the profile checkout:

- `HEAD` commit;
- current ref name if any;
- `git rev-parse --git-common-dir`.

Fail closed if:

- the checkout is not a Git work tree;
- `expected_ref` does not resolve to the current `HEAD`;
- Stable or Preview has a dirty work tree (unknown code identity);
- preview/experiment `git-common-dir` equals the Stable `git-common-dir` (linked worktree of production).

The launcher never changes Git state to make these checks pass.

### 4.4 Data sidecar

Each used `data_dir` has a gitignored sidecar:

```text
<data_dir>/.hermes-data-identity.json
```

Minimum contents:

```json
{
  "kind": "production",
  "profile_id": "stable",
  "updated_at": "<UTC ISO-8601>"
}
```

`kind` is `production` | `preview` | `sandbox`.

Matching rules:

| Profile type | Required sidecar `kind` | If sidecar missing |
|---|---|---|
| `stable` | `production` | Allowed only when paths already match `canonical_production`; first successful Stable start writes the sidecar |
| `preview` | `preview` | Fail closed if the database file already exists |
| `experiment` | `sandbox` | Fail closed if the database file already exists; a missing database (fresh sandbox) is allowed and the sidecar is written on first start |

The sidecar must not contain financial values, tokens or owner payload.

v1 does **not** add a financial-schema table for this. A future optional Alembic stamp is allowed only as a later additive guard; it is not required to accept this ADR.

### 4.5 Why this is enough for v1

Path + file-id + independent Git directory + sidecar + singleton production registry blocks the realistic Windows accidents: wrong folder, junction over `data/`, hardlink of `finance.db`, worktree of production, and “copy the production path into a preview profile”. Content copied through the UAT workflow is a **new file** with `kind=preview`.

## 5. Startup validation sequence

Fail closed at the first failed step. Do not start `start-local.ps1`. Do not open the browser. Do not migrate.

1. **Config valid.** JSON parses; `version == 1`; required fields present; exactly one `stable`; `canonical_production` present; no secrets fields.
2. **Checkout exists.** Profile `checkout` is a directory containing `scripts/start-local.ps1`, `backend/pyproject.toml` and `frontend/package.json`.
3. **Data path allowed for type.** Database path is under `data_dir`; `data_dir` is not a parent of another profile’s checkout in a way that aliases production data. Preview/experiment paths are not the canonical production paths.
4. **Preview/experiment do not reference production data.** Resolved path and file-id checks from §4.2; sidecar rules from §4.4; Git common-dir check from §4.3.
5. **Code identity is known.** `HEAD` matches `expected_ref`. App version is readable from that checkout (`hermes_finance.__version__` / health contract). Stable/Preview dirty trees fail.
6. **Schema compatibility is known.** Open the target database read-only if it exists. Read `alembic_version`. Load that checkout’s Alembic script directory.
    - missing database: allowed for `experiment`; for `stable`/`preview` allowed only when the owner is creating a new dedicated file, not by aliasing production;
    - current revision unknown to this checkout: fail;
    - current revision ahead of this checkout’s heads: fail;
    - current revision behind: allowed — existing `upgrade_database()` in `hermes-finance-api` will upgrade **this** file after Start;
    - cannot read SQLite / integrity_check not `ok`: fail.
7. **Port allowed.** `127.0.0.1:8000` is free. v1 does not pick another port.
8. **Guarded startup.** Invoke the profile checkout’s `scripts/start-local.ps1` with working directory = checkout root. Do not reimplement frontend build, Alembic, uvicorn bind or health probes in a weaker form.
9. **Health check.** Existing probes remain authoritative: `http://127.0.0.1:8000/api/health`, `/api/months` and `/` containing `Hermes Finance`. Health `version` should match the checkout identity shown in the UI.
10. **Open the app.** If `open_browser` is true, open `http://127.0.0.1:8000`. Loopback only.

`start-local.ps1` already forces `HERMES_FINANCE_HOST=127.0.0.1`, `HERMES_FINANCE_PORT=8000`, `HERMES_FINANCE_RELOAD=false`. The launcher must not override those to weaker values.

## 6. Unsafe-state matrix

| State | Result | Owner-facing reason (normative sense) |
|---|---|---|
| Config missing / invalid JSON / unknown `version` | Fail | Launcher config is invalid |
| Two `stable` profiles | Fail | Only one production profile is allowed |
| `type=stable` checkout ≠ canonical production checkout | Fail | Stable may use only the production runtime |
| `type=stable` database ≠ canonical production database | Fail | Stable may use only the production database |
| `type=preview` or `experiment` path/file-id equals production DB | Fail | This profile cannot open production data |
| Junction/symlink/hardlink from preview/experiment data to production data | Fail | Data path aliases production |
| Preview/experiment is a Git worktree of Stable | Fail | Checkout is not independent |
| `expected_ref` ≠ `HEAD` | Fail | Checkout identity does not match this profile |
| Dirty work tree on Stable or Preview | Fail | Code identity is ambiguous |
| Existing preview DB without `kind=preview` sidecar | Fail | Unstamped data is treated as unsafe |
| Existing experiment DB without `kind=sandbox` sidecar | Fail | Unstamped data is treated as unsafe |
| Alembic revision unknown to this checkout | Fail | Schema is not compatible with this code |
| Alembic revision ahead of this checkout | Fail | Database was migrated by newer code |
| SQLite integrity_check fails | Fail | Database file is not a usable SQLite database |
| Host would not be `127.0.0.1` | Fail | Loopback-only invariant |
| Port `8000` already listening | Fail | Another Hermes instance is running; v1 is single-instance |
| `scripts/start-local.ps1` missing in checkout | Fail | Guarded startup is unavailable |
| Health/version/HTML probe fails | Fail / stop | Existing launcher failure path; do not pretend ready |
| Start requested as “checkout this branch in Stable” | Reject | Launcher is not a Git branch switcher |
| Copy preview DB onto production | Reject (process) | UAT copy is one-way; production restore uses production backups only |

Ambiguous identity is always a failure, never a prompt that defaults to Continue.

## 7. UAT-copy process

Goal: **production → explicit Preview copy** so 0.7 can run on realistic owner data.

This is an owner-only action. It is not part of daily Start. Agents never perform it and never receive the copy.

### 7.1 Why not `POST /api/backups/{id}/restore`

Existing restore replaces the **currently running profile’s** database after a same-schema check. Using it as the UAT path would either mutate production or refuse a different future schema. UAT copy is a **file copy of a production backup into the preview data path**, then Preview startup may migrate that copy.

### 7.2 Sequence

1. Owner chooses `Refresh Preview from production backup` (launcher) or an equivalent owner-only script. Daily Start must not do this implicitly.
2. Preview must be stopped. v1 also requires Stable to be stopped so there is no confusion about which instance owns `8000` and so the copy is taken against a quiet runtime. If a current production backup already exists, creating that backup may use the existing SQLite online backup API while Stable is still running; the **copy into Preview** still happens with Preview stopped.
3. Create or select a production backup from Stable’s ignored `data/backups/` using the existing backup mechanism (`create_backup` / `finance_backup_*.sqlite3`). Do not copy a live locked `finance.db` by raw filesystem copy if a backup file is available.
4. Validate the backup as SQLite (`integrity_check`, readable `alembic_version`). Do **not** require the backup schema to match the Preview checkout’s head — Preview may be newer.
5. Write into the Preview `data_dir` only:
    - replace preview `finance.db` with a copy of that backup file;
    - do not write into the canonical production database or production `data/backups/`;
    - write/replace `.hermes-data-identity.json` with `kind=preview`, `profile_id`, `source=production_backup`, `source_backup_id`, `copied_at`, and source Alembic heads. No financial values.
6. Further Preview starts run Alembic only against the preview database. Production remains untouched.
7. Refreshing the copy later is another explicit owner action. It overwrites Preview data, not production.

### 7.3 One-way rule

- Production → Preview copy is allowed only through this workflow.
- Preview → production copy is forbidden.
- Production recovery remains the existing backup/restore path inside the Stable profile.
- The copy is owner-only. It must live in the preview runtime, never in an agent clone, and must not be committed.

## 8. Migration protection

Current production behaviour in `hermes_finance.cli:main` is:

```text
upgrade_database(settings.database_path)  # alembic upgrade head
then serve
```

This ADR does not change that behaviour. Protection is that **the database path `upgrade_database` sees is the profile’s own file**.

| Profile | What may be migrated | What must not be migrated |
|---|---|---|
| Stable | Canonical production DB, as today | Anything else |
| Preview | Preview DB only, including after UAT copy | Production DB |
| Experiment | Sandbox DB only | Production DB and Preview/UAT DB |

Preflight (§5.6) refuses unknown or ahead revisions **before** `start-local.ps1`. Behind revisions are the supported upgrade case for that profile’s file.

Running newer Preview code against production data is prevented by identity checks, not by disabling Alembic.

## 9. Process and port rules

v1 is **single-instance**.

- Only one profile may run at a time.
- Bind remains `127.0.0.1:8000` for every profile.
- If port `8000` is taken, Start fails. The launcher does not auto-kill the occupant.
- Simultaneous Stable + Preview is **not** allowed in v1.
- `scripts/dev.ps1` (`8000` + `5173`) is outside the launcher. If a dev stack already holds `8000`, owner Start fails closed — same as today.

Rationale: current production launcher, health probes, ADR 0004 Host/Origin behaviour and owner habit all assume one local app at `8000`. Dual bind (`8001` for Preview) plus “which window is production?” is a later convenience, not a v1 safety requirement.

v2 *may* add an explicit Preview port only after a separate contract. It is not implied by this ADR.

## 10. Proposed v1 UX

The window shows configured profiles only. It does not offer an arbitrary branch field.

Each row shows:

| Shown | Source |
|---|---|
| Display name | config |
| Type | config (`Stable` / `Preview` / `Experiment`) |
| Ref | current Git ref (read-only) |
| Commit | short `HEAD` |
| App version | checkout `__version__` |
| DB profile | sidecar `kind` (`production` / `UAT copy` / `sandbox`) |
| Readiness | result of validation without starting |

Start:

1. owner selects one radio;
2. clicks **Запустить**;
3. launcher re-runs validation;
4. on failure, shows the matrix reason and does not start;
5. on success, runs that checkout’s `scripts/start-local.ps1`, waits for existing health probes, then opens the browser if configured.

Optional v1 extra, not required for first Start: **Обновить Preview из backup** on the Preview row, implementing §7. If absent from the first executable, the same sequence must still exist as a documented owner-only script.

The launcher must not:

- list every Git branch and check it out;
- offer “use production DB” on Preview/Experiment;
- store tokens;
- auto-update from the network;
- start Docker.

## 11. Implementation technology for #144

Windows-first. A real `.exe` (or equivalently double-clickable packaged launcher) is the UX goal. Docker is out of scope. Cross-platform is not a goal.

| Option | Verdict for v1 |
|---|---|
| Status quo PowerShell `start-local.ps1` | Keep as the **boot engine**. Not the owner UX. |
| Small .NET 8 WinForms (or equivalent Win32 UI) single-file `win-x64` exe | **v1 recommendation.** Native `.exe`, JSON built-in, cheap process start, no extra webview/Rust toolchain. |
| Packaged Python GUI (PyInstaller + tkinter/CustomTkinter) | Rejected for v1. Fat artifact, slower cold start, packaging friction, duplicates a runtime the app already starts via `uv`. |
| WPF / WinUI 3 | Unnecessary ceremony for three radios and a Start button. Allowed later if WinForms is too ugly; not the v1 default. |
| Tauri | Deferred. Useful only if a later task proves installer/tray/update value. v1 must not add that stack. |

**v1 recommendation:** a small .NET 8 Windows Forms single-file executable that:

1. reads `%LOCALAPPDATA%\HermesFinance\launcher\config.json`;
2. performs the validation in this ADR;
3. invokes the selected checkout’s existing `scripts/start-local.ps1`;
4. surfaces health/failure text;
5. opens the loopback URL.

Validation belongs in the exe (or a small library it cannot skip), with automated tests for path/file-id/sidecar/type mismatch. PowerShell remains the guarded app starter. Do not reimplement Alembic, frontend build or uvicorn in C#.

Launcher sources may live under a future `launcher/windows/` tree. Built binaries are not committed. No cloud updater.

## 12. Boundaries for issue #144

#144 may:

- add the Windows launcher project, tests and owner-facing UX above;
- add an owner-only UAT-copy command/script that follows §7;
- write/update data sidecars;
- document local config location and a sample **redacted** config;
- add defense-in-depth checks **in the launcher** before calling `start-local.ps1`.

#144 must not:

- change production startup semantics of `scripts/start-local.ps1` / `hermes-finance-api` except a later, separately reviewed additive guard;
- `git checkout` inside the production runtime;
- point Preview/Experiment at production data;
- add Tauri, Docker, installer-for-its-own-sake, or a cloud updater;
- put secrets in launcher config;
- give agents UAT or production data;
- migrate owner production data as an experiment;
- allow a second bind address or (in v1) a second port;
- treat this ADR as license to redesign ADR 0004 or ADR 0012.

## Consequences

- Daily Start can become a profile radio instead of a raw PowerShell command without turning the launcher into a Git switcher.
- Production Alembic remains exactly as dangerous as today **inside Stable**, and unreachable from Preview/Experiment if this contract is implemented.
- Owner UAT of 0.7 can use a realistic copy while agents stay on synthetic data.
- v1 does not support running Stable and Preview together.
- #144 has a bounded implementation contract.

## Non-goals

This ADR does not:

- ship `HermesFinance.exe`;
- change `scripts/start-local.ps1` behaviour;
- add schema migrations;
- move production `data/` layout;
- introduce auth, cloud, telemetry, VPS or Docker;
- define an installer or auto-update channel;
- allow arbitrary branch checkout against one database.

## References

- ADR 0001 — local architecture and `data/` layout
- ADR 0004 — localhost Host/Origin protection
- ADR 0012 — runtime and agent workspace isolation
- `scripts/start-local.ps1` — guarded production starter
- `scripts/dev.ps1` — development stack, not a launcher profile
- `hermes_finance.cli:main` / `services.migrations.upgrade_database` — Alembic at startup
- `hermes_finance.services.backups` — SQLite online backup/restore
- `GET /api/health` — `{ "status": "ok", "version": "<app version>" }`
- Roadmap #127, contract issue #131, implementation issue #144
