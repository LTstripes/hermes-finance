import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { listAccounts } from "../api/accounts";
import { listMonths } from "../api/months";
import { getPerformanceAttribution, getPerformanceReadiness } from "../api/performance";
import type { Account, PerformanceReadiness } from "../api/types";
import { formatDate } from "../lib/format";
import {
  performanceAttributionUnavailableMessage,
  VALUE_BRIDGE_DISCLAIMER,
  VALUE_BRIDGE_LABEL,
} from "../lib/performanceMessages";
import { queryKeys } from "../queryClient";
import {
  formatPerformancePercent,
  isReadinessFresh,
  sortDiagnostics,
} from "./CapitalPerformanceSummary";
import {
  intervalDays,
  needsAnnualizationWarning,
  type PerformanceContext,
  parsePerformanceContext,
  performanceDetailHref,
  periodPresets,
} from "./capitalPerformanceContext";
import { capabilityCopy, diagnosticCopy, hasWorkingAction } from "./capitalPerformanceCopy";
import { sortReportingMonths } from "./monthSelection";
import { ObservedValuationCapture } from "./ObservedValuationCapture";
import { PerformancePreparation } from "./PerformancePreparation";
import styles from "./UiV2CapitalPerformance.module.css";
import pageStyles from "./UiV2Page.module.css";
import { UiV2Shell } from "./UiV2Shell";
import { isQueryReady, UiV2Loading, UiV2Notice, UiV2WidgetState } from "./UiV2StateBlocks";
import { moneyDeltaText as moneyDelta } from "./valueFormat";

function accountName(accounts: Account[] | undefined, id: number): string {
  const found = accounts?.find((account) => account.id === id);
  return found?.name ?? `Счёт ${id}`;
}

function AccountPerformanceRow({
  accountId,
  end,
  name,
  start,
}: {
  accountId: number;
  end: string;
  name: string;
  start: string;
}) {
  const readinessQuery = useQuery({
    queryKey: queryKeys.performanceReadiness(start, end, "account", accountId),
    queryFn: ({ signal }) => getPerformanceReadiness(start, end, "account", accountId, signal),
    refetchOnWindowFocus: true,
  });
  const data = readinessQuery.data ?? null;
  const fresh = isReadinessFresh(data, {
    start,
    end,
    scope: "account",
    accountId,
  });
  const ready = isQueryReady(readinessQuery) && fresh;
  const xirr = ready && data ? data.xirr : null;
  const twrr = ready && data ? data.twrr : null;
  const xirrText =
    xirr && xirr.availability === "available" && xirr.quality === "exact"
      ? (formatPerformancePercent(xirr.value) ?? "—")
      : "—";
  const twrrText =
    twrr && twrr.availability === "available" && twrr.quality === "exact"
      ? (formatPerformancePercent(twrr.value) ?? "—")
      : "—";
  const state =
    readinessQuery.isError || (isQueryReady(readinessQuery) && !fresh)
      ? "проверка не завершилась"
      : !isQueryReady(readinessQuery)
        ? "загружаем…"
        : xirr?.availability === "available" && twrr?.availability === "available"
          ? "доступен"
          : xirr?.availability === "available" || twrr?.availability === "available"
            ? "частично доступен"
            : "недоступен";
  return (
    <tr data-testid={`performance-account-row-${accountId}`}>
      <td>{name}</td>
      <td className={styles.numeric}>{twrrText}</td>
      <td className={styles.numeric}>{xirrText}</td>
      <td>
        {state}{" "}
        <Link
          to={performanceDetailHref({ start, end, scope: "account", accountId, view: "accounts" })}
        >
          Открыть
        </Link>
      </td>
    </tr>
  );
}

