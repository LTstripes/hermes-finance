import { QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiClientError } from "../api/client";
import { getPerformanceReadiness } from "../api/performance";
import { getPreparation, type Preparation, savePreparation } from "../api/performancePreparation";
import type { Account, PerformanceReadiness } from "../api/types";
import { createQueryClient } from "../queryClient";
import { PerformancePreparation } from "./PerformancePreparation";

vi.mock("../api/performancePreparation", () => ({
  getPreparation: vi.fn(),
  savePreparation: vi.fn(),
}));
vi.mock("../api/performance", () => ({ getPerformanceReadiness: vi.fn() }));

const context = {
  start: "2030-05-01",
  end: "2030-05-31",
  scope: "account" as const,
  accountId: 1,
  view: "accounts" as const,
};
let data: Preparation;
const metric = (kind: "xirr" | "twrr") => ({
  metric: kind,
  scope: "account",
  account_id: 1,
  performance_currency: "RUB",
  value: null,
  value_unit: "percentage_points",
  annualized: kind === "xirr",
  availability: "not_computable",
  quality: "not_computable",
  reason_codes: [],
  period: { start_date: context.start, end_date: context.end },
});

beforeEach(() => {
  vi.resetAllMocks();
  data = {
    account_id: 1,
    start_date: context.start,
    end_date: context.end,
    evidence_token: "read-version",
    flows: [],
    transfer_links: [{ id: 9, status: "resolved", flow_ids: [8, 10] }],
    cash_coverages: [],
    in_kind_coverages: [],
    movements: [],
    cash_balances: [],
    months: [{ id: 4, period_start: context.start, period_end: context.end, status: "draft" }],
  };
  vi.mocked(getPreparation).mockImplementation(async () => structuredClone(data));
  vi.mocked(getPerformanceReadiness).mockResolvedValue({
    schema_version: 1,
    scope: "account",
    account_id: 1,
    start_date: context.start,
    end_date: context.end,
    performance_currency: "RUB",
    xirr: metric("xirr"),
    twrr: metric("twrr"),
  } as unknown as PerformanceReadiness);
});
afterEach(cleanup);

