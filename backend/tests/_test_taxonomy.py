"""Stable path-to-marker mapping for the backend semantic test lanes."""

from __future__ import annotations

from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parent

_MARKER_ORDER = (
    "domain",
    "api",
    "service",
    "persistence",
    "migration",
    "integration",
    "import_export",
    "legacy",
    "runtime",
    "release",
    "benchmark",
    "windows",
    "network_free",
)

CI_LANE_MARKERS = (
    "ci_core",
    "ci_persistence",
    "ci_integrations",
    "ci_runtime_release",
    "ci_benchmark",
)

CI_CORE_SHARD_MARKERS = (
    "ci_core_a",
    "ci_core_b",
)

# Measured with `pytest -m ci_core --durations=0` on the refreshed canonical
# main candidate. Values are summed test/setup/teardown seconds per file; the
# assignment below is recomputed deterministically by weighted bin-packing.
CI_CORE_SHARD_WEIGHTS = {
    "domain/test_cash_balance.py": 0.03,
    "domain/test_coverage_goals.py": 0.05,
    "domain/test_forecast_passive_income.py": 0.05,
    "domain/test_iis_result.py": 0.05,
    "domain/test_liquid_capital.py": 0.05,
    "domain/test_monthly_summary.py": 0.05,
    "domain/test_normalized_bonus.py": 0.05,
    "domain/test_passive_income_average.py": 0.03,
    "domain/test_passive_income.py": 0.05,
    "domain/test_salary_tax.py": 0.05,
    "domain/test_tax_iis_planner_domain.py": 0.05,
    "domain/test_values.py": 0.05,
    "test_accounts.py": 5.03,
    "test_accounts_api.py": 6.33,
    "test_cash.py": 1.97,
    "test_cash_api.py": 0.60,
    "test_cash_balance_service.py": 7.12,
    "test_cash_flow_ladder.py": 1.22,
    "test_capital_composition_api.py": 4.85,
    "test_close_readiness.py": 17.73,
    "test_comments.py": 2.28,
    "test_coverage_goals_service.py": 2.61,
    "test_dashboard_api.py": 10.95,
    "test_d06_events_api.py": 11.32,
    "test_debts.py": 7.31,
    "test_deposits.py": 2.26,
    "test_deterministic_insights.py": 6.00,
    "test_expenses.py": 1.82,
    "test_expected_cash_flows.py": 3.28,
    "test_financial_context_api.py": 2.32,
    "test_forecast_passive_income_service.py": 5.15,
    "test_goal_achievement.py": 2.22,
    "test_goal_achievement_api.py": 1.14,
    "test_goal_settings_sync.py": 2.40,
    "test_goals.py": 2.70,
    "test_goals_api.py": 1.61,
    "test_iis.py": 1.90,
    "test_iis_api.py": 9.38,
    "test_iis_result_service.py": 2.46,
    "test_incomes.py": 6.68,
    "test_instruments.py": 3.56,
    "test_instruments_api.py": 5.16,
    "test_liquid_capital_service.py": 3.30,
    "test_monthly_summary_service.py": 3.34,
    "test_months_api.py": 3.25,
    "test_normalized_bonus_service.py": 4.01,
    "test_passive_income_api.py": 3.16,
    "test_passive_income_average_service.py": 6.49,
    "test_passive_income_read_model_service.py": 0.58,
    "test_passive_income_service.py": 14.37,
    "test_perf04a_attribution.py": 49.68,
    "test_planned_budget_service.py": 3.67,
    "test_portfolio_review_package.py": 24.54,
    "test_portfolio_review_package_assistant_eval.py": 0.07,
    "test_portfolio_review_package_contract.py": 0.13,
    "test_properties.py": 10.62,
    "test_r02_27_passive_goal_current_value.py": 0.41,
    "test_r06_09_api.py": 6.95,
    "test_r08_01c_performance_availability.py": 7.54,
    "test_r08_02_portfolio_xirr.py": 11.39,
    "test_r08_03_portfolio_twrr.py": 13.86,
    "test_r08_03_twrr_contract_recon.py": 2.63,
    "test_r08_03a_valuation_boundaries.py": 11.47,
    "test_r08_h2a_scope_membership_changed.py": 19.84,
    "test_r08_h2b_cash_boundary.py": 32.61,
    "test_r08_h2c_transfer_transit.py": 12.03,
    "test_r08_h2d_in_kind_coverage.py": 8.16,
    "test_r08_h3_tax_direct_payout.py": 6.97,
    "test_salary_cardinality.py": 5.03,
    "test_salary_tax_opening.py": 3.61,
    "test_salary_tax_opening_api.py": 2.99,
    "test_salary_tax_service.py": 4.12,
    "test_scenario_lab_api.py": 13.69,
    "test_scenario_lab_deposit_rate.py": 17.31,
    "test_scenario_lab_equity_drawdown.py": 46.03,
    "test_scenario_lab_fx_translation_shock.py": 7.81,
    "test_scenario_lab_inflation_real_value.py": 12.23,
    "test_tax_brackets_api.py": 1.47,
    "test_tax_iis_planner.py": 11.58,
}

