import { useEffect, useId, useRef, useState, type FocusEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { useFloatingPosition } from "./FloatingLayer";

type HelpTipProps = {
  label: string;
  children: ReactNode;
  align?: "start" | "end";
};

export function HelpTip({ label, children, align = "end" }: HelpTipProps) {
  const [open, setOpen] = useState(false);
  const contentId = useId();
  const rootRef = useRef<HTMLSpanElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const bubbleRef = useRef<HTMLSpanElement>(null);
  const bubbleStyle = useFloatingPosition(rootRef, bubbleRef, open, align);

  useEffect(() => {
    if (!open) return;

    function onPointerDown(event: PointerEvent) {
      const target = event.target as Node;
      if (!rootRef.current?.contains(target) && !bubbleRef.current?.contains(target)) {
        setOpen(false);
      }
    }

    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      event.preventDefault();
      setOpen(false);
      triggerRef.current?.focus();
    }

    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  function handleBlur(event: FocusEvent<HTMLSpanElement>) {
    const next = event.relatedTarget as Node | null;
    if (!next || (!rootRef.current?.contains(next) && !bubbleRef.current?.contains(next))) {
      setOpen(false);
    }
  }

  return (
    <span className={`help-tip help-tip--${align}`} onBlurCapture={handleBlur} ref={rootRef}>
      <button
        aria-controls={contentId}
        aria-expanded={open}
        aria-label={label}
        className="help-tip__trigger"
        onClick={() => setOpen((value) => !value)}
        ref={triggerRef}
        type="button"
      >
        <span aria-hidden="true">i</span>
      </button>
      {open && typeof document !== "undefined"
        ? createPortal(
            <span
              className="help-tip__bubble"
              id={contentId}
              ref={bubbleRef}
              role="tooltip"
              style={bubbleStyle}
            >
              {children}
            </span>,
            document.body,
          )
        : null}
    </span>
  );
}
