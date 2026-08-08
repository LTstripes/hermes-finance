/** Shared API types matching backend D08 error contract and D01 months. */

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

export type ReportingMonthStatus = "draft" | "closed";

export type ReportingMonthSource = "manual" | "excel_migration" | "alfa_pdf" | string;

export type ReportingMonth = {
  id: number;
  year: number;
  month: number;
  status: ReportingMonthStatus;
  snapshot_date: string; // ISO YYYY-MM-DD
  source: ReportingMonthSource;
};

export type ReportingMonthCreate = {
  year: number;
  month: number;
  snapshot_date: string;
  source?: ReportingMonthSource;
};

export type HealthResponse = {
  status: "ok";
  version: string;
};
