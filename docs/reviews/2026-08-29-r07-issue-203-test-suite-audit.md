# [Issue #203](https://github.com/LTstripes/hermes-finance/issues/203) — Test Suite Audit — Phase 1 report

Date: 2026-08-29
Scope: audit/report only; no test deletion, rename, reorganization, product-code change, merge, or PR

## 1. Verdict

The exact r07 baseline is healthy under the available local environment: the backend, frontend, synthetic visual audit, release contract scripts, launcher safety harness, and privacy guard all pass when run with the same source tree and the required Windows test-environment workarounds.

The suite is large but not presently a deletion problem. Most apparently old or duplicated tests are evidence for still-current financial, migration, provider-safety, release, or Windows invariants. The safe next step is a coverage map and lane taxonomy, followed by narrow helper/fixture consolidation. No test is classified as a confirmed obsolete deletion candidate in Phase 1.

The dominant cost is concentrated in database migration and release/startup tests rather than in parameter expansion:

- backend: 1,406 expanded cases in 140 test modules; 1,260 unique base nodes; 5:40.22 for the full run;
- frontend: 321 tests in 53 files; approximately 68.5 seconds wall time for Vitest;
- synthetic visual audit: 40 passed and 2 intentional viewport skips in 59.1 seconds;
- release PowerShell contracts: 62 assertions; the visual path Python check adds 3;
- .NET launcher safety: 11 hand-rolled safety cases.

## 2. Exact baseline, workspace, and source documents

| Item | Value |
| --- | --- |
| Audited source | `67fa84653be23c05852f2e05bd0c4bcd39c879f9` |
| Baseline ref | `origin/r07` at audit start |
| Clean task workspace | `D:\Finance\hermes-finance-codex\.codex-worktrees\r07-203-test-suite-audit` |
| Workspace state at audit start | detached `HEAD`, exact baseline, clean porcelain |
| Project rules | [`AGENTS.md`](../../AGENTS.md) |
| Verification protocol | [`docs/VERIFICATION_POLICY.md`](../VERIFICATION_POLICY.md) |
| CI configuration | [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml) |
| Release workflow checked | [`.github/workflows/release.yml`](../../.github/workflows/release.yml) |
| Backend test configuration | [`backend/pyproject.toml`](../../backend/pyproject.toml) |
| Frontend test/build configuration | [`frontend/package.json`](../../frontend/package.json), [`frontend/vite.config.ts`](../../frontend/vite.config.ts) |

The original development checkout was not used for task work because it acquired an unrelated untracked owner-side document during the audit. All source collection and execution used the isolated clean task workspace above. No private runtime database, `.env`, provider token, owner export, or live provider connection was used.

## 3. CI and local verification model

| CI lane | What it covers | Audit observation |
| --- | --- | --- |
| `privacy` | `scripts/privacy_check.py` and visual-audit path regression | Local privacy check passed: 718 tracked files checked. |
| `backend` | locked uv install, Ruff check/format, full `pytest -q` | Full backend passed. |
| `backend-timezone-windows` | Windows tzdata resolution plus Moscow and AI Analysis Bundle tests | Exact selected subset passed: 19 tests. |
| `frontend` | `npm ci`, Biome lint/format, Vitest, production build | Vitest/lint/build passed; Windows Biome format command reported baseline CRLF normalization noise. |
| `visual-audit-paths` | PR changed-path decision | Local Python contract check passed: 3 tests. |
| `visual-audit` | synthetic Playwright route/state audit | 40 passed, 2 expected skips. No backend or owner data. |
| `release-safety` | four PowerShell release/workflow contract scripts | 62 assertions passed. |
| `windows-production-smoke` | locked install, `start-local.ps1 -ExitAfterReady`, database creation, port cleanup | Could not reach application startup because local uv dependency bootstrap needed a blocked network download. This is an environment limitation, not a product/test failure. |
| `windows-launcher-safety` | .NET build and launcher safety harness | Build passed; 11 safety cases passed. |

The repository helper [`scripts/test.ps1`](../../scripts/test.ps1) is narrower than CI: it checks the backend lockfile/full tests and frontend tests/build, but omits Ruff, Biome, timezone-specific tests, visual audit, release contracts, production smoke, and launcher safety. This is a coverage/documentation gap, not a reason to delete either path.

## 4. Inventory

### 4.1 Backend

The tracked `backend/tests` tree contains 144 Python files:

- 140 collected test modules;
- 4 support modules: `conftest.py`, `_statement_pdf.py`, `startup_network_guard.py`, and `t_invest_mapping_fixtures.py`;
- 6 JSON fixtures under `backend/tests/fixtures` (Alfa PRO, MOEX ISS, and T-Invest synthetic shapes).

The authoritative collection result was **1,406 expanded cases**, **1,260 unique base nodes**, and **201 parameterized cases** from **55 parameterized test nodes**. The remaining **1,205 cases** are unparameterized. Parameterized expansion is therefore 14.3% of executed cases; it is material for a few files but not the main suite-size or runtime explanation.

