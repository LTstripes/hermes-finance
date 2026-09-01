import { Fragment, useEffect, useState } from "react";
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
import {
  createInstrument,
  type InstrumentCreatePayload,
  type InstrumentUpdatePayload,
} from "../api/instruments";
import { listMonths } from "../api/months";
import type { Account, Instrument, ReportingMonth } from "../api/types";
import { formatMoney, formatMonth, formatQuantity } from "../lib/format";
import { labelOf, MONTH_STATUS_LABELS } from "../lib/labels";
import { InstrumentFormDialog } from "./InstrumentFormDialog";
import {
  AlfaSnapshotSummary,
  type AlfaApplyOutcome,
  summarizeAlfaSnapshot,
} from "./month-close/ProviderStepSummary";
import { Badge, Button, ConfirmDialog, Field, Panel, Select, Table, Td, Th } from "./ui";

type DecisionAction = "keep_existing" | "replace" | "";
type PositionFilter = "all" | "applicable" | "attention";
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

const MATCHED_DEFAULT_DECISION: LocalDecision = {
  averageCost: "keep_existing",
  averageValue: "",
  marketPrice: "keep_existing",
  marketValue: "",
  marketDate: "",
  marketSource: "",
  accruedInterest: "keep_existing",
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

function isApplyablePositionRow(row: BrokerPositionRow): boolean {
  return (
    Boolean(row.fingerprint) &&
    !row.is_money &&
    (row.status === "matched" || row.status === "provider_only")
  );
}

function groupPositionRows(rows: BrokerPositionRow[]) {
  const groups = new Map<string, { key: string; accountName: string; rows: BrokerPositionRow[] }>();
  for (const row of rows) {
    const accountName = row.account_name ?? "Счёт не сопоставлен";
    const groupKey = `${String(row.account_id)}:${accountName}`;
    const group = groups.get(groupKey);
    if (group) {
      group.rows.push(row);
    } else {
      groups.set(groupKey, { key: groupKey, accountName, rows: [row] });
    }
  }
  return [...groups.values()];
}

function previewStatusLabel(next: BrokerSnapshotPreview): string {
  if (next.status === "conflicts" && next.eligible_for_apply) {
    return "Есть нерешённые строки; безопасные доступны";
  }
  return labelOf(PREVIEW_STATUS_LABELS, next.status);
}

function previewTone(next: BrokerSnapshotPreview): BadgeTone {
  if (next.status === "conflicts") return "info";
  return next.eligible_for_apply ? "ok" : "closed";
}

function initialDecision(row: BrokerPositionRow): LocalDecision {
  return row.status === "matched" ? MATCHED_DEFAULT_DECISION : EMPTY_DECISION;
}

function joinIdentityParts(parts: Array<string | null | undefined>): string {
  return parts
    .map((part) => part?.trim())
    .filter((part): part is string => Boolean(part))
    .join(" · ");
}

function instrumentMappingLabel(row: BrokerSnapshotPreview["instruments"][number]): string {
  return joinIdentityParts([row.display_name, row.isin, row.ticker]) || "Инструмент без описания";
}

function observedInstrumentLabel(item: {
  display_name: string | null;
  isin: string | null;
  ticker: string | null;
}): string {
  return joinIdentityParts([item.display_name, item.isin, item.ticker]);
}

const ACCOUNT_MAPPING_VISIBLE_INSTRUMENTS = 3;

function accountMappingLabel(row: BrokerSnapshotPreview["accounts"][number]): string {
  const sections = (row.section_codes ?? []).map((code) => `Раздел ${code}`);
  const observed = (row.observed_instruments ?? [])
    .map(observedInstrumentLabel)
    .filter((label) => label !== "");
  const visible = observed.slice(0, ACCOUNT_MAPPING_VISIBLE_INSTRUMENTS);
  const hiddenCount = observed.length - visible.length;
  const hints = visible.length > 0 ? [`Инструменты: ${visible.join(" · ")}`] : [];
  if (hiddenCount > 0) hints.push(`ещё ${hiddenCount}`);
  return [...sections, ...hints].join(" · ") || "Счёт без наблюдений";
}

function localAccountLabel(accountId: number | null, accounts: Account[]): string {
  const account = accountId == null ? null : accounts.find((item) => item.id === accountId);
  return account ? `Сопоставлен со счётом «${account.name}»` : "Сопоставлен с локальным счётом";
}

function localInstrumentLabel(instrumentId: number | null, instruments: Instrument[]): string {
  const instrument =
    instrumentId == null ? null : instruments.find((item) => item.id === instrumentId);
  return instrument
    ? `Сопоставлен с инструментом «${instrument.name}»`
    : "Сопоставлен с локальным инструментом";
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
  initialMonthId?: number;
  monthlyClose?: boolean;
  onApplied?: () => Promise<void> | void;
  onInstrumentCreated?: () => Promise<void> | void;
};

export function BrokerSnapshotPanel({
  accounts,
  instruments,
  initialMonthId,
  monthlyClose = false,
  onApplied,
  onInstrumentCreated,
}: Props) {
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
  const [applyOutcome, setApplyOutcome] = useState<AlfaApplyOutcome | null>(null);
  const [diagnosticCopied, setDiagnosticCopied] = useState(false);
  const [identityMappings, setIdentityMappings] = useState<BrokerIdentityMapping[]>([]);
  const [positionFilter, setPositionFilter] = useState<PositionFilter>("all");
  const [instrumentToCreate, setInstrumentToCreate] = useState<{
    providerId: string;
    name: string | null;
    isin: string | null;
    ticker: string | null;
  } | null>(null);
  const [instrumentCreateBusy, setInstrumentCreateBusy] = useState(false);
  const [instrumentCreateError, setInstrumentCreateError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    async function loadMonths() {
      setMonthsLoading(true);
      setMonthsError(null);
      try {
        const rows = await listMonths(controller.signal);
        if (!controller.signal.aborted) {
          setMonths(rows);
          if (initialMonthId && rows.some((month) => month.id === initialMonthId)) {
            setMonthId(String(initialMonthId));
          }
        }
      } catch (error) {
        if (!controller.signal.aborted) setMonthsError(formatApiError(error));
      } finally {
        if (!controller.signal.aborted) setMonthsLoading(false);
      }
    }
    void loadMonths();
    return () => controller.abort();
  }, [initialMonthId]);

  const selectedMonth = months.find((month) => String(month.id) === monthId) ?? null;
  const baselineDate = selectedMonth?.snapshot_date ?? "";
  const monthClosed = selectedMonth?.status === "closed" || Boolean(preview?.month_closed);
  const selectedRows =
    preview?.positions.filter((row) => selected[rowKey(row)] && isApplyablePositionRow(row)) ?? [];

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
    setPositionFilter("all");
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
    setApplyOutcome(null);
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
    setApplyOutcome(null);
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

  function updateDecision(row: BrokerPositionRow, patch: Partial<LocalDecision>) {
    const key = rowKey(row);
    setDecisions((current) => ({
      ...current,
      [key]: { ...initialDecision(row), ...(current[key] ?? {}), ...patch },
    }));
  }

  function selectAllApplicable() {
    if (!preview || mappingDirty) return;
    setSelected((current) => ({
      ...current,
      ...Object.fromEntries(
        preview.positions.filter(isApplyablePositionRow).map((row) => [rowKey(row), true]),
      ),
    }));
  }

  function clearSelection() {
    setSelected({});
  }

  async function handleInstrumentCreate(
    payload: InstrumentCreatePayload | InstrumentUpdatePayload,
  ) {
    if (!instrumentToCreate) return;
    setInstrumentCreateBusy(true);
    setInstrumentCreateError(null);
    try {
      const created = await createInstrument(payload as InstrumentCreatePayload);
      setInstrumentMappings((current) => ({
        ...current,
        [instrumentToCreate.providerId]: String(created.id),
      }));
      setInstrumentToCreate(null);
      setMappingDirty(true);
      setSuccess(
        "Инструмент создан и выбран для будущего явного сопоставления. Обнови данные из Alfa PRO, чтобы подтвердить его перед применением.",
      );
      await onInstrumentCreated?.();
    } catch (error) {
      setInstrumentCreateError(formatApiError(error));
    } finally {
      setInstrumentCreateBusy(false);
    }
  }

  const moneyProviderInstrumentIds = new Set(
    (preview?.positions ?? [])
      .filter((row) => row.is_money === true && row.provider_instrument_id)
      .map((row) => row.provider_instrument_id as string),
  );
  const moneyInstrumentRows =
    preview?.instruments.filter(
      (row) =>
        row.is_money === true ||
        (row.provider_instrument_id !== null &&
          moneyProviderInstrumentIds.has(row.provider_instrument_id)),
    ) ?? [];
  const instrumentMappingRows =
    preview?.instruments.filter(
      (row) =>
        Boolean(row.provider_instrument_id) &&
        row.is_money !== true &&
        !moneyProviderInstrumentIds.has(row.provider_instrument_id as string),
    ) ?? [];
  const applicablePositionCount = preview?.positions.filter(isApplyablePositionRow).length ?? 0;
  const visiblePositionRows =
    preview?.positions.filter((row) => {
      if (positionFilter === "applicable") return isApplyablePositionRow(row);
      if (positionFilter === "attention") return !isApplyablePositionRow(row);
      return true;
    }) ?? [];
  const groupedPositionRows = groupPositionRows(visiblePositionRows);

  const applyReady = Boolean(
    preview?.eligible_for_apply &&
      !mappingDirty &&
      !monthClosed &&
      Boolean(baselineDate) &&
      selectedRows.length > 0 &&
      selectedRows.every((row) =>
        completeDecision(row, decisions[rowKey(row)] ?? initialDecision(row)),
      ),
  );

  async function apply() {
    if (!preview || !applyReady || !baselineDate) return;
    const previewCounts = summarizeAlfaSnapshot(preview);
    setBusy(true);
    setMessage(null);
    setSuccess(null);
    try {
      const result = await applyBrokerBaseline(Number(monthId), {
        baseline_date: baselineDate,
        mapping: mapping(),
        selections: selectedRows.map((row) =>
          selectionFor(row, decisions[rowKey(row)] ?? initialDecision(row)),
        ),
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
      setApplyOutcome({
        selectedCount: result.selected_count,
        unchangedCount: unchanged,
        attentionCount: previewCounts.unresolved,
      });
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
            disabled={monthsLoading || monthlyClose}
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
      {monthlyClose ? (
        <AlfaSnapshotSummary error={message} outcome={applyOutcome} preview={preview} />
      ) : null}
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
            <Badge tone={previewTone(preview)}>{previewStatusLabel(preview)}</Badge>
          </div>
          {preview.status === "conflicts" && preview.eligible_for_apply ? (
            <div className="inline-alert" role="status">
              Есть нерешённые или спорные строки. Выбирайте только полностью сопоставленные строки;
              остальные останутся без изменений.
            </div>
          ) : null}
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
                const label = accountMappingLabel(row);
                return (
                  <div key={row.provider_account_id} className="stack-8">
                    <div className="toolbar">
                      <div className="stack-8">
                        <strong>{label}</strong>
                        <span className="muted tiny">
                          Короткая подсказка для выбора счёта Hermes
                        </span>
                      </div>
                      <Badge tone={classificationTone(classification)}>
                        {identityLabel(classification, row.status)}
                      </Badge>
                    </div>
                    {showSelect ? (
                      <Field
                        htmlFor={`broker-map-account-${row.provider_account_id}`}
                        label={label}
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
                      <p className="muted">{localAccountLabel(row.hermes_account_id, accounts)}</p>
                    )}
                    <details className="broker-snapshot__mapping-details provider-identity-details">
                      <summary>Подробности источника</summary>
                      <span>Идентификатор счёта Alfa PRO: {row.provider_account_id}</span>
                    </details>
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
          {moneyInstrumentRows.length > 0 ? (
            <p className="muted">
              Денежные строки Alfa не требуют сопоставления инструмента и не участвуют в базовом
              срезе.
            </p>
          ) : null}
          {instrumentMappingRows.length > 0 ? (
            <Panel label="Сопоставление" title="Инструменты Alfa → Hermes">
              <p className="muted">
                Уже подтверждённые и однозначные ISIN не нужно вводить заново. Новые и спорные
                строки можно сопоставить с существующим инструментом Hermes или создать новый
                инструмент отдельным явным действием.
              </p>
              {instrumentMappingRows.map((row) => {
                const providerId = row.provider_instrument_id as string;
                const classification = row.classification ?? "";
                const stored = effectiveMapping("instrument", providerId);
                const showSelect = needsMappingSelect(row.status, classification);
                const label = instrumentMappingLabel(row);
                return (
                  <div key={providerId} className="stack-8">
                    <div className="toolbar">
                      <div className="stack-8">
                        <strong>{label}</strong>
                        <span className="muted tiny">
                          Используй ISIN, тикер и название как подсказки для выбора Hermes
                        </span>
                      </div>
                      <Badge tone={classificationTone(classification)}>
                        {identityLabel(classification, row.status)}
                      </Badge>
                    </div>
                    {showSelect ? (
                      <Field htmlFor={`broker-map-instrument-${providerId}`} label={label}>
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
                        {localInstrumentLabel(row.hermes_instrument_id, instruments)}
                      </p>
                    )}
                    {row.hermes_instrument_id == null ? (
                      <Button
                        size="sm"
                        type="button"
                        variant="secondary"
                        disabled={busy || instrumentCreateBusy}
                        onClick={() => {
                          setInstrumentCreateError(null);
                          setInstrumentToCreate({
                            providerId,
                            name: row.display_name,
                            isin: row.isin,
                            ticker: row.ticker,
                          });
                        }}
                      >
                        Создать инструмент из Alfa PRO
                      </Button>
                    ) : null}
                    <details className="broker-snapshot__mapping-details provider-identity-details">
                      <summary>Подробности источника</summary>
                      <span>Идентификатор инструмента Alfa PRO: {providerId}</span>
                    </details>
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
          <div className="broker-snapshot__position-toolbar">
            <div className="inline-actions">
              <Button
                disabled={busy || mappingDirty || applicablePositionCount === 0}
                onClick={selectAllApplicable}
                size="sm"
                type="button"
                variant="secondary"
              >
                Выбрать все применимые
              </Button>
              <Button
                disabled={busy || Object.values(selected).every((value) => !value)}
                onClick={clearSelection}
                size="sm"
                type="button"
                variant="secondary"
              >
                Снять выбор
              </Button>
            </div>
            <Field htmlFor="broker-position-filter" label="Показывать строки">
              <Select
                id="broker-position-filter"
                value={positionFilter}
                onChange={(event) => setPositionFilter(event.target.value as PositionFilter)}
              >
                <option value="all">Все строки</option>
                <option value="applicable">Только применимые</option>
                <option value="attention">Требуют внимания</option>
              </Select>
            </Field>
            <span className="muted tiny">
              Выбрано: {selectedRows.length} из {applicablePositionCount} применимых
            </span>
          </div>
          <Table className="broker-snapshot__table">
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
              {groupedPositionRows.map((group) => (
                <Fragment key={group.key}>
                  <tr className="broker-snapshot__account-group">
                    <th colSpan={5} scope="rowgroup">
                      Счёт Hermes: {group.accountName}
                    </th>
                  </tr>
                  {group.rows.map((row) => {
                    const key = rowKey(row);
                    const decision = decisions[key] ?? initialDecision(row);
                    const applyable = isApplyablePositionRow(row);
                    return (
                      <tr key={key}>
                        <Td>
                          <div className="stack-8">
                            <strong>{row.account_name ?? "Счёт не найден"}</strong>
                            <span>
                              {row.instrument_name ?? "Инструмент не найден"}
                              {row.instrument_isin ? ` · ${row.instrument_isin}` : ""}
                            </span>
                            <details className="broker-snapshot__row-details provider-identity-details">
                              <summary>Подробности строки</summary>
                              <span>Ключ проверки: {key}</span>
                              {row.provider_account_id || row.provider_instrument_id ? (
                                <span>
                                  Идентификаторы Alfa PRO: {row.provider_account_id ?? "—"} /{" "}
                                  {row.provider_instrument_id ?? "—"}
                                </span>
                              ) : null}
                            </details>
                          </div>
                        </Td>
                        <Td>
                          <input
                            type="checkbox"
                            checked={Boolean(selected[key])}
                            disabled={!applyable || mappingDirty}
                            onChange={(event) =>
                              setSelected((current) => ({
                                ...current,
                                [key]: event.target.checked,
                              }))
                            }
                            aria-label={`Выбрать позицию ${key}`}
                          />
                        </Td>
                        <Td>{labelOf(POSITION_STATUS_LABELS, row.status)}</Td>
                        <Td>
                          <div className="stack-8">
                            <span>
                              <strong>Данные Alfa PRO</strong>: количество{" "}
                              {formatQuantity(row.provider_quantity)}
                              {row.hermes_quantity != null ? (
                                <>
                                  {" · "}
                                  <strong>Текущие данные Hermes</strong>:{" "}
                                  {formatQuantity(row.hermes_quantity)}
                                </>
                              ) : (
                                <> · Текущие данные Hermes: позиции нет</>
                              )}
                            </span>
                            {row.is_money ? (
                              <span className="muted">Денежная строка Alfa PRO, не позиция</span>
                            ) : null}
                            <span>
                              Цена Alfa PRO (только для сравнения):{" "}
                              {formatMoney(row.provider_broker_unit_price)}
                            </span>
                            <span>
                              НКД Alfa PRO (только для сравнения):{" "}
                              {formatMoney(row.provider_accrued_interest_nkd)}
                            </span>
                            <span>
                              P&amp;L Alfa PRO (только для сравнения):{" "}
                              {formatMoney(row.provider_unrealized_result)}
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
                                    updateDecision(row, {
                                      averageCost: event.target.value as DecisionAction,
                                    })
                                  }
                                >
                                  <option value="">— выбери —</option>
                                  {row.status === "matched" ? (
                                    <option value="keep_existing">
                                      Оставить текущее значение Hermes
                                    </option>
                                  ) : null}
                                  <option value="replace">Задать значение Hermes вручную</option>
                                </select>
                              </label>
                              {decision.averageCost === "replace" ? (
                                <input
                                  aria-label={`Локальная средняя стоимость ${key}`}
                                  value={decision.averageValue}
                                  onChange={(event) =>
                                    updateDecision(row, { averageValue: event.target.value })
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
                                    updateDecision(row, {
                                      marketPrice: event.target.value as DecisionAction,
                                    })
                                  }
                                >
                                  <option value="">— выбери —</option>
                                  {row.status === "matched" ? (
                                    <option value="keep_existing">
                                      Оставить текущее значение Hermes
                                    </option>
                                  ) : null}
                                  <option value="replace">Задать значение Hermes вручную</option>
                                </select>
                              </label>
                              {decision.marketPrice === "replace" ? (
                                <>
                                  <input
                                    aria-label={`Локальная рыночная цена ${key}`}
                                    value={decision.marketValue}
                                    onChange={(event) =>
                                      updateDecision(row, { marketValue: event.target.value })
                                    }
                                    placeholder="Цена в RUB"
                                    disabled={!selected[key]}
                                  />
                                  <input
                                    aria-label={`Дата локальной цены ${key}`}
                                    type="date"
                                    value={decision.marketDate}
                                    onChange={(event) =>
                                      updateDecision(row, { marketDate: event.target.value })
                                    }
                                    disabled={!selected[key]}
                                  />
                                  <select
                                    aria-label={`Источник локальной цены ${key}`}
                                    value={decision.marketSource}
                                    onChange={(event) =>
                                      updateDecision(row, { marketSource: event.target.value })
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
                                    updateDecision(row, {
                                      accruedInterest: event.target.value as DecisionAction,
                                    })
                                  }
                                >
                                  <option value="">
                                    {row.status === "provider_only"
                                      ? "— не задавать —"
                                      : "— выбери —"}
                                  </option>
                                  {row.status === "provider_only" ? null : (
                                    <option value="keep_existing">
                                      Оставить текущее значение Hermes
                                    </option>
                                  )}
                                  <option value="replace">Задать значение Hermes вручную</option>
                                </select>
                              </label>
                              {decision.accruedInterest === "replace" ? (
                                <input
                                  aria-label={`Локальный НКД ${key}`}
                                  value={decision.accruedValue}
                                  onChange={(event) =>
                                    updateDecision(row, { accruedValue: event.target.value })
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
                </Fragment>
              ))}
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
      <InstrumentFormDialog
        busy={instrumentCreateBusy}
        error={instrumentCreateError}
        instrument={null}
        onCancel={() => {
          if (!instrumentCreateBusy) {
            setInstrumentToCreate(null);
            setInstrumentCreateError(null);
          }
        }}
        onSubmit={handleInstrumentCreate}
        open={instrumentToCreate !== null}
        prefill={
          instrumentToCreate
            ? {
                name: instrumentToCreate.name,
                isin: instrumentToCreate.isin,
                ticker: instrumentToCreate.ticker,
              }
            : undefined
        }
        sourceLabel="Alfa PRO"
      />
    </Panel>
  );
}
