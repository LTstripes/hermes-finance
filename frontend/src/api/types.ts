/** Shared API types matching backend contracts. */

export type ApiErrorDetail = {
  field: string;
  message: string;
};

export type ApiErrorBody = {
  code: string;
  message: string;
  details: ApiErrorDetail[];
};

export type ApiErrorResponse = {
  error: ApiErrorBody;
};

export type MoneyValue = {
  amount: string;
  currency: string;
};

export type ReportingMonthStatus = "draft" | "closed";

export type ReportingMonthSource = "manual" | "excel_migration" | "alfa_pdf" | string;

export type ReportingMonth = {
  id: number;
  year: number;
  month: number;
  status: ReportingMonthStatus;
  snapshot_date: string;
  source: ReportingMonthSource;
};

export type ReportingMonthCreate = {
  year: number;
  month: number;
  snapshot_date: string;
  source?: ReportingMonthSource;
};

export type ReportingMonthClone = {
  year: number;
  month: number;
  snapshot_date: string;
};

export type ReportingMonthUpdate = {
  snapshot_date?: string;
  source?: ReportingMonthSource;
};

export type CloseReadinessSeverity = "hard_blocker" | "warning" | "info";

export type CloseReadinessItem = {
  severity: CloseReadinessSeverity;
  code: string;
  message: string;
  context: Record<string, unknown>;
};

export type CloseReadiness = {
  year: number;
  month: number;
  status: ReportingMonthStatus;
  snapshot_date: string | null;
  source: ReportingMonthSource;
  can_close: boolean;
  items: CloseReadinessItem[];
};

export type BackupSource = {
  name: string;
  size_bytes: number;
};

export type BackupMetadata = {
  id: string;
  name: string;
  created_at: string;
  size_bytes: number;
  source_database: BackupSource;
};

export type RestoreResponse = {
  restored_backup: BackupMetadata;
  pre_restore_backup: BackupMetadata;
};

export type HealthResponse = {
  status: "ok";
  version: string;
};

export type PortfolioXirr = {
  metric: "xirr";
  scope: "portfolio";
  performance_currency: string;
  value: string | null;
  value_unit: "percentage_points";
  annualized: true;
  period: {
    start_date: string;
    end_date: string;
  };
  availability: "available" | "not_computable";
  quality: "exact" | "unavailable";
  reason_codes: string[];
};

export type PortfolioTwrr = {
  metric: "twrr";
  scope: "portfolio";
  performance_currency: string;
  value: string | null;
  value_unit: "percentage_points";
  annualized: false;
  period: {
    start_date: string;
    end_date: string;
  };
  availability: "available" | "not_computable";
  quality: "exact" | "unavailable";
  reason_codes: string[];
};

export type IncomeType = "salary" | "bonus" | "side_income" | "cashback" | "other" | string;

export type IncomeEntry = {
  id: number;
  reporting_month_id: number;
  income_type: IncomeType;
  name: string;
  gross_amount: MoneyValue;
  tax_amount: MoneyValue;
  net_amount: MoneyValue;
  received_at: string | null;
  is_recurring: boolean;
  include_in_cash_flow: boolean;
  include_in_passive_income: boolean;
  notes: string | null;
};

export type IncomeCreate = {
  reporting_month_id: number;
  income_type: string;
  name: string;
  gross_amount: MoneyValue;
  tax_amount: MoneyValue;
  net_amount: MoneyValue;
  received_at?: string | null;
  is_recurring?: boolean;
  include_in_cash_flow?: boolean;
  include_in_passive_income?: boolean;
  notes?: string | null;
};

export type IncomeUpdate = {
  income_type?: string;
  name?: string;
  gross_amount?: MoneyValue;
  tax_amount?: MoneyValue;
  net_amount?: MoneyValue;
  received_at?: string | null;
  is_recurring?: boolean;
  include_in_cash_flow?: boolean;
  include_in_passive_income?: boolean;
  notes?: string | null;
};

/** Minimal summary slice used by E04 salary editor. */
export type SalaryTaxSummary = {
  tax: MoneyValue;
  calculated_net: MoneyValue;
};