The following layer counts are intentionally non-exclusive filename/directory classifiers. They explain the shape of the suite and must not be added together.

| Layer/classifier | Files | Expanded cases | Interpretation |
| --- | ---: | ---: | --- |
| `tests/domain/` | 12 | 151 | Pure financial/domain calculators and exact boundary rules. |
| Root backend test modules | 128 | 1,255 | API, service, persistence, integrations, release, and runtime tests currently live mostly flat. |
| `_api.py` endpoint classifier | 20 | 161 | HTTP/DTO/status/error contract coverage; other API tests have semantic filenames. |
| Provider/integration classifier | 23 | 359 | Alfa, T-Invest, MOEX identity, quotes, mappings, snapshots, reconciliation. |
| Import/export/legacy classifier | 12 | 158 | Statements, legacy Excel/mapping/migration, Markdown, AI bundle, backups. |
| Payout filename classifier | 14 | 160 | Domain, preview/apply/calendar, persisted payout, T-Invest payout adapters/probes. |
| Migration/runtime/security classifier | 15 | 74 | Alembic, startup, local security, timezone, SQLite, launcher schema, settings. |
| Release/task-ID filenames | 20 | 125 | R02/R04–R08 plus D06/F05/G02/G08 task-specific evidence. |
| R08 valuation/performance group | 7 | 68 | External-flow scope, valuation boundaries, availability, XIRR, TWRR. |
| `hardening`/`reread`/`scope_guard` suffixes | 5 | 10 | Follow-up regression fragments; meaningful scenarios, but fragmented layout. |
| R02–R06 release-ID files | 8 | 36 | Historical regression/release evidence, not automatically obsolete. |

#### Backend collection by file

This is the exact collection table used for the totals above. `Cases` is the number of expanded pytest cases, `nodes` is the number after removing parameter IDs, and `param` is the number of expanded cases with a parameter ID.

