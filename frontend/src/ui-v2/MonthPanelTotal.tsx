import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

/** Present an existing leaf total in the workspace header without a second calculation. */
export function MonthPanelTotal({ value }: { value: string }) {
  const [target, setTarget] = useState<HTMLElement | null>(null);
  useEffect(() => {
    setTarget(document.getElementById("month-panel-total"));
  }, []);
  return target ? createPortal(value, target) : null;
}
