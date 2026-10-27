import { useEffect, useId, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router";
import { ConfirmDialog } from "../components/ui";

/** One navigation guard for a mounted month form. Pending writes are never discarded. */
export function MonthNavigationGuard({
  dirty,
  pending,
  onDiscard,
}: {
  dirty: boolean;
  pending: boolean;
  onDiscard?: (destination?: string) => void;
}) {
  const location = useLocation();
  const navigate = useNavigate();
  const [destination, setDestination] = useState<string | null>(null);
  const href = `${location.pathname}${location.search}${location.hash}`;
  const token = useId();
  const historyGuard = useRef(false);
  const allowPop = useRef(false);
  const latest = useRef({ pending, onDiscard });
  latest.current = { pending, onDiscard };
  const blocked = dirty || pending;
  // BrowserRouter can commit a POP before a later window listener runs. A
  // same-location sentinel keeps the mounted form intact for that first POP.
  useEffect(() => {
    if (!blocked) return;
    const protect = () => {
      historyGuard.current = true;
      allowPop.current = false;
      window.history.pushState({ ...window.history.state, monthNavigationGuard: token }, "", href);
    };
    if (!historyGuard.current || window.history.state?.monthNavigationGuard !== token) protect();
    const guardBack = () => {
      if (allowPop.current) return;
      if (
        !latest.current.pending &&
        window.confirm("Есть несохранённые изменения. Перейти и потерять их?")
      ) {
        allowPop.current = true;
        historyGuard.current = false;
        latest.current.onDiscard?.();
        window.setTimeout(() => window.history.back(), 0);
      } else {
        protect();
        if (latest.current.pending) setDestination(href);
      }
    };
    window.addEventListener("popstate", guardBack);
    return () => window.removeEventListener("popstate", guardBack);
  }, [blocked, href, token]);
  useEffect(() => {
    if (blocked || !historyGuard.current || window.history.state?.monthNavigationGuard !== token)
      return;
    allowPop.current = true;
    historyGuard.current = false;
    window.history.back();
  }, [blocked, token]);
  useEffect(() => {
    if (!dirty && !pending) return;
    const guardLinks = (event: MouseEvent) => {
      if (event.button !== 0 || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey)
        return;
      const anchor = (event.target as Element).closest("a[href]");
      if (!anchor || anchor.getAttribute("target") === "_blank") return;
      const url = new URL(anchor.getAttribute("href") ?? "", window.location.href);
      if (url.origin !== window.location.origin) return;
      const next = `${url.pathname}${url.search}${url.hash}`;
      if (next === href) return;
      if (url.pathname === location.pathname && url.search === location.search) return;
      event.preventDefault();
      event.stopPropagation();
      setDestination(next);
    };
    const guardUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    document.addEventListener("click", guardLinks, true);
    window.addEventListener("beforeunload", guardUnload);
    return () => {
      document.removeEventListener("click", guardLinks, true);
      window.removeEventListener("beforeunload", guardUnload);
    };
  }, [dirty, pending, href, location.pathname, location.search]);
  return (
    <ConfirmDialog
      open={destination !== null}
      title={pending ? "Сохранение ещё не подтверждено" : "Несохранённые изменения"}
      description={
        pending
          ? "Сначала заверши запрос или повторное чтение результата в этой форме. Повторная отправка не выполняется."
          : "Есть несохранённые изменения. Перейти и потерять их?"
      }
      cancelLabel="Остаться"
      confirmLabel={pending ? "Вернуться к форме" : "Перейти без сохранения"}
      onCancel={() => setDestination(null)}
      onConfirm={() => {
        if (!pending && destination) {
          const replace = window.history.state?.monthNavigationGuard === token;
          allowPop.current = true;
          historyGuard.current = false;
          onDiscard?.(destination);
          navigate(destination, { replace });
        }
        setDestination(null);
      }}
    />
  );
}
