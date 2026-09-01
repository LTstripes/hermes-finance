import type { NextMonthOutlook as NextMonthOutlookModel } from "../../api/monthCloseWorkflow";
import type { CashFlowLadderEvent, MoneyValue, UpcomingEventsWindow } from "../../api/types";
import { formatDate, formatMoney, formatMonth } from "../../lib/format";
import { DataValue, Panel } from "../ui";

const COMPONENT_LABELS: Record<string, string> = {
  coupon: "Купон",
  dividend: "Дивиденд",
  deposit_interest: "Проценты по вкладу",
  other_capital_income: "Прочий доход",
  redemption_principal: "Погашение",
};

function money(value: MoneyValue | null | undefined, fallback = "Недоступно"): string {
  if (!value) return fallback;
  return formatMoney(value.amount, { currency: value.currency === "RUB" ? "₽" : value.currency });
}

function eventLabel(event: CashFlowLadderEvent): string {
  return `${formatDate(event.expected_date)} · ${COMPONENT_LABELS[event.component] ?? event.component} · ${event.instrument_name ?? event.account_name}`;
}

function WindowSummary({ window }: { window: UpcomingEventsWindow }) {
  const hasKnownEvents = window.items.length > 0;
  return (
    <article className="final-review__event-window">
      <div className="final-review__event-heading">
        <strong>Ближайшие {window.days} дней</strong>
        <strong>{hasKnownEvents ? money(window.total_cash_flow) : "Событий не известно"}</strong>
      </div>
      <p className="muted tiny">
        {formatDate(window.from_date)} — до {formatDate(window.to_date)} · пассивный доход{" "}
        {hasKnownEvents ? money(window.passive_income) : "неизвестен"} · погашение{" "}
        {hasKnownEvents ? money(window.redemption_principal) : "неизвестно"}
      </p>
      {hasKnownEvents ? (
        <ul className="final-review__event-list">
          {window.items.map((event) => (
            <li
              key={`${event.source_kind}-${event.source_id}-${event.expected_date}-${event.component}`}
            >
              <span>{eventLabel(event)}</span>
              <strong>{money(event.expected_net_amount)}</strong>
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted">В этом окне нет известных событий.</p>
      )}
    </article>
  );
}

export function NextMonthOutlook({ outlook }: { outlook: NextMonthOutlookModel }) {
  if (!outlook.available) {
    return (
      <Panel label="После закрытия" title="Следующий месяц">
        <p className="muted">
          Данные пока недоступны: {outlook.reason_code ?? "причина не указана"}.
        </p>
      </Panel>
    );
  }

  const nextMonth = outlook.next_month;
  const hasKnownNextMonthEvents = Boolean(
    nextMonth?.has_known_events && nextMonth.known_event_count > 0,
  );
  const noKnownEvents = nextMonth ? "Нет известных событий" : "Недоступно";

  return (
    <Panel label="После закрытия" title="Что известно о следующем месяце">
      <p className="muted">
        Показаны только уже известные backend-события после закрытия{" "}
        {formatMonth(outlook.source_month.year, outlook.source_month.month)}. Будущий месяц здесь не
        создаётся.
      </p>
      <div className="final-review__status-grid">
        <DataValue label="Известных событий" value={outlook.known_event_count} />
        <DataValue
          label="Следующий месяц"
          value={nextMonth ? formatMonth(nextMonth.year, nextMonth.month) : "Недоступно"}
        />
        <DataValue
          label="Пассивный доход"
          value={hasKnownNextMonthEvents ? money(nextMonth?.passive_income) : noKnownEvents}
        />
        <DataValue
          label="Погашение · возврат капитала"
          value={hasKnownNextMonthEvents ? money(nextMonth?.redemption_principal) : noKnownEvents}
        />
        <DataValue
          label="Всего денежных потоков"
          value={hasKnownNextMonthEvents ? money(nextMonth?.total_cash_flow) : noKnownEvents}
        />
        <DataValue
          label="Оценка процентов по вкладу"
          value={
            hasKnownNextMonthEvents ? money(nextMonth?.deposit_interest_estimate) : noKnownEvents
          }
        />
      </div>
      {hasKnownNextMonthEvents && nextMonth?.items.length ? (
        <ul className="final-review__event-list">
          {nextMonth.items.map((event) => (
            <li
              key={`${event.source_kind}-${event.source_id}-${event.expected_date}-${event.component}`}
            >
              <span>{eventLabel(event)}</span>
              <strong>{money(event.expected_net_amount)}</strong>
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted">В следующем месяце нет известных событий.</p>
      )}
      <p className="muted final-review__disclosure">
        Погашение — возврат капитала, а не пассивный доход. Нулевое значение не подменяет отсутствие
        известных событий.
      </p>
      <details className="field-details">
        <summary>Показать ближайшие окна</summary>
        <div className="final-review__event-windows">
          {outlook.upcoming_14_days ? <WindowSummary window={outlook.upcoming_14_days} /> : null}
          {outlook.upcoming_30_days ? <WindowSummary window={outlook.upcoming_30_days} /> : null}
        </div>
      </details>
      {outlook.evidence_version ? (
        <details className="field-details">
          <summary>Версия backend-свидетельства</summary>
          <code>{outlook.evidence_version}</code>
        </details>
      ) : null}
    </Panel>
  );
}