| File | Cases | Nodes | Param |
| --- | ---: | ---: | ---: |
| `tests/domain/test_cash_balance.py` | 6 | 6 | 0 |
| `tests/domain/test_coverage_goals.py` | 12 | 12 | 0 |
| `tests/domain/test_forecast_passive_income.py` | 22 | 17 | 7 |
| `tests/domain/test_iis_result.py` | 5 | 5 | 0 |
| `tests/domain/test_liquid_capital.py` | 7 | 7 | 0 |
| `tests/domain/test_monthly_summary.py` | 9 | 9 | 0 |
| `tests/domain/test_normalized_bonus.py` | 7 | 7 | 0 |
| `tests/domain/test_passive_income_average.py` | 15 | 15 | 1 |
| `tests/domain/test_passive_income.py` | 19 | 10 | 11 |
| `tests/domain/test_salary_tax.py` | 17 | 15 | 3 |
| `tests/domain/test_tax_iis_planner_domain.py` | 4 | 4 | 0 |
| `tests/domain/test_values.py` | 28 | 11 | 26 |
| `tests/test_accounts_api.py` | 11 | 11 | 0 |
| `tests/test_accounts.py` | 13 | 5 | 10 |
| `tests/test_ai_analysis_bundle_contract.py` | 9 | 9 | 0 |
| `tests/test_ai_analysis_bundle_export.py` | 5 | 5 | 0 |
| `tests/test_alfa_pro_probe.py` | 38 | 38 | 0 |
| `tests/test_alfa_pro_snapshot.py` | 51 | 42 | 12 |
| `tests/test_app_settings.py` | 4 | 4 | 0 |
| `tests/test_applied_payouts.py` | 14 | 14 | 0 |
| `tests/test_backups_api.py` | 5 | 5 | 0 |
| `tests/test_broker_snapshot_apply.py` | 25 | 25 | 0 |
| `tests/test_capital_composition_api.py` | 2 | 2 | 0 |
| `tests/test_cash_api.py` | 1 | 1 | 0 |
| `tests/test_cash_balance_service.py` | 19 | 11 | 10 |
| `tests/test_cash_flow_ladder.py` | 3 | 3 | 0 |
| `tests/test_cash.py` | 5 | 5 | 0 |
| `tests/test_cli.py` | 5 | 3 | 3 |
| `tests/test_close_readiness.py` | 13 | 13 | 0 |
| `tests/test_comments.py` | 6 | 6 | 0 |
| `tests/test_coverage_goals_service.py` | 5 | 5 | 0 |
| `tests/test_d06_events_api.py` | 12 | 9 | 4 |
| `tests/test_dashboard_api.py` | 6 | 6 | 0 |
| `tests/test_database.py` | 2 | 2 | 0 |
| `tests/test_debts.py` | 4 | 4 | 0 |
| `tests/test_deposits.py` | 6 | 6 | 0 |
| `tests/test_deterministic_insights.py` | 8 | 8 | 0 |
| `tests/test_expected_cash_flows.py` | 7 | 7 | 0 |
| `tests/test_expenses.py` | 5 | 5 | 0 |
| `tests/test_f05_restore_backup.py` | 6 | 6 | 0 |
| `tests/test_forecast_passive_income_service.py` | 14 | 12 | 3 |
| `tests/test_freshness_provenance.py` | 12 | 12 | 0 |
| `tests/test_g02_workflow.py` | 1 | 1 | 0 |
| `tests/test_g08_mvp_control.py` | 1 | 1 | 0 |
| `tests/test_goal_achievement_api.py` | 2 | 2 | 0 |
| `tests/test_goal_achievement.py` | 11 | 9 | 3 |
| `tests/test_goal_settings_sync.py` | 6 | 6 | 0 |
| `tests/test_goals_api.py` | 2 | 2 | 0 |
| `tests/test_goals.py` | 8 | 8 | 0 |
| `tests/test_health.py` | 1 | 1 | 0 |
| `tests/test_historical_batch_reads.py` | 1 | 1 | 0 |
| `tests/test_iis_api.py` | 18 | 18 | 0 |
| `tests/test_iis_result_service.py` | 7 | 7 | 0 |
| `tests/test_iis.py` | 6 | 6 | 0 |
| `tests/test_incomes.py` | 21 | 11 | 13 |
| `tests/test_instrument_mappings_api.py` | 23 | 23 | 0 |
| `tests/test_instrument_mappings.py` | 22 | 20 | 3 |
| `tests/test_instrument_type_compatibility.py` | 15 | 15 | 0 |
| `tests/test_instruments_api.py` | 11 | 11 | 0 |
| `tests/test_instruments.py` | 10 | 5 | 6 |
| `tests/test_investment_cash_flows.py` | 8 | 8 | 0 |
| `tests/test_launcher_schema_check.py` | 2 | 2 | 0 |
| `tests/test_legacy_excel.py` | 3 | 3 | 0 |
| `tests/test_legacy_migration_preview.py` | 3 | 3 | 0 |
| `tests/test_legacy_migration.py` | 9 | 9 | 0 |
| `tests/test_legacy_month_mapping.py` | 5 | 5 | 0 |
| `tests/test_liquid_capital_service.py` | 9 | 9 | 0 |
| `tests/test_local_security.py` | 7 | 7 | 0 |
| `tests/test_markdown_export_api.py` | 7 | 7 | 0 |
| `tests/test_markdown_export.py` | 2 | 2 | 0 |
| `tests/test_market_data_provider.py` | 25 | 25 | 0 |
| `tests/test_market_identity.py` | 9 | 5 | 5 |
| `tests/test_migrations.py` | 14 | 14 | 0 |
| `tests/test_month_clone.py` | 5 | 5 | 0 |
| `tests/test_month_guard.py` | 15 | 5 | 11 |
| `tests/test_monthly_summary_service.py` | 6 | 6 | 0 |
| `tests/test_months_api.py` | 7 | 7 | 0 |
| `tests/test_moscow_tz.py` | 5 | 5 | 0 |
| `tests/test_normalized_bonus_service.py` | 7 | 7 | 0 |
| `tests/test_normalized_reconciliation.py` | 8 | 8 | 0 |
| `tests/test_passive_income_average_service.py` | 8 | 8 | 0 |
| `tests/test_passive_income_service.py` | 17 | 15 | 3 |
| `tests/test_payout_api_hardening.py` | 3 | 3 | 0 |
| `tests/test_payout_api.py` | 10 | 8 | 3 |
| `tests/test_payout_apply_hardening.py` | 2 | 2 | 0 |
| `tests/test_payout_apply_reread.py` | 1 | 1 | 0 |
| `tests/test_payout_apply_scope_guard.py` | 1 | 1 | 0 |
| `tests/test_payout_apply.py` | 30 | 23 | 10 |
| `tests/test_payout_calendar.py` | 15 | 12 | 5 |
| `tests/test_payout_domain.py` | 33 | 23 | 13 |
| `tests/test_payout_preview_hardening.py` | 3 | 3 | 0 |
| `tests/test_payout_preview.py` | 22 | 15 | 10 |
| `tests/test_positions_deposits_api.py` | 20 | 20 | 0 |
| `tests/test_positions.py` | 9 | 9 | 0 |
| `tests/test_private_seed.py` | 5 | 5 | 0 |
| `tests/test_properties.py` | 6 | 6 | 0 |
| `tests/test_provider_capabilities.py` | 3 | 3 | 0 |
| `tests/test_quote_apply_api.py` | 5 | 5 | 0 |
| `tests/test_quote_apply.py` | 11 | 11 | 0 |
| `tests/test_quote_failure_ux.py` | 11 | 7 | 5 |
| `tests/test_quote_preview_api.py` | 6 | 6 | 0 |
| `tests/test_quote_preview.py` | 11 | 10 | 2 |
| `tests/test_r02_10_sqlite_locking.py` | 1 | 1 | 0 |
| `tests/test_r02_27_passive_goal_current_value.py` | 1 | 1 | 0 |
| `tests/test_r04_08_release_verification.py` | 6 | 6 | 0 |
| `tests/test_r04_08_windows_launcher_path.py` | 2 | 2 | 0 |
| `tests/test_r05_10_forecast_dashboard.py` | 11 | 8 | 5 |
| `tests/test_r05_11_release_verification.py` | 5 | 5 | 0 |
| `tests/test_r06_09_api.py` | 7 | 7 | 0 |
| `tests/test_r06_10_release_verification.py` | 3 | 3 | 0 |
| `tests/test_r07_t02_long_history_benchmark.py` | 1 | 1 | 0 |
| `tests/test_r08_01a_external_flows.py` | 12 | 12 | 0 |
| `tests/test_r08_01b_valuation_points.py` | 8 | 8 | 0 |
| `tests/test_r08_01c_performance_availability.py` | 12 | 12 | 0 |
| `tests/test_r08_02_portfolio_xirr.py` | 11 | 11 | 0 |
| `tests/test_r08_03_portfolio_twrr.py` | 8 | 8 | 0 |
| `tests/test_r08_03_twrr_contract_recon.py` | 5 | 4 | 2 |
| `tests/test_r08_03a_valuation_boundaries.py` | 12 | 12 | 0 |
| `tests/test_reconciliation_preview.py` | 31 | 31 | 0 |
| `tests/test_reporting_months.py` | 5 | 5 | 0 |
| `tests/test_risk_allocation.py` | 7 | 7 | 0 |
| `tests/test_salary_cardinality.py` | 9 | 9 | 0 |
| `tests/test_salary_tax_opening_api.py` | 3 | 3 | 0 |
| `tests/test_salary_tax_opening.py` | 8 | 8 | 0 |
| `tests/test_salary_tax_service.py` | 10 | 10 | 0 |
| `tests/test_settings.py` | 12 | 10 | 3 |
| `tests/test_startup.py` | 4 | 4 | 0 |
| `tests/test_statement_import_apply.py` | 40 | 40 | 0 |
| `tests/test_statement_import_retract.py` | 14 | 14 | 0 |
| `tests/test_statement_import.py` | 56 | 50 | 9 |
| `tests/test_static_app.py` | 2 | 2 | 0 |
| `tests/test_t_invest_matured_bond.py` | 5 | 5 | 0 |
| `tests/test_t_invest_payout_adapter.py` | 14 | 14 | 0 |
| `tests/test_t_invest_payout_coverage_guard.py` | 1 | 1 | 0 |
| `tests/test_t_invest_payout_probe.py` | 11 | 11 | 0 |
| `tests/test_t_invest_probe.py` | 9 | 9 | 0 |
| `tests/test_t_invest_provider.py` | 26 | 26 | 0 |
| `tests/test_t_invest_quotation.py` | 6 | 6 | 0 |
| `tests/test_tax_brackets_api.py` | 3 | 3 | 0 |
| `tests/test_tax_iis_planner.py` | 4 | 4 | 0 |