export type MonthSummary = {
  month: {
    id: number;
    year: number;
    month: number;
    status: string;
    snapshot_date: string;
    source: string;
  };
  salary_tax: SalaryTaxSummary;
  salary_actual_net: MoneyValue;
  coverage?: {
    mandatory_expenses: MoneyValue;
    coverage_pct: string | null;
    goal_target?: MoneyValue;
    goal_progress_pct?: string | null;
    warnings?: string[];
  };
};

export type DashboardMortgage = {
  mortgage_balance: MoneyValue;
  coverage_pct: string | null;
  gap: MoneyValue;
};

export type DashboardKpis = {
  liquid_capital_net: MoneyValue;
  liquid_capital_delta: MoneyValue | null;
  passive_income_actual: MoneyValue;
  passive_income_delta: MoneyValue | null;
  forecast_monthly_passive_income: MoneyValue;
  forecast_annual_passive_income: MoneyValue;
  passive_income_average: MoneyValue;
  passive_income_average_months: number;
  passive_income_average_complete: boolean;
  passive_income_history_start_month?: string | null;
  passive_income_average_months_used?: string[];
  goal_progress_pct: string | null;
  goal_target: MoneyValue;
  mandatory_expenses: MoneyValue;
  mandatory_expense_coverage_pct: string | null;
  actual_mandatory_expense_coverage_pct: string | null;
  mortgage_balance: MoneyValue;
  mortgage_coverage_pct: string | null;
};

export type DashboardForecast = {
  breakdown: {
    expected_deposit_interest: MoneyValue;
    expected_coupon_net: MoneyValue;
    expected_dividend_component: MoneyValue;
    other_expected_capital_income: MoneyValue;
  };
  is_approximate: boolean;
  warnings: string[];
};

export type CashFlowLadderEvent = {
  source_kind: "manual" | "provider" | "deposit_forecast" | string;
  source_id: number;
  expected_date: string;
  flow_type: string;
  component:
    | "coupon"
    | "dividend"
    | "deposit_interest"
    | "other_capital_income"
    | "redemption_principal"
    | string;
  account_id: number;
  account_name: string;
  instrument_id: number | null;
  instrument_name: string | null;
  expected_net_amount: MoneyValue;
  is_approximate: boolean;
  source: string;
  provider: string | null;
  provider_instrument_uid: string | null;
  provider_identity_key: string | null;
  reconciliation_id: number | null;
  counting_decision: string | null;
  linked_manual_id: number | null;
  linked_provider_payout_id: number | null;
  source_as_of_date: string | null;
};

export type CashFlowLadderMonth = {
  year: number;
  month: number;
  coupon: MoneyValue;
  dividend: MoneyValue;
  deposit_interest: MoneyValue;
  other_capital_income: MoneyValue;
  redemption_principal: MoneyValue;
  passive_income: MoneyValue;
  total_cash_flow: MoneyValue;
  is_approximate: boolean;
  items: CashFlowLadderEvent[];
};

export type UpcomingEventsWindow = {
  days: number;
  from_date: string;
  to_date: string;
  passive_income: MoneyValue;
  redemption_principal: MoneyValue;
  total_cash_flow: MoneyValue;
  items: CashFlowLadderEvent[];
};

export type CashFlowLadder = {
  as_of_date: string;
  forecast_version: string;
  months: CashFlowLadderMonth[];
  upcoming_14_days: UpcomingEventsWindow;
  upcoming_30_days: UpcomingEventsWindow;
  warnings: string[];
};

export type DashboardMonthRef = {
  id: number;
  year: number;
  month: number;
  status: string;
  snapshot_date: string;
  source: string;
};

/** One point of the closed-month capital history (D07 historical_series). */
export type CapitalHistoryPoint = {
  year: number;
  month: number;
  reporting_month_id: number;
  liquid_capital_net: MoneyValue;
  passive_income_actual: MoneyValue;
};

/** One liquid-asset class slice (E14 allocation: cash/deposits/stocks/bonds/gold_other). */
export type AssetAllocationPoint = {
  asset_class: string;
  amount: MoneyValue;
};

