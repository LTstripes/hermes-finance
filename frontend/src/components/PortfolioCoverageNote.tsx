import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { listAccounts } from "../api/accounts";
import type { PortfolioSourceCoverage } from "../api/types";
import { formatMonth } from "../lib/format";
import { queryKeys } from "../queryClient";
import styles from "./PortfolioCoverageNote.module.css";

type CoverageNoteProps = {
  coverage: PortfolioSourceCoverage | null | undefined;
  month?: { year: number; month: number };
  relatedCoverages?: Array<PortfolioSourceCoverage | null | undefined>;
};

/** The API owns source coverage; this component only explains its result. */
export function PortfolioCoverageNote({
  coverage,
  month,
  relatedCoverages = [],
}: CoverageNoteProps) {
  if (!coverage) return null;
  const pending = coverage.source_account_financial_coverage?.status === "partial";
  if (coverage.status === "complete" && !pending) return null;

  const missing = coverage.reason_codes.includes("active_account_snapshot_missing");
  // Comparisons can omit IDs from their combined coverage, while both endpoints retain them.
  const related = relatedCoverages.filter(
    (item): item is PortfolioSourceCoverage =>
      !!item &&
      (item.reason_codes.includes("active_account_snapshot_missing") ||
        item.missing_account_ids.length > 0),
  );
  const ids = [
    ...new Set([
      ...coverage.missing_account_ids,
      ...related.flatMap((item) => item.missing_account_ids),
    ]),
  ];
  const unidentified = related.some(
    (item) =>
      item.reason_codes.includes("active_account_snapshot_missing") &&
      item.missing_account_ids.length === 0,
  );

  if (missing || (coverage.status === "unavailable" && ids.length > 0)) {
    return (
      <CoverageNoteWithNames
        coverage={coverage}
        month={month}
        ids={ids}
        unidentified={unidentified}
      />
    );
  }
  return <CoverageNote coverage={coverage} month={month} />;
}

function CoverageNoteWithNames({
  coverage,
  month,
  ids,
  unidentified,
}: {
  coverage: PortfolioSourceCoverage;
  month?: { year: number; month: number };
  ids: number[];
  unidentified: boolean;
}) {
  const names = useMissingAccountNames(ids, unidentified);
  return <CoverageNote coverage={coverage} month={month} names={names} plural={ids.length > 1} />;
}

/** Use the same account-name resolution in other warnings about missing snapshots. */
export function MissingAccountNames({ ids }: { ids: number[] }) {
  const names = useMissingAccountNames(ids, false);
  return names ? <>: {names}</> : null;
}

function useMissingAccountNames(ids: number[], unidentified: boolean): string | undefined {
  const accounts = useQuery({
    queryKey: queryKeys.accounts,
    queryFn: ({ signal }) => listAccounts(signal),
    enabled: ids.length > 0,
  });
  const knownNames = ids
    .map((id) => accounts.data?.find((account) => account.id === id)?.name?.trim())
    .filter((name): name is string => Boolean(name));
  const unknownCount = ids.length - knownNames.length;
  if (ids.length > 0 && accounts.isPending) return undefined;
  if (knownNames.length === 0) return "название счёта неизвестно";
  const unknownNames =
    unknownCount === 1
      ? "; название другого счёта неизвестно"
      : unknownCount > 1
        ? "; названия остальных счетов неизвестны"
        : "";
  const unknownPeriod = unidentified ? "; счёт для части данных не уточнён" : "";
  return `${knownNames.join(", ")}${unknownNames}${unknownPeriod}`;
}

function CoverageNote({
  coverage,
  month,
  names,
  plural = false,
}: {
  coverage: PortfolioSourceCoverage;
  month?: { year: number; month: number };
  names?: string;
  plural?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const pending = coverage.source_account_financial_coverage?.status === "partial";
  const missing = coverage.reason_codes.includes("active_account_snapshot_missing");
  const suffix = names ? `: ${names}` : "";
  const missingLabel = plural ? "нет снимков счетов" : "нет снимка счёта";
  const label =
    coverage.status === "unavailable"
      ? `Нет снимков капитала${names ? `; ${missingLabel}${suffix}` : ""}`
      : pending
        ? `Частичный известный итог: разбор источника не завершён${missing ? `; ${missingLabel}${suffix}` : ""}`
        : missing
          ? `Частично: ${missingLabel}${suffix}`
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
                  ? `Не хватает ${plural ? "снимков" : "снимка"}${month ? ` за ${formatMonth(month.year, month.month)}` : ""}${names ? `: ${names}. ` : ". Загружаются названия счетов. "}`
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
