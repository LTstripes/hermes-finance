# Test suite guide

This guide is the Phase 2A ownership and lane map for Hermes Finance. It is
additive: the existing regression tests remain in place, and the full test
commands still collect every existing test. The guide does not authorize
renaming, moving, merging, or deleting test files.

## Current CI topology — 2026-10-04

The optimization wave is complete; this is the supported topology, not a queue for further speed work.

- **Ordinary PR concurrency (#671):** only a newer run of the same repository/workflow/PR cancels its predecessor. Canonical main, release and protected integration/UAT work use independent groups.
- **Visual ownership (#668):** tests that replace the project viewport execute once on the 1440 reference project; tests that genuinely use project viewport still retain the required 1366/1440/1920 coverage.
- **Exact-head UI evidence (#669):** the UI-evidence workflow still checks out the PR head and owns its screenshots, production dist build and provenance. Normal PR CI may omit the overlapping 1440 grep only when head, merge and checkout tree identity is proven; uncertainty falls back to full execution.
- **Docs-only PRs (#670):** the workflow always runs. A narrow fail-closed classifier permits the fast path only for explicitly allowlisted non-executable prose. Unknown/mixed/executable/build/test/release inputs, mode changes, rename/delete and classifier/workflow changes stay full. backend/README.md is deliberately full because Hatchling consumes it as package metadata. Canonical main pushes are always full.
- **Launcher retirement (#629):** the Launcher GUI/C# harness/package/install and launcher-only CI path/safety jobs are gone. Windows production smoke, direct start-local/prepared-runtime regressions, recovery, backup-first update and other shared runtime protections remain.

A green Documentation fast path means only that the candidate was proven safe docs-only and the retained classification/privacy/diff checks succeeded. It never claims that omitted product suites passed.

## Add a regression to the semantic owner

When a regression belongs to an existing behavior, add it to that behavior's
semantic suite. A release or issue identifier belongs in the test name only
when the test is specifically a release gate, version/compatibility check, or
task acceptance contract. For a historical regression that now protects a
current invariant, retain the scenario and its history in a comment or
docstring while keeping the test with the semantic owner.

Do not create a new `test_rXX_*` file merely to record the issue that exposed a
bug. If no suitable owner exists, document the gap first; a new lane or a
Phase 2B rehome may be appropriate after an explicit coverage comparison.

## Backend markers

The registered markers live in `backend/pyproject.toml`. The test
`conftest.py` applies them by stable path through
`backend/tests/_test_taxonomy.py`, so a new test added to an already mapped
file inherits that file's lane without boilerplate. Markers are additive: a
test may belong to both `migration` and `release`, for example. No marker
excludes tests from the normal full suite.

| Marker | Current ownership surface | Primary owner/lane | Contract or evidence |
| --- | --- | --- | --- |
| `domain` | `backend/tests/domain/` | Pure financial/domain rules | `docs/MASTER_SPEC.md` and accepted financial ADRs |
| `api` | Backend files ending in `_api.py` | HTTP/DTO/status contracts | API routes and their schemas |
| `service` | Backend files ending in `_service.py` | Application orchestration | Service contracts and domain tests |
| `persistence` | Database, reporting-month, applied-state, broker-state, and SQLite persistence suites | Persisted state | Persistence models and accepted migration contracts |
| `migration` | `test_migrations.py`, R04/R05/R06 release verification, and R08-01A migration coverage | Schema/data preservation | Alembic chain and additive/downgrade safety |
| `integration` | Alfa, broker, T-Invest, quote, payout, market, provider, reconciliation, and forecast/dashboard integration suites | Provider/integration boundaries | Accepted provider and read-only integration ADRs |
| `import_export` | Statement import, Markdown export, AI bundle, private-seed, and legacy interchange suites | Import/export boundary | Export/import contracts and privacy rules |
| `legacy` | `test_legacy_*.py` | Supported legacy compatibility | Legacy CLI and explicit mapping contracts |
| `runtime` | Startup, settings, local security, static app, CLI, and timezone suites | Runtime safety | Loopback/offline startup and direct-operation contracts |
| `release` | Release verification plus F05/G02/G08 acceptance and Windows release-path checks | Release/task gate | Release workflow and task acceptance contracts |
| `benchmark` | `test_long_history_benchmark.py` and `test_historical_batch_reads.py` | Explicit performance lane | Long-history benchmark contract |
| `windows` | Windows direct-runtime path (spaced/Cyrillic via `start-local`), timezone suites | Windows/runtime lane | Windows process/path/timezone behavior |
| `network_free` | Synthetic provider, startup, and release offline-boundary suites | Offline safety | No live provider or external network during the test |

The semantic mapping is intentionally not a mass classification of every flat
legacy test module. Existing modules may remain semantically unmarked and are
still covered by the full suite; the exclusive CI primary map below owns them
without renaming or moving files. This keeps the ownership decision reviewable
instead of hiding it in a bulk rename.

## Backend CI primary lanes

Issue #282 adds one exclusive primary CI marker to every collected backend
test. The additive semantic markers above remain useful for targeted local
debugging; they do not decide CI ownership when a test has more than one
semantic marker.

| Primary marker | CI lane | Ownership rule |
| --- | --- | --- |
| `ci_core` | Backend core (two deterministic weighted shards) | Domain, service, general API, and explicitly mapped flat financial tests; `ci_core_a` and `ci_core_b` split the same ownership by a committed duration-weighted test-file assignment |
| `ci_persistence` | Backend persistence | SQLite, persisted state, and migration tests |
| `ci_integrations` | Backend integrations | Provider, reconciliation, and import/export boundaries |
| `ci_runtime_release` | Backend runtime/release | Runtime, release, legacy, Windows, and CI-contract tests |
| `ci_benchmark` | Backend benchmark | Explicit benchmark/performance tests only |

`backend/tests/_test_taxonomy.py` owns the deterministic path-to-lane map.
`backend/tests/conftest.py` adds the primary marker to each collected node and
raises a collection error for an unclassified or conflicting node. The
`test_ci_lane_ownership.py` guard also inventories every pytest-style backend
test file. A new flat test module therefore requires an explicit owner before
any lane can pass; benchmark tests cannot silently join a correctness lane.

CI runs the five ownership surfaces as independent matrix jobs with the core
surface split into two deterministic duration-weighted shards (`ci_core_a` and `ci_core_b`),
`--durations=40`, and a 10-minute job timeout. The shard markers are additive
to `ci_core`; both shards together are the complete Backend core lane.

The dedicated Windows timezone job protects runtime `tzdata` availability,
`Europe/Moscow` calendar behavior, and real Windows runtime exports. A Linux
system IANA timezone database can mask a missing runtime dependency, as in
issue #164. The Windows job installs locked backend dependencies, including
`tzdata`, and retains a separate `ZoneInfo("Europe/Moscow")` probe. Dependency,
probe, or test failure blocks the job; its timeout remains 10 minutes.

Its pytest selection is:

- all of `tests/test_moscow_tz.py`;
- `tests/test_ai_analysis_bundle_export.py::test_bundle_export_is_schema_valid_full_history_and_read_only`;
- `tests/test_ai_analysis_bundle_export.py::test_ai_financial_review_route_is_schema_valid_and_read_only`.

This currently selects seven nodes: five timezone tests and two real export
integration tests. The export tests exercise production assembly, SQLite and
schema-file paths, UTF-8 responses, date-based filenames, deterministic output,
and read-only/network guards on Windows.

The complete `test_ai_analysis_bundle_contract.py` and
`test_ai_analysis_bundle_export.py` suites remain mandatory in the Linux
`ci_integrations` lane, including all 28 nodes outside this Windows selection.
The Moscow tests also remain in Linux `ci_runtime_release`. No test assertions
or Linux lane ownership are removed by this Windows selection.

Reassess the Windows subset whenever a new platform-specific export regression
appears. Add the relevant regression to the Windows selection and update this
coverage map when the existing selected tests do not protect its guarantee.

The shared support modules have these owners:

| Support module | Owner/lane | Use |
| --- | --- | --- |
| `backend/tests/_migration_helpers.py` | Migration/persistence | Locked synthetic Alembic execution and revision reads |
| `backend/tests/_network_helpers.py` | Integration/network-free | Forbidden transport for offline HTTP assertions |
| `backend/tests/_release_helpers.py` | Release/runtime | Isolated startup guard and persisted fingerprints |
| `backend/tests/t_invest_mapping_fixtures.py` | Integration | Accepted synthetic provider mapping without quote calls |
| `backend/tests/_statement_pdf.py` | Import/export | Synthetic statement document construction |
| `backend/tests/startup_network_guard.py` | Runtime/network-free | Startup probe and external-network guard |

## Frontend and external lanes

Vitest does not use pytest markers. Its existing directories are the semantic
ownership map:

| Surface | Owner/lane |
| --- | --- |
| `frontend/src/api/` | API client and DTO behavior |
| `frontend/src/lib/` | Pure formatting, period, chart, and display helpers |
| `frontend/src/components/` | Component and month-editor interactions |
| `frontend/src/pages/` and `frontend/src/app/` | Page and routing flows |
| `frontend/e2e/` | Synthetic smoke and visual behavior |
| `scripts/tests/` | Release, workflow, and changed-path contracts |

Keep frontend tests in the existing API/lib/component/page split; do not add
backend-style directories only to make the trees look symmetrical.

## Useful targeted commands

From `backend/`, use a marker for the semantic implementation loop. The full
command below is available when a local full gate is needed under
`VERIFICATION_POLICY.md`; it is not mandatory in addition to complete relevant CI.

```powershell
uv run --locked python -I -m pytest -q -m domain
uv run --locked python -I -m pytest -q -m "ci_core and ci_core_a"
uv run --locked python -I -m pytest -q -m "ci_core and ci_core_b"
uv run --locked python -I -m pytest -q -m "migration or persistence"
uv run --locked python -I -m pytest -q -m "integration and network_free"
uv run --locked python -I -m pytest -q -m benchmark
uv run --locked python -I -m pytest -q
```

`benchmark` is an explicit performance lane; it is preserved and selectable,
not silently removed from the default correctness suite in Phase 2A. A marker
selection is targeted evidence, not a claim that unrelated lanes passed.

## Local helper versus CI

The root `scripts/test.ps1` is an optional developer convenience path, not a
mandatory handoff command. It checks the backend lockfile/full tests and
frontend tests/build. The canonical CI matrix
also runs Ruff, Biome, the Windows timezone subset, the G04 synthetic
real-backend owner journey, synthetic visual audit, privacy/path checks,
release PowerShell contracts and production smoke (direct `start-local` /
`prepare-runtime` prepared-runtime lane). The retired Windows Launcher GUI,
C# safety harness, package/install smoke and its path-gated CI jobs were
removed by #629; `test_r04_08_windows_launcher_path.py` remains because it
covers the direct PowerShell runtime and spaced/Cyrillic paths, not the
retired shell.

The G04 browser gate is intentionally not path-filtered: it runs on every pull
request and canonical `main` push because either frontend routing/editor
changes or backend/API changes can break the same critical monthly workflow.
G04 remains its original deterministic journey. The #572 aggregate also retains
the accepted Performance preparation/PRE-POST journey, native statement
import/apply/readback (`playwright.statement.config.ts`) and native Monthly Close
edit/return/close/report/reopen (`playwright.monthly-close.config.ts`). They run
serially on temporary synthetic databases in the same required browser job;
the two acceptance configs serve the production frontend build. This is the
bounded aggregate gate, not a general browser harness redesign.

Use `docs/VERIFICATION_POLICY.md` for the proportional implementation and
final-gate rules. When a task changes only docs or test organization, review
the diff and run the policy-relevant checks; do not rerun unrelated full
product suites merely because a release-ID file still exists.

## Optional future coverage work — not active backlog

No issue is queued for the items below. Reopen one only when a product/risk need justifies a node-level coverage map and Owner/Integrator decision:

- rehoming or renaming release/task-ID files and payout suffix fragments;
- deciding whether G02/G08 are distinct acceptance evidence or overlap with
  the browser smoke path;
- comparing large frontend interaction suites and any exact duplicate nodes;
- deleting or merging any assertion, including an apparently old release
  regression.