### 4.2 Frontend and E2E

Vitest uses jsdom, global test APIs, and `@testing-library/jest-dom`; it excludes the Playwright E2E directory. The 53 tracked Vitest files and 321 tests break down as follows:

| Frontend area | Files | Tests | Measured file-duration sum |
| --- | ---: | ---: | ---: |
| `src/api` | 6 | 25 | 0.086 s |
| `src/app` | 1 | 13 | 11.800 s |
| `src/components` | 18 | 119 | 35.976 s |
| `src/components/charts` | 6 | 29 | 2.755 s |
| `src/components/ui` | 1 | 3 | 0.733 s |
| `src/lib` | 8 | 52 | 0.086 s |
| `src/pages` | 13 | 80 | 31.753 s |
| **Total** | **53** | **321** | **83.188 s** |

The Vitest JSON report recorded 121 suite entries, all passing. File-duration sums include per-file setup and therefore exceed the approximately 68.5-second process wall time.

Playwright has two logical specs:

- `frontend/e2e/g04-smoke.spec.ts`: one critical monthly workflow (create month, salary, expense, deposit, dashboard, export). The default config lists it, but CI does not execute `npm run test:e2e` and this audit did not start it because its web servers require a valid backend bootstrap.
- `frontend/e2e/visual-audit.spec.ts`: 13 routed pages plus one loading/empty/error state. The visual config expands these 14 logical tests across three viewports to 42 cases; the state test intentionally runs only at 1440×900, giving 40 passes and 2 expected skips.

The default Playwright config lists 15 logical tests in the two files (one G04 test plus 14 visual tests) with one Chromium project. The synthetic visual runner starts only a loopback Vite server and uses deterministic fixtures.

### 4.3 Windows, release, and launcher system

| Surface | Inventory | Result |
| --- | --- | --- |
| `scripts/tests/test-release.ps1` | 37 assertions | PASS, 3.41 s |
| `scripts/tests/test-release-request.ps1` | 16 assertions | PASS, 1.43 s |
| `scripts/tests/test-release-workflow.ps1` | 5 assertions | PASS, 0.96 s |
| `scripts/tests/test-visual-audit-workflow.ps1` | 4 assertions | PASS, 0.86 s |
| `scripts/tests/test-visual-audit-paths.py` | 3 unittest cases | PASS, 0.38 s |
| `.NET` launcher safety harness | 11 cases | Build PASS, run PASS, 3.22 s after a 4.69 s build |
| Backend Windows-specific tests | `test_moscow_tz.py` 5 plus `test_r04_08_windows_launcher_path.py` 2 | Included in the backend inventory; the timezone/AI Bundle CI subset also passed separately. |

