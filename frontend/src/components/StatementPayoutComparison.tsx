import type { PayoutReviewItem, StatementPayoutReview } from "../api/statementImport";
import type { Account } from "../api/types";
import { formatDate, formatMoney, formatMonthKey } from "../lib/format";
import styles from "./StatementPayoutComparison.module.css";
import { Badge, Table, Td, Th } from "./ui";

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
};

function amount(value: string, currency: string | null) {
  return formatMoney(value, { currency: currency === "RUB" ? "₽" : (currency ?? "") });
}

const groups = {
  attention: "Требует внимания",
  verified: "Сверено",
  outside: "Вне покрытия",
  future: "Ожидается",
} as const;

function Items({
  items,
  accounts,
  group,
}: {
  items: PayoutReviewItem[];
  accounts: Account[];
  group: keyof typeof groups;
}) {
  return (
    <Table className={styles.table} aria-label={groups[group]}>
      <thead>
        <tr>
          <Th>Выплата и счёт</Th>
          <Th>Дата</Th>
          <Th numeric className={styles.forecast}>
            Прогноз
          </Th>
          <Th numeric>PDF на руки</Th>
          <Th>Статус и причина</Th>
        </tr>
      </thead>
      <tbody>
        {items.map((item) => {
          const kind = { coupon: "Купон", dividend: "Дивиденд", redemption: "Погашение" }[
            item.event_kind ?? ""
          ];
          const account = accounts.find((a) => a.id === item.account_id)?.name;
          return (
            <tr key={item.key}>
              <Th scope="row">
                {[kind, item.name].filter(Boolean).join(" · ") || "Строка PDF"}
                {account && <small>{account}</small>}
              </Th>
              <Td>
                {formatDate(item.actual_date ?? item.expected_date)}
                {item.actual_date &&
                  item.expected_date &&
                  item.actual_date !== item.expected_date && (
                    <small>Ожидалась {formatDate(item.expected_date)}</small>
                  )}
              </Td>
              <Td numeric className={styles.forecast}>
                {item.expected_amount == null ? (
                  "—"
                ) : (
                  <>
                    {amount(item.expected_amount, item.expected_currency)}
                    <small>
                      {item.expected_basis === "announced"
                        ? "объявлено"
                        : item.expected_basis === "net"
                          ? "на руки"
                          : "основа неизвестна"}
                    </small>
                  </>
                )}
              </Td>
              <Td numeric>
                {item.actual_net == null ? "—" : amount(item.actual_net, item.actual_currency)}
              </Td>
              <Td>
                <Badge
                  className={
                    group === "verified"
                      ? styles.verified
                      : group === "attention"
                        ? styles.attention
                        : ""
                  }
                >
                  {groups[group]}
                </Badge>
                {group !== "verified" && (
                  <small>{reasons[item.reason] ?? "Требуется уточнение."}</small>
                )}
                {item.reason === "different_components" &&
                  item.expected_tax != null &&
                  item.actual_tax != null && (
                    <small>
                      Налог по прогнозу{" "}
                      <span className="num">
                        {amount(item.expected_tax, item.expected_currency)}
                      </span>
                      , по PDF{" "}
                      <span className="num">{amount(item.actual_tax, item.actual_currency)}</span>.
                    </small>
                  )}
              </Td>
            </tr>
          );
        })}
      </tbody>
    </Table>
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
    <section className={styles.review} aria-label="Сверка прогноза с PDF">
      <header className={styles.summary}>
        <h3>Сверка прогноза с PDF</h3>
        <Badge className={styles.verified}>
          Сверено {verified.length} {payoutNoun(verified.length)}
        </Badge>
        {attention.length > 0 && (
          <Badge className={styles.attention}>Требуют внимания {attention.length}</Badge>
        )}
      </header>
      {review.items.length === 0 && <p>В выбранном отчёте нет данных для сверки.</p>}
      {attention.length > 0 && <Items items={attention} accounts={accounts} group="attention" />}
      {(
        [
          ["outside", "Вне подтверждённого покрытия", outside],
          ["future", "Будущие выплаты", future],
          ["verified", "Подтверждённые совпадения", verified],
        ] as const
      ).map(
        ([group, label, items]) =>
          items.length > 0 && (
            <details key={group}>
              <summary>
                {label} <Badge>{items.length}</Badge>
              </summary>
              <Items items={items} accounts={accounts} group={group} />
            </details>
          ),
      )}
      {review.vintages.length > 0 && (
        <details>
          <summary>Период прогноза</summary>
          {review.vintages.map((v) => (
            <p key={v.month}>
              {formatMonthKey(v.month.slice(0, 7))} ·{" "}
              {v.snapshot ? `Снимок на ${formatDate(v.snapshot)}` : "Снимок отсутствует"}
            </p>
          ))}
        </details>
      )}
    </section>
  );
}
