import type { PortfolioSourceCoverage } from "../api/types";
import styles from "./PortfolioCoverageNote.module.css";

/** The API owns source coverage; this component only explains its result. */
export function PortfolioCoverageNote({
  coverage,
}: {
  coverage: PortfolioSourceCoverage | null | undefined;
}) {
  if (!coverage) return null;
  const pending = coverage.source_account_financial_coverage?.status === "partial";
  if (coverage.status === "complete" && !pending) return null;
  const missing = coverage.reason_codes.includes("active_account_snapshot_missing");
  const label = pending
    ? "Частичный известный итог: разбор источника не завершён"
    : coverage.status === "unavailable"
      ? "Нет снимков капитала"
      : missing
        ? "Частично: нет снимка счёта"
        : "Покрытие частичное";
  return (
    <span className={styles.note} data-testid="portfolio-coverage-note">
      {label}
    </span>
  );
}
