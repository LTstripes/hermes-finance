import { type ReactNode, useLayoutEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { type ReasonContext, reasonCopy } from "../../lib/reasonCopy";
import { displayMetric, type Metric } from "./model";
import styles from "./Returns.module.css";

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
  "known-booked-net-payouts":
    "Точная сумма известных принятых выплат после удержаний. Покрытие периода частичное; это не оценка. Выплаты уже включены в результат.",
  credited_payments:
    "Фактически зачисленные выплаты. Будущее расписание сюда не входит; выплаты не прибавляются к результату повторно.",
  PERF04A: "Изменение стоимости после внешних пополнений и снятий, по подтверждённым отчётам.",
  twrr: "Доходность TWRR за выбранный период, по подтверждённым отчётам.",
};
export function visibleReturnReasons(codes: string[]) {
  return codes.filter((code) => code !== "broker_gift_external_flow");
}

export function Explanation({ codes, context }: { codes: string[]; context?: ReasonContext }) {
  const visibleCodes = visibleReturnReasons(codes);
  const copy = [
    ...new Map(
      visibleCodes.map((code) => {
        const value = reasonCopy(code, { surface: "returns", ...context });
        return [value.message, value];
      }),
    ).values(),
  ];
  return (
    <>
      {copy.map(({ message, action }) => (
        <p key={message}>
          {message}
          {action && (
            <>
              {" "}
              <Link to={action.href}>{action.label}</Link>
            </>
          )}
        </p>
      ))}
      {visibleCodes.length > 0 && (
        <details>
          <summary>Подробности</summary>
          <code>{[...new Set(visibleCodes)].join(", ")}</code>
        </details>
      )}
    </>
  );
}
/** Explain only missing operands, once per message, next to the displayed metrics. */
export function MissingMetricNote({ metrics }: { metrics: readonly Metric[] }) {
  const messages = [
    ...new Set(
      metrics
        .filter((metric) => metric.value === null)
        .map((metric) => {
          const code = visibleReturnReasons(metric.reason_codes)[0];
          return code
            ? reasonCopy(code, { surface: "returns" }).message
            : "Нет подтверждённого значения для этого периода.";
        }),
    ),
  ];
  return messages.length ? <p role="note">{messages.join(" ")}</p> : null;
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
        {metric.value === null && !visibleReturnReasons(metric.reason_codes).length && (
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
