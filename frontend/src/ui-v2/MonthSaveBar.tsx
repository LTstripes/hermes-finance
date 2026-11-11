import type { ReactNode } from "react";
import styles from "./UiV2MonthWorkspace.module.css";

export function MonthSaveBar({ changed, children }: { changed: number; children: ReactNode }) {
  return (
    <div className={styles.saveBar}>
      {children}
      {changed > 0 ? <span>Изменено: {changed}</span> : null}
    </div>
  );
}
