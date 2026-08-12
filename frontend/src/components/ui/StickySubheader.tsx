import type { HTMLAttributes, ReactNode } from "react";

type StickySubheaderProps = {
  title: ReactNode;
  meta?: ReactNode;
  summary?: ReactNode;
  actions?: ReactNode;
} & HTMLAttributes<HTMLDivElement>;

export function StickySubheader({
  title,
  meta,
  summary,
  actions,
  className = "",
  ...rest
}: StickySubheaderProps) {
  const classes = ["sticky-subheader", className].filter(Boolean).join(" ");

  return (
    <div className={classes} {...rest}>
      <div className="sticky-subheader__identity">
        <strong className="sticky-subheader__title">{title}</strong>
        {meta ? <span className="sticky-subheader__meta">{meta}</span> : null}
      </div>
      {summary ? <div className="sticky-subheader__summary">{summary}</div> : null}
      {actions ? <div className="sticky-subheader__actions">{actions}</div> : null}
    </div>
  );
}
