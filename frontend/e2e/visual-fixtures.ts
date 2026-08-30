const rub = (amount: string) => ({ amount, currency: "RUB" });

const longAccountName =
  "Синтетический брокерский счёт с очень длинным русским названием для проверки переноса";
const longInstrumentName =
  "Синтетическая облигация инфраструктурной компании с длинным наименованием выпуска";

export const syntheticMonths = Array.from({ length: 12 }, (_, index) => ({
  id: 12 - index,
  year: 2031,
  month: 12 - index,
  status: index === 0 ? "draft" : "closed",
  snapshot_date: `2031-${String(12 - index).padStart(2, "0")}-28`,
  source: "manual",
}));

export const syntheticAccounts = Array.from({ length: 10 }, (_, index) => ({
  id: index + 1,
  name: index === 0 ? longAccountName : `Синтетический счёт ${String(index + 1).padStart(2, "0")}`,
  account_type: index === 1 ? "iis" : "brokerage",
  status: "active",
  external_code: index === 0 ? "SYNTHETIC-ACCOUNT-WITH-A-LONG-SOURCE-IDENTIFIER-0001" : null,
  include_in_capital: true,
  include_in_returns: true,
  notes: index === 0 ? "Только синтетические данные для визуального аудита." : null,
}));

export const syntheticInstruments = Array.from({ length: 12 }, (_, index) => ({
  id: 101 + index,
  name:
    index === 0
      ? longInstrumentName
      : `Синтетический инструмент с длинной подписью ${String(index + 1).padStart(2, "0")}`,
  instrument_type: index % 2 === 0 ? "bond" : "stock",
  isin: `RU000SYN${String(index + 1).padStart(5, "0")}`,
  ticker: `SYNTHETIC-LONG-TICKER-${String(index + 1).padStart(2, "0")}`,
  moex_secid: null,
  currency: "RUB",
  nominal_value: rub("1000.00"),
  is_active: true,
  manual_price_allowed: true,
  notes: null,
}));

const dashboard = {
  month: syntheticMonths[0],
  kpis: {
    liquid_capital_net: rub("987654321098.76"),
    liquid_capital_delta: rub("123456789.01"),
    passive_income_actual: rub("9876543.21"),
    passive_income_delta: rub("-123456.78"),
    forecast_monthly_passive_income: rub("8765432.10"),
    forecast_annual_passive_income: rub("105185185.20"),
    passive_income_average: rub("7654321.09"),
    passive_income_average_months: 11,
    passive_income_average_complete: false,
    passive_income_history_start_month: "2031-01",
    passive_income_average_months_used: syntheticMonths
      .slice(1)
      .map((month) => `${month.year}-${String(month.month).padStart(2, "0")}`),
    goal_progress_pct: "98.75",
    goal_target: rub("10000000.00"),
    mandatory_expenses: rub("1234567.89"),
    mandatory_expense_coverage_pct: "709.98",
    actual_mandatory_expense_coverage_pct: "800.00",
    mortgage_balance: rub("123456789.01"),
    mortgage_coverage_pct: "800000.00",
  },
  summary: {
    forecast: {
      breakdown: {
        expected_deposit_interest: rub("99999999.99"),
        expected_coupon_net: rub("4444444.44"),
        expected_dividend_component: rub("740740.77"),
        other_expected_capital_income: rub("0.00"),
      },
      is_approximate: true,
      warnings: [
        "Синтетическое предупреждение с длинной русской формулировкой проверяет перенос текста внутри карточки и не содержит персональных значений.",
      ],
    },
  },
  mortgage: {
    mortgage_balance: rub("123456789.01"),
    coverage_pct: "800000.00",
    gap: rub("987530864309.75"),
  },
  historical_series: syntheticMonths
    .slice(1)
    .reverse()
    .map((month, index) => ({
      year: month.year,
      month: month.month,
      reporting_month_id: month.id,
      liquid_capital_net: rub(String(700000000000 + index * 20000000000)),
      passive_income_actual: rub(String(5000000 + index * 250000)),
    })),
  asset_allocation: [
    { asset_class: "cash", amount: rub("123456789.01") },
    { asset_class: "deposits", amount: rub("234567890.12") },
    { asset_class: "stocks", amount: rub("345678901.23") },
    { asset_class: "bonds", amount: rub("456789012.34") },
    { asset_class: "gold_other", amount: rub("56789012.34") },
  ],
  asset_allocation_delta: [
    { asset_class: "cash", amount: rub("1234567.89") },
    { asset_class: "deposits", amount: rub("-2345678.90") },
    { asset_class: "stocks", amount: rub("3456789.01") },
    { asset_class: "bonds", amount: rub("0.00") },
    { asset_class: "gold_other", amount: rub("56789.12") },
  ],
  result_by_account: syntheticAccounts.slice(0, 6).map((account, index) => ({
    account_id: account.id,
    account_name: account.name,
    account_type: account.account_type,
    cash_income: rub(String(1000000 + index * 100000)),
    unrealized_result: rub(String(500000 + index * 50000)),
  })),
  result_by_instrument_class: [
    {
      instrument_type: "bond",
      market_value: rub("456789012.34"),
      cost_basis: rub("400000000.00"),
      unrealized_result: rub("56789012.34"),
      realized_result: rub("1234567.89"),
    },
  ],
  warnings: [],
  calculation_version: "synthetic-visual-audit",
};

