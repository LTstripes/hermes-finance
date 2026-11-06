import { useQuery } from "@tanstack/react-query";
import { listAccounts } from "../api/accounts";
import { formatMonth } from "../lib/format";
import { queryKeys } from "../queryClient";
import type { PortfolioSourceCoverage } from "../api/types";
import { useState } from "react";
import styles from "./PortfolioCoverageNote.module.css";

/** The API owns source coverage; this component only explains its result. */
export function PortfolioCoverageNote({
  coverage,
  month,
}: {
  coverage: PortfolioSourceCoverage | null | undefined;
  month?: { year: number; month: number };
}) {
  const [expanded, setExpanded] = useState(false);
  if (!coverage) return null;
  const pending = coverage.source_account_financial_coverage?.status === "partial";
  if (coverage.status === "complete" && !pending) return null;
  const missing = coverage.reason_codes.includes("active_account_snapshot_missing");
  const label =
    coverage.status === "unavailable"
      ? "Нет снимков капитала"
      : pending
        ? "Частичный известный итог: разбор источника не завершён"
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
                {missing ? (
                  <MissingSnapshots ids={coverage.missing_account_ids} month={month} />
                ) : (
                  "Часть данных ещё не подтверждена. "
                )}
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

function MissingSnapshots({
  ids,
  month,
}: {
  ids: number[];
  month?: { year: number; month: number };
}) {
  const accounts = useQuery({
    queryKey: queryKeys.accounts,
    queryFn: ({ signal }) => listAccounts(signal),
    enabled: ids.length > 0,
  });
  const names = ids.map((id) => accounts.data?.find((account) => account.id === id)?.name?.trim());
  const knownNames = names.filter((name): name is string => Boolean(name));
  const hasUnknown = ids.length === 0 || knownNames.length < ids.length;
  return (
    <>
      Не хватает снимка{month ? ` за ${formatMonth(month.year, month.month)}` : ""}:{" "}
      {knownNames.length ? knownNames.join(", ") : "название счёта неизвестно"}
      {knownNames.length && hasUnknown ? "; название другого счёта неизвестно" : ""}.{" "}
    </>
  );
}
