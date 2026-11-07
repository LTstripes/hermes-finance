import type { ReactNode } from "react";
import { Link, useLocation } from "react-router";

import { UiV2BackToTop } from "./UiV2BackToTop";
import { UiV2MonthPlate } from "./UiV2MonthPlate";
import styles from "./UiV2Page.module.css";

export type UiV2Section = "home" | "capital" | "returns" | "data" | "income";

const NATIVE_SECTIONS: Array<{ id: UiV2Section; label: string; icon: ReactNode; to: string }> = [
  {
    id: "home",
    label: "Мои финансы",
    icon: <path d="M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z" />,
    to: "/v2",
  },
  {
    id: "capital",
    label: "Капитал",
    icon: (
      <>
        <rect height="18" rx="2" width="8" x="3" y="3" />
        <rect height="8" rx="2" width="8" x="13" y="3" />
        <rect height="8" rx="2" width="8" x="13" y="13" />
      </>
    ),
    to: "/v2/capital",
  },
  {
    id: "returns",
    label: "Доходность",
    icon: <path d="M3 17l6-6 4 4 8-8M15 7h6v6" />,
    to: "/v2/returns",
  },
  {
    id: "income",
    label: "Доход и планы",
    icon: (
      <>
        <rect height="16" rx="2" width="18" x="3" y="5" />
        <path d="M3 10h18M8 3v4M16 3v4" />
      </>
    ),
    to: "/v2/income",
  },
  {
    id: "data",
    label: "Настройки",
    icon: (
      <>
        <path d="M4 7h10M18 7h2M4 17h2M10 17h10" />
        <circle cx="16" cy="7" r="2" />
        <circle cx="8" cy="17" r="2" />
      </>
    ),
    to: "/v2/data/app",
  },
];

/**
 * Shared UI v2 shell: dark sidebar, one native section marked as the current
 * page and the working month plate.
 */
export function UiV2Shell({
  active,
  busy = false,
  children,
  header,
  sidebarExtra,
}: {
  /** Explicit section for contextual routes outside a native section. */
  active?: UiV2Section;
  busy?: boolean;
  children: ReactNode;
  header: ReactNode;
  sidebarExtra?: ReactNode;
}) {
  const { pathname } = useLocation();
  const current =
    NATIVE_SECTIONS.find((section) =>
      section.id === "home"
        ? pathname === "/v2" || pathname === "/"
        : pathname === section.to || pathname.startsWith(`${section.to}/`),
    )?.id ?? active;
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
            Hermes Finance<small>Только на этом компьютере</small>
          </span>
        </Link>
        <nav aria-label="Основная навигация" className={styles.navigation}>
          {NATIVE_SECTIONS.map((section) => (
            <Link
              aria-current={current === section.id ? "page" : undefined}
              key={section.id}
              to={section.to}
            >
              <svg
                aria-hidden="true"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                viewBox="0 0 24 24"
              >
                {section.icon}
              </svg>
              {section.label}
            </Link>
          ))}
        </nav>
        {sidebarExtra}
        <UiV2MonthPlate />
      </aside>
      <div className={styles.workspace}>
        <main aria-busy={busy} className={styles.main} id="v2-main" tabIndex={-1}>
          <header className={styles.header}>{header}</header>
          {children}
        </main>
        <UiV2BackToTop targetId="v2-main" />
      </div>
    </div>
  );
}
