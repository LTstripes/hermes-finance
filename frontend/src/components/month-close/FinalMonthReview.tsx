import { Link } from "react-router";

import type {
  FinalMonthReview as FinalMonthReviewModel,
  FinalMonthReviewUnavailable,
  ManualReviewCard,
  WorkflowMonth,
} from "../../api/monthCloseWorkflow";
import type {
  CashFlowLadderEvent,
  CloseReadinessItem,
  MoneyValue,
  UpcomingEventsWindow,
} from "../../api/types";
import { formatDate, formatMoney, formatMonth, formatPercent } from "../../lib/format";
import { Badge, DataValue, Panel } from "../ui";
import { withMonthlyCloseReturn } from "./navigation";

const MANUAL_CARD_ORDER = [
  "cash",
  "deposits_savings",
  "debts_property",
  "income_budget",
  "investments_outside_integrations",
  "note",
] as const;

const CARD_SECTIONS: Record<string, string[]> = {
  cash: ["assets"],
  deposits_savings: ["assets"],
  debts_property: ["liabilities"],
  income_budget: ["income", "budget"],
  investments_outside_integrations: ["positions"],
  note: ["note"],
};

const STEP_TITLES: Record<string, string> = {
  alfa_baseline: "Состав портфеля Alfa",
  market_quotes: "Рыночные цены",
  actual_payouts: "Фактические выплаты",
  future_payouts: "Будущие выплаты",
};

const STATE_LABELS: Record<string, string> = {
  not_started: "Не начато",
  ready: "Готово к действию",
  completed: "Готово",
  skipped: "Не применяется",
  warning: "Нужно внимание",
  blocked: "Требуется исправить",
};

function isMoneyValue(value: unknown): value is MoneyValue {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as MoneyValue).amount === "string" &&
    typeof (value as MoneyValue).currency === "string"
  );
}

function money(value: MoneyValue | null | undefined, unavailable = "Недоступно"): string {
  if (!value) return unavailable;
  return formatMoney(value.amount, { currency: value.currency === "RUB" ? "₽" : value.currency });
}

function summaryMoney(summary: Record<string, unknown>, key: string): string {
  const value = summary[key];
  return isMoneyValue(value) ? money(value) : "Недоступно";
}

function summaryCount(summary: Record<string, unknown>, key: string): string | number {
  const value = summary[key];
  return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : "—";
}

function reasonLabel(reasonCode: string | null): string {
  if (reasonCode === "optional_empty") return "Не заполнено · не блокирует закрытие";
  if (reasonCode === "no_position_snapshots") return "Нет позиций для отдельной проверки";
  if (reasonCode === "snapshot_date_required") return "Сначала укажи дату снимка";
  return reasonCode ? "Данные пока недоступны" : "Нет данных";
}

function isZeroMoney(value: unknown): boolean {
  return isMoneyValue(value) && Number(value.amount) === 0;
}

function isOptionalEmpty(card: ManualReviewCard): boolean {
  if (!card.available) return false;
  const { summary } = card;
  const count = (key: string) => summary[key];
  switch (card.id) {
    case "cash":
      return count("row_count") === 0;
    case "deposits_savings":
      return count("deposit_row_count") === 0 && isZeroMoney(summary.savings_allocations);
    case "debts_property":
      return count("debt_row_count") === 0 && count("property_row_count") === 0;
    case "income_budget":
      return (
        count("income_row_count") === 0 &&
        count("expense_row_count") === 0 &&
        count("saving_allocation_count") === 0
      );
    default:
      return false;
  }
}

function availabilityLabel(card: ManualReviewCard): string {
  if (!card.available) return reasonLabel(card.reason_code);
  return isOptionalEmpty(card) ? reasonLabel("optional_empty") : "Есть данные";
}

function cardTone(card: ManualReviewCard): "ok" | "info" | "unknown" {
  if (!card.available) return "unknown";
  return isOptionalEmpty(card) ? "info" : "ok";
}

function editLinks(card: ManualReviewCard, month: WorkflowMonth) {
  return (CARD_SECTIONS[card.id] ?? []).map((section) => (
    <Link
      className="btn btn--ghost btn--sm"
      key={section}
      to={withMonthlyCloseReturn(
        `/months/${month.id}?section=${section}`,
        month.id,
        "final_review_close",
      )}
    >
      {card.id === "income_budget" ? (section === "income" ? "Доходы" : "Бюджет") : "Изменить"}
    </Link>
  ));
}

