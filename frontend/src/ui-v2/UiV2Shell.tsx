import type { ReactNode } from "react";
import { Link } from "react-router";

import { UiV2BackToTop } from "./UiV2BackToTop";
import styles from "./UiV2Page.module.css";

export type UiV2Section = "home" | "capital" | "data" | "income";

const NATIVE_SECTIONS: Array<{ id: UiV2Section; label: string; icon: string; to: string }> = [
  { id: "home", label: "Мои финансы", icon: "⌂", to: "/v2" },
  { id: "capital", label: "Капитал", icon: "◧", to: "/v2/capital" },
  { id: "data", label: "Данные", icon: "◫", to: "/v2/data" },
  { id: "income", label: "Доход и планы", icon: "◒", to: "/v2/income" },
];

const LEGACY_LINKS: Array<{ label: string; to: string }> = [
  { label: "Закрыть месяц", to: "/monthly-close" },
  { label: "Счета и справочники", to: "/accounts" },
  { label: "История и результаты", to: "/analytics" },
  { label: "Доход и цели", to: "/goals" },
  { label: "Экспорт и копии", to: "/export" },
  { label: "Настройки", to: "/settings" },
];

/**
 * Shared opt-in UI v2 shell: dark sidebar, one native section marked as the
 * current page, labelled v1 escapes and the single v1 return link.
 */
export function UiV2Shell({
  active,
  busy = false,
  children,
  header,
  sidebarExtra,
  v1ReturnPath,
}: {
  /** No native section is marked current on the contextual history routes. */
  active?: UiV2Section;
  busy?: boolean;
  children: ReactNode;
  header: ReactNode;
  sidebarExtra?: ReactNode;
  v1ReturnPath: string;
}) {
  return (
    <div className={styles.shell}>
      <a className={styles.skipLink} href="#v2-main">
        К содержанию
      </a>
      <aside className={styles.sidebar}>
        <Link className={styles.brand} to="/v2">
          <span className={styles.brandMark} aria-hidden="true">
            H
          </span>
          <span>
            Hermes Finance<small>Личные финансы</small>
          </span>
        </Link>
        <nav aria-label="Основная навигация" className={styles.navigation}>
          {NATIVE_SECTIONS.map((section) => (
            <Link
              aria-current={active === section.id ? "page" : undefined}
              key={section.id}
              to={section.to}
            >
              <span aria-hidden="true">{section.icon}</span> {section.label}
            </Link>
          ))}
        </nav>
        {sidebarExtra}
        <div className={styles.sidebarNote}>
          <span className={styles.eyebrow}>Финансовая картина</span>
          <p>Капитал, изменения, доход и цели по подтверждённым отчётам.</p>
        </div>
        <div className={styles.legacyLinks}>
          <p className={styles.eyebrow}>В текущем интерфейсе</p>
          {LEGACY_LINKS.map((link) => (
            <Link key={link.to} to={link.to}>
              {link.label} <span aria-hidden="true">↗</span>
            </Link>
          ))}
        </div>
        <p className={styles.localOnly}>Только на этом компьютере</p>
      </aside>
      <div className={styles.workspace}>
        <div className={styles.topbar}>
          <span>
            Новый интерфейс <span className={styles.previewBadge}>Предварительная версия</span>
          </span>
          <Link to={v1ReturnPath}>Вернуться к текущему интерфейсу →</Link>
        </div>
        <main aria-busy={busy} className={styles.main} id="v2-main" tabIndex={-1}>
          <header className={styles.header}>{header}</header>
          {children}
        </main>
        <UiV2BackToTop targetId="v2-main" />
      </div>
    </div>
  );
}
