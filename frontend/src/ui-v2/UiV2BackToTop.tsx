import { useEffect, useState } from "react";

import styles from "./UiV2Page.module.css";

const MEANINGFUL_SCROLL_TOP = 320;
const MODAL_SELECTOR = '[aria-modal="true"]';

function getScrollTop() {
  return Math.max(window.scrollY, document.documentElement.scrollTop, document.body.scrollTop);
}

export function UiV2BackToTop({ targetId }: { targetId: string }) {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const updateVisibility = () => {
      setVisible(
        getScrollTop() >= MEANINGFUL_SCROLL_TOP && !document.querySelector(MODAL_SELECTOR),
      );
    };

    updateVisibility();
    window.addEventListener("scroll", updateVisibility, { passive: true });
    const observer = new MutationObserver(updateVisibility);
    observer.observe(document.body, { childList: true, subtree: true });
    return () => {
      window.removeEventListener("scroll", updateVisibility);
      observer.disconnect();
    };
  }, []);

  if (!visible) return null;

  const returnToMain = () => {
    const target = document.getElementById(targetId);
    if (!target) return;

    const prefersReducedMotion =
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    target.scrollIntoView({
      behavior: prefersReducedMotion ? "auto" : "smooth",
      block: "start",
    });
    target.focus({ preventScroll: true });
  };

  return (
    <button
      aria-controls={targetId}
      className={styles.backToTop}
      data-testid="ui-v2-back-to-top"
      onClick={returnToMain}
      type="button"
    >
      Наверх
    </button>
  );
}
