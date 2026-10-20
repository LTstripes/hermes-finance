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

CI_INTEGRATIONS_SHARD_MARKERS = (
    "ci_integrations_a",
    "ci_integrations_b",
)

CI_INTEGRATIONS_B_SHARD_MARKERS = (
    "ci_integrations_b1",
    "ci_integrations_b2",
    "ci_integrations_b3",
    "ci_integrations_b4",
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
    "test_instrument_cash_income_service.py": 8.0,
    "test_instrument_eod_observations_service.py": 8.0,
    "test_instrument_trades_service.py": 8.0,
    "test_instrument_what_if_service.py": 12.0,
    "test_source_intake_result_service.py": 13.0,
    "test_perf04a_attribution.py": 49.68,
    "test_planned_budget_service.py": 3.67,
    "test_portfolio_review_package.py": 24.54,
    "test_portfolio_review_package_assistant_eval.py": 0.07,
    "test_portfolio_review_package_contract.py": 0.13,
    "test_properties.py": 10.62,
    "test_r02_27_passive_goal_current_value.py": 0.41,
    "test_r06_09_api.py": 6.95,
    "test_r08_01c_performance_availability.py": 7.54,
    "test_performance_readiness.py": 5.0,  # Initial estimate for the new projection contract.
    "test_historical_membership.py": 5.0,
    "test_historical_source_xirr.py": 46.30,
    "test_performance_preparation.py": 5.0,  # Initial estimate for Owner write guards.
    "test_r08_02_portfolio_xirr.py": 11.39,
    "test_r08_03_portfolio_twrr.py": 13.86,
    "test_r08_03_twrr_contract_recon.py": 2.63,
    "test_r08_03a_valuation_boundaries.py": 11.47,
    "test_r08_h2a_scope_membership_changed.py": 19.84,
    "test_r08_h2b_cash_boundary.py": 32.61,
    "test_r08_493_month_delete_coverage.py": 8.0,
    "test_r08_621_month_delete_in_kind_coverage.py": 8.0,
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

# Duration-weighted module seconds for the two ci_integrations shards.
# Source: Actions run 39104674667 on 59c37875 (2530 passed in 1511.72s,
# --durations=40 call time 456.62s). Unlisted nodes use the residual rate
# (1511.72 - 456.62) / 2490. That same rate covers the 90 nodes added in
# test_statement_import_mybroker_endpoints.py by d0f5e7e. A module absent
# from this table has no shard, so collection fails closed.
CI_INTEGRATIONS_SHARD_WEIGHTS = {
    "test_ai_analysis_bundle_contract.py": 3.81,
    "test_ai_analysis_bundle_export.py": 11.44,
    "test_ai_analysis_bundle_financial_review_contract.py": 6.78,
    "test_ai_financial_review_linked_pairs.py": 2.54,
    "test_alfa_pro_probe.py": 16.10,
    "test_alfa_pro_snapshot.py": 21.61,
    "test_broker_baseline_apply.py": 6.78,
    "test_broker_identity_mappings.py": 5.93,
    "test_broker_snapshot_apply.py": 11.44,
    "test_forecast_dashboard_integration.py": 4.66,
    "test_freshness_provenance.py": 5.08,
    "test_instrument_mappings.py": 9.32,
    "test_instrument_mappings_api.py": 9.75,
    "test_instrument_type_compatibility.py": 6.36,
    "test_linked_pair_read_model.py": 3.39,
    "test_markdown_export.py": 0.85,
    "test_markdown_export_api.py": 4.24,
    "test_market_data_provider.py": 10.59,
    "test_market_identity.py": 3.81,
    "test_normalized_reconciliation.py": 3.81,
    "test_payout_api.py": 9.32,
    "test_payout_api_hardening.py": 1.27,
    "test_payout_apply.py": 12.71,
    "test_payout_apply_hardening.py": 0.85,
    "test_payout_apply_reread.py": 1.69,
    "test_payout_apply_scope_guard.py": 0.42,
    "test_payout_calendar.py": 7.20,
    "test_payout_domain.py": 13.98,
    "test_payout_preview.py": 9.32,
    "test_payout_preview_hardening.py": 1.27,
    "test_private_seed.py": 2.12,
    "test_provider_capabilities.py": 1.27,
    "test_quote_apply.py": 4.66,
    "test_quote_apply_api.py": 19.92,
    "test_quote_failure_ux.py": 4.66,
    "test_quote_preview.py": 4.66,
    "test_quote_preview_api.py": 2.54,
    "test_reconciliation_preview.py": 13.56,
    "test_risk_allocation.py": 2.97,
    "test_statement_import.py": 23.73,
    "test_statement_import_apply.py": 17.80,
    "test_statement_import_broker_statement_return.py": 129.71,
    "test_statement_import_broker_statement_provisional.py": 45.0,
    "test_statement_import_broker_statement_what_if.py": 130.43,
    "test_statement_import_executed_trades.py": 14.83,
    "test_statement_import_historical_endpoints.py": 36.44,
    "test_statement_import_historical_owner_flows.py": 52.97,
    "test_statement_import_historical_portfolio_flows.py": 25.42,
    "test_statement_import_historical_reconstruction.py": 13.14,
    "test_statement_import_mybroker.py": 46.19,
    "test_statement_import_mybroker_dispositions.py": 29.11,
    "test_statement_import_mybroker_empty_money.py": 59.75,
    "test_statement_import_mybroker_endpoints.py": 289.65,
    "test_statement_import_source_intake.py": 12.0,
    "test_statement_import_mybroker_identity.py": 11.02,
    "test_statement_import_mybroker_metadata.py": 58.90,
    "test_statement_import_mybroker_money_candidates.py": 18.64,
    "test_statement_import_mybroker_preflight.py": 21.61,
    "test_statement_import_retract.py": 6.78,
    "test_statement_import_source_cash_coverage.py": 270.51,
    "test_t_invest_matured_bond.py": 2.12,
    "test_t_invest_payout_adapter.py": 5.93,
    "test_t_invest_payout_coverage_guard.py": 0.42,
    "test_t_invest_payout_probe.py": 4.66,
    "test_t_invest_probe.py": 3.81,
    "test_t_invest_provider.py": 11.02,
    "test_t_invest_quotation.py": 2.54,
}

# Measured on Windows/Python 3.13.16 at 29cac23c for #902:
# `pytest -m ci_integrations_b --durations=0 --junitxml=...`, 1137 passed
# in 968.29s. JUnit times include setup/call/teardown. Keep the original
# A/B group weights above unchanged; these weights split only group B.
# The large source-cash module is grouped by test function (all parameter
# variants together); all other modules stay whole. Longest-first scheduling
# balances the four jobs without deleting or skipping any tests.
CI_INTEGRATIONS_B_SPLIT_FILES = frozenset({"test_statement_import_source_cash_coverage.py"})

CI_INTEGRATIONS_B_SHARD_WEIGHTS = {
    "test_ai_financial_review_linked_pairs.py": 4.00,
    "test_alfa_pro_snapshot.py": 1.02,
    "test_broker_identity_mappings.py": 5.39,
    "test_instrument_mappings.py": 7.47,
    "test_markdown_export_api.py": 5.98,
    "test_market_identity.py": 0.70,
    "test_payout_api_hardening.py": 1.20,
    "test_payout_api.py": 9.11,
    "test_payout_apply_reread.py": 1.61,
    "test_payout_apply_scope_guard.py": 0.34,
    "test_payout_calendar.py": 5.97,
    "test_payout_domain.py": 0.01,
    "test_provider_capabilities.py": 0.46,
    "test_quote_apply.py": 4.44,
    "test_quote_preview.py": 3.65,
    "test_risk_allocation.py": 3.04,
    "test_statement_import_apply.py": 24.08,
    "test_statement_import_broker_statement_provisional.py": 8.32,
    "test_statement_import_broker_statement_what_if.py": 168.81,
    "test_statement_import_executed_trades.py": 14.79,
    "test_statement_import_historical_owner_flows.py": 72.44,
    "test_statement_import_historical_reconstruction.py": 14.53,
    "test_statement_import_mybroker_dispositions.py": 42.65,
    "test_statement_import_mybroker_empty_money.py": 2.80,
    "test_statement_import_mybroker_identity.py": 15.74,
    "test_statement_import_mybroker_preflight.py": 21.18,
    "test_statement_import_retract.py": 10.68,
    "test_statement_import_source_cash_coverage.py::test_api_preview_apply_get_strict_inputs_and_writer_before_authoritative_reads": 0.59,
    "test_statement_import_source_cash_coverage.py::test_broken_source_withdrawal_binds_new_current_conflict_without_positive_support": 0.53,
    "test_statement_import_source_cash_coverage.py::test_commission_limitation_does_not_dismiss_material_trade_linkage_blockers": 3.66,
    "test_statement_import_source_cash_coverage.py::test_commission_limited_cash_fails_closed_on_conflicting_accepted_trade_support": 0.80,
    "test_statement_import_source_cash_coverage.py::test_coupon_v3_account_aba_stales_preview_and_never_revives_retired_coverage": 7.66,
    "test_statement_import_source_cash_coverage.py::test_coupon_v3_corrupt_current_source_owner_target_proof_fails_closed_without_read_repair": 76.12,
    "test_statement_import_source_cash_coverage.py::test_coupon_v3_dependency_retirement_late_failure_rolls_back_all_tables": 3.29,
    "test_statement_import_source_cash_coverage.py::test_coupon_v3_late_source_add_remove_aba_requires_both_reviews": 9.38,
    "test_statement_import_source_cash_coverage.py::test_coupon_v3_money_receipt_retires_closed_late_listener_replay_reaffirm": 33.13,
    "test_statement_import_source_cash_coverage.py::test_coupon_v3_only_proven_icf_partition_other_conflicts_stay_unknown": 14.05,
    "test_statement_import_source_cash_coverage.py::test_coupon_v3_pdf_first_real_money_links_existing_target_tax_unknown": 3.53,
    "test_statement_import_source_cash_coverage.py::test_coupon_v3_real_money_five_targets_overlap_no_write_no_owner_cash": 89.70,
    "test_statement_import_source_cash_coverage.py::test_coupon_v3_typed_pdf_addition_retires_coverage_and_mutations_are_monotonic": 17.52,
    "test_statement_import_source_cash_coverage.py::test_dependency_loss_retires_transactionally_no_a_b_a_or_receipt_revival": 5.49,
    "test_statement_import_source_cash_coverage.py::test_direct_sql_mismatch_read_and_list_assessor_fail_closed_without_repair": 0.70,
    "test_statement_import_source_cash_coverage.py::test_distinct_same_day_and_corroboration_bind_each_flow_once_every_occurrence": 0.70,
    "test_statement_import_source_cash_coverage.py::test_eod_window_excludes_opening_and_after_closing_preserves_multiplicity": 0.61,
    "test_statement_import_source_cash_coverage.py::test_exact_existing_trade_link_excludes_non_owner_cash_binds_trade_lifecycle": 0.45,
    "test_statement_import_source_cash_coverage.py::test_exact_historical_membership_covers_both_eod_boundaries_without_current_flags": 2.07,
    "test_statement_import_source_cash_coverage.py::test_exact_settled_trade_cash_preserves_commission_limitations_without_owner_crossing": 1.38,
    "test_statement_import_source_cash_coverage.py::test_full_ranges_clipped_union_exact_gap_not_hull": 0.86,
    "test_statement_import_source_cash_coverage.py::test_intent_shape_rejects_undefined_or_expanded_authority": 0.01,
    "test_statement_import_source_cash_coverage.py::test_legacy_complete_conflict_still_retires_v2_flow": 0.44,
    "test_statement_import_source_cash_coverage.py::test_mapping_remap_and_removed_binding_cannot_hide_previously_relevant_report": 0.60,
    "test_statement_import_source_cash_coverage.py::test_no_account_source_authority_or_portfolio_binding_from_missing_history": 0.37,
    "test_statement_import_source_cash_coverage.py::test_overlap_unknown_and_legacy_cash_disclosed_before_acceptance": 0.39,
    "test_statement_import_source_cash_coverage.py::test_paid_nkd_v4_corrupt_support_fails_closed_no_read_repair": 49.33,
    "test_statement_import_source_cash_coverage.py::test_paid_nkd_v4_dependency_transaction_aba_no_revival": 31.93,
    "test_statement_import_source_cash_coverage.py::test_paid_nkd_v4_exact_partition_no_economic_writes": 63.43,
    "test_statement_import_source_cash_coverage.py::test_paid_nkd_v4_late_money_retirement_closed_rollback_replay": 13.44,
    "test_statement_import_source_cash_coverage.py::test_paid_nkd_v4_opaque_money_does_not_inherit_disposition": 2.30,
    "test_statement_import_source_cash_coverage.py::test_paid_nkd_v4_unrelated_money_month_and_account_do_not_retire": 2.65,
    "test_statement_import_source_cash_coverage.py::test_positive_one_day_directed_dependency_and_legacy_reader_refusal": 0.69,
    "test_statement_import_source_cash_coverage.py::test_quiet_zero_requires_each_affirmative_claim": 2.44,
    "test_statement_import_source_cash_coverage.py::test_reaffirm_retired_is_explicit_identity_is_immutable_and_rollback_retirement_atomic": 0.62,
    "test_statement_import_source_cash_coverage.py::test_receipt_failure_rolls_back_projection_revision_and_receipt": 0.42,
    "test_statement_import_source_cash_coverage.py::test_retired_unresolved_flow_is_not_zero_and_apply_never_revives_it": 0.59,
    "test_statement_import_source_cash_coverage.py::test_same_identity_legacy_reaffirm_preserves_id_and_forbids_legacy_forgery_edits": 0.46,
    "test_statement_import_source_cash_coverage.py::test_section_aware_bad_receipt_scope_or_chain_real_reader_fails_closed": 5.45,
    "test_statement_import_source_cash_coverage.py::test_section_aware_dependency_aba_retirement_closed_replay_and_reviewed_reaffirm": 13.96,
    "test_statement_import_source_cash_coverage.py::test_section_aware_extra_quiet_report_retirement_keeps_overlapping_source_inventory": 1.14,
    "test_statement_import_source_cash_coverage.py::test_section_aware_grants_do_not_waive_money_or_material_exposure": 3.75,
    "test_statement_import_source_cash_coverage.py::test_section_aware_late_listener_receipt_retires_in_same_transaction_and_unrelated_does_not": 0.86,
    "test_statement_import_source_cash_coverage.py::test_section_aware_legacy_raw_blockers_never_inherit_grant": 0.69,
    "test_statement_import_source_cash_coverage.py::test_section_aware_legacy_v1_real_inventory_read_replay_and_explicit_version_reaffirm": 1.58,
    "test_statement_import_source_cash_coverage.py::test_section_aware_no_month_get_never_creates_scope_and_legacy_warnings_stay": 0.54,
    "test_statement_import_source_cash_coverage.py::test_section_aware_quiet_real_reader_shared_assessor_and_ten_gets_no_writes": 1.42,
    "test_statement_import_source_cash_coverage.py::test_section_aware_safe_a_never_clears_unsafe_b_both_orders": 1.61,
    "test_statement_import_source_cash_coverage.py::test_section_aware_signed_pair_stays_two_dated_crossings_and_a1_frozen_gate": 1.29,
    "test_statement_import_source_cash_coverage.py::test_section_aware_stale_apply_and_retirement_rollback_are_atomic": 0.99,
    "test_statement_import_source_cash_coverage.py::test_source_preview_stays_read_only_with_legacy_preparation_header": 0.51,
    "test_statement_import_source_cash_coverage.py::test_stale_preview_closed_guard_and_dependency_retirement_across_closed_interval": 0.63,
    "test_statement_import_source_cash_coverage.py::test_stale_request_conflict_noop_and_concurrent_writer_atomicity": 0.48,
    "test_statement_import_source_cash_coverage.py::test_trade_support_report_outside_window_is_bound_and_retires_new_assertion": 0.50,
    "test_statement_import_source_cash_coverage.py::test_unrelated_account_range_and_current_flags_preserve_authority": 0.60,
    "test_statement_import_source_cash_coverage.py::test_unresolved_money_opaque_currency_multiplicity_or_link_cannot_be_dismissed": 2.17,
    "test_statement_import_source_cash_coverage.py::test_v1_requires_explicit_same_core_version_reaffirmation_and_preserves_receipt": 0.57,
    "test_statement_import_source_cash_coverage.py::test_v3_late_receipt_retires_a1_and_a2_transactionally_even_closed": 4.14,
    "test_statement_import_source_cash_coverage.py::test_v3_real_a2_reader_shared_assessor_and_directed_reaffirmation": 2.53,
    "test_statement_import_source_cash_coverage.py::test_v3_transaction_failure_rolls_back_dependency_and_both_retirements": 1.26,
    "test_statement_import_source_intake.py": 22.57,
    "test_t_invest_payout_adapter.py": 0.01,
    "test_t_invest_payout_coverage_guard.py": 0.01,
    "test_t_invest_probe.py": 0.81,
    "test_t_invest_provider.py": 0.02,
    "test_t_invest_quotation.py": 0.01,
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
    "test_performance_readiness.py": "ci_core",
    "test_historical_membership.py": "ci_core",
    "test_historical_source_xirr.py": "ci_core",
    "test_performance_preparation.py": "ci_core",
    "test_r08_02_portfolio_xirr.py": "ci_core",
    "test_r08_03_portfolio_twrr.py": "ci_core",
    "test_r08_03_twrr_contract_recon.py": "ci_core",
    "test_r08_03a_valuation_boundaries.py": "ci_core",
    "test_r08_h2a_scope_membership_changed.py": "ci_core",
    "test_r08_h2b_cash_boundary.py": "ci_core",
    "test_r08_493_month_delete_coverage.py": "ci_core",
    "test_r08_621_month_delete_in_kind_coverage.py": "ci_core",
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
    "test_payout_lifecycle_migration.py": "ci_persistence",
    "test_r08_01b_valuation_points.py": "ci_persistence",
    "test_instrument_mappings_api.py": "ci_integrations",
    "test_ci_lane_ownership.py": "ci_runtime_release",
}

_MIGRATION_FILES = frozenset(
    {
        "test_migrations.py",
        "test_payout_lifecycle_migration.py",
        "test_r04_08_release_verification.py",
        "test_r05_11_release_verification.py",
        "test_r06_10_release_verification.py",
        "test_r08_01a_external_flows.py",
    }
)
_PERSISTENCE_FILES = frozenset(
    {
        "test_class_endpoint_eligibility.py",
        "test_class_returns.py",
        "test_applied_payouts.py",
        "test_backups_api.py",
        "test_protected_backups.py",
        "test_recovery_rehearsal.py",
        "test_broker_baseline_apply.py",
        "test_broker_identity_mappings.py",
        "test_broker_snapshot_apply.py",
        "test_database.py",
        "test_month_clone.py",
        "test_month_guard.py",
        "test_linked_pair_balance_evidence_concurrency.py",
        "test_r08_623_boundary_close_atomicity.py",
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
        "test_scratch_preflight_runtime.py",
        "test_instrument_uat_runtime.py",
        "test_owner_workspace_inventory.py",
        "test_owner_machine_relocation.py",
        "test_app_settings.py",
        "test_cli.py",
        "test_health.py",
        "test_local_security.py",
        "test_moscow_tz.py",
        "test_settings.py",
        "test_startup.py",
        "test_static_app.py",
        "test_recovery_process.py",
        "test_recovery_rehearsal.py",
    }
)
_RELEASE_FILES = frozenset(
    {
        "test_f05_restore_backup.py",
        "test_g02_workflow.py",
        "test_g08_mvp_control.py",
        "test_r04_08_windows_launcher_path.py",
        "test_recovery_process.py",
        "test_recovery_rehearsal.py",
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
        "test_moscow_tz.py",
        "test_r04_08_windows_launcher_path.py",
        "test_recovery_process.py",
        "test_recovery_rehearsal.py",
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
        "test_recovery_process.py",
        "test_recovery_rehearsal.py",
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


def _weighted_shard(
    key: str,
    weights: dict[str, float],
    markers: tuple[str, ...],
) -> str | None:
    """Assign one exclusive shard by duration-weighted list scheduling."""

    if key not in weights:
        return None

    assignments = {marker: set() for marker in markers}
    totals = {marker: 0.0 for marker in markers}
    for path, weight in sorted(weights.items(), key=lambda item: (-item[1], item[0])):
        marker = min(markers, key=lambda candidate: (totals[candidate], candidate))
        assignments[marker].add(path)
        totals[marker] += weight
    return next(marker for marker, paths in assignments.items() if key in paths)


def ci_core_shard_for_test_path(test_path: Path) -> str | None:
    """Return a deterministic duration-weighted shard for a core test file."""

    if ci_lane_for_test_path(test_path) != "ci_core":
        return None

    relative_path = _relative_test_path(test_path)
    if relative_path is None:
        return None
    return _weighted_shard(
        relative_path.as_posix(),
        CI_CORE_SHARD_WEIGHTS,
        CI_CORE_SHARD_MARKERS,
    )


def ci_integrations_shard_for_test_path(test_path: Path) -> str | None:
    """Return one exclusive duration-weighted shard for an integration file."""

    if ci_lane_for_test_path(test_path) != "ci_integrations":
        return None

    relative_path = _relative_test_path(test_path)
    if relative_path is None:
        return None
    return _weighted_shard(
        relative_path.as_posix(),
        CI_INTEGRATIONS_SHARD_WEIGHTS,
        CI_INTEGRATIONS_SHARD_MARKERS,
    )


def ci_integrations_b_shard_for_test_node(test_path: Path, nodeid: str) -> str | None:
    """Assign a B node; keep each split function's parameter variants together."""

    if ci_integrations_shard_for_test_path(test_path) != "ci_integrations_b":
        return None

    relative_path = _relative_test_path(test_path)
    if relative_path is None:
        return None
    key = relative_path.as_posix()
    if key in CI_INTEGRATIONS_B_SPLIT_FILES:
        prefix = f"tests/{key}::"
        if not nodeid.startswith(prefix):
            return None
        key += "::" + nodeid[len(prefix) :].split("[", 1)[0]
    return _weighted_shard(
        key,
        CI_INTEGRATIONS_B_SHARD_WEIGHTS,
        CI_INTEGRATIONS_B_SHARD_MARKERS,
    )


def iter_backend_test_files() -> tuple[Path, ...]:
    """Return all pytest-style backend test files in deterministic order."""

    return tuple(
        sorted(
            path
            for path in TESTS_ROOT.rglob("*.py")
            if path.name.startswith("test_") or path.name.endswith("_test.py")
        )
    )
