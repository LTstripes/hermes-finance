import { beforeEach, expect, it, vi } from "vitest";
import { apiRequest } from "./client";
import { getInvestmentReports } from "./sourceReportPreview";

vi.mock("./client", () => ({ apiRequest: vi.fn(), apiMultipart: vi.fn() }));
beforeEach(() => vi.resetAllMocks());

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
