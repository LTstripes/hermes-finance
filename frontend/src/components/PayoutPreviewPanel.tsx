import { useEffect, useMemo, useState } from "react";

import type {
  PayoutApplySelection,
  PayoutCountingDecision,
  PayoutPreview,
  PayoutPreviewRow,
} from "../api/payouts";
import { formatDate, formatMoney } from "../lib/format";
import { FLOW_TYPE_LABELS, labelOf } from "../lib/labels";
import { moneyAmount } from "../lib/money";
import { Badge, Button, EmptyState, Field, Input, LoadingState, Panel, Select, Table, Td, Th } from "./ui";

type Props = {
  preview: PayoutPreview | null;
  loading: boolean;
  applying: boolean;
  error: string | null;
  readOnly: boolean;
  positionLabel: string | null;
  forecastVersion: string;
  onForecastVersionChange: (value: string) => void;
  onRefresh: () => void;
  onApply: (rows: PayoutApplySelection[]) => void;
};

type BadgeTone = "neutral" | "ok" | "draft" | "closed" | "info";

type DuplicateDraft = {
  decision: "" | PayoutCountingDecision;
  targetId: string;
};

const STATUS_LABELS: Record<string, string> = {
  new: "Новая",
  unchanged: "Без изменений",
  revised: "Изменена",
  possible_manual_duplicate: "Возможный дубль",
  cancelled_by_provider: "Отменена провайдером",
  missing_from_provider: "Нет в текущем ответе",
  tentative: "Предварительно",
  ambiguous_identity: "Неоднозначное событие",
  unsupported: "Не поддерживается",
  unavailable: "Недоступно",
  error: "Ошибка",
  position_gone: "Позиция отсутствует",
};

const DECISION_LABELS: Record<PayoutCountingDecision, string> = {
  keep_both: "Оставить обе выплаты",
  count_manual: "Считать только ручную",
  count_provider: "Считать только T-Invest",
};

function statusTone(status: string): BadgeTone {
  if (status === "new") return "ok";
  if (status === "revised") return "info";
  if (status === "possible_manual_duplicate" || status === "tentative") return "draft";
  if (
    status === "cancelled_by_provider" ||
    status === "missing_from_provider" ||
    status === "ambiguous_identity" ||
    status === "unsupported" ||
    status === "unavailable" ||
    status === "error" ||
    status === "position_gone"
  ) {
    return "closed";
  }
  return "neutral";
}

function rowKey(row: PayoutPreviewRow, index: number): string {
  return [row.event_kind ?? "event", row.identity_key ?? "no-identity", row.fingerprint ?? index].join(":");
}

function selectionFor(
  row: PayoutPreviewRow,
  draft: DuplicateDraft | undefined,
): PayoutApplySelection | null {
  if (!row.event_kind || !row.identity_key || !row.fingerprint) return null;
  const base: PayoutApplySelection = {
    provider: row.provider,
    instrument_uid: row.instrument_uid,
    event_kind: row.event_kind,
    identity_key: row.identity_key,
    fingerprint: row.fingerprint,
  };
  if (row.status !== "possible_manual_duplicate") return base;
  if (!draft?.decision || !draft.targetId) return null;
  const targetId = Number(draft.targetId);
  if (!Number.isInteger(targetId) || !row.manual_candidate_ids.includes(targetId)) return null;
  return {
    ...base,
    manual_duplicate_decision: {
      expected_cash_flow_id: targetId,
      counting_decision: draft.decision,
    },
  };
}

