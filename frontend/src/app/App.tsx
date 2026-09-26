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
import { MonthlyCloseLandingPage } from "../pages/MonthlyCloseLandingPage";
import { MonthlyCloseWorkflowPage } from "../pages/MonthlyCloseWorkflowPage";
import { PayoutsPage } from "../pages/PayoutsPage";
import { ReconciliationCenterPage } from "../pages/ReconciliationCenterPage";
import { RiskAllocationPage } from "../pages/RiskAllocationPage";
import { ScenarioLabPage } from "../pages/ScenarioLabPage";
import { SettingsPage } from "../pages/SettingsPage";
import { TaxIisPlannerPage } from "../pages/TaxIisPlannerPage";
import { createQueryClient } from "../queryClient";
import {
  UiV2CapitalEntry,
  UiV2CloseEntry,
  UiV2DataAppEntry,
  UiV2DataCatalogsEntry,
  UiV2DataFilesEntry,
  UiV2DataReconciliationEntry,
  UiV2DataSourcesEntry,
  UiV2Entry,
  UiV2IncomeEntry,
  UiV2ReportEntry,
  UiV2ReportsEntry,
} from "../ui-v2/UiV2Entry";
import UiV2ScenarioLabPage from "../ui-v2/UiV2ScenarioLabPage";

type AppProps = {
  queryClient?: QueryClient;
};

export function App({ queryClient: providedQueryClient }: AppProps = {}) {
  const [queryClient] = useState(() => providedQueryClient ?? createQueryClient());

  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<UiV2Entry />} />
          <Route path="v2" element={<UiV2Entry />} />
          <Route path="v2/capital" element={<UiV2CapitalEntry />} />
          <Route path="v2/reports" element={<UiV2ReportsEntry />} />
          <Route path="v2/reports/:monthId" element={<UiV2ReportEntry />} />
          <Route path="v2/close" element={<UiV2CloseEntry />} />
          <Route path="v2/data" element={<UiV2DataSourcesEntry />} />
          <Route path="v2/data/reconciliation" element={<UiV2DataReconciliationEntry />} />
          <Route path="v2/data/catalogs" element={<UiV2DataCatalogsEntry />} />
          <Route path="v2/data/files" element={<UiV2DataFilesEntry />} />
          <Route path="v2/data/app" element={<UiV2DataAppEntry />} />
          <Route path="v2/income" element={<UiV2IncomeEntry />} />
          <Route path="v2/income/scenario-lab" element={<UiV2ScenarioLabPage />} />
          <Route element={<AppLayout />}>
            <Route path="v1" element={<DashboardPage />} />
            <Route path="analytics" element={<AnalyticsPage />} />
            <Route path="analytics/risk-allocation" element={<RiskAllocationPage />} />
            <Route path="freshness" element={<FreshnessProvenancePage />} />
            <Route path="reconciliation" element={<ReconciliationCenterPage />} />
            <Route path="months" element={<MonthsPage />} />
            <Route path="monthly-close" element={<MonthlyCloseLandingPage />} />
            <Route path="months/:monthId/close" element={<MonthlyCloseWorkflowPage />} />
            <Route path="months/:monthId" element={<MonthDetailPage />} />
            <Route path="payouts" element={<PayoutsPage />} />
            <Route path="accounts" element={<AccountsPage />} />
            <Route path="goals" element={<GoalsPage />} />
            <Route path="tax-iis-planner" element={<TaxIisPlannerPage />} />
            <Route path="scenario-lab" element={<ScenarioLabPage />} />
            <Route path="export" element={<ExportPage />} />
            <Route path="settings" element={<SettingsPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