function MetricPanel({
  context,
  readiness,
  retry,
}: {
  context: PerformanceContext;
  readiness: PerformanceReadiness;
  retry: () => void;
}) {
  const { xirr, twrr } = readiness;
  const days = intervalDays(context.start, context.end);
  const warn = needsAnnualizationWarning(context.start, context.end);
  const renderMetric = (metric: typeof xirr, label: string, sub: string, testId: string) => {
    const available =
      metric.availability === "available" && metric.quality === "exact" && metric.value !== null;
    const text = available ? formatPerformancePercent(metric.value) : null;
    const reasons = metric.reason_codes;
    return (
      <article className={styles.metricCard} data-testid={testId}>
        <p className={styles.periodLine}>{label}</p>
        {text !== null ? (
          <>
            <p className={styles.metricValue}>{text}</p>
            <p className={styles.metricNote}>
              {sub} · {formatDate(metric.period.start_date)} — {formatDate(metric.period.end_date)}{" "}
              · {metric.performance_currency} · единицы: п.п.
            </p>
          </>
        ) : (
          <p className={styles.metricNote} data-testid={`${testId}-reason`}>
            {reasons.length > 0
              ? diagnosticCopy(
                  sortDiagnostics(
                    readiness.diagnostics.filter((d) => d.affected_metrics.includes(metric.metric)),
                  )[0]?.key ?? "unknown_reason",
                ).title
              : "Не удалось получить подтверждённый результат для выбранного периода."}{" "}
            <button className={styles.inlineButton} onClick={retry} type="button">
              Повторить чтение
            </button>
          </p>
        )}
      </article>
    );
  };
  return (
    <div>
      <div className={styles.metricGrid}>
        {renderMetric(
          xirr,
          "Доходность ваших вложений · XIRR, годовых",
          "годовых",
          "performance-detail-xirr",
        )}
        {renderMetric(twrr, "Доходность за период · TWRR", "за период", "performance-detail-twrr")}
      </div>
      {warn && xirr.availability === "available" ? (
        <p className={styles.warning}>
          XIRR приведён к году по короткому периоду ({days} дн.); это не прогноз.
        </p>
      ) : null}
    </div>
  );
}