The launcher harness covers canonical config loading, unknown-field rejection, stable-profile cardinality, preview/database aliasing and hardlinks, sidecar identity, legacy schema probe selection, fail-closed readiness, quoted PowerShell paths, child-process database binding, and annotated release tags. These are safety contracts, not redundant UI tests.

## 5. Parameterization and runtime evidence

### 5.1 Backend parameterization

Only `parametrize` and platform `skipif` markers were found. There are no registered semantic markers for `slow`, `benchmark`, `legacy`, `release`, `network-free`, or `windows`; `strict-markers` is enabled in `backend/pyproject.toml`.

The largest expansion points were:

| Node | Expanded cases |
| --- | ---: |
| `tests/test_month_guard.py::test_closed_month_blocks_child_create_update_delete` | 11 |
| `tests/domain/test_passive_income.py::test_classify_excluded_flow_types_return_false` | 7 |
| `tests/test_alfa_pro_snapshot.py::test_string_primary_key_never_complete` | 6 |
| `tests/test_instruments.py::test_instrument_types_are_persisted` | 6 |
| `tests/test_accounts.py::test_account_types_are_persisted` | 6 |
| Two cash-balance service nodes | 5 each |
| Income/passive-income, provider-status, payout, and quote-sanitization nodes | 3–5 each |

This expansion is mostly deliberate boundary coverage. Flattening parameters would make the suite longer and less maintainable; the useful change is to make expensive categories selectable by marker/lane.

### 5.2 Slow backend groups

Full backend command:

```powershell
& <backend-venv>\Scripts\python.exe -I -m pytest -q --durations=30 --basetemp D:\Finance\pytest-basetemp-r07-203-full
```

Result: **1,406 passed in 340.22 seconds (5:40.22)**.

Representative slowest cases were:

| Time | Case |
| ---: | --- |
| 5.47 s | `test_migrations.py::test_instrument_mapping_migration_does_not_infer_legacy_moex_secid` |
| 5.15 s | `test_migrations.py::test_provider_neutral_identity_migration_preserves_moex_rows` |
| 4.92 s | `test_r08_01a_external_flows.py::test_scope_membership_migration_preserves_existing_flows_and_downgrades_safely` |
| 4.86 s | `test_r08_01a_external_flows.py::test_migration_keeps_ambiguous_legacy_rows_unclassified_and_downgrade_safe` |
| 4.85 s | `test_migrations.py::test_alembic_upgrades_and_downgrades_a_temporary_database` |
| 4.19 s | `test_migrations.py::test_applied_payout_migration_is_additive_and_preserves_manual_rows` |
| 3.87 s | `test_r08_01a_external_flows.py::test_migration_downgrade_refuses_to_delete_new_owner_data` |
| 3.51 s | another R08-01A migration/scope guard case |
| 3.44 s | `test_launcher_schema_check.py::test_probe_uses_selected_legacy_checkout_graph_without_legacy_probe` |

The exact output was dominated by repeated Alembic subprocesses, temporary SQLite databases, migration downgrade/data-preservation guards, and isolated startup probes. This points to lane separation or setup optimization, not removal of historical safety assertions.

### 5.3 Slow frontend groups

The hottest Vitest files were:

| File | Tests | File duration |
| --- | ---: | ---: |
| `src/app/App.test.tsx` | 13 | 11.800 s |
| `src/pages/MonthDetailPage.test.tsx` | 9 | 7.940 s |
| `src/components/MonthPositionsSection.test.tsx` | 23 | 7.522 s |
| `src/components/StatementImportPanel.test.tsx` | 10 | 5.622 s |
| `src/pages/AccountsPage.test.tsx` | 11 | 3.978 s |
| `src/components/MonthFlowsSection.test.tsx` | 14 | 3.621 s |
| `src/pages/GoalsPage.test.tsx` | 6 | 3.248 s |
| `src/components/MonthBudgetSection.test.tsx` | 5 | 2.903 s |
| `src/pages/PayoutsPage.test.tsx` | 9 | 2.776 s |
| `src/pages/ReconciliationCenterPage.test.tsx` | 7 | 2.768 s |

Page/component interaction suites are the cost center; API and library tests are near-zero. Splitting by user flow or reusing safe synthetic setup may help later, but deleting interaction assertions would reduce important month-lifecycle and provider-safety coverage.

## 6. Durable invariants that must survive cleanup

