import type { FileProblem } from "../../api/spending";
import { formatMonthKey, pluralRu } from "../../lib/format";
import { spendingMonthForm } from "../uiV2Copy";
import { shortDate } from "./common";

export function previewProblem(problem: FileProblem, month: string, count = 1) {
  if (problem.file === "statement") {
    if (problem.line !== undefined)
      return {
        title: "Выписку нельзя применить",
        text: `${count} ${pluralRu(count, ["строка не прочитана", "строки не прочитаны", "строк не прочитано"])}. Файл с ошибками не заменяет загруженные операции — выгрузите выписку заново.`,
      };
    if (problem.code === "no_month_rows")
      return {
        title: `В выписке нет операций за ${formatMonthKey(month).toLowerCase()}`,
        text: `${problem.from && problem.to ? `Файл покрывает ${shortDate(problem.from)}–${shortDate(problem.to, true)}. ` : ""}Выберите другой месяц или другой файл.`,
      };
    return {
      title: "Не удалось прочитать выписку",
      text:
        problem.code === "invalid_encoding"
          ? "Файл пустой или в неизвестной кодировке. Выгрузите выписку заново."
          : "В файле нет колонок выписки Альфа-Банка. Выгрузите историю операций в формате CSV.",
    };
  }
  if (problem.code === "month_mismatch")
    return {
      title: "Ручной файл за другой месяц",
      text: `В файле указан ${formatMonthKey(problem.file_month, { empty: "другой месяц" }).toLowerCase()}, а загружается ${formatMonthKey(month).toLowerCase()}. Исправьте строку month в начале файла или выберите другой месяц.`,
    };
  return {
    title: "Не удалось прочитать ручной файл",
    text: ["missing_frontmatter", "manual_version", "invalid_frontmatter"].includes(problem.code)
      ? "В начале файла нет блока finance_expenses. Возьмите за образец шаблон ручного файла."
      : "В файле не найдена таблица трат. Колонки: Дата, Сумма, Категория, Описание, Оплата.",
  };
}

export function previewHeading(month: string) {
  return `Что изменится в ${spendingMonthForm(month, "prepositional")} ${month.slice(0, 4)}`;
}

const unreadableReasons: Record<string, string> = {
  invalid_date: "неверная дата",
  invalid_amount: "сумма не число",
  invalid_payment: "неизвестный способ оплаты",
  date_outside_month: "дата вне выбранного месяца",
  manual_column_count: "ожидается пять колонок",
};
export function unreadableReason(code: string) {
  return unreadableReasons[code] ?? "строка не прочитана";
}