_CI_LANE_OVERRIDES = {
    # Resolve legacy flat modules and ambiguous additive-marker combinations
    # explicitly. Keep this fail-closed so a new unclassified module cannot
    # disappear from every CI lane by inheriting a broad default.
    "test_accounts.py": "ci_core",
    "test_cash.py": "ci_core",
    "test_cash_flow_ladder.py": "ci_core",
    "test_close_readiness.py": "ci_core",
    "test_comments.py": "ci_core",
    "test_debts.py": "ci_core",
    "test_deposits.py": "ci_core",
    "test_deterministic_insights.py": "ci_core",
    "test_expected_cash_flows.py": "ci_core",
    "test_expenses.py": "ci_core",
    "test_goal_achievement.py": "ci_core",
    "test_goal_settings_sync.py": "ci_core",
    "test_goals.py": "ci_core",
    "test_iis.py": "ci_core",
    "test_incomes.py": "ci_core",
    "test_instruments.py": "ci_core",
    "test_portfolio_review_package.py": "ci_core",
    "test_portfolio_review_package_assistant_eval.py": "ci_core",
    "test_portfolio_review_package_contract.py": "ci_core",
    "test_properties.py": "ci_core",
    "test_r02_27_passive_goal_current_value.py": "ci_core",
    "test_r08_01c_performance_availability.py": "ci_core",
    "test_r08_02_portfolio_xirr.py": "ci_core",
    "test_r08_03_portfolio_twrr.py": "ci_core",
    "test_r08_03_twrr_contract_recon.py": "ci_core",
    "test_r08_03a_valuation_boundaries.py": "ci_core",
    "test_r08_h2a_scope_membership_changed.py": "ci_core",
    "test_r08_h2b_cash_boundary.py": "ci_core",
    "test_r08_h2c_transfer_transit.py": "ci_core",
    "test_r08_h2d_in_kind_coverage.py": "ci_core",
    "test_r08_h3_tax_direct_payout.py": "ci_core",
    "test_linked_pair_read_model.py": "ci_integrations",
    "test_ai_financial_review_linked_pairs.py": "ci_integrations",
    "test_perf04a_attribution.py": "ci_core",
    "test_salary_cardinality.py": "ci_core",
    "test_salary_tax_opening.py": "ci_core",
    "test_tax_iis_planner.py": "ci_core",
    "test_scenario_lab_api.py": "ci_core",
    "test_scenario_lab_deposit_rate.py": "ci_core",
    "test_scenario_lab_equity_drawdown.py": "ci_core",
    "test_scenario_lab_inflation_real_value.py": "ci_core",
    "test_scenario_lab_fx_translation_shock.py": "ci_core",
    "test_instrument_cleanup.py": "ci_persistence",
    "test_investment_cash_flows.py": "ci_persistence",
    "test_positions_deposits_api.py": "ci_persistence",
    "test_r08_01b_valuation_points.py": "ci_persistence",
    "test_instrument_mappings_api.py": "ci_integrations",
    "test_ci_lane_ownership.py": "ci_runtime_release",
}

_MIGRATION_FILES = frozenset(
    {
        "test_migrations.py",
        "test_r04_08_release_verification.py",
        "test_r05_11_release_verification.py",
        "test_r06_10_release_verification.py",
        "test_r08_01a_external_flows.py",
    }
)
_PERSISTENCE_FILES = frozenset(
    {
        "test_applied_payouts.py",
        "test_backups_api.py",
        "test_broker_baseline_apply.py",
        "test_broker_identity_mappings.py",
        "test_broker_snapshot_apply.py",
        "test_database.py",
        "test_month_clone.py",
        "test_month_guard.py",
        "test_positions.py",
        "test_sqlite_locking.py",
        "test_reporting_months.py",
    }
)
_INTEGRATION_FILES = frozenset(
    {
        "test_freshness_provenance.py",
        "test_instrument_mappings.py",
        "test_instrument_type_compatibility.py",
        "test_market_data_provider.py",
        "test_market_identity.py",
        "test_normalized_reconciliation.py",
        "test_provider_capabilities.py",
        "test_reconciliation_preview.py",
        "test_risk_allocation.py",
        "test_forecast_dashboard_integration.py",
    }
)
_RUNTIME_FILES = frozenset(
    {
        "test_app_settings.py",
        "test_cli.py",
        "test_health.py",
        "test_launcher_schema_check.py",
        "test_local_security.py",
        "test_moscow_tz.py",
        "test_settings.py",
        "test_startup.py",
        "test_static_app.py",
    }
)
_RELEASE_FILES = frozenset(
    {
        "test_f05_restore_backup.py",
        "test_g02_workflow.py",
        "test_g08_mvp_control.py",
        "test_r04_08_windows_launcher_path.py",
    }
)
_BENCHMARK_FILES = frozenset(
    {
        "test_historical_batch_reads.py",
        "test_long_history_benchmark.py",
    }
)
_WINDOWS_FILES = frozenset(
    {
        "test_launcher_schema_check.py",
        "test_moscow_tz.py",
        "test_r04_08_windows_launcher_path.py",
    }
)
_NETWORK_FREE_FILES = frozenset(
    {
        "test_ai_analysis_bundle_export.py",
        "test_alfa_pro_probe.py",
        "test_alfa_pro_snapshot.py",
        "test_local_security.py",
        "test_provider_capabilities.py",
        "test_r04_08_release_verification.py",
        "test_r05_11_release_verification.py",
        "test_r06_10_release_verification.py",
        "test_startup.py",
        "test_t_invest_probe.py",
        "test_t_invest_payout_probe.py",
    }
)


