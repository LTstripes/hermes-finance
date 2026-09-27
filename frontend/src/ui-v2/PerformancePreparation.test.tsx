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
          accounts={[
            { id: 1, name: "Synthetic A" } as Account,
            {
              id: 2,
              name: "Synthetic B",
              account_type: "brokerage",
              status: "inactive",
              external_code: null,
              include_in_capital: false,
              include_in_returns: false,
              notes: null,
            },
          ]}
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
    expect(screen.getByLabelText("Счёт операции")).toHaveValue("");
    fireEvent.click(screen.getByLabelText(/Я проверил.*дату, счёт, сумму/));
    expect(screen.getByRole("button", { name: "Сохранить операцию" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Счёт операции"), { target: { value: "2" } });
    expect(screen.getByLabelText(/Я проверил.*дату, счёт, сумму/)).not.toBeChecked();
    fireEvent.click(screen.getByLabelText(/Я проверил.*дату, счёт, сумму/));
    fireEvent.click(screen.getByRole("button", { name: "Сохранить операцию" }));
    await screen.findByText(/Не повторяйте запись вслепую/);
    expect(savePreparation).toHaveBeenCalledTimes(1);
    expect(savePreparation).toHaveBeenCalledWith(
      "/api/external-flows",
      "POST",
      expect.objectContaining({
        boundary_amount: { amount: "90071992547409.91", currency: "RUB" },
        account_id: 2,
        scope_membership: "unknown",
      }),
      "read-version",
    );
    expect(screen.getByRole("button", { name: "Добавить операцию" })).toBeDisabled();
  });

  it("does not relabel a transfer as a portfolio contribution and preserves link on edit", async () => {
    vi.mocked(savePreparation).mockRejectedValue(
      new ApiClientError(422, {
        code: "unprocessable",
        message: "transfer link legs cannot change while reconciliation evidence exists",
        details: [],
      }),
    );
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
    expect(screen.getByLabelText("Счёт операции")).toHaveValue("1");
    fireEvent.change(screen.getByLabelText("Счёт операции"), { target: { value: "2" } });
    fireEvent.click(screen.getByLabelText(/Я проверил.*дату, счёт, сумму/));
    fireEvent.click(screen.getByRole("button", { name: "Сохранить операцию" }));
    await screen.findByText(
      /Запись отклонена: transfer link legs cannot change while reconciliation evidence exists/,
    );
    expect(savePreparation).toHaveBeenCalledTimes(1);
    expect(savePreparation).toHaveBeenCalledWith(
      "/api/external-flows/8",
      "PATCH",
      expect.objectContaining({ account_id: 2, transfer_link_id: 9 }),
      "read-version",
    );
    expect(screen.getByRole("button", { name: "Добавить операцию" })).toBeDisabled();
  });

  it.each(["success", "wrong-account", "different-version", "still-in-source", "missing-row"])(
    "checks both account ledgers after moving a flow: %s",
    async (outcome) => {
      const original = {
        id: 8,
        reporting_month_id: 4,
        account_id: 1,
        event_date: "2030-05-12",
        boundary_amount: { amount: "1.00", currency: "RUB" },
        direction: "contribution",
        kind: "external_contribution",
        scope_membership: "unknown",
        transfer_link_id: null,
        source: "manual",
      } as Preparation["flows"][number];
      data.flows = [original];
      let destination: Preparation;
      vi.mocked(getPreparation).mockImplementation(async (accountId) =>
        structuredClone(accountId === 2 ? destination : data),
      );
      vi.mocked(savePreparation).mockImplementation(async (_path, _method, body) => {
        const saved = { ...original, ...(body as object) };
        data.flows = outcome === "still-in-source" ? [original] : [];
        data.evidence_token = "after-move";
        destination = {
          ...data,
          account_id: outcome === "wrong-account" ? 1 : 2,
          evidence_token: outcome === "different-version" ? "concurrent-edit" : "after-move",
          flows: outcome === "missing-row" ? [] : [saved],
        };
        return saved;
      });
      setup();
      fireEvent.click(await screen.findByRole("button", { name: "Исправить операцию 8" }));
      fireEvent.change(screen.getByLabelText("Счёт операции"), { target: { value: "2" } });
      fireEvent.click(screen.getByLabelText(/Я проверил.*дату, счёт, сумму/));
      const save = screen.getByRole("button", { name: "Сохранить операцию" });
      fireEvent.click(save);
      fireEvent.click(save);
      await screen.findByText(
        outcome === "success" ? /Запись подтверждена/ : /повторная проверка не завершилась/,
      );
      expect(savePreparation).toHaveBeenCalledTimes(1);
      expect(savePreparation).toHaveBeenCalledWith(
        "/api/external-flows/8",
        "PATCH",
        expect.objectContaining({ account_id: 2, scope_membership: "unknown" }),
        "read-version",
      );
      expect(getPreparation).toHaveBeenCalledWith(
        2,
        context.start,
        context.end,
        expect.any(AbortSignal),
      );
      if (outcome === "success") {
        expect(
          screen.queryByRole("button", { name: "Исправить операцию 8" }),
        ).not.toBeInTheDocument();
        expect(getPerformanceReadiness).toHaveBeenCalledWith(
          context.start,
          context.end,
          "account",
          1,
          expect.any(AbortSignal),
        );
      } else {
        expect(screen.getByRole("button", { name: "Добавить операцию" })).toBeDisabled();
        expect(getPerformanceReadiness).not.toHaveBeenCalled();
      }
    },
  );

  it("distinguishes acknowledged writes from failed readiness read-back", async () => {
    vi.mocked(savePreparation).mockImplementation(async (_path, _method, body) => {
      const saved = { id: 7, ...(body as object) };
      data.cash_coverages = [saved as Preparation["cash_coverages"][number]];
      data.evidence_token = "after";
      return saved;
    });
    vi.mocked(getPerformanceReadiness).mockRejectedValue(
      new ApiClientError(422, { code: "unprocessable", message: "invalid interval", details: [] }),
    );
    setup();
    await screen.findByRole("button", { name: "Сохранить: денежная история" });
    fireEvent.click(screen.getAllByLabelText(/история неполна или ещё не проверена/)[0]);
    fireEvent.click(screen.getByRole("button", { name: "Сохранить: денежная история" }));
    await screen.findByText(/Сервер принял запись, но повторная проверка не завершилась/);
    expect(screen.queryByText(/Запись отклонена/)).not.toBeInTheDocument();
    expect(savePreparation).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Сохранить: денежная история" })).toBeDisabled();
  });
});
