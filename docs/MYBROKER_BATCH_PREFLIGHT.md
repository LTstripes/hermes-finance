# MyBroker batch preflight

`POST /api/mybroker-preflight/preview` accepts multipart `files` (one to eight
original XML files) and an optional JSON `intent`. This is a pre-import inventory;
it neither executes BrokerMonth Preview nor creates a ReportingMonth, source,
receipt, mapping or financial row. There is no batch Apply endpoint.

Intent permits `account_bindings` with the existing identity-preview shape and
optional `requested_from` / `requested_to` dates supplied together. Omitted dates
select the uploaded filename-declared range. Bounds are 8 MiB per original,
32 MiB per batch, 30,000 parsed rows and 120 calendar months.
Multipart data is parsed directly from the request stream into bounded memory.
File count, each original and aggregate bytes are checked before extending a
buffer; originals are never spooled to temporary files. Headers and intent are
bounded separately. Batch account bindings are validated against all observed
aliases, then each document receives only its applicable bindings.

The service uses the existing S1 original grammar selector and native reducer,
strict identity planner, and H0 endpoint definitions inside a query-only committed
snapshot. The existing #804 original/inventory-bound incomplete-DRAFT classifier
may clear only proved nonidentity structure for the advisory DRAFT candidate
marker. Standalone identity stays strict; S1 warnings and all financial, H0 and
seam blockers remain visible. Previously persisted originals retain their recorded
Money grammar and must match their immutable binder. H0 remains the inventory of persisted accepted
sources; this preflight does not replace it. A new original's range is declared
by its filename under the S1 contract, not independently attested by this Preview.

The response separates:

- `documents`: original identity/range/parser, source-native position and separate
  RUB cash observations on each endpoint side, mappings/type/denomination evidence,
  unsupported section inventory, and distinct source/calendar/financial/DRAFT/
  Close statuses. Normalized Money, NKD and fee observations remain intact with
  unknown financial authority. An independently observed whole month may be a
  candidate for the existing separate reviewed incomplete DRAFT Preview.
- `calendar`: whole-month original availability and explicit references to source
  endpoint sides. Missing interior EOD is unknown. A partial or wide report proves
  only its own endpoints and dated events; it cannot lend intervening EOD or
  historical market valuations. A following first-day opening can reference the
  previous day's EOD without establishing a whole-month original.
- `seams`: adjacent ending versus opening quantities, source values and RUB cash,
  compared only for the same native source account. Differences use exact Decimal
  arithmetic; one kopeck is a conflict. Missing/ambiguous rows stay unknown. These
  comparisons also stay unknown for sub-kopeck cash or security values, even if
  the Decimal values are equal or their difference is an integral number of
  kopecks. No rounding or monetary minor-unit assertion is made in that case.
  The precision blocker prevents DRAFT candidacy for the affected seam.
  These comparisons do not attest complete settled inventory or financial coverage.
- `native_trade_inventory`: existing reducer projections plus occurrence lineage,
  exact duplicate/enrichment/pending-to-settled, changed core/material, missing
  overlap and multiplicity diagnostics. Repeated identical file uploads are
  counted as uploads, not new trade occurrences. Anonymous Money is never
  economically deduplicated. No second ledger is persisted.
- `report_availability`: explicit missing adjacent and 2025 originals. A known
  range is an observation, not proof of historical financial completeness.
  Adjacent originals are observed only for two consecutive full calendar-month
  originals with the same filename account and valid immutable binders. A
  contiguous seam between partial/wide reports cannot establish this availability.

`coverage_state` and `financial_completeness` remain `unknown`;
`financial_apply_available` is false and `close_performance` is blocked. Preflight
grants no source-account/portfolio crossing, H2, Close, XIRR or TWRR authority.
The Owner-original pilot is a separate later read-only UAT. Automated evidence
uses fabricated originals only; originals and private response values belong
outside Git, logs and public issue/PR evidence.

## Explicit scratch-only reader Start

Windows `scripts/start-local.ps1 -ScratchPreflight -ScratchManifest <absolute-manifest>`
opts into the separate read-only reader. `-ExitAfterReady` performs the bounded
owned-process smoke and cleans up its process tree. Without that switch the
reader stays available until its owning Start process is stopped. Standard Start
and recovery readiness retain their existing migration behavior. This mode cannot
be combined with recovery readiness and has no generic skip-migrations setting.

Prepare/Validate the independent detached exact-SHA checkout with its existing
supported commands first. The reader neither prepares nor restores anything.
An already authorized operator supplies one existing consistent standalone backup
in a physically separate scratch data directory, with no WAL/SHM/journal. The
database is opened with SQLite `mode=ro&immutable=1` after snapshot identity/hash
and isolation checks; immutable prevents sidecar creation even for a standalone
backup with a WAL-mode header. Live databases are not supported inputs. Windows
handles deny other write/delete opens and pin its ancestry for the runtime's life.
Missing/corrupt/linked files, sidecars, changed snapshot, schema drift and any
non-exact/multiple Alembic head refuse startup. No migration entry point is imported
or called. Clearing `query_only` cannot turn this connection into a writer.

The external Owner-local manifest has exactly these fields (placeholders below
are replaced privately; never commit a populated manifest):

```json
{
  "version": 1,
  "kind": "mybroker_preflight_scratch",
  "profile_id": "one-disposable-reader",
  "checkout": "<absolute independent prepared checkout>",
  "checkout_sha": "<full verified commit SHA>",
  "database": "<absolute existing scratch snapshot>",
  "database_identity": "<recovery_process.file_identity_token(snapshot)>",
  "snapshot_sha256": "<verified consistent snapshot SHA256>",
  "runtime_inventory": "<absolute current runtime-inventory JSON>",
  "control_checkout": "<absolute independent control checkout>",
  "owner_root": "<absolute protected Owner root>",
  "ops_root": "<absolute protected Ops root>",
  "workspace_roots": ["<absolute active client workspace root>"]
}
```

`runtime_inventory` follows `runtime-inventory.example.json`, with canonical
Stable and explicit Test/preview boundaries. Every active workspace root must be
declared; control worktrees are also excluded. The data directory's existing
`.hermes-data-identity.json` must equal
`{"kind":"mybroker_preflight_scratch","id":"one-disposable-reader"}`.
This is a disposable explicit binding, not a global registered runtime profile or
permission to create a backup, account or mapping. The code checkout cannot
contain `.env`, private data or a Preview pin. Its own prepared interpreter is
required, including for direct CLI `hermes-finance-api scratch-preflight` use.

Only `GET /api/health` and the existing `POST /api/mybroker-preflight/preview`
are registered. There is no frontend, generic catalogue/provider API, OpenAPI,
Apply or Close route. Localhost Host/Origin checks remain active. Health returns
the current PID, interpreter, process-start marker, SHA and bound DB identity;
Start verifies its fresh challenge headers and listener ownership before reporting
ready. These identity values and full preflight responses stay Owner-local.
Second-account mappings may remain blocked while source-native diagnostics are
available; this grants no mapping, DRAFT, financial or return acceptance.
