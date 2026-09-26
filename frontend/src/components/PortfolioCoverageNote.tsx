import type { PortfolioSourceCoverage } from "../api/types";
import styles from "./PortfolioCoverageNote.module.css";

/** The API owns source coverage; this component only explains its result. */
export function PortfolioCoverageNote({
  coverage,
}: {
  coverage: PortfolioSourceCoverage | null | undefined;
}) {
  if (!coverage || coverage.status === "complete") return null;
  const missing = coverage.reason_codes.includes("active_account_snapshot_missing");
  const label =
    coverage.status === "unavailable"
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