function cardSummary(card: ManualReviewCard) {
  const { summary } = card;
  switch (card.id) {
    case "cash":
      return (
        <>
          <DataValue label="Сейчас" value={summaryMoney(summary, "cash_total")} />
          <DataValue label="Строк" value={summaryCount(summary, "row_count")} />
        </>
      );
    case "deposits_savings":
      return (
        <>
          <DataValue label="Баланс вкладов" value={summaryMoney(summary, "balance")} />
          <DataValue
            label="Проценты получены"
            value={summaryMoney(summary, "actual_interest_received")}
          />
          <DataValue label="Накопления" value={summaryMoney(summary, "savings_allocations")} />
          <DataValue label="Снимков" value={summaryCount(summary, "deposit_row_count")} />
        </>
      );
    case "debts_property":
      return (
        <>
          <DataValue label="Долги" value={summaryMoney(summary, "debt_total")} />
          <DataValue label="Недвижимость" value={summaryMoney(summary, "property_value")} />
          <DataValue label="Ипотека" value={summaryMoney(summary, "mortgage_balance")} />
          <DataValue label="Объектов" value={summaryCount(summary, "property_row_count")} />
        </>
      );
    case "income_budget":
      return (
        <>
          <DataValue label="Денежный баланс" value={summaryMoney(summary, "cash_balance")} />
          <DataValue
            label="Пассивный доход"
            value={summaryMoney(summary, "passive_income_actual")}
          />
          <DataValue label="Зарплата net" value={summaryMoney(summary, "salary_actual_net")} />
          <DataValue
            label="Обязательные расходы"
            value={summaryMoney(summary, "mandatory_expenses")}
          />
        </>
      );
    case "investments_outside_integrations":
      return (
        <>
          <DataValue label="Рыночная стоимость" value={summaryMoney(summary, "market_value")} />
          <DataValue label="Позиций" value={summaryCount(summary, "position_count")} />
          <DataValue label="Цен вручную" value={summaryCount(summary, "manual_price_count")} />
          <DataValue
            label="Фактических потоков"
            value={summaryCount(summary, "actual_flow_count")}
          />
        </>
      );
    case "note":
      return <DataValue label="Записей" value={summaryCount(summary, "comment_count")} />;
    default:
      return <span className="muted">Сводка этого типа пока не поддерживается.</span>;
  }
}

function eventLabel(event: CashFlowLadderEvent): string {
  const componentLabels: Record<string, string> = {
    coupon: "Купон",
    dividend: "Дивиденд",
    deposit_interest: "Проценты по вкладу",
    other_capital_income: "Прочий доход",
    redemption_principal: "Погашение",
  };
  return `${formatDate(event.expected_date)} · ${componentLabels[event.component] ?? event.component} · ${event.instrument_name ?? event.account_name}`;
}

function WindowSummary({ window }: { window: UpcomingEventsWindow }) {
  return (
    <article className="final-review__event-window">
      <div className="final-review__event-heading">
        <strong>Ближайшие {window.days} дней</strong>
        <strong>{money(window.total_cash_flow)}</strong>
      </div>
      <p className="muted tiny">
        {formatDate(window.from_date)} — до {formatDate(window.to_date)} · пассивный доход{" "}
        {money(window.passive_income)} · погашение {money(window.redemption_principal)}
      </p>
      {window.items.length > 0 ? (
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
        <p className="muted">Событий в этом окне нет.</p>
      )}
    </article>
  );
}

