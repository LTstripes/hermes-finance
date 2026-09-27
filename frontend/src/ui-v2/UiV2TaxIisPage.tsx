import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router";

import { formatApiError } from "../api/client";
import { listMonths } from "../api/months";
import { getTaxIisPlanner } from "../api/taxIisPlanner";
import type { ReportingMonth, TaxIisPlanner } from "../api/types";
import { formatDate, formatMoney, formatMonth } from "../lib/format";
import {
  BENEFIT_STATUS_LABELS,
  IIS_TYPE_LABELS,
  labelOf,
  MONTH_STATUS_LABELS,
} from "../lib/labels";
import { UiV2Loading, UiV2Notice, UiV2WidgetState } from "./UiV2StateBlocks";
import { UiV2Panel } from "./UiV2Panel";
import { UiV2Shell } from "./UiV2Shell";
import styles from "./UiV2TaxIis.module.css";
import sharedStyles from "./UiV2Page.module.css";

const SALARY_TAX_HISTORY_INCOMPLETE = "salary_tax_history_incomplete";
const TAX_BRACKETS_UNAVAILABLE = "tax_brackets_unavailable";

const TAX_BRACKET_SOURCE_LABELS: Record<string, string> = {
  official_default: "Официальная шкала",
  manual_configuration: "Пользовательская шкала",
};

function parseMonthId(value: string): number | null {
  if (!/^\d+$/.test(value)) return null;
  const monthId = Number(value);
  return Number.isSafeInteger(monthId) && monthId > 0 ? monthId : null;
}

function sortMonths(months: ReportingMonth[]): ReportingMonth[] {
  return [...months].sort((a, b) => b.year - a.year || b.month - a.month || b.id - a.id);
}

function defaultMonth(months: ReportingMonth[]): ReportingMonth | null {
  const sorted = sortMonths(months);
  return sorted.find((month) => month.status === "closed") ?? sorted[0] ?? null;
}

function formatRateBps(rateBps: number): string {
  const whole = Math.trunc(rateBps / 100);
  const remainder = Math.abs(rateBps % 100);
  return remainder === 0 ? `${whole}%` : `${whole},${String(remainder).padStart(2, "0")}%`;
}

function warningText(code: string): string {
  if (code === SALARY_TAX_HISTORY_INCOMPLETE) {
    return "История зарплатного НДФЛ неполна: накопленный облагаемый доход, текущая ступень и расстояние до порога недоступны.";
  }
  if (code === TAX_BRACKETS_UNAVAILABLE) {
    return "Полная шкала налоговых ступеней недоступна: текущая ступень и порог не определяются.";
  }
  if (code === "salary_tax_context_unavailable") {
    return "Нет отчётного месяца, на который можно опереть зарплатный контекст.";
  }
  return "Есть дополнительное ограничение данных налогового планировщика.";
}

function sourceLabel(source: string | null): string {
  if (source === null) return "Источник шкалы не указан";
  return TAX_BRACKET_SOURCE_LABELS[source] ?? `Неизвестный источник: ${source}`;
}

function unavailableValue(available: boolean): string {
  return available ? "Не указано" : "Недоступно";
}

function Metric({
  label,
  meta,
  testId,
  value,
}: {
  label: string;
  meta: string;
  testId: string;
  value: string;
}) {
  return (
    <div className={styles.metric}>
      <dt>{label}</dt>
      <dd data-testid={testId}>{value}</dd>
      <p>{meta}</p>
    </div>
  );
}

function WarningList({ codes }: { codes: string[] }) {
  if (codes.length === 0) return null;
  const occurrences = new Map<string, number>();
  return (
    <ul className={styles.warnings} role="status">
      {codes.map((code) => {
        const occurrence = occurrences.get(code) ?? 0;
        occurrences.set(code, occurrence + 1);
        return (
          <li key={`${code}-${occurrence}`}>
            {warningText(code)} <code>{code}</code>
          </li>
        );
      })}
    </ul>
  );
}

