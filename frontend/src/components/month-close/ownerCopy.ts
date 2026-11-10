import type { CloseReadinessItem } from "../../api/types";

/** Only unambiguous section destinations; unknown findings stay without a link. */
export function closeFindingPanel(item: CloseReadinessItem): string | undefined {
  const families: Record<string, string> = {
    market_quotes: "positions",
    broker_positions: "positions",
    t_invest_payouts: "payouts",
    alfa_statement_payouts: "brokers",
    manual_month_data: "general",
    deposit_cash_snapshots: "assets",
  };
  const codes: Record<string, string> = {
    snapshot_date_required: "general",
    salary_tax_history_incomplete: "income",
    active_account_snapshot_missing: "positions",
    unresolved_payout_reconciliation: "payouts",
    source_intake_pending: "brokers",
    money_semantics_unsupported: "brokers",
  };
  const family = item.context.family_id;
  if (typeof family === "string" && Object.hasOwn(families, family)) return families[family];
  if (Object.hasOwn(codes, item.code)) return codes[item.code];
  if (item.message.includes("Месяц → Брокерские выписки")) return "brokers";
  return undefined;
}

/** Closed-month summary retains the finding; correction instructions are shown once. */
export function closedFindingCopy(text: string): string {
  return closeOwnerCopy(text)
    .replace(/\s+(?:Открой|Проверь подробности)[^.]*\.(?=\s|$)/gu, "")
    .replace(/\s+Проверь[^.;]*;\s*ручную цену можно оставить\./gu, " Ручную цену можно оставить.")
    .replace(/^Проверь\s+/u, "Нужна проверка: ")
    .trim();
}

/** One source-review action per account; details retain the separate findings. */
export function closeOwnerActionFindings<T extends { message: string; severity: string }>(
  items: T[],
): T[] {
  // The ordinary review needs one next action per account. Detailed review keeps
  // each individual finding and every diagnostic code.
  return closeOwnerFindings(
    items.map((item) => {
      const account =
        /^(.*): .*\. Проверь подробности в разделе «Месяц → Брокерские выписки»\.$/.exec(
          item.message,
        )?.[1];
      return account
        ? {
            ...item,
            message: `${account}: сверка выписки с данными месяца не завершена. Открой «Месяц → Брокерские выписки» и проверь замечания.`,
          }
        : item;
    }),
  );
}

/** One visible issue; all underlying codes/evidence remain in the response. */
export function closeOwnerFindings<T extends { message: string; severity: string }>(
  items: T[],
): T[] {
  const seen = new Set<string>();
  // Keep the strongest severity if multiple codes describe one visible issue.
  const priority = (severity: string) =>
    severity === "hard_blocker" ? 2 : severity === "warning" ? 1 : 0;
  const ordered = [...items].sort((a, b) => priority(b.severity) - priority(a.severity));
  return ordered.filter((item) => {
    const key = closeOwnerCopy(item.message).trim();
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

/** Presentation only: lifecycle enums, evidence and readiness stay authoritative. */
export function closeOwnerCopy(text: string): string {
  return text
    .replaceAll("в core-контракте", "в сохранённых данных")
    .replaceAll("из действующего Close Cockpit", "по текущей проверке готовности")
    .replaceAll("Close Cockpit", "Проверка готовности")
    .replaceAll("hard blockers", "блокеров")
    .replaceAll("hard blocker", "блокер")
    .replaceAll("этим read model", "по сохранённым данным")
    .replaceAll("командой Close", "действием «Закрыть месяц»")
    .replaceAll(
      "Outlook появляется только после закрытия и отдельной композиции известных событий.",
      "События следующего месяца доступны после закрытия, по известным датам.",
    )
    .replaceAll("provenance", "происхождение данных");
}

/** Ordinary month intake copy; source codes remain inside the existing review. */
export const brokerIntakeCopy = {
  title: "Загрузка брокерских файлов",
  drop: "Перетащи сюда XML-выписки и PDF отчёта о выплатах",
  choose: "Выбрать файлы",
  slots: "Места для файлов",
  xmlSlot1: "Выписка счёта 1",
  xmlSlot2: "Выписка счёта 2",
  pdfSlot: "Отчёт о доходах (PDF)",
  statement: "Выписка счёта ",
  unknownAccount: "неизвестен",
  savedFiles: "Сохранённые файлы",
  loading: "Проверяем сохранённые файлы…",
  empty: "Загрузи файлы выбранного месяца.",
  ok: "Всё в порядке",
  confirm: "Нужен разбор файлов: ",
  partial: "Остальные данные сохранены. Можно продолжить работу с месяцем.",
  partialUpload: "Часть файлов сохранена. Неудачные загрузки можно повторить отдельно.",
  structureInfo:
    "Служебные разделы выписки распознаны. Повторное подтверждение не требуется; ограничения расчёта доступны в данных.",
  states: {
    file_saved: "Файл сохранён; можно проверить данные.",
    needs_decision: "Нужно проверить данные перед их принятием.",
    financial_data_accepted: "Финансовые данные приняты.",
  },
  reviewAction: "Разобрать операцию",
  duplicate: "Этот файл уже загружен.",
  saved: "Файл сохранён.",
  uncertain: "Ответ загрузки не получен; проверь сохранённый результат.",
  recover: "Прочитать результат загрузки",
  recovered: "Сохранённые файлы подтверждены.",
  missing: "Часть файлов не найдена; можно повторить только их загрузку.",
  retry: "Повторить проблемные файлы",
  readFailed: "Не удалось подтвердить сохранённые файлы. Обнови результат.",
  fileReadFailed: "Не удалось прочитать выбранные файлы.",
  reselectPdf: "Выбери исходный PDF в зоне загрузки, чтобы проверить и принять его выплаты.",
  refresh: "Обновить результат",
  pdfDecision: "Выбери счёт и выплаты, которые нужно принять.",
  discardPdf: "Закончить разбор? Несохранённый выбор строк будет сброшен.",
  pdfReview: "Подробности и подтверждение выплат PDF",
  investmentDetails: "Подробности сверки XML с инвестиционным отчётом",
  investmentReport: "Дополнительная сверка купонов и дивидендов",
  stay: "Продолжить разбор",
  finishReview: "Закончить разбор PDF",
} as const;
