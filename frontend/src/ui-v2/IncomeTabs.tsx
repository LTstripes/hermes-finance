import { UiV2Tabs } from "./UiV2Tabs";

const sections = [
  ["overview", "Обзор", "/v2/income"],
  ["payouts", "Выплаты", "/v2/data/payouts"],
  ["goals", "Цели", "/v2/income/goals"],
  ["tax", "Налоги и ИИС", "/v2/income/tax-iis"],
  ["scenarios", "Сценарии", "/v2/income/scenario-lab"],
] as const;

export function IncomeTabs({ active, monthId }: { active: string; monthId?: number | null }) {
  return (
    <UiV2Tabs
      label="Разделы дохода и планов"
      tabs={sections.map(([id, label, path]) => ({
        label,
        to: `${path}${monthId == null ? "" : `?month=${monthId}`}`,
        active: id === active,
      }))}
    />
  );
}
