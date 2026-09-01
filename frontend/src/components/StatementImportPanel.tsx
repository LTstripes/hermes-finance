import { useEffect, useMemo, useState } from "react";

import { formatApiError } from "../api/client";
import { updateInstrument } from "../api/instruments";
import {
  applyStatement,
  inspectStatement,
  prepareStatement,
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
};

export function StatementImportPanel({
  accounts,
  instruments,
  readOnly = false,
  onApplied,
  onInstrumentsChange,
  onOutcome,
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
  const [message, setMessage] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [resultItems, setResultItems] = useState<{ action: string; natural_identity: string }[]>(
    [],
  );

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
    setFile(next);
    setInspected(null);
    clearReview();
    setMessage(null);
    setSuccess(null);
    onOutcome?.(null);
  }

  function resetMappings() {
    setAccountMappings({});
    setInstrumentMappings({});
    clearReview();
  }

  async function inspect() {
    if (!file) {
      setMessage("Выбери PDF отчёта Alfa.");
      return;
    }
    setBusy(true);
    setMessage(null);
    setSuccess(null);
    clearReview();
    onOutcome?.(null);
    try {
      const next = await inspectStatement(file);
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
      setMessage(formatApiError(error));
    } finally {
      setBusy(false);
    }
  }

  const mappingReady = Boolean(
    inspected &&
      inspected.status === "applicable" &&
      accountRefs.every((ref) => accountMappings[ref]),
  );

  async function prepare() {
    if (!file || !inspected) {
      setMessage("Сначала выбери PDF и выполни инспекцию.");
      return;
    }
    if (!mappingReady) {
      setMessage("Сопоставь каждый найденный Alfa-счёт с существующим Hermes-счётом.");
      return;
    }
    setBusy(true);
    setMessage(null);
    setSuccess(null);
    clearReview();
    try {
      const next = await prepareStatement(file, mapping());
      setPreparation(next);
      setMessage(reportMessage(next.status, next.reason));
    } catch (error) {
      setMessage(formatApiError(error));
    } finally {
      setBusy(false);
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

  async function apply() {
    if (!file || !preparation || !selectedRowsReady) return;
    setBusy(true);
    setMessage(null);
    setSuccess(null);
    try {
      const result = await applyStatement(
        file,
        mapping(),
        selectedRows.map(({ row, index }) => {
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
        }),
        preparation.document_sha256,
      );
      if (!result.success) {
        if (result.error_code === "preview_changed") clearReview();
        setMessage(result.message ?? "Импорт не применён.");
        return;
      }
      setResultItems(result.items);
      setPreparation(null);
      setSelected({});
      setDecisions({});
      setConfirmOpen(false);
      setSuccess(`Импортировано строк: ${result.selected_count}.`);
      onOutcome?.({ kind: "applied", selectedCount: result.selected_count });
      await onApplied?.();
    } catch (error) {
      setMessage(formatApiError(error));
    } finally {
      setBusy(false);
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
                      id={`statement-map-account-${ref}`}
                      value={accountMappings[ref] ?? ""}
                      onChange={(event) => {
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
                          id={`statement-map-instrument-${isin}`}
                          value={instrumentMappings[isin] ?? ""}
                          onChange={(event) => {
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
                            disabled={!selected[key]}
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
                              disabled={!selected[key]}
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
                                disabled={!selected[key]}
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
