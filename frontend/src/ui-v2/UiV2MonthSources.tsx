import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router";
import { formatApiError } from "../api/client";
import { listSourceIntakes, type SourceIntake } from "../api/sourceIntake";
import type { ReportingMonth } from "../api/types";
import { SourceIntakeUpload } from "../components/month-close/SourceIntakeUpload";
import { formatDate } from "../lib/format";
import { brokerSourceTitle } from "../lib/ownerCopy";
import { UiV2Panel } from "./UiV2Panel";
import { UiV2MonthInstruments } from "./UiV2MonthInstruments";
import { UiV2Loading, UiV2Notice } from "./UiV2StateBlocks";
import styles from "./UiV2MonthWorkspace.module.css";

function sourceAccounts(intake: SourceIntake): string[] {
  return [
    ...new Set([intake.document.filename_account, ...(intake.document.source_accounts ?? [])]),
  ].filter((value) => typeof value === "string" && value.trim().length > 0);
}

export function UiV2MonthSources({
  month,
  onReview,
}: {
  month: Pick<ReportingMonth, "id" | "year" | "month" | "status">;
  onReview: (id: number) => void;
}) {
  const [params, setParams] = useSearchParams();
  const list = useQuery({
    queryKey: ["source-intakes", month.id],
    queryFn: ({ signal }) => listSourceIntakes(month.id, signal),
    refetchOnWindowFocus: true,
  });
  const period = `${month.year}-${String(month.month).padStart(2, "0")}`;
  // A journal can be unbound. Calendar overlap is a display filter, never financial binding.
  const sources = (list.data ?? []).filter(
    (item) =>
      item.state.reporting_month_id === month.id ||
      (item.state.reporting_month_id === null &&
        item.covered_from.slice(0, 7) <= period &&
        item.covered_to.slice(0, 7) >= period),
  );
  const accounts = [...new Set(sources.flatMap(sourceAccounts))].sort();
  const accountValues = params.getAll("source_account");
  const account = accountValues[0] ?? "";
  const invalidAccount = accountValues.length > 1 || (!!account && !accounts.includes(account));
  const visible = invalidAccount
    ? []
    : sources.filter((item) => !account || sourceAccounts(item).includes(account));

  return (
    <>
      <UiV2Panel
        eyebrow="Выписки"
        title="XML и исключения"
        id="month-sources"
        testIdPrefix="month"
        wide
      >
        <div className={styles.stack}>
          {month.status === "closed" ? (
            <p>
              Месяц закрыт. Сохранённые источники доступны для чтения; для исправлений явно открой
              месяц заново.
            </p>
          ) : (
            <SourceIntakeUpload key={month.id} compact />
          )}
          <p className={styles.note}>
            Загрузка сохраняет наблюдения без привязки к финансовому месяцу или счёту Hermes.
            Неизвестный ISIN требует явного разбора. Оригиналы после Reload нужно выбрать заново.
            Другие периоды доступны в{" "}
            <Link to="/v2/data/source-intake">общем журнале источников</Link>.
          </p>
          {list.isPending ? (
            <UiV2Loading label="Читаем источники месяца…" />
          ) : list.isError ? (
            <UiV2Notice title="Источники месяца не подтверждены" retry={() => void list.refetch()}>
              {formatApiError(list.error)}
            </UiV2Notice>
          ) : (
            <>
              <label className={styles.field}>
                Счёт источника месяца
                <select
                  aria-label="Счёт источника месяца"
                  value={account}
                  onChange={(event) => {
                    const value = event.target.value;
                    setParams((previous) => {
                      const next = new URLSearchParams(previous);
                      next.delete("source_account");
                      next.delete("instrument_isin");
                      next.delete("payout_as_of");
                      if (value) next.set("source_account", value);
                      return next;
                    });
                  }}
                >
                  <option value="">Все счета</option>
                  {invalidAccount && (
                    <option value={account}>Недоступный счёт: {account || "пустой"}</option>
                  )}
                  {accounts.map((value) => (
                    <option key={value}>{value}</option>
                  ))}
                </select>
              </label>
              {invalidAccount ? (
                <p role="alert">
                  Выбранный счёт источника не подтверждён для этого месяца. Выбери счёт явно.
                </p>
              ) : !sources.length ? (
                <p>
                  Выписок за отчётный месяц пока нет. Добавь XML выше; ручные данные сохраняются
                  отдельно.
                </p>
              ) : (
                <ul className={styles.sources} aria-label="Источники и исключения месяца">
                  {visible.map((intake) => (
                    <li key={intake.id} className={styles.source}>
                      <div>
                        <strong>
                          Источник #{intake.id} ·{" "}
                          {sourceAccounts(intake).join(" / ") || "Счёт неизвестен"}
                        </strong>
                        <p>
                          {formatDate(intake.covered_from)} — {formatDate(intake.covered_to)} ·
                          наблюдений: {intake.observations.length}
                        </p>
                        <p>
                          {intake.state.reporting_month_id === null
                            ? "Без финансовой привязки"
                            : "Привязан к месяцу"}{" "}
                          · исключений: {intake.exceptions.length}. Save не разрешает Close.
                        </p>
                        {!!intake.exceptions.length && (
                          <details>
                            <summary>Что исправить</summary>
                            <ul>
                              {[...new Set(intake.exceptions)].map((code) => (
                                <li key={code}>
                                  {brokerSourceTitle(code) ??
                                    "Нужно уточнить доказательства источника"}{" "}
                                  <code>{code}</code>
                                </li>
                              ))}
                            </ul>
                          </details>
                        )}
                      </div>
                      <div className={styles.actions}>
                        <button type="button" onClick={() => onReview(intake.id)}>
                          {month.status === "closed"
                            ? "Просмотреть разбор"
                            : "Разобрать и исправить"}{" "}
                          #{intake.id}
                        </button>
                        {sourceAccounts(intake)
                          .filter((value) => !account || value === account)
                          .map((value) => (
                            <Link
                              key={value}
                              to={`/v2/capital/monthly-returns?${new URLSearchParams({ source_account: value, bond_period: `${period}-01` })}#bond-slice`}
                            >
                              Облигации и доходность · {value}
                            </Link>
                          ))}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
        </div>
      </UiV2Panel>
      {!list.isPending && !list.isError && !list.isFetching && !invalidAccount && account ? (
        <UiV2MonthInstruments
          key={`${month.id}:${account}`}
          monthId={month.id}
          year={month.year}
          month={month.month}
          account={account}
          sourceVersion={JSON.stringify(
            sources.map((source) => [source.id, source.head_seq, source.manifest_digest]),
          )}
        />
      ) : !invalidAccount && !account && sources.length > 0 ? (
        <p>
          Выбери один счёт источника, чтобы открыть инструменты и предварительные выплаты этого
          месяца.
        </p>
      ) : null}
    </>
  );
}
