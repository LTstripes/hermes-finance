import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { QuotePreview, QuotePreviewRow, QuotePreviewStatus } from "../api/types";
import { QuotePreviewPanel } from "./QuotePreviewPanel";

const identity = {
  provider: "moex_iss",
  provider_instrument_id: "SBER",
  provider_venue_id: "stock/shares/TQBR",
};

function row(
  overrides: Partial<QuotePreviewRow> &
    Pick<QuotePreviewRow, "position_snapshot_id" | "instrument_id" | "instrument_name" | "status">,
): QuotePreviewRow {
  return {
    account_id: 1,
    instrument_type: "stock",
    mapping_state: "mapped",
    identity,
    current_market_price_per_unit: { amount: "200.00", currency: "RUB" },
    current_price_date: "2026-08-01",
    current_price_source: "manual",
    proposed_market_price_per_unit: { amount: "215.50", currency: "RUB" },
    proposed_price_date: "2026-08-12",
    proposed_quote_kind: "last",
    proposed_raw_price: "215.50",
    proposed_raw_price_basis: "R",
    fetched_at_utc: "2026-08-13T12:00:00Z",
    freshness_status: overrides.status,
    message: null,
    apply_allowed: overrides.status === "ok",
    ...overrides,
  };
}

function preview(rows: QuotePreviewRow[], overrides: Partial<QuotePreview> = {}): QuotePreview {
  return {
    reporting_month_id: 7,
    month_status: "draft",
    target_date: "2026-08-13",
    month_editable: true,
    batch_error: null,
    rows,
    ...overrides,
  };
}

function renderPanel(
  next: QuotePreview | null,
  extras: { loading?: boolean; error?: string | null; closed?: boolean } = {},
) {
  const onRefresh = vi.fn();
  render(
    <QuotePreviewPanel
      closedMonthHint={extras.closed ?? false}
      error={extras.error ?? null}
      loading={extras.loading ?? false}
      onRefresh={onRefresh}
      preview={next}
    />,
  );
  return onRefresh;
}

const STATUS_CASES: Array<{ status: QuotePreviewStatus; label: string }> = [
  { status: "unmapped", label: "Внешний источник не настроен" },
  { status: "excluded", label: "Обновление отключено" },
  { status: "unsupported", label: "Обновляется вручную" },
  { status: "unavailable", label: "Подходящей котировки нет" },
  { status: "network_error", label: "Источник временно недоступен" },
  { status: "malformed_response", label: "Данные источника нельзя безопасно использовать" },
];

