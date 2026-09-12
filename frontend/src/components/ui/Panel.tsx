import type { ReactNode } from "react";

type PanelProps = {
  children: ReactNode;
  id?: string;
  label?: string;
  title?: string;
  titleId?: string;
  action?: ReactNode;
  empty?: boolean;
  className?: string;
  tabIndex?: number;
  as?: "section" | "article" | "div";
};

export function Panel({
  children,
  id,
  label,
  title,
  titleId,
  action,
  empty = false,
  className = "",
  tabIndex,
  as: Tag = "section",
}: PanelProps) {
  const classes = ["panel", empty ? "panel--empty" : "", className].filter(Boolean).join(" ");

  return (
    <Tag className={classes} id={id} aria-labelledby={titleId} tabIndex={tabIndex}>
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
