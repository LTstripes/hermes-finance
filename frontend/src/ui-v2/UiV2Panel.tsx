import type { ReactNode } from "react";

import styles from "./UiV2Page.module.css";

/**
 * Shared UI v2 content panel: one header contract for Home, Capital, the archive
 * and the historical report. Presentation only.
 */
export function UiV2Panel({
  action,
  children,
  eyebrow,
  hint,
  id,
  testIdPrefix,
  title,
  wide = false,
}: {
  action?: ReactNode;
  children: ReactNode;
  eyebrow: string;
  hint?: string;
  id: string;
  testIdPrefix: string;
  title: string;
  wide?: boolean;
}) {
  return (
    <section
      aria-labelledby={id}
      className={`${styles.panel} ${wide ? styles.widePanel : ""}`}
      data-testid={`${testIdPrefix}-${id}`}
    >
      <div className={styles.panelHeader}>
        <div>
          <p className={styles.eyebrow}>{eyebrow}</p>
          <h2 id={id}>{title}</h2>
        </div>
        {action ?? (hint ? <p className={styles.panelHint}>{hint}</p> : null)}
      </div>
      {children}
    </section>
  );
}
