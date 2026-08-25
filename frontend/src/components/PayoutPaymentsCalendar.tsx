import type { PayoutCalendarItem, PayoutCalendarMonth } from "../api/payouts";
import { formatDate, formatMoney, formatMonth } from "../lib/format";
import { FLOW_TYPE_LABELS, labelOf } from "../lib/labels";
import { moneyAmount } from "../lib/money";
import { Badge, EmptyState, Table, Td, Th } from "./ui";

const DECISION_LABELS: Record<string, string> = {
  keep_both: "считать обе",
  count_manual: "считать ручную",
  count_provider: "считать T-Invest",
};

function sourceBadge(item: PayoutCalendarItem) {
  if (item.source_kind === "provider") {
    return <Badge tone="info">T-Invest</Badge>;
  }
  return <Badge>Вручную</Badge>;
}

function flowChip(flowType: string, amount: string) {
  return (
    <span className={`flow-chip flow-chip--${flowType}`} key={flowType}>
      {labelOf(FLOW_TYPE_LABELS, flowType)} {formatMoney(amount)}
    </span>
  );
}

function isNonZeroMoney(value: string): boolean {
  return !/^[+-]?0+(?:\.0+)?$/.test(value.trim());
}

function monthChips(month: PayoutCalendarMonth) {
  const chips = [
    [month.coupon, "coupon"],
    [month.dividend, "dividend"],
    [month.interest, "interest"],
    [month.redemption, "redemption"],
    [month.other, "other"],
  ] as const;
  return chips
    .filter(([value]) => isNonZeroMoney(moneyAmount(value)))
    .map(([value, flowType]) => flowChip(flowType, moneyAmount(value)));
}

export function PayoutPaymentsCalendar({ months }: { months: PayoutCalendarMonth[] }) {
  if (months.length === 0) {
    return (
      <EmptyState
        description="Ручные ожидаемые выплаты и применённые выплаты T-Invest появятся здесь."
        inline
        title="Нет ожидаемых выплат"
      />
    );
  }

  return (
    <div className="payments-calendar">
      {months.map((month) => (
        <details className="payments-calendar__month" key={`${month.year}-${month.month}`}>
          <summary className="payments-calendar__head">
            <span className="payments-calendar__chevron" aria-hidden="true" />
            <span className="payments-calendar__month-name">
              {formatMonth(month.year, month.month)}
            </span>
            <span className="payments-calendar__count">{month.items.length} выплат</span>
            <span className="payments-calendar__chips">{monthChips(month)}</span>
            <span className="payments-calendar__passive">
              Пассивный доход: <strong>{formatMoney(moneyAmount(month.passive_net))}</strong>
              {" · "}весь денежный поток:{" "}
              <strong>{formatMoney(moneyAmount(month.total_net))}</strong>
            </span>
          </summary>
          <Table aria-label={`Выплаты ${formatMonth(month.year, month.month)}`}>
            <thead>
              <tr>
                <Th>Дата</Th>
                <Th>Тип</Th>
                <Th>Счёт / инструмент</Th>
                <Th>Источник</Th>
                <Th numeric>Сумма</Th>
              </tr>
            </thead>
            <tbody>
              {month.items.map((item) => {
                const redemption = item.flow_type === "redemption";
                return (
                  <tr
                    className={redemption ? "row--muted" : undefined}
                    key={`${item.source_kind}-${item.source_id}`}
                  >
                    <Td>{formatDate(item.expected_date)}</Td>
                    <Td>
                      <span className={`flow-chip flow-chip--${item.flow_type}`}>
                        {labelOf(FLOW_TYPE_LABELS, item.flow_type)}
                      </span>
                      {redemption ? (
                        <div className="muted tiny">возврат капитала, не доход</div>
                      ) : null}
                    </Td>
                    <Td>
                      <div>
                        <strong>{item.instrument_name ?? `#${item.instrument_id}`}</strong>
                      </div>
                      <div className="muted tiny">{item.account_name}</div>
                    </Td>
                    <Td>
                      <div className="stack-8">
                        {sourceBadge(item)}
                        {item.source_kind === "manual" && item.manual_source ? (
                          <span className="muted tiny">{item.manual_source}</span>
                        ) : null}
                        {item.source_kind === "provider" ? (
                          <span className="muted tiny">
                            {item.provider_lifecycle ?? "active"}
                            {item.counting_decision
                              ? ` · ${DECISION_LABELS[item.counting_decision] ?? item.counting_decision}`
                              : ""}
                          </span>
                        ) : null}
                      </div>
                    </Td>
                    <Td numeric>
                      {formatMoney(moneyAmount(item.expected_net_amount))}
                      {item.is_approximate ? (
                        <div className="muted tiny">приблизительно</div>
                      ) : null}
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        </details>
      ))}
    </div>
  );
}
