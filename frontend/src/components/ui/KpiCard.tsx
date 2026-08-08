import type { ReactNode } from "react";

type KpiCardProps = {
  label: string;
  value: ReactNode;
  delta?: ReactNode;
  deltaTone?: "up" | "down" | "neutral";
};

export function KpiCard({ label, value, delta, deltaTone = "neutral" }: KpiCardProps) {
  const deltaClass =
    deltaTone === "up"
      ? "kpi__delta kpi__delta--up"
      : deltaTone === "down"
        ? "kpi__delta kpi__delta--down"
        : "kpi__delta";

  return (
    <article className="kpi">
      <div className="kpi__label">{label}</div>
      <div className="kpi__value">{value}</div>
      {delta != null ? <div className={deltaClass}>{delta}</div> : null}
    </article>
  );
}