const capitalComposition = {
  asset_classes: ["cash", "deposits", "stocks", "bonds", "gold_other"],
  points: syntheticMonths
    .slice(1)
    .reverse()
    .map((month, index) => ({
      reporting_month_id: month.id,
      year: month.year,
      month: month.month,
      snapshot_date: month.snapshot_date,
      allocation: dashboard.asset_allocation,
      liquid_assets_total: rub(String(800000000000 + index * 10000000000)),
      included_debts: rub("123456789.01"),
      liquid_capital_net: rub(String(799876543210 + index * 10000000000)),
    })),
};

export const syntheticXirrReasonCode = "not_computable_xirr_root_ambiguity";

const portfolioXirr = {
  metric: "xirr",
  scope: "portfolio",
  performance_currency: "RUB",
  value: null,
  value_unit: "percentage_points",
  annualized: true,
  period: { start_date: "2031-10-28", end_date: "2031-11-28" },
  availability: "not_computable",
  quality: "unavailable",
  reason_codes: [syntheticXirrReasonCode],
};

const portfolioTwrr = {
  metric: "twrr",
  scope: "portfolio",
  performance_currency: "RUB",
  value: null,
  value_unit: "percentage_points",
  annualized: false,
  period: { start_date: "2031-10-28", end_date: "2031-11-28" },
  availability: "not_computable",
  quality: "unavailable",
  reason_codes: ["not_computable_valuation_boundary_missing"],
};

const support = (status = "supported", reasonCodes: string[] = []) => ({
  status,
  reason_codes: reasonCodes,
});

const allocationMetric = {
  support: support(),
  denominator: rub("987654321098.76"),
  covered_amount: rub("987654320000.00"),
  unallocated_amount: rub("1098.76"),
  coverage_pct: "99.99",
  items: syntheticAccounts.slice(0, 8).map((account, index) => ({
    key: index === 0 ? "stock" : `account:${account.id}`,
    label: account.name,
    amount: rub(String(900000000000 - index * 10000000000)),
    share_pct: String(40 - index * 3.25),
    account_id: account.id,
    instrument_id: null,
    instrument_type: index % 2 === 0 ? "stock" : "bond",
  })),
  excluded: [
    {
      source_kind: "position",
      source_id: 999999,
      status: "unavailable",
      reason_codes: ["unsupported_position_valuation"],
    },
  ],
};

