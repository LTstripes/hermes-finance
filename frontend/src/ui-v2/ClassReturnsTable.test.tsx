import { QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ClassReturns } from "../api/types";
import { createQueryClient } from "../queryClient";
import { classReturnsFixture } from "../test/classReturnsFixture";
import UiV2CapitalPerformanceDetail from "./UiV2CapitalPerformanceDetail";

const START = "2031-05-31";
const END = "2031-07-31";
const PATH = `/v2/capital/performance?start=${START}&end=${END}&scope=portfolio&view=classes`;

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{location.search}</output>;
}

function setup(
  transform: (row: ClassReturns) => ClassReturns | Promise<ClassReturns> = (row) => row,
  path = PATH,
) {
  const reads: URL[] = [];
  const client = createQueryClient();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://localhost");
      reads.push(url);
      expect(init?.method).toBe("GET");
      if (url.pathname === "/api/accounts" || url.pathname === "/api/months")
        return new Response("[]");
      if (url.pathname !== "/api/performance/class-returns")
        throw new Error(`Unexpected API ${url.pathname}`);
      const row = await transform(
        classReturnsFixture(
          url.searchParams.get("asset_class") as string,
          url.searchParams.get("start_date") as string,
          url.searchParams.get("end_date") as string,
        ),
      );
      return new Response(JSON.stringify(row), { headers: { "Content-Type": "application/json" } });
    }),
  );
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <LocationProbe />
        <UiV2CapitalPerformanceDetail />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { reads, client };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("class returns in existing Performance detail", () => {
  it("reads just the four ordered classes; explains actual evidence without write actions", async () => {
    const { reads } = setup();
    const stock = await screen.findByTestId("class-return-stock");
    await waitFor(() => expect(stock).toHaveTextContent("+10,12%"));
    expect(stock).toHaveTextContent("+5,75%");
    const table = screen.getByRole("table");
    expect(
      within(table)
        .getAllByRole("rowheader")
        .map((el) => el.textContent),
    ).toEqual(["Акции", "Облигации", "Золото", "Депозиты"]);
    const deposit = screen.getByTestId("class-return-deposit");
    expect(deposit).toHaveTextContent("Расчёт не поддерживается");
    expect(deposit).not.toHaveTextContent("%");
    const user = userEvent.setup();
    const expand = within(stock).getByRole("button", { name: "Подробнее: Акции" });
    expand.focus();
    await user.keyboard("{Enter}");
    expect(expand).toHaveFocus();
    expect(expand).toHaveAttribute("aria-expanded", "true");
    const explanation = document.getElementById(expand.getAttribute("aria-controls") as string);
    expect(explanation).toBeVisible();
    expect(explanation).toHaveTextContent("31.05.2031 — 31.07.2031");
    expect(explanation).toHaveTextContent("Сохранённая рыночная стоимость в RUB");
    expect(explanation).toHaveTextContent("Подтверждение владельца · версия 2");
    expect(explanation).toHaveTextContent("Полный состав на начало: подтверждён");
    expect(explanation).toHaveTextContent("Полный состав на конец: подтверждён");
    expect(reads.map((url) => url.pathname)).toEqual(
      Array(4).fill("/api/performance/class-returns"),
    );
    expect(screen.queryByText("Добавить операцию")).toBeNull();
    expect(screen.queryByText("Наблюдения PRE/POST")).toBeNull();
  });

  it("keeps XIRR visible independently, preserves zero/loss and separates undefined from solver limits", async () => {
    setup((row) => {
      if (row.asset_class === "stock") {
        row.xirr.value = "0";
        row.twrr = {
          ...row.twrr,
          availability: "not_computable",
          quality: "unavailable",
          value: null,
          reason_source: "solver",
          reason_codes: ["not_computable_twrr_zero_or_negative_denominator"],
        };
      }
      if (row.asset_class === "bond") {
        row.twrr.value = "-2.75";
        row.xirr = {
          ...row.xirr,
          availability: "not_computable",
          quality: "unavailable",
          value: null,
          reason_source: "solver",
          reason_codes: ["not_computable_xirr_root_ambiguity"],
        };
      }
      if (row.asset_class === "gold") row.xirr.value = "-100";
      return row;
    });
    await waitFor(() =>
      expect(screen.getByTestId("class-return-stock")).toHaveTextContent("0,00%"),
    );
    expect(screen.getByTestId("class-return-stock")).toHaveTextContent("Доходность не определена");
    expect(screen.getByTestId("class-return-bond")).toHaveTextContent("−2,75%");
    expect(screen.getByTestId("class-return-bond")).toHaveTextContent(
      "Ограничение расчётного метода",
    );
    expect(screen.getByTestId("class-return-gold")).toHaveTextContent("−100,00%");
    fireEvent.click(screen.getByRole("button", { name: "Подробнее: Облигации" }));
    expect(
      screen
        .getAllByText("Причины расчётного метода")
        .some((element) => !element.closest("[hidden]")),
    ).toBe(true);
    expect(screen.getByText(/Метод XIRR не может выбрать однозначный корень/)).toBeVisible();
    expect(screen.queryByText(/Добавьте.*операци/i)).toBeNull();
  });

  it.each([
    ["no_crossing_coverage_missing_or_ambiguous", "unknown", false, "Подтверждения неполны"],
    ["no_crossing_material_changed", "invalidated", true, "Подтверждения изменены или отозваны"],
    ["no_crossing_coverage_not_complete", "unknown", true, "Подтверждения изменены или отозваны"],
    ["no_crossing_coverage_not_complete", "revoked", true, "Подтверждения изменены или отозваны"],
    ["not_computable_xirr_no_valid_root", "complete", true, "Доходность не определена"],
    ["not_computable_xirr_convergence_failed", "complete", true, "Ограничение расчётного метода"],
  ])("maps exact reason %s and coverage %s", async (code, coverage, provenance, label) => {
    setup((row) => {
      if (row.asset_class !== "stock") return row;
      const solver =
        code === "not_computable_xirr_no_valid_root" ||
        code === "not_computable_xirr_convergence_failed";
      row.coverage_state = coverage;
      if (!provenance) row.coverage_provenance = [];
      if (!solver) {
        row.eligibility_status = "unavailable";
        row.evidence_reason_codes = [code];
      }
      for (const kind of ["xirr", "twrr"] as const)
        Object.assign(row[kind], {
          availability: "not_computable",
          quality: "unavailable",
          value: null,
          reason_source: solver ? "solver" : "evidence",
          reason_codes: [code],
        });
      return row;
    });
    await waitFor(() => expect(screen.getByTestId("class-return-stock")).toHaveTextContent(label));
    expect(screen.getByTestId("class-return-stock")).not.toHaveTextContent("%");
  });

  it.each(["class", "requested", "actual", "currency", "unit", "annualized"])(
    "rejects a mismatched %s response",
    async (mismatch) => {
      setup((row) => {
        if (row.asset_class !== "stock") return row;
        if (mismatch === "class") row.asset_class = "gold";
        if (mismatch === "requested") row.requested_period.start_date = "2030-01-01";
        if (mismatch === "actual") row.actual_covered_period.end_date = "2031-06-30";
        if (mismatch === "currency") row.performance_currency = "USD";
        if (mismatch === "unit") Object.assign(row.xirr, { value_unit: "fraction" });
        if (mismatch === "annualized") Object.assign(row.twrr, { annualized: true });
        return row;
      });
      await waitFor(() =>
        expect(screen.getByTestId("class-return-stock")).toHaveTextContent(
          "Ответ не соответствует",
        ),
      );
      expect(screen.getByTestId("class-return-stock")).not.toHaveTextContent("10,12%");
      expect(screen.queryByRole("button", { name: "Подробнее: Акции" })).toBeNull();
    },
  );

  it("does not silently coerce account URLs; portfolio action preserves exact dates", async () => {
    const { reads } = setup(
      (row) => row,
      PATH.replace("scope=portfolio", "scope=account&account_id=77"),
    );
    expect(screen.getByText("По классам — только весь портфель")).toBeVisible();
    expect(reads).toEqual([]);
    expect(screen.getByTestId("location")).toHaveTextContent("account_id=77");
    fireEvent.click(screen.getByRole("button", { name: "Перейти к классам портфеля" }));
    await waitFor(() =>
      expect(screen.getByTestId("class-return-stock")).toHaveTextContent("+10,12%"),
    );
    expect(screen.getByTestId("location")).toHaveTextContent(
      `start=${START}&end=${END}&scope=portfolio`,
    );
    expect(screen.getByTestId("location")).not.toHaveTextContent("account_id");
  });

  it("hides old values during a period change and ignores delayed old responses", async () => {
    let release: ((row: ClassReturns) => void) | undefined;
    const { client } = setup((row) =>
      row.asset_class === "stock" && row.requested_period.start_date === START
        ? new Promise((resolve) => {
            release = resolve;
          })
        : { ...row, xirr: { ...row.xirr, value: row.asset_class === "deposit" ? null : "21" } },
    );
    await waitFor(() => expect(release).toBeDefined());
    fireEvent.change(screen.getByLabelText("Начальная дата снимка"), {
      target: { value: "2031-06-30" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Применить даты" }));
    await waitFor(() =>
      expect(screen.getByTestId("class-return-stock")).toHaveTextContent("+21,00%"),
    );
    release?.(classReturnsFixture("stock", START, END));
    await waitFor(() => expect(client.isFetching()).toBe(0));
    expect(screen.getByTestId("class-return-stock")).toHaveTextContent("+21,00%");
    expect(screen.getByTestId("class-return-stock")).not.toHaveTextContent("10,12%");
  });

  it("hides cached percentages during refetch and retries transport errors without evidence copy", async () => {
    let fail = false;
    const { client } = setup((row) => {
      if (fail && row.asset_class === "stock") throw new Error("network");
      return row;
    });
    await waitFor(() =>
      expect(screen.getByTestId("class-return-stock")).toHaveTextContent("+10,12%"),
    );
    fail = true;
    await client.invalidateQueries({ queryKey: ["class-returns", "stock"] });
    await waitFor(() =>
      expect(screen.getByTestId("class-return-stock")).toHaveTextContent("сетевая ошибка"),
    );
    expect(screen.getByTestId("class-return-stock")).not.toHaveTextContent("10,12%");
    expect(screen.getByTestId("class-return-stock")).not.toHaveTextContent("Подтверждения неполны");
    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "Повторить: Акции" }));
    await waitFor(() =>
      expect(screen.getByTestId("class-return-stock")).toHaveTextContent("+10,12%"),
    );
  });
});