export function PayoutPreviewPanel({
  preview,
  loading,
  applying,
  error,
  readOnly,
  positionLabel,
  forecastVersion,
  onForecastVersionChange,
  onRefresh,
  onApply,
}: Props) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [duplicateDrafts, setDuplicateDrafts] = useState<Record<string, DuplicateDraft>>({});

  useEffect(() => {
    if (!preview || readOnly) {
      setSelected(new Set());
      setDuplicateDrafts({});
      return;
    }
    setSelected(
      new Set(
        preview.rows
          .map((row, index) => ({ row, key: rowKey(row, index) }))
          .filter(({ row }) => row.selectable && row.default_selected)
          .map(({ key }) => key),
      ),
    );
    setDuplicateDrafts({});
  }, [preview, readOnly]);

  const selectedRows = useMemo(() => {
    if (!preview) return [];
    return preview.rows
      .map((row, index) => ({ row, key: rowKey(row, index) }))
      .filter(({ row, key }) => selected.has(key) && row.selectable && !readOnly);
  }, [preview, readOnly, selected]);

  const applyRows = selectedRows
    .map(({ row, key }) => selectionFor(row, duplicateDrafts[key]))
    .filter((row): row is PayoutApplySelection => row !== null);
  const duplicateIncomplete = selectedRows.some(
    ({ row, key }) => row.status === "possible_manual_duplicate" && selectionFor(row, duplicateDrafts[key]) === null,
  );

  return (
    <Panel
      action={
        <div className="inline-actions">
          <Button disabled={loading || applying || !positionLabel} onClick={onRefresh} type="button" variant="primary">
            {loading ? "Запрашиваем…" : preview ? "Обновить preview" : "Проверить выплаты T-Invest"}
          </Button>
          {preview && !readOnly ? (
            <Button
              disabled={loading || applying || applyRows.length === 0 || duplicateIncomplete}
              onClick={() => onApply(applyRows)}
              type="button"
            >
              {applying ? "Применяем…" : `Применить выбранные (${applyRows.length})`}
            </Button>
          ) : null}
        </div>
      }
      label="T-Invest · только по кнопке"
      title="Предпросмотр автоматических выплат"
    >
      <div className="editor-grid filter-grid">
        <Field htmlFor="payout-forecast-version" label="Версия прогноза">
          <Input
            id="payout-forecast-version"
            maxLength={32}
            onChange={(event) => onForecastVersionChange(event.target.value)}
            value={forecastVersion}
          />
        </Field>
        <div className="stack-8">
          <span className="muted tiny">Выбранная позиция</span>
          <strong>{positionLabel ?? "Сначала выбери позицию"}</strong>
        </div>
      </div>

      <p className="muted">
        Здесь нет фонового обновления. Внешний запрос выполняется только после нажатия кнопки выше,
        а запись в календарь — только после отдельного применения выбранных строк.
      </p>

      {readOnly ? (
        <div className="inline-alert inline-alert--warn" role="status">
          Месяц закрыт. Предпросмотр доступен, но применять изменения нельзя до повторного открытия месяца.
        </div>
      ) : null}
      {error ? (
        <div className="inline-alert inline-alert--error" role="alert">
          {error}
        </div>
      ) : null}
      {duplicateIncomplete ? (
        <div className="inline-alert inline-alert--warn" role="status">
          Для выбранного возможного дубля укажи и способ учёта, и конкретную ручную запись.
        </div>
      ) : null}
      {loading && !preview ? <LoadingState description="Получаем данные о выплатах…" inline /> : null}
      {preview && preview.rows.length === 0 ? (
        <EmptyState
          description="Провайдер не вернул событий для этой позиции в горизонте календаря."
          inline
          title="Событий нет"
        />
      ) : null}

      {preview && preview.rows.length > 0 ? (
        <Table aria-label="Предпросмотр автоматических выплат">
          <thead>
            <tr>
              <Th>Выбор</Th>
              <Th>Событие</Th>
              <Th>Дата</Th>
              <Th numeric>На единицу</Th>
              <Th numeric>Итого</Th>
              <Th>Статус</Th>
              <Th>Ручной дубль</Th>
            </tr>
          </thead>
          <tbody>
            {preview.rows.map((row, index) => {
              const key = rowKey(row, index);
              const selectable = row.selectable && !readOnly;
              const duplicateDraft = duplicateDrafts[key] ?? { decision: "", targetId: "" };
              return (
                <tr data-payout-status={row.status} key={key}>
                  <Td>
                    {selectable ? (
                      <input
                        aria-label={`Выбрать выплату ${row.event_kind ?? index + 1}`}
                        checked={selected.has(key)}
                        onChange={(event) => {
                          setSelected((current) => {
                            const next = new Set(current);
                            if (event.target.checked) next.add(key);
                            else next.delete(key);
                            return next;
                          });
                        }}
                        type="checkbox"
                      />
                    ) : null}
                  </Td>
                  <Td>
                    <div className="stack-8">
                      <strong>{row.event_kind ? labelOf(FLOW_TYPE_LABELS, row.event_kind) : "Событие"}</strong>
                      <span className="muted tiny">
                        количество {row.quantity ?? "—"}
                        {row.source_method ? ` · ${row.source_method}` : ""}
                      </span>
                    </div>
                  </Td>
                  <Td>{row.payment_date ? formatDate(row.payment_date) : "—"}</Td>
                  <Td numeric>{row.per_unit_amount ? formatMoney(row.per_unit_amount) : "—"}</Td>
                  <Td numeric>
                    {row.total_amount ? formatMoney(moneyAmount(row.total_amount)) : "—"}
                    {row.currency && row.currency !== "RUB" ? (
                      <div className="muted tiny">{row.currency}</div>
                    ) : null}
                  </Td>
                  <Td>
                    <div className="stack-8">
                      <Badge tone={statusTone(row.status)}>
                        {STATUS_LABELS[row.status] ?? row.status}
                      </Badge>
                      {row.provider_status ? <span className="muted tiny">{row.provider_status}</span> : null}
                      {row.applied_lifecycle ? (
                        <span className="muted tiny">применено: {row.applied_lifecycle}</span>
                      ) : null}
                      {row.message ? <span className="muted tiny">{row.message}</span> : null}
                    </div>
                  </Td>
                  <Td>
                    {row.status === "possible_manual_duplicate" ? (
                      <div className="stack-8">
                        <Select
                          aria-label={`Решение для дубля ${index + 1}`}
                          disabled={!selectable}
                          onChange={(event) =>
                            setDuplicateDrafts((current) => ({
                              ...current,
                              [key]: {
                                ...duplicateDraft,
                                decision: event.target.value as "" | PayoutCountingDecision,
                              },
                            }))
                          }
                          value={duplicateDraft.decision}
                        >
                          <option value="">— способ учёта —</option>
                          {(Object.keys(DECISION_LABELS) as PayoutCountingDecision[]).map((decision) => (
                            <option key={decision} value={decision}>
                              {DECISION_LABELS[decision]}
                            </option>
                          ))}
                        </Select>
                        <Select
                          aria-label={`Ручная запись для дубля ${index + 1}`}
                          disabled={!selectable}
                          onChange={(event) =>
                            setDuplicateDrafts((current) => ({
                              ...current,
                              [key]: { ...duplicateDraft, targetId: event.target.value },
                            }))
                          }
                          value={duplicateDraft.targetId}
                        >
                          <option value="">— выбрать вручную —</option>
                          {row.manual_candidate_ids.map((candidateId) => (
                            <option key={candidateId} value={candidateId}>
                              Ручная запись #{candidateId}
                            </option>
                          ))}
                        </Select>
                        {row.reconciliation ? (
                          <span className="muted tiny">
                            Сейчас связано с #{row.reconciliation.expected_cash_flow_id} · {DECISION_LABELS[row.reconciliation.counting_decision]}
                          </span>
                        ) : null}
                      </div>
                    ) : row.manual_candidate_ids.length > 0 ? (
                      <span className="muted tiny">
                        кандидаты: {row.manual_candidate_ids.map((id) => `#${id}`).join(", ")}
                      </span>
                    ) : (
                      "—"
                    )}
                  </Td>
                </tr>
              );
            })}
          </tbody>
        </Table>
      ) : null}
    </Panel>
  );
}