const concentrationMetric = {
  support: support(),
  denominator: rub("987654321098.76"),
  top_n: 5,
  top_amount: rub("777777777777.77"),
  top_share_pct: "78.75",
  items: syntheticInstruments.slice(0, 8).map((instrument, index) => ({
    key: `position:${instrument.id}`,
    label: `${syntheticAccounts[index % syntheticAccounts.length].name} / ${instrument.name}`,
    amount: rub(String(200000000000 - index * 10000000000)),
    share_pct: String(25 - index * 2.25),
    account_id: syntheticAccounts[index % syntheticAccounts.length].id,
    account_name: syntheticAccounts[index % syntheticAccounts.length].name,
    instrument_id: instrument.id,
    instrument_name: instrument.name,
    instrument_type: instrument.instrument_type,
    position_id: index + 1,
    event_count: index + 1,
    is_approximate: index === 1,
  })),
  excluded: [],
  is_approximate: true,
};

const riskAllocation = {
  reporting_month_id: syntheticMonths[0].id,
  as_of_date: syntheticMonths[0].snapshot_date,
  base_currency: "RUB",
  liquid_assets_total: rub("987654321098.76"),
  allocation_by_asset_class: {
    ...allocationMetric,
    items: [
      { ...allocationMetric.items[0], key: "stock", label: "stock" },
      { ...allocationMetric.items[1], key: "bond", label: "bond" },
      { ...allocationMetric.items[2], key: "deposits", label: "deposits" },
      { ...allocationMetric.items[3], key: "unknown_asset_class", label: "unknown" },
    ],
  },
  allocation_by_account: allocationMetric,
  top_positions: concentrationMetric,
  payout_concentration: { ...concentrationMetric, items: concentrationMetric.items.slice(0, 4) },
  redemption_concentration: {
    ...concentrationMetric,
    items: concentrationMetric.items.slice(2, 6),
  },
  support: {
    asset_class: support(),
    account: support(),
    issuer: support("unavailable", ["issuer_not_persisted"]),
    currency: support("unknown", ["currency_not_persisted"]),
    maturity: support("unavailable", ["maturity_not_persisted"]),
    broker: support("unavailable", ["broker_identity_not_persisted"]),
    bank: support("unavailable", ["bank_identity_not_persisted"]),
  },
};

const freshnessFamilyItems = syntheticInstruments.slice(0, 10).map((instrument, index) => ({
  item_kind: "quote",
  label: instrument.name,
  freshness_status: index % 2 === 0 ? "stale" : "current",
  source_kind: index % 2 === 0 ? "t_invest" : "manual",
  source_timestamp_kind: "price_date",
  source_date: `2031-12-${String(10 + index).padStart(2, "0")}`,
  source_datetime: null,
  fetched_at: "2031-12-22T10:00:00+00:00",
  import_apply_time: "2031-12-22T10:05:00+00:00",
  local_edit_time: "2031-12-22T10:06:00+00:00",
  reason_codes: index % 2 === 0 ? ["quote_stale"] : [],
  account_name: syntheticAccounts[index % syntheticAccounts.length].name,
  instrument_name: instrument.name,
}));

const freshness = {
  reporting_month: syntheticMonths[0],
  evaluated_on: "2031-12-28",
  quote_valuation_target_date: "2031-12-28",
  generated_at: "2031-12-28T12:00:00+00:00",
  providers: ["t_invest"],
  reasons: [
    {
      code: "quote_stale",
      severity: "warning",
      message:
        "Есть синтетические котировки старше окна актуальности; длинная формулировка проверяет перенос текста без выхода из панели.",
    },
  ],
  families: [
    {
      family_id: "market_quotes",
      title: "Рыночные котировки с длинными синтетическими наименованиями",
      status: "mixed",
      providers: ["t_invest"],
      coverage: {
        row_count: freshnessFamilyItems.length,
        current_count: 5,
        stale_count: 5,
        unavailable_count: 0,
        unknown_count: 0,
        missing_count: 0,
        manual_count: 5,
        provider_count: 5,
      },
      reasons: [
        {
          code: "quote_stale",
          severity: "warning",
          message: "Часть котировок устарела относительно выбранной даты оценки.",
        },
      ],
      items: freshnessFamilyItems,
    },
    {
      family_id: "manual_month_data",
      title: "Ручные данные месяца",
      status: "not_applicable",
      providers: [],
      coverage: {
        row_count: 1,
        current_count: 0,
        stale_count: 0,
        unavailable_count: 0,
        unknown_count: 0,
        missing_count: 0,
        manual_count: 1,
        provider_count: 0,
      },
      reasons: [],
      items: [],
    },
  ],
};

