import { useEffect, useMemo, useRef, useState } from "react";

import { ApiClientError, formatApiError } from "../api/client";
import { updateInstrument } from "../api/instruments";
import {
  applyStatement,
  inspectStatement,
  prepareStatement,
  type StatementApplyItem,
  type StatementCandidate,
  type StatementInspect,
  type StatementMapping,
  type StatementPreparation,
  type StatementRow,
} from "../api/statementImport";
import type { Account, Instrument } from "../api/types";
import type { AlfaStatementTransientOutcome } from "./month-close/statementOutcome";
import { formatDate, formatMoney } from "../lib/format";
import { FLOW_TYPE_LABELS, labelOf } from "../lib/labels";
import { fromKopecks } from "../lib/money";
import { Badge, Button, ConfirmDialog, Field, Panel, Select, Table, Td, Th } from "./ui";

type StatementDecision = {
  action: "" | "create_separate" | "link_existing" | "revise";
  candidateId: string;
};

const EMPTY_DECISION: StatementDecision = { action: "", candidateId: "" };

/**
 * Expected account/instrument identity of one submitted statement row (#567).
 * It is the only identity the apply contract exposes for a returned item, so
 * the authoritative post-apply readback proves the persisted flow against it.
 */
export type StatementApplyExpectation = {
  natural_identity: string | null;
  expected_hermes_account_id: number | null;
  expected_hermes_instrument_id: number | null;
};

export type StatementApplyVerification = {
  submittedCount: number;
  selectedCount: number;
  items: StatementApplyItem[];
  expectations: StatementApplyExpectation[];
};

const UNCONFIRMED_READBACK_MESSAGE =
  "Импорт не подтверждён повторной загрузкой данных — успех не показан. Старая подготовка отменена, проверь файл заново и сверь сохранённые строки.";

const AMBIGUOUS_APPLY_MESSAGE =
  "Запрос применения завершился без ответа, результат неизвестен. Это не успех: старая подготовка отменена, чтобы не применить строки дважды. Проверь файл заново и сверь сохранённые строки.";

const REPORT_STATUS_LABELS: Record<string, string> = {
  applicable: "Отчёт готов к подготовке",
  non_applicable: "Отчёт нельзя импортировать",
  malformed: "Структура отчёта не распознана",
  unsupported: "Есть неподдерживаемые строки",
};

const ROW_STATUS_LABELS: Record<string, string> = {
  matched: "Распознано",
  unmatched: "Требуется сопоставление",
  ambiguous: "Нужно уточнение",
  malformed: "Строка не распознана",
  unsupported: "Строка не поддерживается",
};

const EVENT_KIND_LABELS: Record<string, string> = {
  dividend: "Дивиденды",
  coupon: "Купон",
  redemption: "Погашение",
};

const APPLIED_ACTION_LABELS: Record<string, string> = {
  created: "Создана новая запись",
  linked_existing: "Связано с существующей записью",
  revised: "Создано уточнение записи",
  unchanged: "Изменения не требуются",
  revise: "Создано уточнение записи",
};

function reportMessage(status: string, reason: string | null): string | null {
  if (reason === "wrong_report_family") {
    return "Этот тип отчёта пока не поддерживается. Выберите «Отчет о произведенных выплатах доходов по ценным бумагам».";
  }
  if (reason === "missing_required_schema") {
    return "Hermes не смог распознать структуру отчёта Alfa. Данные не были импортированы.";
  }
  if (status === "malformed") {
    return "Файл отчёта Alfa не удалось безопасно прочитать. Данные не были импортированы.";
  }
  if (status === "non_applicable") {
    return "Этот отчёт нельзя импортировать. Выберите поддерживаемый отчёт Alfa.";
  }
  return reason ? "Не удалось подготовить отчёт к импорту." : null;
}

function rowKey(row: StatementRow, index: number): string {
  return (
    row.natural_identity ??
    row.material_fingerprint ??
    `${row.status}:${row.isin ?? "none"}:${index}`
  );
}

function uniqueValues(values: Array<string | null | undefined>): string[] {
  return [...new Set(values.filter((value): value is string => Boolean(value)))];
}

function retainMappings(current: Record<string, string>, keys: string[]): Record<string, string> {
  const allowed = new Set(keys);
  return Object.fromEntries(
    Object.entries(current).filter(([key, value]) => allowed.has(key) && value),
  );
}

function uniqueInstrumentByIsin(isin: string, instruments: Instrument[]): Instrument | null {
  const matches = instruments.filter((item) => item.isin === isin);
  return matches.length === 1 ? matches[0] : null;
}

