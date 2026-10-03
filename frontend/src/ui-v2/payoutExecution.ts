import type {
  PayoutApplyResult,
  PayoutApplySelection,
  PayoutContextRequest,
  PayoutPreviewRow,
} from "../api/payouts";

export type PayoutOutcome =
  | "CONFIRMED"
  | "APPLIED_UNVERIFIED"
  | "REJECTED_NO_WRITE"
  | "STALE_NO_WRITE"
  | "UNKNOWN"
  | "NOT_SENT"
  | "ALREADY_PRESENT";

export type FrozenPayoutGroup = {
  payload: PayoutContextRequest;
  rows: PayoutApplySelection[];
  quantity: string | null;
  label: string;
  reviewedRows: PayoutPreviewRow[];
};
export type PayoutExecutionResult = {
  group: FrozenPayoutGroup;
  outcome: PayoutOutcome;
  message: string;
};

// Shared by individual and bulk execution, including a remounted leaf while
// an old request/readback is still pending. Nothing is persisted or resumed.
let executionActive = false;
export function isPayoutExecutionActive() {
  return executionActive;
}

function identity(
  row: Pick<PayoutApplySelection, "provider" | "instrument_uid" | "event_kind" | "identity_key">,
) {
  return JSON.stringify([row.provider, row.instrument_uid, row.event_kind, row.identity_key]);
}

export function receiptMatches(
  result: PayoutApplyResult,
  rows: PayoutApplySelection[],
  reviewedRows: PayoutPreviewRow[],
): boolean {
  if (
    !result?.success ||
    result.error_code !== null ||
    result.selected_count !== rows.length ||
    !Array.isArray(result.items) ||
    result.items.length !== rows.length
  )
    return false;
  const keys = result.items.map(identity);
  if (new Set(keys).size !== keys.length) return false;
  return rows.every((row) => {
    const item = result.items.find((value) => identity(value) === identity(row));
    const reviewed = reviewedRows.find(
      (value) =>
        value.event_kind !== null &&
        value.identity_key !== null &&
        identity(value as PayoutApplySelection) === identity(row),
    );
    if (
      !item ||
      !Number.isInteger(item.payout_id) ||
      item.payout_id <= 0 ||
      !Number.isInteger(item.revision_id) ||
      item.revision_id <= 0 ||
      item.lifecycle !== "active" ||
      !reviewed?.total_amount ||
      item.total_amount?.amount !== reviewed.total_amount.amount ||
      item.total_amount?.currency !== reviewed.total_amount.currency
    )
      return false;
    const decision = row.manual_duplicate_decision ?? reviewed.reconciliation;
    return (
      (!decision &&
        item.expected_cash_flow_id === null &&
        item.counting_decision === null &&
        item.reconciliation_id === null) ||
      (decision != null &&
        item.expected_cash_flow_id === decision.expected_cash_flow_id &&
        item.counting_decision === decision.counting_decision &&
        Number.isInteger(item.reconciliation_id) &&
        (item.reconciliation_id ?? 0) > 0 &&
        (row.manual_duplicate_decision != null ||
          item.reconciliation_id === reviewed.reconciliation?.reconciliation_id))
    );
  });
}

// These existing service responses are returned before mutation. A generic
// validation code (including a changed/non-applyable state) is insufficient.
const LOCAL_VALIDATION = new Set([
  "at least one payout row must be selected",
  "selected payout identities must be unique",
  "selected payout row is incomplete",
  "manual duplicate decision is required",
  "manual duplicate decision is only valid for duplicate preview rows",
]);