const diagnostics = {
  schema_version: "alfa-pro-diagnostics/v1",
  provider: "alfa_pro",
  snapshot_status: "complete",
  eligible_for_apply: false,
  compatibility_state: "compatible",
  compatibility_fingerprint: "a".repeat(96),
  api_doc_version: "synthetic-2.1",
  observed_alfa_pro_version: "synthetic-compatible-build-with-a-long-version-label",
  observed_api_version: "2.1",
  observed_protocol_version: "router-v1",
  protocol_family: "router-v1",
  layout_family: "snapshot-layout-v2.1-with-long-synthetic-suffix",
  capabilities: ["position_quantity"],
  failure_class: "none",
  failure_codes: [],
  entity_status: ["positions=ok"],
  entity_counts: ["positions=12"],
  observed_fields: ["position.quantity"],
  safe_artifact: true,
  raw_payload_saved: false,
  private_values_included: false,
  credentials_included: false,
};

const reconciliationRows = syntheticInstruments.slice(0, 8).map((instrument, index) => ({
  state: index === 0 ? "unresolved" : index % 2 === 0 ? "differs" : "matched",
  account_id: syntheticAccounts[index % syntheticAccounts.length].id,
  instrument_id: instrument.id,
  account_name: syntheticAccounts[index % syntheticAccounts.length].name,
  instrument_name: instrument.name,
  instrument_isin: instrument.isin,
  instrument_ticker: instrument.ticker,
  provider_account_id: `SYNTHETIC-PROVIDER-ACCOUNT-${String(index + 1).padStart(3, "0")}-${"A".repeat(24)}`,
  provider_instrument_id: `SYNTHETIC-PROVIDER-INSTRUMENT-${String(index + 1).padStart(3, "0")}-${"B".repeat(24)}`,
  hermes_quantity: "123456789.1234",
  provider_quantity: index % 2 === 0 ? "123456790.1234" : "123456789.1234",
  quantity_difference: index % 2 === 0 ? "1" : "0",
  quantity_equal: index % 2 !== 0,
  hermes_market_price_per_unit_kopecks: 987654321,
  provider_broker_unit_price: "9876543.21",
  provider_accounting_price: "8765432.10",
  provider_market_value: "999999999999.99",
  price_comparable: "non_comparable",
  hermes_accrued_interest_kopecks: 12345678,
  provider_accrued_interest_nkd: "123456.78",
  nkd_comparable: "non_comparable",
  hermes_unrealized_result_kopecks: 777777777,
  provider_unrealized_result: "7777777.77",
  unrealized_comparable: "non_comparable",
  reason: index === 0 ? "instrument_mapping_unresolved" : null,
  warnings: index === 0 ? ["mapping_unresolved"] : [],
  comparison_only_fields: ["provider_market_value"],
  fingerprint: "c".repeat(96),
}));

const reconciliation = {
  reporting_month_id: syntheticMonths[0].id,
  provider: "alfa_pro",
  status: "applicable",
  read_only: true,
  eligible_for_apply: false,
  stale: false,
  snapshot_status: "complete",
  compatibility_state: "compatible",
  compatibility_fingerprint: "a".repeat(96),
  snapshot_fingerprint: "d".repeat(96),
  source_as_of: "2031-12-28T10:00:00+00:00",
  captured_at: "2031-12-28T10:01:00+00:00",
  month_status: "draft",
  month_closed: false,
  accounts: [],
  instruments: [],
  rows: reconciliationRows,
  cash: [],
  warnings: [],
  diagnostics,
  diagnostic_report: "safe synthetic diagnostics only\n",
  error_code: null,
  message: null,
};

