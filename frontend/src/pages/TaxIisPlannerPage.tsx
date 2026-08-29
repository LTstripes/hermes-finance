import { useCallback, useEffect, useMemo, useState } from "react";

import { formatApiError } from "../api/client";
import { listMonths } from "../api/months";
import { getTaxIisPlanner } from "../api/taxIisPlanner";
import type { ReportingMonth, TaxIisPlanner } from "../api/types";
import {
  Badge,
  Button,
  DataValue,
  EmptyState,
  ErrorState,
  Field,
  LoadingState,
  Panel,
  Select,
  Table,
  Td,
  Th,
} from "../components/ui";
import { formatDate, formatMoney, formatMonth } from "../lib/format";
import {
  BENEFIT_STATUS_LABELS,
  IIS_TYPE_LABELS,
  labelOf,
  MONTH_STATUS_LABELS,
} from "../lib/labels";

const SALARY_TAX_HISTORY_INCOMPLETE = "salary_tax_history_incomplete";
const TAX_BRACKETS_UNAVAILABLE = "tax_brackets_unavailable";

const TAX_BRACKET_SOURCE_LABELS: Record<string, string> = {
  official_default: "Официальная шкала",
  manual_configuration: "Пользовательская шкала",
};

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

function formatBracket(bracket: TaxIisPlanner["salary_tax"]["current_marginal_bracket"]): string {
  if (!bracket) return "—";
  const from = formatMoney(bracket.threshold_from.amount);
  const to = bracket.threshold_to
    ? formatMoney(bracket.threshold_to.amount)
    : "без верхней границы";
  return `${formatRateBps(bracket.rate_bps)} · ${from} — ${to}`;
}

function benefitTone(status: string): "draft" | "info" | "ok" | "missing" {
  if (status === "planned") return "draft";
  if (status === "submitted") return "info";
  if (status === "received") return "ok";
  return "missing";
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
  return "Есть дополнительное ограничение данных. Обнови страницу или проверь настройки НДФЛ.";
}

