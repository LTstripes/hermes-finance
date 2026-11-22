import type { PayoutReviewItem, StatementPayoutReview } from "../api/statementImport";
import type { Account } from "../api/types";
import { formatDate, formatMoney } from "../lib/format";

const payoutWords = new Intl.PluralRules("ru");
function payoutNoun(count: number) {
  switch (payoutWords.select(count)) {
    case "one":
      return "выплата";
    case "few":
      return "выплаты";
    default:
      return "выплат";
  }
}

const reasons: Record<string, string> = {
  ambiguous: "Несколько возможных соответствий. Уточните событие.",
  already_allocated:
    "Соответствующие прогнозы уже связаны с подтверждёнными выплатами. Эта строка требует отдельной сверки.",
  distinct: "Принятая сверка подтверждает, что выплата и прогноз относятся к разным событиям.",
  stale_evidence: "Данные принятой сверки изменились. Проверьте связь заново.",
  retired: "Ранее принятая связь отозвана.",
  unconfirmed: "Суммы совпадают. Связь с прогнозом требует подтверждения.",
  empty_plan: "В выбранном снимке у счёта нет прогноза выплат на этот месяц.",
  no_forecast: "В выбранном прогнозе такой выплаты нет.",
  no_snapshot: "Для этого месяца нет сохранённого прогноза.",
  correction: "В исправленном PDF изменились данные принятой выплаты.",
  unresolved_row: "Недостаточно данных для сопоставления строки.",
  different_components: "Суммы на руки совпадают, но начисление или налог различаются.",
  different_amount: "Суммы различаются.",
  below_expected: "Сумма в PDF меньше прогноза. Проверьте, частичная ли это выплата.",
  incomparable: "Суммы нельзя сопоставить: различается валюта или неизвестна налоговая основа.",
  future: "Дата ожидаемой выплаты ещё не наступила.",
  coverage_unknown: "Подтверждение не найдено. Полнота отчёта за этот период неизвестна.",
  other_month: "Строка относится к другому месяцу.",
  verified: "Полное исполнение подтверждено.",
};

function amount(value: string, currency: string | null) {
  return formatMoney(value, { currency: currency === "RUB" ? "₽" : (currency ?? "") });
}

function Items({ items, accounts }: { items: PayoutReviewItem[]; accounts: Account[] }) {
  return (
    <ul>
      {items.map((item) => {
        const kind = { coupon: "Купон", dividend: "Дивиденд", redemption: "Погашение" }[
          item.event_kind ?? ""
        ];
        const account = accounts.find((a) => a.id === item.account_id)?.name;
        const day = item.actual_date ?? item.expected_date;
        return (
          <li key={item.key}>
            <strong>
              {[kind, item.name, account, day && formatDate(day)].filter(Boolean).join(" · ") ||
                "Строка PDF"}
            </strong>
            {" — "}
            {reasons[item.reason] ?? "Требуется уточнение."}
            {item.expected_amount != null && (
              <>
                {" "}
                Прогноз{item.expected_basis === "announced" ? " провайдера" : " на руки"}:{" "}
                {amount(item.expected_amount, item.expected_currency)}.
              </>
            )}
            {item.actual_date && item.expected_date && item.actual_date !== item.expected_date && (
              <> Ожидалась {formatDate(item.expected_date)}.</>
            )}
            {item.reason === "different_components" &&
              item.expected_tax != null &&
              item.actual_tax != null && (
                <>
                  {" "}
                  Налог по прогнозу {amount(item.expected_tax, item.expected_currency)}, по PDF{" "}
                  {amount(item.actual_tax, item.actual_currency)}.
                </>
              )}
            {item.forecast_snapshot && (
              <>
                {" "}
                Снимок на {formatDate(item.forecast_snapshot)}
                {item.forecast_version ? ` (${item.forecast_version})` : ""}.
              </>
            )}
            {item.actual_net != null && (
              <> По PDF на руки: {amount(item.actual_net, item.actual_currency)}.</>
            )}
          </li>
        );
      })}
    </ul>
  );
}

export function StatementPayoutComparison({
  review,
  accounts,
}: {
  review: StatementPayoutReview;
  accounts: Account[];
}) {
  const verified = review.items.filter((item) => item.reason === "verified");
  const outside = review.items.filter((item) =>
    ["coverage_unknown", "other_month"].includes(item.reason),
  );
  const future = review.items.filter((item) => item.reason === "future");
  const attention = review.items.filter(
    (item) => !["verified", "coverage_unknown", "other_month", "future"].includes(item.reason),
  );
  return (
    <section aria-label="Сверка прогноза с PDF">
      <h3>Сверка прогноза с PDF</h3>
      <p>
        Сверено {verified.length} {payoutNoun(verified.length)} · Требуют внимания{" "}
        {attention.length}
      </p>
      {review.items.length === 0 && <p>В выбранном отчёте нет данных для сверки.</p>}
      {attention.length > 0 && <Items items={attention} accounts={accounts} />}
      {outside.length > 0 && (
        <details>
          <summary>Вне подтверждённого покрытия ({outside.length})</summary>
          <Items items={outside} accounts={accounts} />
        </details>
      )}
      {future.length > 0 && (
        <details>
          <summary>Будущие выплаты ({future.length})</summary>
          <Items items={future} accounts={accounts} />
        </details>
      )}
      {verified.length > 0 && (
        <details>
          <summary>Подтверждённые совпадения ({verified.length})</summary>
          <Items items={verified} accounts={accounts} />
        </details>
      )}
      {review.vintages.length > 0 && (
        <details>
          <summary>Период прогноза</summary>
          {review.vintages.map((v) => (
            <p key={v.month}>
              {v.month.slice(0, 7)} ·{" "}
              {v.snapshot ? `Снимок на ${formatDate(v.snapshot)}` : "Снимок отсутствует"} ·{" "}
              {review.forecast_version}
            </p>
          ))}
        </details>
      )}
    </section>
  );
}
