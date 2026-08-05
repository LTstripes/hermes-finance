import { BackendStatus } from "../components/BackendStatus";

export function DashboardPage() {
  return (
    <section className="dashboard">
      <header className="page-header">
        <p className="eyebrow">Обзор</p>
        <h1>Дашборд</h1>
        <p className="page-header__description">
          Техническое состояние локального приложения и будущая финансовая сводка — без передачи
          данных наружу.
        </p>
      </header>

      <div className="dashboard-grid">
        <BackendStatus />

        <article className="panel panel--empty">
          <div>
            <p className="panel__label">Финансовая сводка</p>
            <h2>Данные ещё не подключены</h2>
            <p>
              Счета, активы и ежемесячные показатели появятся после создания доменной модели и
              локальной базы.
            </p>
          </div>
          <span className="pending-badge">Следующий этап</span>
        </article>
      </div>
    </section>
  );
}