export function TaxIisPlannerPage() {
  const [months, setMonths] = useState<ReportingMonth[]>([]);
  const [selectedMonthId, setSelectedMonthId] = useState<number | null>(null);
  const [monthsLoading, setMonthsLoading] = useState(true);
  const [monthsReady, setMonthsReady] = useState(false);
  const [monthsError, setMonthsError] = useState<string | null>(null);
  const [planner, setPlanner] = useState<TaxIisPlanner | null>(null);
  const [plannerLoading, setPlannerLoading] = useState(false);
  const [plannerError, setPlannerError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setMonthsLoading(true);
    void listMonths(controller.signal)
      .then((rows) => {
        if (controller.signal.aborted) return;
        const sorted = sortMonths(rows);
        setMonths(sorted);
        setSelectedMonthId((current) =>
          current != null && sorted.some((month) => month.id === current)
            ? current
            : (defaultMonth(sorted)?.id ?? null),
        );
        setMonthsError(null);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setMonths([]);
          setSelectedMonthId(null);
          setMonthsError(formatApiError(error));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setMonthsLoading(false);
          setMonthsReady(true);
        }
      });
    return () => controller.abort();
  }, []);

  const loadPlanner = useCallback(async (monthId: number | null, signal?: AbortSignal) => {
    setPlannerLoading(true);
    setPlannerError(null);
    try {
      const data = await getTaxIisPlanner({ reportingMonthId: monthId }, signal);
      if (!signal?.aborted) setPlanner(data);
    } catch (error: unknown) {
      if (!signal?.aborted) {
        setPlanner(null);
        setPlannerError(formatApiError(error));
      }
    } finally {
      if (!signal?.aborted) setPlannerLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!monthsReady) return;
    const controller = new AbortController();
    void loadPlanner(selectedMonthId, controller.signal);
    return () => controller.abort();
  }, [loadPlanner, monthsReady, selectedMonthId]);

  const selectedMonth = useMemo(
    () => months.find((month) => month.id === selectedMonthId) ?? null,
    [months, selectedMonthId],
  );

  return (
    <section className="tax-iis-planner-page stack-18">
      <header className="page-header tax-iis-planner-page__header">
        <p className="eyebrow">Планирование</p>
        <h1>Налоги и ИИС</h1>
        <p className="page-header__description">
          Текущее состояние по сохранённым данным Hermes: без прогноза зарплаты и без расчётов по
          ценным бумагам.
        </p>
      </header>

      <div className="toolbar tax-iis-planner-page__toolbar">
        {monthsLoading ? (
          <span className="muted tiny">Загружаем отчётные месяцы…</span>
        ) : months.length > 0 ? (
          <Field htmlFor="tax-iis-planner-month" label="Отчётный месяц">
            <Select
              id="tax-iis-planner-month"
              onChange={(event) => setSelectedMonthId(Number(event.target.value))}
              value={selectedMonthId ?? ""}
            >
              {months.map((month) => (
                <option key={month.id} value={month.id}>
                  {formatMonth(month.year, month.month)} ·{" "}
                  {labelOf(MONTH_STATUS_LABELS, month.status)}
                </option>
              ))}
            </Select>
          </Field>
        ) : null}
        <Button
          disabled={plannerLoading}
          onClick={() => void loadPlanner(selectedMonthId)}
          variant="ghost"
        >
          Обновить
        </Button>
      </div>

      {monthsError ? (
        <div className="inline-alert inline-alert--warn" role="status">
          Не удалось загрузить список месяцев: {monthsError}
        </div>
      ) : null}

      {plannerLoading && !planner ? (
        <LoadingState description="Собираем текущий налоговый контекст и данные ИИС…" />
      ) : plannerError ? (
        <ErrorState description={plannerError} title="Не удалось загрузить планировщик" />
      ) : planner ? (
        <PlannerContent planner={planner} selectedMonth={selectedMonth} />
      ) : null}
    </section>
  );
}

