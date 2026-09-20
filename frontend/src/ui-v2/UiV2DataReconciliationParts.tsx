import type {
  BrokerReconciliationResponse,
  ReconciliationAccount,
  ReconciliationInstrument,
  ReconciliationRow,
} from "../api/brokerReconciliation";

export type MappingValues = Record<string, string>;
export type RowFilter = "all" | "attention" | "matched";

const ROW_STATE_LABELS: Record<string, string> = {
  matched: "Совпадает",
  differs: "Отличается",
  missing_local: "Нет локальной позиции",
  missing_provider: "Нет позиции у брокера",
  unresolved: "Не сопоставлено",
};

const ROW_REASON_LABELS: Record<string, string> = {
  mapping_unresolved: "Сопоставление не подтверждено.",
  account_mapping_unresolved: "Счёт брокера ещё не сопоставлен.",
  instrument_mapping_unresolved: "Инструмент брокера ещё не сопоставлен.",
  "duplicate provider account identifier in snapshot":
    "В данных брокера повторяется один и тот же счёт.",
  "explicit mapping targets a Hermes account id that does not exist":
    "Выбранный локальный счёт больше не найден.",
  "no explicit owner mapping for provider account": "Счёт брокера ещё не сопоставлен.",
  "conflicting metadata for the same provider instrument identifier":
    "Для одного инструмента брокера получены противоречивые данные.",
  "provider account is not present in the snapshot account set":
    "Счёт брокера отсутствует в полученном снимке.",
  "provider account mapping is unresolved": "Не удалось подтвердить сопоставление счёта брокера.",
  "provider instrument is not present in the snapshot identity set":
    "Инструмент брокера отсутствует в полученном снимке.",
  "provider instrument mapping is unresolved":
    "Не удалось подтвердить сопоставление инструмента брокера.",
  "position identity or provider quantity is unresolved":
    "Не удалось подтвердить позицию или её количество.",
  "duplicate provider rows map to the same canonical account+instrument; no aggregation rule":
    "Несколько строк брокера указывают на одну позицию; правила объединения нет.",
  "provider-only position; no matching Hermes position":
    "Позиция есть у брокера, но не найдена локально.",
  "Hermes-only position; no provider row with resolved identity":
    "Позиция есть локально, но не найдена у брокера.",
};

export const RECONCILIATION_STATUS_LABELS: Record<string, string> = {
  applicable: "Проверка выполнена",
  conflicts: "Есть конфликты сопоставления",
  non_applicable: "Не применяется",
};

export function rowStateLabel(state: string): string {
  return ROW_STATE_LABELS[state] ?? "Требует проверки";
}

export function rowReasonLabel(reason: string | null): string | null {
  if (!reason) return null;
  return ROW_REASON_LABELS[reason] ?? "Подробность доступна в технической диагностике.";
}

export function rowStateTone(state: string): string {
  if (state === "matched") return "ok";
  if (state === "differs") return "info";
  if (state === "unresolved") return "unknown";
  if (state === "missing_local" || state === "missing_provider") return "missing";
  return "neutral";
}

export function resultStatusTone(status: string): string {
  if (status === "applicable") return "ok";
  if (status === "conflicts") return "unknown";
  return "stale";
}

export function reconciliationStatusLabel(status: string): string {
  return RECONCILIATION_STATUS_LABELS[status] ?? "Статус не подтверждён";
}

export function isComparisonUnavailable(result: BrokerReconciliationResponse): boolean {
  return (
    result.stale ||
    result.compatibility_state !== "compatible" ||
    result.snapshot_status !== "complete"
  );
}

export function nonApplicableReason(result: BrokerReconciliationResponse): string | null {
  if (result.stale) {
    return "Снимок устарел. Сверка и любые следующие действия неприменимы до явного обновления снимка.";
  }
  if (result.compatibility_state !== "compatible") {
    return "Совместимость снимка не подтверждена. Результат оставлен для диагностики и неприменим.";
  }
  if (result.snapshot_status !== "complete") {
    return "Снимок неполный или недоступен. Сверка неприменима до нового явного запроса.";
  }
  return null;
}

export function mappingFromValues(accountValues: MappingValues, instrumentValues: MappingValues) {
  return {
    accounts: Object.entries(accountValues)
      .filter(([, hermesId]) => hermesId !== "")
      .map(([providerAccountId, hermesId]) => ({
        hermes_account_id: Number(hermesId),
        provider_account_id: providerAccountId,
      })),
    instruments: Object.entries(instrumentValues)
      .filter(([, hermesId]) => hermesId !== "")
      .map(([providerInstrumentId, hermesId]) => ({
        hermes_instrument_id: Number(hermesId),
        provider_instrument_id: providerInstrumentId,
      })),
  };
}

export function accountMappingValue(row: ReconciliationAccount, values: MappingValues): string {
  return (
    values[row.provider_account_id] ??
    (row.status === "matched" && row.hermes_account_id != null ? String(row.hermes_account_id) : "")
  );
}

export function instrumentMappingValue(
  row: ReconciliationInstrument,
  values: MappingValues,
): string {
  if (!row.provider_instrument_id) return "";
  return (
    values[row.provider_instrument_id] ??
    (row.status === "matched" ? String(row.hermes_instrument_id) : "")
  );
}

export function rowKey(row: ReconciliationRow): string {
  return [
    row.state,
    row.account_id ?? "provider",
    row.instrument_id ?? "row",
    row.provider_account_id ?? "account",
    row.provider_instrument_id ?? "instrument",
    row.fingerprint ?? "no-fingerprint",
  ].join("-");
}