describe("QuotePreviewPanel", () => {
  it("does not fetch until the owner clicks the explicit button", async () => {
    const user = userEvent.setup();
    const onRefresh = renderPanel(null);
    expect(onRefresh).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Обновить котировки" }));
    expect(onRefresh).toHaveBeenCalledTimes(1);
  });

  it("shows current, proposed and price date for an OK row", () => {
    renderPanel(
      preview([
        row({
          position_snapshot_id: 1,
          instrument_id: 11,
          instrument_name: "Synthetic Stock",
          status: "ok",
        }),
      ]),
    );
    const table = screen.getByRole("table", { name: "Предпросмотр котировок" });
    expect(table).toHaveTextContent("Synthetic Stock");
    expect(table).toHaveTextContent(/200/);
    expect(table).toHaveTextContent(/215,50/);
    expect(table).toHaveTextContent("12.08.2026");
    expect(table).toHaveTextContent("Котировка получена");
    expect(table).toHaveTextContent(/\+15,50/);
  });

  it("shows a T-Invest identity and backend message without apply controls", () => {
    renderPanel(
      preview([
        row({
          position_snapshot_id: 8,
          instrument_id: 18,
          instrument_name: "T Stock",
          status: "unavailable",
          identity: {
            provider: "t_invest",
            provider_instrument_id: "11111111-1111-1111-1111-111111111111",
            provider_venue_id: null,
          },
          proposed_market_price_per_unit: null,
          proposed_price_date: null,
          apply_allowed: false,
          message: "T-Invest read-only token is not configured or is unavailable",
        }),
      ]),
    );
    expect(screen.getByText("T Stock")).toBeInTheDocument();
    expect(screen.getByText(/T-Invest · 11111111-1111-1111-1111-111111111111/)).toBeInTheDocument();
    expect(
      screen.getByText("T-Invest read-only token is not configured or is unavailable"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /примен/i })).not.toBeInTheDocument();
  });

  it("marks stale rows as old and not default-applicable", () => {
    renderPanel(
      preview([
        row({
          position_snapshot_id: 2,
          instrument_id: 12,
          instrument_name: "Stale Stock",
          status: "stale",
          apply_allowed: false,
          proposed_price_date: "2026-08-01",
        }),
      ]),
    );
    const stale = screen.getByText("Stale Stock").closest("tr");
    expect(stale).toHaveClass("quote-preview-row--stale");
    expect(stale).toHaveTextContent("Котировка старая");
    expect(stale).toHaveTextContent("Не обычное обновление");
    expect(stale).toHaveTextContent("01.08.2026");
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /примен/i })).not.toBeInTheDocument();
  });

  it.each(STATUS_CASES)(
    "keeps a $status row visible with a specific status",
    ({ status, label }) => {
      renderPanel(
        preview([
          row({
            position_snapshot_id: 3,
            instrument_id: 13,
            instrument_name: `Row ${status}`,
            status,
            mapping_state:
              status === "excluded" ? "excluded" : status === "unmapped" ? "unmapped" : "mapped",
            identity: status === "unmapped" ? null : identity,
            proposed_market_price_per_unit: null,
            proposed_price_date: null,
            apply_allowed: false,
          }),
        ]),
      );
      expect(screen.getByText(`Row ${status}`)).toBeInTheDocument();
      expect(screen.getByText(label)).toBeInTheDocument();
      expect(screen.queryByText("Ошибка")).not.toBeInTheDocument();
    },
  );

  it("preserves mixed success and failure rows", () => {
    renderPanel(
      preview([
        row({
          position_snapshot_id: 1,
          instrument_id: 11,
          instrument_name: "OK Stock",
          status: "ok",
        }),
        row({
          position_snapshot_id: 2,
          instrument_id: 12,
          instrument_name: "Broken Stock",
          status: "network_error",
          proposed_market_price_per_unit: null,
          apply_allowed: false,
        }),
      ]),
    );
    expect(screen.getByText("OK Stock")).toBeInTheDocument();
    expect(screen.getByText("Broken Stock")).toBeInTheDocument();
    expect(screen.getByText("Котировка получена")).toBeInTheDocument();
    expect(screen.getByText("Источник временно недоступен")).toBeInTheDocument();
  });

  it("shows a batch warning without erasing rows", () => {
    renderPanel(
      preview(
        [
          row({
            position_snapshot_id: 1,
            instrument_id: 11,
            instrument_name: "Kept Stock",
            status: "ok",
          }),
        ],
        {
          batch_error: "market-data provider network error",
        },
      ),
    );
    expect(screen.getByText(/Часть запросов к источнику не удалась/)).toBeInTheDocument();
    expect(screen.getByText("Kept Stock")).toBeInTheDocument();
  });

  it("allows closed-month preview and states that apply is unavailable", () => {
    renderPanel(
      preview(
        [
          row({
            position_snapshot_id: 1,
            instrument_id: 11,
            instrument_name: "Closed Stock",
            status: "ok",
            apply_allowed: false,
          }),
        ],
        {
          month_status: "closed",
          month_editable: false,
        },
      ),
      { closed: true },
    );
    expect(screen.getByRole("button", { name: "Обновить котировки" })).toBeEnabled();
    expect(screen.getByText(/нельзя изменить/)).toBeInTheDocument();
    expect(screen.getByText("Closed Stock")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /примен/i })).not.toBeInTheDocument();
  });

  it("handles an empty preview calmly", () => {
    renderPanel(preview([]));
    expect(screen.getByText("Предпросмотр пуст")).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "Предпросмотр котировок" })).not.toBeInTheDocument();
  });

  it("disables the action while loading", () => {
    renderPanel(null, { loading: true });
    expect(screen.getByRole("button", { name: "Обновляем…" })).toBeDisabled();
    expect(screen.getByText("Запрашиваем котировки…")).toBeInTheDocument();
  });

  it("shows a total request failure through the existing alert", () => {
    renderPanel(null, {
      error:
        "Не удалось подключиться к локальному приложению. Проверь, что Hermes Finance запущен.",
    });
    expect(screen.getByRole("alert")).toHaveTextContent("Не удалось подключиться");
  });
});
