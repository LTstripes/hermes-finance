import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import type { SourceIntake } from "../../api/sourceIntake";
import {
  type Assumptions,
  assumptionKeys,
  matchesSourceIntakeResult,
  readSourceIntakeResult,
  type SourceIntakeResultRequest,
} from "../../api/sourceIntakeResult";
import { Button } from "../ui";
import styles from "./BrokerMonthReview.module.css";

const labels: Record<keyof Assumptions, { title: string; explanation: string }> = {
  no_unobserved_movements: {
    title: "Предполагаю отсутствие дополнительных ненаблюдаемых сделок и движений бумаги",
    explanation:
      "Полнота сделок, переводов и корпоративных действий не доказана. Пустой список известных сделок не доказывает их отсутствия.",
  },
  no_unobserved_payouts: {
    title: "Предполагаю отсутствие дополнительных ненаблюдаемых выплат и прав на них",
    explanation:
      "Известные net-дивиденды подтверждены отдельно; полнота выплат и прав на них за период неизвестна.",
  },
  no_other_costs_or_taxes: {
    title: "Предполагаю отсутствие других отдельно относимых расходов и налогов",
    explanation:
      "Подтверждение всех отдельных расходов отсутствует. Удержания, уже включённые в net, повторно не вычитаются; неизвестный налог не становится фактическим нулём.",
  },
};

export function sourceResultGap(code: string): string {
  if (code === "bond_dirty_basis_source_unproven")
    return "Облигации заблокированы: источник не подтверждает базу с НКД (clean/dirty). Условный итог недоступен.";
  if (code === "changing_quantity_result_unavailable" || code === "quantity_changed_not_profit")
    return "Количество бумаги изменилось: V1−V0+P неприменим. Нужен отдельный датированный расчёт денежных потоков (MWR); в этой версии итог не рассчитывается.";
  if (code === "source_intake_not_bound")
    return "Сохранённый оригинал не привязан к счёту и месяцу: экономические читатели недоступны.";
  if (code === "source_intake_pending")
    return "Строгое финансовое принятие (DRAFT) ещё не подтверждено; число остаётся условным.";
  if (code === "source_intake_identity_deferred")
    return "Решение по идентичности этой бумаги отложено: число не рассчитывается до явного решения.";
  if (code === "source_intake_account_missing") return "Счёт из разбора не найден.";
  if (code === "source_intake_instrument_absent") return "В оригинале нет позиции с таким ISIN.";
  if (code === "source_intake_instrument_ambiguous")
    return "В оригинале несколько неоднозначных записей по этому ISIN.";
  if (code === "source_reader_unavailable")
    return "Чтение источника не удалось; число не рассчитывается.";
  if (code === "source_intake_currency_unproven") return "Валюта бумаги не подтверждена.";
  if (code === "source_intake_currency_conflict")
    return "Валюта бумаги противоречива; RUB не подставляется.";
  if (code === "source_intake_currency_unsupported" || code === "instrument_currency_unsupported")
    return "Поддерживается только RUB; валюта карточки или источника не RUB.";
  if (code === "instrument_identity_unmapped")
    return "Бумага не сопоставлена с карточкой инструмента: подтверждённые выплаты и сделки недоступны.";
  if (code === "instrument_identity_mismatch")
    return "Карточка инструмента не совпадает с ISIN или типом из оригинала.";
  if (code === "money_economic_effect_unproven")
    return "В оригинале есть Money-проводки с недоказанным экономическим эффектом: скрытая выплата не исключается, итог не считается.";
  if (code === "observed_native_movement_or_crossing" || code === "known_execution_or_crossing")
    return "В оригинале есть наблюдаемые сделки или переходящие расчёты по бумаге: фиксированное владение не подтверждено.";
  if (code === "proven_net_dividend_required")
    return "Нет полностью подтверждённых net-дивидендов за период; отсутствие записи не считается нулём.";
  if (code === "no_observed_events") return "Выплаты за период не наблюдались; это не ноль.";
  if (code === "source_fixed_holding_unproven")
    return "В оригинале нет ровно одной позиции по этой бумаге.";
  if (code === "ambiguous_overlapping_originals")
    return "Перекрывающиеся сохранённые оригиналы не согласованы по этой бумаге.";
  if (code.includes("quantity") || code.includes("cash"))
    return "Не сходятся собственные контроли оригинала (деньги или количество).";
  if (code.includes("unparsed") || code.includes("syntax") || code === "unknown_section")
    return "В оригинале есть неразобранные строки: экономический смысл не установлен.";
  return "Оценка или подтверждение источника недоступны, изменились либо противоречат друг другу.";
}

// Keep the exact API decimal string; never round money through binary Number.
const rub = (amount: string | null) =>
  amount === null ? "Неизвестно" : `${amount.replace(".", ",")} ₽`;
const percent = (value: string | null) =>
  value === null ? "Неизвестно" : `${value.replace(".", ",")}%`;