function ReadinessBody({
  accounts,
  context,
  readiness,
  retry,
}: {
  accounts: Account[] | undefined;
  context: PerformanceContext;
  readiness: PerformanceReadiness;
  retry: () => void;
}) {
  const [showAll, setShowAll] = useState(false);
  const ordered = sortDiagnostics(readiness.diagnostics);
  const visible = showAll ? ordered : ordered.slice(0, 2);
  const evidence = readiness.evidence;
  const cashIds = evidence.cash_boundary_coverage.account_ids;
  const inKindIds = evidence.in_kind_boundary_coverage.account_ids;
  const catalogueIds = evidence.scope_membership.account_ids;
  const gapIds = evidence.scope_membership.missing_or_ambiguous_account_ids;
  const rowIds = [...new Set([...cashIds, ...inKindIds])].sort((a, b) => a - b);

  return (
    <div className={styles.summary}>
      <MetricPanel context={context} readiness={readiness} retry={retry} />

      <section aria-label="Состав расчёта" className={styles.composition}>
        <div className={styles.compositionBlock} data-testid="performance-composition-cash">
          <h3>Счета денежной проверки</h3>
          <p>
            {cashIds.length > 0
              ? cashIds.map((id) => accountName(accounts, id)).join("; ")
              : "Денежная проверка не требует счетов за этот интервал."}
          </p>
        </div>
        {inKindIds.length > 0 ? (
          <div className={styles.compositionBlock} data-testid="performance-composition-inkind">
            <h3>Счета неденежной проверки (отдельно)</h3>
            <p>{inKindIds.map((id) => accountName(accounts, id)).join("; ")}</p>
          </div>
        ) : null}
        <div className={styles.compositionBlock} data-testid="performance-composition-membership">
          <h3>Проверка истории участия</h3>
          <p>
            Проверяемый каталог:{" "}
            {catalogueIds.length > 0
              ? catalogueIds.map((id) => accountName(accounts, id)).join("; ")
              : "—"}
            {gapIds.length > 0
              ? ` Проблемные identity: ${gapIds.map((id) => accountName(accounts, id)).join("; ")}.`
              : " Проблем нет."}
          </p>
        </div>
      </section>

      {context.scope === "portfolio" && context.view === "accounts" ? (
        <section aria-label="По счетам">
          <h3>По счетам</h3>
          <p className={styles.periodLine}>
            У каждой строки свои availability/quality при том же интервале. Проценты строк не
            суммируются и не усредняются; доступные счета не делают итог портфеля доступным.
          </p>
          {rowIds.length === 0 ? (
            <p className={styles.periodLine}>Нет счетов для табличного разреза за этот интервал.</p>
          ) : (
            <div className={styles.accountsTableWrap}>
              <table className={styles.accountsTable} data-testid="performance-accounts-table">
                <thead>
                  <tr>
                    <th scope="col">Счёт</th>
                    <th scope="col">TWRR за период</th>
                    <th scope="col">XIRR, годовых</th>
                    <th scope="col">Состояние</th>
                  </tr>
                </thead>
                <tbody>
                  {rowIds.map((id) => (
                    <AccountPerformanceRow
                      accountId={id}
                      end={context.end}
                      key={id}
                      name={accountName(accounts, id)}
                      start={context.start}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      ) : null}

      <section aria-label="Диагностика">
        <h3>Диагностика</h3>
        {ordered.length === 0 ? (
          <p className={styles.periodLine}>Проверки пройдены: причин недоступности нет.</p>
        ) : (
          <>
            <ul className={styles.diagnosticList}>
              {visible.map((diagnostic) => {
                const copy = diagnosticCopy(diagnostic.key);
                const metrics = diagnostic.affected_metrics.join("/").toUpperCase();
                const refs: string[] = [];
                if (diagnostic.refs.dates.length > 0)
                  refs.push(`даты: ${diagnostic.refs.dates.join(", ")}`);
                if (diagnostic.refs.account_ids.length > 0)
                  refs.push(
                    `счета: ${diagnostic.refs.account_ids.map((id) => accountName(accounts, id)).join("; ")}`,
                  );
                if (diagnostic.refs.reporting_month_ids.length > 0)
                  refs.push(`отчёты: ${diagnostic.refs.reporting_month_ids.join(", ")}`);
                if (diagnostic.refs.external_flow_ids.length > 0)
                  refs.push(`потоки: ${diagnostic.refs.external_flow_ids.join(", ")}`);
                if (diagnostic.refs.legacy_flow_ids.length > 0)
                  refs.push(`legacy: ${diagnostic.refs.legacy_flow_ids.join(", ")}`);
                if (diagnostic.refs.movement_ids.length > 0)
                  refs.push(`перемещения: ${diagnostic.refs.movement_ids.join(", ")}`);
                if (diagnostic.refs.boundary_group_ids.length > 0)
                  refs.push(`группы: ${diagnostic.refs.boundary_group_ids.join(", ")}`);
                return (
                  <li className={styles.diagnosticItem} key={`${diagnostic.key}-${metrics}`}>
                    <strong>
                      {copy.title} · {metrics}
                    </strong>
                    <p>{copy.detail}</p>
                    {refs.length > 0 ? <p>Где проверить: {refs.join(" · ")}.</p> : null}
                    <p className={styles.capabilityNote}>
                      {capabilityCopy(diagnostic.action.capability)}
                    </p>
                    {hasWorkingAction(diagnostic.action.capability) &&
                    (diagnostic.key === "membership_history" ||
                      [
                        "review_external_flows",
                        "review_transfer",
                        "review_cash_history",
                        "review_in_kind_history",
                        "review_cash_binding",
                      ].includes(diagnostic.action.kind)) ? (
                      <p>
                        <Link
                          to={`${performanceDetailHref(context)}${diagnostic.refs.account_ids.length === 1 ? `&prepare_account=${diagnostic.refs.account_ids[0]}` : ""}&prepare_reason=${encodeURIComponent(diagnostic.key)}#performance-preparation`}
                        >
                          Проверить данные
                        </Link>
                      </p>
                    ) : null}
                    {diagnostic.key === "valuation_boundary" &&
                    (diagnostic.action.capability === "available" ||
                      diagnostic.action.capability === "requires_reopen") ? (
                      <p>
                        <a href="#performance-capture">Перейти к наблюдениям PRE/POST</a>
                        {diagnostic.action.capability === "requires_reopen"
                          ? " — понадобится явный reopen закрытого отчёта."
                          : null}
                      </p>
                    ) : null}
                    {hasWorkingAction(diagnostic.action.capability) ? (
                      <p className={styles.capabilityNote}>
                        Доступное действие — повторное чтение после проверки данных раздела.{" "}
                        <button className={styles.inlineButton} onClick={retry} type="button">
                          Перечитать
                        </button>
                      </p>
                    ) : null}
                  </li>
                );
              })}
            </ul>
            {ordered.length > 2 ? (
              <div className={styles.actionRow}>
                <button
                  className={styles.inlineButton}
                  onClick={() => setShowAll((value) => !value)}
                  type="button"
                >
                  {showAll ? "Скрыть полный список" : `Все причины (${ordered.length})`}
                </button>
              </div>
            ) : null}
            <details className={styles.technicalBox}>
              <summary>Технические детали</summary>
              <p>
                {ordered.map((d) => `${d.key} [${d.reason_codes.join(", ")}]`).join(" · ") ||
                  "причин нет"}
              </p>
            </details>
          </>
        )}
      </section>
    </div>
  );
}

/**
 * Leaf Performance detail (PUI-03). Mounted by the Integrator at
 * `/v2/capital/performance`; tests mount it directly with a MemoryRouter.
 * No client-side financial math; no class-return UI.
 */
export default function UiV2CapitalPerformanceDetail() {
  const [params, setParams] = useSearchParams();
  const [manualStart, setManualStart] = useState("");
  const [manualEnd, setManualEnd] = useState("");

  const accountsQuery = useQuery({
    queryKey: queryKeys.accounts,
    queryFn: ({ signal }) => listAccounts(signal),
    refetchOnWindowFocus: true,
  });
  const monthsQuery = useQuery({
    queryKey: queryKeys.months,
    queryFn: ({ signal }) => listMonths(signal),
    refetchOnWindowFocus: true,
  });

  const accounts = accountsQuery.data;
  const parsed = useMemo(
    () =>
      parsePerformanceContext(params, {
        accountExists: accounts ? (id) => accounts.some((a) => a.id === id) : undefined,
      }),
    [params, accounts],
  );

  const context = parsed.context;
  const contextError = parsed.error;

  const readinessQuery = useQuery({
    enabled: context !== null,
    queryKey: queryKeys.performanceReadiness(
      context?.start ?? null,
      context?.end ?? null,
      context?.scope ?? null,
      context?.accountId ?? null,
    ),
    queryFn: ({ signal }) =>
      getPerformanceReadiness(
        context?.start as string,
        context?.end as string,
        context?.scope ?? "portfolio",
        context?.accountId ?? null,
        signal,
      ),
    refetchOnWindowFocus: true,
  });

  const attributionQuery = useQuery({
    enabled: context !== null && context.scope === "portfolio",
    queryKey: queryKeys.performanceAttribution(context?.start ?? null, context?.end ?? null),
    queryFn: ({ signal }) =>
      getPerformanceAttribution(context?.start as string, context?.end as string, signal),
    refetchOnWindowFocus: true,
  });

  const closedSnapshots = useMemo(() => {
    const months = monthsQuery.data ?? [];
    return sortReportingMonths(months)
      .filter((month) => month.status === "closed")
      .map((month) => month.snapshot_date)
      .sort();
  }, [monthsQuery.data]);

  const applyParams = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(patch)) {
      if (value === null || value === "") next.delete(key);
      else next.set(key, value);
    }
    void setParams(next, { preventScrollReset: true });
  };

  const presets = useMemo(() => {
    if (context === null || closedSnapshots.length === 0) return [];
    return periodPresets(context.end, closedSnapshots);
  }, [context, closedSnapshots]);

  let content: React.ReactNode;
  if (contextError !== null) {
    content = (
      <UiV2Notice title="Контекст доходности не задан">
        {contextError.message}{" "}
        {contextError.code === "missing_interval" && closedSnapshots.length >= 2 ? (
          <>Можно выбрать даты вручную ниже.</>
        ) : null}
      </UiV2Notice>
    );
  } else if (context === null) {
    content = <UiV2Loading label="Проверяем контекст доходности…" />;
  } else if (context.view === "classes") {
    content = (
      <UiV2Notice title="Разрез по классам ещё не поддерживается">
        Это не нехватка данных.{" "}
        <button
          className={styles.inlineButton}
          onClick={() => applyParams({ view: "accounts" })}
          type="button"
        >
          Перейти к счетам
        </button>
      </UiV2Notice>
    );
  } else if (readinessQuery.isError) {
    content = (
      <UiV2Notice title="Проверка не завершилась" retry={() => void readinessQuery.refetch()}>
        Это не доказательство неполноты данных. Прошлый процент как текущий не показывается.
      </UiV2Notice>
    );
  } else if (!isQueryReady(readinessQuery)) {
    content = <UiV2Loading label="Проверяем готовность расчёта…" />;
  } else if (
    !isReadinessFresh(readinessQuery.data ?? null, {
      start: context.start,
      end: context.end,
      scope: context.scope,
      accountId: context.accountId,
    })
  ) {
    content = (
      <UiV2Notice
        title="Ответ не соответствует запросу"
        retry={() => void readinessQuery.refetch()}
      >
        Получен ответ для другого интервала или охвата; он скрыт. Повторите чтение.
      </UiV2Notice>
    );
  } else {
    const readiness = readinessQuery.data as PerformanceReadiness;
    const attribution = attributionQuery.data ?? null;
    const bridgeReady = context.scope !== "portfolio" || isQueryReady(attributionQuery);
    content = (
      <>
        <ReadinessBody
          accounts={accounts}
          context={context}
          readiness={readiness}
          retry={() => void readinessQuery.refetch()}
        />
        {context.scope === "portfolio" ? (
          <details className={styles.bridgeBox}>
            <summary>Изменение стоимости после внешних потоков (вторично)</summary>
            {!bridgeReady ? (
              <UiV2WidgetState />
            ) : attribution &&
              attribution.availability === "available" &&
              attribution.quality === "exact" &&
              attribution.value !== null ? (
              <>
                <p className={styles.metricValue} data-testid="performance-detail-bridge">
                  {moneyDelta(attribution.value)}
                </p>
                <p className={styles.metricNote}>
                  {VALUE_BRIDGE_LABEL} · {VALUE_BRIDGE_DISCLAIMER} Не прибыль и не доходность.
                </p>
              </>
            ) : (
              <p className={styles.metricNote}>
                {attribution
                  ? performanceAttributionUnavailableMessage(attribution.reason_codes)
                  : "Денежный мост недоступен."}
              </p>
            )}
          </details>
        ) : null}
      </>
    );
  }

  const scopeLabel =
    context?.scope === "account"
      ? `Счёт: ${context.accountId !== null ? accountName(accounts, context.accountId) : "—"}`
      : "Портфель";

  return (
    <UiV2Shell
      active="capital"
      header={
        <>
          <p className={pageStyles.eyebrow}>Капитал · Доходность</p>
          <h1>Доходность</h1>
          <p className={pageStyles.subtitle}>
            {context
              ? `${formatDate(context.start)} — ${formatDate(context.end)} · ${scopeLabel}`
              : "Выберите интервал и охват"}
          </p>
          <p className={styles.periodLine}>
            <Link to="/v2/capital">← Капитал</Link>
          </p>
        </>
      }
      v1ReturnPath="/analytics"
    >
      <section aria-label="Период и охват">
        <div className={styles.controls}>
          <label>
            Начальная дата снимка
            <input
              aria-label="Начальная дата снимка"
              onChange={(event) => setManualStart(event.target.value)}
              type="date"
              value={manualStart || context?.start || ""}
            />
          </label>
          <label>
            Конечная дата снимка
            <input
              aria-label="Конечная дата снимка"
              onChange={(event) => setManualEnd(event.target.value)}
              type="date"
              value={manualEnd || context?.end || ""}
            />
          </label>
          <label>
            Охват
            <select
              aria-label="Охват"
              onChange={(event) => {
                const scope = event.target.value === "account" ? "account" : "portfolio";
                applyParams({
                  scope,
                  account_id: scope === "portfolio" ? null : params.get("account_id"),
                });
              }}
              value={context?.scope ?? "portfolio"}
            >
              <option value="portfolio">Портфель</option>
              <option value="account">Счёт</option>
            </select>
          </label>
          <label>
            Счёт
            <select
              aria-label="Счёт"
              disabled={context?.scope !== "account"}
              onChange={(event) => applyParams({ account_id: event.target.value || null })}
              value={
                context?.accountId !== null && context?.accountId !== undefined
                  ? String(context.accountId)
                  : ""
              }
            >
              <option value="">Выберите счёт</option>
              {(accounts ?? []).map((account) => (
                <option key={account.id} value={account.id}>
                  {account.name}
                </option>
              ))}
            </select>
          </label>
          <div className={`${styles.actionRow} ${styles.controlsFull}`}>
            <button
              className={styles.inlineButton}
              onClick={() =>
                applyParams({
                  start: manualStart || context?.start || null,
                  end: manualEnd || context?.end || null,
                })
              }
              type="button"
            >
              Применить даты
            </button>
            {presets.map((preset) => (
              <button
                className={styles.inlineButton}
                disabled={!preset.available}
                key={preset.key}
                onClick={() => preset.target && applyParams({ start: preset.target })}
                title={preset.hint}
                type="button"
              >
                {preset.label}
              </button>
            ))}
          </div>
        </div>
        {context ? (
          <p className={styles.periodLine} data-testid="performance-detail-period">
            {formatDate(context.start)} — {formatDate(context.end)} · {scopeLabel} · единицы: п.п.
          </p>
        ) : null}
      </section>
      {content}
      {context !== null ? (
        <ObservedValuationCapture
          key={[
            context.start,
            context.end,
            context.scope,
            context.accountId ?? "portfolio",
            context.view,
          ].join(":")}
          context={context}
        />
      ) : null}
      {context && context.view === "accounts" ? (
        <PerformancePreparation accounts={accounts} context={context} />
      ) : null}
    </UiV2Shell>
  );
}
