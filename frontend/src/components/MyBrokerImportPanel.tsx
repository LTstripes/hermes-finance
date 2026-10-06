import { useRef, useState } from "react";
import { listAccounts } from "../api/accounts";
import { confirmBrokerIdentityMapping } from "../api/brokerIdentityMappings";
import { formatApiError } from "../api/client";
import { listInstruments } from "../api/instruments";
import {
  applyMyBroker,
  type MyBrokerImport,
  type MyBrokerPreview,
  previewMyBroker,
  readMyBrokerImport,
} from "../api/mybrokerImport";
import type { Account, Instrument } from "../api/types";
import { Button, Field, Panel, Select, Table, Td, Th } from "./ui";

function stable(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stable).join(",")}]`;
  if (value !== null && typeof value === "object") {
    const record = value as Record<string, unknown>;
    return `{${Object.keys(record)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${stable(record[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

export function verifyMyBrokerReadback(
  preview: MyBrokerPreview,
  applied: MyBrokerImport,
  reread: MyBrokerImport,
) {
  if (
    applied.import_id !== reread.import_id ||
    applied.confirmation_digest !== reread.confirmation_digest ||
    stable(preview.document) !== stable(reread.document) ||
    stable(preview.mappings) !== stable(reread.mappings) ||
    reread.coverage_state !== "unknown"
  ) {
    throw new Error("Сохранённые данные не совпали с предпросмотром. Проверь отчёт повторно.");
  }
}

const REASONS: Record<string, string> = {
  pending_not_cash: "Есть нерассчитанная сделка: фактического денежного потока пока нет.",
  endpoint_unsettled: "Фактическое и ожидаемое количество бумаг на конец периода различаются.",
  trade_ids_incomplete:
    "Не хватает одного из двух ID сделки: автоматическое сопоставление недоступно.",
  settlement_cash_missing_or_ambiguous: "Денежная строка расчётов отсутствует или неоднозначна.",
  commission_basis_unresolved: "Не установлено, включена ли комиссия в сумму расчётов.",
  money_link_ambiguous: "Первый ID связан с несколькими сделками: нужна сверка.",
  money_link_missing: "Для денежной строки не найдена сделка с полным ID.",
  money_semantics_unsupported: "Есть денежные операции, для которых правила ещё не установлены.",
  "4_Transfers_unsupported": "Операции перевода требуют отдельной сверки.",
  "5_UFSR_unsupported": "В разделе UFSR есть неподдерживаемые данные.",
  immutable_trade_conflict: "Изменились исходные условия сделки: нужна сверка.",
  trade_material_conflict: "Повторная запись сделки содержит другие существенные данные.",
  pending_disappeared: "Нерассчитанная сделка исчезла без подтверждённого расчёта.",
  settled_to_pending_conflict: "Рассчитанная сделка снова отмечена как нерассчитанная.",
  document_coverage_conflict:
    "Те же байты отчёта уже сохранены с другим периодом или source account.",
  accepted_mapping_conflict: "Сохранённое сопоставление изменилось: нужна сверка.",
  accepted_class_coverage_requires_reconciliation:
    "Данные могут противоречить принятому подтверждению периода. Сначала нужна сверка этого подтверждения.",
  accepted_endpoint_quantity_conflict: "Количество бумаг расходится с принятым месячным срезом.",
  accepted_parser_version_conflict:
    "Документ уже сохранён другой версией разбора: загрузи отдельный отчёт за этот период.",
  endpoint_beginning_quantity_unavailable:
    "Нет начального количества позиции: endpoint-доказательства неполны.",
  endpoint_value_unavailable:
    "Нет начальной или конечной стоимости позиции: оценка не подтверждена.",
  rub_money_unavailable: "Строка RUB-остатка не наблюдалась: остаток неизвестен, а не ноль.",
  rub_money_incomplete: "В строке RUB-остатка отсутствует сумма начала или конца.",
  position_row_unclassified: "Есть строка позиции без подтверждённого типа: она не сохранена.",
  rub_money_ambiguous: "Найдено несколько строк RUB-остатка: однозначная сумма недоступна.",
};

export function MyBrokerImportPanel() {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<MyBrokerPreview | null>(null);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [instruments, setInstruments] = useState<Instrument[]>([]);
  const [choices, setChoices] = useState<Record<string, string>>({});
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  async function run(action: () => Promise<void>) {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError(null);
    setSuccess(null);
    setConfirmed(false);
    try {
      await action();
    } catch (cause) {
      setPreview(null);
      setError(formatApiError(cause));
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  async function inspect() {
    if (!file) return;
    const [result, accountList, instrumentList] = await Promise.all([
      previewMyBroker(file),
      listAccounts(),
      listInstruments(),
    ]);
    setPreview(result);
    setAccounts(accountList);
    setInstruments(instrumentList);
    setChoices({});
  }

  return (
    <Panel title="Брокерский XML MyBroker">
      <p>
        Загрузи отчёт и подтверди период из имени файла и сопоставления. Сохраняется история
        исходных данных; полнота портфеля и доходность пока остаются неподтверждёнными.
      </p>
      <Field htmlFor="mybroker-xml" label="XML MyBroker">
        <input
          id="mybroker-xml"
          type="file"
          accept=".xml,application/xml,text/xml"
          disabled={busy}
          onChange={(event) => {
            setFile(event.target.files?.[0] ?? null);
            setPreview(null);
            setConfirmed(false);
            setSuccess(null);
            setError(null);
          }}
        />
      </Field>
      <Button disabled={!file || busy} onClick={() => void run(inspect)}>
        Проверить XML
      </Button>
      {error && <p role="alert">Результат сохранения не подтверждён. {error}</p>}
      {success && <p role="status">{success}</p>}
      {preview && (
        <>
          <p>
            Период: {preview.document.covered_from} — {preview.document.covered_to}. Счёт из имени
            файла: {preview.document.filename_account}.
          </p>
          <p>
            Счета источника: {preview.document.source_accounts.join(", ")}. Семейство:{" "}
            {preview.document.provider}; разбор: {preview.document.parser}.
          </p>
          <details>
            <summary>Документ и состав разделов</summary>
            <p style={{ overflowWrap: "anywhere" }}>SHA-256: {preview.document.document_sha256}</p>
            <ul>
              {Object.entries(preview.document.section_inventory).map(([name, count]) => (
                <li key={name}>
                  {name}: {count} элементов
                </li>
              ))}
            </ul>
          </details>
          <p>
            Позиции: {preview.document.positions.length}, деньги RUB:{" "}
            {preview.document.rub_money?.length ?? 0}, сделки: {preview.document.trades.length},
            денежные строки: {preview.document.money.length}.
          </p>
          <Table>
            <thead>
              <tr>
                <Th>Счёт / ISIN</Th>
                <Th>ID сделки</Th>
                <Th>Дата / количество</Th>
                <Th>Цена / сумма</Th>
                <Th>Состояние</Th>
              </tr>
            </thead>
            <tbody>
              {preview.document.trades.map((trade) => (
                <tr key={`${trade.section}:${trade.ordinal}`}>
                  <Td>
                    {trade.core.source_account} / {trade.core.isin}
                  </Td>
                  <Td>{trade.ids.join(" + ") || "ID отсутствует"}</Td>
                  <Td>
                    {trade.core.trade_time} / {trade.core.quantity}
                  </Td>
                  <Td>
                    {trade.core.price} / {trade.core.trade_amount} {trade.core.currency}
                  </Td>
                  <Td>{trade.state === "pending" ? "Ожидает расчётов" : "Рассчитана"}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
          <Table>
            <thead>
              <tr>
                <Th>Позиция: счёт / ISIN</Th>
                <Th>Количество: начало / конец</Th>
                <Th>Стоимость: начало / конец</Th>
                <Th>Ожидается</Th>
              </tr>
            </thead>
            <tbody>
              {preview.document.positions.map((position) => (
                <tr key={position.ordinal}>
                  <Td>
                    {position.source_account} / {position.isin}
                  </Td>
                  <Td>
                    {position.beginning_actual_quantity ?? "—"} / {position.actual_quantity}
                  </Td>
                  <Td>
                    {position.beginning_value ?? "—"} / {position.ending_value ?? "—"}
                  </Td>
                  <Td>{position.forward_quantity}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
          {(preview.document.rub_money?.length ?? 0) > 0 && (
            <Table>
              <thead>
                <tr>
                  <Th>Деньги RUB: счёт</Th>
                  <Th>На начало</Th>
                  <Th>На конец</Th>
                </tr>
              </thead>
              <tbody>
                {preview.document.rub_money?.map((row) => (
                  <tr key={row.ordinal}>
                    <Td>{row.source_account}</Td>
                    <Td>{row.beginning_amount ?? "—"}</Td>
                    <Td>{row.ending_amount ?? "—"}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
          <Table>
            <thead>
              <tr>
                <Th>Денежная строка: счёт</Th>
                <Th>Связь</Th>
                <Th>Сумма источника</Th>
              </tr>
            </thead>
            <tbody>
              {preview.document.money.map((row) => (
                <tr key={row.ordinal}>
                  <Td>{row.source_account}</Td>
                  <Td>
                    {row.kind === "settlement"
                      ? "Расчёт по сделке"
                      : row.kind === "commission"
                        ? "Комиссия по сделке"
                        : "Требует сверки"}
                  </Td>
                  <Td>
                    {row.amount} {row.currency}
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
          <ul>
            {preview.mappings.map((mapping) => (
              <li key={`${mapping.kind}:${mapping.identity}`}>
                {mapping.kind === "account" ? "Счёт" : "Инструмент"} {mapping.identity} → Hermes #
                {mapping.hermes_id}
              </li>
            ))}
          </ul>
          {preview.missing_mappings.map((missing) => {
            const key = `${missing.kind}:${missing.identity}`;
            return (
              <div key={key}>
                <Field
                  htmlFor={`mybroker-${key}`}
                  label={`${missing.kind === "account" ? "Счёт" : "Инструмент"} ${missing.identity}`}
                >
                  <Select
                    id={`mybroker-${key}`}
                    disabled={busy}
                    value={choices[key] ?? ""}
                    onChange={(event) => setChoices({ ...choices, [key]: event.target.value })}
                  >
                    <option value="">Выбери явно</option>
                    {(missing.kind === "account" ? accounts : instruments).map((target) => (
                      <option key={target.id} value={target.id}>
                        {target.name}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Button
                  disabled={busy || !choices[key]}
                  onClick={() =>
                    void run(async () => {
                      await confirmBrokerIdentityMapping({
                        provider: "alfa_mybroker",
                        subject_kind: missing.kind,
                        provider_identity: missing.identity,
                        hermes_target_id: Number(choices[key]),
                        ...(missing.kind === "instrument"
                          ? { observed_isin: missing.identity }
                          : {}),
                      });
                      await inspect();
                    })
                  }
                >
                  Подтвердить сопоставление
                </Button>
              </div>
            );
          })}
          <ul>
            {[...preview.conflicts, ...preview.blockers].map((reason) => (
              <li key={reason}>{REASONS[reason] ?? "Есть данные, требующие отдельной сверки."}</li>
            ))}
          </ul>
          <label>
            <input
              type="checkbox"
              checked={confirmed}
              disabled={busy || !preview.can_apply}
              onChange={(event) => setConfirmed(event.target.checked)}
            />{" "}
            Подтверждаю период из имени файла и все показанные сопоставления для этого документа
          </label>
          <Button
            disabled={busy || !confirmed || !preview.can_apply}
            onClick={() =>
              void run(async () => {
                if (!file) return;
                const reviewed = preview;
                setPreview(null);
                const applied = await applyMyBroker(file, reviewed);
                const reread = await readMyBrokerImport(applied.import_id);
                verifyMyBrokerReadback(reviewed, applied, reread);
                setSuccess(
                  "Данные отчёта сохранены и подтверждены повторным чтением. Полнота финансового периода остаётся неизвестной.",
                );
              })
            }
          >
            Сохранить данные отчёта
          </Button>
        </>
      )}
    </Panel>
  );
}
