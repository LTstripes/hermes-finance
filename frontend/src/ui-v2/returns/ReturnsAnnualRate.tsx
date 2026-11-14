import sheet from "../ReportSheet.module.css";
import type { AnnualReturn } from "./overall";
import { dateLabel, displayCompactRate, tone } from "./model";

function unavailableReason(value: AnnualReturn) {
  const reasons = value.rate.reason_codes;
  if (reasons.includes("overall_source_proof_stale"))
    return "Годовая доходность пока неизвестна: подтверждение истории счёта требует проверки.";
  if (reasons.includes("overall_internal_transfer_unproven"))
    return "Годовая доходность пока неизвестна: нужно подтвердить обе стороны перевода между счетами.";
  if (reasons.includes("overall_short_holding"))
    return "Годовая доходность появится, когда средний срок вложения денег достигнет 90 дней.";
  if (reasons.includes("overall_valuation_unavailable"))
    return "Годовая доходность пока неизвестна: нет полной оценки бумаг и денег на одну дату.";
  if (reasons.includes("overall_account_mapping_unproven"))
    return "Годовая доходность пока неизвестна: нужно подтвердить связь выписок со счетами.";
  return "Годовая доходность пока неизвестна: нужна полная история вводов и выводов с начала вложений.";
}

export function ReturnsAnnualRate({ value }: { value?: AnnualReturn }) {
  if (!value) return null;
  if (value.rate.value === null) return <p className={sheet.muted}>{unavailableReason(value)}</p>;
  const provisional = value.rate.reason_codes.includes("overall_short_holding_provisional");
  const months = Math.floor(Number(value.weighted_holding_days) / 30.4);
  return (
    <section aria-label="Годовая доходность">
      <strong
        data-tone={tone(value.rate)}
        title="XIRR учитывает даты вводов и выводов и стоимость бумаг и денег на дату оценки."
      >
        {provisional ? "≈" : ""}
        {displayCompactRate(value.rate, false)}
      </strong>{" "}
      <small className={sheet.muted}>
        годовых{value.first_operation_date ? `, с ${dateLabel(value.first_operation_date)}` : ""}
      </small>
      {provisional && (
        <p className={sheet.muted}>
          деньги вложены в среднем {months} мес. — процент пока предварительный
        </p>
      )}
      {value.rate.reason_codes.includes("overall_small_unknown_assumed_internal") && (
        <p className={sheet.muted}>
          Оценка: нераспознанные операции менее 100 ₽ условно отнесены к внутренним.
        </p>
      )}
    </section>
  );
}
