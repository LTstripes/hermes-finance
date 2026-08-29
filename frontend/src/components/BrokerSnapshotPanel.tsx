import { useEffect, useState } from "react";
import {
  type BrokerIdentityMapping,
  listBrokerIdentityMappings,
  revokeBrokerIdentityMapping,
} from "../api/brokerIdentityMappings";
import {
  applyBrokerBaseline,
  type BrokerApplySelection,
  type BrokerMapping,
  type BrokerPositionRow,
  type BrokerSnapshotPreview,
  previewBrokerSnapshot,
} from "../api/brokerSnapshot";
import { formatApiError } from "../api/client";
import { listMonths } from "../api/months";
import type { Account, Instrument, ReportingMonth } from "../api/types";
import { formatMonth } from "../lib/format";
import { labelOf, MONTH_STATUS_LABELS } from "../lib/labels";
import { Badge, Button, ConfirmDialog, Field, Panel, Select, Table, Td, Th } from "./ui";

type DecisionAction = "keep_existing" | "replace" | "";
type LocalDecision = {
  averageCost: DecisionAction;
  averageValue: string;
  marketPrice: DecisionAction;
  marketValue: string;
  marketDate: string;
  marketSource: string;
  accruedInterest: DecisionAction;
  accruedValue: string;
};

const EMPTY_DECISION: LocalDecision = {
  averageCost: "",
  averageValue: "",
  marketPrice: "",
  marketValue: "",
  marketDate: "",
  marketSource: "",
  accruedInterest: "",
  accruedValue: "",
};

const PREVIEW_STATUS_LABELS: Record<string, string> = {
  applicable: "Готов к выборочному применению",
  conflicts: "Нужно уточнить сопоставления",
  non_applicable: "Недоступно для применения",
};

const POSITION_STATUS_LABELS: Record<string, string> = {
  matched: "Сопоставлено",
  provider_only: "Нет локальной позиции",
  hermes_only: "Нет позиции у брокера",
  conflict: "Нужно уточнение",
};

const IDENTITY_CLASSIFICATION_LABELS: Record<string, string> = {
  reused: "Уже подтверждено",
  deterministic_isin: "Сопоставлено по ISIN",
  explicit: "Задано в этом просмотре",
  new: "Нужно сопоставить",
  ambiguous: "Неоднозначно",
  conflict: "Конфликт",
  provider_identity_absent: "Нет в текущем снимке",
};

type BadgeTone = "neutral" | "ok" | "info" | "stale" | "unknown" | "missing" | "closed";

function classificationTone(classification: string | undefined): BadgeTone {
  if (classification === "reused" || classification === "deterministic_isin") return "ok";
  if (classification === "explicit") return "info";
  if (classification === "conflict" || classification === "ambiguous") return "unknown";
  if (classification === "provider_identity_absent") return "missing";
  return "stale";
}

function needsMappingSelect(status: string, classification?: string): boolean {
  if (classification === "reused" || classification === "deterministic_isin") return false;
  if (classification === "provider_identity_absent") return false;
  return (
    status === "unmatched" || status === "ambiguous" || status === "conflict" || status === "new"
  );
}

function identityLabel(classification: string | undefined, status: string): string {
  if (classification) return labelOf(IDENTITY_CLASSIFICATION_LABELS, classification);
  if (status === "matched") return IDENTITY_CLASSIFICATION_LABELS.explicit;
  if (status === "unmatched") return IDENTITY_CLASSIFICATION_LABELS.new;
  return labelOf(IDENTITY_CLASSIFICATION_LABELS, status);
}

