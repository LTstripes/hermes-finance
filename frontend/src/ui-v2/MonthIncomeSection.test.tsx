import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useCallback, useEffect, useMemo, useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiClientError } from "../api/client";
import {
  createIncome,
  deleteIncome,
  listIncomes,
  replaceSalaryIncome,
  updateIncome,
} from "../api/incomes";
import { getMonthSummary } from "../api/summary";
import type { IncomeEntry, IncomeType, MonthSummary, ReportingMonth } from "../api/types";
import { formatMoney } from "../lib/format";
import { formatMoneyInput, isBlankMoney } from "../lib/money";
import { createQueryClient } from "../queryClient";
import { MonthIncomeSection } from "./MonthIncomeSection";
import type { MonthEditorContext } from "./UiV2MonthEditorPage";

vi.mock("../api/incomes", () => ({
  listIncomes: vi.fn(),
  createIncome: vi.fn(),
  updateIncome: vi.fn(),
  deleteIncome: vi.fn(),
  replaceSalaryIncome: vi.fn(),
}));
vi.mock("../api/summary", () => ({ getMonthSummary: vi.fn() }));

const draft: ReportingMonth = {
  id: 7,
  year: 2030,
  month: 4,
  status: "draft",
  snapshot_date: "2030-04-30",
  source: "manual",
};
const nextMonth: ReportingMonth = {
  ...draft,
  id: 8,
  month: 5,
  snapshot_date: "2030-05-31",
};

function money(amount: string) {
  return { amount, currency: "RUB" as const };
}

function entry(
  partial: Partial<IncomeEntry> & { id: number; income_type: IncomeType },
): IncomeEntry {
  return {
    reporting_month_id: draft.id,
    name: "",
    gross_amount: money("0.00"),
    tax_amount: money("0.00"),
    net_amount: money("0.00"),
    received_at: null,
    is_recurring: false,
    include_in_cash_flow: true,
    include_in_passive_income: false,
    notes: null,
    ...partial,
  };
}

function cloneEntry(row: IncomeEntry): IncomeEntry {
  return {
    ...row,
    gross_amount: { ...row.gross_amount },
    tax_amount: { ...row.tax_amount },
    net_amount: { ...row.net_amount },
  };
}

function summaryFixture(
  partial: { tax?: string; calculatedNet?: string; parts?: Array<{ rate_bps: number }> } = {},
): MonthSummary {
  return {
    month: {
      id: draft.id,
      year: draft.year,
      month: draft.month,
      status: draft.status,
      snapshot_date: draft.snapshot_date,
      source: draft.source,
    },
    salary_tax: {
      tax: money(partial.tax ?? "13000.00"),
      calculated_net: money(partial.calculatedNet ?? "87000.00"),
      ...(partial.parts ? { parts: partial.parts } : {}),
    },
    salary_actual_net: money(partial.calculatedNet ?? "87000.00"),
  } as MonthSummary;
}

