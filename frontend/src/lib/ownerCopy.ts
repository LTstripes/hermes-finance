import type { CloseReadinessItem } from "../api/types";

type ReadinessCopy = {
  title: string;
  message: string;
};

const READINESS_COPY: Record<string, ReadinessCopy> = {
  snapshot_date_required: {
    title: "Дата снимка не задана",
    message: "Укажи дату снимка месяца, чтобы сервер мог проверить и закрыть этот месяц.",
  },
  salary_tax_history_incomplete: {
    title: "История зарплатного НДФЛ неполная",
    message:
      "Часть истории года ещё не закрыта. Это стоит проверить, но закрытие месяца не блокируется.",
  },
  unresolved_payout_reconciliation: {
    title: "Выплаты требуют решения",
    message:
      "Есть выплаты с неразрешённым сопоставлением. Пока действует безопасный режим «только ручные»; закрытие не блокируется.",
  },
  section_empty: {
    title: "Раздел месяца пуст",
    message:
      "Необязательный раздел пока не заполнен. Это справочная информация и не блокирует закрытие.",
  },
  provenance_summary: {
    title: "Источники данных месяца",
    message: "Проверь состав источников, которые вошли в расчёты этого месяца.",
  },
  backup_present: {
    title: "Резервная копия есть",
    message: "Для месяца доступна резервная копия данных.",
  },
  backup_none: {
    title: "Резервной копии нет",
    message: "Резервная копия ещё не создана. Это контекст, а не блокер закрытия.",
  },
  month_already_closed: {
    title: "Месяц уже закрыт",
    message: "Повторное закрытие недоступно; при необходимости используй явное повторное открытие.",
  },
  quote_current: {
    title: "Котировки в актуальном окне",
    message: "Применённые котировки соответствуют дате оценки месяца.",
  },
  quote_stale: {
    title: "Есть устаревшие котировки",
    message: "Некоторые применённые котировки старше допустимого окна относительно даты оценки.",
  },
  quote_unavailable: {
    title: "Котировки требуют проверки",
    message: "Для некоторых позиций нет доступной котировки в допустимом периоде.",
  },
  quote_source_timestamp_inconsistent: {
    title: "Дата котировки не совпадает с оценкой",
    message: "Дата котировки позже даты оценки месяца, поэтому её актуальность нельзя подтвердить.",
  },
  mapped_quote_not_applied: {
    title: "Котировка ещё не применена",
    message: "Для части инструментов настроен источник котировок, но текущая цена пока не из него.",
  },
  manual_source_no_provider_timestamp: {
    title: "Ручное значение без времени провайдера",
    message: "Ручное значение не имеет времени наблюдения провайдера и не считается устаревшим.",
  },
  historical_quote_provenance_present: {
    title: "Сохранена история котировки",
    message: "После ручного изменения сохранилась исходная история котировки.",
  },
  payout_event_present: {
    title: "В месяце есть выплаты",
    message:
      "В расчёт вошли принятые выплаты. Их дата — событие, а не показатель свежести котировки.",
  },
  payout_none_for_month: {
    title: "Выплат в месяце нет",
    message: "В выбранном месяце нет принятых выплат провайдера.",
  },
  payout_not_freshness_classified: {
    title: "Выплаты проверяются отдельно",
    message: "Дата выплаты — событие, а не котировка; по возрасту она не помечается устаревшей.",
  },
  alfa_pro_observation_not_persisted: {
    title: "Время наблюдения Alfa PRO не сохранено",
    message:
      "Для текущего среза Alfa PRO нельзя честно определить актуальность по времени наблюдения.",
  },
  alfa_pro_baseline_present: {
    title: "Срез Alfa PRO подтверждён",
    message: "В месяце есть подтверждённый владельцем текущий срез Alfa PRO.",
  },
  alfa_pro_observation_not_freshness_classified: {
    title: "Срез Alfa PRO не оценивается как котировка",
    message:
      "Время наблюдения Alfa PRO используется отдельно и не превращается в свежесть котировки.",
  },
  statement_event_present: {
    title: "В месяце есть события выписки",
    message: "В расчёт вошли принятые события выписки Alfa. Их дата относится к событию документа.",
  },
  statement_none_for_month: {
    title: "Событий выписки в месяце нет",
    message: "В выбранном месяце нет принятых событий выписки Alfa.",
  },
  statement_not_freshness_classified: {
    title: "События выписки проверяются отдельно",
    message: "Дата в выписке — событие документа, а не котировка; по возрасту она не устаревает.",
  },
  manual_month_data_present: {
    title: "Есть ручные данные месяца",
    message: "В месяце есть данные, которые ведутся вручную.",
  },
  manual_month_data_empty: {
    title: "Ручных данных месяца нет",
    message: "В месяце нет ручных доходов, расходов, накоплений и ожидаемых выплат.",
  },
  deposit_cash_present: {
    title: "Есть депозиты или остатки кэша",
    message: "В месяце есть данные по депозитам или остаткам кэша.",
  },
  deposit_cash_empty: {
    title: "Депозитов и кэша нет",
    message: "В месяце нет депозитов и остатков кэша.",
  },
  deposit_cash_local_edit_only: {
    title: "Депозиты и кэш ведутся локально",
    message:
      "Для этих данных есть только локальное время правки, а не время наблюдения провайдера.",
  },
  source_timestamp_unavailable: {
    title: "Время наблюдения недоступно",
    message: "Отсутствие времени наблюдения не означает, что данные устарели.",
  },
  multiple_providers: {
    title: "В месяце несколько источников",
    message: "В выбранном месяце есть данные более чем одного провайдера.",
  },
};

function fallbackCopy(item: CloseReadinessItem): ReadinessCopy {
  if (item.severity === "hard_blocker") {
    return {
      title: "Нужно исправить перед закрытием",
      message: "Сначала устрани это условие, иначе сервер не примет закрытие месяца.",
    };
  }
  if (item.severity === "warning") {
    return {
      title: "Стоит проверить",
      message: "Есть данные, которые полезно проверить перед закрытием; они не блокируют закрытие.",
    };
  }
  return {
    title: "Контекст месяца",
    message: "Это справочная информация о составе и ограничениях данных.",
  };
}

export function readinessCopy(item: CloseReadinessItem): ReadinessCopy {
  return READINESS_COPY[item.code] ?? fallbackCopy(item);
}

export function readinessDiagnostic(item: CloseReadinessItem): string {
  const context =
    Object.keys(item.context).length > 0 ? JSON.stringify(item.context, null, 2) : "нет";
  return `Код: ${item.code}\nСерверное сообщение: ${item.message}\nКонтекст: ${context}`;
}

export function russianCount(count: number, one: string, few: string, many: string): string {
  const moduloTen = count % 10;
  const moduloHundred = count % 100;
  const form =
    moduloTen === 1 && moduloHundred !== 11
      ? one
      : moduloTen >= 2 && moduloTen <= 4 && (moduloHundred < 12 || moduloHundred > 14)
        ? few
        : many;
  return `${count} ${form}`;
}