function ReadinessDetails({ review }: { review: FinalMonthReviewModel }) {
  const itemsBySeverity = (severity: CloseReadinessItem["severity"]) =>
    review.close_readiness.items.filter((item) => item.severity === severity);

  return (
    <Panel label="Проверки" title="Готовность, свежесть и источники">
      <div className="final-review__status-grid">
        <DataValue
          label="Закрытие"
          value={review.close_readiness.can_close ? "Можно закрыть" : "Есть блокеры"}
        />
        <DataValue label="Блокеров" value={itemsBySeverity("hard_blocker").length} />
        <DataValue label="Предупреждений" value={itemsBySeverity("warning").length} />
        <DataValue
          label="Свежесть"
          value={review.freshness_summary.available ? "Проверена" : "Недоступна"}
          meta={
            review.freshness_summary.evaluated_on
              ? `На ${formatDate(review.freshness_summary.evaluated_on)}`
              : reasonLabel(review.freshness_summary.reason_codes[0] ?? null)
          }
        />
      </div>

      <details className="field-details">
        <summary>Показать причины и диагностику</summary>
        <div className="final-review__details-stack">
          <section>
            <h3>Close Cockpit</h3>
            {review.close_readiness.items.length > 0 ? (
              <ul className="final-review__diagnostic-list">
                {review.close_readiness.items.map((item) => (
                  <li key={`${item.severity}:${item.code}:${item.message}`}>
                    <Badge
                      tone={
                        item.severity === "hard_blocker"
                          ? "missing"
                          : item.severity === "warning"
                            ? "stale"
                            : "info"
                      }
                    >
                      {item.severity === "hard_blocker"
                        ? "Блокер"
                        : item.severity === "warning"
                          ? "Предупреждение"
                          : "Контекст"}
                    </Badge>
                    <span>{item.message}</span>
                    <code>{item.code}</code>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted">Блокеров и предупреждений нет.</p>
            )}
          </section>

          <section>
            <h3>Свежесть данных</h3>
            {review.freshness_summary.families.length > 0 ? (
              <ul className="final-review__diagnostic-list">
                {review.freshness_summary.families.map((family, index) => {
                  const coverage =
                    typeof family.coverage === "object" && family.coverage !== null
                      ? (family.coverage as Record<string, unknown>)
                      : null;
                  return (
                    <li key={`${String(family.family_id ?? index)}`}>
                      <span>
                        <strong>{String(family.title ?? family.family_id ?? "Источник")}</strong> ·{" "}
                        {String(family.status ?? "unknown")}
                      </span>
                      {coverage ? (
                        <span className="muted">
                          Строк: {String(coverage.row_count ?? "—")} · недоступно:{" "}
                          {String(coverage.unavailable_count ?? "—")}
                        </span>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
            ) : (
              <p className="muted">Сводка свежести недоступна.</p>
            )}
          </section>

          <section>
            <h3>Провайдерские шаги</h3>
            {review.provider_summary.length > 0 ? (
              <ul className="final-review__diagnostic-list">
                {review.provider_summary.map((item, index) => {
                  const stepId = String(item.step_id ?? index);
                  const state = String(item.state ?? "unknown");
                  const reasonCodes = Array.isArray(item.reason_codes)
                    ? item.reason_codes.map(String).join(", ")
                    : "";
                  return (
                    <li key={stepId}>
                      <span>
                        <strong>{STEP_TITLES[stepId] ?? "Провайдерская проверка"}</strong> ·{" "}
                        {STATE_LABELS[state] ?? "Состояние неизвестно"}
                      </span>
                      {reasonCodes ? <code>{reasonCodes}</code> : null}
                    </li>
                  );
                })}
              </ul>
            ) : (
              <p className="muted">Провайдерских сведений нет.</p>
            )}
          </section>

          <section>
            <h3>Сверка Alfa</h3>
            <p className="muted">
              {review.reconciliation_availability.available === true
                ? "Есть результат текущей проверки."
                : "Результат не получен: проверка запускается отдельно и здесь не сохраняется."}
            </p>
            {typeof review.reconciliation_availability.reason_code === "string" ? (
              <code>{review.reconciliation_availability.reason_code}</code>
            ) : null}
          </section>
        </div>
      </details>
    </Panel>
  );
}

function FutureEvents({ review }: { review: FinalMonthReviewModel }) {
  const future = review.important_future_events;
  if (!future.available) {
    return (
      <Panel label="Впереди" title="Важные события">
        <p className="muted">{reasonLabel(future.reason_code)}</p>
      </Panel>
    );
  }

  return (
    <Panel label="Впереди" title="Важные события">
      <div className="final-review__status-grid">
        <DataValue label="Известных событий" value={future.known_event_count} />
        <DataValue
          label="Следующий месяц · доход"
          value={money(future.next_month?.passive_income)}
        />
        <DataValue
          label="Следующий месяц · погашение"
          value={money(future.next_month?.redemption_principal)}
        />
        <DataValue
          label="Следующий месяц · всего"
          value={money(future.next_month?.total_cash_flow)}
        />
      </div>
      <p className="muted final-review__disclosure">
        Погашение — возврат капитала, а не пассивный доход. Будущий месяц здесь не создаётся.
      </p>
      <details className="field-details">
        <summary>Показать ближайшие окна</summary>
        <div className="final-review__event-windows">
          {future.upcoming_14_days ? <WindowSummary window={future.upcoming_14_days} /> : null}
          {future.upcoming_30_days ? <WindowSummary window={future.upcoming_30_days} /> : null}
        </div>
      </details>
    </Panel>
  );
}

function Attention({ review, month }: { review: FinalMonthReviewModel; month: WorkflowMonth }) {
  return (
    <Panel label="Требует внимания" title="Что проверить перед закрытием">
      {review.manual_attention.length > 0 ? (
        <ul className="final-review__attention-list">
          {review.manual_attention.map((item) => {
            const card = review.manual_review_cards.find(
              (candidate) => candidate.id === item.card_id,
            );
            return (
              <li key={`${item.severity}:${item.code}:${item.message}`}>
                <Badge tone={item.severity === "hard_blocker" ? "missing" : "stale"}>
                  {item.severity === "hard_blocker" ? "Блокер" : "Предупреждение"}
                </Badge>
                <span>{item.message}</span>
                {card && CARD_SECTIONS[card.id]?.[0] ? (
                  <Link
                    className="btn btn--ghost btn--sm"
                    to={withMonthlyCloseReturn(
                      `/months/${month.id}?section=${CARD_SECTIONS[card.id][0]}`,
                      month.id,
                      "final_review_close",
                    )}
                  >
                    Открыть {card.title.toLocaleLowerCase()}
                  </Link>
                ) : null}
                <details className="final-review__attention-details">
                  <summary>Техническая причина</summary>
                  <code>{item.code}</code>
                </details>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="muted">Блокеров и предупреждений нет.</p>
      )}
    </Panel>
  );
}

function ManualCards({ review, month }: { review: FinalMonthReviewModel; month: WorkflowMonth }) {
  const cardsById = new Map(review.manual_review_cards.map((card) => [card.id, card]));
  const cards = MANUAL_CARD_ORDER.map((id) => cardsById.get(id)).filter(
    (card): card is ManualReviewCard => card !== undefined,
  );

  return (
    <Panel label="Ручные данные" title="Проверь сохранённые значения">
      <div className="final-review__cards">
        {cards.map((card) => (
          <article
            className="final-review__card"
            data-testid={`final-review-card-${card.id}`}
            key={card.id}
          >
            <div className="final-review__card-heading">
              <h3>{card.title}</h3>
              <Badge tone={cardTone(card)}>{availabilityLabel(card)}</Badge>
            </div>
            <div className="final-review__card-grid">{cardSummary(card)}</div>
            {!card.available ? <p className="muted tiny">{reasonLabel(card.reason_code)}</p> : null}
            <div className="final-review__card-actions">{editLinks(card, month)}</div>
          </article>
        ))}
      </div>
    </Panel>
  );
}

export function FinalMonthReview({
  review,
}: {
  review: FinalMonthReviewModel | FinalMonthReviewUnavailable;
}) {
  if (!review.available) {
    return (
      <Panel label="Итоги месяца" title="Финальная проверка">
        <p className="muted">{reasonLabel(review.reason_code)}</p>
      </Panel>
    );
  }

  return (
    <section className="final-review stack-18" id="final_review_close">
      <header className="final-review__header">
        <div>
          <p className="eyebrow">Финальный шаг</p>
          <h2>Итоги {formatMonth(review.month_header.year, review.month_header.month)}</h2>
        </div>
        <Badge tone={review.month_header.status === "closed" ? "closed" : "info"}>
          {review.month_header.status === "closed" ? "Месяц закрыт" : "Финальная проверка"}
        </Badge>
      </header>
      <p className="final-review__lead">
        Здесь собраны значения месяца из системы и оставшиеся ручные проверки. Ничего не
        пересчитывается в браузере.
      </p>

      <Panel label="Сводка" title="Основные показатели">
        <div className="final-review__kpis">
          <DataValue
            label="Ликвидный капитал"
            value={money(review.kpis.liquid_capital_net)}
            size="lg"
          />
          <DataValue
            label="Деньги сейчас"
            value={money(review.assets_and_cash.current_cash)}
            size="lg"
          />
          <DataValue
            label="Инвестиции"
            value={
              review.investments.available ? money(review.investments.market_value) : "Недоступно"
            }
            meta={
              review.investments.available
                ? `${review.investments.position_count} поз.`
                : reasonLabel(review.investments.reason_code)
            }
            size="lg"
          />
          <DataValue
            label="Пассивный доход · факт"
            value={money(review.actual_passive_income)}
            size="lg"
          />
          <DataValue label="Долги" value={money(review.debts_and_property.debt_total)} size="lg" />
        </div>
        <div className="final-review__supporting-values">
          <DataValue label="Цель пассивного дохода" value={money(review.kpis.goal_target)} />
          <DataValue label="Прогресс цели" value={formatPercent(review.kpis.goal_progress_pct)} />
          <DataValue label="Обязательные расходы" value={money(review.kpis.mandatory_expenses)} />
          <DataValue label="Ипотека" value={money(review.debts_and_property.mortgage_balance)} />
        </div>
      </Panel>

      <Attention month={review.month_header} review={review} />
      <ManualCards month={review.month_header} review={review} />
      <ReadinessDetails review={review} />
      <FutureEvents review={review} />
    </section>
  );
}
