import { NavLink, Outlet } from "react-router";

export function AppLayout() {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span aria-hidden="true" className="brand__mark">
            HF
          </span>
          <span className="brand__text">
            <strong>Hermes Finance</strong>
            <small>Личный капитал</small>
          </span>
        </div>

        <nav aria-label="Основная навигация" className="sidebar__nav">
          <NavLink className="nav-item" to="/">
            <span aria-hidden="true" className="nav-item__icon">
              ◫
            </span>
            Дашборд
          </NavLink>
        </nav>

        <div className="sidebar__footer">
          <span aria-hidden="true" className="privacy-dot" />
          Данные остаются локально
        </div>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <span>Finance Dashboard</span>
          <span className="topbar__badge">MVP · локально</span>
        </header>
        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
