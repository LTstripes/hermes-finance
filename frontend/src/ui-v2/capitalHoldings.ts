import type {
  Account,
  CashBalance,
  DepositSnapshot,
  Instrument,
  MoneyValue,
  PositionSnapshot,
} from "../api/types";

/**
 * Observe-only holdings rows for the native Capital page.
 *
 * Pure presentation mapping over already-fetched backend rows: no totals are
 * computed here, and the canonical class of a position follows the accepted
 * rule `stock → stocks`, `bond → bonds`, everything else → `gold_other`.
 */

export type HoldingKind = "cash" | "deposit" | "position";

export type HoldingRow = {
  key: string;
  kind: HoldingKind;
  name: string;
  /** Backend row context, not a capital-relevant fact. */
  contextLabel: string | null;
  accountId: number | null;
  accountName: string | null;
  /** The row amount exactly as the backend returned it. */
  amount: MoneyValue;
  includeInCapital: boolean;
  assetClass: string;
};

export type HoldingFilter =
  | { kind: "class"; value: string; label: string }
  | { kind: "account"; value: string; label: string }
  | null;

export const UNASSIGNED_CASH_KEY = "unassigned_cash";

export function accountBucketKey(accountId: number): string {
  return `account:${accountId}`;
}

/** Canonical liquid class of a brokerage position. */
export function assetClassForInstrumentType(instrumentType: string | null | undefined): string {
  if (instrumentType === "stock") return "stocks";
  if (instrumentType === "bond") return "bonds";
  return "gold_other";
}

const MISSING_ACCOUNT_NAME = "Счёт не найден";

function accountMaps(accounts: Account[]): {
  names: Map<number, string>;
  included: Map<number, boolean>;
} {
  return {
    names: new Map(accounts.map((account) => [account.id, account.name])),
    included: new Map(accounts.map((account) => [account.id, account.include_in_capital])),
  };
}

export function buildHoldingRows({
  accounts,
  cash,
  deposits,
  instruments,
  positions,
}: {
  accounts: Account[];
  cash: CashBalance[];
  deposits: DepositSnapshot[];
  instruments: Instrument[];
  positions: PositionSnapshot[];
}): HoldingRow[] {
  const accountInfo = accountMaps(accounts);
  const instrumentNames = new Map(instruments.map((item) => [item.id, item.name]));
  const instrumentTypes = new Map(instruments.map((item) => [item.id, item.instrument_type]));

  const cashRows: HoldingRow[] = [...cash]
    .sort((a, b) => a.id - b.id)
    .map((row) => ({
      key: `cash-${row.id}`,
      kind: "cash",
      name: row.name,
      contextLabel: null,
      accountId: row.account_id,
      accountName: row.account_id == null ? null : (accountInfo.names.get(row.account_id) ?? null),
      amount: row.amount,
      includeInCapital: row.include_in_capital,
      assetClass: "cash",
    }));

  const depositRows: HoldingRow[] = [...deposits]
    .sort((a, b) => a.account_id - b.account_id || a.id - b.id)
    .map((row) => ({
      key: `deposit-${row.id}`,
      kind: "deposit",
      name: row.name,
      contextLabel: null,
      accountId: row.account_id,
      accountName: accountInfo.names.get(row.account_id) ?? MISSING_ACCOUNT_NAME,
      amount: row.balance,
      includeInCapital: accountInfo.included.get(row.account_id) ?? false,
      assetClass: "deposits",
    }));

  const positionRows: HoldingRow[] = [...positions]
    .sort((a, b) => a.account_id - b.account_id || a.instrument_id - b.instrument_id || a.id - b.id)
    .map((row) => {
      const instrumentType = instrumentTypes.get(row.instrument_id) ?? null;
      return {
        key: `position-${row.id}`,
        kind: "position",
        name: instrumentNames.get(row.instrument_id) ?? "Инструмент без названия в справочнике",
        contextLabel: instrumentType,
        accountId: row.account_id,
        accountName: accountInfo.names.get(row.account_id) ?? MISSING_ACCOUNT_NAME,
        amount: row.market_value,
        includeInCapital: accountInfo.included.get(row.account_id) ?? false,
        assetClass: assetClassForInstrumentType(instrumentType),
      };
    });

  return [...cashRows, ...depositRows, ...positionRows];
}

/**
 * Presentation filter over already-fetched rows.
 *
 * A class filter matches every row of that canonical class, because the class
 * totals come from the backend read model. An account filter matches the
 * canonical R07-06A buckets: `unassigned_cash` covers included cash rows, and
 * `account:<id>` covers deposits and positions of that account.
 */
export function filterHoldingRows(rows: HoldingRow[], filter: HoldingFilter): HoldingRow[] {
  if (filter == null) return rows;
  if (filter.kind === "class") return rows.filter((row) => row.assetClass === filter.value);
  if (filter.value === UNASSIGNED_CASH_KEY) {
    return rows.filter((row) => row.kind === "cash" && row.includeInCapital);
  }
  const accountId = Number(filter.value.slice("account:".length));
  if (!Number.isSafeInteger(accountId)) return [];
  return rows.filter(
    (row) => row.kind !== "cash" && row.accountId === accountId && row.includeInCapital,
  );
}
