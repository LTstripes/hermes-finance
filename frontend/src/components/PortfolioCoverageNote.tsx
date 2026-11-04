import type { PortfolioSourceCoverage } from "../api/types";
import { useState } from "react";
import styles from "./PortfolioCoverageNote.module.css";

/** The API owns source coverage; this component only explains its result. */
export function PortfolioCoverageNote({
  coverage,
}: {
  coverage: PortfolioSourceCoverage | null | undefined;
}) {
  const [expanded, setExpanded] = useState(false);
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
      {coverage.status !== "unavailable" && (
        <span>
          {" "}
          <button
            type="button"
            aria-expanded={expanded}
            onClick={() => setExpanded((open) => !open)}
          >
            Подробнее
          </button>
          {expanded && (
            <span>
              {" "}
              <span>Показаны данные по известным записям. </span>
              <span>
                {missing
                  ? "Не хватает снимка одного или нескольких счетов. "
                  : "Часть данных ещё не подтверждена. "}
                {pending ? "Разбор данных источника не завершён. " : ""}
              </span>
              <a href="/v2/capital">Открыть капитал</a>
            </span>
          )}
        </span>
      )}
    </span>
  );
}
