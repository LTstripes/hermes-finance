import { BrowserRouter, Route, Routes } from "react-router";

import { AppLayout } from "../components/AppLayout";
import { AccountsPage } from "../pages/AccountsPage";
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
          <Route path="accounts" element={<AccountsPage />} />
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