/** One closed-month point from the read-only Analytics capital-composition API. */
export type CapitalCompositionPoint = {
  reporting_month_id: number;
  year: number;
  month: number;
  snapshot_date: string;
  allocation: AssetAllocationPoint[];
  liquid_assets_total: MoneyValue;
  included_debts: MoneyValue;
  liquid_capital_net: MoneyValue;
};

export type CapitalCompositionHistory = {
  asset_classes: string[];
  points: CapitalCompositionPoint[];
};

/** Monetary result per account (E15): realized cash income + unrealized result. */
export type AccountResultPoint = {
  account_id: number;
  account_name: string;
  account_type: string;
  cash_income: MoneyValue;
  unrealized_result: MoneyValue;
};

/** Monetary result per instrument class (E15). */
export type InstrumentClassResultPoint = {
  instrument_type: string;
  market_value: MoneyValue;
  cost_basis: MoneyValue;
  unrealized_result: MoneyValue;
  realized_result: MoneyValue;
};

export type DashboardSlice = {
  month?: DashboardMonthRef;
  kpis?: DashboardKpis;
  summary?: {
    forecast: DashboardForecast;
  };
  mortgage: DashboardMortgage;
  historical_series?: CapitalHistoryPoint[];
  asset_allocation?: AssetAllocationPoint[];
  result_by_account?: AccountResultPoint[];
  result_by_instrument_class?: InstrumentClassResultPoint[];
  warnings?: string[];
  calculation_version?: string;
  cash_flow_ladder?: CashFlowLadder | null;
};

export type Account = {
  id: number;
  name: string;
  account_type: string;
  status: string;
  external_code: string | null;
  include_in_capital: boolean;
  include_in_returns: boolean;
  notes: string | null;
};

export type DepositSnapshot = {
  id: number;
  reporting_month_id: number;
  account_id: number;
  name: string;
  deposit_type: "deposit" | "savings" | string;
  balance: MoneyValue;
  annual_rate: string;
  expected_monthly_interest: MoneyValue;
  actual_interest_received: MoneyValue;
  notes: string | null;
  updated_at: string;
};

export type DepositCreate = {
  reporting_month_id: number;
  account_id: number;
  name: string;
  deposit_type: string;
  balance: MoneyValue;
  annual_rate: string;
  actual_interest_received?: MoneyValue;
  notes?: string | null;
};

export type DepositUpdate = {
  name?: string;
  deposit_type?: string;
  balance?: MoneyValue;
  annual_rate?: string;
  actual_interest_received?: MoneyValue;
  notes?: string | null;
};

export type CashBalance = {
  id: number;
  reporting_month_id: number;
  name: string;
  amount: MoneyValue;
  currency: string;
  include_in_capital: boolean;
  notes: string | null;
};

export type CashBalanceCreate = {
  reporting_month_id: number;
  name: string;
  amount: MoneyValue;
  currency?: string;
  include_in_capital?: boolean;
  notes?: string | null;
};

export type CashBalanceUpdate = {
  name?: string;
  amount?: MoneyValue;
  currency?: string;
  include_in_capital?: boolean;
  notes?: string | null;
};

export type CashTotal = {
  reporting_month_id: number;
  total: MoneyValue;
  total_in_capital: MoneyValue;
};

export type Instrument = {
  id: number;
  name: string;
  instrument_type: string;
  isin: string | null;
  ticker: string | null;
  moex_secid: string | null;
  currency: string;
  nominal_value: MoneyValue | null;
  is_active: boolean;
  manual_price_allowed: boolean;
  notes: string | null;
};

export type InstrumentCreate = {
  name: string;
  instrument_type: string;
  isin?: string | null;
  ticker?: string | null;
  currency?: string;
  is_active?: boolean;
  manual_price_allowed?: boolean;
};

export type MarketMappingState = "unmapped" | "mapped" | "excluded";

export type MarketIdentity = {
  provider: string;
  provider_instrument_id: string;
  provider_venue_id: string | null;
};

export type MarketIdentityWrite = {
  provider: string;
  provider_instrument_id: string;
  provider_venue_id: string | null;
  isin?: string | null;
};

