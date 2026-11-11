const TITLES: Record<string, string> = {
  "/": "Мои финансы",
  "/v2": "Мои финансы",
  "/v2/capital": "Капитал",
  "/v2/capital/allocation": "Распределение капитала",
  "/v2/returns": "Доходность",
  "/v2/returns/account": "Доходность по месяцам",
  "/v2/reports": "Отчётные месяцы",
  "/v2/close": "Месяц",
  "/v2/data": "Источники данных",
  "/v2/data/overview": "Настройки",
  "/v2/data/source-intake": "Загрузка выписок",
  "/v2/data/months": "Отчётные месяцы",
  "/v2/data/payouts": "Выплаты",
  "/v2/data/catalogs": "Справочники",
  "/v2/data/files": "Экспорт и копии",
  "/v2/data/app": "Приложение",
  "/v2/income": "Доход и планы",
  "/v2/income/goals": "Цели",
  "/v2/income/tax-iis": "Налоги и ИИС",
  "/v2/income/scenario-lab": "Сценарии",
};

export function screenTitle(pathname: string) {
  if (pathname.startsWith("/v2/returns/instrument/")) return "Инструмент";
  if (pathname.startsWith("/v2/reports/")) return "Отчёт месяца";
  if (pathname.startsWith("/v2/data/months/")) return "Редактор месяца";
  return TITLES[pathname] ?? "Мои финансы";
}
