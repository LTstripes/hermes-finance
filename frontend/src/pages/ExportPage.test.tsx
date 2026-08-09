import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

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

    render(<ExportPage />);

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

    render(<ExportPage />);

    expect(screen.getByText("Загружаем месяцы…")).toBeInTheDocument();
    await act(async () => {
      rejectRequest(new Error("backend offline"));
    });

    expect(await screen.findByRole("alert")).toHaveTextContent("backend offline");
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

    render(<ExportPage />);
    await user.click(await screen.findByRole("button", { name: "Скачать Markdown" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Export failed");
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

    render(<ExportPage />);
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

    render(<ExportPage />);
    await user.click(await screen.findByRole("button", { name: "Скачать JSON" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Month missing");
    expect(screen.queryByText(/Файл .*скачан/i)).not.toBeInTheDocument();
  });

  it("loads backup metadata newest first and shows the source database", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(jsonResponse(months))
        .mockResolvedValueOnce(jsonResponse(backups)),
    );

    render(<ExportPage />);

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

    render(<ExportPage />);

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

    render(<ExportPage />);
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

    render(<ExportPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Backup storage is not available");
    expect(screen.getByRole("button", { name: "Создать резервную копию" })).toBeEnabled();
  });

  it("requires explicit confirmation and shows restore loading and success states", async () => {
    const user = userEvent.setup();
    let resolveRestore!: (response: Response) => void;
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
      );
    vi.stubGlobal("fetch", fetchMock);

    render(<ExportPage />);
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

    expect(await screen.findByRole("status")).toHaveTextContent(/восстановлена/i);
    expect(fetchMock).toHaveBeenLastCalledWith(
      `/api/backups/${restored.id}/restore`,
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ confirm: true }),
      }),
    );
    expect(screen.getByText(preRestore.name)).toBeInTheDocument();
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

    render(<ExportPage />);
    await user.click(await screen.findByRole("button", { name: "Восстановить" }));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Восстановить" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Backup is corrupt");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
