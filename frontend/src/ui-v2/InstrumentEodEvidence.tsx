import type { InstrumentObservations } from "../api/instrumentEodObservations";
import { formatDate } from "../lib/format";
import styles from "./UiV2CapitalPerformance.module.css";

const rub = (value: string | null) =>
  value === null ? "Неизвестно" : `${value.replace(".", ",")} ₽`;
const basisLabels = {
  unknown: "Учёт НКД неизвестен",
  included: "НКД включён",
  excluded: "НКД исключён",
  not_applicable: "НКД не применим",
};
export function observationGap(reason: string): string {
  if (reason === "exact_eod_position_missing")
    return "На эту точную дату нет сохранённой позиции. Это не доказывает нулевое владение или стоимость.";
  if (reason === "revision_journal_unavailable")
    return "Нет надёжного журнала версий для этой границы.";
  if (reason === "native_position_authority_unavailable")
    return "Нет принятого native-подтверждения этой позиции.";
  if (
    reason === "historical_identity_or_mapping_changed" ||
    reason === "historical_identity_unknown"
  )
    return "Историческая RUB-идентичность бумаги не подтверждена или привязка изменилась.";
  if (reason === "bond_nkd_basis_unknown")
    return "Учёт НКД неизвестен: сопоставимость двух оценок не подтверждена.";
  if (reason === "bond_nkd_basis_incomparable")
    return "Оценки по-разному учитывают НКД и несопоставимы.";
  if (reason === "quantity_changed_not_profit")
    return "Количество изменилось. Разница стоимости позиции не является прибылью.";
  if (reason === "overlapping_endpoint_conflict")
    return "Источники противоречат друг другу на этой EOD-дате.";
  if (reason.includes("date") || reason.includes("period"))
    return "Точная дата EOD или отчётный период не подтверждены.";
  if (reason === "zero_inventory_entitlement_unproven")
    return "Нулевое владение и отсутствие оставшихся прав на выплаты не подтверждены.";
  if (reason === "archived_position_unavailable")
    return "Архивная запись не подтверждает действующую EOD-оценку.";
  return "Сохранённая оценка или её источник изменились; текущее подтверждение недоступно.";
}

export function InstrumentEodEvidence({ result }: { result: InstrumentObservations }) {
  const pair = [
    ["Начальная оценка EOD", result.opening],
    ["Конечная оценка EOD", result.closing],
  ] as const;
  return (
    <section aria-label="Наблюдаемые EOD-оценки" data-testid="instrument-eod-result">
      <h3>Наблюдаемые EOD-оценки позиции</h3>
      <p>
        Две сохранённые оценки на точные даты. Отсутствие записи не означает нулевую стоимость.
        Движение количества и стоимости позиции не является прибылью.
      </p>
      <div className={styles.metricGrid}>
        {pair.map(([label, boundary]) => {
          const available =
            boundary.availability === "available" &&
            boundary.currentness === "current" &&
            boundary.proof_state === "source_accepted";
          const identity = boundary.historical_identity;
          return (
            <article className={styles.metricCard} key={label} aria-label={label}>
              <h4>
                {label} · {formatDate(boundary.date)}
              </h4>
              <p>
                Наблюдаемая стоимость:{" "}
                <strong>{rub(available ? boundary.market_value : null)}</strong>
              </p>
              <p>Количество: {available ? (boundary.quantity ?? "Неизвестно") : "Неизвестно"}</p>
              <p>{available ? "Источник EOD подтверждён при чтении" : "Оценка недоступна"}</p>
              {available && identity ? (
                <p>
                  {identity.isin} · {identity.instrument_type === "bond" ? "Облигация" : "Акция"} ·
                  номинация {identity.denomination}
                </p>
              ) : null}
              {available && boundary.bond_nkd_basis ? (
                <p>{basisLabels[boundary.bond_nkd_basis]}</p>
              ) : null}
              {boundary.reason_codes.map((reason) => (
                <p key={reason}>{observationGap(reason)}</p>
              ))}
              <details>
                <summary>Происхождение EOD</summary>
                <p>
                  Позиция #{boundary.position_id ?? "—"}; источник:{" "}
                  {boundary.price_source ?? "неизвестен"}; дата оценки:{" "}
                  {boundary.price_date ? formatDate(boundary.price_date) : "неизвестна"}.
                </p>
                <p>
                  Import: {boundary.source_import_id ?? "—"}; поколение:{" "}
                  {boundary.revision_generation ?? "недоступно"}.
                </p>
                {boundary.receipt_ids.map((id) => (
                  <p key={id}>Подтверждение: {id}</p>
                ))}
                <p style={{ overflowWrap: "anywhere" }}>
                  Строка: {boundary.source_row_key ?? "неизвестна"}
                </p>
                <p style={{ overflowWrap: "anywhere" }}>
                  Версия: {boundary.dependency_fingerprint ?? "недоступна"}
                </p>
                {boundary.reason_codes.map((reason) => (
                  <p key={reason}>
                    <small>{reason}</small>
                  </p>
                ))}
              </details>
            </article>
          );
        })}
      </div>
      <p>
        Сопоставимость основы оценок:{" "}
        {result.comparable === true
          ? "подтверждена"
          : result.comparable === false
            ? "оценки несопоставимы"
            : "неизвестна"}
        .
      </p>
      {result.comparable === true && result.observed_position_value_difference !== null ? (
        <p>
          Разница наблюдаемых стоимостей позиции: {rub(result.observed_position_value_difference)}.
          Это не прибыль и не доходность.
        </p>
      ) : null}
      {result.reason_codes
        .filter((r) =>
          [
            "quantity_changed_not_profit",
            "bond_nkd_basis_unknown",
            "bond_nkd_basis_incomparable",
          ].includes(r),
        )
        .map((r) => (
          <p key={r}>{observationGap(r)}</p>
        ))}
      <p>
        <strong>Полная доходность RUB/% пока недоступна.</strong> Полнота операций и денежных выплат
        неизвестна. Оценки и известные выплаты не складываются в инвестиционный результат.
      </p>
    </section>
  );
}
