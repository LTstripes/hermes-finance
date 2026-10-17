import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import type { PayoutScope } from "../api/instrumentCashIncome";
import {
  type Assumptions,
  assumptionKeys,
  evaluateInstrumentWhatIf,
  matchesWhatIf,
  type WhatIfRequest,
} from "../api/instrumentWhatIf";
import styles from "./InstrumentWhatIf.module.css";

const labels: Record<keyof Assumptions, { title: string; explanation: string }> = {
  no_unobserved_movements: {
    title: "Предполагаю отсутствие дополнительных ненаблюдаемых сделок и движений бумаги",
    explanation:
      "Полнота BUY/SELL, переводов и корпоративных действий не доказана. Пустой список известных сделок не доказывает их отсутствия.",
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

export function whatIfGap(code: string): string {
  if (code === "bond_dirty_basis_source_unproven")
    return "Облигации заблокированы: нет оценки с учётом НКД, подтверждённой источником.";
  if (code.includes("quantity") || code.includes("fixed"))
    return "Не подтверждено неизменное положительное количество бумаги.";
  if (code.includes("money") || code.includes("unparsed") || code.includes("unsupported"))
    return "Есть неразобранные или неподдерживаемые строки, либо недоказанный денежный эффект.";
  if (code.includes("dividend") || code.includes("payout") || code.includes("booked"))
    return "Не все выплаты имеют действующее net-подтверждение.";
  if (
    code.includes("execution") ||
    code.includes("movement") ||
    code.includes("crossing") ||
    code.includes("principal") ||
    code.includes("repo")
  )
    return "Наблюдаемая сделка, движение или переходящий расчёт несовместимы с фиксированным владением.";
  if (code.includes("gap")) return "Есть разрыв календаря источников; допущения его не устраняют.";
  return "Оценка, историческая идентичность или подтверждение источника недоступны, изменились либо противоречат друг другу.";
}

const exact = (value: string, unit: string) =>
  `${value.startsWith("-") || /^0(\.0+)?$/.test(value) ? "" : "+"}${value.replace(".", ",")}${unit}`;

export function InstrumentWhatIf({ scope }: { scope: PayoutScope }) {
  const [chosen, setChosen] = useState<Assumptions>({
    no_unobserved_movements: false,
    no_unobserved_payouts: false,
    no_other_costs_or_taxes: false,
  });
  const [request, setRequest] = useState<WhatIfRequest | null>(null);
  const query = useQuery({
    queryKey: ["instrument-what-if", request],
    queryFn: ({ signal }) => {
      if (!request) throw new Error("Choose scenario context");
      return evaluateInstrumentWhatIf(request, signal);
    },
    enabled: request !== null,
    staleTime: 0,
    gcTime: 0,
    retry: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
  const data = request && !query.isFetching && !query.isError ? query.data : null;
  const fresh = data && request && matchesWhatIf(data, request);
  const h = fresh ? data.hypothetical_result : null;
  return (
    <section aria-label="Условный результат бумаги" className={styles.panel}>
      <h3>Условный результат бумаги</h3>
      <p>
        Гипотетический сценарий для неизменного количества RUB-акции. V1 − V0 + P, где P —
        подтверждённые net-дивиденды. Простой процент за (t0,t1], без пересчёта на год,
        реинвестирования и XIRR/TWRR.
      </p>
      <p>
        <strong>Фактическая доходность пока недоступна</strong>. Полнота периода неизвестна.
        Допущения не отменяют наблюдаемые противоречия. Облигации заблокированы до подтверждения
        dirty-оценки с НКД.
      </p>
      <fieldset className={styles.choices}>
        <legend>Три явных допущения сценария — каждое выбирается отдельно</legend>
        {assumptionKeys.map((k) => (
          <label key={k} className={styles.choice}>
            <input
              type="checkbox"
              checked={chosen[k]}
              onChange={(e) => {
                setRequest(null);
                setChosen({ ...chosen, [k]: e.target.checked });
              }}
            />
            <span>
              <span>{labels[k].title}</span>
              <small>{labels[k].explanation}</small>
            </span>
          </label>
        ))}
      </fieldset>
      <button
        type="button"
        disabled={query.isFetching}
        onClick={() => setRequest({ scope, chosen: { ...chosen }, nonce: crypto.randomUUID() })}
      >
        Рассчитать условный результат
      </button>
      {request && query.isFetching ? (
        <p role="status">Перечитываем оценки, выплаты и сделки в одном снимке…</p>
      ) : null}
      {request && query.isError ? (
        <p role="alert">Не удалось проверить сценарий. Повторите расчёт.</p>
      ) : null}
      {data && !fresh ? (
        <p role="alert">Ответ не соответствует выбранному сценарию. Повторите расчёт.</p>
      ) : null}
      {fresh && h ? (
        <div data-testid="instrument-what-if-result" aria-live="polite">
          <p>
            {data.account.name} · {data.instrument.name} · ({data.t0}, {data.t1}] · RUB
          </p>
          {h.conditional_result !== null && h.conditional_period_percent !== null ? (
            <p className={styles.value}>
              Условно: {exact(h.conditional_result, " ₽")} /{" "}
              {exact(h.conditional_period_percent, "%")} за период
            </p>
          ) : (
            <p>Условный результат: недоступен (RUB и % неизвестны).</p>
          )}
          {data.missing_assumptions.length ? (
            <p>Выбраны не все три допущения. Число недоступно.</p>
          ) : null}
          {data.hard_blockers.length ? (
            <div>
              <p>Расчёт заблокирован источниками:</p>
              <ul>
                {data.hard_blockers.map((c) => (
                  <li key={c}>
                    {whatIfGap(c)} <small>({c})</small>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          <details>
            <summary>Источники и метод сценария</summary>
            <p>
              {data.method} v{data.version}; authority=hypothetical; V1−V0+P; annualized=false. Это
              не фактический ноль отсутствующих событий и не подтверждение полноты.
            </p>
            <p>
              Доля за период: {h.conditional_period_fraction ?? "неизвестна"}; процент:{" "}
              {h.conditional_period_percent ?? "неизвестен"} (percentage_points). Точность Decimal:{" "}
              {h.decimal_precision} значащих цифр; без округления для отображения.
            </p>
            <p>
              V0: {data.observed?.opening.market_value ?? "неизвестно"} RUB; V1:{" "}
              {data.observed?.closing.market_value ?? "неизвестно"} RUB; известные net-дивиденды:{" "}
              {data.accepted_known.payouts?.known_booked_net.dividend ?? "неизвестно"} RUB.
            </p>
            {data.source_checks.map((s) => (
              <p key={s.source_import_id}>Источник #{s.source_import_id}</p>
            ))}
            {data.accepted_known.payouts?.events.map((e) => (
              <p key={e.cash_flow_id}>
                ICF #{e.cash_flow_id}: {e.receipt_ids.join("; ")}
              </p>
            ))}
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
