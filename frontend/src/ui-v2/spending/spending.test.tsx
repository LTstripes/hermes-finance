import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ExceptionGroup, SpendingException, SpendingHistoryItem } from "../../api/spending";
import { pluralRu } from "../../lib/format";
import { spendingComparisonNote, spendingMonthForm } from "../uiV2Copy";
import { coverageLabel } from "./common";
import { needsDecision, SpendingExceptions } from "./SpendingExceptions";
import { previewProblem } from "./previewCopy";

const history: SpendingHistoryItem = {
  month: "2026-10",
  loaded: true,
  total: null,
  partial: false,
  has_statement: true,
  has_manual: true,
  coverage: { from: null, to: null, full: true },
  by_type: { mandatory: null, comfortable: null, other: null },
  refunds_total: null,
  month_entries_total: { amount: "0.00", currency: "RUB" },
};

describe("spending status and comparison", () => {
  it.each([
    [{}, "Выписка + ручной файл"],
    [{ has_manual: false }, "Только выписка"],
    [{ has_statement: false }, "Только ручной файл"],
    [
      { partial: true, coverage: { from: "2026-10-01", to: "2026-10-16", full: false } },
      "Частично: 01.10–16.10",
    ],
    [{ loaded: false }, "Нет данных"],
  ])("reads coverage from backend (%j)", (patch, label) => {
    expect(coverageLabel({ ...history, ...patch })).toBe(label);
  });

  it("declines every month and reports exactly one comparison gap", () => {
    const forms = [
      "январе",
      "феврале",
      "марте",
      "апреле",
      "мае",
      "июне",
      "июле",
      "августе",
      "сентябре",
      "октябре",
      "ноябре",
      "декабре",
    ];
    expect(
      forms.map((_, index) =>
        spendingMonthForm(`2026-${String(index + 1).padStart(2, "0")}`, "prepositional"),
      ),
    ).toEqual(forms);
    expect(
      spendingComparisonNote(true, [
        { month: "2026-06", has_manual: false },
        { month: "2026-09", has_manual: false },
      ]),
    ).toBe("Сравнение неточное: в июне и сентябре нет ручного файла, траты там могли быть выше.");
    expect(spendingComparisonNote(false, [{ month: "2026-06", has_manual: true }])).toBe(
      "Сравнение неточное: в этом месяце нет ручного файла, наличные и Сбер не учтены.",
    );
    expect(spendingComparisonNote(true, [{ month: "2026-06", has_manual: true }])).toBeNull();
    expect(spendingComparisonNote(false, [{ month: "2026-06", has_manual: false }])).toBeNull();
    expect(
      [1, 3, 16, 21, 112].map((value) => pluralRu(value, ["операция", "операции", "операций"])),
    ).toEqual(["операция", "операции", "операций", "операция", "операций"]);
  });
});

describe("spending upload copy", () => {
  it.each([
    [
      { file: "statement", code: "csv_headers" },
      "Не удалось прочитать выписку",
      "В файле нет колонок выписки Альфа-Банка.",
    ],
    [
      { file: "statement", code: "invalid_encoding" },
      "Не удалось прочитать выписку",
      "Файл пустой или в неизвестной кодировке.",
    ],
    [
      { file: "statement", code: "no_month_rows", from: "2026-08-16", to: "2026-09-16" },
      "В выписке нет операций за октябрь",
      "Файл покрывает 16.08–16.09.2026.",
    ],
    [
      { file: "statement", code: "invalid_amount", line: 7 },
      "Выписку нельзя применить",
      "2 строки не прочитаны.",
    ],
    [
      { file: "manual", code: "manual_version" },
      "Не удалось прочитать ручной файл",
      "В начале файла нет блока finance_expenses.",
    ],
    [
      { file: "manual", code: "month_mismatch", file_month: "2026-11" },
      "Ручной файл за другой месяц",
      "В файле указан ноябрь",
    ],
    [
      { file: "manual", code: "manual_table_missing" },
      "Не удалось прочитать ручной файл",
      "В файле не найдена таблица трат.",
    ],
  ] as const)("maps file error %j", (problem, title, copy) => {
    const result = previewProblem(problem, "2026-10", 2);
    expect(result.title).toContain(title);
    expect(result.text).toContain(copy);
  });
});

describe("spending exceptions", () => {
  const groups: ExceptionGroup[] = [
    "transfer",
    "possible_duplicate",
    "refund",
    "entry_link",
    "foreign_currency",
    "unknown_debit",
    "new_category",
    "uncategorized",
  ];
  it.each(groups)("%s offers no preselected answer", (group) => {
    const item: SpendingException = {
      id: group,
      group,
      description: "Тестовая операция",
      category: "Тестовая категория",
      candidates: [],
      remember_key: null,
      remember_default: false,
      carried_over_failed: false,
      counted_now: false,
      kind_hint: null,
      recurring: false,
    };
    render(
      <SpendingExceptions
        items={[item]}
        categories={[]}
        month="2026-10"
        disabled={false}
        onResolve={() => undefined}
      />,
    );
    for (const radio of screen.queryAllByRole("radio")) expect(radio).not.toBeChecked();
    if (group === "foreign_currency" || group === "uncategorized") {
      expect(needsDecision(item)).toBe(false);
      expect(screen.getByText("осталось 0 из 0")).toBeVisible();
    } else expect(screen.getAllByRole("radio").length).toBeGreaterThan(0);
  });
});
