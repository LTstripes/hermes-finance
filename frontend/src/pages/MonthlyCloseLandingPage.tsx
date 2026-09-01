import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";

import { formatApiError } from "../api/client";
import { listMonths } from "../api/months";
import { Badge, EmptyState, ErrorState, LoadingState, Panel } from "../components/ui";
import { formatMonth } from "../lib/format";
import { MONTH_STATUS_LABELS, labelOf } from "../lib/labels";
import { queryKeys } from "../queryClient";

export function MonthlyCloseLandingPage() {
  const monthsQuery = useQuery({
    queryKey: queryKeys.months,
    queryFn: ({ signal }) => listMonths(signal),
    select: (rows) =>
      [...rows].sort((left, right) => right.year - left.year || right.month - left.month),
  });

  return (
    <section className="stack-18 monthly-close">
      <header className="page-header">
        <p className="eyebrow">Закрытие месяца</p>
        <h1>Пошаговое закрытие</h1>
        <p className="page-header__description">
          Выбери точный отчётный месяц. Hermes покажет одно следующее действие по сохранённым
          фактам; открытие этой страницы ничего не обновляет и не записывает.
        </p>
      </header>

      <Panel label="Отчётные месяцы" title="Продолжить подготовку">
        {monthsQuery.isPending ? (
          <LoadingState description="Загружаем месяцы…" inline />
        ) : monthsQuery.error ? (
          <ErrorState
            description={formatApiError(monthsQuery.error)}
            inline
            title="Не удалось загрузить месяцы"
          />
        ) : !monthsQuery.data?.length ? (
          <EmptyState
            action={
              <Link className="btn btn--primary btn--sm" to="/months">
                Создать месяц
              </Link>
            }
            description="Сначала создай или клонируй отчётный месяц."
            inline
            title="Нет отчётных месяцев"
          />
        ) : (
          <div className="monthly-close__month-list">
            {monthsQuery.data.map((month) => (
              <Link
                className="monthly-close__month-link"
                key={month.id}
                to={`/months/${month.id}/close`}
              >
                <span>
                  <strong>{formatMonth(month.year, month.month)}</strong>
                  <small>{month.snapshot_date}</small>
                </span>
                <Badge tone={month.status === "closed" ? "closed" : "draft"}>
                  {labelOf(MONTH_STATUS_LABELS, month.status)}
                </Badge>
              </Link>
            ))}
          </div>
        )}
      </Panel>

      <Link className="btn btn--secondary" to="/months">
        Создать или клонировать месяц
      </Link>
    </section>
  );
}
