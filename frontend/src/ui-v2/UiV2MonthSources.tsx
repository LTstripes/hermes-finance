import { useQuery } from "@tanstack/react-query";
import { useLayoutEffect, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { formatApiError } from "../api/client";
import { SourceMonthReturn } from "./SourceMonthReturn";
import { listAllSourceIntakes, type SourceIntake } from "../api/sourceIntake";
import type { ReportingMonth } from "../api/types";
import { BrokerMonthReview } from "../components/month-close/BrokerMonthReview";
import { useBrokerOriginalSession } from "../components/month-close/brokerOriginalSession";
import { useSourceIntakeRecovery } from "../components/month-close/SourceIntakeJournal";
import { SourceIntakeUpload } from "../components/month-close/SourceIntakeUpload";
import { formatDate } from "../lib/format";
import { lastDayOfMonth } from "../lib/period";
import { brokerSourceTitle } from "../lib/ownerCopy";
import { UiV2MonthInstruments } from "./UiV2MonthInstruments";
import { monthWorkspacePath } from "./monthSelection";
import styles from "./UiV2MonthWorkspace.module.css";
import { UiV2Panel } from "./UiV2Panel";
import { UiV2Loading, UiV2Notice } from "./UiV2StateBlocks";

function sourceAccounts(intake: SourceIntake): string[] {
  return [
    ...new Set([intake.document.filename_account, ...(intake.document.source_accounts ?? [])]),
  ].filter((value) => typeof value === "string" && value.trim().length > 0);
}

export function UiV2MonthSources({
  month,
  onReview,
  canClose,
}: {
  month: Pick<ReportingMonth, "id" | "year" | "month" | "status">;
  onReview?: (id: number) => void;
  canClose?: boolean;
}) {
  const [params, setParams] = useSearchParams();
  const { session, original } = useBrokerOriginalSession();
  const [reviewExpanded, setReviewExpanded] = useState(Boolean(original.file));
  const { command: journalCommand } = useSourceIntakeRecovery();
  // Raw URL values distinguish invalid/duplicate scopes, including A→invalid→A.
  const scope = JSON.stringify(params.getAll("source_account"));
  const [review, setReview] = useState(() => ({
    // A retained command owns its original scope even after SPA remount. A
    // retained File without a command must be reselected for an explicit filter.
    scope: journalCommand
      ? JSON.stringify(journalCommand.sourceAccount ? [journalCommand.sourceAccount] : [])
      : original.pending
        ? JSON.stringify([original.pending.preview.document.filename_account])
        : original.file && scope !== "[]"
          ? "[]"
          : scope,
    generation: 0,
    monthId: journalCommand?.monthId ?? month.id,
    selection: null as { id: number } | null,
  }));
  const changingScope = scope !== review.scope || month.id !== review.monthId;
  const unresolved = Boolean(original.pending) || original.busy || Boolean(journalCommand);
  useLayoutEffect(() => {
    if (!changingScope || unresolved) return;
    // Never select/clear while a command's ACK or independent GET is unresolved.
    session.select(null, month.id, "");
    setReview((previous) => ({
      scope,
      monthId: month.id,
      generation: previous.generation + 1,
      selection: null,
    }));
  }, [changingScope, unresolved, scope, month.id, session]);
  const list = useQuery({
    queryKey: ["source-intakes", month.id, "month-overview"],
    queryFn: ({ signal }) => listAllSourceIntakes(signal),
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
  // Prior originals can supply a quantity scenario, never this month's closing EOD.
  const history = (list.data ?? []).filter((item) => item.covered_from.slice(0, 7) <= period);
  const accounts = [...new Set(history.flatMap(sourceAccounts))].sort();
  const accountValues = params.getAll("source_account");
  const account = accountValues[0] ?? "";
  const invalidAccount = accountValues.length > 1 || (!!account && !accounts.includes(account));
  const visible = invalidAccount
    ? []
    : sources.filter((item) => !account || sourceAccounts(item).includes(account));
  const closing = lastDayOfMonth(month.year, month.month);
  const fullMonthSources = visible.filter(
    (item) => item.covered_from === `${period}-01` && item.covered_to === closing,
  );
  const overlappingSources = visible.length - fullMonthSources.length;

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
          <p>
            Сохрани выписки → выбери счёт → проверь инструменты, сделки и выплаты → исправь
            исключения. Доступный расчёт и недостающие доказательства показаны для выбранного
            месяца.
          </p>
          <section aria-label="Состояние источников месяца">
            {list.isPending || list.isFetching ? (
              <p>Проверяем сохранённые выписки…</p>
            ) : list.isError ? (
              <p>Число сохранённых выписок не подтверждено.</p>
            ) : (
              <>
                <p>
                  {period} · счёт источника:{" "}
                  {invalidAccount ? "не подтверждён" : account || "выбери один счёт"}.
                  {invalidAccount
                    ? ""
                    : ` Полных месячных оригиналов: ${fullMonthSources.length}. Исторических или частичных пересечений: ${overlappingSources}.`}
                </p>
                {!sources.length && (
                  <p>
                    Выписок за отчётный месяц пока нет. Добавь XML ниже; ручные данные сохраняются
                    отдельно. Историческое количество можно проверить по выбранному счёту, но оно не
                    доказывает доходность этого месяца.
                  </p>
                )}
                {!invalidAccount && fullMonthSources.length === 0 && (
                  <p>
                    Полного месячного оригинала пока нет. Нужны границы {period}-01 — {closing} и
                    закрывающий EOD {closing}. Историческое пересечение не доказывает конец месяца.
                  </p>
                )}
                <nav className={styles.sourceNav} aria-label="Действия с источниками месяца">
                  <a href="#month-source-list">Сохранённые выписки и исключения</a>
                  {!invalidAccount && account && (
                    <a href="#month-instruments">Инструменты, сделки и выплаты</a>
                  )}
                </nav>
              </>
            )}
            <p>
              {month.status === "closed"
                ? "Финансовый месяц CLOSED · только чтение."
                : canClose === true
                  ? "Финансовый DRAFT · серверная проверка допускает явное закрытие."
                  : "Финансовый DRAFT · готовность к закрытию проверяется отдельно."}{" "}
              Сохранение выписки и предварительная доходность не означают финансового принятия.{" "}
              <Link to={monthWorkspacePath(month.id, "final_review_close")}>
                Проверка финансового месяца
              </Link>
            </p>
          </section>
          {!!account &&
            !invalidAccount &&
            !changingScope &&
            !list.isPending &&
            !list.isError &&
            !list.isFetching && (
              <SourceMonthReturn key={`${account}:${period}`} account={account} period={period} />
            )}
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
              <label className={styles.field} id="month-source-list">
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
              ) : !visible.length ? (
                <p>
                  Для выбранного счёта выписок этого периода нет. Нужен оригинал с границами
                  отчётного месяца; выписки других периодов не становятся его EOD.
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
                          {intake.covered_from === `${period}-01` && intake.covered_to === closing
                            ? "Полный календарный период по датам; достаточность доказательств проверяется отдельно."
                            : "Историческое или частичное пересечение; не полный месячный оригинал."}
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
                        <button
                          type="button"
                          disabled={changingScope || unresolved}
                          onClick={() => {
                            setReviewExpanded(true);
                            setReview((previous) => ({
                              ...previous,
                              selection: { id: intake.id },
                            }));
                            onReview?.(intake.id);
                            document
                              .getElementById("month-source-review")
                              ?.scrollIntoView?.({ block: "start" });
                          }}
                        >
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
      {!changingScope &&
      !list.isPending &&
      !list.isError &&
      !list.isFetching &&
      !invalidAccount &&
      account ? (
        <UiV2MonthInstruments
          key={`${month.id}:${account}`}
          monthId={month.id}
          year={month.year}
          month={month.month}
          account={account}
          sourceVersion={JSON.stringify(
            history.map((source) => [source.id, source.head_seq, source.manifest_digest]),
          )}
        />
      ) : !invalidAccount && !account && sources.length > 0 ? (
        <p>
          Выбери один счёт источника, чтобы открыть инструменты и предварительные выплаты этого
          месяца.
        </p>
      ) : null}
      <div id="month-source-review" tabIndex={-1}>
        <details open={reviewExpanded || unresolved || params.get("step") === "final_review_close"}>
          {/* biome-ignore lint/a11y/noStaticElementInteractions: native summary supports keyboard activation; controlled click avoids delayed toggle events hiding GET recovery. */}
          <summary
            onClick={(event) => {
              event.preventDefault();
              setReviewExpanded((value) => !value);
            }}
          >
            Разбор сохранённой выписки и финансовый DRAFT
          </summary>
          {changingScope && unresolved && (
            <p role="alert">
              Переключение счёта отложено. Разбор остаётся в прежнем контексте:{" "}
              {original.pending?.preview.document.filename_account ||
                JSON.parse(review.scope).join(" / ") ||
                "Все счета"}{" "}
              · месяц #{review.monthId}. Заверши чтение результата исходного запроса. Изменения
              заблокированы; новый POST не выполняется.
            </p>
          )}
          {(!changingScope || unresolved) && (
            <BrokerMonthReview
              key={review.generation}
              monthId={review.monthId}
              closed={month.status === "closed"}
              scopeBlocked={changingScope}
              sourceAccount={
                changingScope
                  ? (JSON.parse(review.scope)[0] ?? "")
                  : invalidAccount
                    ? null
                    : account
              }
              intakeSelection={review.selection}
            />
          )}
        </details>
      </div>
    </>
  );
}
