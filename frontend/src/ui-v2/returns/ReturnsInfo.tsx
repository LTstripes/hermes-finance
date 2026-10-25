import type { ReactNode } from "react";
import { displayMetric, type Metric } from "./model";
import styles from "./Returns.module.css";

const reasons: Record<string, string> = {
  missing_endpoint: "Не хватает стоимости на границе периода.",
  missing_quantity: "Не подтверждено количество на границе периода.",
  unknown_flow: "Не все движения денег определены.",
  unknown_flows: "Не все движения денег определены.",
  flow_coverage_gap: "История движений денег покрывает период не полностью.",
  incomplete_source_coverage: "Выписки покрывают период не полностью.",
  bond_valuation_basis_unknown: "Для полного результата облигации нужен НКД на обеих границах.",
  non_positive_dietz_denominator: "Нет положительной базы для расчёта процента.",
  income_interval_unavailable: "Полученные выплаты за весь этот интервал не подтверждены.",
  interval_rate_unavailable:
    "Расчёт процента для этих границ пока недоступен. Выберите месяц или готовый интервал.",
  accepted_income_breakdown_unavailable:
    "Подтверждённый расчёт не содержит отдельного итога выплат. Они доступны для счетов в группе «По выпискам».",
  accepted_instrument_breakdown_unavailable:
    "Подтверждённый расчёт портфеля не содержит доходности отдельных бумаг. Выберите счёт в группе «По выпискам».",
  payout_link_stale: "Связь выплаты с бумагой требует повторной проверки.",
  source_period_inferred: "Даты остатков в выписке не подтверждены.",
  seam_mismatch: "Остатки соседних периодов расходятся.",
};
const methods: Record<string, string> = {
  modified_dietz: "Процент — оценка Modified Dietz за указанные даты, без пересчёта на год.",
  chained_modified_dietz:
    "Процент — последовательное связывание месячных оценок Modified Dietz. Пропуски не соединяются.",
  source_monthly:
    "Результат по выпискам после исключения пополнений и снятий. Выплаты уже включены в результат.",
  source_period:
    "Итог по границам всей доступной истории и движениям денег. Частичные результаты не подставляются вместо полного итога.",
  instrument_return_v2:
    "Результат бумаги за указанные даты с учётом сделок, выплат и расходов по существующему расчёту.",
  credited_payments:
    "Фактически зачисленные выплаты. Будущее расписание сюда не входит; выплаты не прибавляются к результату повторно.",
  PERF04A: "Изменение стоимости после внешних пополнений и снятий, по подтверждённым отчётам.",
  twrr: "Доходность TWRR за выбранный период, по подтверждённым отчётам.",
};
export function Explanation({ codes }: { codes: string[] }) {
  const texts = [
    ...new Set(
      codes.map(
        (c) =>
          reasons[c] ?? "Для этого значения не хватает проверенных данных за выбранный период.",
      ),
    ),
  ];
  return (
    <>
      {texts.map((text) => (
        <p key={text}>{text}</p>
      ))}
    </>
  );
}
export function Info({ label, children }: { label: string; children: ReactNode }) {
  return (
    <details className={styles.info}>
      <summary aria-label={`Подробнее: ${label}`}>ⓘ</summary>
      <div>{children}</div>
    </details>
  );
}
export function Value({
  metric,
  label,
  signed = false,
}: {
  metric: Metric;
  label: string;
  signed?: boolean;
}) {
  return (
    <div className={styles.valueWrap}>
      <span className={styles.number}>{displayMetric(metric, signed)}</span>
      <Info label={label}>
        {methods[metric.method] && <p>{methods[metric.method]}</p>}
        {metric.value === null && !metric.reason_codes.length && (
          <p>Нет подтверждённого значения для этого периода.</p>
        )}
        <Explanation codes={metric.reason_codes} />
        {metric.estimate && (
          <p>Оценка по сохранённым выпискам; не подтверждённая доходность отчётности.</p>
        )}
      </Info>
    </div>
  );
}
