import { useQuery } from "@tanstack/react-query";
import type { PayoutScope } from "../api/instrumentCashIncome";
import { getKnownTrades } from "../api/instrumentTrades";
import { formatDate } from "../lib/format";
import styles from "./InstrumentCashIncome.module.css";

const roleLabels = {
  settlement: "Расчёт по сделке",
  paid_nkd: "Уплаченный НКД",
  commission: "Комиссия",
};
const rub = (v: string | null) => (v === null ? "Неизвестно" : `${v.replace(".", ",")} ₽`);
function day(value: string | null, inside: boolean | null) {
  return value ? `${formatDate(value)}${inside === false ? " · вне (t0,t1]" : ""}` : "Неизвестно";
}
export function tradeGap(code: string) {
  if (code === "effective_money_proof_unavailable" || code === "role_cash_authority_unavailable")
    return "Нет действующего отдельного денежного подтверждения. Сумма неизвестна.";
  if (code === "historical_rub_identity_unproven")
    return "Историческая RUB-идентичность бумаги не подтверждена.";
  if (code === "sell_cash_authority_unsupported")
    return "Денежные поступления от продажи этим подтверждением не поддерживаются.";
  if (code === "source_inventory_gap")
    return "Нет источника, подтверждающего состав операций за период.";
  if (code === "unaccepted_native_execution_rows")
    return "В источнике есть сделки без принятой канонической версии.";
  if (
    code === "unsupported_money_rows" ||
    code === "unparsed_source_rows" ||
    code === "unknown_section"
  )
    return "Есть неподдерживаемые или неразобранные строки источника.";
  if (code === "inventory_revision_journal_unavailable")
    return "Повторное использование версии недоступно: нет полного журнала изменений состава сделок.";
  return "Подтверждение неполно, изменилось или недоступно. Требуется проверка источника.";
}
export function InstrumentTrades({
  request,
}: {
  request: { scope: PayoutScope; generation: number } | null;
}) {
  const result = useQuery({
    queryKey: ["known-instrument-trades", request],
    queryFn: ({ signal }) => {
      if (!request) throw new Error("Choose trade scope");
      return getKnownTrades(request.scope, signal);
    },
    enabled: request !== null,
    staleTime: 0,
    gcTime: 0,
    retry: false,
  });
  const data = request && !result.isFetching && !result.isError ? result.data : null;
  const scope = request?.scope;
  const fresh =
    data &&
    scope &&
    data.method === "known-instrument-trades" &&
    data.version === 1 &&
    data.currency === "RUB" &&
    data.account.id === scope.accountId &&
    data.instrument.id === scope.instrumentId &&
    data.t0 === scope.t0 &&
    data.t1 === scope.t1 &&
    data.events.every(
      (e) => e.account_id === scope.accountId && e.instrument_id === scope.instrumentId,
    );
  return (
    <section aria-label="Известные сделки и расчёты">
      <h3>Известные сделки и расчёты</h3>
      <p>
        Наблюдаемые BUY/SELL и отдельно подтверждённые денежные ноги. Полнота сделок и денежных
        расчётов неизвестна. Полная доходность RUB/% пока недоступна.
      </p>
      {request && result.isFetching ? (
        <p role="status">Проверяем сделки и денежные подтверждения…</p>
      ) : null}
      {request && result.isError ? (
        <p role="alert">Не удалось прочитать сделки. Повторите чтение выбранного периода.</p>
      ) : null}
      {data && !fresh ? (
        <p role="alert">Ответ сделок не соответствует выбранному контексту. Повторите чтение.</p>
      ) : null}
      {fresh ? (
        <div data-testid="known-trades-result">
          {data.status === "capacity_exceeded" ? (
            <p role="alert">
              Превышен предел {data.capacity} сделок. Сократите период; список не усечён.
            </p>
          ) : (
            <p>Известных сделок: {data.known_count}. Это не полный список операций.</p>
          )}
          {data.known_count === 0 ? (
            <p>Сделки не найдены. Это не доказывает отсутствия сделок за период.</p>
          ) : null}
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Наблюдаемая сделка</th>
                  <th>Даты</th>
                  <th>Денежные подтверждения</th>
                  <th>Источник и ограничения</th>
                </tr>
              </thead>
              <tbody>
                {data.events.map((e) => (
                  <tr key={e.source_identity}>
                    <td>
                      {e.side ?? "Сторона неизвестна"} ·{" "}
                      {e.signed_quantity ?? "Количество неизвестно"}
                      <p>Наблюдаемое исполнение</p>
                      <p>
                        {e.lifecycle === "settled"
                          ? "Расчёты отражены в источнике"
                          : e.lifecycle === "pending"
                            ? "Ожидает расчётов"
                            : "Статус неизвестен"}
                      </p>
                    </td>
                    <td>
                      <p>Сделка: {day(e.execution_date, e.execution_in_interval)}</p>
                      <p>Расчёт: {day(e.settlement_date, e.settlement_in_interval)}</p>
                      <p>Депозитарий: {day(e.depository_date, e.depository_in_interval)}</p>
                      {e.planned_settlement_date ? (
                        <p>План расчёта: {formatDate(e.planned_settlement_date)}</p>
                      ) : null}
                    </td>
                    <td>
                      {e.cash_legs.map((leg) => (
                        <div key={leg.role}>
                          <p>
                            {roleLabels[leg.role]}: {rub(leg.signed_rub)}
                          </p>
                          <p>
                            {leg.proof_class === "effective_cash_leg_authority"
                              ? "Денежная нога подтверждена"
                              : "Денежная нога не подтверждена"}
                          </p>
                          {leg.effective_date ? (
                            <p>{day(leg.effective_date, leg.in_interval)}</p>
                          ) : null}
                          <details>
                            <summary>Основание: {roleLabels[leg.role]}</summary>
                            {leg.receipt_id ? (
                              <p>
                                Money: {leg.receipt_id} · {leg.basis}
                              </p>
                            ) : null}
                            {leg.reason_codes
                              .filter((c) => c !== "effective_money_role_proof")
                              .map((c) => (
                                <p key={c}>
                                  {tradeGap(c)} <small>({c})</small>
                                </p>
                              ))}
                            {leg.occurrences.map((o) => (
                              <p key={`${o.import_id}:${o.ordinal}`}>
                                Money #{o.import_id} · строка {o.ordinal}
                              </p>
                            ))}
                          </details>
                        </div>
                      ))}
                    </td>
                    <td>
                      <details>
                        <summary>Native IDs: {e.native_ids.join(" / ")}</summary>
                        <p>
                          Canonical #{e.trade_id} · revision {e.revision ?? "неизвестна"}
                        </p>
                        <p>
                          {e.currentness === "current"
                            ? "Исполнение проверено при чтении"
                            : "Текущая версия исполнения не подтверждена"}
                        </p>
                        {e.source_occurrences.map((o) => (
                          <p key={`${o.import_id}:${o.section}:${o.ordinal}`}>
                            Источник #{o.import_id} · {o.section} · строка {o.ordinal}
                          </p>
                        ))}
                        {e.reason_codes.map((c) => (
                          <p key={c}>
                            {tradeGap(c)} <small>({c})</small>
                          </p>
                        ))}
                      </details>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {data.reason_codes
            .filter(
              (c) =>
                ![
                  "trade_history_completeness_unknown",
                  "financial_coverage_unknown",
                  "full_instrument_return_unavailable",
                  "no_known_trades_not_zero_activity",
                ].includes(c),
            )
            .map((c) => (
              <p key={c}>
                {tradeGap(c)} <small>({c})</small>
              </p>
            ))}
        </div>
      ) : null}
    </section>
  );
}
