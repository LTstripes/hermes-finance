import { QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { BackupMetadata } from "../api/types";
import { createQueryClient, queryKeys } from "../queryClient";
import { uiV2Months } from "../test/uiV2Fixtures";
import UiV2DataFilesPage from "../ui-v2/UiV2DataFilesPage";

const NativeURL = URL;

const backups: BackupMetadata[] = [
  {
    id: "finance_backup_20320801T123456789000Z",
    name: "finance_backup_20320801T123456789000Z.sqlite3",
    created_at: "2032-08-01T12:34:56.789000Z",
    size_bytes: 4096,
    source_database: { name: "synthetic-finance.db", size_bytes: 8192 },
  },
];

const preRestoreBackup: BackupMetadata = {
  id: "finance_backup_20320802T123456789000Z",
  name: "finance_backup_20320802T123456789000Z.sqlite3",
  created_at: "2032-08-02T12:34:56.789000Z",
  size_bytes: 8192,
  source_database: { name: "synthetic-finance.db", size_bytes: 12288 },
};

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function downloadResponse(filename: string): Response {
  return new Response("synthetic export\n", {
    status: 200,
    headers: {
      "Content-Disposition": `attachment; filename="${filename}"`,
      "Content-Type": "application/octet-stream",
    },
  });
}

function setup({
  months = uiV2Months,
  listedBackups = backups,
  restoreStatus = 200,
  restoreStatuses,
  restoreNetworkError = false,
  path = "/v2/data/files",
}: {
  months?: typeof uiV2Months;
  listedBackups?: BackupMetadata[];
  restoreStatus?: number;
  restoreStatuses?: number[];
  restoreNetworkError?: boolean;
  path?: string;
} = {}) {
  const client = createQueryClient();
  const calls: Array<{ method: string; path: string; body?: string }> = [];
  const restoreResponse = {
    restored_backup: listedBackups[0] ?? backups[0],
    pre_restore_backup: preRestoreBackup,
  };
  let restoreAttempt = 0;
  const fetchMock = vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
    const url = new NativeURL(String(input), "http://localhost");
    const method = options?.method ?? "GET";
    const body = typeof options?.body === "string" ? options.body : undefined;
    calls.push({ method, path: url.pathname, body });

    if (method === "GET" && url.pathname === "/api/months") return jsonResponse(months);
    if (method === "GET" && url.pathname === "/api/backups") {
      return jsonResponse(listedBackups);
    }
    if (method === "POST" && url.pathname === "/api/backups") {
      return jsonResponse(preRestoreBackup, 201);
    }
    if (method === "POST" && /^\/api\/backups\/[^/]+\/restore$/.test(url.pathname)) {
      const currentRestoreStatus = restoreStatuses?.[restoreAttempt] ?? restoreStatus;
      restoreAttempt += 1;
      if (restoreNetworkError) {
        throw new TypeError("Failed to fetch");
      }
      if (currentRestoreStatus !== 200) {
        return jsonResponse(
          { error: { code: "unprocessable", message: "Backup is corrupt", details: [] } },
          currentRestoreStatus,
        );
      }
      return jsonResponse(restoreResponse);
    }
    if (method === "POST" && /\/export\/(markdown|json)$/.test(url.pathname)) {
      const suffix = url.pathname.endsWith("/json") ? "json" : "md";
      return downloadResponse(`finance_data_2031-08.${suffix}`);
    }
    if (method === "GET" && url.pathname === "/api/export/ai-financial-review/json") {
      return downloadResponse("hermes-ai-financial-review.json");
    }
    if (method === "GET" && /\/api\/export\/ai-analysis-bundle(\/markdown)?$/.test(url.pathname)) {
      return downloadResponse("hermes-ai-analysis-bundle.json");
    }
    throw new Error(`Unexpected request: ${method} ${url.pathname}`);
  });
  vi.stubGlobal("fetch", fetchMock);

  function mount() {
    return render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path="v2/data/files" element={<UiV2DataFilesPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
  }

  return { calls, client, fetchMock, mount };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("UI v2 Data files", () => {
  it("keeps read-only exports and mutating backups in separate surfaces", async () => {
    const { calls, mount } = setup();
    mount();

    expect(await screen.findByRole("heading", { name: "Файлы" })).toBeInTheDocument();
    expect(screen.getByTestId("files-exports")).toBeInTheDocument();
    expect(screen.getByTestId("files-backups")).toBeInTheDocument();
    expect(screen.getAllByText("Только чтение").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Изменяет данные").length).toBeGreaterThan(0);
    expect(screen.getByText("Необратимо")).toBeInTheDocument();
    expect(await screen.findByLabelText("Месяц отчёта")).toHaveValue("12");
    expect(
      screen.getByText("Дополнительные / технические выгрузки").closest("details"),
    ).not.toHaveAttribute("open");
    expect(calls.map(({ method, path }) => `${method} ${path}`)).toEqual(
      expect.arrayContaining(["GET /api/months", "GET /api/backups"]),
    );
    expect(calls.some(({ method }) => method === "POST")).toBe(false);
  });

  it("uses the existing month export contract and reports a local download", async () => {
    const user = userEvent.setup();
    const anchorClick = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);
    const createObjectURL = vi.fn(() => "blob:month-export");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { ...NativeURL, createObjectURL, revokeObjectURL });
    const { calls, mount } = setup();
    mount();

    await user.click(await screen.findByRole("button", { name: "Скачать Markdown" }));
    await waitFor(() => expect(anchorClick).toHaveBeenCalledTimes(1));
    expect(calls.at(-1)).toMatchObject({ method: "POST", path: "/api/months/12/export/markdown" });
    expect(await screen.findByRole("status")).toHaveTextContent(/скачан/i);
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:month-export");
  });

  it("keeps no-month state fail-closed while full-history export and backup creation remain separate", async () => {
    const { mount } = setup({ months: [], listedBackups: [] });
    mount();

    expect(await screen.findByTestId("files-no-months")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Выгрузить отчёт для AI" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Создать резервную копию" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Скачать Markdown" })).not.toBeInTheDocument();
  });

  it("creates a backup and shows it in the local list", async () => {
    const user = userEvent.setup();
    const { calls, mount } = setup({ listedBackups: [] });
    mount();

    const createButton = await screen.findByRole("button", { name: "Создать резервную копию" });
    await user.click(createButton);
    expect(await screen.findByRole("status")).toHaveTextContent(/создана/i);
    expect(screen.getByText(preRestoreBackup.name)).toBeInTheDocument();
    expect(calls.at(-1)).toMatchObject({ method: "POST", path: "/api/backups" });
  });

  it("requires exact target confirmation and preserves backend pre-restore evidence", async () => {
    const user = userEvent.setup();
    const { calls, mount } = setup();
    mount();

    const target = backups[0];
    await user.click(
      await screen.findByRole("button", { name: `Восстановить резервную копию ${target.name}` }),
    );
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent(`Точный target: ${target.name}`);
    expect(calls.filter(({ method }) => method === "POST")).toHaveLength(0);

    await user.click(within(dialog).getByRole("button", { name: "Восстановить" }));
    expect(await screen.findByTestId("pre-restore-evidence")).toHaveTextContent(
      preRestoreBackup.name,
    );
    expect(screen.getByRole("status")).toHaveTextContent(/восстановлена/i);
    expect(calls).toContainEqual({
      method: "POST",
      path: `/api/backups/${target.id}/restore`,
      body: JSON.stringify({ confirm: true }),
    });
  });

  it("contains Tab and Shift+Tab inside the restore confirmation", async () => {
    const user = userEvent.setup();
    const { mount } = setup();
    mount();

    const target = backups[0];
    await user.click(
      await screen.findByRole("button", { name: `Восстановить резервную копию ${target.name}` }),
    );
    const dialog = await screen.findByRole("alertdialog");
    const cancel = within(dialog).getByRole("button", { name: "Отмена" });
    const confirm = within(dialog).getByRole("button", { name: "Восстановить" });
    const createButton = screen.getByRole("button", { name: "Создать резервную копию" });

    expect(document.activeElement).toBe(cancel);
    await user.tab();
    expect(document.activeElement).toBe(confirm);
    await user.tab();
    expect(document.activeElement).toBe(cancel);
    await user.tab({ shift: true });
    expect(document.activeElement).toBe(confirm);
    await user.tab({ shift: true });
    expect(document.activeElement).toBe(cancel);
    expect(document.activeElement).not.toBe(createButton);
  });

  it("invalidates cached financial reads and refetches active reads after a successful restore", async () => {
    const user = userEvent.setup();
    const { calls, client, mount } = setup();
    client.setQueryData(queryKeys.accounts, { source: "pre-restore" });
    mount();

    await user.click(
      await screen.findByRole("button", {
        name: `Восстановить резервную копию ${backups[0].name}`,
      }),
    );
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Восстановить" }));

    expect(await screen.findByRole("status")).toHaveTextContent(/восстановлена/i);
    await waitFor(() => {
      expect(
        calls.filter(({ method, path }) => method === "GET" && path === "/api/months"),
      ).toHaveLength(2);
    });
    expect(client.getQueryState(queryKeys.accounts)?.isInvalidated).toBe(true);
    expect(client.getQueryState(queryKeys.months)?.isInvalidated).toBe(false);
  });

  it("shows restore failure without claiming success", async () => {
    const user = userEvent.setup();
    const { calls, client, mount } = setup({ restoreStatus: 422 });
    client.setQueryData(queryKeys.accounts, { source: "current" });
    mount();

    await user.click(
      await screen.findByRole("button", {
        name: `Восстановить резервную копию ${backups[0].name}`,
      }),
    );
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Восстановить" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/восстановление не выполнено/i);
    expect(
      calls.filter(({ method, path }) => method === "GET" && path === "/api/months"),
    ).toHaveLength(1);
    expect(client.getQueryState(queryKeys.accounts)?.isInvalidated).toBe(false);
    expect(client.getQueryState(queryKeys.months)?.isInvalidated).toBe(false);
    expect(screen.queryByTestId("pre-restore-evidence")).not.toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("treats a restore transport failure as unknown and refreshes reads without retrying", async () => {
    const user = userEvent.setup();
    const { calls, client, mount } = setup({ restoreNetworkError: true });
    client.setQueryData(queryKeys.accounts, { source: "current" });
    mount();

    await user.click(
      await screen.findByRole("button", {
        name: `Восстановить резервную копию ${backups[0].name}`,
      }),
    );
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Восстановить" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/результат восстановления не подтверждён/i);
    expect(alert).not.toHaveTextContent(/восстановление не выполнено/i);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByTestId("pre-restore-evidence")).not.toBeInTheDocument();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(
      calls.filter(({ method, path }) => method === "POST" && path.endsWith("/restore")),
    ).toHaveLength(1);
    await waitFor(() => {
      expect(
        calls.filter(({ method, path }) => method === "GET" && path === "/api/months"),
      ).toHaveLength(2);
    });
    expect(client.getQueryState(queryKeys.accounts)?.isInvalidated).toBe(true);
  });

  it("clears prior pre-restore evidence before a later failed restore attempt", async () => {
    const user = userEvent.setup();
    const secondTarget: BackupMetadata = {
      ...backups[0],
      id: "finance_backup_20320803T123456789000Z",
      name: "finance_backup_20320803T123456789000Z.sqlite3",
    };
    const { mount } = setup({
      listedBackups: [backups[0], secondTarget],
      restoreStatuses: [200, 422],
    });
    mount();

    await user.click(
      await screen.findByRole("button", {
        name: `Восстановить резервную копию ${backups[0].name}`,
      }),
    );
    await user.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", {
        name: "Восстановить",
      }),
    );
    expect(await screen.findByTestId("pre-restore-evidence")).toHaveTextContent(
      preRestoreBackup.name,
    );

    await user.click(
      await screen.findByRole("button", {
        name: `Восстановить резервную копию ${secondTarget.name}`,
      }),
    );
    await user.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", {
        name: "Восстановить",
      }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(/восстановление не выполнено/i);
    expect(screen.queryByTestId("pre-restore-evidence")).not.toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("guards restore from starting while backup creation is in flight", async () => {
    const user = userEvent.setup();
    let resolveCreate!: (response: Response) => void;
    const pendingCreate = new Promise<Response>((resolve) => {
      resolveCreate = resolve;
    });
    const { fetchMock, mount } = setup();
    mount();
    const createButton = await screen.findByRole("button", { name: "Создать резервную копию" });
    fetchMock.mockImplementationOnce(() => pendingCreate);
    await user.click(createButton);

    fireEvent.click(
      screen.getByRole("button", {
        name: `Восстановить резервную копию ${backups[0].name}`,
      }),
    );
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(
      fetchMock.mock.calls.filter(
        ([input, options]) =>
          options?.method === "POST" && String(input).endsWith(`/backups/${backups[0].id}/restore`),
      ),
    ).toHaveLength(0);

    resolveCreate(jsonResponse(preRestoreBackup, 201));
    expect(await screen.findByRole("status")).toHaveTextContent(/создана/i);
  });

  it("guards backup creation from starting while restore is in flight", async () => {
    const user = userEvent.setup();
    let resolveRestore!: (response: Response) => void;
    const pendingRestore = new Promise<Response>((resolve) => {
      resolveRestore = resolve;
    });
    const { fetchMock, mount } = setup();
    mount();

    fetchMock.mockImplementationOnce(() => pendingRestore);
    await user.click(
      await screen.findByRole("button", {
        name: `Восстановить резервную копию ${backups[0].name}`,
      }),
    );
    await user.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", {
        name: "Восстановить",
      }),
    );
    expect(await screen.findByRole("button", { name: "…" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Создать резервную копию" }));
    expect(
      fetchMock.mock.calls.filter(
        ([input, options]) => options?.method === "POST" && String(input) === "/api/backups",
      ),
    ).toHaveLength(0);

    resolveRestore(
      jsonResponse({ restored_backup: backups[0], pre_restore_backup: preRestoreBackup }),
    );
    expect(await screen.findByRole("status")).toHaveTextContent(/восстановлена/i);
  });
});