| Invariant | Current evidence | Phase 1 decision |
| --- | --- | --- |
| Exact financial arithmetic: `Decimal`, integer minor units, `ROUND_HALF_UP`; no binary-float financial calculation | `tests/domain/test_values.py`, salary/tax/forecast/cash tests, API decimal-string assertions, frontend backend-value rendering | **Keep.** High confidence; product financial contract. |
| Closed reporting months are immutable until explicit reopen; draft/reopened history is not silently known | `test_month_guard.py`, reporting/month API tests, release tests, `MonthDetailPage` and `PayoutsPage` tests | **Keep.** High confidence; lifecycle invariant. |
| Known zero is different from missing/unknown history; gaps are not fabricated; eligibility uses closed months and explicit boundary | passive-income domain/service tests, R08 valuation/performance tests, chart/page tests | **Keep.** High confidence; accepted historical semantics. |
| Backend is the financial source of truth; frontend formats supplied values and gates selected-month data | API contracts, dashboard/risk/allocation/tax/IIS/page tests | **Keep.** High confidence; prevents UI-derived financial drift. |
| Local loopback-only operation, no startup provider/network access, and no trading surface | `test_local_security.py`, startup network guard, R04–R06 release tests, provider capability tests, reconciliation/payout UI tests | **Keep.** High confidence; security boundary. |
| Provider integrations are read-only by construction; allowlists, authentication state, partial snapshots, and unavailable data fail closed | Alfa/T-Invest probe/snapshot/provider tests, `test_r06_09_api.py`, launcher/startup guards | **Keep.** High confidence; provider safety. |
| Migrations are additive/data-preserving and do not infer historical meaning; downgrade refuses observed owner data | `test_migrations.py`, R04/R05/R06 release tests, R08-01A migration guards | **Keep.** High confidence; data-safety contract. |
| Legacy import/mapping/migration paths remain supported and private-data-safe | four `test_legacy_*` modules, statement import/apply/retract, launcher legacy schema probe, legacy CLI entry points | **Keep.** High confidence; supported compatibility surface. |
| Reconciliation requires explicit mapping/preview and never silently overwrites monthly snapshots; incomplete evidence is non-actionable | R06 reconciliation, normalized reconciliation, broker snapshot, R08 valuation/availability tests | **Keep.** High confidence; financial integrity. |
| Release identity, sidecar, process-tree, path-with-spaces, and post-start cleanup behavior | PowerShell release tests, .NET harness, Windows launcher-path tests, production smoke contract | **Keep.** High confidence; Windows/release gate. |

These invariants are the boundary for any future rename, move, merge, or deletion. A filename containing an old issue ID is not evidence that the invariant is obsolete.

## 7. Historical regressions and release-ID tests

### 7.1 Current release/task-ID inventory

The 20 backend files whose names carry release/task IDs contain 125 expanded cases:

| Group | Files/cases | Examples of evidence | Decision |
| --- | ---: | --- | --- |
| R02 | 2 / 2 | SQLite locking; passive-income Goal current value from the accepted rolling average | Keep; current behavior. |
| R04 | 2 / 8 | Release migration/startup/network/provenance guards; Windows path with spaces | Keep; current release/Windows safety. |
| R05 | 2 / 16 | Forecast/dashboard semantics; 0.6.3 release compatibility and offline startup | Keep; current behavior plus release gate. |
| R06 | 2 / 10 | Alfa/provider API boundaries; 0.6.3 release compatibility and offline startup | Keep; current provider/release safety. |
| R07 | 1 / 1 | Long-history performance envelope | Keep the contract, but move to an explicit benchmark lane. |
| R08 | 7 / 68 | External-flow scope, valuation points, availability, XIRR, TWRR, boundary/reconciliation contracts | Keep; current financial contract. |
| D06/F05/G02/G08 | 4 / 20 | Events API, restore backup, HTTP monthly workflow, MVP control workflow | Keep pending comparison with current smoke/release lanes. |

The named release-verification subset is 14 cases in three files: R04 has 6, R05 has 5, and R06 has 3. R05 and R06 import migration helpers from `test_migrations.py` and startup helpers from `test_r04_08_release_verification.py`; that is real structural overlap and a future helper-extraction opportunity. It is not yet proof that the assertions themselves are duplicates.

### 7.2 History evidence

Recent history shows that the old IDs record genuine regressions or accepted follow-up decisions:

- `test_r02_10_sqlite_locking.py`: `204b227` records the R02-10 locking decision.
- `test_r02_27_passive_goal_current_value.py`: `346d865` and `59b31b3` lock the actual passive-income average and reviewer-blocker regressions.
- R04 release/Windows tests: `07dc2e1`, `0da5980`, `c68ca82`, and `ec9f56b` cover release regressions, provenance/startup safety, and PowerShell path encoding.
- R05/R06 release tests track the 0.6.0–0.6.3 release preparation and current health/startup contracts.
- R07 benchmark: `192f054` measures the long-history performance envelope.
- R08: `da7bfc4`, `029a119`, `bf3e7d6`, `b5b17dc`, `bb1e8d2`, and related commits close scope, valuation, availability, XIRR, and TWRR boundary regressions.

The evidence supports preserving these tests while changing their physical organization only after a node-level coverage map exists.

## 8. Overlap and duplication assessment

Static name overlap is not treated as duplicate coverage. The following clusters should be mapped before any deletion:

