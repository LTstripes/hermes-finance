import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Instrument, InstrumentMarketMapping } from "../api/types";
import { InstrumentMappingDialog } from "./InstrumentMappingDialog";

const instrument: Instrument = {
  id: 10,
  name: "Synthetic Stock",
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

const unmapped: InstrumentMarketMapping = {
  instrument_id: 10,
  state: "unmapped",
  identity: null,
  instrument_isin: "RU0009029540",
  legacy_moex_secid: "SBER",
};

const mapped: InstrumentMarketMapping = {
  ...unmapped,
  state: "mapped",
  identity: {
    provider: "moex_iss",
    provider_instrument_id: "SBER",
    provider_venue_id: "stock/shares/TQBR",
  },
};

function renderDialog(
  mapping: InstrumentMarketMapping,
  overrides: Partial<Parameters<typeof InstrumentMappingDialog>[0]> = {},
) {
  const onSave = vi.fn(async () => undefined);
  const onClear = vi.fn(async () => undefined);
  const onExclude = vi.fn(async () => undefined);
  const onClearExclusion = vi.fn(async () => undefined);
  render(
    <InstrumentMappingDialog
      busy={false}
      error={null}
      instrument={instrument}
      mapping={mapping}
      onCancel={vi.fn()}
      onClear={onClear}
      onClearExclusion={onClearExclusion}
      onExclude={onExclude}
      onSave={onSave}
      open
      {...overrides}
    />,
  );
  return { onSave, onClear, onExclude, onClearExclusion };
}

describe("InstrumentMappingDialog", () => {
  it("shows unmapped state and never treats legacy moex_secid as accepted mapping", () => {
    renderDialog(unmapped);
    expect(screen.getByText("Не настроен")).toBeInTheDocument();
    expect(screen.getByTestId("accepted-mapping-identity")).toHaveTextContent(
      "Принятого источника нет",
    );
    expect(screen.getByTestId("legacy-moex-hint")).toHaveTextContent("SBER");
    expect(screen.getByTestId("legacy-moex-hint")).toHaveTextContent("не принятый источник");
    expect(screen.getByLabelText("Код бумаги (secid)")).toHaveValue("");
  });

  it("shows a complete accepted identity for a mapped instrument", () => {
    renderDialog(mapped);
    expect(screen.getByText("Подключён")).toBeInTheDocument();
    expect(screen.getByTestId("accepted-mapping-identity")).toHaveTextContent(
      "moex_iss · stock/shares · TQBR · SBER",
    );
  });

  it("saves the explicit identity the owner typed", async () => {
    const user = userEvent.setup();
    const { onSave } = renderDialog(unmapped);
    await user.clear(screen.getByLabelText("Режим торгов (boardid)"));
    await user.type(screen.getByLabelText("Режим торгов (boardid)"), "TQBR");
    await user.type(screen.getByLabelText("Код бумаги (secid)"), "SBER");
    await user.click(screen.getByRole("button", { name: "Сохранить источник" }));
    expect(onSave).toHaveBeenCalledWith({
      provider: "moex_iss",
      provider_instrument_id: "SBER",
      provider_venue_id: "stock/shares/TQBR",
    });
  });

  it("clears a mapping and excludes or restores through explicit actions", async () => {
    const user = userEvent.setup();
    const { onClear, onExclude } = renderDialog(mapped);
    await user.click(screen.getByRole("button", { name: "Удалить источник" }));
    await user.click(screen.getByRole("button", { name: "Отключить обновление" }));
    expect(onClear).toHaveBeenCalledTimes(1);
    expect(onExclude).toHaveBeenCalledTimes(1);
  });

  it("preserves visible identity while excluded and can clear the exclusion", async () => {
    const user = userEvent.setup();
    const { onClearExclusion } = renderDialog({ ...mapped, state: "excluded" });
    expect(screen.getByText("Отключён")).toBeInTheDocument();
    expect(screen.getByTestId("accepted-mapping-identity")).toHaveTextContent("TQBR");
    await user.click(screen.getByRole("button", { name: "Включить обновление" }));
    expect(onClearExclusion).toHaveBeenCalledTimes(1);
  });

  it("renders mapping errors through the existing alert", () => {
    renderDialog(unmapped, { error: "Проверь введённые данные." });
    expect(screen.getByRole("alert")).toHaveTextContent("Проверь введённые данные.");
  });

  it("keeps unsupported instruments on the manual path", () => {
    renderDialog(unmapped, {
      instrument: { ...instrument, name: "Synthetic Gold", instrument_type: "gold" },
    });
    expect(screen.getByText(/обновляется вручную/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Сохранить источник" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Отключить обновление" })).toBeInTheDocument();
  });
});