export type InstrumentMarketMapping = {
  instrument_id: number;
  state: MarketMappingState;
  identity: MarketIdentity | null;
  instrument_isin: string | null;
  legacy_moex_secid: string | null;
};

export type MarketDiscoverCandidate = {
  provider: string;
  provider_instrument_id: string;
  provider_venue_id: string | null;
  instrument_kind: string;
  isin: string | null;
  name?: string | null;
  ticker?: string | null;
  class_code?: string | null;
  exchange?: string | null;
  api_trade_available?: boolean | null;
  position_uid?: string | null;
};

export type MarketDiscoverRejected = {
  provider_instrument_id: string;
  candidate_isin: string;
  expected_isin: string;
  reason: string;
};

export type MarketDiscoverResult = {
  status: QuotePreviewStatus;
  message: string | null;
  candidates: MarketDiscoverCandidate[];
  rejected: MarketDiscoverRejected[];
};

export type QuotePreviewStatus =
  | "ok"
  | "stale"
  | "unmapped"
  | "excluded"
  | "unsupported"
  | "ambiguous"
  | "unavailable"
  | "network_error"
  | "malformed_response";

export type QuoteFailureReason =
  | "token_unavailable"
  | "provider_network"
  | "quote_unavailable"
  | "unsupported"
  | "malformed"
  | "unmapped"
  | "excluded"
  | "ambiguous";

export type QuotePreviewRow = {
  position_snapshot_id: number;
  account_id: number;
  instrument_id: number;
  instrument_name: string;
  instrument_type: string;
  mapping_state: MarketMappingState;
  identity: MarketIdentity | null;
  current_market_price_per_unit: MoneyValue;
  current_price_date: string;
  current_price_source: string;
  proposed_market_price_per_unit: MoneyValue | null;
  proposed_price_date: string | null;
  proposed_quote_kind: "last" | "history" | null;
  proposed_raw_price: string | null;
  proposed_raw_price_basis: "R" | "F" | null;
  fetched_at_utc: string | null;
  freshness_status: QuotePreviewStatus | null;
  status: QuotePreviewStatus;
  failure_reason: QuoteFailureReason | null;
  message: string | null;
  apply_allowed: boolean;
};

export type QuotePreview = {
  reporting_month_id: number;
  month_status: ReportingMonthStatus;
  target_date: string;
  month_editable: boolean;
  batch_error: string | null;
  batch_error_reason: QuoteFailureReason | null;
  rows: QuotePreviewRow[];
};

export type QuoteApplyRowRequest = {
  position_snapshot_id: number;
  accept_stale: boolean;
  expected_market_price_per_unit: MoneyValue;
  expected_price_date: string;
  expected_identity: MarketIdentity;
  expected_quote_kind: "last" | "history" | null;
};

export type QuoteApplyResult = {
  reporting_month_id: number;
  applied_count: number;
  rows: Array<{
    position_snapshot_id: number;
    market_price_per_unit: MoneyValue;
    market_value: MoneyValue;
    unrealized_result: MoneyValue;
    accrued_interest: MoneyValue | null;
    price_date: string;
    price_source: string;
    freshness: string;
  }>;
};

export type PositionSnapshot = {
  id: number;
  reporting_month_id: number;
  account_id: number;
  instrument_id: number;
  quantity: string;
  average_cost_per_unit: MoneyValue;
  market_price_per_unit: MoneyValue;
  market_value: MoneyValue;
  cost_basis: MoneyValue;
  unrealized_result: MoneyValue;
  accrued_interest: MoneyValue | null;
  price_source: string;
  price_date: string;
  notes: string | null;
  updated_at: string;
};

export type PositionCreate = {
  reporting_month_id: number;
  account_id: number;
  instrument_id: number;
  quantity: string;
  average_cost_per_unit: MoneyValue;
  market_price_per_unit: MoneyValue;
  accrued_interest?: MoneyValue | null;
  price_source?: string;
  price_date: string;
  notes?: string | null;
};

export type PositionUpdate = {
  quantity?: string;
  average_cost_per_unit?: MoneyValue;
  market_price_per_unit?: MoneyValue;
  accrued_interest?: MoneyValue | null;
  price_source?: string;
  price_date?: string;
  notes?: string | null;
};

