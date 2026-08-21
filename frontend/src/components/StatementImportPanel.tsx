import { useMemo, useState } from "react";

import { formatApiError } from "../api/client";
import {
  applyStatement,
  inspectStatement,
  prepareStatement,
  type StatementInspect,
  type StatementMapping,
  type StatementPreparation,
  type StatementRow,
} from "../api/statementImport";
import type { Account, Instrument } from "../api/types";
import { Badge, Button, ConfirmDialog, Field, Panel, Select, Table, Td, Th } from "./ui";

type StatementDecision = {
  action: "" | "create_separate" | "link_existing" | "revise";
  candidateId: string;
};

const EMPTY_DECISION: StatementDecision = { action: "", candidateId: "" };

function rowKey(row: StatementRow, index: number): string {
  return (
    row.natural_identity ??
    row.material_fingerprint ??
    `${row.status}:${row.isin ?? "none"}:${index}`
  );
}

type Props = {
  accounts: Account[];
  instruments: Instrument[];
  onApplied?: () => Promise<void> | void;
};

export function StatementImportPanel({ accounts, instruments, onApplied }: Props) {
  const [file, setFile] = useState<File | null>(null);
  const [inspected, setInspected] = useState<StatementInspect | null>(null);
  const [accountMappings, setAccountMappings] = useState<Record<string, string>>({});
  const [instrumentMappings, setInstrumentMappings] = useState<Record<string, string>>({});
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

  const accountRefs = useMemo(
    () => [
      ...new Set(
        inspected?.rows
          .map((row) => row.provider_account_ref)
          .filter((value): value is string => Boolean(value)) ?? [],
      ),
    ],
    [inspected],
  );
  const isins = useMemo(
    () => [
      ...new Set(
        inspected?.rows.map((row) => row.isin).filter((value): value is string => Boolean(value)) ??
          [],
      ),
    ],
    [inspected],
  );

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
    setAccountMappings({});
    setInstrumentMappings({});
    clearReview();
    setMessage(null);
    setSuccess(null);
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
    try {
      const next = await inspectStatement(file);
      setInspected(next);
      if (next.reason) setMessage(next.reason);
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
      if (next.reason) setMessage(next.reason);
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
      await onApplied?.();
    } catch (error) {
      setMessage(formatApiError(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel label="Alfa PDF" title="Импорт отчёта Alfa">
      <p className="muted">
        PDF читается только в памяти. На apply отправляется тот же File и проверяется его SHA-256.
      </p>
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
          Инспектировать PDF
        </Button>
        {inspected ? (
          <Button onClick={() => void prepare()} disabled={busy || !mappingReady}>
            Подготовить отчёт
          </Button>
        ) : null}
        {preparation ? (
          <Button
            onClick={() => setConfirmOpen(true)}
            disabled={busy || !selectedRowsReady}
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
          <div className="toolbar">
            <Badge tone={inspected.status === "applicable" ? "ok" : "closed"}>
              {inspected.status}
            </Badge>
            <span className="muted">Найдено строк: {inspected.rows.length}</span>
          </div>
          <Panel label="Сопоставление" title="Временные mapping для этого просмотра">
            {accountRefs.map((ref) => (
              <Field key={ref} htmlFor={`statement-map-account-${ref}`} label={`Alfa-счёт ${ref}`}>
                <Select
                  id={`statement-map-account-${ref}`}
                  value={accountMappings[ref] ?? ""}
                  onChange={(event) => {
                    setAccountMappings((current) => ({ ...current, [ref]: event.target.value }));
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
            {isins.map((isin) => (
              <Field
                key={isin}
                htmlFor={`statement-map-instrument-${isin}`}
                label={`ISIN ${isin} (необязательно при уникальном совпадении)`}
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
                  <option value="">— авто только при уникальном ISIN —</option>
                  {instruments.map((instrument) => (
                    <option key={instrument.id} value={instrument.id}>
                      {instrument.name}
                    </option>
                  ))}
                </Select>
              </Field>
            ))}
          </Panel>
          <Table>
            <thead>
              <tr>
                <Th>Provider account ref</Th>
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
                  <Td>{row.event_kind ?? "—"}</Td>
                  <Td>{row.status}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </div>
      ) : null}
      {preparation ? (
        <div className="stack-12">
          <div className="toolbar">
            <Badge tone={preparation.status === "applicable" ? "ok" : "closed"}>
              {preparation.status}
            </Badge>
            <span className="muted">SHA-256: {preparation.document_sha256}</span>
          </div>
          <Table>
            <thead>
              <tr>
                <Th>Выбор</Th>
                <Th>Статус</Th>
                <Th>Класс</Th>
                <Th>Кандидаты / решение</Th>
              </tr>
            </thead>
            <tbody>
              {preparation.rows.map((row, index) => {
                const key = rowKey(row, index);
                const decision = decisions[key] ?? EMPTY_DECISION;
                const duplicate = row.duplicate_class === "duplicate";
                const correction = row.duplicate_class === "correction";
                const selectable = row.status === "matched" && !duplicate;
                return (
                  <tr key={key}>
                    <Td>
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
                    <Td>{row.status}</Td>
                    <Td>
                      {duplicate
                        ? "DUPLICATE · уже импортировано"
                        : correction
                          ? "CORRECTION · требуется revise"
                          : "NEW"}
                    </Td>
                    <Td>
                      {duplicate ? (
                        <span className="muted">Без изменений; повторно не отправляется.</span>
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
                        <span>Создать отдельную запись после выбора строки</span>
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
                              <option value="">— выбери exact candidate —</option>
                              {row.candidates.map((candidate) => (
                                <option
                                  key={candidate.investment_cash_flow_id}
                                  value={candidate.investment_cash_flow_id}
                                >
                                  #{candidate.investment_cash_flow_id} ·{" "}
                                  {candidate.net_amount_kopecks} kopecks
                                </option>
                              ))}
                            </Select>
                          ) : null}
                        </div>
                      )}
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        </div>
      ) : null}
      {resultItems.length > 0 ? (
        <Panel label="Результат apply" title="Применённые строки">
          <ul>
            {resultItems.map((item) => (
              <li key={`${item.action}:${item.natural_identity}`}>
                {item.action}: {item.natural_identity}
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
