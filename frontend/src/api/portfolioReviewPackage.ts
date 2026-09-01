import { apiDownload, apiRequest, type ApiDownload } from "./client";

export type PortfolioReviewProfile = "concise" | "full";
export type PortfolioReviewSectionStatus = "included" | "partial" | "unavailable" | "omitted";
export type PortfolioReviewSectionId =
  | "capital"
  | "positions"
  | "dynamics"
  | "passive_income"
  | "future_cash_flows"
  | "freshness"
  | "allocation"
  | "context"
  | "deterministic_insights";

export type PortfolioReviewSection = {
  status: PortfolioReviewSectionStatus;
  reason_codes: string[];
  data: Record<string, unknown> | null;
};

export type PortfolioReviewPackage = {
  schema_name: "hermes.finance.portfolio_review_package";
  schema_version: "1.0.0";
  metadata: {
    generated_at: string;
    as_of_date: string;
    base_currency: "RUB";
    application: { name: "Hermes Finance"; version: string | null };
    generation_mode: "read_only";
    source_contract_name: "hermes.finance.ai_analysis_bundle";
    source_contract_version: "1.0.0";
    calculation_versions: Record<string, string>;
    ordering_contract: string;
  };
  profile: PortfolioReviewProfile;
  scope: {
    reporting_period: { year: number; month: number };
    reporting_status: "closed" | "draft";
    selection_reason: "latest_closed" | "latest_available";
    history_start_period: { year: number; month: number };
    history_end_period: { year: number; month: number };
    missing_calendar_periods: Array<{ year: number; month: number }>;
    requested_sections: PortfolioReviewSectionId[];
  };
  sections: Record<PortfolioReviewSectionId, PortfolioReviewSection>;
  field_states: Array<{
    path: string;
    status: "available" | "unavailable" | "omitted";
    reason_codes: string[];
    message: string;
  }>;
  warnings: Array<{
    code: string;
    severity: "info" | "warning" | "error";
    scope: string;
    message: string;
  }>;
};

function packagePath(profile: PortfolioReviewProfile): string {
  return `?profile=${encodeURIComponent(profile)}`;
}

export function getPortfolioReviewPackage(
  profile: PortfolioReviewProfile,
  signal?: AbortSignal,
): Promise<PortfolioReviewPackage> {
  return apiRequest<PortfolioReviewPackage>(
    `/api/export/portfolio-review-package${packagePath(profile)}`,
    {
      method: "GET",
      signal,
    },
  );
}

export function downloadPortfolioReviewPackage(
  profile: PortfolioReviewProfile,
  format: "json" | "markdown",
  signal?: AbortSignal,
): Promise<ApiDownload> {
  return apiDownload(`/api/export/portfolio-review-package/${format}${packagePath(profile)}`, {
    method: "GET",
    signal,
  });
}
