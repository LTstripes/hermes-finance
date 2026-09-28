import { beforeEach, describe, expect, it, vi } from "vitest";

import { getCloseReadiness, getMonth } from "../api/months";
import { listInvestmentFlows } from "../api/investmentFlows";
import type { CloseReadiness, InvestmentFlow, ReportingMonth } from "../api/types";
import type { StatementApplyVerification } from "../components/StatementImportPanel";
import { confirmStatementApply } from "./UiV2StatementImportSection";

vi.mock("../api/months", () => ({
  getMonth: vi.fn(),
  getCloseReadiness: vi.fn(),
}));
vi.mock("../api/investmentFlows", () => ({
  listInvestmentFlows: vi.fn(),
}));

const month = {
  id: 7,
  year: 2026,
  month: 8,
  status: "draft",
  snapshot_date: "2026-08-31",
  source: "manual",
} as ReportingMonth;

const readiness = {
  year: 2026,
  month: 8,
  status: "draft",
  snapshot_date: "2026-08-31",
  source: "manual",
  can_close: false,
  items: [],
} as CloseReadiness;

function flow(id: number, overrides: Partial<InvestmentFlow> = {}): InvestmentFlow {
  return {
    id,
    reporting_month_id: 7,
    account_id: 1,
    instrument_id: 10,
    flow_type: "coupon",
    event_date: "2026-08-03",
    gross_amount: { amount: "12450.00", currency: "RUB" },
    tax_amount: { amount: "1618.50", currency: "RUB" },
    commission_amount: { amount: "0.00", currency: "RUB" },
    net_amount: { amount: "10831.50", currency: "RUB" },
    currency: "RUB",
    source: "alfa_pdf",
    notes: null,
    statement_link: null,
    ...overrides,
  };
}

function item(naturalIdentity: string, flowId: number) {
  return {
    action: "created",
    natural_identity: naturalIdentity,
    applied_statement_event_id: 100 + flowId,
    investment_cash_flow_id: flowId,
    material_fingerprint: `fp-${flowId}`,
    revision_id: 1,
  };
}

function expectation(naturalIdentity: string, accountId = 1, instrumentId = 10) {
  return {
    natural_identity: naturalIdentity,
    expected_hermes_account_id: accountId,
    expected_hermes_instrument_id: instrumentId,
  };
}

function verification(
  overrides: Partial<StatementApplyVerification> = {},
): StatementApplyVerification {
  return {
    submittedCount: 2,
    selectedCount: 2,
    items: [item("row-1", 501), item("row-2", 502)],
    expectations: [expectation("row-1"), expectation("row-2")],
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getMonth).mockResolvedValue(month);
  vi.mocked(getCloseReadiness).mockResolvedValue(readiness);
  vi.mocked(listInvestmentFlows).mockResolvedValue([flow(501), flow(502)]);
});

describe("confirmStatementApply authoritative readback", () => {
  it("proves every applied flow id, identity and readiness for the exact month", async () => {
    await expect(confirmStatementApply(7, verification())).resolves.toBeUndefined();
    expect(getMonth).toHaveBeenCalledTimes(1);
    expect(getMonth).toHaveBeenCalledWith(7);
    expect(listInvestmentFlows).toHaveBeenCalledWith(7);
    expect(getCloseReadiness).toHaveBeenCalledWith(7);
  });

  it("rejects a submitted set that the server did not confirm entirely", async () => {
    await expect(confirmStatementApply(7, verification({ selectedCount: 1 }))).rejects.toThrow(
      /не весь отправленный набор/,
    );
    await expect(confirmStatementApply(7, verification({ submittedCount: 3 }))).rejects.toThrow(
      /не весь отправленный набор/,
    );
    expect(getMonth).not.toHaveBeenCalled();
    expect(listInvestmentFlows).not.toHaveBeenCalled();
  });

  it("rejects a reread month other than the explicit one", async () => {
    vi.mocked(getMonth).mockResolvedValue({ ...month, id: 8 });
    await expect(confirmStatementApply(7, verification())).rejects.toThrow(/другой отчётный месяц/);
  });

  it("rejects an applied flow id that is absent from the exact-month reread", async () => {
    vi.mocked(listInvestmentFlows).mockResolvedValue([flow(501)]);
    await expect(confirmStatementApply(7, verification())).rejects.toThrow(
      /не найдена в повторно загруженном месяце/,
    );
  });

  it("rejects a foreign-month flow returned for the explicit month", async () => {
    vi.mocked(listInvestmentFlows).mockResolvedValue([
      flow(501),
      flow(502, { reporting_month_id: 6 }),
    ]);
    await expect(confirmStatementApply(7, verification())).rejects.toThrow(/запись другого месяца/);
  });

  it("rejects an applied flow saved for another account", async () => {
    vi.mocked(listInvestmentFlows).mockResolvedValue([flow(501, { account_id: 3 }), flow(502)]);
    await expect(confirmStatementApply(7, verification())).rejects.toThrow(
      /не совпала с ожидаемыми счётом и инструментом/,
    );
  });

  it("rejects an applied flow saved for another instrument", async () => {
    vi.mocked(listInvestmentFlows).mockResolvedValue([flow(501), flow(502, { instrument_id: 11 })]);
    await expect(confirmStatementApply(7, verification())).rejects.toThrow(
      /не совпала с ожидаемыми счётом и инструментом/,
    );
  });

  it("rejects an apply result that does not correlate with the submitted rows", async () => {
    await expect(
      confirmStatementApply(7, verification({ items: [item("row-x", 501), item("row-2", 502)] })),
    ).rejects.toThrow(/не сопоставляется с отправленными строками/);
  });

  it("rejects a readiness lifecycle that disagrees with the reread month", async () => {
    vi.mocked(getCloseReadiness).mockResolvedValue({
      ...readiness,
      snapshot_date: "2026-08-30",
    });
    await expect(confirmStatementApply(7, verification())).rejects.toThrow(
      /готовность к закрытию не совпала/,
    );

    vi.mocked(getCloseReadiness).mockResolvedValue({
      ...readiness,
      status: "closed",
    });
    await expect(confirmStatementApply(7, verification())).rejects.toThrow(
      /готовность к закрытию не совпала/,
    );
  });

  it("does not accept a zero-row confirmation for a submitted set", async () => {
    await expect(
      confirmStatementApply(7, verification({ items: [], selectedCount: 0 })),
    ).rejects.toThrow(/не весь отправленный набор/);
  });
});