function requiresManualInstrumentMapping(status: string): boolean {
  return status === "unmatched" || status === "ambiguous";
}

function moneyDisplay(
  amount: string | null | undefined,
  currency: string | null | undefined,
): string {
  if (amount == null || amount === "") {
    return "—";
  }
  const symbol = !currency || currency === "RUB" ? "₽" : currency;
  return formatMoney(amount, { currency: symbol });
}

function taxDisplay(row: StatementRow): string {
  if (row.tax_available === false || row.tax_amount == null || row.tax_amount === "") {
    return "не указан";
  }
  return moneyDisplay(row.tax_amount, row.gross_currency ?? row.net_currency);
}

function eventLabel(kind: string | null | undefined): string {
  if (!kind) {
    return "—";
  }
  return EVENT_KIND_LABELS[kind] ?? labelOf(FLOW_TYPE_LABELS, kind);
}

function classLabel(row: StatementRow): string {
  if (row.duplicate_class === "duplicate") {
    return "Уже импортировано";
  }
  if (row.duplicate_class === "correction") {
    return "Требует пересмотра";
  }
  if (row.status !== "matched") {
    return ROW_STATUS_LABELS[row.status] ?? "Статус неизвестен";
  }
  if (row.candidates.length > 0) {
    return "Нужно решение";
  }
  return "Новая строка";
}

function classTone(row: StatementRow): "ok" | "draft" | "closed" | "info" {
  if (row.duplicate_class === "duplicate") {
    return "closed";
  }
  if (row.duplicate_class === "correction" || row.status !== "matched") {
    return "draft";
  }
  if (row.candidates.length > 0) {
    return "info";
  }
  return "ok";
}

function lookupName(
  id: number | null | undefined,
  items: Array<{ id: number; name: string }>,
): string {
  if (id == null) {
    return "—";
  }
  return items.find((item) => item.id === id)?.name ?? `#${id}`;
}

function candidateLabel(
  candidate: StatementCandidate,
  accounts: Account[],
  instruments: Instrument[],
): string {
  const net = moneyDisplay(fromKopecks(BigInt(candidate.net_amount_kopecks)), candidate.currency);
  return [
    formatDate(candidate.event_date),
    eventLabel(candidate.flow_type),
    lookupName(candidate.instrument_id, instruments),
    lookupName(candidate.account_id, accounts),
    net,
    `#${candidate.investment_cash_flow_id}`,
  ].join(" · ");
}

function isinSaveKind(
  statementIsin: string,
  instrument: Instrument | undefined,
): "none" | "save" | "same" | "conflict" {
  if (!instrument) {
    return "none";
  }
  const existing = instrument.isin?.trim() ?? "";
  if (!existing) {
    return "save";
  }
  return existing === statementIsin ? "same" : "conflict";
}

function readyForBulkSelect(row: StatementRow): boolean {
  return row.status === "matched" && row.duplicate_class == null && row.candidates.length === 0;
}

type Props = {
  accounts: Account[];
  instruments: Instrument[];
  readOnly?: boolean;
  onApplied?: () => Promise<void> | void;
  onInstrumentsChange?: (instruments: Instrument[]) => void;
  onOutcome?: (outcome: AlfaStatementTransientOutcome | null) => void;
  /**
   * Authoritative post-apply verification gate (#567). When provided, neither
   * the success banner nor the `applied` outcome is published until this
   * resolves; a rejection leaves an explicit unconfirmed state and retires the
   * prepared document so the same preparation cannot be replayed blindly.
   */
  verifyApplied?: (verification: StatementApplyVerification) => Promise<void>;
  /**
   * Reports the whole write + authoritative readback lifetime so the host page
   * can freeze its surrounding context controls (#567).
   */
  onApplyingChange?: (applying: boolean) => void;
};

