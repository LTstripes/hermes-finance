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
};
