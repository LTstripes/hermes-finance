import type { NextMonthOutlook as NextMonthOutlookModel } from "../../api/monthCloseWorkflow";
import type { CashFlowLadderEvent, MoneyValue, UpcomingEventsWindow } from "../../api/types";
import { formatDate, formatMonth } from "../../lib/format";
import { eventLabel as ownerEventLabel, PRINCIPAL_REPAYMENT_LABEL } from "../../ui-v2/uiV2Copy";
import { DataValue, MoneyAmount, Panel } from "../ui";

/** #650: single money presentation shared with FinalMonthReview cards. */
function moneyValue(value: MoneyValue | null | undefined, fallback = "Недоступно") {
  if (!value) return <MoneyAmount amount={null} empty={fallback} />;
  return (
    <MoneyAmount
      amount={value}
      currency={value.currency === "RUB" ? "₽" : value.currency}
      empty={fallback}
    />
  );
}

function eventLabel(event: CashFlowLadderEvent): string {
  return `${formatDate(event.expected_date)} · ${ownerEventLabel(event.component)} · ${event.instrument_name ?? event.account_name}`;
}

const OUTLOOK_UNAVAILABLE_LABELS: Record<string, string> = {
  outlook_not_available_until_closed:
    "Данные следующего месяца появятся после закрытия текущего отчёта.",
  outlook_section_unavailable:
    "Для следующего месяца пока недостаточно подтверждённых датированных данных.",
};

function unavailableReason(reasonCode: string | null): string {
  if (!reasonCode) return "Причина недоступности не указана.";
  return OUTLOOK_UNAVAILABLE_LABELS[reasonCode] ?? "Причина недоступности не распознана.";
}

function WindowSummary({ window }: { window: UpcomingEventsWindow }) {
  const hasKnownEvents = window.items.length > 0;
  return (
    <article className="final-review__event-window">
      <div className="final-review__event-heading">
        <strong>Ближайшие {window.days} дней</strong>
        <strong>
          {hasKnownEvents ? moneyValue(window.total_cash_flow) : "Событий не известно"}
        </strong>
      </div>
      <p className="muted tiny">
        {formatDate(window.from_date)} — до {formatDate(window.to_date)} · пассивный доход{" "}
        {hasKnownEvents ? moneyValue(window.passive_income) : "неизвестен"} · возврат основной
        суммы {hasKnownEvents ? moneyValue(window.redemption_principal) : "неизвестно"}
      </p>
      {hasKnownEvents ? (
        <ul className="final-review__event-list">
          {window.items.map((event) => (
            <li
              key={`${event.source_kind}-${event.source_id}-${event.expected_date}-${event.component}`}
            >
              <span>{eventLabel(event)}</span>
              <strong>{moneyValue(event.expected_net_amount)}</strong>
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
        <p className="muted">{unavailableReason(outlook.reason_code)}</p>
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
        Показаны только уже известные события после закрытия{" "}
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
          value={hasKnownNextMonthEvents ? moneyValue(nextMonth?.passive_income) : noKnownEvents}
        />
        <DataValue
          label={PRINCIPAL_REPAYMENT_LABEL}
          value={
            hasKnownNextMonthEvents ? moneyValue(nextMonth?.redemption_principal) : noKnownEvents
          }
        />
        <DataValue
          label="Всего денежных потоков"
          value={hasKnownNextMonthEvents ? moneyValue(nextMonth?.total_cash_flow) : noKnownEvents}
        />
        <DataValue
          label="Оценка процентов по вкладу"
          value={
            hasKnownNextMonthEvents
              ? moneyValue(nextMonth?.deposit_interest_estimate)
              : noKnownEvents
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
              <strong>{moneyValue(event.expected_net_amount)}</strong>
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted">В следующем месяце нет известных событий.</p>
      )}
      <p className="muted final-review__disclosure">
        Возврат основной суммы — это возврат капитала, а не пассивный доход. Нулевое значение не
        подменяет отсутствие известных событий.
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
          <summary>Версия подтверждения</summary>
          <code>{outlook.evidence_version}</code>
        </details>
      ) : null}
    </Panel>
  );
}
