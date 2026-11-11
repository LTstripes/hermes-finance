import { Component, lazy, type ReactNode, Suspense } from "react";
import { Link, Navigate, useLocation, useSearchParams } from "react-router";
import { ReturnsMonthRedirect } from "./returns/ReturnsMonthRedirect";
import { validIsin } from "./returns/navigation";
import { readDisplayNames } from "./returns/dashboard";

const UiV2PayoutForecastPage = lazy(() => import("./UiV2PayoutForecastPage"));

const UiV2Page = lazy(() => import("./UiV2Page"));
const UiV2CapitalPage = lazy(() => import("./UiV2CapitalPage"));
const UiV2CapitalAllocationPage = lazy(() => import("./UiV2CapitalAllocationPage"));
const UiV2ReturnsAccountPage = lazy(() => import("./UiV2ReturnsAccountPage"));
const UiV2ReturnsPage = lazy(() => import("./UiV2ReturnsPage"));
const UiV2ReturnsInstrumentPage = lazy(() => import("./UiV2ReturnsInstrumentPage"));
const UiV2ReportsPage = lazy(() => import("./UiV2ReportsPage"));
const UiV2ReportPage = lazy(() => import("./UiV2ReportPage"));
const UiV2ClosePage = lazy(() => import("./UiV2ClosePage"));
const UiV2DataSourcesPage = lazy(() => import("./UiV2DataSourcesPage"));
const UiV2DataOverviewPage = lazy(() => import("./UiV2DataOverviewPage"));
const UiV2SourceIntakePage = lazy(() => import("./UiV2SourceIntakePage"));
const UiV2MonthsPage = lazy(() => import("./UiV2MonthsPage"));
const UiV2MonthEditorPage = lazy(() => import("./UiV2MonthEditorPage"));
const UiV2DataCatalogsPage = lazy(() => import("./UiV2DataCatalogsPage"));
const UiV2DataFilesPage = lazy(() => import("./UiV2DataFilesPage"));
const UiV2DataAppPage = lazy(() => import("./UiV2DataAppPage"));
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
          <p>Обновите страницу, чтобы повторить загрузку. Сохранённые данные не изменены.</p>
          <button onClick={() => window.location.reload()} type="button">
            Повторить загрузку
          </button>
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
      <Link to="/v2">Мои финансы</Link>
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

export function UiV2ReturnsAccountEntry() {
  const [params] = useSearchParams();
  if (params.has("month") && !params.has("start") && !params.has("end"))
    return <ReturnsMonthRedirect />;
  return (
    <SuspenseFrame>
      <UiV2ReturnsAccountPage />
    </SuspenseFrame>
  );
}

export function UiV2ReturnsEntry() {
  const location = useLocation();
  const [params] = useSearchParams();
  if (params.has("month") && !params.has("start") && !params.has("end"))
    return <ReturnsMonthRedirect />;
  if (["scope", "start", "end", "period", "month", "categories"].some((key) => params.has(key)))
    return <Navigate replace to={`/v2/returns/account${location.search}${location.hash}`} />;
  const isin = params.getAll("isin").length === 1 ? params.get("isin") : null;
  if (validIsin(isin)) {
    const next = new URLSearchParams(params);
    next.delete("isin");
    if (!next.has("back"))
      next.set("back", params.has("capital_account") ? "/v2/capital" : "/v2/returns");
    return <Navigate replace to={`/v2/returns/instrument/${isin}?${next}`} />;
  }
  return (
    <SuspenseFrame>
      <UiV2ReturnsPage />
    </SuspenseFrame>
  );
}

export function UiV2ReturnsInstrumentEntry() {
  return (
    <SuspenseFrame>
      <UiV2ReturnsInstrumentPage accountLabels={readDisplayNames()} />
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

export function UiV2DataOverviewEntry() {
  return (
    <SuspenseFrame>
      <UiV2DataOverviewPage />
    </SuspenseFrame>
  );
}

export function UiV2SourceIntakeEntry() {
  return (
    <SuspenseFrame>
      <UiV2SourceIntakePage />
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