export async function executePayoutSelection(
  groups: FrozenPayoutGroup[],
  hooks: {
    current: () => boolean;
    before: (group: FrozenPayoutGroup) => Promise<boolean>;
    apply: (group: FrozenPayoutGroup) => Promise<PayoutApplyResult>;
    verify: (group: FrozenPayoutGroup, result: PayoutApplyResult) => Promise<boolean>;
    progress: (results: PayoutExecutionResult[], active: number | null) => void;
    stop: () => boolean;
  },
): Promise<PayoutExecutionResult[] | null> {
  if (executionActive) return null;
  executionActive = true;
  const frozen = structuredClone(groups);
  const results: PayoutExecutionResult[] = frozen.map((group) => ({
    group,
    outcome: "NOT_SENT",
    message: "Запрос не отправлен.",
  }));
  const publish = (active: number | null) => hooks.progress([...results], active);
  try {
    publish(null);
    for (let index = 0; index < frozen.length; index++) {
      if (hooks.stop() || !hooks.current()) break;
      const group = frozen[index];
      let safe = false;
      try {
        safe = await hooks.before(group);
      } catch {
        /* no POST */
      }
      if (!safe || !hooks.current()) {
        results[index] = {
          group,
          outcome: "STALE_NO_WRITE",
          message:
            "Контекст изменился или недоступен. Запрос не отправлен; нужен свежий предпросмотр.",
        };
        publish(null);
        break;
      }
      if (hooks.stop()) break;
      publish(index);
      let result: PayoutApplyResult;
      try {
        result = await hooks.apply(group);
      } catch {
        results[index] = {
          group,
          outcome: "UNKNOWN",
          message:
            "Ответ потерян или неоднозначен. Запись могла состояться. Не повторяй запрос: перечитай данные, затем явно получи новый предпросмотр и подтверди новый выбор.",
        };
        publish(null);
        break;
      }
      if (!result || typeof result.success !== "boolean") {
        results[index] = {
          group,
          outcome: "UNKNOWN",
          message:
            "Неоднозначный ответ. Нужен свежий предпросмотр и новое подтверждение; повтор запроса запрещён.",
        };
        publish(null);
        break;
      }
      if (!result.success) {
        if (
          result.selected_count !== group.rows.length ||
          !Array.isArray(result.items) ||
          result.items.length !== 0
        ) {
          results[index] = {
            group,
            outcome: "UNKNOWN",
            message:
              "Ответ об отказе не доказывает отсутствие записи. Применение остановлено; нужен свежий предпросмотр.",
          };
          publish(null);
          break;
        }
        const local =
          result.error_code === "validation_error" &&
          LOCAL_VALIDATION.has(result.message ?? "") &&
          result.items?.length === 0;
        const stale =
          result.error_code === "preview_changed" ||
          result.error_code === "closed_month" ||
          (result.error_code === "validation_error" && !local);
        const rejected =
          local ||
          result.error_code === "provider_error" ||
          result.error_code === "persistence_error";
        results[index] = {
          group,
          outcome: stale ? "STALE_NO_WRITE" : rejected ? "REJECTED_NO_WRITE" : "UNKNOWN",
          message: result.message ?? "Применение остановлено; нужен свежий предпросмотр.",
        };
        publish(null);
        if (local && hooks.current()) continue;
        break;
      }
      results[index] = {
        group,
        outcome: "APPLIED_UNVERIFIED",
        message: "Получен ответ об Apply. Повторная проверка ещё не подтверждена.",
      };
      publish(index);
      let matches = false;
      try {
        matches = receiptMatches(result, group.rows, group.reviewedRows);
      } catch {
        /* malformed receipt */
      }
      if (!matches || !hooks.current()) {
        publish(null);
        break;
      }
      let verified = false;
      try {
        verified = await hooks.verify(group, result);
      } catch {
        /* retain receipt */
      }
      if (!verified || !hooks.current()) {
        results[index] = {
          ...results[index],
          message:
            "Ответ об Apply получен, но авторитетная проверка не завершилась. Нужен свежий предпросмотр и новое подтверждение.",
        };
        publish(null);
        break;
      }
      results[index] = {
        group,
        outcome: "CONFIRMED",
        message: `Подтверждено повторной загрузкой: ${group.rows.length} событий.`,
      };
      publish(null);
    }
    return results;
  } finally {
    executionActive = false;
  }
}
