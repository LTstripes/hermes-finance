# Isolated instrument UAT runtime (#868)

Code capability only. This does not deploy a release or perform #867 Owner UAT.
Normal Start, recovery and `-ScratchPreflight` retain their existing behavior.

## Approved desktop option

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

## Operational boundary

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
# Bounded readiness + cleanup probe instead of an interactive session:
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

## Read and ingress guarantees

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

## Synthetic verification

```text
backend: pytest tests/test_instrument_uat_runtime.py tests/test_scratch_preflight_runtime.py
frontend: npm run build
frontend: npx playwright test --config=playwright.instrument-uat.config.ts
```

The browser harness fabricates current-schema source-backed stock/bond data,
closes its writer, then exercises the real hard-read-only engine and canonical
handlers. It is a test harness, not an alternative operator entrypoint. Full
manifest/process isolation is exercised by Windows launcher tests, including
forced outer-parent exit and port release. Neither synthetic evidence nor green
CI claims real Owner UAT or a Stable update.
