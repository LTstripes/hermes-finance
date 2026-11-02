import { useQuery } from "@tanstack/react-query";
import { Link, Navigate, useLocation, useSearchParams } from "react-router";
import { listMonths } from "../../api/months";
import { queryKeys } from "../../queryClient";
import { UiV2Shell } from "../UiV2Shell";
import { UiV2Loading, UiV2Notice, isQueryReady } from "../UiV2StateBlocks";
import { canonicalId } from "./navigation";
import { legacyMonthPeriod } from "./ReturnsLegacyRedirect";

/** Resolve an explicit report ID without substituting the latest report. Read only. */
export function ReturnsMonthRedirect() {
  const [params] = useSearchParams();
  const { hash } = useLocation();
  const id = params.getAll("month").length === 1 ? canonicalId(params.get("month")) : null;
  const months = useQuery({
    queryKey: queryKeys.months,
    queryFn: ({ signal }) => listMonths(signal),
    enabled: id !== null,
  });
  const month = isQueryReady(months)
    ? months.data?.find((m) => m.id === id && m.status === "closed")
    : null;
  const period = month
    ? legacyMonthPeriod(`${month.year}-${String(month.month).padStart(2, "0")}`)
    : null;
  if (period) {
    const next = new URLSearchParams(params);
    next.set("start", period.start);
    next.set("end", period.end);
    if (!next.has("scope")) next.set("scope", "portfolio");
    return <Navigate replace to={`/v2/returns/account?${next}${hash}`} />;
  }
  return (
    <UiV2Shell active="returns" header={<h1>Доходность</h1>}>
      {id !== null && !months.isError && !isQueryReady(months) ? (
        <UiV2Loading label="Проверяем выбранный месяц…" />
      ) : (
        <UiV2Notice
          title={months.isError ? "Не удалось проверить отчёты" : "Закрытый отчёт не найден"}
        >
          Выбери другой период в разделе <Link to="/v2/returns">Доходность</Link>.
        </UiV2Notice>
      )}
    </UiV2Shell>
  );
}
