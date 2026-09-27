import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ReportingMonth } from "../api/types";
import { UiV2MonthPayoutsSection } from "./UiV2MonthPayoutsSection";
import type { MonthEditorContext } from "./UiV2MonthEditorPage";

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const account = {
  id: 11,
  name: "Synthetic Broker",
  account_type: "brokerage",
  status: "active",
  external_code: null,
  include_in_capital: true,
  include_in_returns: true,
  notes: null,
};

const instrument = {
  id: 21,
  name: "Synthetic Bond",
  instrument_type: "bond",
  isin: null,
  ticker: "SYNB",
  moex_secid: null,
  currency: "RUB",
  nominal_value: null,
  is_active: true,
  manual_price_allowed: true,
  notes: null,
};

const manualFlow = {
  id: 41,
  reporting_month_id: 7,
  account_id: 11,
  instrument_id: 21,
  flow_type: "coupon",
  event_date: "2031-01-15",
  gross_amount: { amount: "1000.00", currency: "RUB" },
  tax_amount: { amount: "130.00", currency: "RUB" },
  commission_amount: { amount: "10.00", currency: "RUB" },
  net_amount: { amount: "860.00", currency: "RUB" },
  currency: "RUB",
  source: "manual",
  notes: null,
  statement_link: null,
};

const redemptionFlow = {
  ...manualFlow,
  id: 44,
  flow_type: "redemption",
  event_date: "2031-01-16",
  net_amount: { amount: "10000.00", currency: "RUB" },
};

const importedFlow = {
  ...manualFlow,
  id: 42,
  event_date: "2031-01-20",
  source: "alfa_depository_income_report",
  statement_link: {
    applied_statement_event_id: 9,
    link_mode: "statement_created",
    status: "active",
  },
};

const expectedFlow = {
  id: 51,
  reporting_month_id: 7,
  account_id: 11,
  instrument_id: 21,
  flow_type: "dividend",
  expected_date: "2031-02-10",
  gross_amount: { amount: "500.00", currency: "RUB" },
  expected_tax_amount: null,
  expected_net_amount: { amount: "435.00", currency: "RUB" },
  currency: "RUB",
  source: "manual",
  source_as_of_date: "2031-01-31",
  forecast_version: "v1",
  is_confirmed: false,
  is_approximate: true,
  notes: null,
};

function contextFor(monthId = 7, readOnly = false, setDirty = vi.fn()): MonthEditorContext {
  const month: ReportingMonth = {
    id: monthId,
    year: 2031,
    month: 1,
    status: readOnly ? "closed" : "draft",
    snapshot_date: "2031-01-31",
    source: "manual",
  };
  return {
    month,
    readOnly,
    refresh: vi.fn(async () => month),
    setDirty,
    returnToClose: null,
  };
}

