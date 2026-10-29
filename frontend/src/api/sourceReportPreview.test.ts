import { beforeEach, expect, it, vi } from "vitest";
import { apiRequest } from "./client";
import { getInvestmentReports } from "./sourceReportPreview";

vi.mock("./client", () => ({ apiRequest: vi.fn(), apiMultipart: vi.fn() }));
beforeEach(() => vi.resetAllMocks());

const metric = (value: string | null) => ({ value, status: "provisional", reason_codes: [] });
function current() {
  return {
    proof_id: 1,
    source_account: "synthetic",
    covered_from: "2030-01-01",
    covered_to: "2030-01-31",
    pdf_period: { covered_from: "2030-01-01", covered_to: "2030-01-31" },
    pdf_payout_rows: 0,
    status: "current",
    reason_codes: [],
    financial_authority: "none",
    interval: {
      source_account: "synthetic",
      source_sha256: "a".repeat(64),
      opening_date: "2029-12-31",
      closing_date: "2030-01-31",
      period_kind: "monthly",
      history_from_zero: false,
      pnl: metric("0"),
      modified_dietz: metric(null),
      xirr_period: metric(null),
      xirr_annualized: metric(null),
      reason_codes: [],
      instruments: [],
      account_only: [],
      unallocated_payouts: [],
      reconciliation: {
        linked_payout_occurrences: 0,
        xml_payout_occurrences: 0,
        cash_delta_kopecks: "0",
        pdf_closing_delta_kopecks: "0",
        pdf_pnl_delta_kopecks: null,
      },
    },
  };
}
it.each([{}, [], null])(
  "rejects a current row with an incomplete interval: %j",
  async (interval) => {
    vi.mocked(apiRequest).mockResolvedValue({ reports: [{ ...current(), interval }] });
    await expect(getInvestmentReports()).rejects.toThrow(/числа скрыты/);
  },
);
it("rejects missing PDF metadata and malformed nested money without rendering numbers", async () => {
  const record = current();
  vi.mocked(apiRequest).mockResolvedValueOnce({ reports: [{ ...record, pdf_period: undefined }] });
  await expect(getInvestmentReports()).rejects.toThrow(/числа скрыты/);
  vi.mocked(apiRequest).mockResolvedValueOnce({
    reports: [
      {
        ...record,
        interval: {
          ...record.interval,
          account_only: [{ kind: "account_fee", amount_kopecks: "not-money" }],
        },
      },
    ],
  });
  await expect(getInvestmentReports()).rejects.toThrow(/числа скрыты/);
});
it("retains a complete current interval and keeps null rates distinct from zero money", async () => {
  const reports = [current()];
  vi.mocked(apiRequest).mockResolvedValue({ reports });
  await expect(getInvestmentReports()).resolves.toEqual({ reports });
});

it.each([
  null,
  [],
  {},
  { reports: null },
  { reports: [{}] },
  {
    reports: [
      {
        source_account: "synthetic",
        covered_from: "2030-01-01",
        covered_to: "2030-01-31",
        status: "current",
        interval: null,
        reason_codes: [],
        financial_authority: "none",
      },
    ],
  },
])(
  "withholds malformed saved evidence instead of treating it as an empty result: %j",
  async (value) => {
    vi.mocked(apiRequest).mockResolvedValue(value);
    await expect(getInvestmentReports()).rejects.toThrow(/числа скрыты/);
  },
);
it("preserves an explicitly empty saved-evidence response", async () => {
  vi.mocked(apiRequest).mockResolvedValue({ reports: [] });
  await expect(getInvestmentReports()).resolves.toEqual({ reports: [] });
});
