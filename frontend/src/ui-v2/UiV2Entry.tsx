import { Component, lazy, type ReactNode, Suspense } from "react";
import { Link } from "react-router";

import type { DataAppSection } from "./monthSelection";

const UiV2Page = lazy(() => import("./UiV2Page"));
const UiV2CapitalPage = lazy(() => import("./UiV2CapitalPage"));
const UiV2ReportsPage = lazy(() => import("./UiV2ReportsPage"));
const UiV2ReportPage = lazy(() => import("./UiV2ReportPage"));
const UiV2ClosePage = lazy(() => import("./UiV2ClosePage"));
const UiV2DataSourcesPage = lazy(() => import("./UiV2DataSourcesPage"));
const UiV2DataReconciliationPage = lazy(() => import("./UiV2DataReconciliationPage"));
const UiV2DataFilesPage = lazy(() => import("./UiV2DataFilesPage"));
const UiV2DataPlaceholderPage = lazy(() => import("./UiV2DataPlaceholderPage"));
const UiV2IncomePage = lazy(() => import("./UiV2IncomePage"));

export class UiV2ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  override state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  override render() {
    if (this.state.failed) {
      return (
        <section className="state-block" role="alert">
          <h1>Новый интерфейс не загрузился</h1>
          <p>Текущий интерфейс остаётся доступным. Сохранённые данные не изменены.</p>
          <Link to="/">Вернуться к текущему интерфейсу</Link>
        </section>
      );
    }
    return this.props.children;
  }
}

function SuspenseFrame({ children }: { children: ReactNode }) {
  return (
    <UiV2ErrorBoundary>
      <Suspense fallback={<p role="status">Загружаем новый интерфейс…</p>}>{children}</Suspense>
    </UiV2ErrorBoundary>
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

export function UiV2DataSourcesEntry() {
  return (
    <SuspenseFrame>
      <UiV2DataSourcesPage />
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

export function UiV2DataFilesEntry() {
  return (
    <SuspenseFrame>
      <UiV2DataFilesPage />
    </SuspenseFrame>
  );
}

export function UiV2DataPlaceholderEntry({
  section,
}: {
  section: Exclude<DataAppSection, "sources" | "reconciliation">;
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
