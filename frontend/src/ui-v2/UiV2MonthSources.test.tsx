import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router";
import { afterEach, expect, it, vi } from "vitest";
import type { SourceIntake } from "../api/sourceIntake";
import { uiV2Months } from "../test/uiV2Fixtures";
import { UiV2MonthSources } from "./UiV2MonthSources";

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
function mount(path = "/v2/close?month=12&step=readiness", closed = false) {
  const onReview = vi.fn();
  const fetcher = vi.fn(
    async () =>
      new Response(
        JSON.stringify([
          intake(1, "ACCOUNT-A"),
          intake(2, "ACCOUNT-B"),
          intake(3, "OTHER-PERIOD", { covered_from: "2031-07-01", covered_to: "2031-07-31" }),
          intake(4, "OTHER-MONTH", { state: { reporting_month_id: 91 } } as Partial<SourceIntake>),
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

it("keeps both accounts, calendar scope, precise review and the accepted bond link", async () => {
  const { onReview, fetcher } = mount();
  const list = await screen.findByRole("list", { name: "Источники и исключения месяца" });
  expect(list.children).toHaveLength(2);
  expect(list).not.toHaveTextContent("OTHER");
  expect(list).toHaveTextContent("Save не разрешает Close");
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
  expect(fetcher).toHaveBeenCalledTimes(1);
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
