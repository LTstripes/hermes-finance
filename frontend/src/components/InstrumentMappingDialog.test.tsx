import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Instrument, InstrumentMarketMapping, MarketDiscoverResult } from "../api/types";
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

const moexMapped: InstrumentMarketMapping = {
  ...unmapped,
  state: "mapped",
  identity: {
    provider: "moex_iss",
    provider_instrument_id: "SBER",
    provider_venue_id: "stock/shares/TQBR",
  },
};

const tInvestUid = "11111111-1111-1111-1111-111111111111";

const tInvestMapped: InstrumentMarketMapping = {
  ...unmapped,
  state: "mapped",
  identity: {
    provider: "t_invest",
    provider_instrument_id: tInvestUid,
    provider_venue_id: null,
  },
};

const discoverResult: MarketDiscoverResult = {
  status: "ok",
  message: null,
  candidates: [
    {
      provider: "t_invest",
      provider_instrument_id: tInvestUid,
      provider_venue_id: null,
      instrument_kind: "stock",
      isin: "RU0009029540",
    },
    {
      provider: "t_invest",
      provider_instrument_id: "22222222-2222-2222-2222-222222222222",
      provider_venue_id: null,
      instrument_kind: "stock",
      isin: "RU0009029540",
    },
  ],
  rejected: [],
};

function renderDialog(
  mapping: InstrumentMarketMapping,
  overrides: Partial<Parameters<typeof InstrumentMappingDialog>[0]> = {},
) {
  const onSave = vi.fn(async () => undefined);
  const onClear = vi.fn(async () => undefined);
  const onExclude = vi.fn(async () => undefined);
  const onClearExclusion = vi.fn(async () => undefined);
  const onDiscover = vi.fn(async () => discoverResult);
  render(
    <InstrumentMappingDialog
      busy={false}
      error={null}
      instrument={instrument}
      mapping={mapping}
      onCancel={vi.fn()}
      onClear={onClear}
      onClearExclusion={onClearExclusion}
      onDiscover={onDiscover}
      onExclude={onExclude}
      onSave={onSave}
      open
      {...overrides}
    />,
  );
  return { onSave, onClear, onExclude, onClearExclusion, onDiscover };
}

describe("InstrumentMappingDialog", () => {
  it("defaults a new mapping to T-Invest and does not discover on open", () => {
    const { onDiscover } = renderDialog(unmapped);
    expect(screen.getByRole("button", { name: "T-Invest" })).toBeInTheDocument();
    expect(screen.getByLabelText("Идентификатор инструмента T-Invest")).toHaveValue("");
    expect(screen.queryByLabelText("Режим торгов (boardid)")).not.toBeInTheDocument();
    expect(onDiscover).not.toHaveBeenCalled();
    expect(screen.queryByTestId("t-invest-candidates")).not.toBeInTheDocument();
  });

  it("shows unmapped state and never treats legacy moex_secid as accepted mapping", () => {
    renderDialog(unmapped);
    expect(screen.getByText("Не настроен")).toBeInTheDocument();
    expect(screen.getByTestId("accepted-mapping-identity")).toHaveTextContent(
      "Принятого источника нет",
    );
    expect(screen.getByTestId("legacy-moex-hint")).toHaveTextContent("SBER");
    expect(screen.getByTestId("legacy-moex-hint")).toHaveTextContent("не принятый источник");
  });

  it("keeps an existing MOEX mapping readable and editable", () => {
    renderDialog(moexMapped);
    expect(screen.getByText("Подключён")).toBeInTheDocument();
    expect(screen.getByTestId("accepted-mapping-identity")).toHaveTextContent(
      "moex_iss · stock/shares · TQBR · SBER",
    );
    expect(screen.getByLabelText("Код бумаги (secid)")).toHaveValue("SBER");
    expect(screen.getByTestId("moex-production-disabled-note")).toBeInTheDocument();
  });

  it("saves a manually entered T-Invest uid without a venue", async () => {
    const user = userEvent.setup();
    const { onSave } = renderDialog(unmapped);
    await user.type(screen.getByLabelText("Идентификатор инструмента T-Invest"), tInvestUid);
    await user.click(screen.getByRole("button", { name: "Сохранить источник" }));
    expect(onSave).toHaveBeenCalledWith({
      provider: "t_invest",
      provider_instrument_id: tInvestUid,
      provider_venue_id: null,
    });
  });

  it("finds T-Invest candidates only after an explicit click and does not save on choose", async () => {
    const user = userEvent.setup();
    const { onSave, onDiscover } = renderDialog(unmapped);
    await user.click(screen.getByRole("button", { name: "Найти в T-Invest" }));
    expect(onDiscover).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("t-invest-candidates")).toHaveTextContent(tInvestUid);
    expect(screen.getByTestId("t-invest-candidates")).toHaveTextContent(
      "22222222-2222-2222-2222-222222222222",
    );
    await user.click(screen.getByRole("button", { name: new RegExp(`Выбрать ${tInvestUid}`) }));
    expect(onSave).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Идентификатор инструмента T-Invest")).toHaveValue(tInvestUid);
    await user.click(screen.getByRole("button", { name: "Сохранить источник" }));
    expect(onSave).toHaveBeenCalledWith({
      provider: "t_invest",
      provider_instrument_id: tInvestUid,
      provider_venue_id: null,
      isin: "RU0009029540",
    });
  });

  it("drops candidate ISIN after the owner edits the UID by hand", async () => {
    const user = userEvent.setup();
    const { onSave } = renderDialog(unmapped);
    await user.click(screen.getByRole("button", { name: "Найти в T-Invest" }));
    await user.click(screen.getByRole("button", { name: new RegExp(`Выбрать ${tInvestUid}`) }));
    await user.type(screen.getByLabelText("Идентификатор инструмента T-Invest"), "9");
    await user.click(screen.getByRole("button", { name: "Сохранить источник" }));
    expect(onSave).toHaveBeenCalledWith({
      provider: "t_invest",
      provider_instrument_id: `${tInvestUid}9`,
      provider_venue_id: null,
    });
  });

  it("shows a calm token-not-configured message from discovery", async () => {
    const user = userEvent.setup();
    renderDialog(unmapped, {
      onDiscover: vi.fn(
        async (): Promise<MarketDiscoverResult> => ({
          status: "unavailable",
          message: "T-Invest read-only token is not configured or is unavailable",
          candidates: [],
          rejected: [],
        }),
      ),
    });
    await user.click(screen.getByRole("button", { name: "Найти в T-Invest" }));
    expect(screen.getByTestId("t-invest-discover-message")).toHaveTextContent(
      "T-Invest read-only token is not configured or is unavailable",
    );
  });

  it("saves the explicit MOEX identity the owner typed after switching", async () => {
    const user = userEvent.setup();
    const { onSave } = renderDialog(unmapped);
    await user.click(screen.getByRole("button", { name: "MOEX ISS" }));
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
    const { onClear, onExclude } = renderDialog(tInvestMapped);
    await user.click(screen.getByRole("button", { name: "Удалить источник" }));
    await user.click(screen.getByRole("button", { name: "Отключить обновление" }));
    expect(onClear).toHaveBeenCalledTimes(1);
    expect(onExclude).toHaveBeenCalledTimes(1);
  });

  it("preserves visible identity while excluded and can clear the exclusion", async () => {
    const user = userEvent.setup();
    const { onClearExclusion } = renderDialog({ ...tInvestMapped, state: "excluded" });
    expect(screen.getByText("Отключён")).toBeInTheDocument();
    expect(screen.getByTestId("accepted-mapping-identity")).toHaveTextContent(tInvestUid);
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
