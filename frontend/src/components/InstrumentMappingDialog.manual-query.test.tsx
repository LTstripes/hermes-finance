import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Instrument, InstrumentMarketMapping, MarketDiscoverResult } from "../api/types";
import { InstrumentMappingDialog } from "./InstrumentMappingDialog";

const instrument: Instrument = {
  id: 10,
  name: "Сбербанк",
  instrument_type: "stock",
  isin: "RU0009029540",
  ticker: "SBER",
  moex_secid: "SBER",
  currency: "RUB",
  nominal_value: null,
  is_active: true,
  manual_price_allowed: true,
  notes: null,
};

const mapping: InstrumentMarketMapping = {
  instrument_id: 10,
  state: "unmapped",
  identity: null,
  instrument_isin: "RU0009029540",
  legacy_moex_secid: "SBER",
};

const emptyResult: MarketDiscoverResult = {
  status: "unavailable",
  message: "Подходящих инструментов T-Invest не найдено.",
  candidates: [],
  rejected: [],
};

function renderDialog(onDiscover: Parameters<typeof InstrumentMappingDialog>[0]["onDiscover"]) {
  render(
    <InstrumentMappingDialog
      busy={false}
      error={null}
      instrument={instrument}
      mapping={mapping}
      onCancel={vi.fn()}
      onClear={vi.fn(async () => undefined)}
      onClearExclusion={vi.fn(async () => undefined)}
      onDiscover={onDiscover}
      onExclude={vi.fn(async () => undefined)}
      onSave={vi.fn(async () => undefined)}
      open
    />,
  );
}

describe("InstrumentMappingDialog manual discovery query", () => {
  it("does not call T-Invest on open or while typing and sends the trimmed query on explicit click", async () => {
    const user = userEvent.setup();
    const onDiscover = vi.fn(async () => emptyResult);
    renderDialog(onDiscover);

    const query = screen.getByLabelText("Название, тикер или ISIN");
    expect(query).toHaveValue("");
    expect(onDiscover).not.toHaveBeenCalled();

    await user.type(query, "  SBER  ");
    expect(onDiscover).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Найти в T-Invest" }));
    expect(onDiscover).toHaveBeenCalledTimes(1);
    expect(onDiscover).toHaveBeenCalledWith("t_invest", "SBER");
  });

  it("preserves default discovery when the manual query is blank", async () => {
    const user = userEvent.setup();
    const onDiscover = vi.fn(async () => emptyResult);
    renderDialog(onDiscover);

    expect(onDiscover).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Найти в T-Invest" }));
    expect(onDiscover).toHaveBeenCalledWith("t_invest", null);
  });
});