def semantic_markers_for(test_path: Path) -> tuple[str, ...]:
    """Return additive markers for a collected test path."""

    try:
        relative_path = test_path.resolve().relative_to(TESTS_ROOT)
    except ValueError:
        return ()

    filename = relative_path.name
    markers: set[str] = set()

    if relative_path.parts and relative_path.parts[0] == "domain":
        markers.add("domain")
    if filename.endswith("_api.py"):
        markers.add("api")
    if filename.endswith("_service.py"):
        markers.add("service")
    if filename.startswith("test_legacy_"):
        markers.update({"import_export", "legacy"})
    elif (
        filename.startswith("test_ai_analysis_bundle")
        or filename.startswith("test_markdown_export")
        or filename.startswith("test_statement_import")
        or filename == "test_private_seed.py"
    ):
        markers.add("import_export")

    if filename in _PERSISTENCE_FILES:
        markers.add("persistence")
    if filename in _MIGRATION_FILES:
        markers.add("migration")
    if filename in _INTEGRATION_FILES or any(
        filename.startswith(prefix)
        for prefix in (
            "test_alfa_pro_",
            "test_broker_",
            "test_payout_",
            "test_quote_",
            "test_t_invest_",
        )
    ):
        markers.add("integration")
    if filename in _RUNTIME_FILES:
        markers.add("runtime")
    if filename.endswith("_release_verification.py") or filename in _RELEASE_FILES:
        markers.add("release")
    if filename in _BENCHMARK_FILES:
        markers.add("benchmark")
    if filename in _WINDOWS_FILES:
        markers.add("windows")
    if filename in _NETWORK_FREE_FILES:
        markers.add("network_free")

    return tuple(marker for marker in _MARKER_ORDER if marker in markers)


def _relative_test_path(test_path: Path) -> Path | None:
    try:
        return test_path.resolve().relative_to(TESTS_ROOT)
    except ValueError:
        return None


def ci_lane_for_test_path(test_path: Path) -> str | None:
    """Return exactly one exclusive CI lane marker for a backend test file."""

    relative_path = _relative_test_path(test_path)
    if relative_path is None:
        return None

    key = relative_path.as_posix()
    if key in _CI_LANE_OVERRIDES:
        return _CI_LANE_OVERRIDES[key]

    markers = set(semantic_markers_for(test_path))
    if "benchmark" in markers:
        return "ci_benchmark"
    if markers.intersection({"release", "runtime", "legacy", "windows"}):
        return "ci_runtime_release"
    if "integration" in markers:
        return "ci_integrations"
    if "import_export" in markers:
        return "ci_integrations"
    if markers.intersection({"migration", "persistence"}):
        return "ci_persistence"
    if markers.intersection({"domain", "api", "service"}):
        return "ci_core"
    return None


def ci_core_shard_for_test_path(test_path: Path) -> str | None:
    """Return a deterministic duration-weighted shard for a core test file."""

    if ci_lane_for_test_path(test_path) != "ci_core":
        return None

    relative_path = _relative_test_path(test_path)
    if relative_path is None:
        return None

    key = relative_path.as_posix()
    if key not in CI_CORE_SHARD_WEIGHTS:
        return None

    assignments = {marker: set() for marker in CI_CORE_SHARD_MARKERS}
    totals = {marker: 0.0 for marker in CI_CORE_SHARD_MARKERS}
    for path, weight in sorted(CI_CORE_SHARD_WEIGHTS.items(), key=lambda item: (-item[1], item[0])):
        marker = min(
            CI_CORE_SHARD_MARKERS,
            key=lambda candidate: (totals[candidate], candidate),
        )
        assignments[marker].add(path)
        totals[marker] += weight

    return next(marker for marker, paths in assignments.items() if key in paths)


def iter_backend_test_files() -> tuple[Path, ...]:
    """Return all pytest-style backend test files in deterministic order."""

    return tuple(
        sorted(
            path
            for path in TESTS_ROOT.rglob("*.py")
            if path.name.startswith("test_") or path.name.endswith("_test.py")
        )
    )
