import type { MouseEvent } from "react";
import { Link, useLocation } from "react-router";

import styles from "./UiV2Tabs.module.css";

/** Section navigation keeps the selected reporting month on every destination. */
export function UiV2Tabs({
  label,
  tabs,
  onNavigate,
}: {
  label: string;
  tabs: { label: string; to: string; active: boolean }[];
  onNavigate?: (event: MouseEvent<HTMLAnchorElement>, to: string) => void;
}) {
  const { search } = useLocation();
  const month = new URLSearchParams(search).get("month");
  return (
    <nav aria-label={label} className={styles.tabs}>
      {tabs.map((tab) => {
        const [path, hash] = tab.to.split("#");
        const [pathname, query] = path.split("?");
        const params = new URLSearchParams(query);
        if (month !== null) params.set("month", month);
        const to = `${pathname}${params.size ? `?${params}` : ""}${hash ? `#${hash}` : ""}`;
        return (
          <Link
            aria-current={tab.active ? "page" : undefined}
            key={tab.to}
            to={to}
            onClick={(event) => onNavigate?.(event, to)}
          >
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}
