import { useLayoutEffect, useState, type CSSProperties, type RefObject } from "react";

type FloatingAlign = "start" | "end";

const VIEWPORT_GUTTER = 8;
const ANCHOR_GAP = 6;

/** Position a portaled layer next to an anchor while keeping it inside the viewport. */
export function useFloatingPosition(
  anchorRef: RefObject<HTMLElement | null>,
  layerRef: RefObject<HTMLElement | null>,
  open: boolean,
  align: FloatingAlign,
): CSSProperties | undefined {
  const [style, setStyle] = useState<CSSProperties>();

  useLayoutEffect(() => {
    if (!open) {
      setStyle(undefined);
      return;
    }

    const update = () => {
      const anchor = anchorRef.current;
      const layer = layerRef.current;
      if (!anchor || !layer) return;

      const anchorRect = anchor.getBoundingClientRect();
      const layerRect = layer.getBoundingClientRect();
      const viewportWidth = document.documentElement.clientWidth || window.innerWidth;
      const viewportHeight = document.documentElement.clientHeight || window.innerHeight;
      const maxLeft = Math.max(VIEWPORT_GUTTER, viewportWidth - layerRect.width - VIEWPORT_GUTTER);
      const maxTop = Math.max(VIEWPORT_GUTTER, viewportHeight - layerRect.height - VIEWPORT_GUTTER);
      const belowTop = anchorRect.bottom + ANCHOR_GAP;
      const aboveTop = anchorRect.top - layerRect.height - ANCHOR_GAP;
      const canFitBelow = belowTop <= maxTop;
      const canFitAbove = aboveTop >= VIEWPORT_GUTTER;
      const top = canFitBelow || !canFitAbove ? belowTop : aboveTop;
      const left = align === "end" ? anchorRect.right - layerRect.width : anchorRect.left;

      setStyle({
        bottom: "auto",
        left: Math.min(Math.max(left, VIEWPORT_GUTTER), maxLeft),
        maxHeight: `calc(100dvh - ${VIEWPORT_GUTTER * 2}px)`,
        position: "fixed",
        right: "auto",
        top: Math.min(Math.max(top, VIEWPORT_GUTTER), maxTop),
        visibility: "visible",
      });
    };

    setStyle({
      bottom: "auto",
      left: 0,
      maxHeight: `calc(100dvh - ${VIEWPORT_GUTTER * 2}px)`,
      position: "fixed",
      right: "auto",
      top: 0,
      visibility: "hidden",
    });
    update();
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    return () => {
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
    };
  }, [align, anchorRef, layerRef, open]);

  return style;
}
