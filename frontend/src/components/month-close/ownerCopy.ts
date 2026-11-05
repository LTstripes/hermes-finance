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
