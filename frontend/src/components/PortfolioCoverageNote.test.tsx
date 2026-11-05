import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { listAccounts } from "../api/accounts";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

vi.mock("../api/accounts", () => ({ listAccounts: vi.fn() }));
function wrapper({ children }: { children: React.ReactNode }) {
  return (
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      {children}
    </QueryClientProvider>
  );
}

import { PortfolioCoverageNote } from "./PortfolioCoverageNote";

it("keeps complete coverage quiet and explains partial known capital", () => {
  const complete = { status: "complete" as const, reason_codes: [], missing_account_ids: [] };
  const { rerender } = render(<PortfolioCoverageNote coverage={complete} />, { wrapper });
  expect(screen.queryByTestId("portfolio-coverage-note")).toBeNull();
  rerender(
    <PortfolioCoverageNote
      coverage={{
        status: "partial",
        reason_codes: ["active_account_snapshot_missing", "another_quality_reason"],
        missing_account_ids: [2],
      }}
    />,
  );
  expect(screen.getByTestId("portfolio-coverage-note")).toHaveTextContent(
    "Частично: нет снимка счёта",
  );
  expect(screen.getByTestId("portfolio-coverage-note")).not.toHaveAttribute("title");
  fireEvent.click(screen.getByRole("button", { name: "Подробнее" }));
  expect(screen.getByText(/Не хватает снимка/)).toBeVisible();
  expect(screen.getByRole("link", { name: "Открыть капитал" })).toHaveAttribute(
    "href",
    "/v2/capital",
  );
});

it("names known missing accounts for the month and keeps unknown names honest", async () => {
  vi.mocked(listAccounts).mockResolvedValue([
    { id: 2, name: "Синтетический счёт А" },
    { id: 3, name: "Синтетический счёт Б" },
  ] as Awaited<ReturnType<typeof listAccounts>>);
  const { rerender } = render(
    <PortfolioCoverageNote
      month={{ year: 2031, month: 3 }}
      coverage={{
        status: "partial",
        reason_codes: ["active_account_snapshot_missing"],
        missing_account_ids: [2, 3],
      }}
    />,
    { wrapper },
  );
  fireEvent.click(screen.getByRole("button", { name: "Подробнее" }));
  expect(await screen.findByText(/Синтетический счёт А, Синтетический счёт Б/)).toHaveTextContent(
    "2031",
  );
  rerender(
    <PortfolioCoverageNote
      month={{ year: 2031, month: 3 }}
      coverage={{
        status: "partial",
        reason_codes: ["active_account_snapshot_missing"],
        missing_account_ids: [2, 99],
      }}
    />,
  );
  expect(screen.getByText(/Синтетический счёт А/)).toHaveTextContent(
    "название другого счёта неизвестно",
  );
  expect(screen.getByText(/Синтетический счёт А/)).not.toHaveTextContent("99");
});

it("uses neutral text when account names are unavailable", async () => {
  vi.mocked(listAccounts).mockRejectedValue(new Error("offline"));
  render(
    <PortfolioCoverageNote
      coverage={{
        status: "partial",
        reason_codes: ["active_account_snapshot_missing"],
        missing_account_ids: [2],
      }}
    />,
    { wrapper },
  );
  fireEvent.click(screen.getByRole("button", { name: "Подробнее" }));
  expect(await screen.findByText(/название счёта неизвестно/)).toBeVisible();
});
