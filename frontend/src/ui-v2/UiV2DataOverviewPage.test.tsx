import { QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { listAccounts } from "../api/accounts";
import { createBackup, listBackups } from "../api/backups";
import { getHealth } from "../api/health";
import { listInstruments } from "../api/instruments";
import type { BackupMetadata } from "../api/types";
import { createQueryClient, queryKeys } from "../queryClient";
import { uiV2Accounts, uiV2Instruments } from "../test/uiV2Fixtures";
import UiV2DataOverviewPage from "./UiV2DataOverviewPage";

vi.mock("../api/accounts", () => ({ listAccounts: vi.fn() }));
vi.mock("../api/backups", () => ({ listBackups: vi.fn(), createBackup: vi.fn() }));
vi.mock("../api/instruments", () => ({ listInstruments: vi.fn() }));
vi.mock("../api/health", () => ({ getHealth: vi.fn() }));

const backup: BackupMetadata = {
  id: "synthetic-copy",
  name: "synthetic-copy.db",
  created_at: "2031-08-20T10:00:00Z",
  size_bytes: 1024,
  source_database: { name: "synthetic.db", size_bytes: 1024 },
};

function mount() {
  const client = createQueryClient();
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/v2/data/overview?month=12"]}>
        <UiV2DataOverviewPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return client;
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 404 })));
  vi.mocked(listBackups).mockResolvedValue([]);
  vi.mocked(listAccounts).mockResolvedValue(uiV2Accounts);
  vi.mocked(listInstruments).mockResolvedValue(uiV2Instruments);
  vi.mocked(getHealth).mockResolvedValue({ status: "ok", version: "0.0.0-test" });
});
afterEach(() => vi.unstubAllGlobals());

it("shows five cards from existing reads, preserves month and performs no writes on entry", async () => {
  mount();
  expect(await screen.findByText("Резервных копий пока нет")).toBeVisible();
  expect(screen.getAllByRole("heading", { level: 2 })).toHaveLength(5);
  expect(
    screen.getByText(`Счетов: ${uiV2Accounts.length} · инструментов: ${uiV2Instruments.length}`),
  ).toBeVisible();
  expect(screen.getByText("Версия 0.0.0-test")).toBeVisible();
  expect(screen.getByRole("link", { name: "Подготовить отчёт →" })).toHaveAttribute(
    "href",
    "/v2/data/files?month=12#files-exports-title",
  );
  expect(createBackup).not.toHaveBeenCalled();
});

it("creates one copy on explicit action and shows the confirmed newest date", async () => {
  let resolve!: (value: BackupMetadata) => void;
  vi.mocked(createBackup).mockImplementation(
    () =>
      new Promise((done) => {
        resolve = done;
      }),
  );
  const client = mount();
  await screen.findByText("Резервных копий пока нет");
  const button = screen.getByRole("button", { name: "Создать копию" });
  fireEvent.click(button);
  fireEvent.click(button);
  expect(createBackup).toHaveBeenCalledTimes(1);
  vi.mocked(listBackups).mockResolvedValue([backup]);
  await act(async () => resolve(backup));
  expect(await screen.findByRole("status")).toHaveTextContent("Резервная копия создана.");
  expect(document.querySelector("time")).toHaveAttribute("dateTime", backup.created_at);
  expect(client.getQueryData(queryKeys.backups)).toEqual([backup]);
});

it("hides previous data while refresh fails and never labels errors as empty", async () => {
  const client = mount();
  await screen.findByText("Версия 0.0.0-test");
  vi.mocked(listBackups).mockRejectedValue(new Error("synthetic failure"));
  vi.mocked(listAccounts).mockRejectedValue(new Error("synthetic failure"));
  vi.mocked(getHealth).mockRejectedValue(new Error("synthetic failure"));
  await act(async () => {
    await client.invalidateQueries();
  });
  await waitFor(() => expect(screen.getByText("Сведения о копиях недоступны")).toBeVisible());
  expect(screen.getByText("Справочники недоступны")).toBeVisible();
  expect(screen.getByText("Версия недоступна")).toBeVisible();
  expect(screen.queryByText("Резервных копий пока нет")).toBeNull();
  expect(screen.queryByText("Версия 0.0.0-test")).toBeNull();
});
