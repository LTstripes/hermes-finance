import type {
  SpendingHistoryItem,
  SpendingMonth,
  SpendingOperation,
  SpendingPreview,
} from "../src/api/spending";

import type { PaymentCard } from "../src/api/spendingPayments";
import type { ReserveView } from "../src/api/spendingReserve";

const money = (amount: string) => ({ amount, currency: "RUB" });
const months = [
  "2025-11",
  "2025-12",
  "2026-01",
  "2026-02",
  "2026-03",
  "2026-04",
  "2026-05",
  "2026-06",
  "2026-07",
  "2026-08",
  "2026-09",
  "2026-10",
];
const selected = "2026-10";
const coverage = { from: "2026-10-01", to: "2026-10-31", full: true };
const emptyCoverage = { from: null, to: null, full: false };
const typed = { mandatory: money("35000"), comfortable: money("6000"), other: money("10500") };
const noTypes = { mandatory: null, comfortable: null, other: null };
const loaded = new Set(["2026-06", "2026-08", "2026-09", selected]);

function historyItem(month: string, hasData: boolean): SpendingHistoryItem {
  const partial = hasData && month === "2026-08";
  return {
    month,
    loaded: hasData,
    total: hasData ? money("51500") : null,
    by_type: hasData ? typed : noTypes,
    coverage: hasData
      ? { from: `${month}-01`, to: `${month}-${partial ? "16" : "30"}`, full: !partial }
      : emptyCoverage,
    partial,
    has_statement: hasData,
    has_manual: hasData && month !== "2026-09",
    refunds_total: hasData ? money("-250") : null,
    month_entries_total: money(hasData ? "35000" : "0"),
  };
}
const item: SpendingOperation = {
  id: 1,
  date: "2026-10-04",
  description: "Тестовый магазин",
  category_id: 2,
  category_name: "Покупки",
  source: "alfa",
  amount: money("4000"),
  kind: "purchase",
  processing: true,
  linked_entry: null,
  is_month_entry: false,
};
const categories = [
  { id: 1, name: "Аренда", expense_type: "mandatory" },
  { id: 2, name: "Покупки", expense_type: "comfortable" },
  { id: 3, name: "Без категории", expense_type: "other" },
] as const;
const monthData: SpendingMonth = {
  ...historyItem(selected, true),
  coverage,
  known_subtotal: money("51500"),
  by_source: {
    alfa: money("11900"),
    cash: money("4250"),
    sber: money("350"),
    manual_other: money("0"),
    month_entries: money("35000"),
  },
  processing_total: money("4000"),
  categories: [
    {
      ...categories[0],
      type: "mandatory",
      amount: money("35000"),
      share_percent: "67.96",
      average_3m: money("35000"),
      delta_percent: "0",
      is_new: false,
    },
    {
      ...categories[1],
      type: "comfortable",
      amount: money("6000"),
      share_percent: "11.65",
      average_3m: money("2000"),
      delta_percent: "200",
      is_new: false,
    },
    {
      ...categories[2],
      type: "other",
      amount: money("10500"),
      share_percent: "20.39",
      average_3m: null,
      delta_percent: null,
      is_new: true,
    },
  ],
  positive_categories: [],
  comparison: {
    average_total: money("43000"),
    delta_percent: "19.8",
    months: [
      { month: "2026-06", has_manual: true },
      { month: "2026-09", has_manual: false },
    ],
  },
  cash: { withdrawn: null, recorded: money("4250") },
  entry_links: [
    {
      id: 7,
      expense_entry_id: 5,
      entry_category: "Интернет",
      month_amount: money("230"),
      diary_amount: money("230"),
      automatic: false,
      confirmed: true,
      operation_ids: [1],
    },
  ],
  open_exceptions: { count: 2, excluded_count: 1, double_risk_count: 1 },
  top_purchases: [item],
  daily: {
    current: Array.from({ length: 31 }, (_, index) => ({
      day: index + 1,
      cumulative: money((Math.floor(index / 3) * 1500).toString()),
    })),
    previous: {
      month: "2026-09",
      points: Array.from({ length: 30 }, (_, index) => ({
        day: index + 1,
        cumulative: money((Math.floor(index / 4) * 1100).toString()),
      })),
    },
    previous_unavailable_reason: null,
    undated_total: money("1500"),
    month_entries_total: money("35000"),
  },
};
monthData.positive_categories = monthData.categories;

