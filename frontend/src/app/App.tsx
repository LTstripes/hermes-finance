import { BrowserRouter, Route, Routes } from "react-router";

import { AppLayout } from "../components/AppLayout";
import { DashboardPage } from "../pages/DashboardPage";
import { ExportPage } from "../pages/ExportPage";
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
                phaseHint="E-фаза · позже"
                title="Счета и инструменты"
              />
            }
          />
          <Route
            path="goals"
            element={
              <PlaceholderPage
                description="Цели капитала. Backend пока не предоставляет /api/goals — здесь только визуальная заглушка."
                eyebrow="Данные"
                gaps={["API /api/goals отсутствует"]}
                phaseHint="E-фаза · ограничение API"
                title="Цели"
              />
            }
          />
          <Route path="export" element={<ExportPage />} />
          <Route
            path="settings"
            element={
              <PlaceholderPage
                description="Локальные настройки приложения. Пока не подключены налоговые ставки и отдельные API денежных средств."
                eyebrow="Система"
                gaps={["API /api/tax-brackets", "API денежных средств"]}
                phaseHint="E-фаза · ограничения API"
                title="Настройки"
              />
            }
          />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
