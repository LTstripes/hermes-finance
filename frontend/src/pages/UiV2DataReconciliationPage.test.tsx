import { QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { BrokerReconciliationResponse, ReconciliationRow } from "../api/brokerReconciliation";
import { createQueryClient } from "../queryClient";
import { uiV2Accounts, uiV2Instruments, uiV2Months } from "../test/uiV2Fixtures";
import UiV2DataReconciliationPage from "../ui-v2/UiV2DataReconciliationPage";

const diagnostics = {
  schema_version: "alfa-pro-diagnostics/v1",
  provider: "alfa_pro",
  snapshot_status: "complete",
  eligible_for_apply: false as const,
  compatibility_state: "compatible",
  compatibility_fingerprint: "a".repeat(64),
  api_doc_version: "synthetic-2.1",
  observed_alfa_pro_version: "synthetic-compat-1",
  observed_api_version: "2.1",
  observed_protocol_version: "router-v1",
  protocol_family: "router-v1",
  layout_family: "snapshot-v2.1",
  capabilities: ["position_quantity"],
  failure_class: "none",
  failure_codes: [],
  entity_status: ["positions=ok"],
  entity_counts: ["positions=1"],
  observed_fields: ["position.quantity"],
  safe_artifact: true,
  raw_payload_saved: false,
  private_values_included: false,
  credentials_included: false,
};

function row(
  state: ReconciliationRow["state"],
  overrides: Partial<ReconciliationRow> = {},
): ReconciliationRow {
  return {
    state,
    account_id: 1,
    instrument_id: 10,
    account_name: "Синтетический счёт",
    instrument_name: "Синтетическая облигация",
    instrument_isin: "RU000SYN00001",
    instrument_ticker: "SYN",
    provider_account_id: "prov-acc",
    provider_instrument_id: "prov-inst",
    hermes_quantity: "10",
    provider_quantity: state === "differs" ? "9" : "10",
    quantity_difference: state === "differs" ? "1" : "0",
    quantity_equal: state !== "differs",
    hermes_market_price_per_unit_kopecks: 10000,
    provider_broker_unit_price: "100.00",
    provider_accounting_price: "100.00",
    provider_market_value: "1000.00",
    price_comparable: "yes",
    hermes_accrued_interest_kopecks: 0,
    provider_accrued_interest_nkd: "0.00",
    nkd_comparable: "yes",
    hermes_unrealized_result_kopecks: 0,
    provider_unrealized_result: "0.00",
    unrealized_comparable: "yes",
    reason: state === "unresolved" ? "mapping_unresolved" : null,
    warnings: [],
    comparison_only_fields: ["provider_broker_unit_price"],
    fingerprint: "fp-1",
    ...overrides,
  };
}

function result(
  overrides: Partial<BrokerReconciliationResponse> = {},
): BrokerReconciliationResponse {
  return {
    reporting_month_id: 12,
    provider: "alfa_pro",
    status: "applicable",
    read_only: true,
    eligible_for_apply: false,
    stale: false,
    snapshot_status: "complete",
    compatibility_state: "compatible",
    compatibility_fingerprint: "a".repeat(64),
    snapshot_fingerprint: "b".repeat(64),
    source_as_of: "2031-08-30T12:00:00+00:00",
    captured_at: "2031-08-30T12:05:00+00:00",
    month_status: "draft",
    month_closed: false,
    accounts: [],
    instruments: [],
    rows: [row("matched"), row("differs", { fingerprint: "fp-2" })],
    cash: [],
    warnings: [],
    diagnostics,
    diagnostic_report: "synthetic diagnostic report",
    error_code: null,
    message: null,
    ...overrides,
  };
}

function setup(path = "/v2/data/reconciliation") {
  const client = createQueryClient();
  const reads: string[] = [];
  const posts: string[] = [];
  const state = {
    months: uiV2Months,
    preview: result(),
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
      const url = new URL(String(input), "http://localhost");
      const method = options?.method ?? "GET";
      const line = `${method} ${url.pathname}`;
      if (method === "GET") reads.push(line);
      if (method === "POST") posts.push(line);
      let data: unknown;
      if (url.pathname === "/api/months") data = state.months;
      else if (url.pathname === "/api/accounts") data = uiV2Accounts;
      else if (url.pathname === "/api/instruments") data = uiV2Instruments;
      else if (url.pathname === "/api/months/12/broker-reconciliation-preview")
        data = state.preview;
      else if (url.pathname === "/api/months/91/broker-reconciliation-preview") {
        data = result({ reporting_month_id: 91, month_status: "closed", month_closed: true });
      } else throw new Error(`Unexpected ${method} ${url.pathname}`);
      return new Response(JSON.stringify(data), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
  function mount() {
    return render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path="v2/data/reconciliation" element={<UiV2DataReconciliationPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
  }
  return { mount, posts, reads, state };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("UI v2 Data reconciliation", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("never calls the broker preview on mount", async () => {
    const { mount, posts } = setup();
    mount();
    expect(await screen.findByTestId("reconciliation-idle")).toBeTruthy();
    expect(screen.getByTestId("reconciliation-safety-note")).toHaveTextContent(
      "Сверка только показывает различия и ничего не сохраняет",
    );
    expect(screen.getByRole("heading", { name: /Сверка ещё не запрашивалась/ })).toBeTruthy();
    await waitFor(() =>
      expect(screen.getByTestId("data-month-context")).toHaveTextContent("Август"),
    );
    expect(posts).toEqual([]);
  });

  it("runs preview only after owner click and keeps read-only semantics", async () => {
    const user = userEvent.setup();
    const { mount, posts } = setup();
    mount();
    await screen.findByTestId("reconciliation-idle");
    await user.click(screen.getByRole("button", { name: "Проверить снимок" }));
    expect(await screen.findByTestId("reconciliation-result")).toBeTruthy();
    expect(posts).toEqual(["POST /api/months/12/broker-reconciliation-preview"]);
    expect(screen.getByTestId("reconciliation-safety-note")).toHaveTextContent(
      "Данные брокера запрашиваются только после нажатия",
    );
    expect(screen.queryByText(/eligible_for_apply|read_only|comparison_only_fields/i)).toBeNull();
    expect(screen.getByTestId("reconciliation-rows")).toHaveTextContent("Сравнение позиций");
    expect(screen.getByTestId("reconciliation-rows")).toHaveTextContent("Совпадает");
  });

  it("translates reconciliation reasons for the owner view", async () => {
    const user = userEvent.setup();
    const { mount, state } = setup();
    state.preview = result({
      rows: [row("unresolved", { reason: "mapping_unresolved" })],
    });
    mount();
    await user.click(await screen.findByRole("button", { name: "Проверить снимок" }));
    const rows = await screen.findByTestId("reconciliation-rows");
    expect(rows).toHaveTextContent("Сопоставление не подтверждено.");
    expect(rows).toHaveTextContent("Сверка остановлена: позиция не подтверждена.");
    expect(rows).not.toHaveTextContent("mapping_unresolved");
  });

  it("fail-closes on invalid month and does not POST", async () => {
    const { mount, posts } = setup("/v2/data/reconciliation?month=0");
    mount();
    expect(await screen.findByText(/Некорректный параметр месяца/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Проверить снимок" })).toBeNull();
    expect(posts).toEqual([]);
  });

  it("shows the safety gate instead of a pretty comparison when unavailable", async () => {
    const user = userEvent.setup();
    const { mount, state } = setup();
    state.preview = result({
      stale: true,
      status: "non_applicable",
      snapshot_status: "complete",
      compatibility_state: "compatible",
    });
    mount();
    await user.click(await screen.findByRole("button", { name: "Проверить снимок" }));
    expect(await screen.findByTestId("reconciliation-gate")).toHaveTextContent(
      "Сверка остановлена из соображений безопасности",
    );
    expect(screen.queryByTestId("reconciliation-mapping")).toBeNull();
  });

  it("hides unsafe diagnostic text when the artifact gate fails", async () => {
    const user = userEvent.setup();
    const { mount, state } = setup();
    state.preview = result({
      diagnostics: { ...diagnostics, safe_artifact: false },
    });
    mount();
    await user.click(await screen.findByRole("button", { name: "Проверить снимок" }));
    await user.click(await screen.findByText("Техническая диагностика"));
    expect(screen.getByTestId("reconciliation-diagnostics")).toHaveTextContent(
      "Диагностический текст скрыт",
    );
    expect(screen.queryByText("synthetic diagnostic report")).toBeNull();
  });

  it("rejects a preview response whose reporting_month_id does not match the request", async () => {
    const user = userEvent.setup();
    const { mount, state } = setup();
    state.preview = result({ reporting_month_id: 91 });
    mount();
    await screen.findByTestId("reconciliation-idle");
    await user.click(screen.getByRole("button", { name: "Проверить снимок" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Ответ сверки не соответствует выбранному месяцу",
    );
    expect(screen.queryByTestId("reconciliation-result")).toBeNull();
    expect(screen.getByTestId("reconciliation-idle")).toBeTruthy();
  });

  it("ignores stale in-flight completion after the selected month changes", async () => {
    const user = userEvent.setup();
    const client = createQueryClient();
    let releasePreview: (value: Response) => void = () => {
      throw new Error("Preview gate was not initialized");
    };
    const previewGate = new Promise<Response>((resolve) => {
      releasePreview = resolve;
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
        const url = new URL(String(input), "http://localhost");
        const method = options?.method ?? "GET";
        if (url.pathname === "/api/months") {
          return new Response(JSON.stringify(uiV2Months), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        if (method === "POST" && url.pathname === "/api/months/12/broker-reconciliation-preview") {
          return previewGate;
        }
        if (method === "POST" && url.pathname === "/api/months/91/broker-reconciliation-preview") {
          return new Response(
            JSON.stringify(
              result({ reporting_month_id: 91, month_status: "closed", month_closed: true }),
            ),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }
        if (url.pathname === "/api/accounts") {
          return new Response(JSON.stringify(uiV2Accounts), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        if (url.pathname === "/api/instruments") {
          return new Response(JSON.stringify(uiV2Instruments), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        throw new Error(`Unexpected ${method} ${url.pathname}`);
      }),
    );
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/v2/data/reconciliation"]}>
          <Routes>
            <Route path="v2/data/reconciliation" element={<UiV2DataReconciliationPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await screen.findByTestId("reconciliation-idle");
    await waitFor(() =>
      expect(screen.getByTestId("data-month-context")).toHaveTextContent("Август"),
    );
    await user.click(screen.getByRole("button", { name: "Проверить снимок" }));
    expect(await screen.findByRole("button", { name: "Получаем снимок…" })).toBeTruthy();
    await user.selectOptions(screen.getByLabelText("Отчётный месяц"), "91");
    await waitFor(() => expect(screen.getByTestId("data-month-context")).toHaveTextContent("Июль"));
    expect(screen.getByTestId("reconciliation-idle")).toBeTruthy();
    releasePreview(
      new Response(JSON.stringify(result({ reporting_month_id: 12 })), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Получаем снимок…" })).toBeNull(),
    );
    expect(screen.queryByTestId("reconciliation-result")).toBeNull();
    expect(screen.getByTestId("reconciliation-idle")).toBeTruthy();
    expect(screen.getByTestId("data-month-context")).toHaveTextContent("Июль");
  });
});
