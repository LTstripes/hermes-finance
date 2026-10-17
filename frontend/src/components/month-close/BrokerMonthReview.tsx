import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { listAccounts } from "../../api/accounts";
import { formatApiError } from "../../api/client";
import {
  listBrokerMonths,
  previewBrokerMonth,
  type BrokerMonthPreview,
  type BrokerMonthReadback,
} from "../../api/brokerMonths";
import type { MyBrokerDocument } from "../../api/mybrokerImport";
import { getMonth } from "../../api/months";
import { previewOriginalContext } from "../../api/mybrokerPreflight";
import { formatDate, formatMoney } from "../../lib/format";
import { queryKeys } from "../../queryClient";
import { Button, Panel, Table, Td, Th } from "../ui";
import styles from "./BrokerMonthReview.module.css";
import { BrokerMonthSummary, sourceTotal } from "./BrokerMonthSummary";
import { BrokerMoneyReview } from "./BrokerMoneyReview";
import { useBrokerOriginalSession } from "./brokerOriginalSession";

function SourceInventory({ document }: { document: MyBrokerDocument }) {
  return (
    <div className={styles.stack}>
      <p>
        MyBroker · {formatDate(document.covered_from)} — {formatDate(document.covered_to)}.
        Начальная оценка относится к предыдущему дню, конечная — к последнему дню отчёта.
      </p>
      <p>
        Общая оценка источника, включая отдельный RUB cash:{" "}
        {formatMoney(sourceTotal(document, "beginning"))} →{" "}
        {formatMoney(sourceTotal(document, "ending"))}. Это оценки брокера; полнота движений
        проверяется отдельно.
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

function AccountAliases({ preview }: { preview: BrokerMonthPreview }) {
  return (
    <Table aria-label="Привязки исходных счетов">
      <thead>
        <tr>
          <Th>Точный alias</Th>
          <Th>Происхождение</Th>
          <Th>Счёт Hermes</Th>
          <Th>Привязка</Th>
        </tr>
      </thead>
      <tbody>
        {preview.account_aliases.map((alias) => (
          <tr key={alias.identity}>
            <Td>{alias.identity}</Td>
            <Td>{alias.origins.join(", ")}</Td>
            <Td>
              {alias.target_name ?? "Неизвестен"} (#{alias.hermes_id})
            </Td>
            <Td>{alias.action === "reuse" ? "Существующая" : "Новая — требует подтверждения"}</Td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

export function BrokerMonthReview({ monthId, closed }: { monthId: number; closed: boolean }) {
  const queryClient = useQueryClient();
  const { session, original } = useBrokerOriginalSession();
  const { file, accountId } = original;
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
  const [preview, setPreview] = useState<BrokerMonthPreview | null>(null);
  const [previewEpoch, setPreviewEpoch] = useState<number | null>(null);
  const readback = original.confirmed;
  const confirmedRequestId = readback?.request_id;
  const [bindingsReviewed, setBindingsReviewed] = useState(false);
  const [checking, setBusy] = useState(false);
  const busy = checking || original.busy;
  const [error, setError] = useState<string | null>(null);
  const request = useRef<string | null>(null);
  const generation = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const invalidateReview = useCallback(() => {
    generation.current++;
    controller.current?.abort();
    setBusy(false);
    setPreview(null);
    setBindingsReviewed(false);
    setError(null);
    setNotice(null);
    request.current = null;
  }, []);
  // A context transition invalidates even A→B→A responses and consents.
  useLayoutEffect(() => {
    invalidateReview();
    session.context(monthId, closed);
    return () => {
      generation.current++;
      controller.current?.abort();
    };
  }, [monthId, closed, session, invalidateReview]);
  useEffect(
    () =>
      queryClient.getQueryCache().subscribe((event) => {
        const key = String(event.query.queryKey[0]);
        if (
          event.type === "updated" &&
          (event.action.type === "invalidate" ||
            (event.action.type === "success" &&
              (event.action.manual || event.query.state.dataUpdateCount > 1))) &&
          [
            "accounts",
            "instruments",
            "broker-identity-mappings",
            "months",
            "month-close-workflow",
          ].includes(key)
        ) {
          invalidateReview();
        }
      }),
    [queryClient, invalidateReview],
  );

  async function inspect(original = file, selected = accountId) {
    if (!original || closed || session.snapshot().pending) return;
    invalidateReview();
    const version = generation.current;
    const epoch = session.snapshot().epoch;
    const abort = new AbortController();
    controller.current = abort;
    const current = () =>
      generation.current === version && session.snapshot().epoch === epoch && !abort.signal.aborted;
    setBusy(true);
    try {
      let target = selected;
      if (!target) {
        const [context, month, available] = await Promise.all([
          previewOriginalContext(original, abort.signal),
          getMonth(monthId, abort.signal),
          listAccounts(abort.signal),
        ]);
        if (!current()) return;
        const end =
          Number.isInteger(month.year) &&
          Number.isInteger(month.month) &&
          month.month >= 1 &&
          month.month <= 12
            ? new Date(Date.UTC(month.year, month.month, 0)).toISOString().slice(0, 10)
            : "";
        if (
          month.id !== monthId ||
          month.status !== "draft" ||
          !end ||
          month.snapshot_date !== end ||
          context.coveredFrom !== `${end.slice(0, 7)}-01` ||
          context.coveredTo !== end
        ) {
          setNotice(
            "Период XML не совпадает с открытым DRAFT и его снимком. Открой соответствующий месяц или выбери полный XML этого месяца; месяц автоматически не меняется.",
          );
          return;
        }
        if (!Array.isArray(available)) throw new Error("Список счетов не подтверждён.");
        const matches = available.filter(
          (a) =>
            a.id === context.accountId &&
            a.status === "active" &&
            ["brokerage", "iis"].includes(a.account_type),
        );
        if (!context.accountId || matches.length !== 1) {
          setNotice(
            "Точная привязка оригинала не подтверждена. Выбери счёт вручную; новые aliases потребуют отдельного подтверждения.",
          );
          return;
        }
        target = String(context.accountId);
        session.identify(target);
      }
      const result = await previewBrokerMonth(
        original,
        {
          reporting_month_id: monthId,
          account_id: Number(target),
        },
        abort.signal,
      );
      if (!current()) return;
      if (
        result.contract_version !== "broker_month_v1" ||
        result.reporting_month_id !== monthId ||
        result.account_id !== Number(target)
      )
        throw new Error("Получен Preview другого счёта или месяца.");
      setPreviewEpoch(session.snapshot().epoch);
      setPreview(result);
      request.current = crypto.randomUUID();
    } catch (e) {
      if (current()) {
        setError(formatApiError(e));
        setNotice("Выбери счёт вручную для обычного Preview или повтори проверку оригинала.");
      }
    } finally {
      if (current()) setBusy(false);
    }
  }
  async function apply() {
    if (
      !file ||
      !preview?.can_apply ||
      busy ||
      closed ||
      !request.current ||
      previewEpoch !== session.snapshot().epoch
    )
      return;
    if (preview.account_bindings.length && !bindingsReviewed) return;
    setBindingsReviewed(false);
    setPreview(null);
    await session.start(preview, request.current);
  }
  const currentBatches = batches.data ?? [];
  const saved = Array.from(
    [
      ...(readback && !currentBatches.some((batch) => batch.request_id === readback.request_id)
        ? [readback]
        : []),
      ...currentBatches,
    ]
      .reduce((accounts, batch) => {
        const prior = accounts.get(batch.account_id);
        accounts.set(batch.account_id, {
          ...batch,
          bookkeeping_ready: batch.bookkeeping_ready && (prior?.bookkeeping_ready ?? true),
          exceptions: [...new Set([...(prior?.exceptions ?? []), ...batch.exceptions])],
        });
        return accounts;
      }, new Map<number, BrokerMonthReadback>())
      .values(),
  );
  return (
    <Panel title="Месяц из MyBroker" label="Исходный отчёт">
      <div className={styles.stack}>
        <p>
          Выбери оригинальный XML: для известного счёта и точного месяца Preview появится
          автоматически. Проверь сводку и явно сохрани source-DRAFT. После независимого чтения
          используй общую итоговую проверку и закрытие месяца.
        </p>
        <p>
          Полнота всего портфеля этим отчётом не подтверждается. Неразобранные движения остаются
          видимыми.
        </p>
        {!closed ? (
          <>
            <label className={styles.field}>
              Оригинальный XML MyBroker{" "}
              <input
                aria-label="Оригинальный XML MyBroker"
                type="file"
                accept=".xml"
                key={monthId}
                onChange={(e) => {
                  const original = e.target.files?.[0] ?? null;
                  session.select(original, monthId, "");
                  invalidateReview();
                  if (original) void inspect(original, "");
                }}
              />
            </label>
            <label className={styles.field}>
              Брокерский счёт{" "}
              <select
                aria-label="Брокерский счёт"
                value={accountId}
                onChange={(e) => {
                  const target = e.target.value;
                  session.select(file, monthId, target);
                  invalidateReview();
                  if (file && target) void inspect(file, target);
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
            <Button
              type="button"
              onClick={() => void inspect()}
              disabled={!file || busy || original.pending != null}
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
        {file ? <p>Оригинал в текущем сеансе: {file.name}</p> : null}
        {error || original.error ? <p role="alert">{error ?? original.error}</p> : null}
        {original.pending && !closed ? (
          <div className={styles.stack}>
            <p role="status">
              {original.pending.committed
                ? "Сохранение подтверждено сервером, независимое чтение не завершено — повторить чтение"
                : "Ответ сохранения не подтверждён. Сначала проверь результат по исходному запросу."}
            </p>
            <Button type="button" disabled={busy} onClick={() => void session.retryRead()}>
              Повторить чтение
            </Button>
            {!original.pending.committed && original.pending.replayAllowed && !busy ? (
              <Button type="button" onClick={() => void session.post()}>
                Повторить сохранение с прежним запросом
              </Button>
            ) : null}
          </div>
        ) : null}
        {notice ? <p role="status">{notice}</p> : null}
        {preview && previewEpoch === original.epoch && !closed && !original.pending ? (
          <>
            <BrokerMonthSummary preview={preview} filename={file?.name ?? "Имя файла неизвестно"} />
            {preview.account_bindings.length ? (
              <>
                <AccountAliases preview={preview} />
                <label className={styles.review}>
                  <input
                    type="checkbox"
                    checked={bindingsReviewed}
                    disabled={busy || !preview.can_apply}
                    onChange={(e) => setBindingsReviewed(e.target.checked)}
                  />{" "}
                  Я подтверждаю, что все новые aliases в таблице относятся к указанному счёту
                  Hermes.
                </label>
              </>
            ) : null}
            <p>
              Кнопка сохраняет только показанные факты источника в DRAFT. Она не подтверждает Money,
              комиссии, НКД, Close или точную доходность.
            </p>
            <Button
              type="button"
              onClick={() => void apply()}
              disabled={
                busy ||
                !preview.can_apply ||
                (preview.account_bindings.length > 0 && !bindingsReviewed)
              }
            >
              {preview.bookkeeping_ready
                ? "Подтвердить сводку и сохранить source-DRAFT"
                : "Подтвердить сводку и сохранить неполный source-DRAFT"}
            </Button>
            <details>
              <summary>Полный состав источника и привязки</summary>
              <div className={styles.stack}>
                {!preview.account_bindings.length ? <AccountAliases preview={preview} /> : null}
                <SourceInventory document={preview.document} />
              </div>
            </details>
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
              <BrokerMoneyReview
                key={`${previous.request_id}:${original.epoch}`}
                baseRequestId={previous.request_id}
                monthId={monthId}
                accountId={previous.account_id}
                importId={previous.import_id}
                closed={closed}
                stored={previous.money_acceptance}
                originalFile={!closed ? session.candidate(previous) : undefined}
                sessionEpoch={original.epoch}
              />
            </div>
          ))
        ) : null}
      </div>
    </Panel>
  );
}
