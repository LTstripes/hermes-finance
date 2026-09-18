import { useQuery } from "@tanstack/react-query";
import { type ReactNode, useMemo } from "react";
import { Link } from "react-router";

import { getCapitalComposition } from "../api/analytics";
import { listMonths } from "../api/months";
import { Table, Td, Th } from "../components/ui";
import type { ArchiveReportRow } from "./reportsArchive";
import { formatDate, formatMonth } from "../lib/format";
import { queryKeys } from "../queryClient";
import { buildArchive, CURRENT_METHODOLOGY_ARCHIVE_NOTE, GAP_ROW_LABEL } from "./reportsArchive";
import { latestClosedMonth } from "./monthSelection";
import { isQueryReady, UiV2Loading, UiV2Notice, UiV2WidgetState } from "./UiV2StateBlocks";
import { UiV2Shell } from "./UiV2Shell";
import styles from "./UiV2Page.module.css";
import reportStyles from "./UiV2Reports.module.css";
import { moneyText as money } from "./valueFormat";

const COLUMNS = [
  "Период",
  "Статус",
  "Снимок",
  "Ликвидный капитал",
  "Активы",
  "Обязательства",
  "Действие",
] as const;

function ReportRowCells({ row }: { row: ArchiveReportRow }) {
  const point = row.point;
  return (
    <>
      <Td data-label={COLUMNS[0]}>
        <span className={reportStyles.reportCell}>
          {formatMonth(row.month.year, row.month.month)}
        </span>
      </Td>
      <Td data-label={COLUMNS[1]}>{row.statusLabel}</Td>
      <Td data-label={COLUMNS[2]}>{formatDate(row.month.snapshot_date)}</Td>
      <Td className={reportStyles.moneyCell} data-label={COLUMNS[3]} numeric>
        {point ? money(point.liquid_capital_net) : "—"}
      </Td>
      <Td className={reportStyles.moneyCell} data-label={COLUMNS[4]} numeric>
        {point ? money(point.liquid_assets_total) : "—"}
      </Td>
      <Td className={reportStyles.moneyCell} data-label={COLUMNS[5]} numeric>
        {point ? `− ${money(point.included_debts)}` : "—"}
      </Td>
      <Td data-label={COLUMNS[6]}>
        <Link to={row.actionPath}>{row.actionLabel}</Link>
      </Td>
    </>
  );
}

