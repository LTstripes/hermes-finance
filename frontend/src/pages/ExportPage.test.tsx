import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
      vi.fn(
        () =>
          new Promise<Response>((_resolve, reject) => {
            rejectRequest = reject;
          }),
      ),
    );

    render(<ExportPage />);

    expect(screen.getByRole("status")).toHaveTextContent(/Загружаем месяцы/i);
    rejectRequest(new Error("backend offline"));

    expect(await screen.findByRole("alert")).toHaveTextContent("backend offline");
  });

  it("shows an export error without claiming that a file was downloaded", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(jsonResponse(months))
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
});
