import { BrowserRouter, Route, Routes } from "react-router";

import { AppLayout } from "../components/AppLayout";
import { DashboardPage } from "../pages/DashboardPage";
import { MonthDetailPage } from "../pages/MonthDetailPage";
import { MonthsPage } from "../pages/MonthsPage";
import { PlaceholderPage } from "../pages/PlaceholderPage";

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppLayout />}>
          <Route index element={<DashboardPage />} />
          <Route path="months" element={<MonthsPage />} />
          <Route path="months/:monthId" element={<MonthDetailPage />} />
          <Route
            path="accounts"
            element={
              <PlaceholderPage
                description="Справочник счетов и инструментов — после базового month editor."
                eyebrow="Данные"
                phaseHint="E later"
                title="Счета и инструменты"
              />
            }
          />
          <Route
            path="goals"
            element={
              <PlaceholderPage
                description="Цели капитала. Backend gap: нет /api/goals — только визуальный stub."
                eyebrow="Данные"
                gaps={["API /api/goals отсутствует"]}
                phaseHint="E later · API gap"
                title="Цели"
              />
            }
          />
          <Route
            path="export"
            element={
              <PlaceholderPage
                description="Экспорт markdown/json и локальные backup/restore."
                eyebrow="Система"
                phaseHint="E later"
                title="Экспорт и бэкапы"
              />
            }
          />
          <Route
            path="settings"
            element={
              <PlaceholderPage
                description="Локальные настройки приложения. Gaps: tax-brackets, cash endpoints — не в scope E02."
                eyebrow="Система"
                gaps={["API /api/tax-brackets", "API cash endpoints"]}
                phaseHint="E later · API gaps"
                title="Настройки"
              />
            }
          />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
