import type { ReactNode } from "react";

type DataValueProps = {
  label: ReactNode;
  value: ReactNode;
  meta?: ReactNode;
  size?: "md" | "lg";
  muted?: boolean;
  className?: string;
};

export function DataValue({
  label,
  value,
  meta,
  size = "md",
  muted = false,
  className = "",
}: DataValueProps) {
  const classes = [
    "data-value",
    `data-value--${size}`,
    muted ? "data-value--muted" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={classes}>
      <span className="data-value__label">{label}</span>
      <strong className="data-value__value">{value}</strong>
      {meta ? <span className="data-value__meta">{meta}</span> : null}
    </div>
  );
}
