import { useQuery } from "@tanstack/react-query";
import { useId, useState } from "react";
import { Link } from "react-router";

import {
  getTotalIncome,
  type TotalIncome as Income,
  type TotalIncomeWindow,
} from "../api/totalIncome";
import type { MoneyValue } from "../api/types";
import { formatMonth, formatPercent } from "../lib/format";
import { queryKeys } from "../queryClient";
import sheet from "./ReportSheet.module.css";
import styles from "./TotalIncome.module.css";
import { isQueryReady, UiV2WidgetState } from "./UiV2StateBlocks";
import { moneyText } from "./valueFormat";
import { wholeMoneyText as whole } from "./wholeMoney";

const WINDOWS = [
  ["calendar_year", "Календарный год"],
  ["rolling_12", "12 мес"],
  ["all", "Всё"],
] as const;

/** Numbers are used exclusively to position chart marks. */
function geometry(value: MoneyValue | null): number {
  return value === null ? 0 : Number(value.amount);
}

function Coverage({ window, target = 12 }: { window: TotalIncomeWindow; target?: number }) {
  return window.months_observed < target ? (
    <small className={sheet.figureDetail}>
      за {window.months_observed} из {target} мес
    </small>
  ) : null;
}

function IncomeChart({ data, window }: { data: Income; window: TotalIncomeWindow }) {
  const id = useId().replace(/:/g, "");
  const points = data.points.filter((point) =>
    window.months_used.includes(`${point.year}-${String(point.month).padStart(2, "0")}`),
  );
  const bonus = geometry(window.bonus_smoothed_monthly);
  const showBonus = bonus > 0;
  const stacks = points.map((point) => [
    geometry(point.salary_net),
    geometry(point.passive_actual),
    showBonus ? bonus : 0,
  ]);
  const average = geometry(window.monthly_average);
  const high = Math.max(
    1,
    average,
    ...stacks.map((parts) => parts.reduce((sum, part) => sum + Math.max(0, part), 0)),
  );
  const low = Math.min(
    0,
    average,
    ...stacks.map((parts) => parts.reduce((sum, part) => sum + Math.min(0, part), 0)),
  );
  const y = (value: number) => 200 - ((value - low) / (high - low)) * 180;
  const width = Math.max(360, points.length * 62);
  const step = width / Math.max(1, points.length);
  return (
    <>
      <div className={styles.chart}>
        <svg
          viewBox={`0 0 ${width} 244`}
          style={{ minWidth: width }}
          role="img"
          aria-label="Весь доход по месяцам: зарплата, пассивка и распределённая премия"
        >
          <defs>
            <pattern id={`${id}-estimate`} width="7" height="7" patternUnits="userSpaceOnUse">
              <rect width="7" height="7" fill="var(--c-bond)" fillOpacity="0.6" />
              <path d="M-1 1L1-1M0 7L7 0M6 8L8 6" stroke="var(--surface)" strokeWidth="2" />
            </pattern>
            <pattern id={`${id}-bonus`} width="7" height="7" patternUnits="userSpaceOnUse">
              <rect width="7" height="7" fill="var(--c-stock)" fillOpacity="0.3" />
              <path d="M0 7L7 0" stroke="var(--c-stock)" strokeWidth="1" />
            </pattern>
          </defs>
          <line x1="0" x2={width} y1={y(0)} y2={y(0)} stroke="var(--line)" />
          {points.map((point, index) => {
            let positive = 0;
            let negative = 0;
            const parts = stacks[index];
            return (
              <g
                key={point.reporting_month_id}
                data-testid={`total-income-month-${point.reporting_month_id}`}
                data-estimate={point.salary_is_estimate || undefined}
              >
                <title>
                  {formatMonth(point.year, point.month)}: ЗП {moneyText(point.salary_net)}; пассивка{" "}
                  {moneyText(point.passive_actual)}
                  {showBonus ? `; премия в месяц ${moneyText(window.bonus_smoothed_monthly)}` : ""}
                </title>
                {parts.map((value, layer) => {
                  const base = value >= 0 ? positive : negative;
                  if (value >= 0) positive += value;
                  else negative += value;
                  const fill =
                    layer === 0
                      ? point.salary_is_estimate
                        ? `url(#${id}-estimate)`
                        : "var(--c-bond)"
                      : layer === 1
                        ? "var(--c-dep)"
                        : `url(#${id}-bonus)`;
                  return value === 0 ? null : (
                    <rect
                      key={["salary", "passive", "bonus"][layer]}
                      x={index * step + step * 0.22}
                      width={step * 0.56}
                      y={Math.min(y(base), y(base + value))}
                      height={Math.abs(y(base + value) - y(base))}
                      fill={fill}
                    />
                  );
                })}
                <text
                  x={(index + 0.5) * step}
                  y="223"
                  textAnchor="middle"
                  fill="var(--muted)"
                  fontSize="11"
                >
                  {String(point.month).padStart(2, "0")}.{point.year}
                </text>
              </g>
            );
          })}
          {window.monthly_average !== null ? (
            <line
              data-testid="total-income-average-line"
              x1="0"
              x2={width}
              y1={y(average)}
              y2={y(average)}
              stroke="var(--ink)"
              strokeWidth="1.5"
              strokeDasharray="6 5"
            >
              <title>В месяц в среднем: {moneyText(window.monthly_average)}</title>
            </line>
          ) : null}
        </svg>
      </div>
      <div className={styles.legend}>
        <span>
          <i style={{ background: "var(--c-bond)" }} />
          ЗП
        </span>
        <span>
          <i style={{ background: "var(--c-dep)" }} />
          Пассивка
        </span>
        {showBonus ? (
          <span data-testid="total-income-bonus-legend">
            <i className={styles.bonus} />
            Премия · в месяц
          </span>
        ) : null}
        {window.monthly_average !== null ? <span>┄ В месяц в среднем</span> : null}
      </div>
    </>
  );
}

