import { Component, lazy, type ReactNode, Suspense } from "react";
import { Link } from "react-router";

import type { DataAppSection } from "./monthSelection";

const UiV2AlfaBaselinePage = lazy(() => import("./UiV2AlfaBaselinePage"));
const UiV2PayoutForecastPage = lazy(() => import("./UiV2PayoutForecastPage"));

const UiV2Page = lazy(() => import("./UiV2Page"));
const UiV2CapitalPage = lazy(() => import("./UiV2CapitalPage"));
const UiV2CapitalAllocationPage = lazy(() => import("./UiV2CapitalAllocationPage"));
const UiV2MonthlyResultPage = lazy(() => import("./UiV2MonthlyResultPage"));
const UiV2CapitalPerformanceDetail = lazy(() => import("./UiV2CapitalPerformanceDetail"));
const UiV2ReportsPage = lazy(() => import("./UiV2ReportsPage"));
const UiV2ReportPage = lazy(() => import("./UiV2ReportPage"));
const UiV2ClosePage = lazy(() => import("./UiV2ClosePage"));
const UiV2DataSourcesPage = lazy(() => import("./UiV2DataSourcesPage"));
const UiV2MonthsPage = lazy(() => import("./UiV2MonthsPage"));
const UiV2MonthEditorPage = lazy(() => import("./UiV2MonthEditorPage"));
const UiV2DataReconciliationPage = lazy(() => import("./UiV2DataReconciliationPage"));
const UiV2DataCatalogsPage = lazy(() => import("./UiV2DataCatalogsPage"));
const UiV2DataFilesPage = lazy(() => import("./UiV2DataFilesPage"));
const UiV2DataAppPage = lazy(() => import("./UiV2DataAppPage"));
const UiV2DataPlaceholderPage = lazy(() => import("./UiV2DataPlaceholderPage"));
const UiV2IncomePage = lazy(() => import("./UiV2IncomePage"));
const UiV2GoalsPage = lazy(() => import("./UiV2GoalsPage"));
const UiV2TaxIisPage = lazy(() => import("./UiV2TaxIisPage"));
const UiV2ScenarioLabPage = lazy(() => import("./UiV2ScenarioLabPage"));

export class UiV2ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  override state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  override render() {
    if (this.state.failed) {
      return (
        <section className="state-block" role="alert">
          <h1>Основной интерфейс не загрузился</h1>
          <p>Предыдущий интерфейс остаётся доступным. Сохранённые данные не изменены.</p>
          <Link to="/v1">Перейти в предыдущий интерфейс (UI v1)</Link>
        </section>
      );
    }
    return this.props.children;
  }
}

export function UiV2LoadingFallback() {
  return (
    <section className="state-block" role="status">
      <p>Загружаем основной интерфейс…</p>
      <Link to="/v1">Перейти в предыдущий интерфейс (UI v1)</Link>
    </section>
  );
}

function SuspenseFrame({ children }: { children: ReactNode }) {
  return (
    <UiV2ErrorBoundary>
      <Suspense fallback={<UiV2LoadingFallback />}>{children}</Suspense>
    </UiV2ErrorBoundary>
  );
}

export function UiV2AlfaBaselineEntry() {
  return (
    <SuspenseFrame>
      <UiV2AlfaBaselinePage />
    </SuspenseFrame>
  );
}

export function UiV2PayoutForecastEntry() {
  return (
    <SuspenseFrame>
      <UiV2PayoutForecastPage />
    </SuspenseFrame>
  );
}

export function UiV2Entry() {
  return (
    <SuspenseFrame>
      <UiV2Page />
    </SuspenseFrame>
  );
}

export function UiV2CapitalEntry() {
  return (
    <SuspenseFrame>
      <UiV2CapitalPage />
    </SuspenseFrame>
  );
}

export function UiV2CapitalAllocationEntry() {
  return (
    <SuspenseFrame>
      <UiV2CapitalAllocationPage />
    </SuspenseFrame>
  );
}

export function UiV2MonthlyResultEntry() {
  return (
    <SuspenseFrame>
      <UiV2MonthlyResultPage />
    </SuspenseFrame>
  );
}

export function UiV2CapitalPerformanceEntry() {
  return (
    <SuspenseFrame>
      <UiV2CapitalPerformanceDetail />
    </SuspenseFrame>
  );
}

export function UiV2DataSourcesEntry() {
  return (
    <SuspenseFrame>
      <UiV2DataSourcesPage />
    </SuspenseFrame>
  );
}

export function UiV2MonthsEntry() {
  return (
    <SuspenseFrame>
      <UiV2MonthsPage />
    </SuspenseFrame>
  );
}

export function UiV2MonthEditorEntry() {
  return (
    <SuspenseFrame>
      <UiV2MonthEditorPage />
    </SuspenseFrame>
  );
}

export function UiV2DataReconciliationEntry() {
  return (
    <SuspenseFrame>
      <UiV2DataReconciliationPage />
    </SuspenseFrame>
  );
}

export function UiV2DataCatalogsEntry() {
  return (
    <SuspenseFrame>
      <UiV2DataCatalogsPage />
    </SuspenseFrame>
  );
}

export function UiV2DataFilesEntry() {
  return (
    <SuspenseFrame>
      <UiV2DataFilesPage />
    </SuspenseFrame>
  );
}

export function UiV2DataAppEntry() {
  return (
    <SuspenseFrame>
      <UiV2DataAppPage />
    </SuspenseFrame>
  );
}

export function UiV2DataPlaceholderEntry({
  section,
}: {
  section: Exclude<
    DataAppSection,
    "sources" | "reconciliation" | "months" | "alfa-baseline" | "payouts"
  >;
}) {
  return (
    <SuspenseFrame>
      <UiV2DataPlaceholderPage section={section} />
    </SuspenseFrame>
  );
}

export function UiV2ReportsEntry() {
  return (
    <SuspenseFrame>
      <UiV2ReportsPage />
    </SuspenseFrame>
  );
}

export function UiV2ReportEntry() {
  return (
    <SuspenseFrame>
      <UiV2ReportPage />
    </SuspenseFrame>
  );
}

export function UiV2CloseEntry() {
  return (
    <SuspenseFrame>
      <UiV2ClosePage />
    </SuspenseFrame>
  );
}

export function UiV2IncomeEntry() {
  return (
    <SuspenseFrame>
      <UiV2IncomePage />
    </SuspenseFrame>
  );
}

export function UiV2GoalsEntry() {
  return (
    <SuspenseFrame>
      <UiV2GoalsPage />
    </SuspenseFrame>
  );
}

export function UiV2TaxIisEntry() {
  return (
    <SuspenseFrame>
      <UiV2TaxIisPage />
    </SuspenseFrame>
  );
}

export function UiV2ScenarioLabEntry() {
  return (
    <SuspenseFrame>
      <UiV2ScenarioLabPage />
    </SuspenseFrame>
  );
}
