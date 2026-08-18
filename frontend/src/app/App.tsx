import { BrowserRouter, Route, Routes } from "react-router";

import { AppLayout } from "../components/AppLayout";
import { AccountsPage } from "../pages/AccountsPage";
import { AnalyticsPage } from "../pages/AnalyticsPage";
import { DashboardPage } from "../pages/DashboardPage";
import { ExportPage } from "../pages/ExportPage";
import { GoalsPage } from "../pages/GoalsPage";
import { MonthDetailPage } from "../pages/MonthDetailPage";
import { MonthsPage } from "../pages/MonthsPage";
import { PayoutsPage } from "../pages/PayoutsPage";
import { SettingsPage } from "../pages/SettingsPage";

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppLayout />}>
          <Route index element={<DashboardPage />} />
          <Route path="analytics" element={<AnalyticsPage />} />
          <Route path="months" element={<MonthsPage />} />
          <Route path="months/:monthId" element={<MonthDetailPage />} />
          <Route path="payouts" element={<PayoutsPage />} />
          <Route path="accounts" element={<AccountsPage />} />
          <Route path="goals" element={<GoalsPage />} />
          <Route path="export" element={<ExportPage />} />
          <Route path="settings" element={<SettingsPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
