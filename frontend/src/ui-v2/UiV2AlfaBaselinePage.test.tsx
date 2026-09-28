import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { beforeEach, expect, it, vi } from "vitest";
import { listAccounts } from "../api/accounts";
import { listInstruments } from "../api/instruments";
import { getCloseReadiness, getMonth, listMonths } from "../api/months";
import { listPositions } from "../api/positions";
import type { CloseReadiness, PositionSnapshot, ReportingMonth } from "../api/types";
import { createQueryClient } from "../queryClient";
import UiV2AlfaBaselinePage from "./UiV2AlfaBaselinePage";

vi.mock("../api/accounts", () => ({ listAccounts: vi.fn() }));
vi.mock("../api/instruments", () => ({ listInstruments: vi.fn() }));
vi.mock("../api/months", () => ({
  listMonths: vi.fn(),
  getMonth: vi.fn(),
  getCloseReadiness: vi.fn(),
}));
vi.mock("../api/positions", () => ({ listPositions: vi.fn() }));
vi.mock("../components/BrokerSnapshotPanel", () => ({
  BrokerSnapshotPanel: ({ initialMonthId }: { initialMonthId: number }) => (
    <div>Canonical panel month {initialMonthId}</div>
  ),
}));

const month = {
  id: 7,
  year: 2026,
  month: 8,
  status: "draft",
  snapshot_date: "2026-08-31",
  source: "manual",
} as ReportingMonth;
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(listMonths).mockResolvedValue([month]);
  vi.mocked(getMonth).mockResolvedValue(month);
  vi.mocked(listAccounts).mockResolvedValue([]);
  vi.mocked(listInstruments).mockResolvedValue([]);
  vi.mocked(listPositions).mockResolvedValue([]);
  vi.mocked(getCloseReadiness).mockResolvedValue({
    ...month,
    can_close: false,
    items: [],
  } as CloseReadiness);
});
function show(query: string) {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={[`/v2/data/alfa-baseline${query}`]}>
        <UiV2AlfaBaselinePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
it("uses the exact month and preserves query/hash in Data navigation", async () => {
  show("?month=7&from=monthly-close-v2&monthId=7&step=alfa_baseline&scope=synthetic#target");
  expect(await screen.findByText("Canonical panel month 7")).toBeInTheDocument();
  expect(getMonth).toHaveBeenCalledWith(7);
  expect(screen.getByRole("link", { name: "Вернуться к закрытию" })).toHaveAttribute(
    "href",
    "/v2/close?month=7&step=alfa_baseline",
  );
  expect(screen.getByRole("link", { name: /^Файлы$/ })).toHaveAttribute(
    "href",
    "/v2/data/files?month=7&from=monthly-close-v2&monthId=7&step=alfa_baseline&scope=synthetic#target",
  );
});
it.each([
  "",
  "?month=",
  "?month=bad",
  "?month=999",
  "?month=7&month=7",
  "?month=07",
  "?month=9007199254740992",
])("rejects invalid explicit scope %s", async (query) => {
  show(query);
  expect(await screen.findByText("Месяц не выбран")).toBeInTheDocument();
  expect(screen.queryByText(/Canonical panel month/)).not.toBeInTheDocument();
  expect(getMonth).not.toHaveBeenCalled();
});
it("mounts the tool only after the Owner explicitly selects a month", async () => {
  const user = userEvent.setup();
  show("?from=monthly-close-v2&monthId=7&step=alfa_baseline#target");
  expect(await screen.findByText("Месяц не выбран")).toBeInTheDocument();
  expect(screen.queryByText(/Canonical panel month/)).not.toBeInTheDocument();
  await user.selectOptions(screen.getByLabelText("Месяц базового среза"), "7");
  expect(await screen.findByText("Canonical panel month 7")).toBeInTheDocument();
  expect(getMonth).toHaveBeenCalledWith(7);
  expect(screen.getByRole("link", { name: /^Файлы$/ })).toHaveAttribute(
    "href",
    "/v2/data/files?from=monthly-close-v2&monthId=7&step=alfa_baseline&month=7#target",
  );
});
it("does not present foreign-month rows as current or mount the write panel", async () => {
  vi.mocked(listPositions).mockResolvedValue([
    { id: 1, reporting_month_id: 8 },
  ] as PositionSnapshot[]);
  show("?month=7");
  expect(await screen.findByText("Актуальный результат не подтверждён")).toBeInTheDocument();
  expect(screen.queryByText("Canonical panel month 7")).not.toBeInTheDocument();
});
it("does not offer a return to a different close month", async () => {
  show("?month=7&from=monthly-close-v2&monthId=8&step=alfa_baseline");
  await screen.findByText("Canonical panel month 7");
  expect(screen.queryByRole("link", { name: "Вернуться к закрытию" })).not.toBeInTheDocument();
});
