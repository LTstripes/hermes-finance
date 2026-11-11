import { useLayoutEffect, useRef, useState, type ReactElement } from "react";
import { ResponsiveContainer } from "recharts";
import styles from "./CssResponsiveContainer.module.css";

/** Recharts' initial bounding rect includes CSS zoom; chart geometry needs CSS pixels. */
export function CssResponsiveContainer({
  children,
  height,
}: {
  children: ReactElement;
  height: number;
}) {
  const container = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const element = container.current;
    if (!element) return;
    setWidth(element.clientWidth);
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return (
    <div className={styles.container} ref={container}>
      <ResponsiveContainer height={height} width={width || "100%"} minWidth={0}>
        {children}
      </ResponsiveContainer>
    </div>
  );
}