function previewErrorMessage(next: BrokerSnapshotPreview): string | null {
  if (next.snapshot_status === "provider_unavailable" || next.error_code === "provider_error") {
    return "Не удалось подключиться к Альфа PRO. Убедитесь, что терминал запущен и выполнен вход.";
  }
  if (next.diagnostics?.compatibility_state === "unsupported") {
    return "Протокол Альфа PRO не поддержан. Применение отключено; передайте безопасную диагностику разработчику.";
  }
  if (next.diagnostics?.compatibility_state === "unknown") {
    if (next.diagnostics.failure_class === "protocol") {
      return "Не удалось однозначно распознать протокол Альфа PRO. Применение отключено; передайте безопасную диагностику разработчику.";
    }
    if (next.diagnostics.failure_class === "layout") {
      return "Не удалось однозначно распознать формат данных Альфа PRO. Применение отключено; передайте безопасную диагностику разработчику.";
    }
    return "Совместимость Альфа PRO не подтверждена. Применение отключено; передайте безопасную диагностику разработчику.";
  }
  if (next.error_code) return next.message ?? "Не удалось получить данные из Альфа PRO.";
  return null;
}

function rowKey(row: BrokerPositionRow): string {
  return `${row.account_id}:${row.instrument_id}`;
}

function validAmount(value: string): boolean {
  const normalized = value.trim().replace(",", ".");
  return /^-?\d+(?:\.\d+)?$/.test(normalized) && Number.isFinite(Number(normalized));
}

function completeDecision(row: BrokerPositionRow, decision: LocalDecision | undefined): boolean {
  if (!decision) return false;
  const replaceAverage = decision.averageCost === "replace";
  const replaceMarket = decision.marketPrice === "replace";
  const replaceAccrued = decision.accruedInterest === "replace";
  const create = row.status === "provider_only";
  if (!decision.averageCost || !decision.marketPrice) return false;
  if (create) {
    if (!replaceAverage || !replaceMarket) return false;
    if (decision.accruedInterest === "keep_existing") return false;
  } else if (!decision.accruedInterest) {
    return false;
  }
  if (replaceAverage && !validAmount(decision.averageValue)) return false;
  if (
    replaceMarket &&
    (!validAmount(decision.marketValue) || !decision.marketDate || !decision.marketSource)
  )
    return false;
  if (replaceAccrued && !validAmount(decision.accruedValue)) return false;
  return true;
}

function selectionFor(row: BrokerPositionRow, decision: LocalDecision): BrokerApplySelection {
  const amount = (action: DecisionAction, value: string) =>
    action === "replace" ? { action, value: value.replace(",", ".") } : { action };
  return {
    account_id: row.account_id,
    instrument_id: row.instrument_id,
    fingerprint: row.fingerprint as string,
    action: row.status === "provider_only" ? "create" : "update",
    average_cost: amount(decision.averageCost, decision.averageValue),
    market_price:
      decision.marketPrice === "replace"
        ? {
            action: "replace",
            market_price_per_unit: decision.marketValue.replace(",", "."),
            price_date: decision.marketDate,
            price_source: decision.marketSource,
          }
        : { action: "keep_existing" },
    ...(decision.accruedInterest
      ? { accrued_interest: amount(decision.accruedInterest, decision.accruedValue) }
      : {}),
  } as BrokerApplySelection;
}

type Props = {
  accounts: Account[];
  instruments: Instrument[];
  onApplied?: () => Promise<void> | void;
};

