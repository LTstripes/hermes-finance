import type { PerformanceReadinessCapability } from "../api/types";

/**
 * Exact-key owner copy for readiness diagnostics (accepted #529/#530).
 * Keys come from the backend `_RULES` table; unknown keys use a neutral fallback.
 * No substring matching on reason codes.
 */
export type DiagnosticCopy = {
  title: string;
  detail: string;
};

const DIAGNOSTIC_COPY: Record<string, DiagnosticCopy> = {
  opening_valuation: {
    title: "Нет подтверждённой оценки на начальную дату",
    detail: "Выберите другую начальную дату либо откройте отчёт из данных границы.",
  },
  closing_valuation: {
    title: "Нет подтверждённой оценки на конечную дату",
    detail: "Выберите другую конечную дату либо откройте отчёт из данных границы.",
  },
  reporting_month: {
    title: "Отчёт ещё не закрыт",
    detail: "Проверьте конкретный отчёт. Месяц не закрывается автоматически.",
  },
  snapshot_date: {
    title: "Дата снимка не подтверждена",
    detail: "Нужен фактический источник даты; текущий курс исправлением не является.",
  },
  position_valuation: {
    title: "Оценка позиции не подтверждена",
    detail: "Нужен фактический источник оценки позиции.",
  },
  membership_history: {
    title: "История состава счетов не подтверждена",
    detail:
      "Подтвердите явные конечные интервалы в подготовке данных; текущий флажок счёта прошлое не лечит.",
  },
  membership_changed: {
    title: "Состав счетов менялся за интервал",
    detail: "Можно выбрать другой интервал вручную. История не переписывается ради расчёта.",
  },
  cash_binding: {
    title: "Не подтверждена принадлежность денег",
    detail: "Проверьте привязку денег на уровне раздела; это не замена gate доходности.",
  },
  scope_coverage: {
    title: "Компоненты выбранного охвата неполны",
    detail: "Проверьте охват на уровне раздела.",
  },
  external_flows: {
    title: "Полнота внешних потоков не подтверждена",
    detail: "Проверьте ledger в режиме чтения; причина не локализована.",
  },
  no_recorded_external_flows: {
    title: "В ledger нет записанных внешних потоков",
    detail: "Пустая таблица не доказывает нулевую активность; нужно явное подтверждение полноты.",
  },
  cash_history: {
    title: "Не подтверждена полнота денежной истории",
    detail: "Известные операции проверяются владельцем, затем история подтверждается явно.",
  },
  legacy_flows: {
    title: "Есть legacy-операции без классификации",
    detail:
      "Показаны именно эти записи. Legacy evidence не удаляется и не конвертируется эвристикой.",
  },
  transfer_identity: {
    title: "Перевод не связан",
    detail: "Каноническая связка перевода пока не поддержана.",
  },
  transfer_reconciliation: {
    title: "Перевод не сверен",
    detail: "Каноническая сверка перевода пока не поддержана.",
  },
  transfer_in_transit: {
    title: "Нет принятой оценки денег в пути",
    detail: "Ограничение расчёта; связка перевода его не гарантирует.",
  },
  in_kind_history: {
    title: "Не проверена история неденежных перемещений",
    detail: "Проверяется отдельно через in-kind coverage; из cash coverage не выводится.",
  },
  in_kind_valuation: {
    title: "Неденежное перемещение без подтверждённой стоимости",
    detail: "Факт показан; complete coverage его оценённым не делает.",
  },
  valuation_boundary: {
    title: "Нет подтверждённого наблюдения до/после операции",
    detail: "Наблюдение фиксируется принятым capture; повторная запись вслепую не делается.",
  },
  valuation_order: {
    title: "Порядок наблюдения не подтверждён",
    detail: "Нужна явная принятая связь; сортировка по ID не используется.",
  },
  historical_fx: {
    title: "Нет принятого перевода в валюту расчёта",
    detail: "Исторический FX-пересчёт не поддержан; текущий курс не исправление.",
  },
  xirr_no_root: {
    title: "XIRR не получен: нет подходящего корня",
    detail: "Ограничение solver при пройденных проверках; TWRR при этом сохраняется.",
  },
  xirr_ambiguous: {
    title: "XIRR неоднозначен для этой истории",
    detail: "Однозначность корня не подтверждена; ноль не подставляется, TWRR сохраняется.",
  },
  xirr_convergence: {
    title: "XIRR не сошёлся надёжно",
    detail: "Ограничение solver; повторная запись не помогает.",
  },
  unknown_reason: {
    title: "Результат не получен",
    detail: "Приложение не умеет подробнее объяснить эту причину.",
  },
};

export function diagnosticCopy(key: string): DiagnosticCopy {
  return (
    DIAGNOSTIC_COPY[key] ?? {
      title: "Результат не получен",
      detail: "Приложение не умеет подробнее объяснить эту причину.",
    }
  );
}

export function capabilityCopy(capability: PerformanceReadinessCapability): string {
  switch (capability) {
    case "available":
      return "Доступно к проверке";
    case "requires_reopen":
      return "Доступно после reopen закрытого месяца. Reopen — отдельное действие в закрытии месяца.";
    case "not_implemented":
      return "Возможность пока не реализована.";
    case "source_required":
      return "Нужен фактический источник; приложение не может доказать его отсутствие.";
    case "unsupported":
      return "Ограничение расчёта: исправление вводом невозможно.";
  }
}

/** Only `available` renders an in-page action button; anything else is status text. */
export function hasWorkingAction(capability: PerformanceReadinessCapability): boolean {
  return capability === "available";
}
