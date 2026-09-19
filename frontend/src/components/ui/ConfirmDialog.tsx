import { useEffect, useId, useRef } from "react";

import { Button } from "./Button";

type ConfirmDialogProps = {
  open: boolean;
  title: string;
  description: string;
  confirmLabel?: string;
  cancelLabel?: string;
  busy?: boolean;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
};

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = "Подтвердить",
  cancelLabel = "Отмена",
  busy = false,
  danger = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const titleId = useId();
  const descriptionId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const busyRef = useRef(busy);
  const onCancelRef = useRef(onCancel);

  useEffect(() => {
    busyRef.current = busy;
    onCancelRef.current = onCancel;
  }, [busy, onCancel]);

  useEffect(() => {
    if (!open) {
      return;
    }

    const dialog = dialogRef.current;
    const previouslyFocused =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const focusableSelector = [
      "button:not([disabled])",
      "[href]",
      "input:not([disabled]):not([type=hidden])",
      "select:not([disabled])",
      "textarea:not([disabled])",
      "[tabindex]:not([tabindex='-1'])",
    ].join(",");
    const getFocusableElements = () =>
      dialog
        ? Array.from(dialog.querySelectorAll<HTMLElement>(focusableSelector)).filter(
            (element) => !element.hasAttribute("aria-hidden"),
          )
        : [];

    const initialFocus =
      cancelRef.current && !cancelRef.current.hasAttribute("disabled")
        ? cancelRef.current
        : getFocusableElements()[0];
    if (initialFocus && !initialFocus.hasAttribute("disabled")) {
      initialFocus.focus();
    } else {
      dialog?.focus();
    }

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !busyRef.current) {
        onCancelRef.current();
        return;
      }
      if (event.key !== "Tab") {
        return;
      }

      const focusableElements = getFocusableElements();
      if (focusableElements.length === 0) {
        event.preventDefault();
        dialog?.focus();
        return;
      }

      const first = focusableElements[0];
      const last = focusableElements[focusableElements.length - 1];
      const activeElement = document.activeElement;
      const activeIsFocusable = focusableElements.includes(activeElement as HTMLElement);

      if (event.shiftKey) {
        if (!activeIsFocusable || activeElement === first) {
          event.preventDefault();
          last.focus();
        }
      } else if (!activeIsFocusable || activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      if (previouslyFocused?.isConnected) {
        previouslyFocused.focus();
      }
    };
  }, [open]);

  if (!open) {
    return null;
  }

  return (
    <div className="dialog-backdrop" role="presentation">
      <div
        aria-describedby={descriptionId}
        aria-labelledby={titleId}
        aria-modal="true"
        className="dialog"
        ref={dialogRef}
        role="alertdialog"
        tabIndex={-1}
      >
        <h2 className="dialog__title" id={titleId}>
          {title}
        </h2>
        <p className="dialog__body" id={descriptionId}>
          {description}
        </p>
        <div className="dialog__actions">
          <Button disabled={busy} onClick={onCancel} ref={cancelRef} type="button">
            {cancelLabel}
          </Button>
          <Button
            disabled={busy}
            onClick={onConfirm}
            type="button"
            variant={danger ? "danger" : "primary"}
          >
            {busy ? "…" : confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}
