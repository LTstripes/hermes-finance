import { useQuery } from "@tanstack/react-query";
import { useId, useLayoutEffect, useRef, useState } from "react";
import { Link } from "react-router";

import {
  getTotalIncome,
  type TotalIncome as Income,
  type TotalIncomeWindow,
} from "../api/totalIncome";
import type { MoneyValue } from "../api/types";
import { formatMonth, formatPercent, shortMonthLabel } from "../lib/format";
import { queryKeys } from "../queryClient";
import sheet from "./ReportSheet.module.css";
import styles from "./TotalIncome.module.css";
import { rubleAxisTick } from "./rubleAxis";
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
  const container = useRef<HTMLDivElement>(null);
  const [available, setAvailable] = useState(0);
  const [active, setActive] = useState<number | null>(null);
  useLayoutEffect(() => {
    const el = container.current;
    if (!el) return;
    setAvailable(el.clientWidth);
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => setAvailable(entry.contentRect.width));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
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
  const roughStep = (high - low) / 4;
  const unit = 10 ** Math.floor(Math.log10(roughStep));
  const tickStep = ([1, 2, 5, 10].find((factor) => factor * unit >= roughStep) ?? 10) * unit;
  const bottom = Math.floor(low / tickStep) * tickStep;
  const top = Math.ceil(high / tickStep) * tickStep;
  const ticks = Array.from(
    { length: Math.round((top - bottom) / tickStep) + 1 },
    (_, i) => bottom + i * tickStep,
  );
  const y = (value: number) => 203 - ((value - bottom) / (top - bottom)) * 178;
  const left = 76;
  const width = Math.max(available, left + points.length * 58 + 12);
  const step = (width - left - 12) / Math.max(1, points.length);
  const barWidth = Math.min(step * 0.55, 62);
  const current = active === null ? undefined : points[active];
  return (
    <>
      <div className={styles.chart} ref={container}>
        <div className={styles.plot} style={{ width }}>
          <svg width={width} height={246} role="img" aria-label="Весь доход по месяцам">
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
            {ticks.map((tick) => (
              <g key={tick}>
                <line
                  x1={left}
                  x2={width - 12}
                  y1={y(tick)}
                  y2={y(tick)}
                  stroke={tick === 0 ? "var(--line)" : "var(--line-2)"}
                />
                <text className={styles.tick} x={left - 8} y={y(tick) + 4} textAnchor="end">
                  {rubleAxisTick(tick)}
                </text>
              </g>
            ))}
            {points.map((point, index) => {
              let positive = 0;
              let negative = 0;
              const parts = stacks[index];
              const center = left + (index + 0.5) * step;
              const x = center - barWidth / 2;
              return (
                <g key={point.reporting_month_id}>
                  <rect
                    x={center - step / 2}
                    y={18}
                    width={step}
                    height={213}
                    fill={
                      active === index || index === points.length - 1
                        ? "var(--accent-soft)"
                        : "transparent"
                    }
                    opacity={active === index ? 0.85 : 0.42}
                    rx={4}
                  />
                  {parts.map((value, layer) => {
                    if (value === 0) return null;
                    const base = value > 0 ? positive : negative;
                    if (value > 0) positive += value;
                    else negative += value;
                    const fill =
                      layer === 0
                        ? point.salary_is_estimate
                          ? `url(#${id}-estimate)`
                          : "var(--c-bond)"
                        : layer === 1
                          ? "var(--c-dep)"
                          : `url(#${id}-bonus)`;
                    const y1 = y(base),
                      y2 = y(base + value);
                    const cap = !parts
                      .slice(layer + 1)
                      .some((part) => Math.sign(part) === Math.sign(value));
                    const r = cap ? Math.min(4, Math.abs(y1 - y2), barWidth / 2) : 0;
                    const shoulder = y2 + Math.sign(value) * r;
                    return (
                      <path
                        key={["salary", "passive", "bonus"][layer]}
                        fill={fill}
                        d={`M ${x} ${y1} V ${shoulder} Q ${x} ${y2} ${x + r} ${y2} H ${x + barWidth - r} Q ${x + barWidth} ${y2} ${x + barWidth} ${shoulder} V ${y1} Z`}
                      />
                    );
                  })}
                  <text x={center} y={225} className={styles.tick} textAnchor="middle">
                    {shortMonthLabel(point.year, point.month, index === 0)}
                  </text>
                </g>
              );
            })}
            {window.monthly_average !== null && (
              <g pointerEvents="none">
                <line
                  data-testid="total-income-average-line"
                  x1={left}
                  x2={width - 12}
                  y1={y(average)}
                  y2={y(average)}
                  stroke="var(--ink-2)"
                  strokeDasharray="5 4"
                />
                <text x={width - 12} y={y(average) - 6} textAnchor="end" className={styles.average}>
                  В среднем · {rubleAxisTick(average)}
                </text>
              </g>
            )}
          </svg>
          {points.map((point, index) => (
            <button
              type="button"
              className={styles.chartTrigger}
              style={{ left: left + index * step, width: step }}
              key={point.reporting_month_id}
              aria-label={formatMonth(point.year, point.month)}
              aria-describedby={active === index ? `${id}-tip` : undefined}
              onClick={() => setActive(index)}
              onFocus={() => setActive(index)}
              onBlur={() => setActive(null)}
              onPointerEnter={() => setActive(index)}
              onPointerLeave={() => setActive(null)}
              onKeyDown={(event) => {
                if (event.key === "Escape") setActive(null);
              }}
              data-testid={`total-income-month-${point.reporting_month_id}`}
              data-estimate={point.salary_is_estimate || undefined}
            />
          ))}
          {current && active !== null && (
            <div
              role="tooltip"
              id={`${id}-tip`}
              className={styles.tooltip}
              style={{
                left: Math.max(4, Math.min(width - 222, left + (active + 0.5) * step - 108)),
              }}
            >
              <strong>{formatMonth(current.year, current.month)}</strong>
              <dl>
                <dt>{current.salary_is_estimate ? "Зарплата · оценка" : "Зарплата"}</dt>
                <dd className="num">{moneyText(current.salary_net)}</dd>
                <dt>Пассивный доход</dt>
                <dd className="num">{moneyText(current.passive_actual)}</dd>
                {showBonus && (
                  <>
                    <dt>Премия в месяц</dt>
                    <dd className="num">{moneyText(window.bonus_smoothed_monthly)}</dd>
                  </>
                )}
              </dl>
            </div>
          )}
        </div>
      </div>
      <div className={styles.legend}>
        <span>
          <i style={{ background: "var(--c-bond)" }} />
          Зарплата
        </span>
        <span>
          <i style={{ background: "var(--c-dep)" }} />
          Пассивный доход
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
        ).map(([label, value, coverage, target], index) => (
          <div className={sheet.figure} key={label}>
            <strong
              className={`${index === 0 ? sheet.hero : sheet.figureValue} num`}
              title={moneyText(value)}
            >
              {whole(value)}
            </strong>
            <span className={sheet.figureLabel}>{label}</span>
            <Coverage window={coverage} target={target} />
          </div>
        ))}
      </div>
      {window.months_observed > 0 ? (
        <IncomeChart key={selected} data={data} window={window} />
      ) : null}
      {window.current_level !== null ? (
        <p className={styles.note} title={moneyText(window.current_level)}>
          Сейчас ≈ <span className="num">{whole(window.current_level)}</span> в месяц
        </p>
      ) : null}
      {Array.from(new Set(window.warnings)).length > 0 ? (
        <p className={styles.note} data-testid="total-income-warnings">
          {Array.from(
            new Set(
              window.warnings.map((warning) =>
                warning.replace(/^Пассивка учитывается/, "Пассивный доход учитывается"),
              ),
            ),
          ).join(". ")}
        </p>
      ) : null}
    </section>
  );
}

export function TotalIncomeHomeRow({ data }: { data: Income }) {
  const window = data.windows.calendar_year;
  return (
    <div className={styles.homeRow} data-testid="total-income-home">
      <span className={styles.kicker}>Весь доход · с начала года</span>
      <div className={styles.homeFacts}>
        <span title={moneyText(window.monthly_average)}>
          <strong className="num">{whole(window.monthly_average)}</strong> в месяц в среднем
        </span>
        {window.passive_share_pct !== null && (
          <span className={styles.note}>
            Пассивный доход · <span className="num">{formatPercent(window.passive_share_pct)}</span>
          </span>
        )}
      </div>
      <Link to="/v2/income">Доход и планы →</Link>
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
