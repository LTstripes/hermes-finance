// One in-session return position; no financial data or persistent browser storage.
let pending: { path: string; y: number } | null = null;

export function rememberInstrumentScroll() {
  pending = { path: location.pathname + location.search + location.hash, y: window.scrollY };
}

export function restoreInstrumentScroll(path: string, main: HTMLElement) {
  const saved = pending;
  if (!saved || saved.path !== path) return;
  const restore = () => {
    if (pending !== saved || main.querySelector('[aria-busy="true"]')) return;
    if (document.documentElement.scrollHeight - window.innerHeight < saved.y) return;
    window.scrollTo({ top: saved.y, behavior: "instant" });
    pending = null;
  };
  const observer = new ResizeObserver(restore);
  const content = new MutationObserver(restore);
  observer.observe(main);
  content.observe(main, { childList: true, subtree: true, attributes: true });
  restore();
  return () => {
    observer.disconnect();
    content.disconnect();
  };
}