export function BrokerSnapshotPanel({ accounts, instruments, onApplied }: Props) {
  const [monthId, setMonthId] = useState("");
  const [months, setMonths] = useState<ReportingMonth[]>([]);
  const [monthsLoading, setMonthsLoading] = useState(true);
  const [monthsError, setMonthsError] = useState<string | null>(null);
  const [accountMappings, setAccountMappings] = useState<Record<string, string>>({});
  const [instrumentMappings, setInstrumentMappings] = useState<Record<string, string>>({});
  const [preview, setPreview] = useState<BrokerSnapshotPreview | null>(null);
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [decisions, setDecisions] = useState<Record<string, LocalDecision>>({});
  const [mappingDirty, setMappingDirty] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [diagnosticCopied, setDiagnosticCopied] = useState(false);
  const [identityMappings, setIdentityMappings] = useState<BrokerIdentityMapping[]>([]);

  useEffect(() => {
    const controller = new AbortController();
    async function loadMonths() {
      setMonthsLoading(true);
      setMonthsError(null);
      try {
        const rows = await listMonths(controller.signal);
        if (!controller.signal.aborted) setMonths(rows);
      } catch (error) {
        if (!controller.signal.aborted) setMonthsError(formatApiError(error));
      } finally {
        if (!controller.signal.aborted) setMonthsLoading(false);
      }
    }
    void loadMonths();
    return () => controller.abort();
  }, []);

  const selectedMonth = months.find((month) => String(month.id) === monthId) ?? null;
  const baselineDate = selectedMonth?.snapshot_date ?? "";
  const monthClosed = selectedMonth?.status === "closed" || Boolean(preview?.month_closed);
  const selectedRows =
    preview?.positions.filter((row) => selected[rowKey(row)] && row.fingerprint && !row.is_money) ??
    [];

  function effectiveMapping(subjectKind: "account" | "instrument", providerIdentity: string) {
    return identityMappings.find(
      (row) =>
        row.status === "effective" &&
        row.subject_kind === subjectKind &&
        row.provider_identity === providerIdentity,
    );
  }

  function mapping(): BrokerMapping {
    return {
      accounts: Object.entries(accountMappings)
        .filter(([, hermesId]) => hermesId)
        .map(([providerAccountId, hermesId]) => ({
          hermes_account_id: Number(hermesId),
          provider_account_id: providerAccountId,
        })),
      instruments: Object.entries(instrumentMappings)
        .filter(([, hermesId]) => hermesId)
        .map(([providerInstrumentId, hermesId]) => ({
          hermes_instrument_id: Number(hermesId),
          provider_instrument_id: providerInstrumentId,
        })),
    };
  }

  function clearReview() {
    setPreview(null);
    setSelected({});
    setDecisions({});
    setMappingDirty(false);
    setConfirmOpen(false);
    setDiagnosticCopied(false);
    setIdentityMappings([]);
  }

  async function copyDiagnostic() {
    if (!preview) return;
    try {
      await navigator.clipboard.writeText(preview.diagnostic_report);
      setDiagnosticCopied(true);
    } catch {
      setDiagnosticCopied(false);
      setMessage("Не удалось скопировать диагностику. Выделите текст вручную.");
    }
  }

  async function refresh() {
    const id = Number(monthId);
    if (!Number.isInteger(id) || id < 1) {
      setMessage("Выберите отчётный месяц.");
      return;
    }
    setBusy(true);
    setMessage(null);
    setSuccess(null);
    clearReview();
    try {
      const next = await previewBrokerSnapshot(id, mapping());
      setPreview(next);
      setMessage(previewErrorMessage(next));
      try {
        const rows = await listBrokerIdentityMappings(next.provider || "alfa_pro");
        setIdentityMappings(rows.filter((row) => row.status === "effective"));
      } catch {
        setIdentityMappings([]);
      }
    } catch (error) {
      setMessage(formatApiError(error));
    } finally {
      setBusy(false);
    }
  }

  async function revokeIdentity(mappingId: number) {
    setBusy(true);
    setMessage(null);
    setSuccess(null);
    try {
      await revokeBrokerIdentityMapping(mappingId);
      setMappingDirty(true);
      setSuccess("Сопоставление отозвано. Получите обновлённые данные из Альфа PRO.");
    } catch (error) {
      setMessage(formatApiError(error));
    } finally {
      setBusy(false);
    }
  }

  function updateDecision(key: string, patch: Partial<LocalDecision>) {
    setDecisions((current) => ({
      ...current,
      [key]: { ...(current[key] ?? EMPTY_DECISION), ...patch },
    }));
  }

  const applyReady = Boolean(
    preview?.eligible_for_apply &&
      !mappingDirty &&
      !monthClosed &&
      Boolean(baselineDate) &&
      selectedRows.length > 0 &&
      selectedRows.every((row) => completeDecision(row, decisions[rowKey(row)])),
  );

  async function apply() {
    if (!preview || !applyReady || !baselineDate) return;
    setBusy(true);
    setMessage(null);
    setSuccess(null);
    try {
      const result = await applyBrokerBaseline(Number(monthId), {
        baseline_date: baselineDate,
        mapping: mapping(),
        selections: selectedRows.map((row) => selectionFor(row, decisions[rowKey(row)])),
      });
      if (!result.success) {
        if (result.error_code === "preview_changed") clearReview();
        setMessage(result.message ?? "Базовый срез не применён.");
        return;
      }
      const unchanged = result.items.filter((item) => item.action === "unchanged").length;
      setSuccess(
        unchanged === result.selected_count
          ? `Базовый срез без изменений: ${result.selected_count}.`
          : `Базовый срез применён. Позиций: ${result.selected_count}.`,
      );
      clearReview();
      await onApplied?.();
    } catch (error) {
      setMessage(formatApiError(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel label="Alfa PRO" title="Текущий базовый срез">
      <p className="muted">
        Снимок запрашивается только по кнопке. Подтверждённые сопоставления используются повторно.
        Количество выбранных позиций записывается в черновик месяца как текущий срез на дату месяца.
        Цена, учётная цена, НКД и P&amp;L брокера только для сравнения.
      </p>
      <div className="editor-grid">
        <Field htmlFor="broker-month-id" label="Отчётный месяц">
          <Select
            id="broker-month-id"
            value={monthId}
            onChange={(event) => setMonthId(event.target.value)}
            disabled={monthsLoading}
          >
            <option value="">{monthsLoading ? "Загружаем месяцы…" : "— выберите месяц —"}</option>
            {[...months]
              .sort((a, b) => b.year - a.year || b.month - a.month || b.id - a.id)
              .map((month) => (
                <option key={month.id} value={month.id}>
                  {formatMonth(month.year, month.month)} ·{" "}
                  {labelOf(MONTH_STATUS_LABELS, month.status)}
                </option>
              ))}
          </Select>
        </Field>
        {selectedMonth ? (
          <Field htmlFor="broker-baseline-date" label="Дата базового среза">
            <input id="broker-baseline-date" value={baselineDate} readOnly />
          </Field>
        ) : null}
      </div>
      {monthClosed ? (
        <div className="inline-alert" role="status">
          Утверждённый месяц нельзя менять. Сначала откройте его заново.
        </div>
      ) : null}
      {monthsError ? (
        <div className="inline-alert inline-alert--error" role="alert">
          Не удалось загрузить список отчётных месяцев: {monthsError}
        </div>
      ) : null}
      <div className="toolbar">
        <Button onClick={() => void refresh()} disabled={busy}>
          {preview ? "Обновить данные из Альфа PRO" : "Получить данные из Альфа PRO"}
        </Button>
        {preview ? (
          <Button
            onClick={() => setConfirmOpen(true)}
            disabled={busy || !applyReady}
            variant="primary"
          >
            Применить выбранный базовый срез
          </Button>
        ) : null}
      </div>
      {message ? (
        <div className="inline-alert inline-alert--error" role="alert">
          {message}
        </div>
      ) : null}
      {success ? (
        <div className="month-workspace__save-ok" role="status">
          {success}
        </div>
      ) : null}
      {preview ? (
        <div className="stack-12">
          <div className="toolbar">
            <Badge tone={preview.eligible_for_apply ? "ok" : "closed"}>
              {labelOf(PREVIEW_STATUS_LABELS, preview.status)}
            </Badge>
          </div>
          <details>
            <summary>Безопасная диагностика для поддержки</summary>
            <div className="stack-8">
              <p className="muted">
                Здесь нет credentials, исходного payload, номеров счетов или финансовых значений.
                Этот текст можно передать разработчику.
              </p>
              <pre className="diagnostic-output">{preview.diagnostic_report}</pre>
              <Button
                onClick={() => void copyDiagnostic()}
                size="sm"
                type="button"
                variant="secondary"
              >
                {diagnosticCopied ? "Скопировано" : "Скопировать диагностику"}
              </Button>
            </div>
          </details>
          {preview.accounts.length > 0 ? (
            <Panel label="Сопоставление" title="Счета Alfa → Hermes">
              {preview.accounts.map((row) => {
                const classification = row.classification ?? "";
                const stored = effectiveMapping("account", row.provider_account_id);
                const showSelect = needsMappingSelect(row.status, classification);
                return (
                  <div key={row.provider_account_id} className="stack-8">
                    <div className="toolbar">
                      <strong>{row.provider_account_id}</strong>
                      <Badge tone={classificationTone(classification)}>
                        {identityLabel(classification, row.status)}
                      </Badge>
                    </div>
                    {showSelect ? (
                      <Field
                        htmlFor={`broker-map-account-${row.provider_account_id}`}
                        label={row.provider_account_id}
                      >
                        <Select
                          id={`broker-map-account-${row.provider_account_id}`}
                          value={accountMappings[row.provider_account_id] ?? ""}
                          onChange={(event) => {
                            setAccountMappings((current) => ({
                              ...current,
                              [row.provider_account_id]: event.target.value,
                            }));
                            setMappingDirty(true);
                          }}
                        >
                          <option value="">— выбери существующий счёт —</option>
                          {accounts.map((account) => (
                            <option key={account.id} value={account.id}>
                              {account.name}
                            </option>
                          ))}
                        </Select>
                      </Field>
                    ) : (
                      <p className="muted">
                        {row.hermes_account_id
                          ? `Локальный счёт #${row.hermes_account_id}`
                          : "Счёт не сопоставлен"}
                      </p>
                    )}
                    {stored ? (
                      <Button
                        size="sm"
                        type="button"
                        variant="secondary"
                        disabled={busy}
                        onClick={() => void revokeIdentity(stored.mapping_id)}
                      >
                        Отозвать сопоставление счёта
                      </Button>
                    ) : null}
                  </div>
                );
              })}
            </Panel>
          ) : null}
          {preview.instruments.length > 0 ? (
            <Panel label="Сопоставление" title="Инструменты Alfa → Hermes">
              <p className="muted">
                Уже подтверждённые и однозначные ISIN не нужно вводить заново. Новые и спорные
                строки сопоставляются с существующим инструментом Hermes; новые инструменты здесь не
                создаются.
              </p>
              {preview.instruments
                .filter((row) => row.provider_instrument_id)
                .map((row) => {
                  const providerId = row.provider_instrument_id as string;
                  const classification = row.classification ?? "";
                  const stored = effectiveMapping("instrument", providerId);
                  const showSelect = needsMappingSelect(row.status, classification);
                  return (
                    <div key={providerId} className="stack-8">
                      <div className="toolbar">
                        <strong>
                          {providerId} · {row.isin ?? row.display_name ?? "без ISIN"}
                        </strong>
                        <Badge tone={classificationTone(classification)}>
                          {identityLabel(classification, row.status)}
                        </Badge>
                      </div>
                      {showSelect ? (
                        <Field
                          htmlFor={`broker-map-instrument-${providerId}`}
                          label={`${providerId} · ${row.isin ?? row.display_name ?? "без ISIN"}`}
                        >
                          <Select
                            id={`broker-map-instrument-${providerId}`}
                            value={instrumentMappings[providerId] ?? ""}
                            onChange={(event) => {
                              setInstrumentMappings((current) => ({
                                ...current,
                                [providerId]: event.target.value,
                              }));
                              setMappingDirty(true);
                            }}
                          >
                            <option value="">— выбери существующий инструмент —</option>
                            {instruments.map((instrument) => (
                              <option key={instrument.id} value={instrument.id}>
                                {instrument.name}
                                {instrument.isin ? ` · ${instrument.isin}` : ""}
                              </option>
                            ))}
                          </Select>
                        </Field>
                      ) : (
                        <p className="muted">
                          {row.hermes_instrument_id
                            ? `Локальный инструмент #${row.hermes_instrument_id}`
                            : "Инструмент не сопоставлен"}
                        </p>
                      )}
                      {stored ? (
                        <Button
                          size="sm"
                          type="button"
                          variant="secondary"
                          disabled={busy}
                          onClick={() => void revokeIdentity(stored.mapping_id)}
                        >
                          Отозвать сопоставление инструмента
                        </Button>
                      ) : null}
                    </div>
                  );
                })}
            </Panel>
          ) : null}
          {mappingDirty ? (
            <div className="inline-alert" role="status">
              Сопоставление изменилось. Получите обновлённые данные из Альфа PRO перед выбором и
              применением.
            </div>
          ) : null}
          <Table>
            <thead>
              <tr>
                <Th>Счёт / инструмент</Th>
                <Th>Выбор</Th>
                <Th>Статус</Th>
                <Th>Данные из Альфа PRO</Th>
                <Th>Решения владельца</Th>
              </tr>
            </thead>
            <tbody>
              {preview.positions.map((row) => {
                const key = rowKey(row);
                const decision = decisions[key] ?? EMPTY_DECISION;
                const applyable =
                  Boolean(row.fingerprint) &&
                  !row.is_money &&
                  (row.status === "matched" || row.status === "provider_only");
                return (
                  <tr key={key}>
                    <Td>
                      <div className="stack-8">
                        <strong>{row.account_name ?? "Счёт не найден"}</strong>
                        <span>
                          {row.instrument_name ?? "Инструмент не найден"}
                          {row.instrument_isin ? ` · ${row.instrument_isin}` : ""}
                        </span>
                        <span className="muted tiny">ID: {key}</span>
                      </div>
                    </Td>
                    <Td>
                      <input
                        type="checkbox"
                        checked={Boolean(selected[key])}
                        disabled={!applyable || mappingDirty}
                        onChange={(event) =>
                          setSelected((current) => ({ ...current, [key]: event.target.checked }))
                        }
                        aria-label={`Выбрать позицию ${key}`}
                      />
                    </Td>
                    <Td>{labelOf(POSITION_STATUS_LABELS, row.status)}</Td>
                    <Td>
                      <div className="stack-8">
                        <span>
                          Количество: {row.provider_quantity ?? "—"}
                          {row.hermes_quantity != null ? ` vs локально ${row.hermes_quantity}` : ""}
                        </span>
                        {row.is_money ? (
                          <span className="muted">Денежная строка Alfa, не позиция</span>
                        ) : null}
                        <span>
                          Цена брокера (только сравнение): {row.provider_broker_unit_price ?? "—"}
                        </span>
                        <span>
                          НКД брокера (только сравнение): {row.provider_accrued_interest_nkd ?? "—"}
                        </span>
                        <span>
                          P&amp;L брокера (только сравнение):{" "}
                          {row.provider_unrealized_result ?? "—"}
                        </span>
                      </div>
                    </Td>
                    <Td>
                      {applyable ? (
                        <div className="stack-8">
                          <label>
                            Средняя стоимость{" "}
                            <select
                              aria-label={`Решение средней стоимости ${key}`}
                              value={decision.averageCost}
                              disabled={!selected[key]}
                              onChange={(event) =>
                                updateDecision(key, {
                                  averageCost: event.target.value as DecisionAction,
                                })
                              }
                            >
                              <option value="">— выбери —</option>
                              <option value="keep_existing">Оставить текущую</option>
                              <option value="replace">Заменить локальным значением</option>
                            </select>
                          </label>
                          {decision.averageCost === "replace" ? (
                            <input
                              aria-label={`Локальная средняя стоимость ${key}`}
                              value={decision.averageValue}
                              onChange={(event) =>
                                updateDecision(key, { averageValue: event.target.value })
                              }
                              placeholder="Сумма в RUB"
                              disabled={!selected[key]}
                            />
                          ) : null}
                          <label>
                            Рыночная цена{" "}
                            <select
                              aria-label={`Решение рыночной цены ${key}`}
                              value={decision.marketPrice}
                              disabled={!selected[key]}
                              onChange={(event) =>
                                updateDecision(key, {
                                  marketPrice: event.target.value as DecisionAction,
                                })
                              }
                            >
                              <option value="">— выбери —</option>
                              <option value="keep_existing">Оставить текущую</option>
                              <option value="replace">Заменить локальным значением</option>
                            </select>
                          </label>
                          {decision.marketPrice === "replace" ? (
                            <>
                              <input
                                aria-label={`Локальная рыночная цена ${key}`}
                                value={decision.marketValue}
                                onChange={(event) =>
                                  updateDecision(key, { marketValue: event.target.value })
                                }
                                placeholder="Цена в RUB"
                                disabled={!selected[key]}
                              />
                              <input
                                aria-label={`Дата локальной цены ${key}`}
                                type="date"
                                value={decision.marketDate}
                                onChange={(event) =>
                                  updateDecision(key, { marketDate: event.target.value })
                                }
                                disabled={!selected[key]}
                              />
                              <select
                                aria-label={`Источник локальной цены ${key}`}
                                value={decision.marketSource}
                                onChange={(event) =>
                                  updateDecision(key, { marketSource: event.target.value })
                                }
                                disabled={!selected[key]}
                              >
                                <option value="">— источник —</option>
                                <option value="manual">manual</option>
                                <option value="moex">moex</option>
                                <option value="t_invest">t_invest</option>
                              </select>
                            </>
                          ) : null}
                          <label>
                            НКД{" "}
                            <select
                              aria-label={`Решение НКД ${key}`}
                              value={decision.accruedInterest}
                              disabled={!selected[key]}
                              onChange={(event) =>
                                updateDecision(key, {
                                  accruedInterest: event.target.value as DecisionAction,
                                })
                              }
                            >
                              <option value="">
                                {row.status === "provider_only" ? "— не задавать —" : "— выбери —"}
                              </option>
                              {row.status === "provider_only" ? null : (
                                <option value="keep_existing">Оставить текущую</option>
                              )}
                              <option value="replace">Заменить локальным значением</option>
                            </select>
                          </label>
                          {decision.accruedInterest === "replace" ? (
                            <input
                              aria-label={`Локальный НКД ${key}`}
                              value={decision.accruedValue}
                              onChange={(event) =>
                                updateDecision(key, { accruedValue: event.target.value })
                              }
                              placeholder="НКД в RUB"
                              disabled={!selected[key]}
                            />
                          ) : null}
                        </div>
                      ) : (
                        <span className="muted">Строка не применима</span>
                      )}
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        </div>
      ) : null}
      <ConfirmDialog
        open={confirmOpen}
        busy={busy}
        title="Применить базовый срез?"
        description={`В черновик месяца на ${baselineDate || "дату месяца"} будут записаны только ${selectedRows.length} выбранных количеств. Новые сопоставления выбранных строк сохранятся вместе с количествами. Цена, НКД и P&L брокера не копируются.`}
        confirmLabel="Подтвердить базовый срез"
        onCancel={() => setConfirmOpen(false)}
        onConfirm={() => {
          setConfirmOpen(false);
          void apply();
        }}
      />
    </Panel>
  );
}