const removed = {
  id: 12,
  operation_date: "2026-10-12",
  description: "Тестовая аптека",
  category: "Здоровье",
  amount_kopecks: 64000,
  currency: "RUB",
  fingerprint: "0".repeat(64),
  ordinal: 1,
};
const preview: SpendingPreview = {
  month: selected,
  preview_id: "synthetic-spending-preview",
  stale: false,
  applicable: true,
  total_before: money("51500"),
  total_after: money("52150"),
  sets: [
    {
      label: "Тестовый счёт ··0001",
      kind: "statement",
      added: 12,
      changed: 0,
      removed: 1,
      total_before: money("11900"),
      total_after: money("12550"),
      removed_items: [removed],
      changed_items: [],
    },
    {
      label: "Ручной файл",
      kind: "manual",
      added: 4,
      changed: 0,
      removed: 0,
      total_before: null,
      total_after: money("4600"),
      removed_items: [],
      changed_items: [],
    },
  ],
  exceptions: [
    {
      id: "synthetic-transfer",
      group: "transfer",
      date: "2026-10-10",
      description: "СБП Тестовый получатель",
      amount: money("950"),
      bank_category: "Переводы",
      candidates: [],
      remember_key: "ТЕСТОВЫЙ ПОЛУЧАТЕЛЬ",
      remember_default: false,
      carried_over_failed: false,
      counted_now: false,
      kind_hint: null,
      recurring: false,
    },
  ],
  operations: [],
  technical: { count: 0, items: [] },
  processing: { count: 1, amount: money("4000") },
  coverage,
  out_of_month: { count: 2, from: "2026-09-28", to: "2026-09-30" },
  file_errors: [],
  blocking: { needs_removal_confirmation: true, unreadable_manual_rows: [] },
  entry_links: [],
  added: 16,
  changed: 0,
  removed: 1,
};

const annualCard: PaymentCard = {
  token: "synthetic-card",
  title: item.description,
  fact_amount: item.amount.amount,
  category_mandatory: false,
  schedules: [],
  decisions: [],
  rule: {
    id: 8,
    title: item.description,
    month: selected,
    source: "alfa",
    operation_id: item.id,
    note: "Продление годовой подписки",
    mandatory_override: true,
    mandatory: true,
    repeat: true,
    period_months: 12,
    next_due: "2027-10-04",
    amount: "24000",
    monthly_amount: "2000",
    needs_review: false,
    archived: false,
    was_recurring: true,
    occurrences: [],
    version: 1,
  },
};

function reserveView(complete: boolean): ReserveView {
  const renewal = {
    rule_id: 8,
    date: "2027-10-04",
    title: item.description,
    amount: money("24000"),
  };
  return {
    revision: 1,
    plan: {
      start: "2027-10-01",
      end: "2027-10-31",
      sources: [{ key: "synthetic", portion: null }],
      categories: complete ? [] : [{ id: 2, estimate: null }],
      months: [],
    },
    gaps: complete ? [] : ["Для категории «Покупки» недостаточно истории."],
    reserve: money("24000"),
    monthly: complete ? money("2000") : null,
    coverage_months: complete ? "12" : null,
    target: complete ? money("24000") : null,
    difference: complete ? money("0") : null,
    snapshot_date: "2026-10-31",
    payment_candidates: [],
    history_coverage: [],
    sources: [
      { key: "synthetic", label: "Учебный вклад", kind: "deposit", balance: money("24000") },
    ],
    categories: [{ id: 2, name: "Покупки" }],
    basis: complete ? [] : [{ id: 2, name: "Покупки", method: "history", amount: null }],
    calendar: [
      {
        month: "2027-10",
        variable: complete ? money("0") : null,
        payments: [renewal],
        total: complete ? money("24000") : null,
      },
    ],
    rules: [
      {
        id: 8,
        title: item.description,
        amount: money("24000"),
        period_months: 12,
        monthly: money("2000"),
        next_due: renewal.date,
        needs_review: false,
      },
    ],
  };
}

export function spendingVisualResponse(
  url: URL,
  method: string,
  state: "content" | "empty" | "error",
) {
  const path = url.pathname;
  if (!path.startsWith("/api/spending/")) return null;
  const content = state === "content";
  if (state === "error")
    return { status: 503, json: { error: { code: "unavailable", message: "Недоступно" } } };
  if (path === "/api/spending/months")
    return {
      json: {
        items: months.map((month) => historyItem(month, content && loaded.has(month))),
        has_more: false,
      },
    };
  if (path.startsWith("/api/spending/months/"))
    return {
      json: content
        ? monthData
        : {
            ...monthData,
            ...historyItem(selected, false),
            month_entries_total: money("0"),
          },
    };
  if (path === "/api/spending/operations")
    return {
      json: {
        items: content ? [item] : [],
        total_count: content ? 1 : 0,
        filtered_total: money(content ? "4000" : "0"),
      },
    };
  if (path === "/api/spending/reserve" && method === "GET") return { json: reserveView(content) };
  if (path === "/api/spending/payment-rules/alfa/1" && method === "GET")
    return { json: annualCard };
  if (path === "/api/spending/payment-rules" && method === "GET") return { json: [] };
  if (path === "/api/spending/categories") return { json: content ? categories : [] };
  if (path === "/api/spending/rules")
    return {
      json: content
        ? [
            {
              id: 1,
              scope: "merchant",
              key: "ТЕСТОВЫЙ ПОЛУЧАТЕЛЬ",
              action: "not_spending",
              category_id: null,
            },
          ]
        : [],
    };
  if (path === "/api/spending/entry-links")
    return {
      json: content ? monthData.entry_links.map((row) => ({ ...row, month: selected })) : [],
    };
  if (path === "/api/spending/preview" && method === "POST") return { json: preview };
  return null;
}
