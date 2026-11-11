import { useQuery } from "@tanstack/react-query";
import { Link, useLocation } from "react-router";

import { getMonthWorkingStatus } from "../api/months";
import { formatDate, formatMonth } from "../lib/format";
import { queryKeys } from "../queryClient";
import { monthWorkspacePath } from "./monthSelection";
import styles from "./UiV2Page.module.css";

/**
 * Sidebar entry to the working month. It reads only the narrow working-status
 * endpoint: the close workflow is too heavy to load on every page (#1067).
 * Without a loaded month it stays a plain link to the month workspace.
 */
export function UiV2MonthPlate() {
  const { pathname, search } = useLocation();
  const statusQuery = useQuery({
    queryKey: queryKeys.monthWorkingStatus,
    queryFn: ({ signal }) => getMonthWorkingStatus(signal),
  });
  const status = statusQuery.data;
  const requestedMonths = new URLSearchParams(search).getAll("month");
  const selected = requestedMonths.length === 1 ? requestedMonths[0] : null;
  const routeMonth = /^\/v2\/(?:data\/months|reports)\/(\d+)$/.exec(pathname)?.[1];
  const onMonth = pathname === "/v2/close" || routeMonth !== undefined;
  const shownMonth = routeMonth ?? selected;
  const ariaCurrent =
    onMonth &&
    status?.month &&
    (shownMonth === String(status.month.id) ||
      (pathname === "/v2/close" && requestedMonths.length === 0)) &&
    (routeMonth !== undefined || requestedMonths.length <= 1)
      ? "page"
      : undefined;
  if (!status?.month) {
    return (
      <Link aria-current={ariaCurrent} className={styles.monthPlate} to="/v2/close">
        <strong>Месяц</strong>
      </Link>
    );
  }
  const { month } = status;
  const closed = month.status === "closed";
  const title = formatMonth(month.year, month.month);
  const state = closed
    ? `Закрыт · снимок ${formatDate(month.snapshot_date)}`
    : `${status.completed_steps} из ${status.total_steps} шагов`;
  return (
    <Link
      aria-current={ariaCurrent}
      aria-label={`Рабочий месяц: ${title}, ${state}`}
      className={styles.monthPlate}
      to={monthWorkspacePath(month.id)}
    >
      <span className={styles.monthPlateLabel}>Рабочий месяц</span>
      <strong>{title}</strong>
      <span className={styles.monthPlateStatus} data-state={closed ? "closed" : "progress"}>
        {state}
      </span>
    </Link>
  );
}
