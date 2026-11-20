import { apiRequest } from "./client";
import type { MoneyValue } from "./types";

export type ReservePlan = {
  start: string;
  end: string;
  sources: { key: string; portion: string | null }[];
  categories: { id: number; estimate: string | null }[];
  months: string[];
};
export type ReserveView = {
  revision: number;
  plan: ReservePlan;
  gaps: string[];
  reserve: MoneyValue | null;
  monthly: MoneyValue | null;
  coverage_months: string | null;
  target: MoneyValue | null;
  difference: MoneyValue | null;
  snapshot_date: string | null;
  history_coverage: {
    month: string;
    full: boolean;
    manual: boolean;
    accounts: number;
    same_sources: boolean;
    unresolved: boolean;
  }[];
  sources: { key: string; label: string; kind: string; balance: MoneyValue | null }[];
  categories: { id: number; name: string }[];
  basis: { id: number; name: string; method: "estimate" | "history"; amount: MoneyValue | null }[];
  calendar: {
    month: string;
    variable: MoneyValue | null;
    payments: { rule_id: number; date: string; title: string; amount: MoneyValue }[];
    total: MoneyValue | null;
  }[];
  rules: {
    id: number;
    title: string;
    amount: MoneyValue | null;
    period_months: number | null;
    next_due: string | null;
    needs_review: boolean;
  }[];
};
const path = "/api/spending/reserve";
export const getReserve = (signal?: AbortSignal) => apiRequest<ReserveView>(path, { signal });
export const putReserve = (plan: ReservePlan, revision: number) =>
  apiRequest<ReserveView>(path, { method: "PUT", body: { plan, expected_revision: revision } });