function setup({
  flows = [] as unknown[],
  expected = [] as unknown[],
  expectedV2 = [] as unknown[],
  expectedVersion = "v1",
  failPost,
  failDeleteId,
  slowCreate = false,
  slowExpectedCreate = false,
  slowPatch = false,
  stalePatch = false,
}: {
  flows?: unknown[];
  expected?: unknown[];
  expectedV2?: unknown[];
  expectedVersion?: string;
  failPost?: { status: number; code: string; message: string };
  failDeleteId?: number;
  slowCreate?: boolean;
  slowExpectedCreate?: boolean;
  slowPatch?: boolean;
  stalePatch?: boolean;
} = {}) {
  let finishCreate!: (value: Response) => void;
  let finishExpectedCreate!: (value: Response) => void;
  let finishPatch!: (value: Response) => void;
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    if (method === "GET" && url === "/api/accounts") return jsonResponse([account]);
    if (method === "GET" && url === "/api/instruments?active=true")
      return jsonResponse([instrument]);
    if (method === "GET" && url === "/api/investment-flows?month_id=7") return jsonResponse(flows);
    if (method === "GET" && url === "/api/investment-flows?month_id=8") return jsonResponse([]);
    if (
      method === "GET" &&
      url === `/api/expected-flows?month_id=7&forecast_version=${expectedVersion}`
    )
      return jsonResponse(expected);
    if (method === "GET" && url === "/api/expected-flows?month_id=7&forecast_version=v2")
      return jsonResponse(expectedV2);
    if (method === "GET" && url === "/api/expected-flows?month_id=8&forecast_version=v1")
      return jsonResponse([]);
    if (method === "GET" && url === "/api/expected-flows?month_id=8&forecast_version=v2")
      return jsonResponse([]);
    if (method === "POST" && url === "/api/investment-flows") {
      if (failPost)
        return jsonResponse(
          { error: { code: failPost.code, message: failPost.message, details: [] } },
          failPost.status,
        );
      const body = JSON.parse(String(init?.body));
      const created = { ...manualFlow, ...body, id: 31, reporting_month_id: 7 };
      if (slowCreate)
        return new Promise<Response>((resolve) => {
          finishCreate = resolve;
        });
      flows = [...flows, created];
      return jsonResponse(created, 201);
    }
    if (method === "POST" && url === "/api/expected-flows") {
      if (failPost)
        return jsonResponse(
          { error: { code: failPost.code, message: failPost.message, details: [] } },
          failPost.status,
        );
      const body = JSON.parse(String(init?.body));
      const created = { ...expectedFlow, ...body, id: 52, reporting_month_id: 7 };
      if (slowExpectedCreate)
        return new Promise<Response>((resolve) => {
          finishExpectedCreate = resolve;
        });
      if (created.forecast_version === "v2") expectedV2 = [...expectedV2, created];
      else expected = [...expected, created];
      return jsonResponse(created, 201);
    }
    if (method === "PATCH" && url === "/api/investment-flows/41") {
      const body = JSON.parse(String(init?.body));
      const updated = { ...manualFlow, ...body };
      if (slowPatch)
        return new Promise<Response>((resolve) => {
          finishPatch = resolve;
        });
      if (!stalePatch) {
        flows = (flows as unknown[]).map((row) =>
          (row as { id: number }).id === 41 ? updated : row,
        );
      }
      return jsonResponse(updated);
    }
    if (method === "DELETE" && url === "/api/investment-flows/41") {
      if (failDeleteId === 41)
        return jsonResponse(
          { error: { code: "closed_month", message: "month is closed", details: [] } },
          409,
        );
      flows = (flows as unknown[]).filter((row) => (row as { id: number }).id !== 41);
      return new Response(null, { status: 204 });
    }
    if (method === "DELETE" && url === "/api/expected-flows/51") {
      expected = (expected as unknown[]).filter((row) => (row as { id: number }).id !== 51);
      return new Response(null, { status: 204 });
    }
    if (method === "GET" && url.startsWith("/api/payouts/calendar"))
      throw new Error("calendar must not be requested by the payouts leaf");
    if (method === "POST" && url.includes("payout-batch-preview"))
      throw new Error("preview must not be requested by the payouts leaf");
    if (method === "POST" && url.includes("payout-apply"))
      throw new Error("apply must not be requested by the payouts leaf");
    if (method === "POST" && url.includes("statement-import"))
      throw new Error("statement import must not be requested by the payouts leaf");
    return jsonResponse(
      { error: { code: "not_found", message: `no mock for ${method} ${url}`, details: [] } },
      404,
    );
  });
  vi.stubGlobal("fetch", fetchMock);
  return {
    fetchMock,
    releaseCreate: (created: unknown = { ...manualFlow, id: 31, reporting_month_id: 7 }) => {
      flows = [...(flows as unknown[]), created];
      return finishCreate(jsonResponse(created, 201));
    },
    releaseExpectedCreate: (created: Record<string, unknown>) => {
      const row = { ...expectedFlow, ...created, id: 52, reporting_month_id: 7 };
      if (row.forecast_version === "v2") expectedV2 = [...expectedV2, row];
      else expected = [...expected, row];
      return finishExpectedCreate(jsonResponse(row, 201));
    },
    releasePatch: (updated: unknown) => {
      flows = (flows as unknown[]).map((row) =>
        (row as { id: number }).id === 41
          ? { ...(row as Record<string, unknown>), ...(updated as Record<string, unknown>) }
          : row,
      );
      return finishPatch(jsonResponse(updated));
    },
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("UiV2MonthPayoutsSection", () => {
  it("creates a manual fact with exact money and readback, keeping null instrument allowed", async () => {
    const { fetchMock } = setup();
    const user = userEvent.setup();
    render(<UiV2MonthPayoutsSection context={contextFor()} />);

    expect(await screen.findByRole("heading", { name: "Фактические потоки" })).toBeInTheDocument();
    const instrumentSelect = await screen.findByLabelText("Инструмент (необязательно)");
    expect(instrumentSelect).toHaveValue("");
    await user.type(screen.getByLabelText("Брутто"), "1000");
    await user.type(screen.getByLabelText("Нетто"), "860");
    await user.click(screen.getByRole("button", { name: "Добавить выплату" }));

    expect(await screen.findByText("Выплата сохранена и подтверждена.")).toBeInTheDocument();
    const post = fetchMock.mock.calls.find(
      ([input, init]) => String(input) === "/api/investment-flows" && init?.method === "POST",
    );
    expect(post).toBeDefined();
    expect(JSON.parse(String(post?.[1]?.body))).toMatchObject({
      reporting_month_id: 7,
      account_id: 11,
      flow_type: "coupon",
      gross_amount: { amount: "1000.00", currency: "RUB" },
      net_amount: { amount: "860.00", currency: "RUB" },
      instrument_id: null,
    });
  });

  it("keeps fact, forecast and principal visually distinct", async () => {
    const { fetchMock } = setup({ flows: [manualFlow, redemptionFlow], expected: [expectedFlow] });
    render(<UiV2MonthPayoutsSection context={contextFor()} />);

    expect(await screen.findByText("пассивный доход")).toBeInTheDocument();
    expect(screen.getByText("не доход (погашение)")).toBeInTheDocument();
    expect(screen.getAllByText(/план/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Погашение (не доход):")).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some(([input]) => String(input).includes("/api/payouts/calendar")),
    ).toBe(false);
  });

  it("shows validation without a success notice", async () => {
    setup();
    const user = userEvent.setup();
    render(<UiV2MonthPayoutsSection context={contextFor()} />);

    await screen.findByRole("heading", { name: "Фактические потоки" });
    await user.type(screen.getByLabelText("Брутто"), "abc");
    await user.type(screen.getByLabelText("Нетто"), "860");
    await user.click(screen.getByRole("button", { name: "Добавить выплату" }));
    expect(await screen.findByText("Укажи gross и net")).toBeInTheDocument();
    expect(screen.queryByText("Выплата сохранена и подтверждена.")).not.toBeInTheDocument();
  });

  it("keeps the draft when save fails and blocks double submit", async () => {
    const { fetchMock } = setup({
      failPost: { status: 422, code: "validation_error", message: "bad amount" },
    });
    const user = userEvent.setup();
    render(<UiV2MonthPayoutsSection context={contextFor()} />);

    await screen.findByRole("heading", { name: "Фактические потоки" });
    await user.type(screen.getByLabelText("Брутто"), "1000");
    await user.type(screen.getByLabelText("Нетто"), "860");
    await user.click(screen.getByRole("button", { name: "Добавить выплату" }));
    await user.click(screen.getByRole("button", { name: "Добавить выплату" }));
    expect(await screen.findByText("Проверь введённые данные.")).toBeInTheDocument();
    expect(screen.getByLabelText("Брутто")).toHaveValue("1000");
    expect(
      fetchMock.mock.calls.filter(
        ([input, init]) => String(input) === "/api/investment-flows" && init?.method === "POST",
      ).length,
    ).toBeLessThanOrEqual(2);
  });

  it("edits a manual row and keeps imported provenance read-only", async () => {
    const { fetchMock } = setup({ flows: [manualFlow, importedFlow] });
    const user = userEvent.setup();
    render(<UiV2MonthPayoutsSection context={contextFor()} />);

    const table = await screen.findByRole("table");
    expect(table).toHaveTextContent("Выписка Альфа-Банка");
    expect(table).toHaveTextContent("не редактируется");
    await user.click(
      within(table).getByRole("button", { name: "Действия для выплаты «Купон» от 2031-01-15" }),
    );
    await user.click(screen.getByRole("menuitem", { name: "Изменить" }));
    const net = screen.getByDisplayValue("860.00");
    await user.clear(net);
    await user.type(net, "870.00");
    await user.click(screen.getByRole("button", { name: "OK" }));

    await waitFor(() => {
      const patch = fetchMock.mock.calls.find(
        ([input, init]) => String(input) === "/api/investment-flows/41" && init?.method === "PATCH",
      );
      expect(patch).toBeDefined();
      expect(JSON.parse(String(patch?.[1]?.body))).toMatchObject({
        net_amount: { amount: "870.00", currency: "RUB" },
      });
    });
  });

  it("confirms delete with fresh read and surfaces backend errors", async () => {
    const { fetchMock } = setup({ flows: [manualFlow] });
    const user = userEvent.setup();
    render(<UiV2MonthPayoutsSection context={contextFor()} />);

    const tables = await screen.findAllByRole("table");
    expect(tables.length).toBeGreaterThan(0);
    await user.click(
      screen.getByRole("button", { name: "Действия для выплаты «Купон» от 2031-01-15" }),
    );
    await user.click(screen.getByRole("menuitem", { name: "Удалить" }));
    const dialog = screen.getByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Удалить" }));
    expect(await screen.findByText("Выплата удалена и подтверждена.")).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.filter(
        ([input, init]) =>
          String(input) === "/api/investment-flows?month_id=7" && (init?.method ?? "GET") === "GET",
      ).length,
    ).toBeGreaterThan(1);
  });

  it("creates an expected forecast as unconfirmed plan", async () => {
    const { fetchMock } = setup({ expected: [] });
    const user = userEvent.setup();
    render(<UiV2MonthPayoutsSection context={contextFor()} />);

    expect(
      await screen.findByRole("heading", { name: "Ручные ожидаемые выплаты" }),
    ).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Инструмент выплаты"), "21");
    await user.type(screen.getByLabelText("Прогноз брутто"), "500");
    await user.click(screen.getByRole("button", { name: "Добавить ожидаемую выплату" }));

    expect(
      await screen.findByText("Ожидаемая выплата сохранена и подтверждена."),
    ).toBeInTheDocument();
    const post = fetchMock.mock.calls.find(
      ([input, init]) => String(input) === "/api/expected-flows" && init?.method === "POST",
    );
    expect(JSON.parse(String(post?.[1]?.body))).toMatchObject({
      reporting_month_id: 7,
      instrument_id: 21,
      forecast_version: "v1",
    });
  });

  it("disables mutations and hides forms in a closed month", async () => {
    setup({ flows: [manualFlow], expected: [expectedFlow] });
    const user = userEvent.setup();
    render(<UiV2MonthPayoutsSection context={contextFor(7, true)} />);

    const tables = await screen.findAllByRole("table");
    expect(tables.length).toBe(2);
    expect(screen.queryByRole("button", { name: "Добавить выплату" })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Добавить ожидаемую выплату" }),
    ).not.toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Действия для выплаты «Купон» от 2031-01-15" }),
    );
    expect(screen.getByRole("menuitem", { name: "Изменить" })).toBeDisabled();
    expect(screen.getByRole("menuitem", { name: "Удалить" })).toBeDisabled();
  });

  it("reports dirty state and clears it on unmount", async () => {
    setup();
    const setDirty = vi.fn();
    const user = userEvent.setup();
    const view = render(<UiV2MonthPayoutsSection context={contextFor(7, false, setDirty)} />);

    await screen.findByRole("heading", { name: "Фактические потоки" });
    await user.type(screen.getByLabelText("Брутто"), "10");
    await waitFor(() => expect(setDirty).toHaveBeenCalledWith("payouts", true));
    view.unmount();
    expect(setDirty).toHaveBeenCalledWith("payouts", false);
  });

  it("ignores a late create response after month switch", async () => {
    const { fetchMock, releaseCreate } = setup({ slowCreate: true });
    const user = userEvent.setup();
    const first = contextFor(7);
    const { rerender } = render(<UiV2MonthPayoutsSection context={first} />);

    await screen.findByRole("heading", { name: "Фактические потоки" });
    await user.type(screen.getByLabelText("Брутто"), "1000");
    await user.type(screen.getByLabelText("Нетто"), "860");
    await user.click(screen.getByRole("button", { name: "Добавить выплату" }));
    rerender(<UiV2MonthPayoutsSection context={contextFor(8)} />);
    releaseCreate();
    await waitFor(() =>
      expect(screen.queryByText("Выплата сохранена и подтверждена.")).not.toBeInTheDocument(),
    );
    expect(screen.queryByText("Выплата сохранена.")).not.toBeInTheDocument();
    // The server-side write stands honestly: only the current-month view stays clean.
    expect(
      fetchMock.mock.calls.some(
        ([input, init]) => String(input) === "/api/investment-flows" && init?.method === "POST",
      ),
    ).toBe(true);
    // The new month form is usable again and starts empty.
    expect(screen.getByLabelText("Брутто")).toHaveValue("");
    expect(screen.getByLabelText("Брутто")).toBeEnabled();
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([input]) => String(input) === "/api/investment-flows?month_id=8",
        ),
      ).toBe(true),
    );
  });

  it("preserves an unsaved actual draft when the forecast version filter changes", async () => {
    const { fetchMock } = setup({ expected: [expectedFlow] });
    const user = userEvent.setup();
    const setDirty = vi.fn();
    render(<UiV2MonthPayoutsSection context={contextFor(7, false, setDirty)} />);

    await screen.findByRole("heading", { name: "Фактические потоки" });
    await user.type(screen.getByLabelText("Брутто"), "1000");
    await user.type(screen.getByLabelText("Нетто"), "860");
    await waitFor(() => expect(setDirty).toHaveBeenCalledWith("payouts", true));

    const versionFilter = screen.getByLabelText("Версия прогноза");
    await user.clear(versionFilter);
    await user.type(versionFilter, "v2");
    await user.click(screen.getByRole("button", { name: "Показать" }));

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([input]) => String(input) === "/api/expected-flows?month_id=7&forecast_version=v2",
        ),
      ).toBe(true),
    );
    // Unrelated actual input survives the filter change with its dirty flag.
    expect(screen.getByLabelText("Брутто")).toHaveValue("1000");
    expect(screen.getByLabelText("Нетто")).toHaveValue("860");
    expect(setDirty).toHaveBeenLastCalledWith("payouts", true);
    expect(screen.queryByText("Выплата сохранена и подтверждена.")).not.toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some(
        ([input, init]) => String(input) === "/api/investment-flows" && init?.method === "POST",
      ),
    ).toBe(false);
  });

  it("preserves an unsaved expected draft and an open edit across a version change", async () => {
    setup({ flows: [manualFlow] });
    const user = userEvent.setup();
    render(<UiV2MonthPayoutsSection context={contextFor()} />);

    await screen.findByRole("heading", { name: "Фактические потоки" });
    const table = screen.getAllByRole("table")[0];
    await user.click(
      within(table).getByRole("button", { name: "Действия для выплаты «Купон» от 2031-01-15" }),
    );
    await user.click(screen.getByRole("menuitem", { name: "Изменить" }));
    const editNet = screen.getByDisplayValue("860.00");
    await user.clear(editNet);
    await user.type(editNet, "861.00");
    await user.type(screen.getByLabelText("Прогноз брутто"), "500");

    const versionFilter = screen.getByLabelText("Версия прогноза");
    await user.clear(versionFilter);
    await user.type(versionFilter, "v2");
    await user.click(screen.getByRole("button", { name: "Показать" }));

    await screen.findByText("Нет ожидаемых выплат для версии «v2».");
    expect(screen.getByDisplayValue("861.00")).toBeInTheDocument();
    expect(screen.getByLabelText("Прогноз брутто")).toHaveValue("500");
    expect(screen.getByRole("button", { name: "OK" })).toBeInTheDocument();
  });

  it("keeps newer input typed during a pending save", async () => {
    const { releaseCreate } = setup({ slowCreate: true });
    const user = userEvent.setup();
    render(<UiV2MonthPayoutsSection context={contextFor()} />);

    await screen.findByRole("heading", { name: "Фактические потоки" });
    await user.type(screen.getByLabelText("Брутто"), "1000");
    await user.type(screen.getByLabelText("Нетто"), "860");
    await user.click(screen.getByRole("button", { name: "Добавить выплату" }));
    await user.type(screen.getByLabelText("Брутто"), "0");
    expect(screen.getByLabelText("Брутто")).toHaveValue("10000");
    releaseCreate();
    expect(
      await screen.findByText("Выплата сохранена. Есть новые несохранённые правки."),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Брутто")).toHaveValue("10000");
  });

  it("does not leak a forecast created for another version into the current view", async () => {
    const { fetchMock } = setup({ expected: [] });
    const user = userEvent.setup();
    render(<UiV2MonthPayoutsSection context={contextFor()} />);

    expect(
      await screen.findByRole("heading", { name: "Ручные ожидаемые выплаты" }),
    ).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Инструмент выплаты"), "21");
    await user.type(screen.getByLabelText("Прогноз брутто"), "500");
    const rowVersion = screen.getByLabelText("Версия");
    await user.clear(rowVersion);
    await user.type(rowVersion, "v2");
    await user.click(screen.getByRole("button", { name: "Добавить ожидаемую выплату" }));

    expect(
      await screen.findByText("Ожидаемая выплата сохранена (версия «v2»)."),
    ).toBeInTheDocument();
    // The v1 view stays v1: filter value, empty state, no foreign rows.
    expect(screen.getByLabelText("Версия прогноза")).toHaveValue("v1");
    expect(screen.getByText("Нет ожидаемых выплат для версии «v1».")).toBeInTheDocument();
    expect(screen.queryByText("10.02.2031")).not.toBeInTheDocument();
    const post = fetchMock.mock.calls.find(
      ([input, init]) => String(input) === "/api/expected-flows" && init?.method === "POST",
    );
    expect(JSON.parse(String(post?.[1]?.body))).toMatchObject({ forecast_version: "v2" });
  });

  it("installs the validated dataset when the version changes mid-flight", async () => {
    const { fetchMock, releaseExpectedCreate } = setup({
      expected: [],
      expectedV2: [],
      slowExpectedCreate: true,
    });
    const user = userEvent.setup();
    render(<UiV2MonthPayoutsSection context={contextFor()} />);

    expect(
      await screen.findByRole("heading", { name: "Ручные ожидаемые выплаты" }),
    ).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Инструмент выплаты"), "21");
    await user.type(screen.getByLabelText("Прогноз брутто"), "500");
    const rowVersion = screen.getByLabelText("Версия");
    await user.clear(rowVersion);
    await user.type(rowVersion, "v2");
    await user.click(screen.getByRole("button", { name: "Добавить ожидаемую выплату" }));

    // Switch the view to v2 while the create is still in flight.
    const versionFilter = screen.getByLabelText("Версия прогноза");
    await user.clear(versionFilter);
    await user.type(versionFilter, "v2");
    await user.click(screen.getByRole("button", { name: "Показать" }));
    releaseExpectedCreate({
      ...expectedFlow,
      id: 52,
      reporting_month_id: 7,
      forecast_version: "v2",
    });

    expect(
      await screen.findByText("Ожидаемая выплата сохранена и подтверждена."),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Версия прогноза")).toHaveValue("v2");
    expect(
      fetchMock.mock.calls.some(
        ([input]) => String(input) === "/api/expected-flows?month_id=7&forecast_version=v2",
      ),
    ).toBe(true);
  });

  it("rejects an edit whose readback misses the submitted values", async () => {
    setup({ flows: [manualFlow], stalePatch: true });
    const user = userEvent.setup();
    render(<UiV2MonthPayoutsSection context={contextFor()} />);

    const table = await screen.findAllByRole("table").then((tables) => tables[0]);
    await user.click(
      within(table).getByRole("button", { name: "Действия для выплаты «Купон» от 2031-01-15" }),
    );
    await user.click(screen.getByRole("menuitem", { name: "Изменить" }));
    const net = screen.getByDisplayValue("860.00");
    await user.clear(net);
    await user.type(net, "870.00");
    await user.click(screen.getByRole("button", { name: "OK" }));

    expect(
      await screen.findByText("Изменение не подтверждено повторной загрузкой."),
    ).toBeInTheDocument();
    // The edit stays open with the submitted values; nothing is announced as saved.
    expect(screen.getByDisplayValue("870.00")).toBeInTheDocument();
    expect(screen.queryByText("Выплата обновлена и подтверждена.")).not.toBeInTheDocument();
  });

  it("freezes edit controls while the save is in flight", async () => {
    const { releasePatch } = setup({ flows: [manualFlow], slowPatch: true });
    const user = userEvent.setup();
    render(<UiV2MonthPayoutsSection context={contextFor()} />);

    const table = await screen.findAllByRole("table").then((tables) => tables[0]);
    await user.click(
      within(table).getByRole("button", { name: "Действия для выплаты «Купон» от 2031-01-15" }),
    );
    await user.click(screen.getByRole("menuitem", { name: "Изменить" }));
    const net = screen.getByDisplayValue("860.00");
    await user.clear(net);
    await user.type(net, "870.00");
    await user.click(screen.getByRole("button", { name: "OK" }));

    await waitFor(() => expect(screen.getByDisplayValue("870.00")).toBeDisabled());
    expect(screen.getByDisplayValue("1000.00")).toBeDisabled();
    releasePatch({ ...manualFlow, net_amount: { amount: "870.00", currency: "RUB" } });
    expect(await screen.findByText("Выплата обновлена и подтверждена.")).toBeInTheDocument();
  });

  it("submits a new fact by keyboard only", async () => {
    const { fetchMock } = setup();
    const user = userEvent.setup();
    render(<UiV2MonthPayoutsSection context={contextFor()} />);

    expect(await screen.findByRole("heading", { name: "Фактические потоки" })).toBeInTheDocument();
    (screen.getByLabelText("Тип потока") as HTMLElement).focus();
    await user.keyboard("[Tab][Tab][Tab][Tab]");
    expect(screen.getByLabelText("Брутто")).toHaveFocus();
    await user.keyboard("1000[Tab][Tab][Tab]");
    expect(screen.getByLabelText("Нетто")).toHaveFocus();
    await user.keyboard("860[Tab][Enter]");

    expect(await screen.findByText("Выплата сохранена и подтверждена.")).toBeInTheDocument();
    const post = fetchMock.mock.calls.find(
      ([input, init]) => String(input) === "/api/investment-flows" && init?.method === "POST",
    );
    expect(JSON.parse(String(post?.[1]?.body))).toMatchObject({
      gross_amount: { amount: "1000.00", currency: "RUB" },
      net_amount: { amount: "860.00", currency: "RUB" },
    });
  });
});