function setup(raw = "1") {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter
        initialEntries={[
          `/v2/capital/performance?start=${context.start}&end=${context.end}&scope=account&account_id=1&prepare_account=${raw}`,
        ]}
      >
        <PerformancePreparation
          accounts={[{ id: 1, name: "Synthetic" } as Account]}
          context={context}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Owner preparation", () => {
  it("requires independent explicit zero-crossing attestation and rereads both metrics", async () => {
    vi.mocked(savePreparation).mockImplementation(async (_path, _method, body) => {
      const saved = { id: 7, ...(body as object) };
      data.cash_coverages = [saved as Preparation["cash_coverages"][number]];
      data.evidence_token = "after";
      return saved;
    });
    setup();
    const button = await screen.findByRole("button", { name: "Сохранить: денежная история" });
    expect(button).toBeDisabled();
    fireEvent.click(
      screen.getAllByLabelText("История сверена полностью за весь указанный период")[0],
    );
    expect(button).toBeDisabled();
    fireEvent.click(screen.getByLabelText(/денежных пересечений.*не было/));
    fireEvent.click(button);
    fireEvent.click(button);
    await screen.findByText(/Запись подтверждена/);
    expect(savePreparation).toHaveBeenCalledTimes(1);
    expect(savePreparation).toHaveBeenCalledWith(
      "/api/cash-boundary-coverages",
      "POST",
      expect.objectContaining({
        account_id: 1,
        covered_from: context.start,
        covered_to: context.end,
        coverage_state: "complete",
      }),
      "read-version",
    );
    expect(getPerformanceReadiness).toHaveBeenCalledWith(
      context.start,
      context.end,
      "account",
      1,
      expect.any(AbortSignal),
    );
    expect(data.in_kind_coverages).toEqual([]);
    expect(screen.getByRole("button", { name: "Сохранить: неденежная история" })).toBeDisabled();
  });

  it("can explicitly leave history unknown without implicitly making it complete", async () => {
    vi.mocked(savePreparation).mockRejectedValue(
      new ApiClientError(409, { code: "conflict", message: "changed", details: [] }),
    );
    setup();
    await screen.findByRole("button", { name: "Сохранить: денежная история" });
    fireEvent.click(screen.getAllByLabelText(/история неполна или ещё не проверена/)[0]);
    fireEvent.click(screen.getByRole("button", { name: "Сохранить: денежная история" }));
    await screen.findByText(/Форма устарела/);
    expect(savePreparation).toHaveBeenCalledWith(
      expect.any(String),
      "POST",
      expect.objectContaining({ coverage_state: "unknown" }),
      "read-version",
    );
    expect(screen.getByRole("button", { name: "Сохранить: денежная история" })).toBeDisabled();
  });

  it("blocks coverage on CLOSED and does not call reopen", async () => {
    data.months[0].status = "closed";
    setup();
    const button = await screen.findByRole("button", { name: "Сохранить: денежная история" });
    expect(button).toBeDisabled();
    expect(savePreparation).not.toHaveBeenCalled();
  });

  it("rejects wrong-account responses and conflicting interval confirmations", async () => {
    data.account_id = 2;
    setup();
    await screen.findByText("Ответ не соответствует выбранному счёту и интервалу.");
    expect(screen.queryByRole("button", { name: "Добавить операцию" })).not.toBeInTheDocument();
  });

  it("keeps exact money as a string and unknown flow membership; rejects blind retry", async () => {
    vi.mocked(savePreparation).mockRejectedValue(
      new ApiClientError(0, { code: "network_error", message: "lost", details: [] }),
    );
    setup();
    fireEvent.click(await screen.findByRole("button", { name: "Добавить операцию" }));
    fireEvent.change(screen.getByLabelText("Отчёт операции"), { target: { value: "4" } });
    fireEvent.change(screen.getByLabelText("Дата операции"), { target: { value: "2030-05-12" } });
    fireEvent.change(screen.getByLabelText("Сумма операции"), {
      target: { value: "90071992547409.91" },
    });
    fireEvent.click(screen.getByLabelText(/Я проверил.*дату, счёт, сумму/));
    fireEvent.click(screen.getByRole("button", { name: "Сохранить операцию" }));
    await screen.findByText(/Не повторяйте запись вслепую/);
    expect(savePreparation).toHaveBeenCalledTimes(1);
    expect(savePreparation).toHaveBeenCalledWith(
      "/api/external-flows",
      "POST",
      expect.objectContaining({
        boundary_amount: { amount: "90071992547409.91", currency: "RUB" },
        scope_membership: "unknown",
      }),
      "read-version",
    );
    expect(screen.getByRole("button", { name: "Добавить операцию" })).toBeDisabled();
  });

  it("does not relabel a transfer as a portfolio contribution and preserves link on edit", async () => {
    data.flows = [
      {
        id: 8,
        reporting_month_id: 4,
        account_id: 1,
        event_date: "2030-05-12",
        boundary_amount: { amount: "1.00", currency: "RUB" },
        direction: "contribution",
        kind: "external_contribution",
        scope_membership: "stable_in_scope",
        transfer_link_id: 9,
        transfer_status: "resolved",
        portfolio_scope_classification: "internal_transfer",
        account_scope_classification: "external_contribution",
        source: "manual",
        notes: null,
      },
    ];
    setup();
    fireEvent.click(await screen.findByRole("button", { name: "Исправить операцию 8" }));
    expect(screen.getByLabelText("Связь перевода")).toHaveValue("9");
    expect(screen.getByLabelText("Это перевод между счетами")).toBeChecked();
    expect(screen.getByText(/Портфель: внутренний перевод/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Вернуться к доходности/ })).toHaveAttribute(
      "href",
      expect.stringContaining("account_id=1"),
    );
  });
});
