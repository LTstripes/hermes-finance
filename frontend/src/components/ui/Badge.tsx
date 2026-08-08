import type { ReactNode } from "react";

type BadgeTone = "neutral" | "ok" | "draft" | "closed" | "info";

const toneClass: Record<BadgeTone, string> = {
  neutral: "chip",
  ok: "chip chip--ok",
  draft: "badge badge--draft",
  closed: "badge badge--closed",
  info: "badge badge--info",
};

type BadgeProps = {
  children: ReactNode;
  tone?: BadgeTone;
  className?: string;
};

export function Badge({ children, tone = "neutral", className = "" }: BadgeProps) {
  return <span className={`${toneClass[tone]} ${className}`.trim()}>{children}</span>;
}
