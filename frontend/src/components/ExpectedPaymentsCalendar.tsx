import type { ExpectedCalendarMonth } from "../api/types";
import { formatDate, formatMoney, formatMonth } from "../lib/format";
import { FLOW_TYPE_LABELS, labelOf } from "../lib/labels";
import { moneyAmount } from "../lib/money";
import { EmptyState, Table, Td, Th } from "./ui";

function flowChip(flowType: string, amount: string) {
  return (
    <span className={`flow-chip flow-chip--${flowType}`} key={flowType}>
      {labelOf(FLOW_TYPE_LABELS, flowType)} {formatMoney(amount)}
    </span>
  );
}

function monthChips(month: ExpectedCalendarMonth) {
  const chips = [
    [month.coupon, "coupon"],
    [month.dividend, "dividend"],
    [month.interest, "interest"],
    [month.redemption, "redemption"],
    [month.other, "other"],
  ] as const;
  return chips
    .filter(([value]) => Number(moneyAmount(value)) > 0)
    .map(([value, flowType]) => flowChip(flowType, moneyAmount(value)));
}

export function ExpectedPaymentsCalendar({ months }: { months: ExpectedCalendarMonth[] }) {
  if (months.length === 0) {
    return (
      <EmptyState
        description="Добавь ожидаемые выплаты — календарь на 12 месяцев появится здесь."
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
            <span className="payments-calendar__month-name">
              {formatMonth(month.year, month.month)}
            </span>
            <span className="payments-calendar__chips">{monthChips(month)}</span>
            <span className="payments-calendar__passive">
              Пассивный доход, нетто: <strong>{formatMoney(moneyAmount(month.passive_net))}</strong>
            </span>
          </summary>
          <Table>
            <thead>
              <tr>
                <Th>Дата</Th>
                <Th>Тип</Th>
                <Th>Счёт / инструмент</Th>
                <Th numeric>Нетто</Th>
              </tr>
            </thead>
            <tbody>
              {month.items.map((item) => (
                <tr key={item.id}>
                  <Td>{formatDate(item.expected_date)}</Td>
                  <Td>
                    <span className={`flow-chip flow-chip--${item.flow_type}`}>
                      {labelOf(FLOW_TYPE_LABELS, item.flow_type)}
                    </span>
                  </Td>
                  <Td>
                    <div>{item.account_name}</div>
                    <div className="muted tiny">
                      {item.instrument_name ?? "—"}
                      {item.is_approximate ? " · приблизительно" : ""}
                      {!item.is_confirmed ? " · не подтверждено" : ""}
                    </div>
                  </Td>
                  <Td numeric>{formatMoney(moneyAmount(item.expected_net_amount))}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </details>
      ))}
    </div>
  );
}
