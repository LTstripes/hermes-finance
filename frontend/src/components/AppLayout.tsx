import { NavLink, Outlet } from "react-router";

import { RuntimeStatusBanner } from "./RuntimeStatus";

type NavItem = {
  to: string;
  label: string;
  icon: string;
  end?: boolean;
};

type NavGroup = {
  section: string;
  items: NavItem[];
};

const NAV: NavGroup[] = [
  {
    section: "Обзор",
    items: [
      { to: "/", label: "Дашборд", icon: "◫", end: true },
      { to: "/analytics", label: "Аналитика", icon: "⌁" },
      { to: "/freshness", label: "Актуальность данных", icon: "◷" },
      { to: "/reconciliation", label: "Сверка портфеля", icon: "⇄" },
    ],
  },
  {
    section: "Учёт",
    items: [
      { to: "/months", label: "Месяцы", icon: "☰" },
      { to: "/accounts", label: "Счета и инструменты", icon: "⬡" },
    ],
  },
  {
    section: "Планирование",
    items: [
      { to: "/payouts", label: "Автовыплаты", icon: "◌" },
      { to: "/goals", label: "Цели", icon: "◎" },
      { to: "/tax-iis-planner", label: "Налоги и ИИС", icon: "₽" },
    ],
  },
  {
    section: "Система",
    items: [
      { to: "/export", label: "Экспорт и резервные копии", icon: "⇩" },
      { to: "/settings", label: "Настройки", icon: "⚙" },
    ],
  },
];

export function AppLayout() {
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">
        К содержанию
      </a>
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
          {NAV.map((group) => (
            <div key={group.section}>
              <div className="nav-section">{group.section}</div>
              {group.items.map((item) => (
                <NavLink
                  key={item.to}
                  className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}
                  end={item.end}
                  to={item.to}
                >
                  <span aria-hidden="true" className="nav-item__icon">
                    {item.icon}
                  </span>
                  {item.label}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>

        <div className="sidebar__footer">
          <span aria-hidden="true" className="privacy-dot" />
          Данные остаются локально
        </div>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <span>Финансовая панель</span>
        </header>
        <RuntimeStatusBanner />
        <main className="content" id="main">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
