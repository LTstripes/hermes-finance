import { type QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { BrowserRouter, Route, Routes } from "react-router";

import { AppLayout } from "../components/AppLayout";
import { AccountsPage } from "../pages/AccountsPage";
import { AnalyticsPage } from "../pages/AnalyticsPage";
import { DashboardPage } from "../pages/DashboardPage";
import { ExportPage } from "../pages/ExportPage";
import { FreshnessProvenancePage } from "../pages/FreshnessProvenancePage";
import { GoalsPage } from "../pages/GoalsPage";
import { MonthDetailPage } from "../pages/MonthDetailPage";
import { MonthsPage } from "../pages/MonthsPage";
import { PayoutsPage } from "../pages/PayoutsPage";
import { ReconciliationCenterPage } from "../pages/ReconciliationCenterPage";
import { RiskAllocationPage } from "../pages/RiskAllocationPage";
import { SettingsPage } from "../pages/SettingsPage";
import { TaxIisPlannerPage } from "../pages/TaxIisPlannerPage";
import { createQueryClient } from "../queryClient";

type AppProps = {
  queryClient?: QueryClient;
};

export function App({ queryClient: providedQueryClient }: AppProps = {}) {
  const [queryClient] = useState(() => providedQueryClient ?? createQueryClient());

  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<AppLayout />}>
            <Route index element={<DashboardPage />} />
            <Route path="analytics" element={<AnalyticsPage />} />
            <Route path="analytics/risk-allocation" element={<RiskAllocationPage />} />
            <Route path="freshness" element={<FreshnessProvenancePage />} />
            <Route path="reconciliation" element={<ReconciliationCenterPage />} />
            <Route path="months" element={<MonthsPage />} />
            <Route path="months/:monthId" element={<MonthDetailPage />} />
            <Route path="payouts" element={<PayoutsPage />} />
            <Route path="accounts" element={<AccountsPage />} />
            <Route path="goals" element={<GoalsPage />} />
            <Route path="tax-iis-planner" element={<TaxIisPlannerPage />} />
            <Route path="export" element={<ExportPage />} />
            <Route path="settings" element={<SettingsPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
