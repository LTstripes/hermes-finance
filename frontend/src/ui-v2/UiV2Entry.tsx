import { Component, lazy, type ReactNode, Suspense } from "react";
import { Link } from "react-router";

const UiV2Page = lazy(() => import("./UiV2Page"));

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

export function UiV2Entry() {
  return (
    <UiV2ErrorBoundary>
      <Suspense fallback={<p role="status">Загружаем новый интерфейс…</p>}>
        <UiV2Page />
      </Suspense>
    </UiV2ErrorBoundary>
  );
}
