import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { listAccounts } from "../../api/accounts";
import { formatApiError } from "../../api/client";
import {
  applyBrokerMonth,
  listBrokerMonths,
  previewBrokerMonth,
  readBrokerMonth,
  type BrokerMonthPreview,
  type BrokerMonthReadback,
} from "../../api/brokerMonths";
import type { MyBrokerDocument } from "../../api/mybrokerImport";
import { formatDate, formatMoney } from "../../lib/format";
import { sumMoneyAmounts } from "../../lib/money";
import { queryKeys } from "../../queryClient";
import { Button, Panel, Table, Td, Th } from "../ui";
import styles from "./BrokerMonthReview.module.css";

function SourceInventory({ document }: { document: MyBrokerDocument }) {
  const total = (side: "beginning" | "ending") => {
    const values = document.positions.map((p) =>
      side === "beginning" ? p.beginning_value : p.ending_value,
    );
    values.push(
      document.rub_money?.length === 1
        ? side === "beginning"
          ? document.rub_money[0].beginning_amount
          : document.rub_money[0].ending_amount
        : null,
    );
    return values.every((v): v is string => typeof v === "string") ? sumMoneyAmounts(values) : null;
  };
  return (
    <div className={styles.stack}>
      <p>
        MyBroker · {formatDate(document.covered_from)} — {formatDate(document.covered_to)}.
        Начальная оценка относится к предыдущему дню, конечная — к последнему дню отчёта.
      </p>
      <p>
        Общая оценка источника, включая отдельный RUB cash: {formatMoney(total("beginning"))} →{" "}
        {formatMoney(total("ending"))}. Это оценки брокера; полнота движений проверяется отдельно.
      </p>
      <Table>
        <caption>Позиции по исходному отчёту</caption>
        <thead>
          <tr>
            <Th>ISIN</Th>
            <Th numeric>Количество в начале</Th>
            <Th numeric>Количество в конце</Th>
            <Th numeric>Начальная оценка</Th>
            <Th numeric>Конечная оценка</Th>
          </tr>
        </thead>
        <tbody>
          {document.positions.map((p) => (
            <tr key={`${p.source_account}:${p.ordinal}`}>
              <Td>{p.isin}</Td>
              <Td numeric>{p.beginning_actual_quantity ?? "Неизвестно"}</Td>
              <Td numeric>{p.actual_quantity}</Td>
              <Td numeric>{formatMoney(p.beginning_value ?? null)}</Td>
              <Td numeric>{formatMoney(p.ending_value ?? null)}</Td>
            </tr>
          ))}
        </tbody>
      </Table>
      <p>
        Отдельный RUB cash: {formatMoney(document.rub_money?.[0]?.beginning_amount ?? null)} →{" "}
        {formatMoney(document.rub_money?.[0]?.ending_amount ?? null)}. Денежные проводки повторно в
        cash не добавляются.
      </p>
      <p>
        Сделки: {document.trades.length}. Денежные строки: {document.money.length}. Себестоимость,
        налоги и НКД облигаций остаются неизвестными; точная доходность не подтверждена.
      </p>
      <details>
        <summary>Все денежные строки и секции источника</summary>
        <Table>
          <caption>
            Money: полный состав, без автоматической классификации неизвестных строк
          </caption>
          <thead>
            <tr>
              <Th>Дата</Th>
              <Th>Строка</Th>
              <Th>Роль</Th>
              <Th numeric>Сумма</Th>
            </tr>
          </thead>
          <tbody>
            {document.money.map((m, index) => (
              <tr key={`${m.source_account}:${m.ordinal}`}>
                <Td>{m.date ? formatDate(m.date) : "Неизвестно"}</Td>
                <Td>{index + 1}</Td>
                <Td>
                  {m.kind === "unsupported"
                    ? "Не разобрано — требуется доказательство"
                    : m.kind === "settlement"
                      ? "Расчёты по сделке"
                      : "Комиссия по сделке"}
                </Td>
                <Td numeric>
                  {m.currency === "RUB" ? formatMoney(m.amount) : `${m.amount} ${m.currency}`}
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
        <ul>
          {Object.entries(document.section_inventory).map(([section, count]) => (
            <li key={section}>
              {section}: {count}
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}

function Exceptions({ codes }: { codes: string[] }) {
  if (!codes.length) return null;
  return (
    <div role="alert" className={styles.exceptions}>
      <p>
        Черновик неполный. Есть неразобранные движения или изменённые доказательства. Закрытие
        покрытого брокерского счёта заблокировано.
      </p>
      <details>
        <summary>Причины и недостающие доказательства</summary>
        <ul>
          {codes.map((code) => (
            <li key={code}>{code}</li>
          ))}
        </ul>
      </details>
    </div>
  );
}

export function BrokerMonthReview({ monthId, closed }: { monthId: number; closed: boolean }) {
  const queryClient = useQueryClient();
  const accounts = useQuery({
    queryKey: queryKeys.accounts,
    queryFn: async ({ signal }) => {
      const result = await listAccounts(signal);
      if (!Array.isArray(result)) throw new Error("Список счетов не подтверждён.");
      return result;
    },
  });
  const batches = useQuery({
    queryKey: ["broker-months", monthId],
    queryFn: async ({ signal }) => {
      const result = await listBrokerMonths(monthId, signal);
      if (
        !Array.isArray(result) ||
        result.some(
          (batch) =>
            batch.contract_version !== "broker_month_v1" || batch.reporting_month_id !== monthId,
        )
      )
        throw new Error("Сохранённые источники месяца не подтверждены.");
      return result;
    },
  });
  const [accountId, setAccountId] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<BrokerMonthPreview | null>(null);
  const [readback, setReadback] = useState<BrokerMonthReadback | null>(null);
  const [confirmedRequestId, setConfirmedRequestId] = useState<string | null>(
    () => queryClient.getQueryData<string>(["broker-month-confirmed", monthId]) ?? null,
  );
  const [reviewed, setReviewed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const request = useRef<string | null>(null);
  const active = useRef(true);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);

  function invalidateReview() {
    setPreview(null);
    setReadback(null);
    setReviewed(false);
    setError(null);
    request.current = null;
  }
  async function inspect() {
    if (!file || !accountId || busy || closed) return;
    setBusy(true);
    setError(null);
    setReadback(null);
    setPreview(null);
    request.current = null;
    setReviewed(false);
    try {
      const result = await previewBrokerMonth(file, {
        reporting_month_id: monthId,
        account_id: Number(accountId),
      });
      if (!active.current) return;
      if (
        result.contract_version !== "broker_month_v1" ||
        result.reporting_month_id !== monthId ||
        result.account_id !== Number(accountId)
      )
        throw new Error("Получен Preview другого счёта или месяца.");
      setPreview(result);
      request.current = crypto.randomUUID();
    } catch (e) {
      if (active.current) setError(formatApiError(e));
    } finally {
      if (active.current) setBusy(false);
    }
  }
  async function apply() {
    if (!file || !preview?.can_apply || !reviewed || busy || closed || !request.current) return;
    setBusy(true);
    setError(null);
    try {
      const intent = { reporting_month_id: monthId, account_id: Number(accountId) };
      const committed = await applyBrokerMonth(
        file,
        intent,
        preview.confirmation_digest,
        request.current,
      );
      const persisted = await readBrokerMonth(request.current);
      if (!active.current) return;
      if (
        persisted.contract_version !== "broker_month_v1" ||
        persisted.request_id !== request.current ||
        persisted.reporting_month_id !== monthId ||
        persisted.account_id !== intent.account_id ||
        persisted.confirmation_digest !== preview.confirmation_digest ||
        JSON.stringify(committed.accepted) !== JSON.stringify(persisted.accepted)
      )
        throw new Error(
          "Независимое чтение не подтвердило сохранённый результат. Обнови состояние.",
        );
      setReadback(persisted);
      setConfirmedRequestId(persisted.request_id);
      // Parent workflow refresh may temporarily unmount this panel. Retain
      // only the proven request marker, never a cached financial readiness.
      queryClient.setQueryData(["broker-month-confirmed", monthId], persisted.request_id);
      setPreview(null);
      setReviewed(false);
      await queryClient.invalidateQueries();
    } catch (e) {
      if (active.current) setError(formatApiError(e));
    } finally {
      if (active.current) setBusy(false);
    }
  }
  const saved = Array.from(
    new Map(
      [
        ...(batches.data ?? []),
        ...(readback
          ? [batches.data?.find((batch) => batch.request_id === readback.request_id) ?? readback]
          : []),
      ].map((batch) => [batch.account_id, batch]),
    ).values(),
  );
  return (
    <Panel title="Месяц из MyBroker" label="Исходный отчёт">
      <div className={styles.stack}>
        <p>
          Один оригинальный XML → проверка всего счёта → черновик. После независимого чтения
          используй общую итоговую проверку и закрытие месяца.
        </p>
        <p>
          Полнота всего портфеля этим отчётом не подтверждается. Неразобранные движения остаются
          видимыми.
        </p>
        {!closed ? (
          <>
            <label className={styles.field}>
              Брокерский счёт{" "}
              <select
                aria-label="Брокерский счёт"
                value={accountId}
                disabled={busy}
                onChange={(e) => {
                  setAccountId(e.target.value);
                  invalidateReview();
                }}
              >
                <option value="">Выбери счёт</option>
                {accounts.data
                  ?.filter(
                    (a) => a.status === "active" && ["brokerage", "iis"].includes(a.account_type),
                  )
                  .map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
              </select>
            </label>
            <label className={styles.field}>
              Оригинальный XML MyBroker{" "}
              <input
                aria-label="Оригинальный XML MyBroker"
                type="file"
                accept=".xml"
                disabled={busy}
                onChange={(e) => {
                  setFile(e.target.files?.[0] ?? null);
                  invalidateReview();
                }}
              />
            </label>
            <Button
              type="button"
              onClick={() => void inspect()}
              disabled={!file || !accountId || busy}
            >
              {busy ? "Проверяем…" : "Проверить MyBroker"}
            </Button>
          </>
        ) : (
          <p>Месяц закрыт. Доступно чтение сохранённого источника; импорт его не изменяет.</p>
        )}
        {accounts.error || batches.error ? (
          <p role="alert">
            Не удалось обновить состояние источников:{" "}
            {formatApiError(accounts.error ?? batches.error)}
          </p>
        ) : null}
        {error ? <p role="alert">{error}</p> : null}
        {preview ? (
          <>
            <SourceInventory document={preview.document} />
            <Exceptions codes={preview.exceptions} />
            {preview.conflicts.length ? (
              <div role="alert">
                <p>
                  Черновик нельзя сформировать: требуется разрешить конфликт источника или
                  идентичности.
                </p>
                <ul>
                  {preview.conflicts.map((c) => (
                    <li key={c}>{c}</li>
                  ))}
                </ul>
              </div>
            ) : null}
            <label className={styles.review}>
              <input
                type="checkbox"
                checked={reviewed}
                disabled={busy || !preview.can_apply}
                onChange={(e) => setReviewed(e.target.checked)}
              />{" "}
              Я проверил весь счёт и видимую неполноту черновика.
            </label>
            <Button
              type="button"
              onClick={() => void apply()}
              disabled={busy || !preview.can_apply || !reviewed}
            >
              {preview.bookkeeping_ready
                ? "Сформировать черновик"
                : "Сформировать неполный черновик"}
            </Button>
          </>
        ) : saved.length ? (
          saved.map((previous) => (
            <div key={previous.account_id} className={styles.stack}>
              <p role="status">
                Счёт #{previous.account_id}.{" "}
                {confirmedRequestId === previous.request_id
                  ? "Сохранённый результат подтверждён независимым чтением."
                  : "Сохранённый источник месяца."}{" "}
                {previous.bookkeeping_ready
                  ? "Брокерский компонент готов к общей проверке."
                  : "Черновик неполный; Close заблокирован."}
              </p>
              {previous.accepted.document ? (
                <SourceInventory document={previous.accepted.document} />
              ) : (
                <p role="alert">
                  Исходные доказательства изменены. Сохранённая оценка не подтверждена.
                </p>
              )}
              <Exceptions codes={previous.exceptions} />
            </div>
          ))
        ) : null}
      </div>
    </Panel>
  );
}