export type StatementLink = {
  applied_statement_event_id: number;
  link_mode: "statement_created" | "linked_existing";
  status: "active" | "retracted";
};

export type InvestmentFlow = {
  id: number;
  reporting_month_id: number;
  account_id: number;
  instrument_id: number | null;
  flow_type: string;
  event_date: string;
  gross_amount: MoneyValue;
  tax_amount: MoneyValue;
  commission_amount: MoneyValue;
  net_amount: MoneyValue;
  currency: string;
  source: string;
  notes: string | null;
  statement_link?: StatementLink | null;
};

export type InvestmentFlowCreate = {
  reporting_month_id: number;
  account_id: number;
  flow_type: string;
  event_date: string;
  gross_amount: MoneyValue;
  tax_amount?: MoneyValue;
  commission_amount?: MoneyValue;
  net_amount: MoneyValue;
  instrument_id?: number | null;
  currency?: string;
  source: string;
  notes?: string | null;
};

export type InvestmentFlowUpdate = {
  flow_type?: string;
  event_date?: string;
  gross_amount?: MoneyValue;
  tax_amount?: MoneyValue;
  commission_amount?: MoneyValue;
  net_amount?: MoneyValue;
  instrument_id?: number | null;
  currency?: string;
  source?: string;
  notes?: string | null;
};

export type ExpectedFlow = {
  id: number;
  reporting_month_id: number;
  account_id: number;
  instrument_id: number;
  flow_type: string;
  expected_date: string;
  gross_amount: MoneyValue;
  expected_tax_amount: MoneyValue | null;
  expected_net_amount: MoneyValue;
  currency: string;
  source: string;
  source_as_of_date: string;
  forecast_version: string;
  is_confirmed: boolean;
  is_approximate: boolean;
  notes: string | null;
};

/** One expected payout inside a calendar month (E16). */
export type ExpectedCalendarItem = {
  id: number;
  expected_date: string;
  flow_type: string;
  account_name: string;
  instrument_name: string | null;
  expected_net_amount: MoneyValue;
  is_confirmed: boolean;
  is_approximate: boolean;
  source: string;
};

/** Aggregated expected payouts for one calendar month (E16). */
export type ExpectedCalendarMonth = {
  year: number;
  month: number;
  coupon: MoneyValue;
  dividend: MoneyValue;
  interest: MoneyValue;
  redemption: MoneyValue;
  other: MoneyValue;
  passive_net: MoneyValue;
  total_net: MoneyValue;
  items: ExpectedCalendarItem[];
};

export type ExpectedFlowCreate = {
  reporting_month_id: number;
  account_id: number;
  instrument_id: number;
  flow_type: string;
  expected_date: string;
  gross_amount: MoneyValue;
  expected_tax_amount?: MoneyValue | null;
  expected_net_amount?: MoneyValue | null;
  currency?: string;
  source: string;
  source_as_of_date: string;
  forecast_version: string;
  is_confirmed?: boolean;
  notes?: string | null;
};

export type ExpenseEntry = {
  id: number;
  reporting_month_id: number;
  category: string;
  amount: MoneyValue;
  expense_type: string;
  is_recurring: boolean;
  notes: string | null;
};

export type ExpenseUpdate = {
  category?: string;
  amount?: MoneyValue;
  expense_type?: string;
  is_recurring?: boolean;
  notes?: string | null;
};

export type SavingAllocation = {
  id: number;
  reporting_month_id: number;
  destination: string;
  amount: MoneyValue;
  notes: string | null;
};

export type SavingUpdate = {
  destination?: string;
  amount?: MoneyValue;
  notes?: string | null;
};

export type DebtEntry = {
  id: number;
  reporting_month_id: number;
  debt_type: string;
  name: string;
  current_balance: MoneyValue;
  include_in_liquid_capital: boolean;
  notes: string | null;
};

export type DebtUpdate = {
  debt_type?: string;
  name?: string;
  current_balance?: MoneyValue;
  include_in_liquid_capital?: boolean;
  notes?: string | null;
};