| Cluster | Evidence | What is genuinely distinct | Safe future action |
| --- | --- | --- | --- |
| Payout | 14 files / 160 cases; `hardening`, `reread`, and `scope_guard` fragments add 10 cases | Domain validation, preview, apply, calendar, persisted applied state, T-Invest transport, and UI/API boundaries | Extract shared synthetic fixtures and a semantic map; merge/rehome only exact duplicates. |
| Release verification | 3 release files / 14 cases plus common migration/startup helpers | Release-specific version, migration, offline startup, provider, and data-preservation assertions | Move common helpers to support module; keep release assertions in a release lane. |
| Statement import | `test_statement_import.py` 56, apply 40, retract 14 = 110 | Parse/preview, transactional apply, and reversible retract are separate supported operations | Keep three behavioral boundaries; consider a common fixture/module only. |
| Alfa PRO | Probe 38 and snapshot 51 = 89 | Transport/auth/allowlist normalization versus current broker snapshot DTO behavior | Keep separate provider boundaries; share sanitized fixture builders. |
| T-Invest | Seven provider/payout files, 72 cases | Market/provider, quotation, payout, matured bond, coverage guard, and probe contracts | Keep separate capabilities; consolidate only repeated fixture code. |
| Quote | Five quote API/service/failure files, 44 cases | Preview/apply APIs, service semantics, and sanitized failure UX | Preserve layer separation; map repeated closed-month/provider-error cases. |
| Reconciliation | Provider-neutral preview 31 plus normalized reconciliation 8 = 39 | Older preview contract versus newer normalized/read-only contract | Keep both until the newer contract fully supersedes the old API; then rehome with explicit product decision. |
| Frontend page/component suites | `App`, `MonthDetail`, `MonthPositions`, `StatementImportPanel` dominate runtime | Distinct user flows and state transitions, not simple duplicate assertions | Split by flow only if ownership/runtime benefits justify the churn. |
| Local aggregate versus CI | `scripts/test.ps1` repeats backend/frontend tests but omits six CI gate types | Developer convenience path versus canonical CI gates | Document or extend the matrix; do not delete either path in Phase 1. |

No pair was classified as a safe delete from names alone. The strongest near-term duplication is organizational: common fixtures/helpers and release suffix fragmentation, not redundant financial assertions.

## 9. Supported legacy coverage and obsolete candidates

### 9.1 Legacy paths that are explicitly supported

`backend/pyproject.toml` exposes `hermes-finance-legacy-mapping`, `hermes-finance-legacy-extract`, `hermes-finance-legacy-preview`, and `hermes-finance-legacy-migrate`. The four legacy modules contain 20 cases:

- `test_legacy_excel.py` — legacy sheet/cell extraction behavior;
- `test_legacy_month_mapping.py` — explicit period/sheet validation and sanitized CLI output;
- `test_legacy_migration_preview.py` — non-mutating preview;
- `test_legacy_migration.py` — backup, nullable ISIN, and migration application.

The launcher also tests the legacy-checkout schema-probe graph. These are supported compatibility and safety paths, not obsolete tests. The statement import/apply/retract tests and backup tests likewise cover current entry points and should remain.

### 9.2 Candidate list requiring Phase 2/product decisions

| Candidate | Proposed action | Confidence | Rationale/dependency | Product decision required |
| --- | --- | ---: | --- | --- |
| Release-version assertions in R05/R06 release files | Move or rename into a release-contract lane | Medium | Version assertions are intentionally release-specific; avoid scattering them through behavioral suites | Release owner decides canonical version gate. |
| Common startup/migration helpers imported across R04/R05/R06 | Extract support helper; do not remove assertions | High | Direct import overlap is confirmed | None beyond maintainer approval. |
| `*_hardening.py`, `*_reread.py`, `*_scope_guard.py` payout fragments | Rehome/merge by semantic boundary after mapping | Medium | Fragmentation is confirmed; scenarios are still meaningful | Owner/integrator approves final taxonomy. |
| `test_r07_t02_long_history_benchmark.py` | Mark or move to explicit benchmark/performance lane | Medium | Benchmark evidence is not a normal correctness gate; `test_historical_batch_reads.py` also consumes benchmark machinery | Decide whether CI full suite should include performance guard. |
| G02/G08 one-case workflow tests versus G04 | Compare and either keep as distinct acceptance checks or consolidate | Low | Similar workflow vocabulary, but no equivalence proof | Product/acceptance owner decides which workflow is canonical. |
| Older R04/R05/R06 assertions that resemble current migration/startup tests | Build node-level equivalence map; possible later merge | Low | Historical provenance is strong; static overlap is insufficient | Integrator must approve loss of historical file-level evidence. |
| Large frontend interaction files | Split by user flow if runtime/ownership benefit is demonstrated | Low | Runtime concentration is clear, but coverage is not duplicated | Frontend maintainer decides whether churn pays back. |

**Confirmed obsolete deletion candidates: none in Phase 1.** Deletion requires equivalent current coverage, preserved historical regression intent, supported-legacy review, and a product/integrator decision.

