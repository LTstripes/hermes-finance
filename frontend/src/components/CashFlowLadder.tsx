import type {
  CashFlowLadder as CashFlowLadderModel,
  CashFlowLadderEvent,
  UpcomingEventsWindow,
} from "../api/types";
import { Table, Td, Th } from "./ui";
import { formatDate, formatMoney, formatMonth } from "../lib/format";
import { isBlankMoney, moneyAmount } from "../lib/money";

const COMPONENT_LABELS: Record<string, string> = {
  coupon: "Купоны",
  dividend: "Дивиденды",
  deposit_interest: "Вклады",
  other_capital_income: "Прочее",
  redemption_principal: "Погашение",
};

function componentLabel(component: string): string {
  return COMPONENT_LABELS[component] ?? component;
}

function sourceLabel(event: CashFlowLadderEvent): string {
  if (event.source_kind === "deposit_forecast") return "Снимок вклада";
  if (event.source_kind === "provider") return `Провайдер: ${event.provider ?? event.source}`;
  return `Вручную: ${event.source}`;
}

function EventList({ window }: { window: UpcomingEventsWindow }) {
  return window.items.length === 0 ? (
    <p className="muted">Событий в этом окне нет.</p>
  ) : (
    <ul className="cash-flow-ladder__events">
      {window.items.map((event) => (
        <li
          key={`${event.source_kind}-${event.source_id}-${event.expected_date}-${event.component}`}
        >
          <span>
            <strong>{formatDate(event.expected_date)}</strong> · {componentLabel(event.component)} ·{" "}
            {event.instrument_name ?? event.account_name}
          </span>
          <strong>{formatMoney(moneyAmount(event.expected_net_amount))}</strong>
        </li>
      ))}
    </ul>
  );
}

function WindowCard({ window }: { window: UpcomingEventsWindow }) {
  return (
    <article className="cash-flow-ladder__window">
      <div className="cash-flow-ladder__window-heading">
        <h3>Ближайшие {window.days} дней</h3>
        <strong>{formatMoney(moneyAmount(window.total_cash_flow))}</strong>
      </div>
      <p className="muted tiny">
        {formatDate(window.from_date)} — до {formatDate(window.to_date)} · пассивный доход{" "}
        {formatMoney(moneyAmount(window.passive_income))}
        {!isBlankMoney(moneyAmount(window.redemption_principal))
          ? ` · погашение ${formatMoney(moneyAmount(window.redemption_principal))}`
          : ""}
      </p>
      <EventList window={window} />
    </article>
  );
}

export function CashFlowLadder({ ladder }: { ladder: CashFlowLadderModel }) {
  return (
    <div className="cash-flow-ladder stack-12">
      <fieldset className="cash-flow-ladder__windows">
        <legend className="sr-only">Ближайшие ожидаемые события</legend>
        <WindowCard window={ladder.upcoming_14_days} />
        <WindowCard window={ladder.upcoming_30_days} />
      </fieldset>

      <div className="cash-flow-ladder__note">
        <strong>На {formatDate(ladder.as_of_date)}</strong> · погашение — возврат капитала, не
        пассивный доход.
        {ladder.warnings.map((warning) => (
          <span className="muted" key={warning}>
            {" "}
            {warning}
          </span>
        ))}
      </div>

      <Table className="cash-flow-ladder__table">
        <caption className="sr-only">12-месячная лестница ожидаемых денежных потоков</caption>
        <thead>
          <tr>
            <Th>Месяц</Th>
            <Th numeric>Купоны</Th>
            <Th numeric>Дивиденды</Th>
            <Th numeric>Вклады</Th>
            <Th numeric>Прочее</Th>
            <Th numeric>Погашение</Th>
            <Th numeric>Итого</Th>
          </tr>
        </thead>
        <tbody>
          {ladder.months.map((month) => (
            <tr key={`${month.year}-${month.month}`}>
              <Td>
                <strong>{formatMonth(month.year, month.month)}</strong>
                {month.is_approximate ? <div className="muted tiny">есть оценка</div> : null}
              </Td>
              <Td numeric>{formatMoney(moneyAmount(month.coupon))}</Td>
              <Td numeric>{formatMoney(moneyAmount(month.dividend))}</Td>
              <Td numeric>{formatMoney(moneyAmount(month.deposit_interest))}</Td>
              <Td numeric>{formatMoney(moneyAmount(month.other_capital_income))}</Td>
              <Td numeric>{formatMoney(moneyAmount(month.redemption_principal))}</Td>
              <Td numeric>
                <strong>{formatMoney(moneyAmount(month.total_cash_flow))}</strong>
              </Td>
            </tr>
          ))}
        </tbody>
      </Table>

      <details className="field-details">
        <summary>Источники и provenance</summary>
        <div className="cash-flow-ladder__provenance">
          {ladder.months
            .flatMap((month) => month.items)
            .map((event) => (
              <div
                key={`${event.source_kind}-${event.source_id}-${event.expected_date}-${event.component}`}
              >
                {formatDate(event.expected_date)} · {componentLabel(event.component)} ·{" "}
                {event.instrument_name ?? event.account_name} · {sourceLabel(event)} · id{" "}
                {event.source_id}
                {event.reconciliation_id ? ` · reconciliation ${event.reconciliation_id}` : ""}
                {event.is_approximate ? " · приблизительно" : ""}
              </div>
            ))}
          {ladder.months.every((month) => month.items.length === 0) ? (
            <p className="muted">Источников пока нет.</p>
          ) : null}
        </div>
      </details>
    </div>
  );
}