export type PropertySnapshot = {
  id: number;
  reporting_month_id: number;
  name: string;
  estimated_value: MoneyValue;
  mortgage_balance: MoneyValue;
  monthly_payment: MoneyValue;
  notes: string | null;
};

export type PropertyUpdate = {
  name?: string;
  estimated_value?: MoneyValue;
  mortgage_balance?: MoneyValue;
  monthly_payment?: MoneyValue;
  notes?: string | null;
};

export type MonthlyComment = {
  id: number;
  reporting_month_id: number;
  position: number;
  text: string;
};

export type IisProfile = {
  id: number;
  account_id: number;
  iis_type: string;
  opened_at: string;
  eligible_close_at: string | null;
  notes: string | null;
};

export type IisContribution = {
  id: number;
  account_id: number;
  tax_year: number;
  amount: MoneyValue;
  is_target_reached: boolean;
  notes: string | null;
};

export type TaxBenefit = {
  id: number;
  account_id: number;
  tax_year: number;
  benefit_type: string;
  status: string;
  amount: MoneyValue;
  received_at: string | null;
  notes: string | null;
};

export type TaxIisPlannerBracket = {
  threshold_from: MoneyValue;
  threshold_to: MoneyValue | null;
  rate_bps: number;
};

export type TaxIisPlannerSalaryTax = {
  tax_year: number | null;
  history_complete: boolean;
  history_coverage: "complete" | "unavailable";
  available: boolean;
  opening_context_available: boolean;
  taxable_gross_ytd: MoneyValue | null;
  current_marginal_bracket: TaxIisPlannerBracket | null;
  current_marginal_rate_bps: number | null;
  next_threshold: MoneyValue | null;
  distance_to_next_threshold: MoneyValue | null;
  tax_bracket_source: string | null;
  warning_codes: string[];
};

export type TaxIisPlannerContribution = {
  tax_year: number;
  amount: MoneyValue;
  is_target_reached: boolean;
};

export type TaxIisPlannerBenefitTotals = {
  planned: MoneyValue;
  submitted: MoneyValue;
  received: MoneyValue;
  rejected: MoneyValue;
};

export type TaxIisPlannerAccount = {
  account_id: number;
  account_name: string;
  iis_type: string;
  opened_at: string;
  eligible_close_at: string | null;
  contributions_by_tax_year: TaxIisPlannerContribution[];
  tax_benefits: TaxIisPlannerBenefitTotals;
};

export type TaxIisPlanner = {
  contract_version: string;
  tax_year: number | null;
  as_of: {
    reporting_month: ReportingMonth | null;
    selection_reason: string;
  };
  salary_tax: TaxIisPlannerSalaryTax;
  iis_accounts: TaxIisPlannerAccount[];
  warnings: string[];
};

export type FreshnessStatus =
  | "current"
  | "stale"
  | "mixed"
  | "unavailable"
  | "unknown"
  | "not_applicable"
  | "missing";

export type FreshnessReason = {
  code: string;
  severity: "info" | "warning" | string;
  message: string;
};

export type FreshnessCoverage = {
  row_count: number;
  current_count: number;
  stale_count: number;
  unavailable_count: number;
  unknown_count: number;
  missing_count: number;
  manual_count: number;
  provider_count: number;
};

export type FreshnessItem = {
  item_kind: string;
  label: string;
  freshness_status: FreshnessStatus;
  source_kind: string;
  source_timestamp_kind: string;
  source_date: string | null;
  source_datetime: string | null;
  fetched_at: string | null;
  import_apply_time: string | null;
  local_edit_time: string | null;
  reason_codes: string[];
  account_name: string | null;
  instrument_name: string | null;
};

export type FreshnessFamily = {
  family_id: string;
  title: string;
  status: FreshnessStatus;
  providers: string[];
  coverage: FreshnessCoverage;
  reasons: FreshnessReason[];
  items: FreshnessItem[];
};

export type FreshnessProvenanceSummary = {
  reporting_month: ReportingMonth;
  evaluated_on: string;
  quote_valuation_target_date: string;
  generated_at: string;
  families: FreshnessFamily[];
  reasons: FreshnessReason[];
  providers: string[];
};
