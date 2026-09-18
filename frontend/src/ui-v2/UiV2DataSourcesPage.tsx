import { useQuery } from "@tanstack/react-query";
import { useMemo, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router";

import { getFreshnessProvenance } from "../api/freshnessProvenance";
import { listMonths } from "../api/months";
import { listProviderCapabilities } from "../api/providerCapabilities";
import { isGuidedCloseStepId, monthlyCloseReturnPath } from "../components/month-close/navigation";
import { queryKeys } from "../queryClient";
import { DataMonthContext, resolveDataMonth, UiV2DataFrame } from "./UiV2DataShell";
import dataStyles from "./UiV2Data.module.css";
import { CapabilitiesDisclosure, FreshnessBody, MonthToolbar } from "./UiV2DataFreshnessPanels";
import { isQueryReady, UiV2Loading, UiV2Notice } from "./UiV2StateBlocks";
import { sortReportingMonths } from "./monthSelection";

export default function UiV2DataSourcesPage() {
  const [params, setParams] = useSearchParams();
  const monthsQuery = useQuery({
    queryKey: queryKeys.months,
    queryFn: ({ signal }) => listMonths(signal),
    refetchOnWindowFocus: true,
  });
  const months = useMemo(() => sortReportingMonths(monthsQuery.data ?? []), [monthsQuery.data]);
  const monthsReady = isQueryReady(monthsQuery);
  const resolution = resolveDataMonth(params.getAll("month"), months, monthsReady);

  const monthId = resolution.kind === "ready" ? resolution.month.id : null;
  const freshnessQuery = useQuery({
    enabled: monthId !== null,
    queryKey: queryKeys.freshnessProvenance(monthId),
    queryFn: ({ signal }) => getFreshnessProvenance(monthId as number, signal),
    refetchOnWindowFocus: true,
  });
  const capabilitiesQuery = useQuery({
    queryKey: queryKeys.providerCapabilities,
    queryFn: ({ signal }) => listProviderCapabilities(signal),
    refetchOnWindowFocus: true,
  });

  // Exact reporting_month.id only — year/month coincidence is not identity.
  const summaryIdentityOk =
    freshnessQuery.data != null &&
    monthId !== null &&
    freshnessQuery.data.reporting_month.id === monthId;
  const freshnessReady = isQueryReady(freshnessQuery) && summaryIdentityOk;
  const capabilitiesReady = isQueryReady(capabilitiesQuery);

  const requestedStepValues = params.getAll("step");
  const requestedStep =
    requestedStepValues.length === 1 && isGuidedCloseStepId(requestedStepValues[0])
      ? requestedStepValues[0]
      : null;
  const v1ReturnPath =
    resolution.kind === "ready"
      ? requestedStep
        ? monthlyCloseReturnPath({ monthId: resolution.month.id, step: requestedStep })
        : "/freshness"
      : "/freshness";

  function selectMonth(id: number) {
    const next = new URLSearchParams(params);
    next.set("month", String(id));
    setParams(next, { replace: true });
  }

  let content: ReactNode;
  if (monthsQuery.isError) {
    content = (
      <UiV2Notice title="Не удалось загрузить отчёты" retry={() => void monthsQuery.refetch()}>
        Диагностика скрыта, пока список месяцев не подтверждён.
      </UiV2Notice>
    );
  } else if (resolution.kind === "loading") {
    content = <UiV2Loading label="Проверяем доступные отчётные месяцы…" />;
  } else if (resolution.kind === "invalid") {
    content = (
      <UiV2Notice title="Некорректный параметр месяца">
        Явный <code>?month=</code> должен быть одним положительным целым ID. Числа не показаны — без
        тихой подмены.
      </UiV2Notice>
    );
  } else if (resolution.kind === "missing") {
    content = (
      <UiV2Notice title="Месяц не найден">
        Запрошенный отчётный месяц отсутствует. Числа не показаны — без тихой подмены на другой
        месяц.
      </UiV2Notice>
    );
  } else if (resolution.kind === "empty") {
    content = (
      <UiV2Notice title="Нет отчётных месяцев">
        Нечего диагностировать, пока не создан хотя бы один месяц.{" "}
        <Link to="/months">Открыть месяцы в текущем интерфейсе ↗</Link>
      </UiV2Notice>
    );
  } else {
    const month = resolution.month;
    content = (
      <>
        <DataMonthContext automatic={resolution.automatic} month={month}>
          <Link to="/freshness">В текущем интерфейсе ↗</Link>
        </DataMonthContext>
        <div className={dataStyles.badgeRow}>
          <span className={dataStyles.readOnlyBadge}>Только чтение</span>
          <span className={dataStyles.muted}>
            Без запроса к провайдеру · без универсальной оценки актуальности
          </span>
        </div>
        <MonthToolbar months={months} onSelect={selectMonth} selected={month} />
        {!freshnessReady ? (
          freshnessQuery.isError ? (
            <UiV2Notice
              title="Не удалось загрузить актуальность"
              retry={() => void freshnessQuery.refetch()}
            >
              Семьи источников скрыты, пока DTO не подтверждён для выбранного месяца.
            </UiV2Notice>
          ) : isQueryReady(freshnessQuery) && freshnessQuery.data != null && !summaryIdentityOk ? (
            <UiV2Notice title="Ответ не соответствует выбранному месяцу">
              Показатели скрыты: DTO относится к другому отчётному месяцу. Без тихой подмены.
            </UiV2Notice>
          ) : (
            <UiV2Loading label="Читаем сохранённую актуальность и происхождение…" />
          )
        ) : freshnessQuery.data ? (
          <FreshnessBody monthId={month.id} summary={freshnessQuery.data} />
        ) : (
          <UiV2Loading label="Читаем сохранённую актуальность и происхождение…" />
        )}
        <CapabilitiesDisclosure
          failed={capabilitiesQuery.isError}
          profiles={capabilitiesReady ? capabilitiesQuery.data : undefined}
          ready={capabilitiesReady}
          retry={() => void capabilitiesQuery.refetch()}
        />
        <p className={dataStyles.muted} style={{ marginTop: 14 }}>
          Импорт и apply выполняются только в закрытии месяца. Здесь — состояние и handoff.{" "}
          <Link to={monthlyCloseReturnPath({ monthId: month.id, step: "readiness" })}>
            Открыть закрытие месяца →
          </Link>
        </p>
      </>
    );
  }

  return (
    <UiV2DataFrame
      active="sources"
      busy={!monthsReady}
      monthId={monthId ?? undefined}
      subtitle="Откуда числа, чем подтверждены и насколько актуальны сохранённые данные."
      title="Источники и актуальность"
      v1ReturnPath={v1ReturnPath}
    >
      {content}
    </UiV2DataFrame>
  );
}
