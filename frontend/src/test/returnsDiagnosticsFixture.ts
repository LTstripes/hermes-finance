import type { Context, Overview } from "../ui-v2/returns/model";
import { unavailable } from "../ui-v2/returns/model";

/** Host reads added by the Returns consolidation; metric fixtures stay in each scenario. */
export function returnsDiagnosticsFixture(
  url: URL,
  accounts: { id: number; name: string }[] = [],
): Context | Overview | undefined {
  if (url.pathname === "/api/returns/context") {
    return {
      accounts: [
        { id: "portfolio", label: "Общий портфель", basis: "accepted" },
        ...accounts.map((account) => ({
          id: `account:${account.id}`,
          label: account.name,
          basis: "accepted" as const,
        })),
      ],
      source_periods: {},
      closed_periods: [],
      default_period: null,
    };
  }
  if (url.pathname === "/api/returns/overview") {
    return {
      scope: url.searchParams.get("scope") ?? "",
      selected: {
        valuation_date: null,
        period: {
          start: url.searchParams.get("start") ?? "",
          end: url.searchParams.get("end") ?? "",
        },
        pnl: unavailable,
        rate: { ...unavailable, unit: "fraction" },
        coupons: unavailable,
        dividends: unavailable,
      },
      all_history: null,
      history: [],
      periods: [],
      instruments: [],
      instrument_reason_codes: [],
      proof_status: "absent",
    };
  }
}
