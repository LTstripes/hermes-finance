import {
  useEffect,
  useId,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type FocusEvent,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";

import { Button } from "./Button";
import { useFloatingPosition } from "./FloatingLayer";

type OverflowMenuProps = {
  label?: string;
  children: ReactNode;
  align?: "start" | "end";
};

type OverflowMenuItemProps = {
  danger?: boolean;
} & ButtonHTMLAttributes<HTMLButtonElement>;

export function OverflowMenu({
  label = "Дополнительные действия",
  children,
  align = "end",
}: OverflowMenuProps) {
  const [open, setOpen] = useState(false);
  const menuId = useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const menuStyle = useFloatingPosition(rootRef, menuRef, open, align);

  useEffect(() => {
    if (!open) return;
    menuItems(menuRef.current)[0]?.focus();
  }, [open]);

  useEffect(() => {
    if (!open) return;

    function onPointerDown(event: PointerEvent) {
      const target = event.target as Node;
      if (!rootRef.current?.contains(target) && !menuRef.current?.contains(target)) {
        setOpen(false);
      }
    }

    function onKeyDown(event: globalThis.KeyboardEvent) {
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

  function handleBlur(event: FocusEvent<HTMLDivElement>) {
    const next = event.relatedTarget as Node | null;
    if (!next || (!rootRef.current?.contains(next) && !menuRef.current?.contains(next))) {
      setOpen(false);
    }
  }

  function handleMenuKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const items = menuItems(menuRef.current);
    if (items.length === 0) return;

    const current = items.indexOf(document.activeElement as HTMLElement);
    let next = current;

    if (event.key === "ArrowDown") {
      next = current < 0 ? 0 : (current + 1) % items.length;
    } else if (event.key === "ArrowUp") {
      next = current < 0 ? items.length - 1 : (current - 1 + items.length) % items.length;
    } else if (event.key === "Home") {
      next = 0;
    } else if (event.key === "End") {
      next = items.length - 1;
    } else {
      return;
    }

    event.preventDefault();
    items[next]?.focus();
  }

  return (
    <div
      className={`overflow-menu overflow-menu--${align}`}
      onBlurCapture={handleBlur}
      ref={rootRef}
    >
      <Button
        aria-controls={menuId}
        aria-expanded={open}
        aria-haspopup="menu"
        aria-label={label}
        className="overflow-menu__trigger"
        onClick={() => setOpen((value) => !value)}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown") {
            event.preventDefault();
            setOpen(true);
          }
        }}
        ref={triggerRef}
        size="sm"
        variant="ghost"
      >
        <span aria-hidden="true">⋯</span>
      </Button>
      {open && typeof document !== "undefined"
        ? createPortal(
            <div
              className="overflow-menu__menu"
              id={menuId}
              onClick={(event) => {
                if ((event.target as Element).closest('[role="menuitem"]')) {
                  setOpen(false);
                }
              }}
              onKeyDown={handleMenuKeyDown}
              ref={menuRef}
              role="menu"
              style={menuStyle}
            >
              {children}
            </div>,
            document.body,
          )
        : null}
    </div>
  );
}

export function OverflowMenuItem({
  danger = false,
  className = "",
  type = "button",
  ...rest
}: OverflowMenuItemProps) {
  const classes = ["overflow-menu__item", danger ? "overflow-menu__item--danger" : "", className]
    .filter(Boolean)
    .join(" ");

  return <button className={classes} role="menuitem" type={type} {...rest} />;
}

function menuItems(root: HTMLDivElement | null): HTMLElement[] {
  if (!root) return [];
  return Array.from(root.querySelectorAll<HTMLElement>('[role="menuitem"]:not([disabled])'));
}
