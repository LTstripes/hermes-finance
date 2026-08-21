import { useState } from "react";

import { formatApiError } from "../api/client";
import {
  applyStatement,
  prepareStatement,
  type StatementMapping,
  type StatementPreparation,
} from "../api/statementImport";
import type { Account } from "../api/types";
import { Badge, Button, Field, Panel, Table, Td, Th } from "./ui";

export function StatementImportPanel({ accounts }: { accounts: Account[] }) {
  const [file, setFile] = useState<File | null>(null);
  const [providerRefs, setProviderRefs] = useState<Record<number, string>>({});
  const [preparation, setPreparation] = useState<StatementPreparation | null>(null);
  const [actions, setActions] = useState<
    Record<string, "create_separate" | "link_existing" | "revise">
  >(() => ({}));
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  function mapping(): StatementMapping {
    return {
      account_mappings: accounts
        .map((account) => ({
          hermes_account_id: account.id,
          provider_account_ref: providerRefs[account.id]?.trim() ?? "",
        }))
        .filter((row) => row.provider_account_ref),
      instrument_mappings: [],
    };
  }

  async function prepare() {
    if (!file) return setMessage("Выбери PDF отчёта Alfa.");
    setBusy(true);
    setMessage(null);
    try {
      const next = await prepareStatement(file, mapping());
      setPreparation(next);
      setMessage(next.reason);
    } catch (error) {
      setMessage(formatApiError(error));
    } finally {
      setBusy(false);
    }
  }

  async function apply() {
    if (!file || !preparation) return;
    const rows = preparation.rows.filter(
      (row) => row.status === "matched" && row.natural_identity && row.material_fingerprint,
    );
    if (rows.length === 0) return setMessage("В подготовке нет применимых строк.");
    setBusy(true);
    setMessage(null);
    try {
      const result = await applyStatement(
        file,
        mapping(),
        rows.map((row) => ({
          natural_identity: row.natural_identity,
          material_fingerprint: row.material_fingerprint,
          expected_hermes_account_id: row.expected_hermes_account_id,
          expected_hermes_instrument_id: row.expected_hermes_instrument_id,
          action: row.duplicate_class
            ? (actions[row.natural_identity as string] ?? "revise")
            : undefined,
          expected_candidate_ids: row.expected_candidate_ids,
        })),
        preparation.document_sha256,
      );
      setMessage(
        result.success
          ? `Импортировано строк: ${result.selected_count}.`
          : (result.message ?? "Импорт не применён."),
      );
      if (result.success) setPreparation(null);
    } catch (error) {
      setMessage(formatApiError(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel label="Alfa PDF" title="Импорт отчёта Alfa">
      <p className="muted">
        Файл читается только в памяти. После подготовки PDF нужно отправить заново для атомарного
        применения.
      </p>
      <div className="editor-grid">
        <Field htmlFor="statement-file" label="PDF отчёта">
          <input
            id="statement-file"
            type="file"
            accept="application/pdf"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
        </Field>
        {accounts.map((account) => (
          <Field
            key={account.id}
            htmlFor={`statement-account-${account.id}`}
            label={`Alfa ID · ${account.name}`}
          >
            <input
              id={`statement-account-${account.id}`}
              value={providerRefs[account.id] ?? ""}
              onChange={(event) =>
                setProviderRefs((current) => ({ ...current, [account.id]: event.target.value }))
              }
            />
          </Field>
        ))}
      </div>
      <div className="toolbar">
        <Button onClick={() => void prepare()} disabled={busy || !file}>
          Подготовить отчёт
        </Button>
        {preparation ? (
          <Button onClick={() => void apply()} disabled={busy} variant="primary">
            Применить выбранные строки
          </Button>
        ) : null}
      </div>
      {message ? (
        <div className="inline-alert inline-alert--error" role="alert">
          {message}
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
                <Th>Статус</Th>
                <Th>Счёт / ISIN</Th>
                <Th>Класс</Th>
                <Th>Решение</Th>
              </tr>
            </thead>
            <tbody>
              {preparation.rows.map((row, index) => {
                const key =
                  row.natural_identity ??
                  row.material_fingerprint ??
                  `${row.status}-${row.isin ?? "none"}-${row.event_date ?? "none"}`;
                return (
                  <tr key={key}>
                    <Td>{row.status}</Td>
                    <Td>
                      {row.expected_hermes_account_id ?? "—"} · {String(row.isin ?? "—")}
                    </Td>
                    <Td>{row.duplicate_class ?? "NEW"}</Td>
                    <Td>
                      {row.duplicate_class ? (
                        <select
                          aria-label={`Решение строки ${index}`}
                          value={actions[row.natural_identity as string] ?? "revise"}
                          onChange={(event) =>
                            setActions((current) => ({
                              ...current,
                              [row.natural_identity as string]: event.target.value as
                                | "create_separate"
                                | "link_existing"
                                | "revise",
                            }))
                          }
                        >
                          <option value="revise">Пересмотреть</option>
                          <option value="create_separate">Создать отдельно</option>
                          <option value="link_existing">Связать существующее</option>
                        </select>
                      ) : (
                        "Создать"
                      )}
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        </div>
      ) : null}
    </Panel>
  );
}
