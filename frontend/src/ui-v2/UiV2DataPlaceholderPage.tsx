import { useMemo } from "react";
import { Link, useSearchParams } from "react-router";

import { useQuery } from "@tanstack/react-query";

import { listMonths } from "../api/months";
import { queryKeys } from "../queryClient";
import { type DataAppSection, sortReportingMonths } from "./monthSelection";
import { DataMonthContext, resolveDataMonth, UiV2DataFrame } from "./UiV2DataShell";
import dataStyles from "./UiV2Data.module.css";
import { isQueryReady, UiV2Loading, UiV2Notice } from "./UiV2StateBlocks";

const COPY: Record<
  Exclude<
    DataAppSection,
    "sources" | "reconciliation" | "months" | "alfa-baseline" | "payouts" | "source-intake"
  >,
  { title: string; subtitle: string; escapes: Array<{ label: string; to: string }> }
> = {
  catalogs: {
    title: "Справочники и сопоставления",
    subtitle:
      "Счета, инструменты и постоянные сопоставления. Этот блок появится в следующем срезе.",
    escapes: [
      { label: "Счета и инструменты →", to: "/v2/data/catalogs" },
      { label: "Сопоставления счетов брокера →", to: "/v2/data/catalogs?tab=mappings" },
    ],
  },
  files: {
    title: "Файлы",
    subtitle: "Экспорт и локальные копии базы. Этот блок появится в следующем срезе.",
    escapes: [{ label: "Экспорт и резервные копии →", to: "/v2/data/files" }],
  },
  app: {
    title: "Приложение",
    subtitle:
      "Настройки, налоговые шкалы и диагностика среды. Этот блок появится в следующем срезе.",
    escapes: [{ label: "Настройки →", to: "/v2/data/app" }],
  },
};

export default function UiV2DataPlaceholderPage({
  section,
}: {
  section: Exclude<
    DataAppSection,
    "sources" | "reconciliation" | "months" | "alfa-baseline" | "payouts" | "source-intake"
  >;
}) {
  const copy = COPY[section];
  const [params] = useSearchParams();
  const monthsQuery = useQuery({
    queryKey: queryKeys.months,
    queryFn: ({ signal }) => listMonths(signal),
  });
  const months = useMemo(() => sortReportingMonths(monthsQuery.data ?? []), [monthsQuery.data]);
  const monthsReady = isQueryReady(monthsQuery);
  const resolution = resolveDataMonth(params.getAll("month"), months, monthsReady);
  const monthId = resolution.kind === "ready" ? resolution.month.id : undefined;

  return (
    <UiV2DataFrame
      active={section}
      busy={!monthsReady}
      monthId={monthId}
      subtitle={copy.subtitle}
      title={copy.title}
    >
      {resolution.kind === "loading" ? (
        <UiV2Loading label="Проверяем доступные отчётные месяцы…" />
      ) : resolution.kind === "ready" ? (
        <DataMonthContext automatic={resolution.automatic} month={resolution.month} />
      ) : resolution.kind === "invalid" || resolution.kind === "missing" ? (
        <UiV2Notice title="Параметр месяца не принят">
          Явный месяц должен существовать ровно один раз. Без тихой подмены.
        </UiV2Notice>
      ) : null}
      <section className={dataStyles.resultPanel} data-testid={`data-placeholder-${section}`}>
        <div className={dataStyles.badgeRow}>
          <span className={`${dataStyles.modeBadge} ${dataStyles.modeBadgeMutate}`}>
            Изменяет данные · позже
          </span>
        </div>
        <p>
          Нативный экран ещё не перенесён. Пока пользуйся текущим интерфейсом — ссылки ниже явно
          помечены.
        </p>
        <div className={dataStyles.escapeList}>
          {copy.escapes.map((item) => (
            <Link key={item.to} to={item.to}>
              {item.label}
            </Link>
          ))}
        </div>
      </section>
    </UiV2DataFrame>
  );
}
