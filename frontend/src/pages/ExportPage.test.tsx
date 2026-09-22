import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { QueryClientProvider } from "@tanstack/react-query";

import { createQueryClient, queryKeys } from "../queryClient";
import { ExportPage } from "./ExportPage";

const months = [
  {
    id: 2,
    year: 2026,
    month: 7,
    status: "draft" as const,
    snapshot_date: "2026-07-31",
    source: "manual",
  },
  {
    id: 1,
    year: 2026,
    month: 6,
    status: "closed" as const,
    snapshot_date: "2026-06-30",
    source: "manual",
  },
];

const backups = [
  {
    id: "finance_backup_20320731T123456789000Z",
    name: "finance_backup_20320731T123456789000Z.sqlite3",
    created_at: "2032-07-31T12:34:56.789000Z",
    size_bytes: 4096,
    source_database: {
      name: "synthetic-finance.db",
      size_bytes: 8192,
    },
  },
];

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, resolve, reject };
}

function deferredResponse() {
  return deferred<Response>();
}

function renderExportPage() {
  const queryClient = createQueryClient();
  return {
    queryClient,
    ...render(
      <QueryClientProvider client={queryClient}>
        <ExportPage />
      </QueryClientProvider>,
    ),
  };
}

describe("ExportPage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("downloads Markdown for the selected reporting month and shows success", async () => {
    const user = userEvent.setup();
    const anchorClick = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);
    const createObjectURL = vi.fn(() => "blob:markdown-report");
    const revokeObjectURL = vi.fn();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(months))
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(
        new Response("# Июнь 2026\n", {
          status: 200,
          headers: {
            "Content-Type": "text/markdown; charset=utf-8",
            "Content-Disposition": 'attachment; filename="finance_report_2026-06.md"',
          },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL });

    renderExportPage();

    expect(
      screen.getByText("Скачай отчёт в Markdown или JSON для выбранного отчётного месяца."),
    ).toBeInTheDocument();
    expect(screen.getByText(/Дата среза фиксируется приложением/)).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent(/backend|metadata\.as_of_date|Готовим bundle/i);
    expect(await screen.findByRole("button", { name: "Скачать Markdown" })).toBeEnabled();
    await user.selectOptions(screen.getByLabelText("Месяц отчёта"), "1");
    await user.click(screen.getByRole("button", { name: "Скачать Markdown" }));

    await waitFor(() => expect(anchorClick).toHaveBeenCalledTimes(1));
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/months/1/export/markdown",
      expect.objectContaining({ method: "POST" }),
    );
    expect(anchorClick.mock.instances[0]).toHaveProperty("download", "finance_report_2026-06.md");
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:markdown-report");
    expect(await screen.findByRole("status")).toHaveTextContent(/скачан/i);
  });

  it("shows loading and then a readable error when months cannot be loaded", async () => {
    let rejectRequest!: (error: Error) => void;
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockImplementationOnce(
          () =>
            new Promise<Response>((_resolve, reject) => {
              rejectRequest = reject;
            }),
        )
        .mockResolvedValueOnce(jsonResponse([])),
    );

    renderExportPage();

    expect(screen.getByText("Загружаем месяцы…")).toBeInTheDocument();
    await act(async () => {
      rejectRequest(new Error("backend offline"));
    });

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(
      "Не удалось подключиться к локальному приложению. Проверь, что Hermes Finance запущен.",
    );
    expect(alert).not.toHaveTextContent("backend offline");
  });

  it("shows an export error without claiming that a file was downloaded", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(jsonResponse(months))
        .mockResolvedValueOnce(jsonResponse([]))
        .mockResolvedValueOnce(
          jsonResponse(
            { error: { code: "internal_error", message: "Export failed", details: [] } },
            500,
          ),
        ),
    );

    renderExportPage();
    await user.click(await screen.findByRole("button", { name: "Скачать Markdown" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Внутренняя ошибка приложения. Попробуй обновить данные.");
    expect(alert).not.toHaveTextContent("Export failed");
    expect(screen.queryByText(/Файл .*скачан/i)).not.toBeInTheDocument();
  });

  it("downloads JSON beside Markdown and shows loading and success states", async () => {
    const user = userEvent.setup();
    const anchorClick = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);
    const createObjectURL = vi.fn(() => "blob:json-export");
    const revokeObjectURL = vi.fn();
    let resolveExport!: (response: Response) => void;
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(months))
      .mockResolvedValueOnce(jsonResponse([]))
      .mockImplementationOnce(
        () =>
          new Promise<Response>((resolve) => {
            resolveExport = resolve;
          }),
      );
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL });

    renderExportPage();
    const button = await screen.findByRole("button", { name: "Скачать JSON" });
    await user.selectOptions(screen.getByLabelText("Месяц отчёта"), "1");
    await user.click(button);

    expect(await screen.findByRole("button", { name: "Готовим JSON…" })).toBeDisabled();
    resolveExport(
      new Response('{"schema_version":"1.0"}', {
        status: 200,
        headers: {
          "Content-Type": "application/json; charset=utf-8",
          "Content-Disposition": 'attachment; filename="finance_data_2026-06.json"',
        },
      }),
    );
    await waitFor(() => expect(anchorClick).toHaveBeenCalledTimes(1));
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/months/1/export/json",
      expect.objectContaining({ method: "POST" }),
    );
    expect(anchorClick.mock.instances[0]).toHaveProperty("download", "finance_data_2026-06.json");
    expect(await screen.findByRole("status")).toHaveTextContent(/скачан/i);
  });

  it("shows a JSON export error without a success message", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(jsonResponse(months))
        .mockResolvedValueOnce(jsonResponse([]))
        .mockResolvedValueOnce(
          jsonResponse(
            { error: { code: "not_found", message: "Month missing", details: [] } },
            404,
          ),
        ),
    );

    renderExportPage();
    await user.click(await screen.findByRole("button", { name: "Скачать JSON" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Запрошенные данные не найдены.");
    expect(alert).not.toHaveTextContent("Month missing");
    expect(screen.queryByText(/Файл .*скачан/i)).not.toBeInTheDocument();
  });

  it("downloads the full-history AI Analysis Bundle without transforming the backend artifact", async () => {
    const user = userEvent.setup();
    const anchorClick = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);
    const createObjectURL = vi.fn<(blob: Blob) => string>(() => "blob:ai-analysis-bundle");
    const revokeObjectURL = vi.fn();
    const bundle = '{"schema_name":"hermes.finance.ai_analysis_bundle"}\n';
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(months))
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(
        new Response(bundle, {
          status: 200,
          headers: {
            "Content-Type": "application/json; charset=utf-8",
            "Content-Disposition":
              'attachment; filename="hermes-ai-analysis-bundle-2026-07-31-v1.1.0.json"',
          },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL });

    renderExportPage();

    const button = await screen.findByRole("button", {
      name: "Скачать AI Analysis Bundle (JSON)",
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    await user.click(button);

    await waitFor(() => expect(anchorClick).toHaveBeenCalledTimes(1));
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/export/ai-analysis-bundle",
      expect.objectContaining({ method: "POST" }),
    );
    expect(anchorClick.mock.instances[0]).toHaveProperty(
      "download",
      "hermes-ai-analysis-bundle-2026-07-31-v1.1.0.json",
    );
    const [createdBlob] = createObjectURL.mock.calls[0] ?? [];
    expect(await (createdBlob as Blob).text()).toBe(bundle);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:ai-analysis-bundle");
    expect(await screen.findByRole("status")).toHaveTextContent(/скачан/i);
  });

  it("downloads the optional Markdown companion only after an explicit click", async () => {
    const user = userEvent.setup();
    const anchorClick = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);
    vi.stubGlobal("URL", {
      ...URL,
      createObjectURL: vi.fn(() => "blob:ai-analysis-markdown"),
      revokeObjectURL: vi.fn(),
    });
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(months))
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(
        new Response("# Hermes Finance AI Analysis Bundle 1.1.0\n", {
          status: 200,
          headers: {
            "Content-Type": "text/markdown; charset=utf-8",
            "Content-Disposition":
              'attachment; filename="hermes-ai-analysis-bundle-2026-07-31-v1.1.0.md"',
          },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    renderExportPage();
    await user.click(await screen.findByRole("button", { name: "Скачать Markdown-компаньон" }));

    await waitFor(() => expect(anchorClick).toHaveBeenCalledTimes(1));
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/export/ai-analysis-bundle/markdown",
      expect.objectContaining({ method: "POST" }),
    );
    const notes = screen.getAllByRole("note");
    expect(notes).toHaveLength(2);
    expect(notes[1]).toHaveTextContent(/финансовые данные/i);
  });

  it("shows a bundle error without claiming a download", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(jsonResponse(months))
        .mockResolvedValueOnce(jsonResponse([]))
        .mockResolvedValueOnce(
          jsonResponse(
            { error: { code: "internal_error", message: "Bundle failed", details: [] } },
            500,
          ),
        ),
    );

    renderExportPage();
    await user.click(
      await screen.findByRole("button", { name: "Скачать AI Analysis Bundle (JSON)" }),
    );

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Внутренняя ошибка приложения. Попробуй обновить данные.");
    expect(alert).not.toHaveTextContent("Bundle failed");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("handles a network-offline bundle request without contacting a cloud URL", async () => {
    const user = userEvent.setup();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(months))
      .mockResolvedValueOnce(jsonResponse([]))
      .mockRejectedValueOnce(new TypeError("Failed to fetch"));
    vi.stubGlobal("fetch", fetchMock);

    renderExportPage();
    await user.click(
      await screen.findByRole("button", { name: "Скачать AI Analysis Bundle (JSON)" }),
    );

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(
      "Не удалось подключиться к локальному приложению. Проверь, что Hermes Finance запущен.",
    );
    expect(fetchMock.mock.calls.every(([path]) => String(path).startsWith("/api/"))).toBe(true);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("loads backup metadata newest first and shows the source database", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(jsonResponse(months))
        .mockResolvedValueOnce(jsonResponse(backups)),
    );

    renderExportPage();

    expect(await screen.findByRole("heading", { name: "Резервные копии" })).toBeInTheDocument();
    expect(await screen.findByText(backups[0].name)).toBeInTheDocument();
    expect(screen.getByText("synthetic-finance.db")).toBeInTheDocument();
    expect(screen.getByText("4096 Б")).toBeInTheDocument();
  });

  it("shows a loading state while backup metadata is being fetched", async () => {
    let resolveList!: (response: Response) => void;
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(jsonResponse(months))
        .mockImplementationOnce(
          () =>
            new Promise<Response>((resolve) => {
              resolveList = resolve;
            }),
        ),
    );

    renderExportPage();

    expect(screen.getByText("Загружаем список резервных копий…")).toBeInTheDocument();
    await act(async () => {
      resolveList(jsonResponse([]));
    });
    expect(await screen.findByText("Резервных копий пока нет")).toBeInTheDocument();
  });

  it("shows backup loading and then success after creating a backup", async () => {
    const user = userEvent.setup();
    let resolveCreate!: (response: Response) => void;
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(months))
      .mockResolvedValueOnce(jsonResponse([]))
      .mockImplementationOnce(
        () =>
          new Promise<Response>((resolve) => {
            resolveCreate = resolve;
          }),
      );
    vi.stubGlobal("fetch", fetchMock);

    renderExportPage();
    const createButton = await screen.findByRole("button", { name: "Создать резервную копию" });
    await user.click(createButton);

    expect(await screen.findByRole("button", { name: "Создаём резервную копию…" })).toBeDisabled();
    resolveCreate(jsonResponse(backups[0], 201));

    expect(await screen.findByRole("status")).toHaveTextContent(/создан/i);
    expect(screen.getByText(backups[0].name)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/backups",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("shows a readable backup-list error and keeps the create button available", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(jsonResponse(months))
        .mockResolvedValueOnce(
          jsonResponse(
            {
              error: {
                code: "internal_error",
                message: "Backup storage is not available",
                details: [],
              },
            },
            500,
          ),
        ),
    );

    renderExportPage();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Внутренняя ошибка приложения. Попробуй обновить данные.");
    expect(alert).not.toHaveTextContent("Backup storage is not available");
    expect(screen.getByRole("button", { name: "Создать резервную копию" })).toBeEnabled();
  });

  it("requires explicit confirmation and shows restore loading and success states", async () => {
    const user = userEvent.setup();
    let resolveRestore!: (response: Response) => void;
    let resolveMonthsReload!: (response: Response) => void;
    const restored = {
      ...backups[0],
      id: "finance_backup_20320731T123456789000Z",
      name: backups[0].name,
    };
    const preRestore = {
      ...backups[0],
      id: "finance_backup_20320801T123456789000Z",
      name: "finance_backup_20320801T123456789000Z.sqlite3",
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(months))
      .mockResolvedValueOnce(jsonResponse(backups))
      .mockImplementationOnce(
        () =>
          new Promise<Response>((resolve) => {
            resolveRestore = resolve;
          }),
      )
      .mockImplementationOnce(
        () =>
          new Promise<Response>((resolve) => {
            resolveMonthsReload = resolve;
          }),
      );
    vi.stubGlobal("fetch", fetchMock);

    const { queryClient } = renderExportPage();
    queryClient.setQueryData(queryKeys.accounts, { source: "pre-restore" });
    const restoreButton = await screen.findByRole("button", { name: "Восстановить" });
    await user.click(restoreButton);

    const dialog = await screen.findByRole("alertdialog");
    expect(fetchMock).toHaveBeenCalledTimes(2);
    await user.click(within(dialog).getByRole("button", { name: "Отмена" }));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);

    await user.click(restoreButton);
    const openDialog = await screen.findByRole("alertdialog");
    await user.click(within(openDialog).getByRole("button", { name: "Восстановить" }));
    expect(await screen.findByRole("button", { name: "…" })).toBeDisabled();

    resolveRestore(jsonResponse({ restored_backup: restored, pre_restore_backup: preRestore }));

    expect(await screen.findByText("Загружаем месяцы…")).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /Июль.*2026/ })).not.toBeInTheDocument();
    resolveMonthsReload(
      jsonResponse([
        {
          id: 7,
          year: 2025,
          month: 4,
          status: "closed",
          snapshot_date: "2025-04-30",
          source: "restored",
        },
      ]),
    );

    expect(await screen.findByText(/База восстановлена/i)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      `/api/backups/${restored.id}/restore`,
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ confirm: true }),
      }),
    );
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/months",
      expect.objectContaining({ method: "GET" }),
    );
    expect(screen.getByLabelText("Месяц отчёта")).toHaveValue("7");
    expect(screen.getByRole("option", { name: /Апрель.*2025/ })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /Июль.*2026/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /Июнь.*2026/ })).not.toBeInTheDocument();
    expect(screen.getByText(preRestore.name)).toBeInTheDocument();
    expect(queryClient.getQueryState(queryKeys.accounts)?.isInvalidated).toBe(true);
  });

  it("keeps restored months authoritative when the initial request resolves last", async () => {
    const user = userEvent.setup();
    const initialMonthsRequest = deferredResponse();
    const restoredMonthsRequest = deferredResponse();
    const restoredMonths = [
      {
        id: 7,
        year: 2025,
        month: 4,
        status: "closed" as const,
        snapshot_date: "2025-04-30",
        source: "restored",
      },
    ];
    let monthRequestCount = 0;
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/months") {
        monthRequestCount += 1;
        return monthRequestCount === 1
          ? initialMonthsRequest.promise
          : restoredMonthsRequest.promise;
      }
      if (url === "/api/backups") {
        return Promise.resolve(jsonResponse(backups));
      }
      if (url.endsWith("/restore")) {
        return Promise.resolve(
          jsonResponse({
            restored_backup: backups[0],
            pre_restore_backup: {
              ...backups[0],
              id: "finance_backup_pre_restore",
              name: "finance_backup_pre_restore.sqlite3",
            },
          }),
        );
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderExportPage();
    await user.click(await screen.findByRole("button", { name: "Восстановить" }));
    await user.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", {
        name: "Восстановить",
      }),
    );
    await waitFor(() => expect(monthRequestCount).toBe(2));

    await act(async () => {
      restoredMonthsRequest.resolve(jsonResponse(restoredMonths));
      await Promise.resolve();
    });
    expect(await screen.findByText(/База восстановлена/i)).toBeInTheDocument();
    expect(screen.getByLabelText("Месяц отчёта")).toHaveValue("7");

    await act(async () => {
      initialMonthsRequest.resolve(jsonResponse(months));
      await Promise.resolve();
    });
    expect(screen.getByLabelText("Месяц отчёта")).toHaveValue("7");
    expect(screen.getByRole("option", { name: /Апрель.*2025/ })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /Июль.*2026/ })).not.toBeInTheDocument();
  });

  it("keeps loading authoritative when the initial request resolves before the restored request", async () => {
    const user = userEvent.setup();
    const initialMonthsRequest = deferredResponse();
    const restoredMonthsRequest = deferredResponse();
    let monthRequestCount = 0;
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/months") {
        monthRequestCount += 1;
        return monthRequestCount === 1
          ? initialMonthsRequest.promise
          : restoredMonthsRequest.promise;
      }
      if (url === "/api/backups") {
        return Promise.resolve(jsonResponse(backups));
      }
      if (url.endsWith("/restore")) {
        return Promise.resolve(
          jsonResponse({
            restored_backup: backups[0],
            pre_restore_backup: {
              ...backups[0],
              id: "finance_backup_pre_restore",
              name: "finance_backup_pre_restore.sqlite3",
            },
          }),
        );
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderExportPage();
    await user.click(await screen.findByRole("button", { name: "Восстановить" }));
    await user.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", {
        name: "Восстановить",
      }),
    );
    await waitFor(() => expect(monthRequestCount).toBe(2));

    await act(async () => {
      initialMonthsRequest.resolve(jsonResponse(months));
      await Promise.resolve();
    });
    expect(screen.getByText("Загружаем месяцы…")).toBeInTheDocument();
    expect(screen.queryByLabelText("Месяц отчёта")).not.toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /Июль.*2026/ })).not.toBeInTheDocument();

    await act(async () => {
      restoredMonthsRequest.resolve(
        jsonResponse([
          {
            id: 8,
            year: 2025,
            month: 5,
            status: "draft",
            snapshot_date: "2025-05-31",
            source: "restored",
          },
        ]),
      );
      await Promise.resolve();
    });
    expect(await screen.findByText(/База восстановлена/i)).toBeInTheDocument();
    expect(screen.getByLabelText("Месяц отчёта")).toHaveValue("8");
  });

  it("retires the initial request before shared invalidation when it resolves", async () => {
    const user = userEvent.setup();
    const initialMonthsRequest = deferredResponse();
    const restoredMonthsRequest = deferredResponse();
    const invalidation = deferred<void>();
    let monthRequestCount = 0;
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/months") {
        monthRequestCount += 1;
        return monthRequestCount === 1
          ? initialMonthsRequest.promise
          : restoredMonthsRequest.promise;
      }
      if (url === "/api/backups") {
        return Promise.resolve(jsonResponse(backups));
      }
      if (url.endsWith("/restore")) {
        return Promise.resolve(
          jsonResponse({
            restored_backup: backups[0],
            pre_restore_backup: {
              ...backups[0],
              id: "finance_backup_pre_restore",
              name: "finance_backup_pre_restore.sqlite3",
            },
          }),
        );
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const { queryClient } = renderExportPage();
    const invalidateQueries = vi
      .spyOn(queryClient, "invalidateQueries")
      .mockImplementation(() => invalidation.promise);
    await user.click(await screen.findByRole("button", { name: "Восстановить" }));
    await user.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", {
        name: "Восстановить",
      }),
    );
    await waitFor(() => expect(invalidateQueries).toHaveBeenCalledTimes(1));

    await act(async () => {
      initialMonthsRequest.resolve(jsonResponse(months));
      await Promise.resolve();
    });
    expect(screen.getByText("Загружаем месяцы…")).toBeInTheDocument();
    expect(screen.queryByLabelText("Месяц отчёта")).not.toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /Июль.*2026/ })).not.toBeInTheDocument();
    expect(screen.queryByText("Не удалось загрузить месяцы")).not.toBeInTheDocument();

    await act(async () => {
      invalidation.resolve();
      await Promise.resolve();
    });
    await waitFor(() => expect(monthRequestCount).toBe(2));
    restoredMonthsRequest.resolve(jsonResponse([]));
    expect(await screen.findByText(/База восстановлена/i)).toBeInTheDocument();
  });

  it("retires the initial request before shared invalidation when it rejects", async () => {
    const user = userEvent.setup();
    const initialMonthsRequest = deferredResponse();
    const restoredMonthsRequest = deferredResponse();
    const invalidation = deferred<void>();
    let monthRequestCount = 0;
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/months") {
        monthRequestCount += 1;
        return monthRequestCount === 1
          ? initialMonthsRequest.promise
          : restoredMonthsRequest.promise;
      }
      if (url === "/api/backups") {
        return Promise.resolve(jsonResponse(backups));
      }
      if (url.endsWith("/restore")) {
        return Promise.resolve(
          jsonResponse({
            restored_backup: backups[0],
            pre_restore_backup: {
              ...backups[0],
              id: "finance_backup_pre_restore",
              name: "finance_backup_pre_restore.sqlite3",
            },
          }),
        );
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const { queryClient } = renderExportPage();
    const invalidateQueries = vi
      .spyOn(queryClient, "invalidateQueries")
      .mockImplementation(() => invalidation.promise);
    await user.click(await screen.findByRole("button", { name: "Восстановить" }));
    await user.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", {
        name: "Восстановить",
      }),
    );
    await waitFor(() => expect(invalidateQueries).toHaveBeenCalledTimes(1));

    await act(async () => {
      initialMonthsRequest.reject(new Error("stale request failed"));
      await Promise.resolve();
    });
    expect(screen.getByText("Загружаем месяцы…")).toBeInTheDocument();
    expect(screen.queryByLabelText("Месяц отчёта")).not.toBeInTheDocument();
    expect(screen.queryByText("Не удалось загрузить месяцы")).not.toBeInTheDocument();

    await act(async () => {
      invalidation.resolve();
      await Promise.resolve();
    });
    await waitFor(() => expect(monthRequestCount).toBe(2));
    restoredMonthsRequest.resolve(jsonResponse([]));
    expect(await screen.findByText(/База восстановлена/i)).toBeInTheDocument();
  });

  it("hides already-loaded months while shared invalidation is pending", async () => {
    const user = userEvent.setup();
    const invalidation = deferred<void>();
    const restoredMonthsRequest = deferredResponse();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(months))
      .mockResolvedValueOnce(jsonResponse(backups))
      .mockResolvedValueOnce(
        jsonResponse({
          restored_backup: backups[0],
          pre_restore_backup: {
            ...backups[0],
            id: "finance_backup_pre_restore",
            name: "finance_backup_pre_restore.sqlite3",
          },
        }),
      )
      .mockImplementationOnce(() => restoredMonthsRequest.promise);
    vi.stubGlobal("fetch", fetchMock);

    const { queryClient } = renderExportPage();
    const invalidateQueries = vi
      .spyOn(queryClient, "invalidateQueries")
      .mockImplementation(() => invalidation.promise);
    expect(await screen.findByLabelText("Месяц отчёта")).toHaveValue("2");

    await user.click(screen.getByRole("button", { name: "Восстановить" }));
    await user.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", {
        name: "Восстановить",
      }),
    );
    await waitFor(() => expect(invalidateQueries).toHaveBeenCalledTimes(1));

    expect(screen.getByText("Загружаем месяцы…")).toBeInTheDocument();
    expect(screen.queryByLabelText("Месяц отчёта")).not.toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /Июль.*2026/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /Июнь.*2026/ })).not.toBeInTheDocument();

    await act(async () => {
      invalidation.resolve();
      await Promise.resolve();
    });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));
    restoredMonthsRequest.resolve(jsonResponse([]));
    expect(await screen.findByText(/База восстановлена/i)).toBeInTheDocument();
  });

  it("keeps confirmed restore success separate from a failed month reload", async () => {
    const user = userEvent.setup();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(months))
      .mockResolvedValueOnce(jsonResponse(backups))
      .mockResolvedValueOnce(
        jsonResponse({
          restored_backup: backups[0],
          pre_restore_backup: {
            ...backups[0],
            id: "finance_backup_pre_restore",
            name: "finance_backup_pre_restore.sqlite3",
          },
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse(
          { error: { code: "internal_error", message: "Month read failed", details: [] } },
          500,
        ),
      );
    vi.stubGlobal("fetch", fetchMock);

    renderExportPage();
    await user.click(await screen.findByRole("button", { name: "Восстановить" }));
    await user.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", {
        name: "Восстановить",
      }),
    );

    expect(await screen.findByText(/База восстановлена/i)).toBeInTheDocument();
    expect(screen.getByText("Не удалось загрузить месяцы")).toBeInTheDocument();
    expect(screen.queryByLabelText("Месяц отчёта")).not.toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /Июль.*2026/ })).not.toBeInTheDocument();
  });

  it("selects the newest restored month after sorting an out-of-order response", async () => {
    const user = userEvent.setup();
    const restoredMonths = [
      {
        id: 20,
        year: 2024,
        month: 12,
        status: "closed" as const,
        snapshot_date: "2024-12-31",
        source: "restored",
      },
      {
        id: 22,
        year: 2025,
        month: 11,
        status: "draft" as const,
        snapshot_date: "2025-11-30",
        source: "restored",
      },
      {
        id: 21,
        year: 2026,
        month: 1,
        status: "closed" as const,
        snapshot_date: "2026-01-31",
        source: "restored",
      },
    ];
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(months))
      .mockResolvedValueOnce(jsonResponse(backups))
      .mockResolvedValueOnce(
        jsonResponse({
          restored_backup: backups[0],
          pre_restore_backup: {
            ...backups[0],
            id: "finance_backup_pre_restore",
            name: "finance_backup_pre_restore.sqlite3",
          },
        }),
      )
      .mockResolvedValueOnce(jsonResponse(restoredMonths));
    vi.stubGlobal("fetch", fetchMock);

    renderExportPage();
    await user.click(await screen.findByRole("button", { name: "Восстановить" }));
    await user.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", {
        name: "Восстановить",
      }),
    );

    expect(await screen.findByText(/База восстановлена/i)).toBeInTheDocument();
    const select = screen.getByLabelText("Месяц отчёта");
    expect(select).toHaveValue("21");
    expect(
      within(select)
        .getAllByRole("option")
        .map((option) => option.getAttribute("value")),
    ).toEqual(["21", "22", "20"]);
  });

  it("preserves the selected month only when it exists in the restored database", async () => {
    const user = userEvent.setup();
    const restoredMonths = [
      {
        id: 9,
        year: 2027,
        month: 1,
        status: "draft" as const,
        snapshot_date: "2027-01-31",
        source: "restored",
      },
      months[1],
    ];
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(months))
      .mockResolvedValueOnce(jsonResponse(backups))
      .mockResolvedValueOnce(
        jsonResponse({
          restored_backup: backups[0],
          pre_restore_backup: {
            ...backups[0],
            id: "finance_backup_pre_restore",
            name: "finance_backup_pre_restore.sqlite3",
          },
        }),
      )
      .mockResolvedValueOnce(jsonResponse(restoredMonths));
    vi.stubGlobal("fetch", fetchMock);

    renderExportPage();
    const select = await screen.findByLabelText("Месяц отчёта");
    await user.selectOptions(select, "1");
    await user.click(screen.getByRole("button", { name: "Восстановить" }));
    await user.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", {
        name: "Восстановить",
      }),
    );

    expect(await screen.findByText(/База восстановлена/i)).toBeInTheDocument();
    expect(screen.getByLabelText("Месяц отчёта")).toHaveValue("1");
    expect(screen.getByRole("option", { name: /Июнь.*2026/ })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /Июль.*2026/ })).not.toBeInTheDocument();
  });

  it("clears the selected month when the restored database has no months", async () => {
    const user = userEvent.setup();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(months))
      .mockResolvedValueOnce(jsonResponse(backups))
      .mockResolvedValueOnce(
        jsonResponse({
          restored_backup: backups[0],
          pre_restore_backup: {
            ...backups[0],
            id: "finance_backup_pre_restore",
            name: "finance_backup_pre_restore.sqlite3",
          },
        }),
      )
      .mockResolvedValueOnce(jsonResponse([]));
    vi.stubGlobal("fetch", fetchMock);

    renderExportPage();
    await user.click(await screen.findByRole("button", { name: "Восстановить" }));
    await user.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", {
        name: "Восстановить",
      }),
    );

    expect(await screen.findByText(/База восстановлена/i)).toBeInTheDocument();
    expect(screen.getByText("Нет месяцев")).toBeInTheDocument();
    expect(screen.queryByLabelText("Месяц отчёта")).not.toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /Июль.*2026/ })).not.toBeInTheDocument();
  });

  it("shows a restore error without claiming success", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(jsonResponse(months))
        .mockResolvedValueOnce(jsonResponse(backups))
        .mockResolvedValueOnce(
          jsonResponse(
            { error: { code: "unprocessable", message: "Backup is corrupt", details: [] } },
            422,
          ),
        ),
    );

    renderExportPage();
    await user.click(await screen.findByRole("button", { name: "Восстановить" }));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Восстановить" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Проверь введённые данные.");
    expect(alert).not.toHaveTextContent("Backup is corrupt");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Месяц отчёта")).toHaveValue("2");
    expect(fetch).toHaveBeenCalledTimes(3);
  });

  it("does not reload months or claim success for an ambiguous restore outcome", async () => {
    const user = userEvent.setup();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(months))
      .mockResolvedValueOnce(jsonResponse(backups))
      .mockResolvedValueOnce(
        jsonResponse(
          {
            error: {
              code: "restore_outcome_ambiguous",
              message: "Restore outcome is ambiguous; inspect refreshed state before retrying",
              details: [],
            },
          },
          500,
        ),
      );
    vi.stubGlobal("fetch", fetchMock);

    renderExportPage();
    await user.click(await screen.findByRole("button", { name: "Восстановить" }));
    await user.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", {
        name: "Восстановить",
      }),
    );

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(
      "Restore outcome is ambiguous; inspect refreshed state before retrying",
    );
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Месяц отчёта")).toHaveValue("2");
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("marks exactly one export as recommended and keeps old exports in the secondary area", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValueOnce(jsonResponse(months)).mockResolvedValueOnce(jsonResponse([])),
    );

    renderExportPage();

    const recommendedHeading = await screen.findByRole("heading", {
      name: "Полный финансовый отчёт для AI",
    });
    expect(recommendedHeading).toBeInTheDocument();
    expect(screen.getByText("Рекомендуемый для AI-анализа")).toBeInTheDocument();
    expect(screen.getByText("Рекомендуется")).toBeInTheDocument();

    const recommendedMentions = screen.getAllByText(/рекомендуе/i);
    expect(recommendedMentions).toHaveLength(2);
    const recommendedSection = recommendedHeading.closest("section");
    expect(recommendedSection).not.toBeNull();
    for (const node of recommendedMentions) {
      expect(recommendedSection).toContainElement(node);
    }

    expect(
      screen.getByText(
        "Обычный ежемесячный файл для ChatGPT или другого AI. Включает капитал, портфель, динамику по месяцам, пассивный доход, цели, долги и недвижимость, будущие выплаты, сигналы о качестве данных и ваши комментарии.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Выгрузить отчёт для AI" })).toBeEnabled();

    const secondaryToggle = screen.getByText("Дополнительные / технические выгрузки");
    expect(secondaryToggle.tagName.toLowerCase()).toBe("summary");
    const secondaryArea = secondaryToggle.closest("details");
    expect(secondaryArea).not.toBeNull();

    const bodyText = document.body.textContent ?? "";
    expect(bodyText.indexOf("Полный финансовый отчёт для AI")).toBeLessThan(
      bodyText.indexOf("Дополнительные / технические выгрузки"),
    );

    for (const name of [
      "Скачать Markdown",
      "Скачать JSON",
      "Скачать AI Analysis Bundle (JSON)",
      "Скачать Markdown-компаньон",
    ]) {
      const button = screen.getByRole("button", { name });
      expect(secondaryArea).toContainElement(button);
    }
    expect(screen.getByRole("heading", { name: "Скачать отчёт" })).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Полный анализ для ассистента" }),
    ).toBeInTheDocument();

    const redirects = screen.getAllByText(/используй основной отчёт/i);
    expect(redirects).toHaveLength(4);
    for (const node of redirects) {
      expect(secondaryArea).toContainElement(node);
    }
  });

  it("downloads the canonical AI financial review JSON without transforming the backend artifact", async () => {
    const user = userEvent.setup();
    const anchorClick = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);
    const createObjectURL = vi.fn<(blob: Blob) => string>(() => "blob:ai-financial-review");
    const revokeObjectURL = vi.fn();
    const review = '{"schema_name":"hermes.finance.ai_financial_review"}\n';
    let resolveReview!: (response: Response) => void;
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(months))
      .mockResolvedValueOnce(jsonResponse([]))
      .mockImplementationOnce(
        () =>
          new Promise<Response>((resolve) => {
            resolveReview = resolve;
          }),
      );
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL });

    renderExportPage();

    const button = await screen.findByRole("button", { name: "Выгрузить отчёт для AI" });
    expect(button.className).toMatch(/btn--primary/);
    await user.click(button);

    expect(await screen.findByRole("button", { name: "Готовим отчёт…" })).toBeDisabled();
    resolveReview(
      new Response(review, {
        status: 200,
        headers: {
          "Content-Type": "application/json; charset=utf-8",
          "Content-Disposition":
            'attachment; filename="hermes-ai-financial-review-2026-07-31.json"',
        },
      }),
    );

    await waitFor(() => expect(anchorClick).toHaveBeenCalledTimes(1));
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/export/ai-financial-review/json",
      expect.objectContaining({ method: "GET" }),
    );
    expect(anchorClick.mock.instances[0]).toHaveProperty(
      "download",
      "hermes-ai-financial-review-2026-07-31.json",
    );
    const [createdBlob] = createObjectURL.mock.calls[0] ?? [];
    expect(await (createdBlob as Blob).text()).toBe(review);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:ai-financial-review");
    expect(await screen.findByRole("status")).toHaveTextContent(/скачан/i);
  });

  it("shows a canonical AI report error without claiming a download", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(jsonResponse(months))
        .mockResolvedValueOnce(jsonResponse([]))
        .mockResolvedValueOnce(
          jsonResponse(
            { error: { code: "internal_error", message: "Review failed", details: [] } },
            500,
          ),
        ),
    );

    renderExportPage();
    await user.click(await screen.findByRole("button", { name: "Выгрузить отчёт для AI" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Внутренняя ошибка приложения. Попробуй обновить данные.");
    expect(alert).not.toHaveTextContent("Review failed");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
