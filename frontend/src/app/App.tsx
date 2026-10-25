import { type QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { BrowserRouter, Navigate, Route, Routes, useParams } from "react-router";

import { createQueryClient } from "../queryClient";
import BrokerStatementReturnPage from "../ui-v2/BrokerStatementReturnPage";
import {
  UiV2AlfaBaselineEntry,
  UiV2CapitalAllocationEntry,
  UiV2CapitalEntry,
  UiV2CapitalPerformanceEntry,
  UiV2CloseEntry,
  UiV2DataAppEntry,
  UiV2DataCatalogsEntry,
  UiV2DataFilesEntry,
  UiV2DataReconciliationEntry,
  UiV2DataSourcesEntry,
  UiV2Entry,
  UiV2GoalsEntry,
  UiV2IncomeEntry,
  UiV2MonthEditorEntry,
  UiV2MonthlyResultEntry,
  UiV2MonthlyReturnsEntry,
  UiV2ReturnsEntry,
  UiV2MonthsEntry,
  UiV2PayoutForecastEntry,
  UiV2ReportEntry,
  UiV2ReportsEntry,
  UiV2ScenarioLabEntry,
  UiV2SourceIntakeEntry,
  UiV2TaxIisEntry,
} from "../ui-v2/UiV2Entry";

type AppProps = {
  queryClient?: QueryClient;
};

function MonthRedirect() {
  const { monthId } = useParams();
  return <Navigate replace to={`/v2/data/months/${monthId}`} />;
}

function MonthCloseRedirect() {
  const { monthId } = useParams();
  return <Navigate replace to={`/v2/close?month=${monthId}`} />;
}

export function App({ queryClient: providedQueryClient }: AppProps = {}) {
  const [queryClient] = useState(() => providedQueryClient ?? createQueryClient());

  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<UiV2Entry />} />
          <Route path="v2" element={<UiV2Entry />} />
          <Route path="v2/capital" element={<UiV2CapitalEntry />} />
          <Route path="v2/capital/allocation" element={<UiV2CapitalAllocationEntry />} />
          <Route path="v2/capital/monthly-result" element={<UiV2MonthlyResultEntry />} />
          <Route path="v2/capital/performance" element={<UiV2CapitalPerformanceEntry />} />
          <Route path="v2/capital/monthly-returns" element={<UiV2MonthlyReturnsEntry />} />
          <Route path="v2/returns" element={<UiV2ReturnsEntry />} />
          <Route path="v2/capital/statement-return" element={<BrokerStatementReturnPage />} />
          <Route path="v2/reports" element={<UiV2ReportsEntry />} />
          <Route path="v2/reports/:monthId" element={<UiV2ReportEntry />} />
          <Route path="v2/close" element={<UiV2CloseEntry />} />
          <Route path="v2/data" element={<UiV2DataSourcesEntry />} />
          <Route path="v2/data/source-intake" element={<UiV2SourceIntakeEntry />} />
          <Route path="v2/data/months" element={<UiV2MonthsEntry />} />
          <Route path="v2/data/months/:monthId" element={<UiV2MonthEditorEntry />} />
          <Route path="v2/data/reconciliation" element={<UiV2DataReconciliationEntry />} />
          <Route path="v2/data/alfa-baseline" element={<UiV2AlfaBaselineEntry />} />
          <Route path="v2/data/payouts" element={<UiV2PayoutForecastEntry />} />
          <Route path="v2/data/catalogs" element={<UiV2DataCatalogsEntry />} />
          <Route path="v2/data/files" element={<UiV2DataFilesEntry />} />
          <Route path="v2/data/app" element={<UiV2DataAppEntry />} />
          <Route path="v2/income/goals" element={<UiV2GoalsEntry />} />
          <Route path="v2/income/tax-iis" element={<UiV2TaxIisEntry />} />
          <Route path="v2/income" element={<UiV2IncomeEntry />} />
          <Route path="v2/income/scenario-lab" element={<UiV2ScenarioLabEntry />} />
          <Route path="v1" element={<Navigate replace to="/v2" />} />
          <Route path="analytics" element={<Navigate replace to="/v2/capital/performance" />} />
          <Route
            path="analytics/risk-allocation"
            element={<Navigate replace to="/v2/capital/allocation" />}
          />
          <Route path="freshness" element={<Navigate replace to="/v2/data" />} />
          <Route
            path="reconciliation"
            element={<Navigate replace to="/v2/data/reconciliation" />}
          />
          <Route path="months" element={<Navigate replace to="/v2/data/months" />} />
          <Route path="months/:monthId/close" element={<MonthCloseRedirect />} />
          <Route path="months/:monthId" element={<MonthRedirect />} />
          <Route path="monthly-close" element={<Navigate replace to="/v2/close" />} />
          <Route path="payouts" element={<Navigate replace to="/v2/data/payouts" />} />
          <Route path="accounts" element={<Navigate replace to="/v2/data/catalogs" />} />
          <Route path="goals" element={<Navigate replace to="/v2/income/goals" />} />
          <Route path="tax-iis-planner" element={<Navigate replace to="/v2/income/tax-iis" />} />
          <Route path="scenario-lab" element={<Navigate replace to="/v2/income/scenario-lab" />} />
          <Route path="export" element={<Navigate replace to="/v2/data/files" />} />
          <Route path="settings" element={<Navigate replace to="/v2/data/app" />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
