import { useMemo } from "react";
import type { TooltipContentProps } from "recharts";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { AccountResultPoint, InstrumentClassResultPoint } from "../../api/types";
import { formatMoneyDelta } from "../../lib/format";
import { moneyAmount, sumMoneyAmounts } from "../../lib/money";
import { EmptyState, Td, Th } from "../ui";

const ACCOUNT_TYPE_LABELS: Record<string, string> = {
  brokerage: "Брокерский",
  iis: "ИИС",
  deposit: "Депозит",
  savings: "Накопительный",
  cash: "Наличные",
  other: "Прочее",
};

const INSTRUMENT_CLASS_LABELS: Record<string, string> = {
  stock: "Акции",
  bond: "Облигации",
  fund: "Фонды",
  currency: "Валюта",
  gold: "Золото",
  other: "Прочее",
};

type AccountBar = {
  key: string;
  name: string;
  accountType: string;
  cash: number;
  unrealized: number;
  cashAmount: string;
  unrealizedAmount: string;
};

function buildBars(accounts: AccountResultPoint[]): AccountBar[] {
  return accounts.map((account) => {
    const cashAmount = moneyAmount(account.cash_income);
    const unrealizedAmount = moneyAmount(account.unrealized_result);
    return {
      key: String(account.account_id),
      name: account.account_name,
      accountType: ACCOUNT_TYPE_LABELS[account.account_type] ?? account.account_type,
      // Axis position only — display always uses formatMoneyDelta on strings.
      cash: Number(cashAmount),
      unrealized: Number(unrealizedAmount),
      cashAmount,
      unrealizedAmount,
    };
  });
}

function ResultTooltip({ active, payload }: TooltipContentProps) {
  const datum = (payload?.[0]?.payload ?? undefined) as AccountBar | undefined;
  if (!active || !datum) {
    return null;
  }
  const series = payload?.[0];
  const amount = series?.dataKey === "unrealized" ? datum.unrealizedAmount : datum.cashAmount;
  return (
    <div className="chart-tooltip">
      <strong>{datum.name}</strong>
      <span className="chart-tooltip__amount">{formatMoneyDelta(amount)}</span>
    </div>
  );
}

function resultTableRow(key: string, label: string, cash: string, unrealized: string) {
  return (
    <tr key={key}>
      <Td>{label}</Td>
      <Td numeric>{formatMoneyDelta(cash)}</Td>
      <Td numeric>{formatMoneyDelta(unrealized)}</Td>
      <Td numeric>{formatMoneyDelta(sumMoneyAmounts([cash, unrealized]))}</Td>
    </tr>
  );
}

export function InvestmentResultChart({
  accounts,
  classes,
}: {
  accounts: AccountResultPoint[];
  classes: InstrumentClassResultPoint[];
}) {
  const bars = useMemo(() => buildBars(accounts), [accounts]);

  const hasData = bars.length > 0 || classes.length > 0;
  if (!hasData) {
    return (
      <EmptyState
        description="Добавь позиции или денежные события в закрытые месяцы — результат появится здесь."
        title="Нет данных о результате"
      />
    );
  }

  return (
    <section aria-label="Результат по счетам и классам активов" className="investment-result">
      {bars.length > 0 && (
        <div className="investment-result__chart">
          <ResponsiveContainer height={260} width="100%">
            <BarChart
              accessibilityLayer
              data={bars}
              margin={{ bottom: 4, left: 0, right: 8, top: 8 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="var(--line-soft)" vertical={false} />
              <XAxis
                dataKey="name"
                interval={0}
                stroke="var(--muted)"
                tick={{ fill: "var(--muted)", fontSize: 12 }}
                tickFormatter={(value: string) =>
                  value.length > 14 ? `${value.slice(0, 13)}…` : value
                }
              />
              <YAxis
                stroke="var(--muted)"
                tick={{ fill: "var(--muted)", fontSize: 12 }}
                width={70}
              />
              <Tooltip
                content={(props) => <ResultTooltip {...props} />}
                cursor={{ fill: "var(--line-soft)" }}
              />
              <Legend />
              <Bar dataKey="cash" fill="#27734c" isAnimationActive={false} name="Денежный доход" />
              <Bar
                dataKey="unrealized"
                fill="#9a6a1d"
                isAnimationActive={false}
                name="Нереализованный результат"
              />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      <div className="investment-result__tables">
        {bars.length > 0 && (
          <table className="investment-result__table">
            <caption className="visually-hidden">Результат по счетам</caption>
            <thead>
              <tr>
                <Th>Счёт</Th>
                <Th>Тип</Th>
                <Th numeric>Денежный доход</Th>
                <Th numeric>Нереализованный</Th>
                <Th numeric>Итог</Th>
              </tr>
            </thead>
            <tbody>
              {bars.map((bar) =>
                resultTableRow(
                  bar.key,
                  `${bar.name} (${bar.accountType})`,
                  bar.cashAmount,
                  bar.unrealizedAmount,
                ),
              )}
            </tbody>
          </table>
        )}

        {classes.length > 0 && (
          <table className="investment-result__table">
            <caption className="visually-hidden">Результат по классам активов</caption>
            <thead>
              <tr>
                <Th>Класс</Th>
                <Th numeric>Денежный доход</Th>
                <Th numeric>Нереализованный</Th>
                <Th numeric>Итог</Th>
              </tr>
            </thead>
            <tbody>
              {classes.map((item) => {
                const label = INSTRUMENT_CLASS_LABELS[item.instrument_type] ?? item.instrument_type;
                return resultTableRow(
                  item.instrument_type,
                  label,
                  moneyAmount(item.realized_result),
                  moneyAmount(item.unrealized_result),
                );
              })}
            </tbody>
          </table>
        )}

        <p className="chart-note">
          Точная доходность периода появится позже — по модифицированному Дитцу (MASTER_SPEC
          §10.13). Сейчас показан денежный результат: полученные купоны, дивиденды и проценты (net),
          реализованный P&amp;L и нереализованный результат позиций. Погашения облигаций и
          пополнения не считаются доходом.
        </p>
      </div>
    </section>
  );
}