function PlannerContent({
  planner,
  requestedMonthId,
  selectedMonth,
}: {
  planner: TaxIisPlanner;
  requestedMonthId: number | null;
  selectedMonth: ReportingMonth | null;
}) {
  const salary = planner.salary_tax;
  const reportingMonth = planner.as_of.reporting_month;
  const taxYear = planner.tax_year ?? salary.tax_year;
  const rateBps =
    salary.current_marginal_rate_bps ?? salary.current_marginal_bracket?.rate_bps ?? null;
  const bracket = salary.current_marginal_bracket;
  const bracketValue = bracket
    ? formatMoney(bracket.threshold_from.amount) +
      " — " +
      (bracket.threshold_to ? formatMoney(bracket.threshold_to.amount) : "без верхней границы")
    : unavailableValue(salary.available);
  const nextThresholdValue = salary.next_threshold
    ? formatMoney(salary.next_threshold.amount)
    : salary.available
      ? "Нет следующего порога"
      : "Недоступно";
  const distanceValue = salary.distance_to_next_threshold
    ? formatMoney(salary.distance_to_next_threshold.amount)
    : salary.available && salary.next_threshold === null
      ? "—"
      : unavailableValue(salary.available);
  const historyLabel = salary.history_complete
    ? "Полная"
    : salary.history_coverage === "unavailable"
      ? "Недоступна"
      : "Неполная";
  const monthMismatch =
    requestedMonthId !== null && reportingMonth !== null && reportingMonth.id !== requestedMonthId;

  return (
    <>
      <div className={styles.context} data-testid="tax-iis-as-of">
        {taxYear === null ? (
          <strong>Налоговый год недоступен</strong>
        ) : (
          <strong>Налоговый год {taxYear}</strong>
        )}
        {reportingMonth ? (
          <span>
            Срез {formatMonth(reportingMonth.year, reportingMonth.month)} ·{" "}
            {labelOf(MONTH_STATUS_LABELS, reportingMonth.status)} · снимок{" "}
            {formatDate(reportingMonth.snapshot_date)}
          </span>
        ) : selectedMonth ? (
          <span>
            Выбран {formatMonth(selectedMonth.year, selectedMonth.month)}, но приложение не получило
            отчётный срез.
          </span>
        ) : requestedMonthId !== null ? (
          <span>Запрошен отчётный месяц {requestedMonthId}, но срез не получен.</span>
        ) : (
          <span>Нет отчётного месяца; зарплатный контекст недоступен.</span>
        )}
      </div>

      {monthMismatch ? (
        <UiV2Notice title="Получен другой отчётный срез">
          Запрошен месяц {requestedMonthId}, а планировщик вернул месяц {reportingMonth?.id}. Данные
          показаны по срезу, указанному ответом сервера.
        </UiV2Notice>
      ) : null}

      <WarningList codes={planner.warnings} />

      <UiV2Panel
        eyebrow="НДФЛ"
        id="tax-iis-salary"
        testIdPrefix="tax-iis"
        title="Текущий зарплатный контекст"
        wide
      >
        <dl className={styles.salaryGrid}>
          <Metric
            label="Облагаемый доход с начала года"
            meta={
              salary.available
                ? "Накоплено в текущем налоговом году"
                : salary.warning_codes.includes(SALARY_TAX_HISTORY_INCOMPLETE)
                  ? "Недоступно при неполной истории"
                  : "Недоступно по текущему контексту"
            }
            testId="tax-iis-taxable-gross-ytd"
            value={
              salary.taxable_gross_ytd
                ? formatMoney(salary.taxable_gross_ytd.amount)
                : unavailableValue(salary.available)
            }
          />
          <Metric
            label="Текущая предельная ступень"
            meta={bracket ? "Границы по шкале НДФЛ" : "Ступень не определена"}
            testId="tax-iis-marginal-bracket"
            value={bracketValue}
          />
          <Metric
            label="Текущая предельная ставка"
            meta={
              salary.current_marginal_rate_bps === null && bracket
                ? "Ставка указана в текущей ступени"
                : salary.available
                  ? "По ответу налогового планировщика"
                  : "Недоступно по текущему контексту"
            }
            testId="tax-iis-marginal-rate"
            value={rateBps === null ? unavailableValue(salary.available) : formatRateBps(rateBps)}
          />
          <Metric
            label="Следующий порог"
            meta={
              salary.next_threshold
                ? "По настроенной шкале НДФЛ"
                : salary.available
                  ? "Открытая финальная ступень"
                  : "Не определяется"
            }
            testId="tax-iis-next-threshold"
            value={nextThresholdValue}
          />
          <Metric
            label="Расстояние до порога"
            meta={
              salary.next_threshold
                ? "Значение из ответа налогового планировщика"
                : salary.available
                  ? "У финальной ступени нет следующего порога"
                  : "Не определяется"
            }
            testId="tax-iis-threshold-distance"
            value={distanceValue}
          />
        </dl>

        <div className={styles.salaryMeta}>
          <span className={styles.metaItem}>
            Зарплатный контекст: {salary.available ? "доступен" : "недоступен"}
          </span>
          <span className={styles.metaItem}>История НДФЛ: {historyLabel}</span>
          <span className={styles.metaItem}>
            Начальный контекст: {salary.opening_context_available ? "задан" : "не задан"}
          </span>
          <span className={styles.sourceBadge}>
            Источник шкалы: {sourceLabel(salary.tax_bracket_source)}
          </span>
        </div>
        <WarningList codes={salary.warning_codes} />
      </UiV2Panel>

      <UiV2Panel
        eyebrow="ИИС"
        id="tax-iis-accounts"
        testIdPrefix="tax-iis"
        title="Взносы и налоговые льготы"
        wide
      >
        {planner.iis_accounts.length === 0 ? (
          <UiV2WidgetState title="Нет профилей ИИС в сохранённых данных" />
        ) : (
          <div className={styles.accountList}>
            {planner.iis_accounts.map((account) => (
              <IisAccountCard account={account} key={account.account_id} />
            ))}
          </div>
        )}
      </UiV2Panel>
    </>
  );
}

