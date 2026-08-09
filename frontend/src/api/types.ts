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

export type HealthResponse = {
  status: "ok";
  version: string;
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
  forecast_monthly_passive_income: MoneyValue;
  passive_income_average: MoneyValue;
  passive_income_average_months: number;
  passive_income_average_complete: boolean;
  goal_progress_pct: string | null;
  goal_target: MoneyValue;
  mandatory_expenses: MoneyValue;
  mandatory_expense_coverage_pct: string | null;
  mortgage_balance: MoneyValue;
  mortgage_coverage_pct: string | null;
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
  mortgage: DashboardMortgage;
  historical_series?: CapitalHistoryPoint[];
  asset_allocation?: AssetAllocationPoint[];
  result_by_account?: AccountResultPoint[];
  result_by_instrument_class?: InstrumentClassResultPoint[];
  warnings?: string[];
  calculation_version?: string;
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

export type SavingAllocation = {
  id: number;
  reporting_month_id: number;
  destination: string;
  amount: MoneyValue;
  notes: string | null;
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

export type PropertySnapshot = {
  id: number;
  reporting_month_id: number;
  name: string;
  estimated_value: MoneyValue;
  mortgage_balance: MoneyValue;
  monthly_payment: MoneyValue;
  notes: string | null;
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