const exact = (value: string, unit: string) =>
  `${value.startsWith("-") || /^0(\.0+)?$/.test(value) ? "" : "+"}${value.replace(".", ",")}${unit}`;

function previousDay(value: string): string {
  const day = new Date(`${value}T00:00:00Z`);
  day.setUTCDate(day.getUTCDate() - 1);
  return day.toISOString().slice(0, 10);
}

export function SourceIntakeInstrumentResult({ intake }: { intake: SourceIntake }) {
  const proposals = useMemo(() => intake.proposals.filter((proposal) => proposal.isin), [intake]);
  const [isin, setIsin] = useState(proposals[0]?.isin ?? "");
  const selected = proposals.some((proposal) => proposal.isin === isin)
    ? isin
    : (proposals[0]?.isin ?? "");
  const [chosen, setChosen] = useState<Assumptions>({
    no_unobserved_movements: false,
    no_unobserved_payouts: false,
    no_other_costs_or_taxes: false,
  });
  const [request, setRequest] = useState<SourceIntakeResultRequest | null>(null);
  const t0 = previousDay(intake.covered_from);
  const t1 = intake.covered_to;
  const query = useQuery({
    queryKey: ["source-intake-instrument-result", request],
    queryFn: ({ signal }) => {
      if (!request) throw new Error("Choose a source intake context");
      return readSourceIntakeResult(request, signal);
    },
    enabled: request !== null,
    staleTime: 0,
    gcTime: 0,
    retry: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
  const data = request && !query.isFetching && !query.isError ? query.data : null;
  const fresh = data && request && matchesSourceIntakeResult(data, request);
  const h = fresh ? data.hypothetical_result : null;
  const change = (mutate: () => void) => {
    setRequest(null);
    mutate();
  };
  return (
    <section
      className={styles.stack}
      aria-label="Условный результат бумаги из сохранённого оригинала"
    >
      <h3>Условный результат бумаги из сохранённого оригинала</h3>
      <p>
        Гипотетический результат одной RUB-акции из сохранённого оригинала: V1 − V0 + P, где P —
        подтверждённые net-дивиденды. Значения позиции — собственные EOD-факты оригинала. Простой
        процент за (t0,t1], без пересчёта на год и без XIRR/TWRR.
      </p>
      <p>
        <strong>Фактическая доходность пока недоступна</strong>. Полнота периода неизвестна.
        Неизвестные выплаты, комиссии, НКД и налоги не становятся нулём. Облигации и бумаги с
        изменением количества не получают числовой итог в этой версии.
      </p>
      {proposals.length === 0 ? (
        <p role="alert">
          В сохранённом оригинале нет бумаг с распознанным ISIN. Число не рассчитывается.
        </p>
      ) : (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (selected)
              setRequest({
                intakeId: intake.id,
                isin: selected,
                t0,
                t1,
                chosen: { ...chosen },
                nonce: crypto.randomUUID(),
              });
          }}
        >
          <label className={styles.field}>
            Бумага из сохранённого оригинала
            <select
              aria-label="Бумага из сохранённого оригинала"
              value={selected}
              onChange={(event) => change(() => setIsin(event.target.value))}
            >
              {proposals.map((proposal) => (
                <option key={proposal.isin} value={proposal.isin}>
                  {proposal.source_name ?? proposal.isin} · {proposal.isin}
                  {proposal.instrument_type === "bond" ? " · облигация" : ""}
                  {proposal.hermes_id === null || proposal.hermes_id === undefined
                    ? " · без карточки"
                    : ""}
                </option>
              ))}
            </select>
          </label>
          <fieldset>
            <legend>Три явных допущения сценария — каждое выбирается отдельно</legend>
            {assumptionKeys.map((key) => (
              <label key={key} className={styles.review}>
                <input
                  type="checkbox"
                  checked={chosen[key]}
                  onChange={(event) =>
                    change(() => setChosen({ ...chosen, [key]: event.target.checked }))
                  }
                />
                <span>
                  <span>{labels[key].title}</span>
                  <small>{labels[key].explanation}</small>
                </span>
              </label>
            ))}
          </fieldset>
          <Button type="submit" disabled={query.isFetching}>
            Рассчитать условный результат
          </Button>
        </form>
      )}
      {request && query.isFetching ? (
        <p role="status">Перечитываем оригинал, выплаты и сделки в одном снимке…</p>
      ) : null}
      {request && query.isError ? (
        <p role="alert">Не удалось проверить сценарий. Повторите расчёт.</p>
      ) : null}
      {data && !fresh ? (
        <p role="alert">Ответ не соответствует выбранному сценарию. Повторите расчёт.</p>
      ) : null}
      {fresh && h && data ? (
        <div className={styles.summary} data-testid="source-intake-result">
          <h4>
            {data.account ? `${data.account.name} · ` : "Без счёта · "}
            {data.instrument.name ?? data.instrument.isin} · ({data.t0}, {data.t1}] · RUB
          </h4>
          <p>
            Разбор #{data.intake.id}, версия {data.intake.head_seq}.{" "}
            {data.intake.finance_link === "present"
              ? "Есть проверенная ссылка на строгий DRAFT."
              : "Финансовое принятие не подтверждено."}
          </p>
          <dl className={styles.metrics}>
            <div>
              <dt>Изменение стоимости позиции (котировка)</dt>
              <dd>
                {rub(data.observed.value_change)} / {percent(data.observed.value_change_percent)}
              </dd>
              <dd>
                {rub(data.observed.beginning_value)} → {rub(data.observed.ending_value)} ·{" "}
                {data.observed.quantity ?? "количество неизвестно"} шт.
              </dd>
            </div>
            <div>
              <dt>Подтверждённые net-дивиденды</dt>
              <dd>{rub(data.known.net_distributions)}</dd>
            </div>
            <div>
              <dt>Условный итог (V1 − V0 + P)</dt>
              <dd>
                {h.conditional_result !== null && h.conditional_period_percent !== null
                  ? `${exact(h.conditional_result, " ₽")} / ${exact(
                      h.conditional_period_percent,
                      "%",
                    )} за период`
                  : "недоступен (RUB и % неизвестны)"}
              </dd>
            </div>
          </dl>
          <p>
            Изменение котировки — не прибыль, если количество менялось; итог учитывает дивиденды
            отдельно и не удваивает их.
          </p>
          {data.known.payouts?.events.length ? (
            <details>
              <summary>Подтверждённые выплаты за период</summary>
              {data.known.payouts.events.map((event) => (
                <p key={event.cash_flow_id} className={styles.sourceName}>
                  {event.date} · {event.kind === "dividend" ? "Дивиденд" : "Купон"}:{" "}
                  {rub(event.booked_net)}
                  {event.included_in_known_net ? "" : " (в подтверждённую сумму не включено)"}
                </p>
              ))}
            </details>
          ) : null}
          <details>
            <summary>Подтверждённые отдельные комиссии и НКД</summary>
            {data.known.confirmed_cost_legs.length ? (
              data.known.confirmed_cost_legs.map((leg) => (
                <p key={`${leg.trade_id}:${leg.role}`} className={styles.sourceName}>
                  Сделка #{leg.trade_id} ·{" "}
                  {leg.role === "commission" ? "комиссия" : "уплаченный НКД"}: {rub(leg.signed_rub)}
                  {leg.effective_date ? ` · ${leg.effective_date}` : ""}
                </p>
              ))
            ) : (
              <p>
                Подтверждённых отдельных комиссий и НКД не найдено. Это не подтверждение их
                отсутствия: полнота расходов неизвестна.
              </p>
            )}
          </details>
          {data.missing_assumptions.length ? (
            <p>Выбраны не все три допущения. Число недоступно.</p>
          ) : null}
          {data.hard_blockers.length ? (
            <div className={styles.exceptions}>
              <p>Расчёт заблокирован источниками:</p>
              <ul>
                {data.hard_blockers.map((code) => (
                  <li key={code} className={styles.sourceName}>
                    {sourceResultGap(code)} <small>({code})</small>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {data.observed.reason_codes.length ? (
            <details>
              <summary>Причины по наблюдаемым фактам позиции</summary>
              <ul>
                {data.observed.reason_codes.map((code) => (
                  <li key={code} className={styles.sourceName}>
                    {sourceResultGap(code)} <small>({code})</small>
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
          <details>
            <summary>Источники и метод сценария</summary>
            <p>
              {data.method} v{data.version}; authority=hypothetical; V1−V0+P; annualized=false.
              Оригинал: {data.intake.document_sha256.slice(0, 16)}…; базис начала —{" "}
              {data.observed.beginning_basis}, конца — {data.observed.ending_basis}. Это не
              фактический ноль отсутствующих событий и не подтверждение полноты.
            </p>
            <p>
              Доля за период: {h.conditional_period_fraction ?? "неизвестна"}; процент:{" "}
              {h.conditional_period_percent ?? "неизвестен"} (percentage_points). Точность Decimal:{" "}
              {h.decimal_precision} значащих цифр; без округления для отображения.
            </p>
            <p>
              Валютный базис: {data.currency_assessment.effective_currency ?? "не подтверждён"} (
              {data.currency_assessment.basis ?? "неизвестен"}
              {data.currency_assessment.provisional ? ", предварительно" : ""}).
            </p>
            {data.intake.exceptions.length ? (
              <div>
                <p>Текущие исключения разбора:</p>
                <ul>
                  {data.intake.exceptions.map((code) => (
                    <li key={code} className={styles.sourceName}>
                      {sourceResultGap(code)} <small>({code})</small>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
            <p>
              Проверено только при этом чтении. Повторное использование подтверждения полноты
              недоступно.
            </p>
          </details>
        </div>
      ) : null}
    </section>
  );
}
