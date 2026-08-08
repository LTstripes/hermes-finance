import type { ReactNode } from "react";

type PanelProps = {
  children: ReactNode;
  label?: string;
  title?: string;
  titleId?: string;
  action?: ReactNode;
  empty?: boolean;
  className?: string;
  as?: "section" | "article" | "div";
};

export function Panel({
  children,
  label,
  title,
  titleId,
  action,
  empty = false,
  className = "",
  as: Tag = "section",
}: PanelProps) {
  const classes = ["panel", empty ? "panel--empty" : "", className].filter(Boolean).join(" ");

  return (
    <Tag className={classes} aria-labelledby={titleId}>
      {(label || title || action) && (
        <div className="panel__heading">
          <div>
            {label ? <p className="panel__label">{label}</p> : null}
            {title ? <h2 id={titleId}>{title}</h2> : null}
          </div>
          {action}
        </div>
      )}
      {children}
    </Tag>
  );
}
