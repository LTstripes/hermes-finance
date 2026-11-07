import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { listAccounts } from "../api/accounts";
import type { PortfolioSourceCoverage } from "../api/types";
import { PortfolioCoverageNote } from "./PortfolioCoverageNote";

vi.mock("../api/accounts", () => ({ listAccounts: vi.fn() }));

const accounts = [
  { id: 2, name: "Синтетический счёт А" },
  { id: 3, name: "Синтетический счёт Б" },
] as Awaited<ReturnType<typeof listAccounts>>;

function partial(ids: number[]): PortfolioSourceCoverage {
  return {
    status: "partial",
    reason_codes: ["active_account_snapshot_missing"],
    missing_account_ids: ids,
  };
}

function Wrapper({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () => new QueryClient({ defaultOptions: { queries: { retry: false } } }),
  );
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(listAccounts).mockResolvedValue(accounts);
});

it("keeps complete coverage quiet, including a confirmed zero", () => {
  render(
    <PortfolioCoverageNote
      coverage={{ status: "complete", reason_codes: [], missing_account_ids: [] }}
    />,
    { wrapper: Wrapper },
  );
  expect(screen.queryByTestId("portfolio-coverage-note")).toBeNull();
  expect(listAccounts).not.toHaveBeenCalled();
});

it("names one missing account in the warning and its month-specific details", async () => {
  render(<PortfolioCoverageNote coverage={partial([2])} month={{ year: 2031, month: 3 }} />, {
    wrapper: Wrapper,
  });
  const note = screen.getByTestId("portfolio-coverage-note");
  await waitFor(() =>
    expect(note).toHaveTextContent("Частично: нет снимка счёта: Синтетический счёт А"),
  );
  expect(note).not.toHaveAttribute("title");
  const button = within(note).getByRole("button", { name: "Подробнее" });
  expect(button).toHaveAttribute("aria-expanded", "false");
  fireEvent.click(button);
  expect(button).toHaveAttribute("aria-expanded", "true");
  expect(note).toHaveTextContent("Не хватает снимка за Март 2031: Синтетический счёт А");
  expect(within(note).getByRole("link", { name: "Открыть капитал" })).toHaveAttribute(
    "href",
    "/v2/capital",
  );
});

it("names several accounts and marks a missing or blank name as unknown", async () => {
  const { rerender } = render(<PortfolioCoverageNote coverage={partial([2, 3])} />, {
    wrapper: Wrapper,
  });
  const note = screen.getByTestId("portfolio-coverage-note");
  await waitFor(() => expect(note).toHaveTextContent("Синтетический счёт А, Синтетический счёт Б"));
  fireEvent.click(within(note).getByRole("button", { name: "Подробнее" }));
  expect(note.textContent?.match(/Синтетический счёт А, Синтетический счёт Б/g)).toHaveLength(2);

  rerender(<PortfolioCoverageNote coverage={partial([2, 999999])} />);
  expect(note).toHaveTextContent("Синтетический счёт А; название другого счёта неизвестно");
  expect(note).not.toHaveTextContent("999999");
});

it("preserves unknown names for an empty list, blank names, and failed account reads", async () => {
  const { rerender } = render(<PortfolioCoverageNote coverage={partial([])} />, {
    wrapper: Wrapper,
  });
  const note = screen.getByTestId("portfolio-coverage-note");
  expect(note).toHaveTextContent("название счёта неизвестно");
  expect(listAccounts).not.toHaveBeenCalled();
  rerender(<PortfolioCoverageNote coverage={partial([2])} />);
  await waitFor(() => expect(note).toHaveTextContent("Синтетический счёт А"));

  const blankClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  blankClient.setQueryData(["accounts"], [{ id: 2, name: "   " }]);
  const blank = render(
    <QueryClientProvider client={blankClient}>
      <PortfolioCoverageNote coverage={partial([2])} />
    </QueryClientProvider>,
  );
  expect(within(blank.container).getByTestId("portfolio-coverage-note")).toHaveTextContent(
    "название счёта неизвестно",
  );
  blank.unmount();

  vi.mocked(listAccounts).mockRejectedValue(new Error("offline"));
  const failed = render(<PortfolioCoverageNote coverage={partial([999999])} />, {
    wrapper: Wrapper,
  });
  const failedNote = within(failed.container).getByTestId("portfolio-coverage-note");
  await waitFor(() => expect(failedNote).toHaveTextContent("название счёта неизвестно"));
  fireEvent.click(within(failedNote).getByRole("button", { name: "Подробнее" }));
  expect(failedNote).not.toHaveTextContent("999999");
});

it("keeps pending source and missing snapshot reasons separate", async () => {
  const coverage: PortfolioSourceCoverage = {
    ...partial([2]),
    source_account_financial_coverage: {
      status: "partial",
      reason_codes: [],
      account_ids: [],
      intake_count: 1,
    },
  };
  render(<PortfolioCoverageNote coverage={coverage} />, { wrapper: Wrapper });
  const note = screen.getByTestId("portfolio-coverage-note");
  await waitFor(() => expect(note).toHaveTextContent("нет снимка счёта: Синтетический счёт А"));
  expect(note).toHaveTextContent("разбор источника не завершён");
  fireEvent.click(within(note).getByRole("button", { name: "Подробнее" }));
  expect(note).toHaveTextContent("Разбор данных источника не завершён");
});

it("does not assume an unidentified comparison period refers to a different account", async () => {
  render(
    <PortfolioCoverageNote coverage={partial([])} relatedCoverages={[partial([2]), partial([])]} />,
    { wrapper: Wrapper },
  );
  const note = screen.getByTestId("portfolio-coverage-note");
  await waitFor(() => expect(note).toHaveTextContent("Синтетический счёт А"));
  expect(note).toHaveTextContent("счёт для части данных не уточнён");
  expect(note).not.toHaveTextContent("другого счёта");
});

it("names known missing accounts when all capital snapshots are unavailable", async () => {
  render(
    <PortfolioCoverageNote
      coverage={{
        status: "unavailable",
        reason_codes: ["portfolio_snapshot_missing"],
        missing_account_ids: [2, 3],
      }}
    />,
    { wrapper: Wrapper },
  );
  const note = screen.getByTestId("portfolio-coverage-note");
  await waitFor(() => expect(note).toHaveTextContent("Синтетический счёт А, Синтетический счёт Б"));
  expect(note).toHaveTextContent("Нет снимков капитала");
  expect(within(note).queryByRole("button", { name: "Подробнее" })).toBeNull();
});

it("uses the current missing IDs when an account request finishes after coverage changes", async () => {
  let resolveAccounts!: (value: typeof accounts) => void;
  vi.mocked(listAccounts).mockReturnValue(
    new Promise((resolve) => {
      resolveAccounts = resolve;
    }),
  );
  const { rerender } = render(<PortfolioCoverageNote coverage={partial([2])} />, {
    wrapper: Wrapper,
  });
  const note = screen.getByTestId("portfolio-coverage-note");
  expect(note).not.toHaveTextContent("неизвестно");
  rerender(<PortfolioCoverageNote coverage={partial([3])} />);
  await act(async () => resolveAccounts(accounts));
  await waitFor(() => expect(note).toHaveTextContent("Синтетический счёт Б"));
  expect(note).not.toHaveTextContent("Синтетический счёт А");
});
