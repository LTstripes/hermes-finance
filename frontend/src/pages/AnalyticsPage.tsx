import { EmptyState, Panel } from "../components/ui";

export function AnalyticsPage() {
  return (
    <section className="stack-18">
      <header className="page-header">
        <p className="eyebrow">Обзор</p>
        <h1>Аналитика</h1>
        <p className="page-header__description">
          История капитала и структура портфеля будут собраны здесь в отдельном аналитическом
          представлении.
        </p>
      </header>

      <Panel label="Капитал" title="Динамика состава капитала">
        <EmptyState
          description="График по классам активов появится здесь после подключения исторического API."
          inline
          title="Аналитика готовится"
        />
      </Panel>
    </section>
  );
}