function PlannerContent({
  planner,
  selectedMonth,
}: {
  planner: TaxIisPlanner;
  selectedMonth: ReportingMonth | null;
}) {
  const salary = planner.salary_tax;
  const reportingMonth = planner.as_of.reporting_month;

  return (
    <>
      <p className="tax-iis-planner-page__as-of muted tiny">
        {reportingMonth
          ? `Срез ${formatMonth(reportingMonth.year, reportingMonth.month)} · ${labelOf(MONTH_STATUS_LABELS, reportingMonth.status)} · снимок ${formatDate(reportingMonth.snapshot_date)}`
          : selectedMonth
            ? `Выбран ${formatMonth(selectedMonth.year, selectedMonth.month)}, но приложение не получило отчётный срез.`
            : "Нет отчётного месяца; зарплатный контекст недоступен."}
      </p>

      {planner.warnings.length > 0 ? (
        <div className="tax-iis-planner-page__warnings" role="status">
          {planner.warnings.map((warning) => (
            <div className="inline-alert inline-alert--warn" key={warning}>
              {warningText(warning)}
            </div>
          ))}
        </div>
      ) : null}

      <Panel label="НДФЛ" title="Текущий зарплатный контекст">
        <div className="tax-iis-planner-page__salary-grid">
          <DataValue
            label="Облагаемый доход с начала года"
            meta={
              salary.available
                ? "Накоплено в текущем налоговом году"
                : salary.warning_codes.includes(SALARY_TAX_HISTORY_INCOMPLETE)
                  ? "Недоступно при неполной истории"
                  : "Недоступно по текущему контексту"
            }
            value={formatMoney(salary.taxable_gross_ytd?.amount)}
          />
          <DataValue
            label="Текущая предельная ступень"
            meta={salary.current_marginal_bracket ? "По настроенной шкале НДФЛ" : "Не определена"}
            value={formatBracket(salary.current_marginal_bracket)}
          />
          <DataValue
            label="До следующего порога"
            meta={
              !salary.available
                ? "Не определяется"
                : salary.next_threshold
                  ? `Порог ${formatMoney(salary.next_threshold.amount)}`
                  : "Открытая финальная ступень"
            }
            value={formatMoney(salary.distance_to_next_threshold?.amount)}
          />
        </div>
        <div className="tax-iis-planner-page__salary-meta">
          <span>
            История: <strong>{salary.history_complete ? "полная" : "недоступна"}</strong>
          </span>
          {salary.opening_context_available ? (
            <span>Начальный налоговый контекст задан</span>
          ) : null}
          {salary.tax_bracket_source ? (
            <Badge tone="info">
              {labelOf(TAX_BRACKET_SOURCE_LABELS, salary.tax_bracket_source)}
            </Badge>
          ) : null}
        </div>
        {salary.warning_codes.length > 0 ? (
          <div className="tax-iis-planner-page__warning-codes" role="status">
            {salary.warning_codes.map((warning) => (
              <span key={warning}>{warningText(warning)}</span>
            ))}
          </div>
        ) : null}
      </Panel>

      <Panel label="ИИС" title="Взносы и налоговые льготы">
        {planner.iis_accounts.length === 0 ? (
          <EmptyState
            description="В сохранённых данных нет счетов с профилем ИИС."
            inline
            title="Нет профилей ИИС"
          />
        ) : (
          <div className="tax-iis-planner-page__accounts">
            {planner.iis_accounts.map((account) => (
              <IisAccountCard account={account} key={account.account_id} />
            ))}
          </div>
        )}
      </Panel>
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
    <article className="tax-iis-planner-page__account">
      <header className="tax-iis-planner-page__account-header">
        <div>
          <p className="panel__label">{labelOf(IIS_TYPE_LABELS, account.iis_type)}</p>
          <h3>{account.account_name}</h3>
        </div>
        <Badge tone="info">ИИС</Badge>
      </header>
      <p className="tax-iis-planner-page__account-meta muted tiny">
        Открыт {formatDate(account.opened_at)} · Закрытие доступно с{" "}
        {formatDate(account.eligible_close_at)}
      </p>

      <section
        className="tax-iis-planner-page__account-section"
        aria-labelledby={`iis-contributions-${account.account_id}`}
      >
        <h4 id={`iis-contributions-${account.account_id}`}>Взносы по налоговым годам</h4>
        {account.contributions_by_tax_year.length === 0 ? (
          <p className="muted tiny">Нет сохранённых взносов.</p>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>Налоговый год</Th>
                <Th numeric>Взнос</Th>
                <Th>Прогресс</Th>
              </tr>
            </thead>
            <tbody>
              {account.contributions_by_tax_year.map((contribution) => (
                <tr key={contribution.tax_year}>
                  <Td>{contribution.tax_year}</Td>
                  <Td numeric>{formatMoney(contribution.amount.amount)}</Td>
                  <Td>
                    <Badge tone={contribution.is_target_reached ? "ok" : "draft"}>
                      {contribution.is_target_reached ? "Цель достигнута" : "В процессе"}
                    </Badge>
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </section>

      <section
        className="tax-iis-planner-page__account-section"
        aria-labelledby={`iis-benefits-${account.account_id}`}
      >
        <h4 id={`iis-benefits-${account.account_id}`}>Льготы по статусам</h4>
        <div className="tax-iis-planner-page__benefits-grid">
          {benefitRows.map(([status, amount]) => (
            <DataValue
              key={status}
              label={
                <Badge tone={benefitTone(status)}>{labelOf(BENEFIT_STATUS_LABELS, status)}</Badge>
              }
              value={formatMoney(amount.amount)}
            />
          ))}
        </div>
        <p className="muted tiny">
          Запланировано, подано, получено и отклонено показаны отдельно; эти статусы не
          складываются.
        </p>
      </section>
    </article>
  );
}
