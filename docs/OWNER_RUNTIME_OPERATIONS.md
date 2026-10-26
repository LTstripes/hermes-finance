# Operations, release and recovery

Current normative handbook. Historical evidence and section-by-section provenance are in the [migration map](archive/2026-10-18/MIGRATION_MAP.md); it is not required reading for ordinary work. Current delivery/installation/task state is owned by [CURRENT_STATUS](CURRENT_STATUS.md).

[1. Runtime roles, binding, Prepare/Validate/Start](#o1) | [2. Test, scratch, local UAT and read-only diagnosis](#o2) | [3. Publication, backup-first update and separate Start](#o3) | [4. Backup, restore and ambiguous results](#o4) | [5. Inventory, frozen-plan deletion and recoverable retirement](#o5) | [6. Provider configuration and diagnostics](#o6)

<a id="o1"></a>

Direct operations consume the retained profile/identity/exclusion safeguards below. References to Launcher in that historical contract identify the shared protection mechanism, not an installed shell or a requirement to recreate its UI/config. Current direct-operations runtime inventory and command inputs in O2–O4 take precedence over the retired shell representation.

## 1. Runtime roles, binding, Prepare/Validate/Start

Stable is the published production runtime; Main is canonical Control code; Test is the persistent isolated exact-SHA Preview/UAT location; Owner holds local registry/manifests/recovery/journals; Ops holds accepted installed operations. Client task workspaces are separate. Concrete absolute mappings stay machine-local.

Direct operations are normal; the Launcher shell/config/shortcuts and repository shell source are retired. Preserve shared RuntimeConfig/backup/recovery helpers whose names still mention Launcher. Prepare/Validate, Start, update and publication are separate bounded operations. A code merge or preparation proof never authorizes a runtime action. Only an owned runtime uses loopback port 8000; never kill an unrelated process by port. S contains dated installation evidence.

<a id="o1-owner_runtime_operations-5"></a>
### Separate runtime roles and direct operations

<a id="o1-owner_runtime_operations-5-1-architecture-in-one-sentence"></a>
#### 1. Architecture in one sentence

Hermes uses separate explicit Prepare/Validate, deterministic Start, exact-SHA Test preparation, backup-first Stable release transition and guarded publication; no Launcher is required.

- Prepare/Validate: `scripts/prepare-runtime.ps1`.
- Start: `scripts/start-local.ps1`.
- Preview/UAT role in the persistent Test folder: `scripts/prepare-preview.ps1`.
- Stable release transition: `scripts/update-stable.ps1` from trusted Main/Control.
- Publication: guarded #124.

#313 composable-runtime redesign is complete. A failure in one operation does not automatically authorize Start, migration, Test mutation or release publication.

<a id="o1-owner_runtime_operations-41"></a>
### Prepare, Validate and separate deterministic Start

<a id="o1-owner_runtime_operations-41-4-prepare-an-exact-checkout"></a>
#### 4. Prepare an exact checkout

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


<a id="o1-owner_runtime_operations-41-5-deterministic-start"></a>
#### 5. Deterministic Start

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

<a id="o1-0014-launcher-runtime-profile-safety-77"></a>
### Retained runtime profile identity and production exclusions

<a id="o1-0014-launcher-runtime-profile-safety-77-1-profile-model"></a>
#### 1. Profile model

Exactly one profile may have `type=stable`. Preview and experiment profiles may exist in any number, each with its own checkout and data.


<a id="o1-0014-launcher-runtime-profile-safety-77-11-stable"></a>
#### 1.1 Stable

| Field | Rule |
|---|---|
| Checkout | The canonical production runtime clone |
| Data | That clone’s ignored runtime data, including the real owner database |
| Startup | Existing `scripts/start-local.ps1` |
| Network | Loopback `127.0.0.1:8000` |
| Migrations | Inherit current production behaviour: `hermes-finance-api` runs `alembic upgrade head` on **this** database only |
| Git | Launcher inspects identity; it does not change it |

Stable is the only application runtime profile allowed to open production data.
Assigned read-only Owner analysis is separately governed by the [Owner data workflow](DEVELOPMENT.md#d1-owner_data_workflow-5);
it does not authorize startup/migrations from an experimental checkout.


<a id="o1-0014-launcher-runtime-profile-safety-77-12-preview"></a>
#### 1.2 Preview

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


<a id="o1-0014-launcher-runtime-profile-safety-77-13-experiment"></a>
#### 1.3 Experiment

| Field | Rule |
|---|---|
| Checkout | A separate independent clone on a specific prepared feature/task ref |
| Data | Sandbox / synthetic database by default |
| Production / UAT data | No access |
| Purpose | Try a prepared experimental checkout without production consequences |

An experiment profile is still an **owner runtime**, not an agent workspace. Agent development continues in clean clones with pytest temp databases.


<a id="o1-0014-launcher-runtime-profile-safety-77-2-folder-and-checkout-model"></a>
#### 2. Folder and checkout model

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


<a id="o1-0014-launcher-runtime-profile-safety-77-3-profile-configuration"></a>
#### 3. Profile configuration

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


<a id="o1-0014-launcher-runtime-profile-safety-77-4-production-data-protection"></a>
#### 4. Production data protection

Do not trust the name `finance.db`. Identity is the **conjunction** of the checks below. Any one failure fails closed.


<a id="o1-0014-launcher-runtime-profile-safety-77-41-canonical-production-registry"></a>
#### 4.1 Canonical production registry

Launcher config declares exactly one production checkout, data directory and database. Those three paths are resolved before comparison.

`type=stable` may start only if its checkout/data/database match that singleton after resolution.

`type=preview` and `type=experiment` may start only if none of their checkout, data directory or database match that singleton after resolution.


<a id="o1-0014-launcher-runtime-profile-safety-77-42-resolved-location-identity"></a>
#### 4.2 Resolved location identity

For every compared file or directory:

1. reject if the path does not exist when it is required to exist;
2. expand user and make it absolute;
3. recursively resolve reparse points (symlinks, junctions, directory junctions);
4. reject `..` escape out of the declared checkout or data directory;
5. compare the resolved path strings case-insensitively on Windows;
6. if both sides exist as files, also compare Win32 file identity (`dwVolumeSerialNumber` + `nFileIndexHigh` / `nFileIndexLow`) so a hardlink to production is detected even when the path strings differ.

Preview/experiment fail if their database file identity equals the canonical production database.


<a id="o1-0014-launcher-runtime-profile-safety-77-43-checkout-git-identity"></a>
#### 4.3 Checkout Git identity

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


<a id="o1-0014-launcher-runtime-profile-safety-77-44-data-sidecar"></a>
#### 4.4 Data sidecar

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


<a id="o1-0014-launcher-runtime-profile-safety-77-45-why-this-is-enough-for-v1"></a>
#### 4.5 Why this is enough for v1

Path + file-id + independent Git directory + sidecar + singleton production registry blocks the realistic Windows accidents: wrong folder, junction over `data/`, hardlink of `finance.db`, worktree of production, and “copy the production path into a preview profile”. Content copied through the UAT workflow is a **new file** with `kind=preview`.


<a id="o1-0014-launcher-runtime-profile-safety-77-5-startup-validation-sequence"></a>
#### 5. Startup validation sequence

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


<a id="o1-0014-launcher-runtime-profile-safety-77-6-unsafe-state-matrix"></a>
#### 6. Unsafe-state matrix

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


<a id="o1-0014-launcher-runtime-profile-safety-77-7-uat-copy-process"></a>
#### 7. UAT-copy process

Goal: **production → explicit Preview copy** so 0.7 can run on realistic owner data.

This is an owner-only action. It is not part of daily Start. Agents never perform it and never receive the copy.


<a id="o1-0014-launcher-runtime-profile-safety-77-71-why-not-post-apibackupsidrestore"></a>
#### 7.1 Why not `POST /api/backups/{id}/restore`

Existing restore replaces the **currently running profile’s** database after a same-schema check. Using it as the UAT path would either mutate production or refuse a different future schema. UAT copy is a **file copy of a production backup into the preview data path**, then Preview startup may migrate that copy.


<a id="o1-0014-launcher-runtime-profile-safety-77-72-sequence"></a>
#### 7.2 Sequence

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


<a id="o1-0014-launcher-runtime-profile-safety-77-73-one-way-rule"></a>
#### 7.3 One-way rule

- Production → Preview copy is allowed only through this workflow.
- Preview → production copy is forbidden.
- Production recovery remains the existing backup/restore path inside the Stable profile.
- The copy is owner-only. It must live in the preview runtime, never in an agent clone, and must not be committed.


<a id="o1-0014-launcher-runtime-profile-safety-77-8-migration-protection"></a>
#### 8. Migration protection

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


<a id="o1-0014-launcher-runtime-profile-safety-77-9-process-and-port-rules"></a>
#### 9. Process and port rules

v1 is **single-instance**.

- Only one profile may run at a time.
- Bind remains `127.0.0.1:8000` for every profile.
- If port `8000` is taken, Start fails. The launcher does not auto-kill the occupant.
- Simultaneous Stable + Preview is **not** allowed in v1.
- `scripts/dev.ps1` (`8000` + `5173`) is outside the launcher. If a dev stack already holds `8000`, owner Start fails closed — same as today.

Rationale: current production launcher, health probes, ADR 0004 Host/Origin behaviour and owner habit all assume one local app at `8000`. Dual bind (`8001` for Preview) plus “which window is production?” is a later convenience, not a v1 safety requirement.

v2 *may* add an explicit Preview port only after a separate contract. It is not implied by this ADR.

<a id="o2"></a>
## 2. Test, scratch, local UAT and read-only diagnosis

Use the exact authorized SHA and physically separate data through supported OPS03. Persistent Test is not Stable and is not recreated as a new top-level stand per routine UAT; separately authorized disposable scratch pilots remain disjoint. No copying scratch tables into protected DBs. Read-only diagnostics use query-only/read-only connections and never migration-capable startup.

Owner-requested data analysis authorizes only relevant reads in its assigned context under D1; this documentation task authorizes no private DB/statements/secrets reads. Runtime evaluation also binds current PID/creation/executable, endpoint, code and selected data/profile. Health/version or filename alone is insufficient. Offline saved-evidence review needs no listener. Continue from valid bounded receipts, invalidating only changed dependencies; a new chat is not a reason to replay UAT.

<a id="o2-owner_runtime_operations-80"></a>
### Exact-SHA isolated Test preparation

<a id="o2-owner_runtime_operations-80-6-exact-previewuat-preparation"></a>
#### 6. Exact Preview/UAT preparation

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

Populate Test only through an explicitly approved isolated copy/recovery/synthetic workflow. Never point Test at production SQLite or copy its data back to Stable. Retain needed Test artifacts before a deliberate refresh. Real-data reading requires the bounded Owner authority in D1; credentials remain excluded and development tasks have no implicit runtime authority. Current Owner checks and exact UAT scopes are in [CURRENT_STATUS](CURRENT_STATUS.md#s1).

<a id="o2-instrument_uat_runtime-1"></a>
### Query-only, migration-free instrument checks

Code capability only. This does not deploy a release or perform #867 Owner UAT.
Normal Start, recovery and `-ScratchPreflight` retain their existing behavior.


<a id="o2-instrument_uat_runtime-1-approved-desktop-option"></a>
#### Approved desktop option

Owner decision in the #868 implementation conversation, 2026-10-17:
**«Разрешить отдельную UAT-страницу»**. The original Capital → Performance
SPA made five out-of-scope requests in a synthetic browser probe:
`/api/months`, `/api/performance/membership`, `/preparation`, `/readiness`,
`/valuation-captures` (the latter four under `/api/performance`). It also
included navigation to mutation/export pages. Independent contract review
confirmed the issue's explicit STOP. Owner then authorized the finite alternative:
a separate production entry mounting the existing `InstrumentCashIncome`
component, without the ordinary App/shell, navigation or write components.
The original API allowlist remains unchanged. Financial logic is not copied.


<a id="o2-instrument_uat_runtime-1-operational-boundary"></a>
#### Operational boundary

After Integrator acceptance/merge and exact-main CI, a correctly routed
HONOR-local operator may use the existing #867 authority. Do not run this mode
against Owner data during code delivery. Use an independent clean, detached,
prepared checkout pinned to the exact authorized main SHA and a pre-existing,
consistent offline SQLite snapshot, physically disjoint from Stable, Test,
Owner, Ops, control checkout and active workspace roots. Reuse an already
verified snapshot where possible. Snapshot preparation remains a separate
supported backup/recovery operation; this runtime never copies or repairs DBs.

The manifest has exactly the same version-1 fields as #832:
`version`, `kind`, `profile_id`, `checkout`, `checkout_sha`, `database`,
`database_identity`, `snapshot_sha256`, `runtime_inventory`, `control_checkout`,
`owner_root`, `ops_root`, `workspace_roots`. Here `kind` is
`instrument_uat_scratch`; the snapshot parent's `.hermes-data-identity.json`
must be exactly `{"kind":"instrument_uat_scratch","id":"<profile_id>"}`.
An old preflight manifest/sidecar cannot opt into this mode.

Use the prepared checkout's Windows PowerShell launcher:

```powershell
powershell.exe -NoProfile -File scripts/start-instrument-uat.ps1 -Manifest <absolute-local-manifest>

<a id="o2-instrument_uat_runtime-1-bounded-readiness--cleanup-probe-instead-of-an-interactive-session"></a>
#### Bounded readiness + cleanup probe instead of an interactive session:
powershell.exe -NoProfile -File scripts/start-instrument-uat.ps1 -Manifest <absolute-local-manifest> -ExitAfterReady
```

Backend dispatch is `hermes-finance-api instrument-uat --manifest <path>
--readiness-token <random-64-lowercase-hex>`. It cannot fall through to ordinary
migration-capable startup. The launcher generates this private token; do not
publish it. There is no global skip-migrations setting or runtime profile.

Port **18868**, `127.0.0.1` only, is fixed and separate from Stable's 8000.
Occupied ports fail; no existing process is stopped or redirected. The launcher
reuses the authenticated Windows kill-on-close Job bootstrap, gates children
before execution, verifies the listener's process ancestry/creation identity
and an HMAC binding to mode/port/PID/start/SHA/snapshot identity/hash.
Termination of the outer launcher closes the Job and its descendants.
The persistent launcher is bounded to eight hours and buffers inner stdout;
its initial “Starting” message is not a readiness assertion. `-ExitAfterReady`
returns the verified ready message after owned cleanup.


<a id="o2-instrument_uat_runtime-1-read-and-ingress-guarantees"></a>
#### Read and ingress guarantees

Reuse #832's physical path/inventory/checkout/interpreter/schema checks,
`_hold_snapshot` and `_read_database`. SQLite opens only
`mode=ro&immutable=1` with query-only and foreign keys enabled. The accepted
snapshot must have exact schema head/table/column shape, integrity and FK
checks, no WAL/SHM/journal and no conflicting writer handle. No Alembic
upgrade/stamp, create_all, provider or standard application startup runs.
OS read-only remains effective after coherent reader cleanup clears query-only.

Snapshot, manifest, inventory, sidecar and UAT dist closure are pinned against
write/delete on Windows. Prepared validation runs again after pinning static
bytes. Each permitted request rechecks content and exact clean checkout binding.
A detected binding failure latches the process unavailable, even after A→B→A;
restart explicitly after diagnosing it. Response and error headers are no-store.
No local paths, SQL or DB identities are returned by public health/errors/logs.
Only the private token holder can obtain the keyed process readiness proof.

Only GET is accepted, with the runtime's loopback Host and same Origin when
present. The registered canonical API surface is:

- `/api/health`, `/api/accounts`, `/api/instruments`;
- `/api/instruments/{id}/cash-income`, `/eod-observations`, `/known-trades`,
  `/conditional-return` (all four under the same instrument prefix).

`/` serves `instrument-uat.html`; only the recursively referenced Vite
manifest asset closure is served. No SPA fallback, main entry, arbitrary static
file, source map, generic API, exports, provider GET or mutation handler is
registered. CSP prohibits external connections/resources, frames and form posts.

The canonical panel preserves source gaps, bond blocking, three unchecked
hypothetical assumptions, actual return NULL and unknown completeness/NULL
trade inventory fingerprint. An immutable snapshot cannot demonstrate later live
changes; the displayed evidence applies to the bound offline snapshot only.


<a id="o2-instrument_uat_runtime-1-synthetic-verification"></a>
#### Synthetic verification

```text
backend: pytest tests/test_instrument_uat_runtime.py tests/test_scratch_preflight_runtime.py
frontend: npm run build
frontend: npx playwright test --project=instrument-uat
```

The browser harness fabricates current-schema source-backed stock/bond data,
closes its writer, then exercises the real hard-read-only engine and canonical
handlers. It is a test harness, not an alternative operator entrypoint. Full
manifest/process isolation is exercised by Windows launcher tests, including
forced outer-parent exit and port release. Neither synthetic evidence nor green
CI claims real Owner UAT or a Stable update.

<a id="o3"></a>
## 3. Publication, backup-first update and separate Start

Publish only an Owner-selected accepted canonical candidate through the guarded release route. Distinguish application version, release commit/tag, prepared code and database schema. Keep release-note family paths `docs/release-notes-{Version}.md`. Do not mutate historical tag content or published assets to repair main's links.

Historical notes before 1.3.0 are organized under `docs/release-notes/` on main; their original paths remain in the published tags. The active release-note family remains at `docs/release-notes-{Version}.md`: release identity checks and installed immutable updaters read that target-commit path before updating. Moving the active release-note family requires a separately accepted compatible updater transition; changing only main's reader cannot update already installed readers. Keep the current note and future publication paths compatible until then, without root redirects or weaker release gates.

Runtime update is backup-first, published immutable release-pinned and separate from Start. Explicitly bind the existing physical production DB and disjoint backup destination. Preserve the matching old code/database recovery pair; old code must not open an unsupported newer schema. `backend/migrations/README` and released migrations remain byte-stable. Current installed/released identity belongs only in S.

<a id="o3-source-proof-recovery"></a>
### Actual payout schema 0066: candidate recovery boundary

`0066_actual_payout_links` is the code-only #711 candidate; it authorizes no
Owner/Stable/Test migration. Upgrade requires exactly `0065_source_return_proofs`,
integrity/FK and supported-schema validation before DDL, FK suspension before
BEGIN IMMEDIATE, and three explicit rebuilds: ECF, reconciliations and Money
occurrence owners. Every old value/receipt/CLOSED fact, unrelated schema object,
prior sequence, both 0065 proof tables and all thirteen guards must survive,
without new proof nonces from copying. Existing migration transaction handling
restores FK enforcement after success or failure.

Downgrade refuses before DDL for any v2/payout/dependency receipt, dividend owner,
actual/retired link history or positive ECF revision. The populated 0065→0064
prohibition remains unchanged; this is not a production rollback plan.
Same-schema physical recovery invalidates old confirmations/currentness and
requires fresh DRAFT review/reaffirmation; CLOSED history remains accepted.
Cross-schema restore remains forbidden. A verified producing code/schema pair,
recovery cutoff and separate Owner authorization are necessary for real operations;
post-backup history cannot be recreated from memory or provider responses.

### Source-only proof schema 0065: preservation and recovery

`0065_source_return_proofs` adds two empty source-only tables and 13 guards over
0064. Migration advances alembic_version only; all historical table rows, CLOSED
states, sources, mappings and financial facts must match. Verify exact candidate,
physical DB/profile/process binding, fresh stock backup with independent full-table
and schema readback, empty new tables and actual trigger SQL before UAT. Prepare
through OPS03 and Start remain separate; neither imports originals or confirms
proof automatically. Never rewrite released migration sources/README.

Proof Preview uses all exactly required current originals for one native account.
It is zero-write. Attested Confirm appends source provenance only; independent
ACK→GET, ordinary Month/Monthly Returns, Back/Reload and normal restart verify
the result. Unknown-flow/cancellation principal and unsupported bond valuation/NKD
remain NULL. Do not simulate lost ACK, ABA, classification changes or restores on
protected data merely to repeat accepted synthetic evidence.

Payout relink is a separate protected metadata operation. Under 0065 it can append
one retirement nonce per changed classification row. A 0064 Preview claiming no
other-table effects is stale. Capture exact proposed row/column and trigger/nonce
footprints, CLOSED eligibility, unchanged financial/source tables and currentness;
obtain separate Owner GO and fresh backup/readback. Recognized text is not an
instrument mapping or a new payment. If relink and proof are approved together,
relink first, refresh the exact proof Preview and confirm proof last. Actual random
nonce bytes are read back after execution, never predicted or fabricated.

Before Stable rollout, rehearse 0064→0065 on a verified production-compatible copy
at the **published SHA**, isolated from Test/Stable. Preserve all historical
fingerprints and the producing code/backup pair; obtain the Owner's separate
recovery/cutoff/RPO/outage decision. Code/Test acceptance does not waive this gate.
Use owned Stop, fresh independently verified backup, OPS02 with explicit existing
physical DatabasePath and disjoint BackupDirectory, target Prepare/Validate and
separately authorized Start. Stable proof/relink then require new local Previews,
backups/currentness and their own Owner GO. No Test DB, rows or proofs are promoted.

Populated proof history, even stale, refuses downgrade before DDL. Exact-schema
restore, older-version OPS02 refusal and isolated-only O4 do not provide an
in-place 0065→0064 rollback. Preserve the matching code/database pair and follow an
accepted compatible recovery or forward-fix route; no raw overwrite, old binary
on 0065, guard removal or unapproved restore. A recovered physical DB retires saved
proof even with matching contents; preserve its append-only history and obtain a
new exact-original confirmation. Do not promise rollback from a retained 0064
backup. Current installed/released/UAT state belongs only in S.

<a id="o3-empty-close-recovery"></a>
### Intentional-empty Close audit schema recovery (#952)

Schema `0064_month_template_provenance` adds nullable origin columns to income,
expense and saving tables without modifying old values. NULL remains unknown;
MANUAL DRAFT rows require explicit amount confirmation to count for the empty
guard. Backup/restore preserves origins. Downgrade refuses before mutation if any
origin is populated: old code would accept copied templates as facts. Preserve
the code/schema pair and use reviewed forward recovery. An isolated old backup
upgraded to 0064 retains unknown origins, never invented acceptance. These checks
authorize no production migration or runtime operation.

Schema `0063_intentional_empty_close` is additive over 0062: one initially empty
audit table/index and immutable UPDATE/DELETE guards, no changed historical month
or economic rows. Before any separately authorized deployment, verify a fresh
backup and code/schema pairing using the existing O2/O4 procedures. This backend
Worker change does not authorize Test/Stable/Owner migration, Start or actual Close.

Downgrade to 0062 is allowed only while the new audit is empty. A populated audit
fails before schema mutation; never drop triggers, delete receipts or rewrite
status/history to get past that refusal. Preserve the current code/database pair
and use a reviewed forward fix. An older binary also lacks the new Close policy,
so merely opening a newer database with old code is not an accepted rollback.

Stock in-app restore still rejects a cross-schema backup. Retain a verified 0062
backup with its producing code as an old recovery pair. Supported forward recovery
copies that verified artifact to a fresh isolated target and upgrades it to 0063;
it does not replace the live database or invent post-backup audit. After any real
successful Close, recovery must preserve that decision and its receipt; a pre-Close
backup cannot stand in for current financial history. A same-0063 backup preserves
audit and triggers. Synthetic Windows evidence covers populated table preservation,
empty downgrade/re-upgrade, populated downgrade refusal, backup readback and an
isolated 0062→0063 forward target; actual Owner recovery remains separately gated.

<a id="o3-owner_runtime_operations-100"></a>
### Backup-first immutable release update

<a id="o3-owner_runtime_operations-100-7-explicit-stable-update"></a>
#### 7. Explicit Stable update

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

<a id="o3-owner_runtime_operations-124"></a>
### Release sequence and bounded failures

<a id="o3-owner_runtime_operations-124-9-normal-future-release-sequence"></a>
#### 9. Normal future release sequence

Prepare one exact canonical candidate → isolated Test UAT → Owner acceptance → guarded publication through #124 → independent tag/release read-back → stop owned Stable → explicit backup-first OPS02 → target pin/preparation read-back → explicit Start → health/version and data-continuity check.

Do not call a GitHub merge a release or a runtime update. Filesystem relocation and janitor deployment do not promote code versions.


<a id="o3-owner_runtime_operations-124-10-failure-handling"></a>
#### 10. Failure handling

Diagnose the failing bounded operation and preserve the existing backup/error evidence. Do not improvise DB rebinding, refs, runtime profile JSON, another version or an unsafe retry. Ambiguous restore/write outcomes are not success or confirmed failure and must not be blindly replayed. During a relocation, a failed Stable readiness check is resolved or rolled back before unrelated legacy deletion.

An authorized local operations Worker executes the bounded workflow and reports sanitized results; the Owner is not assigned repeated JSON/PowerShell diagnostic relays. That exception does not grant ordinary development tasks runtime access. Existing exact-release/privacy guards remain authoritative.


<a id="o3-owner_runtime_operations-124-11-launcher-state-after-585--586-and-629"></a>
#### 11. Launcher state after #585 / #586 and #629

#585 path-gating and #586 compact shell are historical implementation evidence.
Local removal is complete and #629 retired the repository source/package/tests/jobs.
No further Launcher installation or UX work is implied. Shared direct startup,
backup, prepared-runtime and recovery contracts remain in force; their
`RuntimeConfig`/`launcher-production-backup` inputs follow the direct-operations
runtime inventory defined in section 13, not the deleted shell.

<a id="o3-release_automation-7"></a>
### Guarded publication and immutable release notes

<a id="o3-release_automation-7-control-endpoint"></a>
#### Control endpoint

Permanent control issue: **#124 — Release Control — guarded owner trigger**.

Keep that issue open and unlocked. A release is requested only by a newly created owner-authored comment on #124 with exactly three lines:

```text
/release
version=X.Y.Z
expected_main_sha=<full 40-character main SHA>
```

The version has no `v` prefix. The SHA must be the complete 40-character commit ID.

Edited comments, extra fields, short SHAs, other issues, another actor, or another comment author are rejected. A normal comment that does not begin with `/release` does not enter the release job.

The issue-comment trigger is intentional: the ChatGPT GitHub integration can create an auditable issue comment directly, while it does not require the owner to open GitHub Actions and press a manual workflow-dispatch button.


<a id="o3-release_automation-7-chat-first-integrator-flow"></a>
#### Chat-first integrator flow

This is the **normal release route** when the active integrator has direct GitHub access and can create/read issue comments and Actions runs. The owner should not be asked to open GitHub, PowerShell or Codex merely to relay the release trigger.

For the normal chat-driven path the owner can ask the integrator to release a prepared version. The integrator should:

1. read current GitHub `main` and capture its exact 40-character SHA;
2. confirm canonical `ci.yml` has a completed successful `push` run for that exact `main` SHA;
3. verify repository release identity and `docs/release-notes-X.Y.Z.md` are present;
4. create the exact `/release` request comment on control issue #124 itself;
5. read the Guarded Release run and its job summary;
6. independently read back the tag object, peeled commit and published GitHub Release before reporting success.

The workflow repeats the critical checks itself. Pre-checking in chat is convenience and defense in depth, not authorization to skip workflow guards.

If the direct integration cannot perform a materially required step, use the narrowest safe fallback. Do not hand the owner routine repository busywork merely because another execution surface also exists. See [`AGENTS.md`](../AGENTS.md) and the [integration procedure](DEVELOPMENT.md#d5).


<a id="o3-release_automation-7-guard-chain"></a>
#### Guard chain

`.github/workflows/release.yml` invokes `scripts/release-automation.ps1`, which performs the narrow trigger/identity preflight and then delegates publication to the existing `Invoke-HermesRelease` implementation in `scripts/release-lib.ps1`.

The combined path requires all of the following before publication:

- repository is exactly `LTstripes/hermes-finance`;
- event is a newly created issue comment;
- issue is exactly #124;
- GitHub actor and comment author are both the repository owner;
- request body follows the exact three-line grammar;
- requested version is a stable `X.Y.Z` identity;
- expected main is a full commit SHA;
- `backend/pyproject.toml` `[project].version` equals the requested version;
- `backend/src/hermes_finance/__init__.py` `__version__` equals the requested version;
- canonical `docs/release-notes-X.Y.Z.md` exists and is non-empty;
- release notes contain no candidate-only lifecycle wording such as
  `UAT-PENDING`, a candidate status/title, or a declaration that the release is
  not published;
- fetched `origin/main` still equals the expected SHA;
- canonical `ci.yml` has a completed successful exact-main `push` run for that SHA;
- that exact-main `ci.yml` run includes the required synthetic visual-audit job;
- existing local/remote tag state is compatible with the same annotated tag at the same commit;
- existing GitHub Release state is compatible with a published stable release.

Unexpected tag/release state fails closed. The helper never force-updates or deletes a release tag to make a request succeed.


<a id="o3-release_automation-7-release-note-lifecycle"></a>
#### Release-note lifecycle

`docs/release-notes-X.Y.Z.md` is the publication payload, not the durable place
for a pending candidate gate. Before the release-control request is created,
owner UAT must be complete and candidate-only status wording must be replaced
with publication-ready facts. Candidate preparation state remains in the
release record and execution history until that gate passes.

The shared publication helper checks the notes before resolving tools, fetching
refs, creating a tag or calling GitHub. Both the guarded workflow and the manual
fallback therefore fail closed on stale `UAT-PENDING` or equivalent explicit
candidate-status wording. After publication, the normal documentation closeout
records the published identity without rewriting the historical preparation
record.

<a id="o3-release_automation-93"></a>
### Publication permissions, privacy and verification

<a id="o3-release_automation-93-publication-boundary"></a>
#### Publication boundary

The publication path is deliberately narrow:

- create an annotated `vX.Y.Z` tag at the guarded exact main SHA when it does not already exist;
- push only `refs/tags/vX.Y.Z:refs/tags/vX.Y.Z` with no follow-tags behavior;
- create a published, non-prerelease GitHub Release from that existing tag and canonical release notes;
- never push, reset, update, delete or force-update a branch ref;
- never use `--tags`, `--all`, `--mirror`, force push or tag deletion.

If tag publication succeeds but GitHub Release creation fails, the tag is intentionally retained. Repeating the exact same guarded request may safely reuse the same compatible annotated tag; it is not moved or recreated.


<a id="o3-release_automation-93-permissions-and-credentials"></a>
#### Permissions and credentials

The workflow uses only the repository-provided `GITHUB_TOKEN`; there is no PAT or custom release token.

Workflow-level default permission:

- `contents: read`.

The single release job narrows its elevated permissions to:

- `actions: read` — read canonical exact-main Actions runs;
- `contents: write` — push the one release tag and create/read the GitHub Release.

No `issues: write`, `pull-requests: write`, `packages: write`, deployment permission, id-token, or repository-administration permission is granted to the release job.


<a id="o3-release_automation-93-privacy-and-runtime-isolation"></a>
#### Privacy and runtime isolation

The workflow checks out only the public repository on a GitHub-hosted Windows runner. It has no path or connector to the production runtime and must not read or receive:

- a real `.env`;
- the real finance database or SQLite sidecars;
- backups;
- `private/` owner data;
- provider credentials or owner exports.

No production smoke or live provider operation is part of release publication.


<a id="o3-release_automation-93-verification-and-job-summary"></a>
#### Verification and job summary

After the shared release helper returns, the automation performs a final remote read-back and fails if any invariant changed. The job summary exposes:

- requested version and tag;
- annotated tag object SHA;
- peeled commit SHA;
- final `main` SHA;
- GitHub Release title;
- published state;
- GitHub Release URL;
- control issue and request actor.

A valid successful result requires the peeled tag commit and final `main` to equal the original expected SHA, and the tag object SHA to differ from the peeled commit SHA (annotated tag evidence).

An integrator can independently verify the same state through GitHub by reading `main`, `refs/tags/vX.Y.Z`, the peeled tag target, the canonical exact-main CI run and the GitHub Release. The job summary is evidence, not a substitute for independent read-back when release correctness matters.

<a id="o3-release_automation-199"></a>
### Manual publication fallback

<a id="o3-release_automation-199-manual-fallback"></a>
#### Manual fallback

`scripts/release.ps1` remains the supported manual fallback. It uses the same guarded `scripts/release-lib.ps1` publication implementation:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\release.ps1 `
  -Version X.Y.Z `
  -ExpectedMainSha <full-40-character-main-sha> `
  -ReleaseNotes .\docs\release-notes-X.Y.Z.md
```

The automated path does not weaken or replace those release guards; it adds a repository-owned, chat-triggerable entrypoint around them.

<a id="o4"></a>
## 4. Backup, restore and ambiguous results

Use supported consistent SQLite online backup, verified managed publication/readback and explicit isolated recovery. Local/synced readback does not prove off-device visibility or encryption. Protected and Owner-accepted plaintext modes retain distinct attestations and retention sets. Rehearsal uses a fresh detached independent code checkout/target and never restores Test over Stable.

For confirmed-negative validation failure report the failure without inventing a successful restore. A lost ACK or ambiguous mutation/restore preserves evidence and blocks blind retry. Reread authoritative restored state, invalidate in-flight requests/confirmations and reconcile month selection before showing current success. A changed or uncertain target is not reused. Do not improvise raw DB copying or downgrade to resolve ambiguity.

Stock production restore requires the backup's exact live schema signature. OPS02 refuses
older target versions, including a return after code pinning before DB migration; the O4
rehearsal writes only fresh isolated targets. These operations do not provide cross-schema
Stable rollback. Settle the concrete recovery disposition with Owner/Integrator before a
schema-changing production Start; preserving a verified old code/backup pair is evidence,
not an accepted command to restore it over Stable.

<a id="o4-forward-recovery"></a>
### Bounded 0058 forward recovery at the selected release

The separate `hermes_finance.forward_recovery_cli` module implements one offline
Windows path under #940. This is checkpoint recovery at the **new** code head;
it is not old-code rollback. Integration, independent operational acceptance,
publication and explicit local operational authority remain prerequisites. The
module never publishes, switches code, starts Hermes or invokes OPS02. Existing
API exact-schema restore, OPS02 older-version refusal and O4 isolated-rehearsal
exclusions remain unchanged.

V1 requires fixed local NTFS and a same-volume transaction directory, an authentic
managed point produced by published v1.3.0 at 0058, a clean detached independent
recovery checkout at the selected **published and prepared** future release, and
Stable already pinned/prepared to that same SHA. Control remains independent.
The point's provenance and acceptable loss of changes after that checkpoint must
be explicitly selected by the Owner/operator; manifest verification is not a new
attestation that an arbitrary file originated from production. Plain OPS02 backups
are not managed points and must not be relabeled. Preserve a fresh managed 0058
point through the existing publisher before the actual update; this development
task creates no such production point.

`qualify` writes only a fresh disjoint qualification directory and returns a
frozen plan digest plus snapshot digest. It verifies actual canonical inventory,
production identity, exact Stable Settings/interpreter/working-directory selector,
prepared state, stopped process evidence, source protection/hash/producer/schema,
integrity/FK, and an unambiguous forward migration graph. It generates synthetic
reference schemas from the selected immutable migration graph. Schema signatures
preserve columns, SQL expressions, indexes and triggers; only the order of
table-level constraints is canonicalized because Alembic reflection emits that
order nondeterministically across Python processes. Live/source DBs are unchanged.
References, plans, hashes and numerical preservation evidence stay outside Git.

Run only with the selected checkout's own isolated interpreter; all path variables
are explicit verified local values. No inherited-environment uv bootstrap is used:

```powershell
$python = Join-Path $recoveryCheckout 'backend\.venv\Scripts\python.exe'
& $python -I -m hermes_finance.forward_recovery_cli qualify `
  --database $productionDatabase --artifact $managedPoint --inventory $runtimeConfig `
  --checkout $recoveryCheckout --control $controlCheckout --selected-sha $releaseSha `
  --work $freshDisjointTransactionDirectory `
  --protection-state $acceptedProtectionState --protection-mode $acceptedProtectionMode
```

Qualification is not permission to install. Each following command requires the
separately retained exact plan digest and **explicit acceptance of that snapshot's
RPO/cutoff**, expressed as `--accept-checkpoint $snapshotDigest`:

```powershell
& $python -I -m hermes_finance.forward_recovery_cli recover `
  --plan $plan --plan-sha256 $planDigest --accept-checkpoint $snapshotDigest
# After a failed/lost-ACK recover, use explicit resume, never repeat recover blindly:
& $python -I -m hermes_finance.forward_recovery_cli resume `
  --plan $plan --plan-sha256 $planDigest --accept-checkpoint $snapshotDigest
# Separate authoritative readback; this still does not Start:
& $python -I -m hermes_finance.forward_recovery_cli finish `
  --plan $plan --plan-sha256 $planDigest --accept-checkpoint $snapshotDigest
```

Stock CLI lifetime admission, direct migration and SQLite connection opening share
the same pre-writer admission protocol. The durable adjacent
`<database>.hermes-recovery.json` fence blocks Start even after process death; a
malformed or linked fence never means success. Recovery proves stopped ownership
and obtains native file/ancestor custody before its first operational mutation.
V1 refuses **any** WAL/SHM/journal/super-journal family member before SQLite reads;
it never checkpoints, deletes sidecars or repairs a hot journal. Immutable reads
are made only from handle-bound, sidecar-free bytes. A free port is insufficient.

After the fence is flushed, a fresh staging file is held from CREATE_NEW through
SQLite online backup and forward-only migration. All SQLite writers close before
stage sealing; original file ID and final hash must survive sealing. Final schema,
integrity/FK and every original table/column/row (including CLOSED/history and
provenance) are verified. Native non-overwriting handle renames retain the original
incident in the transaction directory and install the sealed stage at the same
production path without releasing live/stage custody or rebinding production.
The selected future code stays unchanged. A failed migration on stage does not
authorize rewriting released migrations or guessing a corrective release.

`recover` returns `installed_fenced`. Only `finish`, after source/code/binding,
incident and installed-file readback and a flushed acceptance receipt, retires the
fence into the transaction directory. Separate stock Start remains an explicitly
authorized operation. A lost finish ACK is reconciled from matching installed,
accepted and completed-fence records; `already_finished` is historical transaction
completion, not an assertion that later permitted financial writes are absent.

Explicit `resume` never re-migrates or overwrites a recorded sealed stage. Before
sealing, it can build a new unique stage while retaining incomplete attempts.
After incident/install renames it reconciles actual file IDs/hashes rather than
repeating destructive actions. Torn/foreign records, unknown object arrangements,
changed source/code/binding, late sidecars, disk/full-sharing failures or uncertain
outcomes leave the fence and all incident/stage evidence intact. Never manually
clear a fence, reuse an ambiguous target, delete incident files or retry Start.

Crash qualification covers abrupt **process termination** at durable phase
boundaries and lost ACK, including kernel handle/mutex cleanup. It does not claim
hardware/power-loss durability from file `fsync` alone. Following OS/storage/power
failure, preserve all objects, keep runtime stopped and reconcile authoritative
file identities and complete transaction records under local operational authority;
unproved namespace/record durability is not GO. No automatic repair/purge exists.
The synthetic service harness declares external release/installed-profile evidence;
native custody, subprocess Start/writer exclusion, forward migration, abrupt exits,
resume, finish and guarded CLI readiness are exercised on generated data. Those
checks do not attest the real Stable runtime or constitute Owner UAT.

<a id="o4-owner_runtime_operations-155"></a>
### Managed backup, retention and isolated recovery

<a id="o4-owner_runtime_operations-155-modes-and-owner-preconditions"></a>
#### Modes and Owner preconditions

`protection_state=protected`, `protection_mode=external_encrypted_destination_v1`, `format_version=1` requires an already opened/mounted readable/writable Owner-managed encrypted container/volume and independently available recovery material. Hermes does not validate/authenticate the key. A plain synced directory is not encrypted merely because it synchronizes.

The separately Owner-accepted pair is `owner_accepted_plaintext` / `synced_filesystem_destination_v1`. It supports an ordinary synced filesystem destination without claiming protected-at-rest encryption. Do not reclassify existing encrypted attestations. Any other pair fails closed. Aliases remain `protected-destination` and `synced-filesystem-destination`.

For either mode the destination must not alias production, Stable/Test/development, local backups or an ambiguous/reparse-linked path. Owner selects and attests the appropriate mode outside Git. Credentials, recovery material and private paths/payloads remain local. Local publication/read-back does not prove cloud delivery; off-device visibility is a separate Owner fact.


<a id="o4-owner_runtime_operations-155-publication-sequence"></a>
#### Publication sequence

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


<a id="o4-owner_runtime_operations-155-isolated-recovery-rehearsal"></a>
#### Isolated recovery rehearsal

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

All variables are explicitly verified Owner-local values. For plaintext use the matching accepted pair. Target profile/data/database must not already exist. The `-RuntimeConfig` argument takes an Owner-local JSON file following [runtime-inventory.example.json](schemas/runtime-inventory.example.json): `version` 1, `canonical_production` plus `profiles` entries each carrying absolute local `checkout`/`data_dir`/`database` paths, exactly one `stable` profile whose three paths equal `canonical_production`. The Owner creates and keeps that file outside Git at an Owner-local path, passes its explicit path on every rehearsal invocation, and never commits it with real paths. A missing, unreadable, non-version-1, incomplete or non-canonical inventory fails closed before any target is touched. Do not reinstall the GUI just to satisfy an unexplained missing reference.

The repository wrapper proves Git/boundaries before its first uv run, establishes its checkout-local environment, pins mutable preparation outputs and owns descendants under a deadline. Do not bypass it with an inherited-environment uv command. Source/target descriptors and snapshot identity are rechecked through preparation/start. A failed or ambiguous mutated target is not reused. Synthetic rehearsal is not Owner UAT or proof of cloud delivery.


<a id="o4-owner_runtime_operations-155-restore-read-state-requirement"></a>
#### Restore read-state requirement

After in-app restore, reread the month list from the restored DB. Keep the selected ID only if it exists; otherwise use the supported restored fallback or clear selection. Do not expose a stale pre-restore month as current (#462/#502). Confirmed-negative versus ambiguous restore outcomes retain #475 semantics.

<a id="o4-ui_v2_completion_closeout_2026-09-20-46"></a>
### Restore confirmation, ambiguity and concurrent-mutation guards

Final accepted UI safety behavior includes:

- exact backup target shown before confirmation;
- no restore POST before explicit owner confirmation;
- existing `{confirm:true}` backend contract preserved;
- pre-restore evidence shown only after confirmed success;
- previous evidence cleared before a new attempt;
- successful restore invalidates/refetches shared QueryClient state;
- confirmed backend rejection preserves good cached state;
- network/transport/body-read/malformed-success ambiguity is treated as **unknown**, not falsely as success or failure;
- unknown outcome performs safe QueryClient refresh without blind retry;
- one restore POST only;
- ConfirmDialog traps Tab/Shift+Tab focus;
- create-backup and restore mutations cannot overlap, including handler-level guards.

No new backup backend semantics were introduced.

<a id="o4-0017-protected-offsite-backup-and-recovery-9"></a>
### Complete protected/off-device recovery contract

<a id="o4-0017-protected-offsite-backup-and-recovery-9-1-decision-summary"></a>
#### 1. Decision summary

Hermes supports two explicit provider-neutral filesystem destination modes.

`external_encrypted_destination_v1` remains the protected mode. Its configured
destination must be the writable view of an already existing Owner-managed
encrypted container or volume whose encrypted backing storage is synchronized
off-device. Hermes does not encrypt an archive, derive or store keys, call a
cloud API, or upload in the background. An ordinary synced folder is not
protected.

`synced_filesystem_destination_v1` is the Owner-accepted plaintext synced
filesystem mode, recorded as `protection_state=owner_accepted_plaintext`. It
describes an ordinary synced folder, including the Owner's initial Google
Drive for desktop folder, and must not be labeled or attested as encrypted or
protected-at-rest. Hermes proves only local publication and destination
read-back for either mode. It does not claim Google or any other cloud
delivery. The Owner confirms off-device visibility separately. No Google API,
OAuth, SDK, cloud account, telemetry, or background upload service is added.

The Owner decision on #417, 2026-09-25, accepts this plaintext privacy
tradeoff and supersedes the earlier requirement that the off-device
destination be encrypted. Existing artifacts that already claim
`external_encrypted_destination_v1` are not retroactively reclassified.

This ADR freezes the contract for the managed recovery-point publisher,
retention, isolated disaster-recovery rehearsal, and post-restore read-state
invalidation. #459 publisher, #460 retention, #461 isolated DR, #462 restore
read-state, the real-rehearsal fixes #511/#524, and #527 plaintext synced mode
are accepted and integrated. On 2026-09-25 the Owner-live completion flow also
passed: fresh plaintext publication/read-back, independent off-device visibility,
and a clean isolated DR rehearsal with verified readiness and unchanged source.


<a id="o4-0017-protected-offsite-backup-and-recovery-9-2-at-rest-protection-contract"></a>
#### 2. At-rest protection contract

The protection decision is explicit and machine-readable:

```text
protection_state=protected
protection_mode=external_encrypted_destination_v1
format_version=1
```

```text
protection_state=owner_accepted_plaintext
protection_mode=synced_filesystem_destination_v1
format_version=1
```

The protected state is valid only after the Owner has attested outside Git
that the existing encrypted container/volume has already been successfully
opened or mounted and is readable and writable by the supported workflow.
Independent availability of recovery material remains an Owner-controlled UAT
gate for that mode. Hermes does not validate or authenticate that material.

The plaintext state is valid only when the Owner explicitly selects that exact
pair, accepting that the destination is an ordinary readable and writable
synced filesystem folder and is not encrypted. Its privacy-safe destination
alias is `synced-filesystem-destination`. The protected alias remains
`protected-destination`.

Hermes records or returns only the selected protection mode, format version,
and the matching privacy-safe destination alias.

The following are mandatory fail-closed rules:

- missing, unknown, unattested, unreadable, or unwritable protection boundary
  fails before destination staging;
- a normal Google Drive, OneDrive, Dropbox, Syncthing, NAS, or other synced
  folder is not protected merely because it synchronizes;
- plaintext publication succeeds only for the exact pair
  `owner_accepted_plaintext` + `synced_filesystem_destination_v1`;
- unknown states, unknown modes, and crossed pairs fail closed before
  destination staging or restore mutation;
- a published manifest must match the requested pair on later verification,
  retention, and disaster-recovery rehearsal;
- no key, credential, full private path, financial value, or reconstructive
  payload is persisted or logged;
- Hermes does not validate or authenticate a key or recovery material;
- independently available recovery material for the encrypted mode remains an
  Owner-controlled UAT gate and is not stored inside the recovery artifact or
  only on the laptop being backed up;
- plaintext publication does not claim cloud delivery.

Portable Hermes archive encryption would require a separate accepted design
for a vetted format/library, authenticated encryption, key derivation and
storage, rotation, packaging, and recovery. This ADR does not authorize it.


<a id="o4-0017-protected-offsite-backup-and-recovery-9-3-managed-recovery-point-contract"></a>
#### 3. Managed recovery-point contract

A recovery point is a single versioned managed artifact containing a
consistent SQLite snapshot and a deterministic manifest. The concrete
serialization is an implementation detail of #459, but the logical contract
is fixed:

- the snapshot is produced through the accepted SQLite online-backup path;
  copying a live `finance.db` is not a backup operation;
- the manifest identifies format version, one exact accepted protection
  state/mode pair, creation time, snapshot/schema identity, artifact size,
  deterministic artifact and snapshot hashes, the producing checkout's full
  40-character Git SHA, and the source database Alembic revision set as an
  exactly sorted deterministic set;
- verification accepts only that exact pair; publication, retention, and
  disaster-recovery rehearsal must request the same pair that the manifest
  records;
- a unique destination-local incomplete name is used while the artifact or
  manifest is incomplete;
- only one exact managed final-name pattern is eligible for listing or
  retention; incomplete, stale, corrupt, foreign, and unknown names are not
  recovery points;
- staging, manifest construction, SQLite integrity/foreign-key/schema checks,
  and deterministic hash checks complete before final exposure;
- final exposure uses an atomic same-filesystem rename/move;
- the destination artifact is read back and fully verified before the result
  may report `published` and `verified`;
- a destination-scoped exclusive lock rejects or safely serializes concurrent
  publication; a contended or ambiguous lock fails closed;
- an interrupted run must not leave a name that can be mistaken for a
  completed recovery point;
- a failed run preserves the newest previously verified recovery point.

Creation rejects snapshots larger than 256 MiB with `ProtectedBackupError`, before artifact construction or final exposure. A size rejection cleans up its temporary snapshot and preserves previously verified recovery points. Verification uses the same snapshot cap.

Verification checks archive budgets before reading members: exactly the ordered manifest and snapshot, no duplicate members, stored-only compression, a 64 KiB manifest and a 256 MiB snapshot, with at most 64 KiB additional container overhead. Artifact/descriptor reads are bounded independently of ZIP metadata. Oversized or compressed foreign artifacts fail closed; successful hashing alone does not waive these limits.

Destination validation occurs before staging. It rejects production data,
Stable/Preview/development checkouts, the normal local backup directory,
source artifacts, non-regular or reparse-linked paths, and ambiguous roots.
Path aliases are never treated as a substitute for proving the allowed
destination boundary.

The operation result is privacy-safe and distinguishes at least:

| Result fact | Meaning |
|---|---|
| `created` | A consistent snapshot was produced; it is not yet a published recovery point. |
| `verified` | Manifest, hashes, SQLite checks, and protection state passed before/after publication as applicable. |
| `published` | The exact final name was atomically exposed and destination read-back verification passed. |
| `action_required` | The operation did not complete or a follow-up owner action is required. |

The result may include only a destination alias/class, format/protection
versions, creation time, size, read-back state, retention outcome, and action
required. It must not include financial values, account identifiers,
credentials, encryption material, full private paths, or raw payloads.


<a id="o4-0017-protected-offsite-backup-and-recovery-9-4-retention-boundary"></a>
#### 4. Retention boundary

Retention runs only after a replacement has been fully published and read-back
verified. It is deliberately not a catalogue service:

- enumerate only exact managed final names whose artifact and manifest verify
  as the same accepted protection pair as the replacement;
- retain the newest 12 verified managed recovery points of that pair;
- in a directory that contains both accepted pairs, the bound is 12 verified
  managed points per accepted protection pair;
- perform no age-based expiry or deletion in v1;
- preserve the newest verified recovery point of the pair being replaced;
- never delete a verified point whose manifest pair differs from the
  replacement;
- never delete unknown, partial, corrupt, foreign, or unrelated files;
- never delete the newest verified point before its replacement is complete;
- report cleanup failure separately without invalidating a newly verified point.

Any cleanup of incomplete staging artifacts remains limited to the exact
managed incomplete-name contract. It must never become a general folder
cleanup operation.


<a id="o4-0017-protected-offsite-backup-and-recovery-9-5-isolated-disaster-recovery-rehearsal"></a>
#### 5. Isolated disaster-recovery rehearsal

The supported rehearsal proves recovery into a clean isolated Finance
profile. It is not a production restore and never overwrites Stable.

Before target mutation, the Owner explicitly selects one immutable full
40-character recovery Git SHA and an independent checkout pinned exactly to
that SHA. A branch or other ref without the full SHA, an ambiguous checkout,
or a dirty checkout fails closed. The selected recovery SHA may differ from
the producing SHA when the compatibility rule below accepts a forward
upgrade; recovery is not restricted to the producer SHA.

Before target mutation, the workflow must verify:

1. the source artifact is the expected managed format and its manifest,
   hashes, producer SHA, sorted source Alembic revision set, protection
   state, container readability, SQLite integrity, and foreign keys all pass;
2. the source artifact remains unchanged throughout verification and restore;
3. the selected recovery checkout is independent, clean, pinned exactly to
   the selected SHA, and its Alembic migration graph and supported head set
   are loaded;
4. every source revision is known to that graph, and exactly one of these
   relationships is accepted:
   - `same_revision`: the source revision set equals the selected checkout's
     supported head set;
   - `forward_upgrade`: one unambiguous supported forward-only Alembic path
     exists from the source revision set to the selected checkout's heads;
5. unknown, ahead, divergent, downgrade-required, ambiguous, or multiple
   unsupported paths fail closed before target mutation;
6. the target is a fresh isolated checkout/profile/data/database boundary;
7. Stable, Preview, development workspaces, local backup/source aliases,
   reparse/linked paths, non-empty targets, and conflicting targets are
   rejected;
8. only broad non-private structural counts and readiness facts are emitted.

After compatibility verification, re-read the selected checkout's Git SHA and
clean state immediately before the restore target write. If migration occurs,
perform a new identity/clean-state re-check immediately before migration. If
Start occurs, perform another new re-check immediately before Start. Every
phase must still equal the selected full SHA and remain clean. An identity
change fails closed before target mutation where possible and never proceeds
to migration or Start. Verification, the existing ADR 0014 schema-preflight,
guarded Prepare/Validate, migration, Start/readiness, and final evidence all
use that same selected SHA; this workflow does not create a second runtime
state machine.

The rehearsal restores into the isolated target and confirms that the
application can read restored months and core financial surfaces. Successful
privacy-safe evidence binds the managed artifact identity and hashes, producer
SHA, sorted source revision set, selected recovery SHA, selected checkout
head set, accepted relationship (`same_revision` or `forward_upgrade`), and
resulting readiness/schema/code identity. It does not perform cloud
operations or claim Owner UAT.


<a id="o4-0017-protected-offsite-backup-and-recovery-9-6-restore-read-state-contract"></a>
#### 6. Restore read-state contract

Successful existing in-app restore must invalidate affected owner-facing read
state. The month list is reloaded from the restored database; the selected
month ID is retained only when it exists in that list. Otherwise the client
selects the restored list's allowed fallback or clears selection when the list
is empty. Stale pre-restore month IDs and lists must not remain visible as
current.

The focused implementation and frontend regression are integrated through
#462 / PR #502. This ADR freezes the behavior without adding a new UI state
system or a backup-publisher UI.

<a id="o5"></a>

The inventory command is permanently read-only and bounded to an explicit local registry (schema retained at docs/schemas/owner-workspace-registry.schema.json), at most 64 entries per batch. It reports KEEP for protected roles, ACTIVE WORKSPACE for active/unresolved ownership and UNKNOWN for unresolved evidence; it never authorizes deletion. Use `python -B <ControlCheckout>/scripts/owner_workspace_inventory.py --registry <OwnerLocalRegistry>`. Default sanitized output is not payload discovery; --local-paths is Owner-only and must not be uploaded. Do not read DB/.env/backup contents, follow reparse targets, infer inactivity from age, or treat Git ref coverage/logical bytes as deletion proof.

## 5. Inventory, frozen-plan deletion and recoverable retirement

These are separate procedures. Inventory is bounded read-only structural classification, not disposal authorization. Frozen-plan deletion requires its exact independently authorized target plan, expiry/identity/quiescence and Windows no-follow guards. Scheduled retirement uses explicit managed lifecycle and same-volume recoverable rename; it never frees disk space, purges or substitutes for backup.

Current code accepts Scan/Retire and refuses legacy Apply. Merged code does not prove matched installation or a running scheduler. The installed helper can be inspected read-only without changing it. Scheduler activation/deployment is a separate accepted local operation; historical daily Apply/7-day instructions are superseded by the accepted retirement contract. S records only independently observed installation/scheduler facts.

<a id="o5-owner_workspace_cleanup-1"></a>
### Frozen-plan inventory and deletion procedure

<a id="o5-owner_workspace_cleanup-1-current-status-and-tool-selection"></a>
#### Current status and tool selection

#679/#666 migration and the named legacy cleanup are **CLOSED COMPLETE**. The [final report](https://github.com/LTstripes/hermes-finance/issues/679#issuecomment-5973182455) records all 54 Access Denied remnants removed and no remaining failures. Do not rerun the historical inventory/config/plan batches. The one-time Owner permission to discard those named technical histories is not future blanket deletion authority.

The accepted recurring retirement consumer is **`scripts/cleanup-workspaces.ps1` plus its native helper**, described below. Installed/scheduler identity is independently evidenced in S, not inferred from code. Its active Ops installation is protected even though it is outside the main Hermes folder. This page describes the separate conservative Python frozen-plan tool, not the scheduler.

Only the Owner or the one local Worker under an explicitly accepted operational assignment runs this on real paths. Ordinary agents use synthetic fixtures. Keep populated configuration, plans and journals outside Git, runtime trees and task workspaces. They contain local paths and must not be uploaded. The [inventory tool](#o1) remains read-only. This Python command implements no scheduler or automatic runtime migration.


<a id="o5-owner_workspace_cleanup-1-configuration"></a>
#### Configuration

All paths are absolute local fixed-disk paths selected by the Owner, not template literals.

| Field | Meaning |
| --- | --- |
| `version` | Integer `1` |
| `owner_root` | Protected Owner container; never a target |
| `stable`, `control`, `preview` | Mandatory protected runtime/code/data boundaries; current roles are Stable/Main/Test |
| `workspace_roots` | Configured roots pairwise disjoint from each other and protected boundaries |
| `entries` | Up to 64 explicit `path` + `role` entries (`workspace`, `unknown`, `stable`, `control`, `preview`) |
| `active`, `artifacts_resolved` | Explicit false / true required for evaluation; not inferred from historical registry or closed PR alone |
| `git_dir`, `git_common_dir` | For linked worktrees only: own registration and trusted Control's `.git` |

Targets must be immediate task children of configured roots. Active/unknown/out-of-boundary/unresolved entries are HOLD without payload inspection. Protected roots and client roots are not targets. Legacy linked worktrees outside trusted Control and independent clones with retained child worktrees remain HOLD under this generic tool. Do not generalize #679's exceptional discard decision into a changed generic classifier.

Use existing Python 3.12+, Git and authenticated gh from trusted Main/Control. It must be an independent clean main with HEAD and origin/main equal to freshly queried canonical GitHub main. Network/auth failures, unsafe config or incomplete scans refuse the run; the command does not fetch/reset/change credentials.


<a id="o5-owner_workspace_cleanup-1-plan"></a>
#### Plan

```powershell
& $Python -B "$CONTROL_CHECKOUT/scripts/owner_workspace_cleanup.py" `
  --config $OWNER_CLEANUP_CONFIG --plan $OWNER_FROZEN_PLAN
```

Plan-only is default. Its destination must be new. It freezes exact configuration, main, object/file identities, fingerprints, HEAD, shared refs and logical size; stdout is only canonical JSON SHA-256 and candidate/HOLD counts. Enumerated failure `reason` is privacy-safe; unknown exceptions become `unsafe_or_unresolved`. A Control-level refusal is not evidence that entries were evaluated. Logical size is not measured reclaimed disk space.

Eligibility requires a complete code-only plain scan, safe Git config, no runtime/private material, and clean index/bytes with no untracked/ignored files. Exact public repository exceptions remain narrowly defined by current source (#677/#678); ordinary project lockfiles are not Git administrative locks. The read-only inventory intentionally retains broader name heuristics. Do not extend public exceptions to arbitrary `.env*`, `data/*` or token-named content.

Unsupported index flags, alias/reparse/junction/symlink/hardlink, nested Git/submodules, locks, unsafe filters/includes, alternate/shallow/grafted graphs and incomplete evidence fail closed. Actual bytes are checked against index objects; status must also prove index=HEAD. Name checks cannot detect arbitrary renamed private payloads: only declared code-only workspaces may be evaluated.

HEAD must be in trusted Control and an ancestor of current main. Independent clones require all local refs/reflog history preserved, no stash/replacement refs or unreachable objects. Linked pointers require exact reciprocal registration/common-dir evidence; only ordinary own metadata and preserved ORIG_HEAD are removed, never shared refs/object store or unrelated history.


<a id="o5-owner_workspace_cleanup-1-apply"></a>
#### Apply

Review an unexpired exact local plan and authorize its canonical digest. Generic plans expire after 15 minutes; changed main/path/bytes/Git/config require a new plan and approval. An earlier issue discussion is not approval of an arbitrary future plan.

```powershell
& $Python -B "$CONTROL_CHECKOUT/scripts/owner_workspace_cleanup.py" apply `
  --config $OWNER_CLEANUP_CONFIG --plan $OWNER_FROZEN_PLAN `
  --approve-sha256 $OWNER_APPROVED_PLAN_SHA256
```

Windows-only Apply pins input/configuration/ancestors/objects, obtains fresh canonical evidence before each deletion and revalidates frozen identity/state. It deletes the checked objects via handles, not recursive link traversal, Git force, branch deletion or general worktree prune. Only the exact task and its own trusted registration are removed for linked worktrees.

An exclusive `.apply.jsonl` journal records digest/entry/time/revalidation/deletion outcome. Keep it Owner-local. Failure may leave a partially removed candidate; stop and reinventory with the journal retained. `deleting` or `refused_or_incomplete_reinventory_required` is not success. CLI replay is refused after any Apply attempt. No ACL/ownership repair, quarantine or automatic rollback is supplied. Missing platform support refuses deletion; Linux tests do not replace Windows probes.

The separate recurring janitor has its own accepted 7-day eligibility and deployment. Do not schedule this Python command or weaken its guards merely to make an old frozen plan work. Current operating boundaries are in [OWNER_MACHINE_LAYOUT](#o1).

<a id="o5-workspace_janitor-3"></a>
### Current Scan and recoverable retirement consumer

<a id="o5-workspace_janitor-3-current-contract"></a>
#### Current contract

The automatic consumer uses [recoverable workspace relocation](#o5-workspace_retirement-8).
It includes explicit managed lifecycle/worker enrollment for new standalone clones.
Scan is the default; Apply is refused. Retire relocates the same verified physical
root container with its actual contents to fixed recovery storage, without deletion,
Shell, copy/delete fallback, automatic restore or purge. It is not a snapshot or
backup and does not free disk space.

Only explicit completed managed checkouts can become eligible, after at least seven
days since both completion and relevant activity and all clean/publication/private/
process/root/cache guards. Active, paused, unknown, legacy, dirty, unpublished and
shared worktrees remain PRESERVE. Do not adopt or backdate old folders.

Install the two scripts/cleanup-workspaces.* files together under the existing
container-relative ops/workspace-cleanup location. The script derives only the four
fixed Hermes/workspaces/{codex,opencode,grok,hermes} roots, Ops and recovery/workspaces
from that installation. Main, Stable, Test/UAT, Owner, staging, backups, runtime,
Ops and recovery are excluded. Do not relocate Ops or change its ACLs/security.

After exact project acceptance and matched installation/rollback, validate synthetic
restore and review a fresh Scan. A separately authorized daily task uses the logged-in
Owner Interactive/Limited context, hidden WinPS5.1, IgnoreNew, StartWhenAvailable,
`-Operation Scan -Retire -RetentionDays 7`. Keep existing execution policy and
credentials; do not add an ExecutionPolicy override. No Finance runtime operations
or automatic classification of old tasks are involved.

The bounded structural latest report remains ops/workspace-cleanup-latest.json.
It never includes private contents or raw process/Git diagnostics. Scan may fetch
local-origin metadata for completed candidates; it is not strictly read-only.
Changed or uncertain relocation outcomes become NEEDS_REVIEW and preserve their
containers and journals, without automatic retry/restore/Resume/purge.

The existing Windows Release safety CI entrypoint scripts/tests/test-cleanup-workspaces.ps1
now runs the focused retirement regressions in a separate child after the full guards;
FixtureOnly initialization does not recurse. Retain the exact source/evidence scope
and do not replace missing Finance CI with Health evidence.


<a id="o5-workspace_janitor-3-historical-deployment"></a>
#### Historical deployment

<a id="o5-workspace_retirement-8"></a>
### Recoverable retirement, journals and explicit restore

Retirement moves the same verified root container with actual contents to a fixed
same-volume recovery folder. It is not a snapshot, backup or free-space reclamation.
No Shell, permanent deletion, purge, automatic restore or copy/delete fallback.

Existing clean/publication/private/process/standalone-clone guards, explicit
completion and seven days since both completion and activity remain. Active,
paused, unknown, legacy, dirty, unpublished and shared worktrees preserve. Runtime,
Stable/Test/UAT/Owner/Ops/staging/backups/recovery remain outside the fixed allowlist.

The existing FinanceDirectory installation derivation, four client roots, origin
and Global\HermesFinance.WorkspaceCleanup mutex are retained. The fixed recovery
root is FinanceDirectory/recovery/workspaces; no arbitrary CLI destination exists.
Root/ancestor handles and project mutex remain held. Descendant handles release
only after durable intent and v2 retiring state. Rename uses the checked root
handle on the same fixed local NTFS volume and never replaces a destination.

Bounded no-follow observation retains root DELETE binding before enumeration.
Manifests say NonSnapshot=true and contain metadata, not content hashes or an
atomic snapshot. Detected changes, reparse/private material, bounds, unexpected
old-path occupants and uncertain outcomes become durable NEEDS_REVIEW. Preserve
both objects; no automatic retry, restore, Resume, cleanup or purge follows.

Claims remain format1 for workers. Retirement format2 adds Transaction and blocked
retiring/retired/restoring/needs_review states, rejected by old readers. The journal
is strict ordered format2 with root/Git/enrollment/claim/generation, fixed destination,
before/after metadata digests and observation references. Prepared intent survives
crash; explicit Recover reconciles fixed locations without repeating moves.
Closed journal alone cannot admit an old completed record: the new paused claim
must be committed, or a later legitimate generation must exist.

Explicit Restore verifies the root and current observation, writes intent, performs
no-replace reverse rename to a vacant original path, inspects again and returns a
fresh paused claim. Changed/uncertain outcomes preserve NEEDS_REVIEW. Work requires
the separate Resume and CheckActive transitions. There is no adoption/override.

The consumer keeps bounds of 200 tasks, 25000 entries per task, depth128, 4MiB per
observation and 8KiB per journal/claim. Scan remains default and may fetch eligible
completed candidates, writing local Git metadata. Apply is refused; Retire moves.

For a change to these safeguards, verify scripts/tests/test-cleanup-workspaces.ps1 in WinPS5.1
using only synthetic roots. This existing Finance CI entrypoint now invokes
test-workspace-retirement.ps1 in a separate child after the full guards; FixtureOnly
setup does not recurse. Validate that chain in Finance exact CI and retain evidence.
The Health workflow is not copied over Finance CI. An apply-check is not acceptance.

Installation, recovery-directory changes, runtime actions, merge and scheduler changes require their assigned Finance acceptance/operational authority. Deploy matching readers
together with schedules disabled, verify synthetic restore and review a fresh Scan
before independently approved hidden Interactive/Limited daily Retire scheduling.
Stop future invocations for rollback, retain all records and containers, and never
restore an old automatic janitor that ignores retirement claims.


<a id="o5-workspace_retirement-8-new-managed-worker-checkouts"></a>
#### New managed worker checkouts

The installed matched helper exposes Invoke-WorkerLifecycle. A task assignment
supplies the configured client root, one new sanitized child, a unique owner and
the current local Claim. Dot-source the installed helper, then use Create before
clone, Bind after clone, and CheckActive before writes/tests/delivery. Pause retains
ownership. Resume returns a new Claim/generation: persist it locally and CheckActive
before continuing. Complete only after actual task delivery; completion is never
inferred from timestamps, directory age, Git cleanliness or a closed PR.

Create/Bind is for new checkouts only. No enrollment, adoption, backdating, state
reset or override exists for legacy or ambiguous folders. Claims are local authority:
never commit or publish them. Existing unregistered workspaces remain PRESERVE.
Without an accepted configured helper, follow the existing fresh uniquely named
checkout fallback in D2; that fallback does not enroll it.


<a id="o5-workspace_retirement-8-deployment-and-scheduler"></a>
#### Deployment and scheduler

Install both files together under the existing container-relative ops/workspace-cleanup
location with verified rollback and future invocations stopped. Preserve normal user
rights, current execution policy, ACLs and credentials. Do not start/restart Finance.
Validate one installed-pair synthetic roundtrip, then run Scan without Retire and
review every record. The independent daily task uses the current logged-in user,
InteractiveToken/Limited, hidden WinPS5.1, IgnoreNew and StartWhenAvailable with
`-Operation Scan -Retire -RetentionDays 7`. No ExecutionPolicy override is required.

Recovery is a separate fixed same-volume directory; it is never a scan root.
Relocation does not free space. Stop future invocations to roll back and preserve
all containers/claims/journals. After a v2 transaction, retain a compatible accepted
reader; never restore an old automatic deletion job. Explicit Recover/Restore is a
separate operational decision and never a scheduled retry or purge.

<a id="o6"></a>
## 6. Provider configuration and diagnostics

Use the selected checkout's documented public environment variable names and official adapters; keep actual credentials and `.env` local. T-Invest token setup/probe uses the accepted bounded read-only market provider contract. Alfa runs on its loopback router with version-pinned supported protocol and typed diagnostics; no historical orders/trades or speculative fallback. A current protocol failure is not cured by an old probe PASS. C9 owns provider entities, exact fields, units, freshness and reconciliation authority. Any live provider call needs the assigned operational authority; normal automated checks use synthetic transports.