function cloneSummary(summary: MonthSummary): MonthSummary {
  return {
    ...summary,
    month: { ...summary.month },
    salary_tax: { ...summary.salary_tax },
    salary_actual_net: { ...summary.salary_actual_net },
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

let store: IncomeEntry[];
let sequence: number;
let summaryData: MonthSummary;

beforeEach(() => {
  store = [];
  sequence = 0;
  summaryData = summaryFixture();

  vi.mocked(listIncomes)
    .mockReset()
    .mockImplementation(async (monthId) =>
      store.filter((row) => row.reporting_month_id === monthId).map((row) => cloneEntry(row)),
    );
  vi.mocked(getMonthSummary)
    .mockReset()
    .mockImplementation(async () => cloneSummary(summaryData));
  vi.mocked(createIncome)
    .mockReset()
    .mockImplementation(async (payload) => {
      sequence += 1;
      const created = entry({
        id: sequence,
        reporting_month_id: payload.reporting_month_id,
        income_type: payload.income_type,
        name: payload.name,
        gross_amount: payload.gross_amount,
        tax_amount: payload.tax_amount,
        net_amount: payload.net_amount,
        received_at: payload.received_at ?? null,
        is_recurring: payload.is_recurring ?? false,
        include_in_cash_flow: payload.include_in_cash_flow ?? true,
        include_in_passive_income: payload.include_in_passive_income ?? false,
        notes: payload.notes ?? null,
      });
      store.push(created);
      return cloneEntry(created);
    });
  vi.mocked(updateIncome)
    .mockReset()
    .mockImplementation(async (entryId, payload) => {
      const index = store.findIndex((row) => row.id === entryId);
      if (index < 0) {
        throw new ApiClientError(404, {
          code: "not_found",
          message: "income not found",
          details: [],
        });
      }
      const patch = Object.fromEntries(
        Object.entries(payload).filter(([, value]) => value !== undefined),
      );
      const updated = { ...store[index], ...patch } as IncomeEntry;
      store[index] = updated;
      return cloneEntry(updated);
    });
  vi.mocked(deleteIncome)
    .mockReset()
    .mockImplementation(async (entryId) => {
      store = store.filter((row) => row.id !== entryId);
    });
  vi.mocked(replaceSalaryIncome)
    .mockReset()
    .mockImplementation(async (monthId, payload) => {
      const rows = store.filter(
        (row) => row.reporting_month_id === monthId && row.income_type === "salary",
      );
      store = store.filter(
        (row) => !(row.reporting_month_id === monthId && row.income_type === "salary"),
      );
      const zero =
        isBlankMoney(payload.gross_amount.amount) &&
        isBlankMoney(payload.tax_amount.amount) &&
        isBlankMoney(payload.net_amount.amount);
      if (zero) return null;
      sequence += 1;
      const base =
        rows[0] ??
        entry({
          id: sequence,
          reporting_month_id: monthId,
          income_type: "salary",
          name: "Зарплата",
        });
      const replaced: IncomeEntry = {
        ...base,
        income_type: "salary",
        name: "Зарплата",
        gross_amount: { ...payload.gross_amount },
        tax_amount: { ...payload.tax_amount },
        net_amount: { ...payload.net_amount },
        is_recurring: true,
        include_in_cash_flow: true,
        include_in_passive_income: false,
      };
      store.push(replaced);
      return cloneEntry(replaced);
    });
});

type HarnessProps = {
  month: ReportingMonth;
  onDirty: (section: string, value: boolean) => void;
  onRefresh: () => void;
  refresh?: () => Promise<ReportingMonth>;
};

function Harness({ month, onDirty, onRefresh, refresh }: HarnessProps) {
  const [current, setCurrent] = useState(month);
  useEffect(() => setCurrent(month), [month]);
  const doRefresh = useCallback(async () => {
    onRefresh();
    const next = refresh ? await refresh() : current;
    setCurrent(next);
    return next;
  }, [current, onRefresh, refresh]);
  const context = useMemo<MonthEditorContext>(
    () => ({
      month: current,
      readOnly: current.status === "closed",
      refresh: doRefresh,
      setDirty: onDirty,
      returnToClose: null,
    }),
    [current, doRefresh, onDirty],
  );
  return <MonthIncomeSection context={context} />;
}

function renderSection(
  options: { month?: ReportingMonth; refresh?: () => Promise<ReportingMonth> } = {},
) {
  const client = createQueryClient();
  const onDirty = vi.fn();
  const onRefresh = vi.fn();
  const view = render(
    <QueryClientProvider client={client}>
      <Harness
        month={options.month ?? draft}
        refresh={options.refresh}
        onDirty={onDirty}
        onRefresh={onRefresh}
      />
    </QueryClientProvider>,
  );
  const rerenderWithMonth = (month: ReportingMonth) =>
    view.rerender(
      <QueryClientProvider client={client}>
        <Harness month={month} refresh={options.refresh} onDirty={onDirty} onRefresh={onRefresh} />
      </QueryClientProvider>,
    );
  return { ...view, onDirty, onRefresh, rerenderWithMonth };
}

/** formatMoney separates groups with NBSP; testing-library string matchers do not normalize it. */
function moneyText(expected: string) {
  return (content: string) => content.replace(/\s/g, " ") === expected.replace(/\s/g, " ");
}

/** Captures the beforeEach store-backed create implementation for failure-injection wrappers. */
function baseCreateMock() {
  const implementation = vi.mocked(createIncome).getMockImplementation();
  if (!implementation) throw new Error("createIncome base mock is missing");
  return implementation;
}

/** Resolves once the section finished loading its canonical data. */
async function readySection(): Promise<HTMLElement> {
  const section = await screen.findByRole("region", { name: "Зарплата и прочее" });
  await within(section).findByLabelText("Зарплата до вычета налогов");
  return section;
}

async function editAndSave(section: HTMLElement, label: string, value: string) {
  const user = userEvent.setup();
  await user.type(within(section).getByLabelText(label), value);
  await user.click(within(section).getByRole("button", { name: "Сохранить доходы" }));
}

describe("native month editor income leaf", () => {
  it("loads canonical income values and keeps null, empty and explicit zero apart", async () => {
    store = [
      entry({
        id: 1,
        income_type: "salary",
        name: "Зарплата",
        gross_amount: money("100000.00"),
        tax_amount: money("13000.00"),
        net_amount: money("87000.00"),
      }),
      entry({
        id: 5,
        income_type: "side_income",
        name: "Подработка",
        gross_amount: money("0.00"),
        net_amount: money("0.00"),
      }),
    ];
    summaryData = summaryFixture({ parts: [{ rate_bps: 1300 }] });

    const { onDirty } = renderSection();
    const section = await readySection();

    await waitFor(() => {
      expect(within(section).getByLabelText("Зарплата до вычета налогов")).toHaveValue(
        formatMoneyInput("100000.00"),
      );
      expect(within(section).getByLabelText("Фактическая зарплата после налогов")).toHaveValue(
        formatMoneyInput("87000.00"),
      );
      expect(within(section).getByLabelText("Дополнительный доход")).toHaveValue(
        formatMoneyInput("0.00"),
      );
      expect(within(section).getByLabelText("Премия")).toHaveValue("");
      expect(within(section).getByLabelText("Кэшбэк (не пассивный доход)")).toHaveValue("");
    });
    expect(within(section).getByText(moneyText(formatMoney("13000.00")))).toBeInTheDocument();
    expect(within(section).getByText(moneyText(formatMoney("87000.00")))).toBeInTheDocument();
    expect(within(section).getByText("13%")).toBeInTheDocument();
    expect(within(section).getByRole("button", { name: "О расчётном налоге" })).toBeInTheDocument();
    expect(within(section).getByText("Расчётный налог")).toBeInTheDocument();
    expect(within(section).getByText("Расчётный net")).toBeInTheDocument();
    expect(listIncomes).toHaveBeenCalledWith(7, expect.any(AbortSignal));
    expect(getMonthSummary).toHaveBeenCalledWith(7, expect.any(AbortSignal));
    expect(onDirty).not.toHaveBeenCalledWith("income", true);
    expect(within(section).getByRole("button", { name: "Сохранить доходы" })).toBeDisabled();
  });

  it("creates missing lines with exact legacy payloads, confirms readback and reloads", async () => {
    const first = renderSection();
    const section = await readySection();
    const user = userEvent.setup();
    await user.type(within(section).getByLabelText("Зарплата до вычета налогов"), "100000");
    await user.type(within(section).getByLabelText("Фактическая зарплата после налогов"), "87000");
    await user.type(within(section).getByLabelText("Премия"), "5000");
    await user.click(within(section).getByRole("button", { name: "Сохранить доходы" }));

    expect(
      await within(section).findByText("Доходы сохранены и подтверждены."),
    ).toBeInTheDocument();
    expect(replaceSalaryIncome).toHaveBeenCalledWith(7, {
      gross_amount: money("100000.00"),
      tax_amount: money("13000.00"),
      net_amount: money("87000.00"),
    });
    expect(createIncome).toHaveBeenCalledTimes(1);
    expect(createIncome).toHaveBeenCalledWith({
      reporting_month_id: 7,
      income_type: "bonus",
      name: "Премия",
      gross_amount: money("5000.00"),
      tax_amount: money("0.00"),
      net_amount: money("5000.00"),
      is_recurring: false,
      include_in_cash_flow: true,
      include_in_passive_income: false,
    });
    expect(updateIncome).not.toHaveBeenCalled();
    expect(deleteIncome).not.toHaveBeenCalled();
    expect(first.onRefresh).toHaveBeenCalledTimes(1);
    expect(first.onDirty).toHaveBeenCalledWith("income", true);
    expect(first.onDirty.mock.calls.at(-1)).toEqual(["income", false]);
    await waitFor(() =>
      expect(within(section).getByLabelText("Премия")).toHaveValue(formatMoneyInput("5000.00")),
    );

    first.unmount();
    renderSection();
    const reloaded = await readySection();
    await waitFor(() => {
      expect(within(reloaded).getByLabelText("Зарплата до вычета налогов")).toHaveValue(
        formatMoneyInput("100000.00"),
      );
      expect(within(reloaded).getByLabelText("Премия")).toHaveValue(formatMoneyInput("5000.00"));
    });
  });

  it("updates and deletes existing lines while keeping the untouched salary exact", async () => {
    store = [
      entry({
        id: 1,
        income_type: "salary",
        name: "Зарплата",
        gross_amount: money("90000.00"),
        tax_amount: money("11700.00"),
        net_amount: money("78300.00"),
      }),
      entry({
        id: 2,
        income_type: "bonus",
        name: "Премия",
        gross_amount: money("5000.00"),
        net_amount: money("5000.00"),
      }),
      entry({
        id: 3,
        income_type: "cashback",
        name: "Кэшбэк",
        gross_amount: money("300.00"),
        net_amount: money("300.00"),
      }),
      entry({
        id: 4,
        income_type: "side_income",
        name: "Подработка",
        gross_amount: money("0.00"),
        net_amount: money("0.00"),
      }),
    ];
    summaryData = summaryFixture({ tax: "11700.00", calculatedNet: "78300.00" });

    const { onDirty } = renderSection();
    const section = await readySection();
    const user = userEvent.setup();
    await user.clear(within(section).getByLabelText("Премия"));
    await user.clear(within(section).getByLabelText("Дополнительный доход"));
    await user.type(within(section).getByLabelText("Дополнительный доход"), "200");
    await user.clear(within(section).getByLabelText("Кэшбэк (не пассивный доход)"));
    await user.type(within(section).getByLabelText("Кэшбэк (не пассивный доход)"), "0");
    await user.click(within(section).getByRole("button", { name: "Сохранить доходы" }));

    expect(
      await within(section).findByText("Доходы сохранены и подтверждены."),
    ).toBeInTheDocument();
    expect(replaceSalaryIncome).toHaveBeenCalledWith(7, {
      gross_amount: money("90000.00"),
      tax_amount: money("11700.00"),
      net_amount: money("78300.00"),
    });
    expect(deleteIncome).toHaveBeenCalledTimes(2);
    expect(deleteIncome).toHaveBeenCalledWith(2);
    expect(deleteIncome).toHaveBeenCalledWith(3);
    expect(updateIncome).toHaveBeenCalledTimes(1);
    expect(updateIncome).toHaveBeenCalledWith(4, {
      name: "Подработка",
      income_type: "side_income",
      gross_amount: money("200.00"),
      tax_amount: money("0.00"),
      net_amount: money("200.00"),
      include_in_passive_income: false,
    });
    expect(createIncome).not.toHaveBeenCalled();
    expect(onDirty.mock.calls.at(-1)).toEqual(["income", false]);
    await waitFor(() => {
      expect(within(section).getByLabelText("Премия")).toHaveValue("");
      expect(within(section).getByLabelText("Кэшбэк (не пассивный доход)")).toHaveValue("");
      expect(within(section).getByLabelText("Дополнительный доход")).toHaveValue(
        formatMoneyInput("200.00"),
      );
    });
  });

  it("rejects invalid money before any write", async () => {
    const { onDirty } = renderSection();
    const section = await readySection();
    await editAndSave(section, "Премия", "abc");

    expect(await within(section).findByRole("alert")).toHaveTextContent(
      "Некорректная сумма: Премия",
    );
    expect(replaceSalaryIncome).not.toHaveBeenCalled();
    expect(createIncome).not.toHaveBeenCalled();
    expect(updateIncome).not.toHaveBeenCalled();
    expect(deleteIncome).not.toHaveBeenCalled();
    expect(within(section).queryByText("Доходы сохранены и подтверждены.")).not.toBeInTheDocument();
    expect(onDirty.mock.calls.at(-1)).toEqual(["income", true]);
  });

  it("keeps a failed save visible without claiming success", async () => {
    vi.mocked(replaceSalaryIncome).mockRejectedValueOnce(new Error("save failed"));
    const { onDirty } = renderSection();
    const section = await readySection();
    await editAndSave(section, "Премия", "5000");

    expect(await within(section).findByRole("alert")).toHaveTextContent("save failed");
    expect(within(section).queryByText("Доходы сохранены и подтверждены.")).not.toBeInTheDocument();
    const saveButton = within(section).getByRole("button", { name: "Сохранить доходы" });
    await waitFor(() => expect(saveButton).toBeEnabled());
    expect(within(section).getByLabelText("Премия")).toHaveValue(formatMoneyInput("5000"));
    expect(onDirty.mock.calls.at(-1)).toEqual(["income", true]);
  });

  it("treats a readback that does not match the writes as an unconfirmed save", async () => {
    renderSection();
    const section = await readySection();
    const user = userEvent.setup();
    await user.type(within(section).getByLabelText("Премия"), "5000");
    vi.mocked(listIncomes).mockImplementationOnce(async () => []);
    await user.click(within(section).getByRole("button", { name: "Сохранить доходы" }));

    expect(await within(section).findByRole("alert")).toHaveTextContent(
      "Сохранение не подтверждено повторной загрузкой данных.",
    );
    expect(within(section).queryByText("Доходы сохранены и подтверждены.")).not.toBeInTheDocument();
    expect(within(section).getByLabelText("Премия")).toHaveValue(formatMoneyInput("5000"));
    expect(createIncome).toHaveBeenCalledTimes(1);
  });

  it("does not run a second write from a repeat click while saving", async () => {
    const gate = deferred<IncomeEntry | null>();
    vi.mocked(replaceSalaryIncome).mockImplementation(() => gate.promise);
    renderSection();
    const section = await readySection();
    const user = userEvent.setup();
    await user.type(within(section).getByLabelText("Премия"), "5000");
    await user.click(within(section).getByRole("button", { name: "Сохранить доходы" }));

    expect(await within(section).findByRole("button", { name: "Сохраняем…" })).toBeDisabled();
    fireEvent.click(within(section).getByRole("button", { name: "Сохраняем…" }));
    gate.resolve(null);

    expect(
      await within(section).findByText("Доходы сохранены и подтверждены."),
    ).toBeInTheDocument();
    expect(replaceSalaryIncome).toHaveBeenCalledTimes(1);
    expect(createIncome).toHaveBeenCalledTimes(1);
  });

  it("reports the canonical closed-month conflict without a false success", async () => {
    vi.mocked(replaceSalaryIncome).mockRejectedValueOnce(
      new ApiClientError(409, {
        code: "conflict",
        message: "month was closed concurrently",
        details: [],
      }),
    );
    renderSection();
    const section = await readySection();
    await editAndSave(section, "Премия", "5000");

    expect(await within(section).findByRole("alert")).toHaveTextContent(
      "Операцию нельзя выполнить в текущем состоянии данных.",
    );
    expect(within(section).queryByText("Доходы сохранены и подтверждены.")).not.toBeInTheDocument();
  });

  it("never confirms a save when the month turns CLOSED during readback", async () => {
    const { onDirty } = renderSection({
      refresh: async () => ({ ...draft, status: "closed" }),
    });
    const section = await readySection();
    await editAndSave(section, "Премия", "5000");

    expect(await within(section).findByRole("alert")).toHaveTextContent(
      "Месяц закрыт во время сохранения. Данные не подтверждены.",
    );
    expect(within(section).queryByText("Доходы сохранены и подтверждены.")).not.toBeInTheDocument();
    expect(
      within(section).queryByRole("button", { name: "Сохранить доходы" }),
    ).not.toBeInTheDocument();
    await waitFor(() => expect(within(section).getByLabelText("Премия")).toBeDisabled());
    expect(onDirty.mock.calls.at(-1)).toEqual(["income", true]);
  });

  it("drops pending edits and stale confirmations when another month is selected", async () => {
    const gate = deferred<IncomeEntry | null>();
    vi.mocked(replaceSalaryIncome).mockImplementation(() => gate.promise);
    const view = renderSection();
    const section = await readySection();
    const user = userEvent.setup();
    await user.type(within(section).getByLabelText("Премия"), "5000");
    await user.click(within(section).getByRole("button", { name: "Сохранить доходы" }));
    expect(await within(section).findByRole("button", { name: "Сохраняем…" })).toBeInTheDocument();

    view.rerenderWithMonth(nextMonth);
    await waitFor(() => expect(view.onDirty.mock.calls.at(-1)).toEqual(["income", false]));

    gate.resolve(null);
    await waitFor(() => expect(createIncome).toHaveBeenCalledTimes(1));
    expect(createIncome).toHaveBeenCalledWith(expect.objectContaining({ reporting_month_id: 7 }));
    const reloaded = await readySection();
    await waitFor(() => expect(within(reloaded).getByLabelText("Премия")).toHaveValue(""));
    expect(screen.queryByText("Доходы сохранены и подтверждены.")).not.toBeInTheDocument();
    expect(view.onDirty.mock.calls.at(-1)).toEqual(["income", false]);
  });

  it("clears the dirty flag on unmount", async () => {
    const view = renderSection();
    const section = await readySection();
    const user = userEvent.setup();
    await user.type(within(section).getByLabelText("Премия"), "5000");
    expect(view.onDirty).toHaveBeenCalledWith("income", true);

    view.unmount();
    expect(view.onDirty.mock.calls.at(-1)).toEqual(["income", false]);
  });

  it("keeps a closed month read-only without any mutation call", async () => {
    renderSection({ month: { ...draft, status: "closed" } });
    const section = await screen.findByRole("region", { name: "Зарплата и прочее" });
    const input = await within(section).findByLabelText("Зарплата до вычета налогов");

    expect(input).toBeDisabled();
    expect(within(section).getByLabelText("Премия")).toBeDisabled();
    expect(
      within(section).queryByRole("button", { name: "Сохранить доходы" }),
    ).not.toBeInTheDocument();
    expect(
      within(section).getByText("Закрытый месяц доступен только для чтения."),
    ).toBeInTheDocument();
    expect(replaceSalaryIncome).not.toHaveBeenCalled();
    expect(createIncome).not.toHaveBeenCalled();
    expect(updateIncome).not.toHaveBeenCalled();
    expect(deleteIncome).not.toHaveBeenCalled();
  });

  it("blocks editing when the summary cannot be loaded and recovers on retry", async () => {
    vi.mocked(getMonthSummary).mockRejectedValueOnce(new Error("summary down"));
    renderSection();
    const section = await screen.findByRole("region", { name: "Зарплата и прочее" });

    expect(await within(section).findByRole("alert")).toHaveTextContent(
      "Не удалось загрузить данные: summary down",
    );
    expect(within(section).queryByLabelText("Зарплата до вычета налогов")).not.toBeInTheDocument();

    await userEvent.click(within(section).getByRole("button", { name: "Повторить загрузку" }));
    await waitFor(() =>
      expect(within(section).getByLabelText("Зарплата до вычета налогов")).toBeInTheDocument(),
    );
    expect(within(section).queryByRole("alert")).not.toBeInTheDocument();
    expect(within(section).getByRole("button", { name: "Сохранить доходы" })).toBeDisabled();
  });

  it("gates the retry until a partial save is reconciled and never duplicates the created row", async () => {
    store = [
      entry({
        id: 1,
        income_type: "salary",
        name: "Зарплата",
        gross_amount: money("100000.00"),
        tax_amount: money("13000.00"),
        net_amount: money("87000.00"),
      }),
    ];
    sequence = 1;

    // Bonus create commits; the following side-income create fails once.
    const baseCreate = baseCreateMock();
    let sideFailed = false;
    vi.mocked(createIncome).mockImplementation(async (payload, signal) => {
      if (payload.income_type === "side_income" && !sideFailed) {
        sideFailed = true;
        throw new ApiClientError(500, {
          code: "internal_error",
          message: "side create failed",
          details: [],
        });
      }
      return baseCreate(payload, signal);
    });
    // Hold the post-failure canonical re-read so the gated state is observable.
    const gateReconcile = deferred<void>();
    const baseList = vi.mocked(listIncomes).getMockImplementation();
    if (!baseList) throw new Error("listIncomes base mock is missing");
    let listReads = 0;
    vi.mocked(listIncomes).mockImplementation(async (monthId, signal) => {
      listReads += 1;
      if (listReads > 1) await gateReconcile.promise;
      return baseList(monthId, signal);
    });

    renderSection();
    const section = await readySection();
    const user = userEvent.setup();
    await user.type(within(section).getByLabelText("Премия"), "5000");
    await user.type(within(section).getByLabelText("Дополнительный доход"), "200");
    await user.click(within(section).getByRole("button", { name: "Сохранить доходы" }));

    // Partial outcome is reported, no success is claimed, the draft survives,
    // and the retry stays gated while the canonical re-read is pending.
    expect(await within(section).findByRole("alert")).toHaveTextContent(
      "Внутренняя ошибка приложения.",
    );
    expect(within(section).queryByText("Доходы сохранены и подтверждены.")).not.toBeInTheDocument();
    expect(
      within(section).getByText("Часть изменений могла сохраниться. Перечитываем данные месяца…"),
    ).toBeInTheDocument();
    expect(within(section).getByRole("button", { name: "Сохранить доходы" })).toBeDisabled();
    expect(within(section).getByLabelText("Премия")).toHaveValue(formatMoneyInput("5000"));
    expect(within(section).getByLabelText("Дополнительный доход")).toHaveValue(
      formatMoneyInput("200"),
    );
    expect(store.filter((row) => row.income_type === "bonus")).toHaveLength(1);
    expect(store.filter((row) => row.income_type === "side_income")).toHaveLength(0);

    gateReconcile.resolve();
    const saveButton = within(section).getByRole("button", { name: "Сохранить доходы" });
    await waitFor(() => expect(saveButton).toBeEnabled());
    expect(
      within(section).getByText(
        "Данные месяца перечитаны после сбоя. Проверь значения и сохрани ещё раз.",
      ),
    ).toBeInTheDocument();

    await user.click(saveButton);
    expect(
      await within(section).findByText("Доходы сохранены и подтверждены."),
    ).toBeInTheDocument();
    expect(within(section).queryByRole("alert")).not.toBeInTheDocument();

    // Exactly one create per successful type: the retry updates the persisted
    // bonus row; the failed side-income create is replayed exactly once.
    const createdTypes = vi.mocked(createIncome).mock.calls.map(([payload]) => payload.income_type);
    expect(createdTypes).toEqual(["bonus", "side_income", "side_income"]);
    expect(createdTypes.filter((type) => type === "bonus")).toHaveLength(1);
    expect(vi.mocked(updateIncome).mock.calls.map(([id]) => id)).toEqual([3]);
    expect(store.filter((row) => row.income_type === "bonus")).toHaveLength(1);
    expect(store.filter((row) => row.income_type === "side_income")).toHaveLength(1);
  });

  it("reconciles a persisted-but-timeout create and never re-creates it on retry", async () => {
    store = [
      entry({
        id: 1,
        income_type: "salary",
        name: "Зарплата",
        gross_amount: money("100000.00"),
        tax_amount: money("13000.00"),
        net_amount: money("87000.00"),
      }),
    ];
    sequence = 1;

    const baseCreate = baseCreateMock();
    let persisted = false;
    vi.mocked(createIncome).mockImplementation(async (payload, signal) => {
      if (payload.income_type === "bonus" && !persisted) {
        persisted = true;
        await baseCreate(payload, signal); // the row commits…
        throw new ApiClientError(0, { code: "network_error", message: "timed out", details: [] }); // …but the response is lost
      }
      return baseCreate(payload, signal);
    });

    renderSection();
    const section = await readySection();
    const user = userEvent.setup();
    await user.type(within(section).getByLabelText("Премия"), "5000");
    await user.click(within(section).getByRole("button", { name: "Сохранить доходы" }));

    expect(await within(section).findByRole("alert")).toHaveTextContent(
      "Не удалось подключиться к локальному приложению.",
    );
    expect(within(section).queryByText("Доходы сохранены и подтверждены.")).not.toBeInTheDocument();
    expect(store.filter((row) => row.income_type === "bonus")).toHaveLength(1);
    expect(within(section).getByLabelText("Премия")).toHaveValue(formatMoneyInput("5000"));

    const saveButton = within(section).getByRole("button", { name: "Сохранить доходы" });
    await waitFor(() => expect(saveButton).toBeEnabled());
    await user.click(saveButton);
    expect(
      await within(section).findByText("Доходы сохранены и подтверждены."),
    ).toBeInTheDocument();

    const bonusCreates = vi
      .mocked(createIncome)
      .mock.calls.filter(([payload]) => payload.income_type === "bonus");
    expect(bonusCreates).toHaveLength(1);
    expect(vi.mocked(updateIncome).mock.calls.map(([id]) => id)).toEqual([3]);
    expect(store.filter((row) => row.income_type === "bonus")).toHaveLength(1);
    expect(within(section).queryByRole("alert")).not.toBeInTheDocument();
  });

  it("keeps retry gated while the reconciliation read fails and the draft survives", async () => {
    store = [
      entry({
        id: 1,
        income_type: "salary",
        name: "Зарплата",
        gross_amount: money("100000.00"),
        tax_amount: money("13000.00"),
        net_amount: money("87000.00"),
      }),
    ];
    sequence = 1;

    renderSection();
    const section = await readySection();
    vi.mocked(replaceSalaryIncome).mockRejectedValueOnce(new Error("save failed"));
    vi.mocked(listIncomes).mockRejectedValueOnce(
      new ApiClientError(0, { code: "network_error", message: "reconcile down", details: [] }),
    );
    const user = userEvent.setup();
    await user.type(within(section).getByLabelText("Премия"), "5000");
    await user.click(within(section).getByRole("button", { name: "Сохранить доходы" }));

    expect(
      await within(section).findByRole("button", { name: "Перечитать данные" }),
    ).toBeInTheDocument();
    expect(within(section).getByText("save failed")).toBeInTheDocument();
    expect(within(section).getByText(/Не удалось перечитать данные месяца/)).toBeInTheDocument();
    expect(within(section).queryByText("Доходы сохранены и подтверждены.")).not.toBeInTheDocument();

    const saveButton = within(section).getByRole("button", { name: "Сохранить доходы" });
    expect(saveButton).toBeDisabled();
    expect(within(section).getByLabelText("Премия")).toHaveValue(formatMoneyInput("5000"));
    expect(replaceSalaryIncome).toHaveBeenCalledTimes(1);
    expect(createIncome).not.toHaveBeenCalled();

    await user.click(within(section).getByRole("button", { name: "Перечитать данные" }));
    await waitFor(() => expect(saveButton).toBeEnabled());
    await user.click(saveButton);
    expect(
      await within(section).findByText("Доходы сохранены и подтверждены."),
    ).toBeInTheDocument();

    expect(replaceSalaryIncome).toHaveBeenCalledTimes(2);
    expect(createIncome).toHaveBeenCalledTimes(1);
    expect(store.filter((row) => row.income_type === "bonus")).toHaveLength(1);
    expect(store.filter((row) => row.income_type === "salary")).toHaveLength(1);
    expect(within(section).queryByRole("alert")).not.toBeInTheDocument();
  });
});
