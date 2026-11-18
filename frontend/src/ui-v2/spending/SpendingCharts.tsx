import { useId, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  Line,
  LineChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { SpendingHistoryItem, SpendingMonth } from "../../api/spending";
import type { MoneyValue } from "../../api/types";
import { CssResponsiveContainer } from "../../components/charts/CssResponsiveContainer";
import { Table, Td, Th } from "../../components/ui";
import { formatMonthKey } from "../../lib/format";
import { rubleAxisTick } from "../rubleAxis";
import sheet from "../ReportSheet.module.css";
import { wholeMoneyText } from "../wholeMoney";
import {
  coverageLabel,
  isNonzero,
  Money,
  shiftMonth,
  typeColors,
  typeLabels,
  types,
} from "./common";
import { spendingMonthForm } from "../uiV2Copy";
import styles from "./Spending.module.css";

export function coordinate(value?: MoneyValue | null) {
  return value == null ? null : Number(value.amount);
}

const shortMonths = [
  "янв",
  "фев",
  "мар",
  "апр",
  "май",
  "июн",
  "июл",
  "авг",
  "сен",
  "окт",
  "ноя",
  "дек",
];
const ticks = [1, 5, 10, 15, 20, 25, 31];
const columns = ["Месяц", ...types.map((type) => typeLabels[type]), "Итого", "Данные"];

function HistoryTick({
  x = 0,
  y = 0,
  index = 0,
  item,
  mini,
}: {
  x?: number;
  y?: number;
  index?: number;
  item: SpendingHistoryItem;
  mini: boolean;
}) {
  const number = Number(item.month.slice(5));
  return (
    <text
      x={x}
      y={y + 6}
      fill={item.loaded ? "var(--muted)" : "var(--faint)"}
      textAnchor="middle"
      fontSize={11}
    >
      {!item.loaded && (
        <tspan x={x} dy={-11}>
          —
        </tspan>
      )}
      <tspan x={x} dy={item.loaded ? 0 : 11}>
        {shortMonths[number - 1]}
      </tspan>
      {(index === 0 || number === 1) && (
        <tspan x={x} dy={13}>
          {item.month.slice(0, 4)}
        </tspan>
      )}
      {!mini && item.has_statement && !item.has_manual && (
        <tspan x={x} dy={13}>
          ○
        </tspan>
      )}
    </text>
  );
}
function historyTip(item: SpendingHistoryItem, mini: boolean) {
  if (!item.loaded) return `${formatMonthKey(item.month)} · Нет данных`;
  return [
    `${formatMonthKey(item.month)}: ${wholeMoneyText(item.total)}`,
    ...(!mini
      ? types.map((type) => `${typeLabels[type]}: ${wholeMoneyText(item.by_type[type])}`)
      : []),
    coverageLabel(item),
    isNonzero(item.refunds_total) ? `Возвраты: ${wholeMoneyText(item.refunds_total)}` : "",
    !mini && isNonzero(item.month_entries_total)
      ? `в т. ч. записи месяца ${wholeMoneyText(item.month_entries_total)}`
      : "",
  ]
    .filter(Boolean)
    .join("\n");
}
export function HistoryChart({
  items,
  selected,
  selectMonth,
  mini = false,
}: {
  items: SpendingHistoryItem[];
  selected: string;
  selectMonth: (month: string) => void;
  mini?: boolean;
}) {
  const pattern = useId();
  const [table, setTable] = useState(false);
  const keys = mini ? (["category"] as const) : types;
  const data = items.map((item) => {
    const amounts = { category: item.total, ...item.by_type };
    const points = keys.map((key) => Math.max(0, coordinate(amounts[key]) ?? 0));
    return {
      ...item,
      points,
      top: points.reduce((top, point, index) => (point > 0 ? index : top), -1),
      label: item.month === selected && item.loaded ? wholeMoneyText(item.total) : "",
    };
  });
  const drawTick = (props: { x: string | number; y: string | number; index: number }) => {
    const item = items[props.index];
    return item ? (
      <HistoryTick
        x={Number(props.x)}
        y={Number(props.y)}
        index={props.index}
        item={item}
        mini={mini}
      />
    ) : (
      <g />
    );
  };
  return (
    <>
      <div
        className={styles.chartFrame}
        data-testid={mini ? "spending-category-history" : "spending-history"}
      >
        <CssResponsiveContainer height={mini ? 120 : 270}>
          <BarChart
            accessibilityLayer={false}
            data={data}
            margin={{ top: 20, right: 8, bottom: 0, left: 0 }}
          >
            <defs>
              <pattern
                id={pattern}
                patternUnits="userSpaceOnUse"
                width="5"
                height="5"
                patternTransform="rotate(45)"
              >
                <path d="M 0 0 L 0 5" stroke="var(--surface)" strokeOpacity=".65" strokeWidth="2" />
              </pattern>
            </defs>
            <CartesianGrid vertical={false} stroke="var(--line-2)" />
            <XAxis
              axisLine={{ stroke: "var(--line-2)" }}
              tickLine={false}
              dataKey="month"
              height={mini ? 30 : 48}
              interval={items.length > 16 ? "preserveStartEnd" : 0}
              tick={drawTick}
            />
            <YAxis
              axisLine={false}
              tickLine={false}
              tickFormatter={rubleAxisTick}
              tickCount={5}
              width={62}
              tick={{ fill: "var(--muted)", fontSize: 11 }}
              domain={[0, "auto"]}
            />
            {keys.map((key, index) => (
              <Bar
                key={key}
                dataKey={(row: (typeof data)[number]) => (row.loaded ? row.points[index] : null)}
                stackId="types"
                maxBarSize={42}
                isAnimationActive={false}
                shape={({
                  x,
                  y,
                  width,
                  height,
                  payload,
                  index: itemIndex,
                }: {
                  x?: number;
                  y?: number;
                  width?: number;
                  height?: number;
                  payload?: (typeof data)[number];
                  index?: number;
                }) => {
                  if (x == null || y == null || width == null || height == null || height <= 0)
                    return <g />;
                  const row = payload ?? data[itemIndex ?? -1];
                  if (!row) return <g />;
                  const top = row.top === index;
                  const radius = top ? Math.min(4, width / 2, height) : 0;
                  const bottom = y + Math.max(0, height - (index === 0 ? 0 : 2));
                  const d = `M${x},${bottom}V${y + radius}Q${x},${y} ${x + radius},${y}H${x + width - radius}Q${x + width},${y} ${x + width},${y + radius}V${bottom}Z`;
                  return (
                    <g opacity={row.month === selected ? 1 : 0.45}>
                      <path d={d} fill={key === "category" ? "var(--accent)" : typeColors[key]} />
                      {row.partial && <path d={d} fill={`url(#${pattern})`} />}
                    </g>
                  );
                }}
              >
                {data.map((item) => (
                  <Cell key={item.month} />
                ))}
                <LabelList
                  dataKey={(row: (typeof data)[number]) => (row.top === index ? row.label : "")}
                  position="top"
                  fill="var(--ink)"
                  fontSize={12}
                />
              </Bar>
            ))}
          </BarChart>
        </CssResponsiveContainer>
        <div className={styles.monthButtons}>
          {items.map((item) => (
            <button
              key={item.month}
              type="button"
              onClick={() => selectMonth(item.month)}
              aria-label={`${formatMonthKey(item.month)}: ${item.loaded ? `${wholeMoneyText(item.total)}, ${coverageLabel(item).toLowerCase()}` : "Нет данных"}`}
              aria-pressed={item.month === selected}
            >
              <span aria-hidden="true">{historyTip(item, mini)}</span>
            </button>
          ))}
        </div>
      </div>
      {!mini && (
        <>
          <ul className={styles.legend}>
            {types.map((type) => (
              <li key={type}>
                <span className={styles.swatch} style={{ background: typeColors[type] }} />
                {typeLabels[type]}
              </li>
            ))}
            {items.some((item) => item.partial) && (
              <li>
                <span className={`${styles.swatch} ${styles.hatch}`} />
                Частичный месяц
              </li>
            )}
            {items.some((item) => item.has_statement && !item.has_manual) && (
              <li>○ Только выписка</li>
            )}
            {items.some((item) => !item.loaded) && <li>— Нет данных</li>}
          </ul>
          <button
            className={`btn btn--ghost ${styles.sectionLink}`}
            type="button"
            aria-expanded={table}
            onClick={() => setTable(!table)}
          >
            Таблица
          </button>
          {table && (
            <Table>
              <thead>
                <tr>
                  {columns.map((label) => (
                    <Th key={label}>{label}</Th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.month}>
                    <Td>
                      <button
                        type="button"
                        className={`btn btn--ghost ${styles.sectionLink}`}
                        onClick={() => selectMonth(item.month)}
                      >
                        {formatMonthKey(item.month)}
                      </button>
                    </Td>
                    {types.map((type) => (
                      <Td numeric key={type}>
                        <Money value={item.by_type[type]} />
                      </Td>
                    ))}
                    <Td numeric>
                      <Money value={item.total} />
                    </Td>
                    <Td>{coverageLabel(item)}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </>
      )}
    </>
  );
}

export function DailyChart({ month, daily }: { month: string; daily: SpendingMonth["daily"] }) {
  const previous = daily.previous;
  const previousMonth = shiftMonth(month, -1);
  const points = Array.from({ length: 31 }, (_, index) => {
    const day = index + 1;
    const now = daily.current[index]?.cumulative;
    const past = previous?.points[index]?.cumulative;
    const last = day === daily.current.at(-1)?.day;
    return { day, now, past, current: coordinate(now), previous: coordinate(past), last };
  });
  const omitted = [
    isNonzero(daily.undated_total) ? `без даты ${wholeMoneyText(daily.undated_total)}` : "",
    isNonzero(daily.month_entries_total)
      ? `записи месяца ${wholeMoneyText(daily.month_entries_total)}`
      : "",
  ].filter(Boolean);
  return (
    <>
      {daily.current.length > 0 && (
        <div data-testid="spending-daily">
          <CssResponsiveContainer height={240}>
            <LineChart data={points} margin={{ top: 18, right: 68, bottom: 0, left: 0 }}>
              <CartesianGrid vertical={false} stroke="var(--line-2)" />
              <XAxis
                dataKey="day"
                type="number"
                domain={[1, 31]}
                ticks={ticks}
                tickLine={false}
                tick={{ fill: "var(--muted)", fontSize: 11 }}
              />
              <YAxis
                tickFormatter={rubleAxisTick}
                width={58}
                tickCount={5}
                domain={([minimum, maximum]) => [Math.min(0, minimum), Math.max(0, maximum)]}
                tickLine={false}
                axisLine={false}
                tick={{ fill: "var(--muted)", fontSize: 11 }}
              />
              <Tooltip
                cursor={{ stroke: "var(--faint)" }}
                content={({ active, label }) => {
                  const point = points.find((item) => item.day === Number(label));
                  if (!active || !point || (!point.now && !point.past)) return null;
                  return (
                    <div className={styles.chartTip}>
                      {point.day} {spendingMonthForm(month, "genitive")}:{" "}
                      <Money value={point.now} />
                      {point.past && (
                        <>
                          {" "}
                          · в {spendingMonthForm(previousMonth, "prepositional")} к этому дню{" "}
                          <Money value={point.past} />
                        </>
                      )}
                    </div>
                  );
                }}
              />
              {previous && (
                <Line
                  dataKey="previous"
                  stroke="var(--faint)"
                  strokeWidth={2}
                  dot={false}
                  isAnimationActive={false}
                />
              )}
              <Line
                dataKey="current"
                stroke="var(--accent)"
                strokeWidth={2}
                isAnimationActive={false}
                dot={({
                  cx,
                  cy,
                  payload,
                }: {
                  cx?: number;
                  cy?: number;
                  payload?: (typeof points)[number];
                }) =>
                  payload?.last && cx != null && cy != null ? (
                    <g key={payload.day}>
                      <circle cx={cx} cy={cy} r={4} fill="var(--accent)" />
                      <text x={cx + 8} y={cy + 4} fontSize={11} fill="var(--ink)">
                        {wholeMoneyText(payload.now)}
                      </text>
                    </g>
                  ) : (
                    <g key={payload?.day} />
                  )
                }
              />
            </LineChart>
          </CssResponsiveContainer>
        </div>
      )}
      {previous && (
        <ul className={styles.legend}>
          <li>
            <span className={styles.swatch} style={{ background: "var(--accent)" }} />
            {formatMonthKey(month)}
          </li>
          <li>
            <span className={styles.swatch} style={{ background: "var(--faint)" }} />
            {formatMonthKey(previousMonth)}
          </li>
        </ul>
      )}
      {!previous && daily.previous_unavailable_reason && (
        <p className={sheet.muted}>
          {formatMonthKey(previousMonth).split(/\s/)[0]} не с чем сравнить:{" "}
          {daily.previous_unavailable_reason === "partial"
            ? "месяц загружен частично"
            : "не загружен"}
        </p>
      )}
      {!!omitted.length && <p className={sheet.gapNote}>Не на линии: {omitted.join(", ")}.</p>}
    </>
  );
}
