import { useLocation, useSearchParams } from "react-router";
import { UiV2Tabs } from "../UiV2Tabs";
import { spendingPath, validMonth } from "./common";

export function ExpenseTabs({ month: selectedMonth }: { month?: string } = {}) {
  const { pathname } = useLocation();
  const [params] = useSearchParams();
  const month = selectedMonth ?? params.get("month");
  const query = month && validMonth(month) ? `?month=${month}` : "";
  const sections = [
    ["Обзор", spendingPath],
    ["Подушка", `${spendingPath}/reserve`],
    ["Категории и правила", `${spendingPath}/rules`],
  ] as const;
  return (
    <UiV2Tabs
      label="Раздел расходов"
      inheritMonth={false}
      tabs={sections.map(([label, path]) => ({
        label,
        to: `${path}${query}`,
        active: pathname.replace(/\/$/, "") === path,
      }))}
    />
  );
}