export function TotalIncomeSection({ data }: { data: Income }) {
  const [selected, setSelected] = useState<keyof Income["windows"]>("calendar_year");
  const window = data.windows[selected];
  return (
    <section
      className={sheet.section}
      aria-labelledby="total-income-title"
      data-testid="total-income-section"
    >
      <div className={sheet.sectionHead}>
        <h2 id="total-income-title">Весь доход</h2>
        <fieldset className={sheet.segmented} aria-label="Период общего дохода">
          {WINDOWS.map(([key, label]) => (
            <button
              type="button"
              key={key}
              aria-pressed={selected === key}
              onClick={() => setSelected(key)}
            >
              {label}
            </button>
          ))}
        </fieldset>
      </div>
      <div className={sheet.figures}>
        {(
          [
            [
              "В месяц в среднем",
              window.monthly_average,
              window,
              selected === "all" ? window.bonus_target_months : 12,
            ],
            ["С начала года", data.windows.calendar_year.total_net, data.windows.calendar_year, 12],
            ["За 12 месяцев", data.windows.rolling_12.total_net, data.windows.rolling_12, 12],
          ] as const
        ).map(([label, value, coverage, target]) => (
          <div className={sheet.figure} key={label}>
            <strong className={sheet.figureValue} title={moneyText(value)}>
              {whole(value)}
            </strong>
            <span className={sheet.figureLabel}>{label}</span>
            <Coverage window={coverage} target={target} />
          </div>
        ))}
      </div>
      {window.months_observed > 0 ? <IncomeChart data={data} window={window} /> : null}
      {window.current_level !== null ? (
        <p className={styles.note} title={moneyText(window.current_level)}>
          Сейчас ≈ {whole(window.current_level)} в месяц
        </p>
      ) : null}
      {Array.from(new Set(window.warnings)).length > 0 ? (
        <p className={styles.note} data-testid="total-income-warnings">
          {Array.from(new Set(window.warnings)).join(". ")}
        </p>
      ) : null}
    </section>
  );
}

export function TotalIncomeHomeRow({ data }: { data: Income }) {
  const window = data.windows.calendar_year;
  return (
    <div className={styles.homeRow} data-testid="total-income-home">
      <Link to="/v2/income">Весь доход →</Link>
      <span title={moneyText(window.monthly_average)}>
        <strong>{whole(window.monthly_average)}</strong> в месяц в среднем
      </span>
      {window.passive_share_pct !== null ? (
        <span className={styles.note}>
          пассивка закрывает {formatPercent(window.passive_share_pct)} дохода
        </span>
      ) : null}
    </div>
  );
}

export function TotalIncomeWidget({
  monthId,
  compact = false,
}: {
  monthId: number;
  compact?: boolean;
}) {
  const query = useQuery({
    queryKey: queryKeys.totalIncome(monthId),
    queryFn: ({ signal }) => getTotalIncome(monthId, signal),
  });
  if (!isQueryReady(query) || query.data?.latest_closed_report_id !== monthId) {
    // The home row is secondary: no placeholder while loading, retry only on failure.
    if (compact && !query.isError) return null;
    return <UiV2WidgetState retry={() => void query.refetch()} />;
  }
  if (compact) {
    return query.data.windows.calendar_year.monthly_average === null ? null : (
      <TotalIncomeHomeRow data={query.data} />
    );
  }
  return <TotalIncomeSection data={query.data} />;
}
