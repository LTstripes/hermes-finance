import { reasonCopy } from "../lib/reasonCopy";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { listAccounts } from "../api/accounts";
import {
  formatStatementPercent,
  getStatementReturn,
  listStatementSources,
  statementExportHref,
  statementMoney,
} from "../api/brokerStatementReturn";
import { formatApiError } from "../api/client";
import { formatDate } from "../lib/format";
import styles from "./BrokerStatementReturnDiagnostics.module.css";
import { BrokerStatementWhatIfPanel } from "./BrokerStatementWhatIfPanel";

export default function BrokerStatementReturnDiagnostics({
  accountId,
}: {
  accountId?: number;
} = {}) {
  const [account, setAccount] = useState(accountId === undefined ? "" : String(accountId));
  const [request, setRequest] = useState("");
  const accounts = useQuery({
    queryKey: ["statement-return-accounts"],
    queryFn: ({ signal }) => listAccounts(signal),
  });
  const sources = useQuery({
    queryKey: ["statement-return-sources", account],
    enabled: Boolean(account),
    queryFn: ({ signal }) => listStatementSources(Number(account), signal),
    staleTime: 5 * 60 * 1000,
  });
  const selected = sources.data?.find(
    (s) => s.account_id === Number(account) && s.request_id === request,
  );
  const result = useQuery({
    queryKey: ["statement-return", account, request],
    enabled: Boolean(selected),
    queryFn: ({ signal }) => getStatementReturn(Number(account), request, signal),
    staleTime: 5 * 60 * 1000,
    retry: false,
  });
  const candidate = result.data;
  const matches =
    candidate &&
    selected &&
    candidate.account_id === selected.account_id &&
    candidate.t0 === selected.t0 &&
    candidate.t1 === selected.t1 &&
    candidate.sources[0]?.request_id === request &&
    candidate.method === "broker_statement_mwr_period_v1" &&
    candidate.currency === "RUB" &&
    candidate.annualized === false &&
    candidate.opening.account_id === selected.account_id &&
    candidate.closing.account_id === selected.account_id;
  const data = matches && !result.isFetching && !result.isError ? candidate : null;
  const error = accounts.error ?? sources.error ?? result.error;
  return (
    <section aria-label="Доходность по отдельной выписке">
      <h2>Доходность по отдельной выписке</h2>
      <div className={styles.content}>
        <p>
          Предварительная доходность выбранного счёта по оценкам брокера и подтверждённым движениям
          за фактический период.
        </p>
        <div className={styles.controls}>
          <label>
            Брокерский счёт
            <select
              aria-label="Брокерский счёт"
              value={account}
              onChange={(e) => {
                setAccount(e.target.value);
                setRequest("");
              }}
            >
              <option value="">Выбери счёт</option>
              {accounts.data
                ?.filter((a) => a.account_type === "brokerage" || a.account_type === "iis")
                .map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
            </select>
          </label>
          <label>
            Принятая выписка
            <select
              aria-label="Принятая выписка"
              value={request}
              disabled={!account || sources.isFetching}
              onChange={(e) => setRequest(e.target.value)}
            >
              <option value="">Выбери период</option>
              {sources.data
                ?.filter((s) => s.account_id === Number(account))
                .map((s) => (
                  <option key={s.request_id} value={s.request_id}>
                    {formatDate(s.t0)} — {formatDate(s.t1)} · {s.request_id}
                  </option>
                ))}
            </select>
          </label>
          <button
            type="button"
            disabled={!selected || result.isFetching}
            onClick={() => void result.refetch()}
          >
            Обновить результат
          </button>
        </div>
        {error && <p role="alert">{formatApiError(error)}</p>}
        {account && !sources.isFetching && sources.data?.length === 0 && (
          <p>Для этого счёта нет принятой выписки с оценками.</p>
        )}
        {result.isFetching && <p role="status">Проверяем актуальные основания…</p>}
        {candidate && selected && !matches && (
          <p role="alert">Ответ не соответствует выбранному счёту или периоду.</p>
        )}
        {data && (
          <section className={styles.result} aria-label="Результат по выписке">
            <h2>Предварительная доходность за период</h2>
            <p className={styles.rate}>
              {data.status === "indicative" && data.quality === "indicative"
                ? formatStatementPercent(data.rate_fraction)
                : "Недоступна"}
            </p>
            <p>
              Счёт: {accounts.data?.find((a) => a.id === data.account_id)?.name} ·{" "}
              {formatDate(data.t0)} — {formatDate(data.t1)} · RUB · EOD
            </p>
            {data.warnings.map((w) => (
              <p key={w}>{w}</p>
            ))}
            {data.reason_codes.length > 0 && (
              <ul aria-label="Причины недоступности">
                {data.reason_codes.map((r) => (
                  <li key={r}>{reasonCopy(r, { surface: "brokerReturn" }).message}</li>
                ))}
              </ul>
            )}
            <table>
              <caption>Оценки брокера и отдельный cash</caption>
              <thead>
                <tr>
                  <th>Компонент</th>
                  <th>{formatDate(data.t0)} · EOD</th>
                  <th>{formatDate(data.t1)} · EOD</th>
                </tr>
              </thead>
              <tbody>
                {(["positions_value_kopecks", "cash_kopecks", "total_value_kopecks"] as const).map(
                  (key, i) => (
                    <tr key={key}>
                      <th>{["Позиции", "RUB cash", "Всего"][i]}</th>
                      <td>{statementMoney(data.opening[key])}</td>
                      <td>{statementMoney(data.closing[key])}</td>
                    </tr>
                  ),
                )}
              </tbody>
            </table>
            <h2>Подтверждённые пересечения границы счёта</h2>
            <p>
              Плюс — в счёт, минус — из счёта. Купоны, комиссии и расчёты внутри счёта уже отражены
              в cash.
            </p>
            {data.crossings.length > 0 ? (
              <ul>
                {data.crossings.map((c) => (
                  <li key={c.event_id}>
                    {formatDate(c.event_date)}: {c.signed_amount_kopecks.startsWith("-") ? "" : "+"}
                    {statementMoney(c.signed_amount_kopecks)}
                  </li>
                ))}
              </ul>
            ) : (
              <p>
                {data.cash_coverage_state === "complete"
                  ? "Подтверждено отсутствие пересечений за период."
                  : "Полнота движений не подтверждена; пустой список не означает нулевые движения."}
              </p>
            )}
            <a href={statementExportHref(data)} download>
              Экспорт результата и оснований JSON
            </a>
            <details>
              <summary>Источники и актуальность</summary>
              {!!data.reason_codes.length && <code>{data.reason_codes.join(", ")}</code>}
              {data.sources.map((s) => (
                <p key={s.import_id}>
                  Источник {s.import_id}: {s.document_sha256}
                </p>
              ))}
              <p>Основания: {data.material_fingerprint}</p>
              <p>
                Охват cash: {data.cash_coverage_state}; НКД: {data.bond_nkd_basis}.
              </p>
            </details>
          </section>
        )}
        {data && (
          <BrokerStatementWhatIfPanel
            key={`${data.account_id}:${request}:${data.material_fingerprint}`}
            actual={data}
          />
        )}
      </div>
    </section>
  );
}
