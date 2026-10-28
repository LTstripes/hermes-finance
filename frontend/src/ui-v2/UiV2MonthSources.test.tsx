import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router";
import { afterEach, expect, it, vi } from "vitest";
import type { SourceIntake } from "../api/sourceIntake";
import { uiV2Months } from "../test/uiV2Fixtures";
import { UiV2MonthSources } from "./UiV2MonthSources";

vi.mock("../components/month-close/BrokerMonthReview", () => ({ BrokerMonthReview: () => null }));

function intake(id: number, account: string, patch: Partial<SourceIntake> = {}) {
  return {
    id,
    covered_from: "2031-08-01",
    covered_to: "2031-08-31",
    state: { reporting_month_id: null },
    document: { filename_account: account, source_accounts: [`${account}-native`] },
    observations: [{ id }],
    exceptions: ["identity_pending"],
    ...patch,
  };
}
function Location() {
  const location = useLocation();
  return <output data-testid="location">{location.search}</output>;
}
function mount(
  path = "/v2/close?month=12&step=readiness",
  closed = false,
  extras: ReturnType<typeof intake>[] = [],
) {
  const onReview = vi.fn();
  const fetcher = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) =>
    String(input).includes("/draft-payouts")
      ? new Response(
          JSON.stringify({
            reporting_month_id: 12,
            status: closed ? "closed" : "draft",
            context_digest: "a".repeat(64),
            eligible_positions: 0,
            items: [],
          }),
        )
      : String(input).includes("/payouts/calendar")
        ? new Response(JSON.stringify([]))
        : String(input).startsWith("/api/source-returns/monthly")
          ? new Response(JSON.stringify({ months: [] }), {
              headers: { "Content-Type": "application/json" },
            })
          : new Response(
              JSON.stringify([
                intake(1, "ACCOUNT-A"),
                intake(2, "ACCOUNT-B"),
                intake(3, "OTHER-PERIOD", { covered_from: "2031-07-01", covered_to: "2031-07-31" }),
                intake(4, "OTHER-MONTH", {
                  state: { reporting_month_id: 91 },
                } as Partial<SourceIntake>),
                ...extras,
              ]),
              { headers: { "Content-Type": "application/json" } },
            ),
  );
  vi.stubGlobal("fetch", fetcher);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Location />
        <UiV2MonthSources
          month={{ ...uiV2Months[1], status: closed ? "closed" : "draft" }}
          onReview={onReview}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { onReview, fetcher };
}
afterEach(() => vi.unstubAllGlobals());

it("distinguishes long historical overlap from a complete month and names the absent closing EOD", async () => {
  mount("/v2/close?month=12&source_account=LONG", false, [
    intake(5, "LONG", { covered_from: "2024-01-01", covered_to: "2031-08-04" }),
  ]);
  const status = await screen.findByRole("region", { name: "Состояние источников месяца" });
  await screen.findByRole("list", { name: "Источники и исключения месяца" });
  expect(status).toHaveTextContent(
    "Полных месячных оригиналов: 0. Исторических или частичных пересечений: 1",
  );
  expect(status).toHaveTextContent("остатки на 2031-08-31");
  expect(screen.getByRole("list", { name: "Источники и исключения месяца" })).toHaveTextContent(
    "Историческое или частичное пересечение",
  );
  expect(
    screen.getByText("Исправления и сохранение месяца").closest("details"),
  ).not.toHaveAttribute("open");
  fireEvent.click(screen.getByRole("button", { name: "Разобрать и исправить #5" }));
  expect(screen.getByText("Исправления и сохранение месяца").closest("details")).toHaveAttribute(
    "open",
  );
});

it("keeps both accounts, calendar scope, precise review and the accepted bond link", async () => {
  const { onReview, fetcher } = mount();
  const list = await screen.findByRole("list", { name: "Источники и исключения месяца" });
  expect(list.children).toHaveLength(2);
  expect(list).not.toHaveTextContent("OTHER");
  expect(list).toHaveTextContent("Без финансовой привязки");
  fireEvent.change(screen.getByLabelText("Счёт источника месяца"), {
    target: { value: "ACCOUNT-B" },
  });
  expect(list).toHaveTextContent("ACCOUNT-B");
  expect(list).not.toHaveTextContent("ACCOUNT-A");
  expect(screen.getByTestId("location")).toHaveTextContent(
    "month=12&step=readiness&source_account=ACCOUNT-B",
  );
  expect(screen.getByRole("link", { name: "Облигации и доходность · ACCOUNT-B" })).toHaveAttribute(
    "href",
    "/v2/capital/monthly-returns?source_account=ACCOUNT-B&bond_period=2031-08-01#bond-slice",
  );
  fireEvent.click(screen.getByRole("button", { name: "Разобрать и исправить #2" }));
  expect(onReview).toHaveBeenCalledWith(2);
  expect(fetcher.mock.calls.map(([url]) => String(url))).toContain(
    "/api/source-returns/monthly?source_account=ACCOUNT-B",
  );
  expect(fetcher.mock.calls.every(([, init]) => !init?.method || init.method === "GET")).toBe(true);
});

it.each(["source_account=MISSING", "source_account=ACCOUNT-A&source_account=ACCOUNT-B"])(
  "fails closed for explicit stale/duplicate account (%s)",
  async (query) => {
    mount(`/v2/close?month=12&${query}`);
    expect(await screen.findByRole("alert")).toHaveTextContent("не подтверждён");
    expect(screen.queryByRole("link", { name: /Облигации/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Разобрать/ })).not.toBeInTheDocument();
  },
);

it("offers read-only review and no upload for CLOSED", async () => {
  const { onReview } = mount("/v2/close?month=12", true);
  fireEvent.click(await screen.findByRole("button", { name: "Просмотреть разбор #1" }));
  expect(onReview).toHaveBeenCalledWith(1);
  expect(screen.queryByLabelText("XML-файлы")).not.toBeInTheDocument();
});

it("retains historical source-account selection without treating its original as this month's EOD", async () => {
  const { fetcher } = mount("/v2/close?month=12&source_account=OTHER-PERIOD");
  expect(await screen.findByRole("region", { name: "Состояние источников месяца" })).toBeVisible();
  expect(await screen.findByText(/Для выбранного счёта выписок этого периода нет/)).toBeVisible();
  expect(screen.getByRole("region", { name: "Состояние источников месяца" })).toHaveTextContent(
    "Полных месячных оригиналов: 0",
  );
  expect(screen.getByRole("link", { name: "Инструменты, сделки и выплаты" })).toHaveAttribute(
    "href",
    "#month-instruments",
  );
  expect(
    fetcher.mock.calls.some(([url]) =>
      String(url).includes("/api/source-returns/monthly?source_account=OTHER-PERIOD"),
    ),
  ).toBe(true);
  expect(fetcher.mock.calls.every(([, init]) => !init?.method || init.method === "GET")).toBe(true);
});