const taxPlanner = {
  contract_version: "tax_iis_planner_v1",
  tax_year: 2031,
  as_of: { reporting_month: syntheticMonths[0], selection_reason: "requested" },
  salary_tax: {
    tax_year: 2031,
    history_complete: false,
    history_coverage: "unavailable",
    available: false,
    opening_context_available: false,
    taxable_gross_ytd: null,
    current_marginal_bracket: null,
    current_marginal_rate_bps: null,
    next_threshold: null,
    distance_to_next_threshold: null,
    tax_bracket_source: "official_default",
    warning_codes: ["salary_tax_history_incomplete"],
  },
  iis_accounts: [
    {
      account_id: 2,
      account_name:
        "Синтетический индивидуальный инвестиционный счёт с длинным названием для проверки карточки",
      iis_type: "type_a",
      opened_at: "2031-01-01",
      eligible_close_at: "2036-01-01",
      contributions_by_tax_year: Array.from({ length: 6 }, (_, index) => ({
        tax_year: 2031 - index,
        amount: rub(String(400000 + index * 11111.11)),
        is_target_reached: index % 2 === 0,
      })),
      tax_benefits: {
        planned: rub("6000000.00"),
        submitted: rub("5000000.00"),
        received: rub("4000000.00"),
        rejected: rub("1000000.00"),
      },
    },
  ],
  warnings: ["salary_tax_history_incomplete"],
};

const monthSummary = {
  month: syntheticMonths[0],
  salary_tax: { tax: rub("1604938.26"), calculated_net: rub("10716049.63") },
  salary_actual_net: rub("10716049.63"),
  coverage: {
    mandatory_expenses: rub("1234567.89"),
    coverage_pct: "709.98",
    goal_target: rub("10000000.00"),
    goal_progress_pct: "98.75",
    warnings: [],
  },
};

const incomeRows = [
  {
    id: 1,
    reporting_month_id: syntheticMonths[0].id,
    income_type: "salary",
    name: "Зарплата",
    gross_amount: rub("12320987.89"),
    tax_amount: rub("1604938.26"),
    net_amount: rub("10716049.63"),
    received_at: "2031-12-25",
    is_recurring: true,
    include_in_cash_flow: true,
    include_in_passive_income: false,
    notes: null,
  },
];

const settings = {
  base_currency: "RUB",
  locale: "ru-RU",
  timezone: "Europe/Moscow",
  passive_income_goal: rub("10000000.00"),
  formula_version: "v1",
  passive_income_history_start_month: "2031-01",
};

const backups = [
  {
    id: "synthetic-backup-2031-12-28",
    name: "synthetic-finance-visual-audit.db",
    created_at: "2031-12-28T12:00:00+00:00",
    size_bytes: 987654321,
    source_database: { name: "synthetic-finance.db", size_bytes: 987654321 },
  },
];

export type AuditState = "content" | "empty" | "error";

