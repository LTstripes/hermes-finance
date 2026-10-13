import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";
import { listBrokerMonths, type BrokerMonthReadback } from "../api/brokerMonths";
import type { Account, ReportingMonth } from "../api/types";
import { Table, Td, Th } from "../components/ui";
import { formatDate, formatMoney, formatMonth } from "../lib/format";
import { isQueryReady, UiV2Notice } from "./UiV2StateBlocks";
import styles from "./CapitalDraftValuation.module.css";

const title = "Черновик / предварительная оценка, не закрытый месяц";

/** Original-bound source facts only; never assemble a new balance or return. */
function DraftSources({ month, accounts }: { month: ReportingMonth; accounts: Account[] }) {
  const [accountChoice, setAccountChoice] = useState<number | null>(null);
  const [sourceChoice, setSourceChoice] = useState<string | null>(null);
  const query = useQuery({
    queryKey: ["broker-months", month.id],
    queryFn: ({ signal }) => listBrokerMonths(month.id, signal),
    refetchOnWindowFocus: true,
  });
  const eligible = accounts.filter(
    (a) => a.status === "active" && ["brokerage", "iis"].includes(a.account_type),
  );
  const batches = isQueryReady(query)
    ? (query.data ?? []).filter(
        (b) =>
          b.contract_version === "broker_month_v1" &&
          b.status === "draft" &&
          b.reporting_month_id === month.id &&
          eligible.some((a) => a.id === b.account_id) &&
          b.accepted?.document?.provider === "mybroker",
      )
    : [];
  const accountId = accountChoice ?? batches[0]?.account_id;
  const account = eligible.find((a) => a.id === accountId);
  const sources = batches.filter((b) => b.account_id === accountId);
  const saved = sources.find((b) => b.request_id === (sourceChoice ?? sources[0]?.request_id));

  if (query.isError) {
    return (
      <UiV2Notice title="Не удалось проверить DRAFT" retry={() => void query.refetch()}>
        Предварительные оценки скрыты до актуального чтения исходной выписки.
      </UiV2Notice>
    );
  }
  // Cached, incompatible or inaccessible sources must not masquerade as a fresh preview.
  if (!batches.length) return null;

  return (
    <section className={styles.preview} aria-labelledby="capital-draft-heading">
      <p className={styles.badge}>DRAFT · только чтение</p>
      <h2 id="capital-draft-heading">{title}</h2>
      <p>
        Оценки брокера показаны отдельно. Капитал по последнему CLOSED остаётся основным; черновик
        не подтверждает доходность или готовность к закрытию.
      </p>
      <div className={styles.controls}>
        <label>
          Брокерский счёт черновика
          <select
            value={accountId}
            onChange={(event) => {
              setAccountChoice(Number(event.target.value));
              setSourceChoice(null);
            }}
          >
            {eligible.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </label>
        {sources.length > 1 ? (
          <label>
            Исходная выписка черновика
            <select
              value={saved?.request_id ?? ""}
              onChange={(event) => setSourceChoice(event.target.value)}
            >
              {sources.map((b) => (
                <option key={b.request_id} value={b.request_id}>
                  {b.request_id}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <button type="button" onClick={() => void query.refetch()}>
          Обновить DRAFT
        </button>
      </div>
      {account && saved ? (
        <>
          <p>
            {account.name} · {formatMonth(month.year, month.month)} ·{" "}
            {account.include_in_capital ? "Счёт включён в капитал." : "Счёт исключён из капитала."}{" "}
            {account.include_in_returns
              ? "Счёт включён в доходность."
              : "Счёт исключён из доходности."}
          </p>
          <DraftFacts saved={saved} />
        </>
      ) : (
        <p role="status">Для этого счёта нет совместимого DRAFT.</p>
      )}
    </section>
  );
}

function DraftFacts({ saved }: { saved: BrokerMonthReadback }) {
  const document = saved.accepted.document;
  if (!document) return null;
  const cash = document.rub_money?.filter((row) => row.currency === "RUB") ?? [];
  return (
    <div className={styles.facts}>
      <p role="status">
        {saved.bookkeeping_ready
          ? "Брокерский компонент требует общей проверки месяца."
          : "Черновик неполный; Close заблокирован."}{" "}
        Полнота покрытия: {saved.coverage_state ?? "unknown"}. Точная доходность не подтверждена.
      </p>
      <p>
        MyBroker · {formatDate(document.covered_from)} — {formatDate(document.covered_to)}.
        Начальная оценка относится к предыдущему дню, конечная — к последнему дню отчёта.
      </p>
      <Table>
        <caption>Позиции DRAFT по исходной выписке · RUB</caption>
        <thead>
          <tr>
            <Th>Исходный счёт / ISIN</Th>
            <Th numeric>Количество в конце</Th>
            <Th numeric>Начальная оценка</Th>
            <Th numeric>Конечная оценка</Th>
          </tr>
        </thead>
        <tbody>
          {document.positions.map((row) => (
            <tr key={`${row.source_account}:${row.ordinal}`}>
              <Td>
                {row.source_account} / {row.isin}
              </Td>
              <Td numeric>{row.actual_quantity}</Td>
              <Td numeric>{formatMoney(row.beginning_value, { empty: "Неизвестно" })}</Td>
              <Td numeric>{formatMoney(row.ending_value, { empty: "Неизвестно" })}</Td>
            </tr>
          ))}
        </tbody>
      </Table>
      {!document.positions.length ? (
        <p>В выписке нет строк позиций; это не доказательство нулевой оценки.</p>
      ) : null}
      <Table>
        <caption>Отдельный RUB cash DRAFT</caption>
        <thead>
          <tr>
            <Th>Исходный счёт</Th>
            <Th numeric>В начале</Th>
            <Th numeric>В конце</Th>
          </tr>
        </thead>
        <tbody>
          {cash.map((row) => (
            <tr key={`${row.source_account}:${row.ordinal}`}>
              <Td>{row.source_account}</Td>
              <Td numeric>{formatMoney(row.beginning_amount, { empty: "Неизвестно" })}</Td>
              <Td numeric>{formatMoney(row.ending_amount, { empty: "Неизвестно" })}</Td>
            </tr>
          ))}
        </tbody>
      </Table>
      {!cash.length ? <p>RUB cash неизвестен.</p> : null}
      {saved.exceptions.length ? (
        <ul aria-label="Предупреждения источника DRAFT">
          {saved.exceptions.map((code) => (
            <li key={code}>{code}</li>
          ))}
        </ul>
      ) : null}
      <p>Налоги, себестоимость и учёт НКД в оценке не подтверждены.</p>
      <div className={styles.controls}>
        <Link to={`/v2/close?month=${saved.reporting_month_id}&step=final_review_close`}>
          Источник и предупреждения месяца →
        </Link>
        <button type="button" disabled>
          Закрыть месяц
        </button>
      </div>
      <p>
        Закрытие выполняется только после общей проверки месяца; этот просмотр доступен только для
        чтения.
      </p>
      <details>
        <summary>Происхождение оценки</summary>
        <p>
          Источник: {saved.request_id} · import #{saved.import_id} · {document.parser}
        </p>
        <p>Оригинал SHA-256: {document.document_sha256}</p>
        <p>Source digest: {saved.accepted.source_digest}</p>
      </details>
    </div>
  );
}

export function CapitalDraftValuation({
  months,
  accounts,
}: {
  months: ReportingMonth[];
  accounts: Account[];
}) {
  const drafts = months.filter((month) => month.status === "draft");
  const [choice, setChoice] = useState<number | null>(null);
  const month = drafts.find((m) => m.id === choice) ?? drafts[0];
  if (!month || !accounts.length) return null;
  return (
    <div className={styles.container}>
      {drafts.length > 1 ? (
        <label className={styles.monthChoice}>
          Месяц DRAFT
          <select value={month.id} onChange={(event) => setChoice(Number(event.target.value))}>
            {drafts.map((m) => (
              <option key={m.id} value={m.id}>
                {formatMonth(m.year, m.month)}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      <DraftSources key={month.id} month={month} accounts={accounts} />
    </div>
  );
}
