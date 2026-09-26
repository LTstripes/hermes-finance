import { useCallback } from "react";
import { useSearchParams } from "react-router";

import { GoalsPage } from "../pages/GoalsPage";

function parseMonthId(value: string): number | null {
  if (!/^\d+$/.test(value)) return null;
  const monthId = Number(value);
  return Number.isSafeInteger(monthId) && monthId > 0 ? monthId : null;
}

export default function UiV2GoalsPage() {
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

  const updateMonthContext = useCallback(
    (monthId: number, options?: { replace?: boolean }) => {
      const next = new URLSearchParams(searchParams);
      next.set("month", String(monthId));
      if (options?.replace) setSearchParams(next, { replace: true });
      else setSearchParams(next);
    },
    [searchParams, setSearchParams],
  );

  return (
    <GoalsPage
      incomeReturnTo={incomeReturnTo}
      monthContext={monthContext}
      monthContextError={monthContextError}
      onMonthContextChange={updateMonthContext}
      presentation="v2"
    />
  );
}