export function syntheticApiResponse(
  url: URL,
  method: string,
  state: AuditState = "content",
): { status?: number; json: unknown } | null {
  const path = url.pathname;
  if (path === "/api/health") return { json: { status: "ok", version: "0.7.0-synthetic" } };

  if (state === "error" && path === "/api/months") {
    return {
      status: 503,
      json: {
        error: {
          code: "synthetic_unavailable",
          message: "Синтетическая ошибка загрузки для проверки состояния интерфейса.",
          details: [],
        },
      },
    };
  }

  if (path === "/api/months" && method === "GET") {
    return { json: state === "empty" ? [] : syntheticMonths };
  }
  if (/^\/api\/months\/\d+$/.test(path) && method === "GET") return { json: syntheticMonths[0] };
  if (/^\/api\/months\/\d+\/dashboard$/.test(path)) return { json: dashboard };
  if (/^\/api\/months\/\d+\/summary$/.test(path)) return { json: monthSummary };
  if (/^\/api\/months\/\d+\/freshness-provenance$/.test(path)) return { json: freshness };
  if (/^\/api\/months\/\d+\/broker-reconciliation-preview$/.test(path)) {
    return { json: reconciliation };
  }
  if (path === "/api/analytics/capital-composition") return { json: capitalComposition };
  if (path === "/api/analytics/risk-allocation") return { json: riskAllocation };
  if (path === "/api/performance/xirr" && method === "GET") return { json: portfolioXirr };
  if (path === "/api/performance/twrr" && method === "GET") return { json: portfolioTwrr };
  if (path === "/api/accounts" && method === "GET") {
    return { json: state === "empty" ? [] : syntheticAccounts };
  }
  if (path === "/api/instruments" && method === "GET") {
    return { json: state === "empty" ? [] : syntheticInstruments };
  }
  if (path === "/api/broker-identity-mappings" && method === "GET") {
    return { json: [] };
  }
  if (/^\/api\/instruments\/\d+\/market-mapping$/.test(path)) {
    const instrumentId = Number(path.split("/")[3]);
    return {
      json: {
        instrument_id: instrumentId,
        state: "mapped",
        identity: {
          provider: "t_invest",
          provider_instrument_id: `SYNTHETIC-PROVIDER-ID-${instrumentId}-${"X".repeat(24)}`,
          provider_venue_id: null,
        },
        instrument_isin:
          syntheticInstruments.find((item) => item.id === instrumentId)?.isin ?? null,
        legacy_moex_secid: null,
      },
    };
  }
  if (path === "/api/incomes") return { json: state === "empty" ? [] : incomeRows };
  if (path === "/api/settings") return { json: settings };
  if (/^\/api\/tax-brackets\/\d+$/.test(path)) {
    const year = Number(path.split("/").at(-1));
    return {
      json: {
        year,
        effective_from: `${year}-01-01`,
        effective_to: `${year}-12-31`,
        source: "official_default",
        contract_version: "tax_brackets_year_v1",
        mutable: true,
        closed_months: [],
        brackets: [
          { threshold_from: rub("0.00"), threshold_to: rub("2400000.00"), rate_bps: 1300 },
          {
            threshold_from: rub("2400000.00"),
            threshold_to: rub("5000000.00"),
            rate_bps: 1500,
          },
        ],
      },
    };
  }
  if (/^\/api\/iis\/\d+\/profile$/.test(path)) {
    const accountId = Number(path.split("/")[3]);
    return {
      json: {
        id: accountId,
        account_id: accountId,
        iis_type: "type_a",
        opened_at: "2031-01-01",
        eligible_close_at: "2036-01-01",
        notes: null,
      },
    };
  }
  if (/^\/api\/iis\/\d+\/(contributions|benefits)$/.test(path)) return { json: [] };
  if (path === "/api/tax-iis-planner") return { json: taxPlanner };
  if (path === "/api/backups" && method === "GET") return { json: backups };
  if (path === "/api/goals/summary") return { json: [] };
  if (path === "/api/goals" && method === "GET") return { json: [] };
  if (path === "/api/positions") return { json: [] };
  if (path === "/api/payouts/calendar") return { json: [] };
  if (/^\/api\/months\/\d+\/payout-refresh-status$/.test(path)) {
    return { json: { reporting_month_id: syntheticMonths[0].id, positions_changed: 0, items: [] } };
  }
  if (
    path === "/api/deposits" ||
    path === "/api/cash-balances" ||
    path === "/api/expenses" ||
    path === "/api/savings" ||
    path === "/api/debts" ||
    path === "/api/properties" ||
    path === "/api/comments" ||
    path === "/api/investment-flows" ||
    path === "/api/expected-flows"
  ) {
    return { json: [] };
  }
  return null;
}