export function StatementImportPanel({
  accounts,
  instruments,
  readOnly = false,
  onApplied,
  onInstrumentsChange,
  onOutcome,
  verifyApplied,
  onApplyingChange,
}: Props) {
  const [file, setFile] = useState<File | null>(null);
  const [inspected, setInspected] = useState<StatementInspect | null>(null);
  const [accountMappings, setAccountMappings] = useState<Record<string, string>>({});
  const [instrumentMappings, setInstrumentMappings] = useState<Record<string, string>>({});
  const [localInstruments, setLocalInstruments] = useState<Instrument[]>(instruments);
  const [preparation, setPreparation] = useState<StatementPreparation | null>(null);
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [decisions, setDecisions] = useState<Record<string, StatementDecision>>({});
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [applying, setApplying] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [unconfirmed, setUnconfirmed] = useState<string | null>(null);
  const [resultItems, setResultItems] = useState<{ action: string; natural_identity: string }[]>(
    [],
  );
  // Lifecycle identity: an in-flight inspect/prepare/apply completion only
  // publishes while the panel is alive and the file/mapping revision is intact.
  const aliveRef = useRef(true);
  const revisionRef = useRef(0);
  const inFlightRef = useRef(false);
  const onApplyingChangeRef = useRef(onApplyingChange);

  useEffect(() => {
    onApplyingChangeRef.current = onApplyingChange;
  });

  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
      revisionRef.current += 1;
      onApplyingChangeRef.current?.(false);
    };
  }, []);

  useEffect(() => {
    setLocalInstruments(instruments);
  }, [instruments]);

  const accountRefs = useMemo(
    () => uniqueValues(inspected?.rows.map((row) => row.provider_account_ref) ?? []),
    [inspected],
  );
  const isins = useMemo(
    () => uniqueValues(inspected?.rows.map((row) => row.isin) ?? []),
    [inspected],
  );
  const manualMappingIsins = useMemo(
    () =>
      uniqueValues(
        inspected?.rows
          .filter((row) => requiresManualInstrumentMapping(row.status))
          .map((row) => row.isin) ?? [],
      ),
    [inspected],
  );

  const mappingSummary = useMemo(() => {
    let auto = 0;
    let manual = 0;
    let manualNeeded = 0;
    for (const isin of isins) {
      if (instrumentMappings[isin]) {
        manual += 1;
      } else if (uniqueInstrumentByIsin(isin, localInstruments)) {
        auto += 1;
      } else {
        manualNeeded += 1;
      }
    }
    return { auto, manual, manualNeeded, accounts: accountRefs.length, isins: isins.length };
  }, [accountRefs.length, instrumentMappings, isins, localInstruments]);

  function mapping(): StatementMapping {
    return {
      account_mappings: Object.entries(accountMappings)
        .filter(([, hermesId]) => hermesId)
        .map(([provider_account_ref, hermesId]) => ({
          provider_account_ref,
          hermes_account_id: Number(hermesId),
        })),
      instrument_mappings: Object.entries(instrumentMappings)
        .filter(([, hermesId]) => hermesId)
        .map(([isin, hermesId]) => ({ isin, hermes_instrument_id: Number(hermesId) })),
    };
  }

  function clearReview() {
    setPreparation(null);
    setSelected({});
    setDecisions({});
    setResultItems([]);
    setConfirmOpen(false);
  }

  function chooseFile(next: File | null) {
    // Selecting, changing or clearing the document retires every completion
    // that belongs to the previous file/mapping/selection/confirm lifetime.
    revisionRef.current += 1;
    setFile(next);
    setInspected(null);
    clearReview();
    setMessage(null);
    setSuccess(null);
    setUnconfirmed(null);
    onOutcome?.(null);
  }

  function resetMappings() {
    revisionRef.current += 1;
    setAccountMappings({});
    setInstrumentMappings({});
    clearReview();
  }

  async function inspect() {
    if (inFlightRef.current) return;
    if (!file) {
      setMessage("Выбери PDF отчёта Alfa.");
      return;
    }
    clearReview();
    const revision = revisionRef.current;
    inFlightRef.current = true;
    setBusy(true);
    setMessage(null);
    setSuccess(null);
    setUnconfirmed(null);
    onOutcome?.(null);
    try {
      const next = await inspectStatement(file);
      if (!aliveRef.current || revision !== revisionRef.current) return;
      const nextRefs = uniqueValues(next.rows.map((row) => row.provider_account_ref));
      const nextIsins = uniqueValues(next.rows.map((row) => row.isin));
      setInspected(next);
      setAccountMappings((current) => retainMappings(current, nextRefs));
      setInstrumentMappings((current) => retainMappings(current, nextIsins));
      onOutcome?.(
        next.status === "applicable" && next.rows.length === 0 ? { kind: "zero_rows" } : null,
      );
      setMessage(reportMessage(next.status, next.reason));
    } catch (error) {
      if (!aliveRef.current || revision !== revisionRef.current) return;
      setMessage(formatApiError(error));
    } finally {
      inFlightRef.current = false;
      if (aliveRef.current) setBusy(false);
    }
  }

  const mappingReady = Boolean(
    inspected &&
      inspected.status === "applicable" &&
      accountRefs.every((ref) => accountMappings[ref]),
  );

  async function prepare() {
    if (inFlightRef.current) return;
    if (!file || !inspected) {
      setMessage("Сначала выбери PDF и выполни инспекцию.");
      return;
    }
    if (!mappingReady) {
      setMessage("Сопоставь каждый найденный Alfa-счёт с существующим Hermes-счётом.");
      return;
    }
    clearReview();
    const revision = revisionRef.current;
    inFlightRef.current = true;
    setBusy(true);
    setMessage(null);
    setSuccess(null);
    setUnconfirmed(null);
    try {
      const next = await prepareStatement(file, mapping());
      if (!aliveRef.current || revision !== revisionRef.current) return;
      setPreparation(next);
      setMessage(reportMessage(next.status, next.reason));
    } catch (error) {
      if (!aliveRef.current || revision !== revisionRef.current) return;
      setMessage(formatApiError(error));
    } finally {
      inFlightRef.current = false;
      if (aliveRef.current) setBusy(false);
    }
  }

  async function saveCanonicalIsin(isin: string, instrumentId: number) {
    const instrument = localInstruments.find((item) => item.id === instrumentId);
    const kind = isinSaveKind(isin, instrument);
    if (kind !== "save" || !instrument) {
      if (kind === "conflict" && instrument) {
        setMessage(
          `У инструмента «${instrument.name}» уже указан ISIN ${instrument.isin}. ISIN из отчёта ${isin} не записан.`,
        );
      }
      return;
    }
    setBusy(true);
    setMessage(null);
    setSuccess(null);
    try {
      const updated = await updateInstrument(instrumentId, { isin });
      const next = localInstruments.map((item) => (item.id === updated.id ? updated : item));
      setLocalInstruments(next);
      onInstrumentsChange?.(next);
      setSuccess(`ISIN ${isin} сохранён в инструмент «${updated.name}».`);
    } catch (error) {
      setMessage(formatApiError(error));
    } finally {
      setBusy(false);
    }
  }

  function updateDecision(key: string, patch: Partial<StatementDecision>) {
    setDecisions((current) => ({
      ...current,
      [key]: { ...(current[key] ?? EMPTY_DECISION), ...patch },
    }));
  }

  function rowReady(row: StatementRow, index: number): boolean {
    const key = rowKey(row, index);
    if (!selected[key] || row.status !== "matched" || row.duplicate_class === "duplicate")
      return false;
    const decision = decisions[key] ?? EMPTY_DECISION;
    if (row.duplicate_class === "correction") return decision.action === "revise";
    if (row.candidates.length === 0) return decision.action === "";
    if (decision.action === "create_separate") return true;
    return (
      decision.action === "link_existing" &&
      row.expected_candidate_ids.includes(Number(decision.candidateId))
    );
  }

  const selectedRows =
    preparation?.rows
      .map((row, index) => ({ row, index }))
      .filter(
        ({ row, index }) =>
          selected[rowKey(row, index)] &&
          row.status === "matched" &&
          row.duplicate_class !== "duplicate",
      ) ?? [];
  const selectedRowsReady =
    selectedRows.length > 0 && selectedRows.every(({ row, index }) => rowReady(row, index));

  const preparedSummary = useMemo(() => {
    if (!preparation) {
      return null;
    }
    let readyNew = 0;
    let duplicates = 0;
    let needsDecision = 0;
    for (const row of preparation.rows) {
      if (row.duplicate_class === "duplicate") {
        duplicates += 1;
      } else if (
        row.duplicate_class === "correction" ||
        row.candidates.length > 0 ||
        row.status !== "matched"
      ) {
        needsDecision += 1;
      } else {
        readyNew += 1;
      }
    }
    const selectedCount = preparation.rows.filter(
      (row, index) => selected[rowKey(row, index)],
    ).length;
    return {
      total: preparation.rows.length,
      readyNew,
      duplicates,
      needsDecision,
      selectedCount,
    };
  }, [preparation, selected]);

  function selectAllReady() {
    if (!preparation) {
      return;
    }
    const next: Record<string, boolean> = {};
    preparation.rows.forEach((row, index) => {
      next[rowKey(row, index)] = readyForBulkSelect(row);
    });
    setSelected(next);
  }

  async function refreshFacts() {
    try {
      await onApplied?.();
    } catch (error) {
      setMessage(formatApiError(error));
    }
  }

  async function apply() {
    // Single-flight: a second confirmation in the same tick cannot start a
    // second concurrent apply for the same preparation.
    if (inFlightRef.current) return;
    if (!file || !preparation || !selectedRowsReady) return;
    const revision = revisionRef.current;
    const submittedCount = selectedRows.length;
    const selections = selectedRows.map(({ row, index }) => {
      const decision = decisions[rowKey(row, index)] ?? EMPTY_DECISION;
      return {
        natural_identity: row.natural_identity,
        material_fingerprint: row.material_fingerprint,
        expected_hermes_account_id: row.expected_hermes_account_id,
        expected_hermes_instrument_id: row.expected_hermes_instrument_id,
        action: decision.action || undefined,
        existing_cash_flow_id:
          decision.action === "link_existing" ? Number(decision.candidateId) : undefined,
        expected_candidate_ids: row.expected_candidate_ids,
      };
    });
    const expectations: StatementApplyExpectation[] = selectedRows.map(({ row }) => ({
      natural_identity: row.natural_identity,
      expected_hermes_account_id: row.expected_hermes_account_id,
      expected_hermes_instrument_id: row.expected_hermes_instrument_id,
    }));
    inFlightRef.current = true;
    setBusy(true);
    setApplying(true);
    onApplyingChangeRef.current?.(true);
    setMessage(null);
    setSuccess(null);
    setUnconfirmed(null);
    try {
      const result = await applyStatement(file, mapping(), selections, preparation.document_sha256);
      if (!aliveRef.current || revision !== revisionRef.current) return;
      if (!result.success) {
        if (result.error_code === "preview_changed") clearReview();
        setMessage(result.message ?? "Импорт не применён.");
        return;
      }
      if (verifyApplied) {
        try {
          await verifyApplied({
            submittedCount,
            selectedCount: result.selected_count,
            items: result.items,
            expectations,
          });
        } catch (error) {
          if (!aliveRef.current || revision !== revisionRef.current) return;
          clearReview();
          setUnconfirmed(`${UNCONFIRMED_READBACK_MESSAGE} Причина: ${formatApiError(error)}`);
          await refreshFacts();
          return;
        }
      }
      if (!aliveRef.current || revision !== revisionRef.current) return;
      clearReview();
      setResultItems(result.items);
      setSuccess(`Импортировано строк: ${result.selected_count}.`);
      onOutcome?.({ kind: "applied", selectedCount: result.selected_count });
      await refreshFacts();
    } catch (error) {
      if (!aliveRef.current || revision !== revisionRef.current) return;
      // Only a completed HTTP rejection proves that nothing was written. A
      // network/timeout failure after the apply request is ambiguous: it must
      // not read as success and must not leave a replayable preparation.
      const definiteRejection = error instanceof ApiClientError && error.status >= 400;
      if (definiteRejection) {
        setMessage(formatApiError(error));
        return;
      }
      clearReview();
      setUnconfirmed(`${AMBIGUOUS_APPLY_MESSAGE} ${formatApiError(error)}`);
      await refreshFacts();
    } finally {
      inFlightRef.current = false;
      if (aliveRef.current) {
        setBusy(false);
        setApplying(false);
      }
      onApplyingChangeRef.current?.(false);
    }
  }

  function focusInstrumentMapping(isin: string) {
    const target = document.getElementById(`statement-map-instrument-${isin}`);
    if (!(target instanceof HTMLSelectElement)) {
      return;
    }
    target.scrollIntoView?.({ behavior: "smooth", block: "center" });
    target.focus();
  }

  return (
    <Panel className="statement-import" label="Alfa PDF" title="Импорт отчёта Alfa">
      <p className="muted">
        PDF читается только в памяти. При применении Hermes повторно проверит тот же файл и
        убедится, что он не изменился.
      </p>
      {readOnly ? (
        <div className="inline-alert inline-alert--warn" role="status">
          Месяц закрыт. Проверка PDF доступна, но применение выплат заблокировано до явного
          повторного открытия месяца.
        </div>
      ) : null}
      <div className="editor-grid">
        <Field htmlFor="statement-file" label="PDF отчёта Alfa">
          <input
            id="statement-file"
            type="file"
            accept="application/pdf"
            disabled={applying}
            onChange={(event) => chooseFile(event.target.files?.[0] ?? null)}
          />
        </Field>
      </div>
      <div className="toolbar">
        <Button onClick={() => void inspect()} disabled={busy || !file}>
          Проверить отчёт
        </Button>
        {inspected ? (
          <Button onClick={() => void prepare()} disabled={busy || !mappingReady}>
            Подготовить к импорту
          </Button>
        ) : null}
        {preparation ? (
          <Button
            onClick={() => setConfirmOpen(true)}
            disabled={readOnly || busy || !selectedRowsReady}
            variant="primary"
          >
            Применить выбранные строки
          </Button>
        ) : null}
      </div>
      {message ? (
        <div className="inline-alert inline-alert--error" role="alert">
          {message}
        </div>
      ) : null}
      {unconfirmed ? (
        <div className="inline-alert inline-alert--warn" role="alert">
          {unconfirmed}
        </div>
      ) : null}
      {success ? (
        <div className="month-workspace__save-ok" role="status">
          {success}
        </div>
      ) : null}
      {inspected ? (
        <div className="stack-12">
          {inspected.status === "applicable" && inspected.rows.length === 0 ? (
            <div className="inline-alert inline-alert--info" role="status">
              В этом PDF нет подходящих выплат за отчётные месяцы. Это результат только текущей
              проверки: после перезапуска файл не считается просмотренным.
            </div>
          ) : null}
          <div className="statement-import__summary">
            <Badge tone={inspected.status === "applicable" ? "ok" : "closed"}>
              {REPORT_STATUS_LABELS[inspected.status] ?? "Статус отчёта неизвестен"}
            </Badge>
            <span className="muted">Найдено строк: {inspected.rows.length}</span>
            <span className="muted">
              ISIN: автоматически — {mappingSummary.auto} · вручную — {mappingSummary.manual} ·
              требуется сопоставить — {mappingSummary.manualNeeded}
            </span>
          </div>
          <Panel
            className="statement-import__mapping"
            label="Сопоставление"
            title="Временное сопоставление для этой проверки"
          >
            <div className="statement-import__mapping-toolbar">
              <Button disabled={busy} onClick={resetMappings} size="sm" type="button">
                Сбросить сопоставления
              </Button>
              <span className="muted tiny">
                Сопоставления Alfa-счетов живут только в этой сессии и не записываются в базу.
              </span>
            </div>
            {manualMappingIsins.length > 0 ? (
              <div
                className="inline-alert inline-alert--warn statement-import__mapping-help"
                role="note"
              >
                Для ISIN со статусом «Требуется сопоставление» выбери существующий инструмент Hermes
                в списке «Выбрать инструмент Hermes…» ниже. Это временное сопоставление только для
                этой проверки; новый инструмент автоматически не создаётся.
              </div>
            ) : null}
            <div className="statement-import__mapping-grid">
              <div className="stack-12">
                <p className="panel__label section-form-label">Счета Alfa</p>
                {accountRefs.map((ref) => (
                  <Field
                    key={ref}
                    htmlFor={`statement-map-account-${ref}`}
                    label={`Alfa-счёт ${ref}`}
                  >
                    <Select
                      disabled={applying}
                      id={`statement-map-account-${ref}`}
                      value={accountMappings[ref] ?? ""}
                      onChange={(event) => {
                        // A mapping change retires the previously prepared
                        // identity; an in-flight completion must not publish.
                        revisionRef.current += 1;
                        setAccountMappings((current) => ({
                          ...current,
                          [ref]: event.target.value,
                        }));
                        clearReview();
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
                ))}
              </div>
              <div className="stack-12">
                <p className="panel__label section-form-label">ISIN</p>
                {isins.map((isin) => {
                  const auto = uniqueInstrumentByIsin(isin, localInstruments);
                  const selectedId = instrumentMappings[isin];
                  const selectedInstrument = localInstruments.find(
                    (item) => String(item.id) === selectedId,
                  );
                  const kind = isinSaveKind(isin, selectedInstrument);
                  return (
                    <div className="statement-import__isin-row" key={isin}>
                      <div className="statement-import__isin-head">
                        <code>{isin}</code>
                        {auto && !selectedId ? (
                          <Badge tone="ok">совпало автоматически</Badge>
                        ) : selectedId ? (
                          <Badge tone="draft">сопоставлено вручную</Badge>
                        ) : (
                          <Badge tone="closed">требует сопоставления</Badge>
                        )}
                      </div>
                      <Field
                        htmlFor={`statement-map-instrument-${isin}`}
                        label={`Инструмент для ${isin}`}
                      >
                        <Select
                          disabled={applying}
                          id={`statement-map-instrument-${isin}`}
                          value={instrumentMappings[isin] ?? ""}
                          onChange={(event) => {
                            revisionRef.current += 1;
                            setInstrumentMappings((current) => ({
                              ...current,
                              [isin]: event.target.value,
                            }));
                            clearReview();
                          }}
                        >
                          <option value="">
                            {auto ? `Автоматически: ${auto.name}` : "Выбрать инструмент Hermes…"}
                          </option>
                          {localInstruments.map((instrument) => (
                            <option key={instrument.id} value={instrument.id}>
                              {instrument.name}
                              {instrument.isin ? ` · ${instrument.isin}` : ""}
                            </option>
                          ))}
                        </Select>
                      </Field>
                      {kind === "save" && selectedInstrument ? (
                        <>
                          <span className="muted tiny">
                            У инструмента пока нет ISIN. При необходимости сохрани ISIN из отчёта.
                          </span>
                          <Button
                            disabled={busy}
                            onClick={() => void saveCanonicalIsin(isin, selectedInstrument.id)}
                            size="sm"
                            type="button"
                          >
                            Сохранить ISIN в инструмент
                          </Button>
                        </>
                      ) : null}
                      {kind === "same" ? (
                        <span className="muted tiny">ISIN уже сохранён в инструменте</span>
                      ) : null}
                      {kind === "conflict" && selectedInstrument ? (
                        <div className="inline-alert inline-alert--warn" role="status">
                          У инструмента «{selectedInstrument.name}» уже ISIN{" "}
                          {selectedInstrument.isin}. ISIN из отчёта {isin} не будет записан.
                        </div>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            </div>
          </Panel>
          <Table className="statement-import__inspect-table">
            <thead>
              <tr>
                <Th>Счёт у Alfa</Th>
                <Th>ISIN</Th>
                <Th>Событие</Th>
                <Th>Статус</Th>
              </tr>
            </thead>
            <tbody>
              {inspected.rows.map((row) => (
                <tr
                  key={`${row.provider_account_ref ?? "none"}:${row.isin ?? "none"}:${row.event_kind ?? "none"}:${row.record_date ?? "none"}:${row.event_date ?? "none"}`}
                >
                  <Td>{row.provider_account_ref ?? "—"}</Td>
                  <Td>{row.isin ?? "—"}</Td>
                  <Td>{eventLabel(row.event_kind)}</Td>
                  <Td>
                    <div className="statement-import__inspect-status">
                      <span>{ROW_STATUS_LABELS[row.status] ?? "Статус неизвестен"}</span>
                      {row.isin && requiresManualInstrumentMapping(row.status) ? (
                        <Button
                          onClick={() => focusInstrumentMapping(row.isin as string)}
                          size="sm"
                          type="button"
                        >
                          Сопоставить
                        </Button>
                      ) : null}
                    </div>
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </div>
      ) : null}
      {preparation ? (
        <div className="stack-12">
          <div className="statement-import__summary">
            <Badge tone={preparation.status === "applicable" ? "ok" : "closed"}>
              {REPORT_STATUS_LABELS[preparation.status] ?? "Статус отчёта неизвестен"}
            </Badge>
            {preparedSummary ? (
              <span className="muted">
                {preparedSummary.total} строк · {preparedSummary.readyNew} новых ·{" "}
                {preparedSummary.duplicates} дубля · {preparedSummary.needsDecision} требует решения
                · выбрано {preparedSummary.selectedCount}
              </span>
            ) : (
              <span className="muted">Файл проверен и готов к применению.</span>
            )}
            <Button disabled={busy} onClick={selectAllReady} size="sm" type="button">
              Выбрать все готовые
            </Button>
            <Button disabled={busy} onClick={() => setSelected({})} size="sm" type="button">
              Снять выбор
            </Button>
          </div>
          <Table className="statement-import__prepare-table">
            <thead>
              <tr>
                <Th className="statement-import__prepare-table__select">Выбор</Th>
                <Th className="statement-import__prepare-table__instrument">Инструмент</Th>
                <Th className="statement-import__prepare-table__account">Счёт</Th>
                <Th className="statement-import__prepare-table__event">Событие</Th>
                <Th numeric>Брутто</Th>
                <Th numeric>Налог</Th>
                <Th numeric>Нетто</Th>
                <Th className="statement-import__prepare-table__class">Класс</Th>
                <Th className="statement-import__prepare-table__decision">Кандидаты / решение</Th>
              </tr>
            </thead>
            <tbody>
              {preparation.rows.map((row, index) => {
                const key = rowKey(row, index);
                const decision = decisions[key] ?? EMPTY_DECISION;
                const duplicate = row.duplicate_class === "duplicate";
                const correction = row.duplicate_class === "correction";
                const selectable = row.status === "matched" && !duplicate;
                const instrumentName = lookupName(
                  row.expected_hermes_instrument_id,
                  localInstruments,
                );
                const accountName = lookupName(row.expected_hermes_account_id, accounts);
                return (
                  <tr key={key}>
                    <Td className="statement-import__prepare-table__select">
                      <input
                        type="checkbox"
                        checked={Boolean(selected[key])}
                        disabled={!selectable || busy}
                        onChange={(event) =>
                          setSelected((current) => ({ ...current, [key]: event.target.checked }))
                        }
                        aria-label={`Выбрать строку ${index + 1}`}
                      />
                    </Td>
                    <Td className="statement-import__prepare-table__instrument">
                      <div className="statement-import__identity">
                        <span className="statement-import__identity-name">{instrumentName}</span>
                        <span className="muted tiny">{row.isin ?? "—"}</span>
                      </div>
                    </Td>
                    <Td className="statement-import__prepare-table__account">
                      <div className="statement-import__account">{accountName}</div>
                    </Td>
                    <Td className="statement-import__prepare-table__event">
                      <div className="statement-import__event">
                        <span>{eventLabel(row.event_kind)}</span>
                        <span className="muted tiny">
                          {row.event_date ? formatDate(row.event_date) : "—"}
                        </span>
                      </div>
                    </Td>
                    <Td numeric>
                      {moneyDisplay(row.gross_amount, row.gross_currency ?? row.net_currency)}
                    </Td>
                    <Td numeric>{taxDisplay(row)}</Td>
                    <Td numeric>
                      {moneyDisplay(row.net_amount, row.net_currency ?? row.gross_currency)}
                    </Td>
                    <Td className="statement-import__prepare-table__class">
                      <Badge tone={classTone(row)}>{classLabel(row)}</Badge>
                    </Td>
                    <Td className="statement-import__prepare-table__decision">
                      <div className="statement-import__decision">
                        {duplicate ? (
                          <span className="muted statement-import__decision-label">
                            Без изменений
                          </span>
                        ) : correction ? (
                          <Select
                            aria-label={`Решение correction ${index + 1}`}
                            value={decision.action}
                            disabled={busy || !selected[key]}
                            onChange={(event) =>
                              updateDecision(key, {
                                action: event.target.value as StatementDecision["action"],
                              })
                            }
                          >
                            <option value="">— выбери —</option>
                            <option value="revise">Пересмотреть локальную запись</option>
                          </Select>
                        ) : row.candidates.length === 0 ? (
                          <span className="statement-import__decision-label">Создать</span>
                        ) : (
                          <div className="stack-8">
                            <Select
                              aria-label={`Решение кандидата ${index + 1}`}
                              value={decision.action}
                              disabled={busy || !selected[key]}
                              onChange={(event) =>
                                updateDecision(key, {
                                  action: event.target.value as StatementDecision["action"],
                                  candidateId: "",
                                })
                              }
                            >
                              <option value="">— выбери —</option>
                              <option value="create_separate">Создать отдельно</option>
                              <option value="link_existing">Связать существующую</option>
                            </Select>
                            {decision.action === "link_existing" ? (
                              <Select
                                aria-label={`Кандидат для ссылки ${index + 1}`}
                                value={decision.candidateId}
                                disabled={busy || !selected[key]}
                                onChange={(event) =>
                                  updateDecision(key, { candidateId: event.target.value })
                                }
                              >
                                <option value="">— выбери существующую запись —</option>
                                {row.candidates.map((candidate) => (
                                  <option
                                    key={candidate.investment_cash_flow_id}
                                    value={candidate.investment_cash_flow_id}
                                  >
                                    {candidateLabel(candidate, accounts, localInstruments)}
                                  </option>
                                ))}
                              </Select>
                            ) : null}
                          </div>
                        )}
                      </div>
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        </div>
      ) : null}
      {resultItems.length > 0 ? (
        <Panel label="Итог импорта" title="Обработанные строки">
          <ul>
            {resultItems.map((item) => (
              <li key={`${item.action}:${item.natural_identity}`}>
                {APPLIED_ACTION_LABELS[item.action] ?? "Строка обработана"}
              </li>
            ))}
          </ul>
        </Panel>
      ) : null}
      <ConfirmDialog
        open={confirmOpen}
        busy={busy}
        title="Применить отчёт?"
        description={`Будут применены все ${selectedRows.length} отмеченные строки; каждая должна иметь явное решение владельца.`}
        confirmLabel="Подтвердить и применить"
        onCancel={() => setConfirmOpen(false)}
        onConfirm={() => {
          setConfirmOpen(false);
          void apply();
        }}
      />
    </Panel>
  );
}
