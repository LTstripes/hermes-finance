import { type Metric, unavailable } from "./model";
import type { Overall, OverallInstrument } from "./overall";

/** Exact presentation sums; eligibility remains the producer's. */
export function knownMoney(values: Metric[]): Metric {
  const known = values.filter(
    (m): m is Metric & { value: string } =>
      m.unit === "kopecks" && m.value !== null && /^-?\d+$/.test(m.value),
  );
  return {
    ...unavailable,
    value: known.length ? known.reduce((sum, m) => sum + BigInt(m.value), 0n).toString() : null,
    method: "known_nonoverlapping_components",
    estimate: known.some((m) => m.estimate),
    reason_codes: [
      ...new Set([
        ...values.flatMap((m) => m.reason_codes),
        ...(known.length === values.length ? [] : ["selected_components_incomplete"]),
      ]),
    ],
  };
}
export function selectedAccounts(data: Overall, scope: string) {
  return data.source_accounts.filter((a) => scope === "all" || a.scope === scope);
}
export function brokerageResult(data: Overall, scope: string) {
  const components = data.mixed_result.components.filter(
    (c) =>
      ["brokerage", "iis", "brokerage_iis"].includes(c.category) &&
      (scope === "all" || c.id === scope),
  );
  const eligible = components.filter(
    (component) => component.included || (scope !== "all" && component.available),
  );
  const periods = new Set(
    eligible.filter((c) => c.period).map((c) => `${c.period?.start}/${c.period?.end}`),
  );
  return {
    amount: periods.size > 1 ? unavailable : knownMoney(eligible.map((c) => c.amount)),
    partial:
      periods.size > 1 ||
      components.some((c) => !c.included || c.amount.value === null || c.amount.estimate),
  };
}
export function selectedIncome(data: Overall, scope: string, kind: "coupon" | "dividend") {
  const income = kind === "coupon" ? data.coupon_income : data.dividend_income;
  const accounts = income.accounts.filter((a) => scope === "all" || a.scope === scope);
  const periods = new Set(
    accounts
      .filter((a) => a.included && a.period)
      .map((a) => `${a.period?.start}/${a.period?.end}`),
  );
  const conflict =
    accounts.length > 1 &&
    accounts.some((account) =>
      data.mixed_result.components.some(
        (component) => component.id === account.scope && component.coverage.status === "conflict",
      ),
    );
  return {
    ...income,
    accounts,
    selected_accounts: selectedAccounts(data, scope).length,
    included_accounts: accounts.filter((a) => a.included).length,
    known_total:
      periods.size > 1 || conflict
        ? unavailable
        : knownMoney(accounts.filter((a) => a.included).map((a) => a.amount)),
  };
}
export function instrumentSummary(data: Overall, row: OverallInstrument, scope: string) {
  const accounts = row.accounts.filter((a) => scope === "all" || a.scope === scope);
  const eligible = accounts.filter(
    (a) =>
      a.native_period === true ||
      (data.source_accounts.some((s) => s.scope === a.scope && s.proof_status === "current") &&
        !data.mixed_result.components.some(
          (c) =>
            ["brokerage", "iis", "brokerage_iis"].includes(c.category) &&
            c.id === a.scope &&
            c.coverage.status === "conflict",
        )),
  );
  const values = eligible.filter((a) => a.details_loaded);
  const periods = new Set(
    values.filter((a) => a.period).map((a) => `${a.period?.start}/${a.period?.end}`),
  );
  const aggregationUnsafe =
    periods.size > 1 ||
    (values.length > 1 &&
      values.some((a) =>
        data.mixed_result.components.some(
          (c) => c.id === a.scope && c.coverage.status === "conflict",
        ),
      ));
  return {
    ...row,
    accounts: accounts.map((a) => ({
      ...a,
      resultAvailable: eligible.includes(a) && a.details_loaded,
    })),
    pnl: aggregationUnsafe ? unavailable : knownMoney(values.map((a) => a.pnl)),
    coupons: aggregationUnsafe ? unavailable : knownMoney(values.map((a) => a.coupons)),
    dividends: aggregationUnsafe ? unavailable : knownMoney(values.map((a) => a.dividends)),
    rate:
      values.length === 1 && accounts.length === 1
        ? values[0].rate
        : { ...unavailable, unit: "fraction" as const },
    partial: values.length !== accounts.length || values.some((a) => a.pnl.value === null),
  };
}
export const compactQuantity = (value: string) =>
  value.includes(".") ? value.replace(/0+$/, "").replace(/\.$/, "") : value;
const aliasKey = "hermes.returns.account-display-names.v1";
export function readDisplayNames(): Record<string, string> {
  try {
    const raw: unknown = JSON.parse(localStorage.getItem(aliasKey) ?? "{}");
    return raw && typeof raw === "object" && !Array.isArray(raw)
      ? Object.fromEntries(
          Object.entries(raw).filter(
            ([k, v]) =>
              k.startsWith("source:") &&
              typeof v === "string" &&
              v.trim().length > 0 &&
              v.length <= 80,
          ),
        )
      : {};
  } catch {
    return {};
  }
}
export function saveDisplayNames(names: Record<string, string>) {
  localStorage.setItem(aliasKey, JSON.stringify(names));
}
