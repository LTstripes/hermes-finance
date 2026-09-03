# Test suite guide

This guide is the Phase 2A ownership and lane map for Hermes Finance. It is
additive: the existing regression tests remain in place, and the full test
commands still collect every existing test. The guide does not authorize
renaming, moving, merging, or deleting test files.

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
| `runtime` | Startup, settings, local security, static app, CLI, timezone, and launcher schema suites | Runtime safety | Loopback/offline startup and launcher contracts |
| `release` | Release verification plus F05/G02/G08 acceptance and Windows release-path checks | Release/task gate | Release workflow and task acceptance contracts |
| `benchmark` | `test_long_history_benchmark.py` and `test_historical_batch_reads.py` | Explicit performance lane | Long-history benchmark contract |
| `windows` | Windows launcher path, timezone, and launcher schema suites | Windows/runtime lane | Windows process/path/timezone behavior |
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
| `ci_core` | Backend core | Domain, service, general API, and explicitly mapped flat financial tests |
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

CI runs the five lanes as independent matrix jobs with `--durations=40` and a
10-minute job timeout. The existing Windows timezone job remains a dedicated
Windows check; its selected subset is intentionally preserved in addition to
the normal Linux correctness lanes.

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
| `launcher/windows/` safety harness | Windows process/filesystem safety |

Keep frontend tests in the existing API/lib/component/page split; do not add
backend-style directories only to make the trees look symmetrical.

## Useful targeted commands

From `backend/`, use a marker for a semantic implementation loop and the full
suite once the affected layer is stable:

```powershell
uv run --locked python -I -m pytest -q -m domain
uv run --locked python -I -m pytest -q -m "migration or persistence"
uv run --locked python -I -m pytest -q -m "integration and network_free"
uv run --locked python -I -m pytest -q -m benchmark
uv run --locked python -I -m pytest -q
```

`benchmark` is an explicit performance lane; it is preserved and selectable,
not silently removed from the default correctness suite in Phase 2A. A marker
selection is targeted evidence, not a claim that unrelated lanes passed.

## Local helper versus CI

The root `scripts/test.ps1` is a developer convenience path. It checks the
backend lockfile/full tests and frontend tests/build. The canonical CI matrix
also runs Ruff, Biome, the Windows timezone subset, synthetic visual audit,
privacy/path checks, release PowerShell contracts, production smoke, and the
.NET launcher safety harness. These are complementary lanes, not duplicate
test files.

Use `docs/VERIFICATION_POLICY.md` for the proportional implementation and
final-gate rules. When a task changes only docs or test organization, review
the diff and run the policy-relevant checks; do not rerun unrelated full
product suites merely because a release-ID file still exists.

## Deferred to Phase 2B

The following require a node-level coverage map and owner/integrator decision:

- rehoming or renaming release/task-ID files and payout suffix fragments;
- deciding whether G02/G08 are distinct acceptance evidence or overlap with
  the browser smoke path;
- comparing large frontend interaction suites and any exact duplicate nodes;
- deleting or merging any assertion, including an apparently old release
  regression.