## 10. Proposed target taxonomy and prioritized cleanup

This is a proposal only; no directories or tests were changed.

### P0 — establish evidence before mutation

1. Add a small test-suite manifest or registered marker taxonomy: `domain`, `api`, `service`, `persistence`, `migration`, `integration`, `import_export`, `legacy`, `runtime`, `release`, `benchmark`, `windows`, and `network_free` as applicable.
2. Record owner, source contract, lane, and last-known regression/issue for every file or test group.
3. Keep an exact collection/timing baseline and require node-level comparison before merge/delete.

### P1 — low-risk lane and helper cleanup

1. Extract shared migration/startup/release helpers and synthetic provider fixtures without changing assertions.
2. Separate the long-history benchmark from the default correctness suite, preserving it in an explicit performance job.
3. Decide whether G04 is a CI Windows production-smoke/E2E gate or an explicit manual acceptance test; it is currently listed but not executed by CI.
4. Document the difference between `scripts/test.ps1` and canonical CI, or extend the helper deliberately after measuring the cost.

### P2 — semantic rehome/rename

Use the following target organization only when imports and history can be preserved:

```text
backend/tests/
  domain/
  api/
  services/
  persistence/
  migrations/
  import_export/
  integrations/
  runtime/
  release/
  legacy/
  benchmarks/
frontend/src/                 # existing api/lib/components/pages split is already useful
frontend/e2e/
  smoke/
  visual/
scripts/tests/                # release/path/workflow contracts
launcher/windows/...          # .NET safety harness
```

First rehome release/task-ID files and payout suffix fragments by semantic ownership, retaining issue IDs in comments or manifest metadata. Do not rename the frontend semantic directories merely to mirror a backend taxonomy.

### P3 — only after owner/integrator approval

1. Merge only proven-equivalent nodes.
2. Delete only after the current contract, historical regression, supported legacy path, and CI lane all have an explicit surviving owner.
3. Re-run the affected targeted lanes, full backend/frontend suites where required by the verification policy, and the Windows/release probes before delivery.

## 11. Commands and verification results

Commands below were run against the exact task workspace. The backend interpreter was an existing locked-equivalent local venv because task-local `uv sync --locked` could not bootstrap `hatchling` without network access. `PYTHONTZPATH` pointed only to a cached tzdata directory, and an explicit external pytest `--basetemp` avoided the inaccessible default Windows pytest temp root.

| Command/result | Outcome |
| --- | --- |
| `git rev-parse HEAD`; `git status --short --branch`; `git ls-files` inventory | Exact baseline and clean isolated workspace. |
| `python -I -m pytest --collect-only -q` | 1,406 expanded cases; 1,260 base nodes; 201 parameterized cases. |
| `python -I -m pytest -q --durations=30 --basetemp ...` | 1,406 passed in 340.22 s. |
| `ruff check .` | PASS. |
| `ruff format --check .` | PASS; 393 files already formatted. |
| `ZoneInfo('Europe/Moscow')` with cached tzdata path | PASS, `resolved Europe/Moscow`. |
| CI Windows subset: Moscow + AI Bundle contract/export | 19 passed in 5.62 s. |
| `npm ci --offline --no-audit --no-fund` | PASS; 162 packages installed in the task frontend. |
| `npm.cmd test -- --reporter=json ...` | 321 passed, 0 failed across 53 files. |
| `npm run lint` | PASS; Biome checked 189 files. |
| `npm run build` | PASS; Vite transformed 805 modules. Existing large-chunk warning remains informational. |
| `npm run format-check` | 188 errors on Windows, predominantly baseline CRLF→LF normalization plus an ignored generated visual-audit JSON file; no mass-formatting was performed. |
| `npm exec -- playwright test --config playwright.config.ts --list` | 15 logical tests in 2 files. |
| `npm run audit:visual` | 40 passed, 2 expected skips in 59.1 s. |
| Four release PowerShell scripts plus `test-visual-audit-paths.py` | 65 assertions/cases passed. |
| `dotnet build ...SafetyTests.csproj --configuration Release` | PASS, 0 warnings/errors. |
| `dotnet run ...SafetyTests.csproj --configuration Release --no-build` | 11 PASS. |
| `backend\.venv\Scripts\python.exe -I scripts/privacy_check.py` | PASS; 718 tracked files checked. |
| `scripts/start-local.ps1 -ExitAfterReady` with synthetic DB path | Could not start because task-local uv attempted a blocked network dependency build; no valid smoke result claimed. |
| `git diff --check` | PASS after report creation. |

The initial global uv invocation also hit the known Windows cache permission failure (`WinError 5`); the valid reruns used task-local/cached dependencies and explicit temp isolation. These environment failures are recorded separately from the green suite results.

## 12. Phase 1 decision

Phase 1 is complete. The suite needs taxonomy, ownership, lane selection, and helper consolidation; it does not yet justify mass deletion, rename, or reorganization. The next implementation task should begin only after the owner/integrator accepts this inventory and chooses the P1/P2 order.