export default function UiV2ReportsPage() {
  const monthsQuery = useQuery({
    queryKey: queryKeys.months,
    queryFn: ({ signal }) => listMonths(signal),
    refetchOnWindowFocus: true,
  });
  const latestClosed = useMemo(() => latestClosedMonth(monthsQuery.data ?? []), [monthsQuery.data]);
  const compositionQuery = useQuery({
    enabled: latestClosed !== null,
    queryKey: queryKeys.capitalComposition,
    queryFn: ({ signal }) => getCapitalComposition(signal),
    refetchOnWindowFocus: true,
  });

  const monthsReady = isQueryReady(monthsQuery);
  const compositionReady = isQueryReady(compositionQuery);
  const moneyConfirmed =
    compositionReady &&
    latestClosed !== null &&
    compositionQuery.data?.points.at(-1)?.reporting_month_id === latestClosed.id;
  const archive = useMemo(
    () =>
      buildArchive({
        months: monthsQuery.data ?? [],
        points: compositionQuery.data?.points ?? [],
        moneyConfirmed,
      }),
    [compositionQuery.data, moneyConfirmed, monthsQuery.data],
  );
  const v1ReturnPath = latestClosed ? `/months/${latestClosed.id}` : "/";

  let content: ReactNode;
  if (monthsQuery.isError) {
    content = (
      <UiV2Notice title="Не удалось загрузить отчёты" retry={() => void monthsQuery.refetch()}>
        Список отчётов скрыт, пока подтверждённые закрытые отчёты не прочитаны.
      </UiV2Notice>
    );
  } else if (!monthsReady) {
    content = <UiV2Loading label="Проверяем закрытые отчёты…" />;
  } else if (archive.closedCount === 0) {
    content = (
      <UiV2Notice title="Закрой первый отчёт">
        Архив строится только по закрытым отчётам. Черновик не выдаётся за историю.{" "}
        <Link to="/monthly-close">Перейти к закрытию месяца →</Link>
      </UiV2Notice>
    );
  } else {
    content = (
      <>
        <div className={reportStyles.archiveIntro}>
          <p className={reportStyles.archiveNote}>{CURRENT_METHODOLOGY_ARCHIVE_NOTE}</p>
          <Link to="/v2">Мои финансы →</Link>
        </div>
        {archive.singleReportNote ? (
          <p className={reportStyles.archiveNote} data-testid="reports-single-note">
            {archive.singleReportNote}
          </p>
        ) : null}
        {archive.newerDraft ? (
          <p className={reportStyles.draftNote} data-testid="reports-draft-note">
            <strong>
              {formatMonth(archive.newerDraft.year, archive.newerDraft.month)} ещё не закрыт
            </strong>
            <span>это черновик, не отчёт.</span>
            <Link to="/v2">Мои финансы →</Link>
          </p>
        ) : null}
        {moneyConfirmed ? null : (
          <UiV2WidgetState
            retry={() => void compositionQuery.refetch()}
            title="Денежные значения отчётов временно недоступны"
          />
        )}
        <div
          data-money-state={moneyConfirmed ? "confirmed" : "unavailable"}
          data-testid="reports-archive"
        >
          {archive.groups.map((group) => (
            <section
              aria-labelledby={`reports-year-${group.year}`}
              className={reportStyles.yearGroup}
              data-testid={`reports-year-${group.year}`}
              key={group.year}
            >
              <h2 id={`reports-year-${group.year}`}>{group.year}</h2>
              <Table className={reportStyles.archiveTable}>
                <thead>
                  <tr>
                    {COLUMNS.map((column, index) => (
                      <Th key={column} numeric={index >= 3 && index <= 5}>
                        {column}
                      </Th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {group.rows.map((row) =>
                    row.kind === "gap" ? (
                      <tr
                        className={reportStyles.gapRow}
                        data-testid={`reports-gap-${row.year}-${row.month}`}
                        key={row.key}
                      >
                        <Td data-label={COLUMNS[0]}>
                          <span className={reportStyles.gapPeriod}>
                            {formatMonth(row.year, row.month)}
                          </span>
                        </Td>
                        <Td data-label={COLUMNS[1]}>{GAP_ROW_LABEL}</Td>
                        <Td data-label={COLUMNS[2]}>—</Td>
                        <Td data-label={COLUMNS[3]} numeric>
                          —
                        </Td>
                        <Td data-label={COLUMNS[4]} numeric>
                          —
                        </Td>
                        <Td data-label={COLUMNS[5]} numeric>
                          —
                        </Td>
                        <Td data-label={COLUMNS[6]}>—</Td>
                      </tr>
                    ) : (
                      <tr
                        data-current={row.isCurrent ? "true" : "false"}
                        data-testid={`reports-row-${row.month.id}`}
                        key={row.key}
                      >
                        <ReportRowCells row={row} />
                      </tr>
                    ),
                  )}
                </tbody>
              </Table>
            </section>
          ))}
        </div>
        <p className={reportStyles.archiveNote}>
          <Link to="/months">Месяцы в текущем интерфейсе →</Link>
        </p>
      </>
    );
  }

  return (
    <UiV2Shell
      busy={!monthsReady}
      header={
        <>
          <p className={styles.eyebrow}>История подтверждённых отчётов</p>
          <h1>Отчёты</h1>
          <p className={styles.subtitle}>
            Подтверждённые отчёты по закрытым месяцам. Текущий отчёт всегда открыт в «Мои финансы».
          </p>
          <p className={reportStyles.backLink}>
            <Link to="/v2">← Мои финансы</Link>
          </p>
        </>
      }
      v1ReturnPath={v1ReturnPath}
    >
      {content}
    </UiV2Shell>
  );
}