function IisAccountCard({ account }: { account: TaxIisPlanner["iis_accounts"][number] }) {
  const benefits = account.tax_benefits;
  const benefitRows = [
    ["planned", benefits.planned],
    ["submitted", benefits.submitted],
    ["received", benefits.received],
    ["rejected", benefits.rejected],
  ] as const;

  return (
    <article className={styles.accountCard}>
      <header className={styles.accountHeader}>
        <div>
          <p className={styles.eyebrow}>{labelOf(IIS_TYPE_LABELS, account.iis_type)}</p>
          <h3>{account.account_name}</h3>
        </div>
        <span className={styles.accountType}>ИИС</span>
      </header>
      <p className={styles.accountMeta}>
        Открыт {formatDate(account.opened_at)} · Закрытие доступно с{" "}
        {formatDate(account.eligible_close_at, { empty: "не рассчитано" })}
      </p>

      <section
        aria-labelledby={`iis-contributions-${account.account_id}`}
        className={styles.accountSection}
      >
        <h4 id={`iis-contributions-${account.account_id}`}>Взносы по налоговым годам</h4>
        {account.contributions_by_tax_year.length === 0 ? (
          <p className={styles.emptyCopy}>Нет сохранённых взносов.</p>
        ) : (
          <div className={styles.tableWrap}>
            <table className={styles.contributionTable}>
              <thead>
                <tr>
                  <th scope="col">Налоговый год</th>
                  <th className={styles.numeric} scope="col">
                    Взнос
                  </th>
                  <th scope="col">Прогресс</th>
                </tr>
              </thead>
              <tbody>
                {account.contributions_by_tax_year.map((contribution) => (
                  <tr key={contribution.tax_year}>
                    <th scope="row">{contribution.tax_year}</th>
                    <td className={styles.numeric}>{formatMoney(contribution.amount.amount)}</td>
                    <td>
                      <span
                        data-reached={contribution.is_target_reached}
                        className={styles.targetState}
                      >
                        {contribution.is_target_reached ? "Цель достигнута" : "В процессе"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section
        aria-labelledby={`iis-benefits-${account.account_id}`}
        className={styles.accountSection}
      >
        <h4 id={`iis-benefits-${account.account_id}`}>Льготы по статусам</h4>
        <dl className={styles.benefitsGrid}>
          {benefitRows.map(([status, amount]) => (
            <div className={styles.benefit} key={status}>
              <dt>{labelOf(BENEFIT_STATUS_LABELS, status)}</dt>
              <dd>{formatMoney(amount.amount)}</dd>
            </div>
          ))}
        </dl>
        <p className={styles.nonAggregateNote}>
          Запланировано, подано, получено и отклонено показаны отдельно; эти статусы не
          складываются.
        </p>
      </section>
    </article>
  );
}

export default function UiV2TaxIisPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const monthValues = searchParams.getAll("month");
  const rawMonth = monthValues[0];
  const monthContext =
    rawMonth === undefined ? undefined : monthValues.length === 1 ? parseMonthId(rawMonth) : null;
  const monthContextError =
    monthValues.length > 1 || (rawMonth !== undefined && monthContext === null)
      ? "В ссылке указан некорректный месяц. Выберите доступный отчётный месяц."
      : null;
  const returnQuery = searchParams.toString();
  const incomeReturnTo = `/v2/income${returnQuery ? `?${returnQuery}` : ""}`;
  const [months, setMonths] = useState<ReportingMonth[]>([]);
  const [monthsLoading, setMonthsLoading] = useState(true);
  const [monthsReady, setMonthsReady] = useState(false);
  const [monthsError, setMonthsError] = useState<string | null>(null);
  const [planner, setPlanner] = useState<TaxIisPlanner | null>(null);
  const [plannerLoading, setPlannerLoading] = useState(false);
  const [plannerError, setPlannerError] = useState<string | null>(null);
  const [refreshSequence, setRefreshSequence] = useState(0);

  const autoSelectedMonthId = useMemo(() => defaultMonth(months)?.id ?? null, [months]);
  const selectedMonthId = monthContext === undefined ? autoSelectedMonthId : monthContext;
  const selectedMonth = months.find((month) => month.id === selectedMonthId) ?? null;

  const updateMonthContext = useCallback(
    (monthId: number, options?: { replace?: boolean }) => {
      const next = new URLSearchParams(searchParams);
      next.set("month", String(monthId));
      if (options?.replace) setSearchParams(next, { replace: true });
      else setSearchParams(next);
    },
    [searchParams, setSearchParams],
  );

  useEffect(() => {
    const controller = new AbortController();
    setMonthsLoading(true);
    void listMonths(controller.signal)
      .then((rows) => {
        if (controller.signal.aborted) return;
        setMonths(sortMonths(rows));
        setMonthsError(null);
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setMonths([]);
        setMonthsError(formatApiError(error));
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setMonthsLoading(false);
          setMonthsReady(true);
        }
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!monthsReady || monthContext !== undefined || autoSelectedMonthId === null) return;
    updateMonthContext(autoSelectedMonthId, { replace: true });
  }, [autoSelectedMonthId, monthContext, monthsReady, updateMonthContext]);

  // The refresh buttons deliberately re-run this effect without changing the request parameters.
  // biome-ignore lint/correctness/useExhaustiveDependencies: refreshSequence is the refresh trigger.
  useEffect(() => {
    if (!monthsReady) return;
    if (monthContext === undefined && autoSelectedMonthId !== null) return;
    if (monthContextError) {
      setPlanner(null);
      setPlannerError(null);
      setPlannerLoading(false);
      return;
    }

    const controller = new AbortController();
    const requestedMonthId = monthContext === undefined ? null : monthContext;
    setPlanner(null);
    setPlannerLoading(true);
    setPlannerError(null);
    void getTaxIisPlanner({ reportingMonthId: requestedMonthId }, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setPlanner(data);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setPlanner(null);
          setPlannerError(formatApiError(error));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setPlannerLoading(false);
      });
    return () => controller.abort();
  }, [autoSelectedMonthId, monthContext, monthContextError, monthsReady, refreshSequence]);

  const selectedMonthIsUnavailable =
    monthsReady &&
    monthsError === null &&
    monthContext !== undefined &&
    monthContext !== null &&
    selectedMonth === null;

  return (
    <UiV2Shell
      active="income"
      busy={monthsLoading || plannerLoading}
      header={
        <>
          <p className={sharedStyles.eyebrow}>Сохранённые налоговые данные</p>
          <h1>Налоги и ИИС</h1>
          <p className={sharedStyles.subtitle}>
            Зарплатный НДФЛ и профили ИИС по выбранному отчётному контексту, без прогноза зарплаты и
            расчётов по ценным бумагам.
          </p>
        </>
      }
      v1ReturnPath="/tax-iis-planner"
    >
      <section className={styles.page}>
        <div className={styles.toolbar}>
          {monthsLoading ? (
            <span className={sharedStyles.loading} role="status">
              Загружаем отчётные месяцы…
            </span>
          ) : months.length > 0 ? (
            <label className={styles.monthField} htmlFor="tax-iis-reporting-month">
              Отчётный месяц
              <select
                className={styles.monthSelect}
                id="tax-iis-reporting-month"
                onChange={(event) => {
                  const monthId = parseMonthId(event.target.value);
                  if (monthId !== null) updateMonthContext(monthId);
                }}
                value={selectedMonthId ?? ""}
              >
                {selectedMonthId === null ? (
                  <option value="">Выберите отчётный месяц</option>
                ) : null}
                {selectedMonthIsUnavailable ? (
                  <option value={selectedMonthId ?? ""}>Выбранный месяц недоступен в списке</option>
                ) : null}
                {months.map((month) => (
                  <option key={month.id} value={month.id}>
                    {formatMonth(month.year, month.month)} ·{" "}
                    {labelOf(MONTH_STATUS_LABELS, month.status)}
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <span className={sharedStyles.loading}>Нет отчётных месяцев в списке.</span>
          )}
          <button
            className={styles.toolbarButton}
            disabled={plannerLoading || monthContextError !== null}
            onClick={() => setRefreshSequence((sequence) => sequence + 1)}
            type="button"
          >
            Обновить
          </button>
          <Link className={styles.backLink} to={incomeReturnTo}>
            ← Доход и планы
          </Link>
        </div>

        {monthsError ? (
          <UiV2Notice title="Не удалось загрузить отчётные месяцы">
            Список месяцев недоступен: {monthsError}. Данные планировщика остаются привязаны к
            указанному контексту.
          </UiV2Notice>
        ) : null}

        {monthContextError ? (
          <UiV2Notice title="Некорректный отчётный месяц">
            {monthContextError} Выбери месяц из списка выше. Планировщик не переключён на другой
            отчётный месяц.
          </UiV2Notice>
        ) : null}

        {!monthContextError && selectedMonthIsUnavailable ? (
          <UiV2Notice title="Выбранного месяца нет в доступном списке">
            Запрос сохранён как есть. Данные ниже появятся только если налоговый планировщик вернёт
            ответ именно для этого контекста.
          </UiV2Notice>
        ) : null}

        {!monthContextError && (plannerLoading || (!planner && plannerError === null)) ? (
          <UiV2Loading label="Собираем текущий налоговый контекст и данные ИИС…" />
        ) : plannerError ? (
          <UiV2Notice
            retry={() => setRefreshSequence((sequence) => sequence + 1)}
            title="Не удалось загрузить планировщик"
          >
            {plannerError}
          </UiV2Notice>
        ) : !monthContextError && planner ? (
          <PlannerContent
            planner={planner}
            requestedMonthId={monthContext ?? null}
            selectedMonth={selectedMonth}
          />
        ) : !monthContextError && !plannerLoading && !plannerError ? (
          <UiV2WidgetState title="Налоговый контекст и данные ИИС пока недоступны" />
        ) : null}
      </section>
    </UiV2Shell>
  );
}
