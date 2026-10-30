import { describe, expect, it } from "vitest";

import {
  accountBucketKey,
  assetClassForInstrumentType,
  buildHoldingRows,
  filterHoldingRows,
  holdingReturnsNavigation,
  UNASSIGNED_CASH_KEY,
} from "./capitalHoldings";
import {
  makeUiV2Cash,
  makeUiV2Deposits,
  makeUiV2Positions,
  uiV2Accounts,
  uiV2Instruments,
} from "../test/uiV2Fixtures";

function rows() {
  return buildHoldingRows({
    accounts: uiV2Accounts,
    cash: makeUiV2Cash(),
    deposits: makeUiV2Deposits(),
    instruments: uiV2Instruments,
    positions: makeUiV2Positions(),
  });
}

describe("capitalHoldings", () => {
  it("maps an instrument type to the canonical liquid class only", () => {
    expect(assetClassForInstrumentType("stock")).toBe("stocks");
    expect(assetClassForInstrumentType("bond")).toBe("bonds");
    expect(assetClassForInstrumentType("fund")).toBe("gold_other");
    expect(assetClassForInstrumentType("gold")).toBe("gold_other");
    expect(assetClassForInstrumentType(null)).toBe("gold_other");
  });

  it("keeps backend row amounts, class and account context unchanged", () => {
    const built = rows();
    expect(built.map((row) => row.key)).toEqual([
      "cash-701",
      "cash-702",
      "deposit-601",
      "deposit-602",
      "position-501",
      "position-502",
      "position-503",
    ]);
    const wallet = built[0];
    expect(wallet.assetClass).toBe("cash");
    expect(wallet.amount.amount).toBe("803900.00");
    expect(wallet.includeInCapital).toBe(true);
    const excludedDeposit = built[3];
    expect(excludedDeposit.includeInCapital).toBe(false);
    expect(excludedDeposit.accountName).toBe("Синтетический старый вклад");
    const fund = built[6];
    expect(fund.name).toBe("Синтетический фонд");
    expect(fund.assetClass).toBe("gold_other");
    expect(fund.includeInCapital).toBe(false);
  });

  it("never invents a name for a position without a catalog instrument", () => {
    const built = buildHoldingRows({
      accounts: uiV2Accounts,
      cash: [],
      deposits: [],
      instruments: [],
      positions: makeUiV2Positions(),
    });
    expect(built.map((row) => row.name)).toEqual([
      "Инструмент без названия в справочнике",
      "Инструмент без названия в справочнике",
      "Инструмент без названия в справочнике",
    ]);
    expect(built.every((row) => row.includeInCapital === false)).toBe(false);
    expect(built.map((row) => row.assetClass)).toEqual(["gold_other", "gold_other", "gold_other"]);
  });

  it("filters by canonical class as presentation only", () => {
    const built = rows();
    expect(
      filterHoldingRows(built, { kind: "class", label: "Акции", value: "stocks" }),
    ).toHaveLength(1);
    expect(
      filterHoldingRows(built, { kind: "class", label: "Депозиты", value: "deposits" }),
    ).toHaveLength(2);
    expect(
      filterHoldingRows(built, { kind: "class", label: "Золото", value: "gold_other" }),
    ).toHaveLength(1);
    expect(filterHoldingRows(built, null)).toHaveLength(7);
  });

  it("keeps cash out of account buckets and inside the unassigned cash bucket", () => {
    const built = rows();
    const accountThree = filterHoldingRows(built, {
      kind: "account",
      label: "Синтетический брокерский счёт",
      value: accountBucketKey(3),
    });
    expect(accountThree.map((row) => row.key)).toEqual(["position-501", "position-502"]);
    const cashBucket = filterHoldingRows(built, {
      kind: "account",
      label: "наличные",
      value: UNASSIGNED_CASH_KEY,
    });
    expect(cashBucket.map((row) => row.key)).toEqual(["cash-701"]);
    const excludedAccount = filterHoldingRows(built, {
      kind: "account",
      label: "вне капитала",
      value: accountBucketKey(4),
    });
    expect(excludedAccount).toEqual([]);
  });

  it("ignores an unparsable account bucket instead of matching everything", () => {
    expect(
      filterHoldingRows(rows(), { kind: "account", label: "сломанный", value: "account:abc" }),
    ).toEqual([]);
  });
});

it("uses exact position/catalogue IDs and ISIN despite duplicate display names", () => {
  const instruments = uiV2Instruments.map((instrument) => ({
    ...instrument,
    name: "Одинаковое имя",
    isin: instrument.id === 10 ? "RU000A000010" : "RU000A000011",
  }));
  const built = buildHoldingRows({
    accounts: uiV2Accounts,
    instruments,
    positions: makeUiV2Positions(),
    cash: [],
    deposits: [],
  });
  expect(built[0]).toMatchObject({ instrumentId: 10, isin: "RU000A000010", accountId: 3 });
  expect(holdingReturnsNavigation(built[0]).href).toBe(
    "/v2/returns?isin=RU000A000010&capital_account=3",
  );
  expect(holdingReturnsNavigation(built[1]).href).toBe(
    "/v2/returns?isin=RU000A000011&capital_account=3",
  );
});
it.each([0, -1, 3.5, Number.MAX_SAFE_INTEGER + 1])(
  "invalid canonical account ID %s cannot make a Returns link",
  (id) => {
    const row = rows().find((item) => item.kind === "position");
    if (!row) throw new Error("missing synthetic position");
    expect(
      holdingReturnsNavigation({ ...row, accountId: id, isin: "RU000A000010" }).href,
    ).toBeNull();
  },
);
it("unproven or conflicting catalogue identity remains non-link; exact gold IDs are distinct", () => {
  const instruments = [
    { ...uiV2Instruments[0], isin: "RU000A000010" },
    { ...uiV2Instruments[0], isin: "RU000A000011" },
    { ...uiV2Instruments[1], instrument_type: "gold", isin: null },
  ];
  const built = buildHoldingRows({
    accounts: uiV2Accounts,
    instruments,
    positions: makeUiV2Positions(),
    cash: [],
    deposits: [],
  });
  expect(built[0].instrumentId).toBe(10);
  expect(holdingReturnsNavigation(built[0]).href).toBeNull();
  expect(holdingReturnsNavigation(built[0]).reason).toBeTruthy();
  expect(holdingReturnsNavigation(built[1]).href).toBe(
    "/v2/returns?capital_account=3&gold_instrument=11#returns-gold",
  );
  expect(holdingReturnsNavigation(built[2]).href).toBeNull();
});
it("missing ISIN and invalid instrument IDs never guess from names or tickers", () => {
  const row = rows().find((item) => item.kind === "position");
  if (!row) throw new Error("missing synthetic position");
  expect(holdingReturnsNavigation(row).href).toBeNull();
  expect(holdingReturnsNavigation({ ...row, isin: "not-an-isin" }).href).toBeNull();
  expect(
    holdingReturnsNavigation({ ...row, instrumentId: 0, isin: "RU000A000010" }).href,
  ).toBeNull();
});
