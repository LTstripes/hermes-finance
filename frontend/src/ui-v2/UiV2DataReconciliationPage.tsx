import { useMutation, useQuery } from "@tanstack/react-query";
import { type ReactNode, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router";

import { listAccounts } from "../api/accounts";
import {
  type BrokerReconciliationResponse,
  previewBrokerReconciliation,
} from "../api/brokerReconciliation";
import { formatApiError } from "../api/client";
import { listInstruments } from "../api/instruments";
import { listMonths } from "../api/months";
import { isGuidedCloseStepId, monthlyCloseReturnPath } from "../components/month-close/navigation";
import { queryKeys } from "../queryClient";
import { sortReportingMonths } from "./monthSelection";
import dataStyles from "./UiV2Data.module.css";
import {
  DiagnosticPanel,
  MappingPanel,
  MonthToolbar,
  ResultSummary,
  RowsPanel,
} from "./UiV2DataReconciliationPanels";
import {
  isComparisonUnavailable,
  type MappingValues,
  mappingFromValues,
  nonApplicableReason,
  reconciliationStatusLabel,
  resultStatusTone,
} from "./UiV2DataReconciliationParts";
import { DataMonthContext, resolveDataMonth, UiV2DataFrame } from "./UiV2DataShell";
import { isQueryReady, UiV2Loading, UiV2Notice } from "./UiV2StateBlocks";

export default function UiV2DataReconciliationPage() {
  const [params, setParams] = useSearchParams();
  const [result, setResult] = useState<BrokerReconciliationResponse | null>(null);
  const [accountValues, setAccountValues] = useState<MappingValues>({});
  const [instrumentValues, setInstrumentValues] = useState<MappingValues>({});
  const [mappingDirty, setMappingDirty] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const monthsQuery = useQuery({
    queryKey: queryKeys.months,
    queryFn: ({ signal }) => listMonths(signal),
    refetchOnWindowFocus: true,
  });
  const months = useMemo(() => sortReportingMonths(monthsQuery.data ?? []), [monthsQuery.data]);
  const monthsReady = isQueryReady(monthsQuery);
  const resolution = resolveDataMonth(params.getAll("month"), months, monthsReady);
  const monthId = resolution.kind === "ready" ? resolution.month.id : null;
  const monthIdRef = useRef(monthId);
  monthIdRef.current = monthId;

  const accountsQuery = useQuery({
    enabled: result !== null && !isComparisonUnavailable(result),
    queryKey: queryKeys.accounts,
    queryFn: ({ signal }) => listAccounts(signal),
  });
  const instrumentsQuery = useQuery({
    enabled: result !== null && !isComparisonUnavailable(result),
    queryKey: queryKeys.instruments,
    queryFn: ({ signal }) => listInstruments({}, signal),
  });
  const previewMutation = useMutation({
    mutationFn: ({ id, mapping }: { id: number; mapping: ReturnType<typeof mappingFromValues> }) =>
      previewBrokerReconciliation(id, mapping),
  });

  const requestedStepValues = params.getAll("step");
  const requestedStep =
    requestedStepValues.length === 1 && isGuidedCloseStepId(requestedStepValues[0])
      ? requestedStepValues[0]
      : null;
  const v1ReturnPath =
    resolution.kind === "ready"
      ? requestedStep
        ? monthlyCloseReturnPath({
            monthId: resolution.month.id,
            origin: "monthly-close",
            step: requestedStep,
          })
        : "/reconciliation"
      : "/reconciliation";

  function selectMonth(id: number) {
    const next = new URLSearchParams(params);
    next.set("month", String(id));
    setParams(next, { replace: true });
    setResult(null);
    setAccountValues({});
    setInstrumentValues({});
    setMappingDirty(false);
    setActionError(null);
  }

  async function runReconciliation() {
    if (monthId == null) return;
    const requestedMonthId = monthId;
    setActionError(null);
    try {
      const next = await previewMutation.mutateAsync({
        id: requestedMonthId,
        mapping: mappingFromValues(accountValues, instrumentValues),
      });
      // Reject mismatched identity or stale completion after month change.
      if (next.reporting_month_id !== requestedMonthId) {
        setActionError("Ответ сверки не соответствует выбранному месяцу.");
        return;
      }
      if (monthIdRef.current !== requestedMonthId) {
        return;
      }
      setResult(next);
      setMappingDirty(false);
      if (next.error_code && next.message) setActionError(next.message);
    } catch (error) {
      if (monthIdRef.current !== requestedMonthId) return;
      setActionError(formatApiError(error));
    }
  }

  let content: ReactNode;
  if (monthsQuery.isError) {
    content = (
      <UiV2Notice title="Не удалось загрузить отчёты" retry={() => void monthsQuery.refetch()}>
        Сверка скрыта, пока список месяцев не подтверждён.
      </UiV2Notice>
    );
  } else if (resolution.kind === "loading") {
    content = <UiV2Loading label="Проверяем доступные отчётные месяцы…" />;
  } else if (resolution.kind === "invalid") {
    content = (
      <UiV2Notice title="Некорректный параметр месяца">
        Выбор месяца должен содержать один положительный идентификатор. Сверка не запускается и
        числа не подставляются.
      </UiV2Notice>
    );
  } else if (resolution.kind === "missing") {
    content = (
      <UiV2Notice title="Месяц не найден">
        Запрошенный отчётный месяц отсутствует. Без тихой подмены на другой месяц.
      </UiV2Notice>
    );
  } else if (resolution.kind === "empty") {
    content = (
      <UiV2Notice title="Нет отчётных месяцев">
        Нечего сверять, пока не создан хотя бы один месяц.{" "}
        <Link to="/months">Открыть месяцы в текущем интерфейсе ↗</Link>
      </UiV2Notice>
    );
  } else {
    const month = resolution.month;
    const displayResult = result != null && result.reporting_month_id === month.id ? result : null;
    const unavailable = displayResult ? isComparisonUnavailable(displayResult) : false;
    const unavailableMessage = displayResult ? nonApplicableReason(displayResult) : null;
    content = (
      <>
        <DataMonthContext automatic={resolution.automatic} month={month}>
          <Link to="/reconciliation">В текущем интерфейсе ↗</Link>
        </DataMonthContext>
        <p className={dataStyles.noticeInline} data-testid="reconciliation-safety-note">
          Сверка только показывает различия и ничего не сохраняет. Данные брокера запрашиваются
          только после нажатия «Проверить снимок».
        </p>
        <MonthToolbar
          hasResult={displayResult !== null}
          months={months}
          onRun={() => void runReconciliation()}
          onSelect={selectMonth}
          running={previewMutation.isPending}
          selected={month}
        />
        {actionError ? (
          <div className={dataStyles.alert} role="alert">
            {actionError}
          </div>
        ) : null}
        {!displayResult ? (
          <section className={dataStyles.idlePanel} data-testid="reconciliation-idle">
            <h2>Сверка ещё не запрашивалась</h2>
            <p>Выберите месяц и нажмите «Проверить снимок», чтобы получить сравнение позиций.</p>
            <p className={dataStyles.familyActions}>
              <Link
                to={monthlyCloseReturnPath({
                  monthId: month.id,
                  origin: "monthly-close",
                  step: "broker_reconciliation",
                })}
              >
                Открыть шаг закрытия →
              </Link>
            </p>
          </section>
        ) : (
          <>
            <section className={dataStyles.resultPanel} data-testid="reconciliation-result">
              <div className={dataStyles.familyHeader}>
                <h2>Результат сверки</h2>
                <span
                  className={dataStyles.statusBadge}
                  data-tone={resultStatusTone(displayResult.status)}
                >
                  {reconciliationStatusLabel(displayResult.status)}
                </span>
              </div>
              <ResultSummary result={displayResult} />
              {unavailableMessage ? (
                <div className={dataStyles.gate} role="status" data-testid="reconciliation-gate">
                  <span className={dataStyles.statusBadge} data-tone="stale">
                    Сверка неприменима
                  </span>
                  <div>
                    <strong>Сверка остановлена из соображений безопасности</strong>
                    <p>{unavailableMessage}</p>
                  </div>
                </div>
              ) : null}
              {mappingDirty && !unavailable ? (
                <div className={dataStyles.noticeInline} role="status">
                  Сопоставление изменилось. Повтори явную проверку, чтобы увидеть результат для
                  нового сопоставления.
                </div>
              ) : null}
            </section>
            {!unavailable ? (
              <MappingPanel
                accounts={accountsQuery.data ?? []}
                accountValues={accountValues}
                instruments={instrumentsQuery.data ?? []}
                instrumentValues={instrumentValues}
                onAccountChange={(providerId, hermesId) => {
                  setAccountValues((current) => ({ ...current, [providerId]: hermesId }));
                  setMappingDirty(true);
                }}
                onInstrumentChange={(providerId, hermesId) => {
                  setInstrumentValues((current) => ({ ...current, [providerId]: hermesId }));
                  setMappingDirty(true);
                }}
                result={displayResult}
              />
            ) : null}
            <RowsPanel result={displayResult} />
            <DiagnosticPanel result={displayResult} />
            <p className={dataStyles.familyActions}>
              <Link
                to={monthlyCloseReturnPath({
                  monthId: month.id,
                  origin: "monthly-close",
                  step: "broker_reconciliation",
                })}
              >
                Открыть шаг закрытия →
              </Link>
            </p>
          </>
        )}
      </>
    );
  }

  return (
    <UiV2DataFrame
      active="reconciliation"
      busy={!monthsReady}
      monthId={monthId ?? undefined}
      subtitle="Сравнение позиций Hermes с данными брокера за выбранный месяц."
      title="Сверка портфеля"
      v1ReturnPath={v1ReturnPath}
    >
      {content}
    </UiV2DataFrame>
  );
}
