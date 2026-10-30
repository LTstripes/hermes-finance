import { type ReactNode, useLayoutEffect, useRef, useState } from "react";
import { displayMetric, type Metric } from "./model";
import styles from "./Returns.module.css";

const reasons: Record<string, string> = {
  known_source_history_coupons_only:
    "Учтены только известные полученные купоны из сохранённой истории выписок каждого включённого счёта.",
  current_coupon_history_unavailable:
    "Актуальная проверенная история купонов этого счёта недоступна; старые значения не подставляются.",
  coupon_income_unavailable: "Сумма полученных купонов по этому счёту не подтверждена.",
  coupon_history_accounts_missing_or_excluded:
    "По части счетов история отсутствует либо счёт исключён; доступные купоны остальных счетов сохранены.",
  coupon_account_history_periods_differ:
    "Границы доступной истории купонов различаются по счетам и приведены отдельно.",
  source_account_identity_mapping_conflict:
    "Соответствие источника каноническому счёту конфликтует; компонент не включён в известный итог.",
  source_proof_stale: "Проверка выписок устарела; требуется актуальное подтверждение.",
  known_components_only:
    "В известный результат входят только включённые компоненты с подтверждённой основой и отсутствием пересечений.",
  source_only_not_financial_close:
    "Основа — сохранённые выписки; данные не означают принятие финансового месяца.",
  all_history_source_proof_absent: "Проверенный расчёт за всю историю отсутствует.",
  all_history_source_proof_unavailable: "Проверенный расчёт за всю историю недоступен.",
  instrument_name_unavailable: "Название бумаги не подтверждено; используется точный ISIN.",
  instrument_name_conflict:
    "В источниках различаются названия; навигация связана только по точному ISIN.",
  known_received_interest_only: "Включены только известные фактически полученные проценты.",
  deposit_full_history_not_proven: "Полнота истории депозитов не подтверждена.",
  draft_deposit_interest_excluded: "Проценты из черновиков не включены в известный итог.",
  gold_period_return_unproven: "Результат золота за период не подтверждён.",
  snapshot_result_not_period_return:
    "Результат сохранённого снимка не является доходностью периода.",
  saved_snapshot_unrealized_only: "Доступен только сохранённый нереализованный результат.",
  current_catalogue_gold_classification: "Классификация золота основана на текущем справочнике.",
  historical_gold_classification_unproven: "Историческая классификация золота не подтверждена.",
  gold_snapshot_cost_result_missing_or_conflicting:
    "Стоимость, затраты или результат снимка отсутствуют либо противоречат друг другу.",
  gold_cost_return_denominator_unavailable:
    "Нет подтверждённых положительных затрат для процентного результата.",
  gold_dated_trade_history_unavailable: "Подтверждённая история сделок с золотом недоступна.",
  overall_aggregation_pending_review:
    "Общий результат по категориям и общая процентная доходность пока не подтверждены. Доступные компоненты показаны отдельно.",

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
  known_source_history_coupons:
    "Сумма купонов по уникальным счетам, рассчитанная сервером по актуальной сохранённой истории. Суммы инструментов и месячные наблюдения повторно не добавляются.",
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
