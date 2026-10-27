import { type ReactNode, useLayoutEffect, useRef, useState } from "react";
import { displayMetric, type Metric } from "./model";
import styles from "./Returns.module.css";

const reasons: Record<string, string> = {
  historical_brokerage_iis_type_unproven:
    "Исторический тип счёта не подтверждён. Для известной части по всем выпискам включите и брокерские счета, и ИИС.",
  basket_native_identity_unproven:
    "Идентичность счёта или его aliases не подтверждена однозначно; сумма исключена.",
  basket_account_identity_overlap:
    "Представления счетов пересекаются или противоречат друг другу. Сумма исключена во избежание двойного учёта.",
  basket_crossing_reconciliation_unavailable:
    "Есть движения через границу счёта или сведения о переводе. Их общий эффект и расходы для выбранной корзины не подтверждены; месяц исключён.",
  accepted_basket_pnl_and_category_unproven:
    "Подтверждённый денежный мост счёта не является P&L этой корзины; историческая категория также не подтверждена.",
  source_inventory_unproven: "Состав счетов по выпискам не подтверждён.",
  deposit_inventory_unproven: "Нет наблюдений, доказывающих состав депозитов за период.",
  deposit_snapshot_missing:
    "В этом месяце нет наблюдения по депозитам этого счёта. Это не нулевые проценты.",
  calendar_month_missing_or_not_closed:
    "Нет единственного закрытого отчёта за этот календарный месяц.",
  physical_gold_period_evidence_unavailable:
    "Доходность физического золота за период не подтверждена. Текущая стоимость и прирост от цены покупки её не заменяют.",
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
  calendar_month_not_closed: "За этот месяц пока нет закрытого отчёта.",
  calendar_month_missing: "Нет результата за полный календарный месяц.",
  calendar_month_ambiguous: "Нельзя однозначно выбрать результат месяца.",
  calendar_month_unavailable: "Результат месяца недоступен.",
  partial_calendar_month: "Неполный календарный месяц не включён в сумму.",
};
const methods: Record<string, string> = {
  available_calendar_months:
    "Сумма доступных полных календарных результатов одного счёта. Это частичный итог, без процента.",
  modified_dietz: "Процент — оценка Modified Dietz за указанные даты, без пересчёта на год.",
  chained_modified_dietz:
    "Процент — последовательное связывание месячных оценок Modified Dietz. Пропуски не соединяются.",
  source_monthly:
    "Результат по выпискам после исключения пополнений и снятий. Выплаты уже включены в результат.",
  source_period:
    "Итог по границам всей доступной истории и движениям денег. Частичные результаты не подставляются вместо полного итога.",
  source_account_reconciliation:
    "Результат всего счёта за указанные даты, включая денежный остаток и операции счёта, по существующему расчёту выписок.",
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
  const ref = useRef<HTMLDetailsElement>(null);
  const [open, setOpen] = useState(false);
  useLayoutEffect(() => {
    if (!open) return;
    const place = () => {
      const details = ref.current;
      const panel = details?.querySelector("div");
      if (!details || !panel) return;
      const anchor = details.getBoundingClientRect();
      const left = Math.max(16, (details.closest("main")?.getBoundingClientRect().left ?? 0) + 16);
      const width = Math.min(310, window.innerWidth - left - 16);
      panel.style.width = `${width}px`;
      panel.style.left = `${Math.max(left, Math.min(anchor.left, window.innerWidth - width - 16))}px`;
      panel.style.top = `${Math.max(16, Math.min(anchor.bottom + 8, window.innerHeight - panel.offsetHeight - 16))}px`;
    };
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [open]);
  return (
    <details ref={ref} className={styles.info} onToggle={(e) => setOpen(e.currentTarget.open)}>
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
