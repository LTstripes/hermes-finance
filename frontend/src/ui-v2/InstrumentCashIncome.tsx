import { useQuery } from "@tanstack/react-query";
import { useRef, useState } from "react";
import type { PayoutScope } from "../api/instrumentCashIncome";
import { getInstrumentObservations } from "../api/instrumentEodObservations";
import { listInstruments } from "../api/instruments";
import type { Account } from "../api/types";
import { formatDate } from "../lib/format";
import incomeStyles from "./InstrumentCashIncome.module.css";
import { InstrumentEodEvidence } from "./InstrumentEodEvidence";
import { InstrumentTrades } from "./InstrumentTrades";
import { InstrumentWhatIf } from "./InstrumentWhatIf";
import styles from "./UiV2CapitalPerformance.module.css";

const stateLabels = {
  manual_booked: "Ручная запись",
  source_accepted: "Источник подтверждён",
  retired_or_unmatched: "Подтверждение отозвано или не совпадает",
  incomplete_unknown: "Подтверждение неполное",
};
const provenanceLabels: Record<string, string> = {
  manual: "Ручная запись",
  accepted_money_coupon: "Принятый купон Money",
  typed_depository: "Депозитарный отчёт PDF",
};
export function payoutGap(code: string): string {
  if (code === "canonical_revision_unavailable")
    return "Нет действующего журнала изменений для текущего подтверждения записи. Выплата показана отдельно от подтверждённой суммы.";
  if (code === "manual_revision_unavailable")
    return "У ручной записи нет журнала версий для проверки изменений. Она показана отдельно от подтверждённой суммы.";
  if (code === "historical_instrument_identity_unknown")
    return "Не подтверждена историческая RUB-идентичность бумаги.";
  if (code === "payout_scope_unsupported")
    return "Не подтверждены счёт, тип бумаги, валюта или дата выплаты.";
  if (code === "typed_statement_conflict") return "Запись расходится с принятой версией PDF.";
  if (code === "payout_source_unproven")
    return "Для записи нет действующего подтверждения источника.";
  return "Подтверждение источника сейчас недоступно или изменилось.";
}
// Keep the exact API decimal string; never round money through binary Number.
const rub = (amount: string | null) =>
  amount === null ? "Неизвестно" : `${amount.replace(".", ",")} ₽`;

export function InstrumentCashIncome({
  accounts,
  start,
  end,
  accountId,
}: {
  accounts: Account[] | undefined;
  start: string;
  end: string;
  accountId: number | null;
}) {
  const [open, setOpen] = useState(false);
  const generation = useRef(0);
  const evidenceRead = useRef(0);
  const [account, setAccount] = useState(accountId ? String(accountId) : "");
  const [instrument, setInstrument] = useState("");
  const [t0, setT0] = useState(start);
  const [t1, setT1] = useState(end);
  const [request, setRequest] = useState<{ scope: PayoutScope; generation: number } | null>(null);
  const instruments = useQuery({
    queryKey: ["known-payout-instruments"],
    queryFn: ({ signal }) => listInstruments({}, signal),
    enabled: open,
  });
  const scope = { accountId: Number(account), instrumentId: Number(instrument), t0, t1 };
  const valid = !!account && !!instrument && !!t0 && !!t1 && t0 < t1;
  const matching = request !== null && JSON.stringify(request.scope) === JSON.stringify(scope);
  const result = useQuery({
    queryKey: ["instrument-observations-and-payouts", request],
    queryFn: async ({ signal }) => {
      if (!request) throw new Error("Choose a payout scope");
      // Each GET is a new authority epoch, even for identical data or batched
      // fetching notifications. Never derive it from amounts/fingerprints/time.
      const epoch = ++evidenceRead.current;
      return { epoch, response: await getInstrumentObservations(request.scope, signal) };
    },
    enabled: open && matching,
    staleTime: 0,
    gcTime: 0,
    retry: false,
    refetchOnWindowFocus: true,
  });
  const response =
    open && matching && !result.isFetching && !result.isError ? result.data?.response : null;
  const data = response?.known_payouts ?? null;
  const fresh =
    response &&
    response.method === "persisted-instrument-eod-pair" &&
    response.version === 1 &&
    response.account.id === scope.accountId &&
    response.instrument.id === scope.instrumentId &&
    response.t0 === t0 &&
    response.t1 === t1 &&
    [response.opening, response.closing].every(
      (b, i) =>
        b.account_id === scope.accountId &&
        b.instrument_id === scope.instrumentId &&
        b.date === (i === 0 ? t0 : t1),
    ) &&
    data &&
    data.account.id === scope.accountId &&
    data.instrument.id === scope.instrumentId &&
    data.t0 === t0 &&
    data.t1 === t1 &&
    data.method === "known-booked-net-payouts" &&
    data.version === 1;
  const change = (set: (v: string) => void, value: string) => {
    setRequest(null);
    set(value);
  };
  return (
    <section
      aria-label="Известные выплаты по бумаге"
      className={`${styles.preparation} ${incomeStyles.panel}`}
    >
      <h2>Наблюдения и выплаты по бумаге</h2>
      <button
        type="button"
        className={styles.inlineButton}
        aria-expanded={open}
        onClick={() => {
          setOpen(!open);
          setRequest(null);
        }}
      >
        {open ? "Скрыть выплаты" : "Выбрать бумагу и период"}
      </button>
      {open ? (
        <>
          <p>
            Чистые зачисленные купоны и дивиденды за (начальная дата, конечная дата]. Полнота
            истории неизвестна. Полная доходность бумаги в RUB и % недоступна.
          </p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (valid) setRequest({ scope, generation: ++generation.current });
            }}
          >
            <div className={styles.controls}>
              <label>
                Счёт выплат
                <select
                  aria-label="Счёт выплат"
                  value={account}
                  onChange={(e) => change(setAccount, e.target.value)}
                >
                  <option value="">Выберите счёт</option>
                  {(accounts ?? [])
                    .filter((a) => ["brokerage", "iis"].includes(a.account_type))
                    .map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.name}
                      </option>
                    ))}
                </select>
              </label>
              <label>
                Бумага
                <select
                  aria-label="Бумага выплат"
                  value={instrument}
                  onChange={(e) => change(setInstrument, e.target.value)}
                >
                  <option value="">Выберите бумагу</option>
                  {(instruments.data ?? []).map((i) => (
                    <option key={i.id} value={i.id}>
                      {i.name}
                      {i.is_active ? "" : " (неактивна)"}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Начальная дата EOD (выплаты — после неё)
                <input
                  aria-label="Выплаты после даты"
                  type="date"
                  value={t0}
                  onChange={(e) => change(setT0, e.target.value)}
                />
              </label>
              <label>
                Конечная дата EOD (выплаты — включительно)
                <input
                  aria-label="Выплаты по дату"
                  type="date"
                  value={t1}
                  onChange={(e) => change(setT1, e.target.value)}
                />
              </label>
            </div>
            {!valid ? (
              <p>Выберите счёт, бумагу и период: начальная дата должна быть раньше конечной.</p>
            ) : null}
            <button
              className={styles.inlineButton}
              type="submit"
              disabled={!valid || result.isFetching}
            >
              Прочитать оценки и выплаты
            </button>
          </form>
          <InstrumentTrades request={open && matching ? request : null} />
          {instruments.isError ? (
            <p role="alert">
              Не удалось загрузить список бумаг.{" "}
              <button type="button" onClick={() => void instruments.refetch()}>
                Повторить
              </button>
            </p>
          ) : null}
          {matching && result.isFetching ? (
            <p role="status">Проверяем записи и текущие подтверждения…</p>
          ) : null}
          {matching && result.isError ? (
            <p role="alert">Не удалось проверить выплаты. Повторите чтение.</p>
          ) : null}
          {data && !fresh ? (
            <p role="alert">Ответ не соответствует выбранному контексту. Повторите чтение.</p>
          ) : null}
          {fresh ? (
            <div>
              <h3>
                {data.account.name} · {data.instrument.name}
              </h3>
              <p>
                {formatDate(data.t0)} EOD — {formatDate(data.t1)} EOD · RUB · выплаты за (t0,t1]
              </p>
              {response ? <InstrumentEodEvidence result={response} /> : null}
              <section aria-label="Известные net-выплаты" data-testid="known-payouts-result">
                <h3>Известные net-выплаты</h3>
                <p>
                  Известные зачисления: купоны {rub(data.known_booked_net.coupon)}; дивиденды{" "}
                  {rub(data.known_booked_net.dividend)}.
                </p>
                <p>
                  Записей: {data.event_count}; включено в известную сумму: {data.known_event_count}.
                  Полнота периода неизвестна.
                </p>
                {data.event_count === 0 ? (
                  <p>Записей не обнаружено. Это не подтверждает нулевой доход за период.</p>
                ) : null}
                {data.event_count > 0 ? (
                  <div className={incomeStyles.tableWrap}>
                    <table className={incomeStyles.table}>
                      <thead>
                        <tr>
                          <th>Дата / вид</th>
                          <th>Зачислено net</th>
                          <th>Подтверждение</th>
                          <th>Происхождение</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.events.map((event) => (
                          <tr key={event.cash_flow_id}>
                            <td>
                              {formatDate(event.date)} ·{" "}
                              {event.kind === "coupon" ? "Купон" : "Дивиденд"}
                            </td>
                            <td>
                              {rub(event.booked_net)}
                              {!event.included_in_known_net ? (
                                <p>В известную сумму не включено</p>
                              ) : null}
                            </td>
                            <td>
                              <span>{stateLabels[event.proof_state]}</span>
                              <p>
                                {event.currentness === "current"
                                  ? "Проверено при чтении"
                                  : "Текущее подтверждение недоступно"}
                              </p>
                            </td>
                            <td>
                              <details>
                                <summary>Детали записи ICF #{event.cash_flow_id}</summary>
                                <p>
                                  {event.provenance
                                    .map((p) => provenanceLabels[p] ?? p)
                                    .join("; ") || "Источник не подтверждён"}
                                </p>
                                <p>
                                  Gross: {rub(event.gross)}; налог: {rub(event.tax)}; комиссия:{" "}
                                  {rub(event.fee)}. Net уже учитывает включённые удержания.
                                </p>
                                {event.receipt_ids.map((id) => (
                                  <p key={id}>Подтверждение: {id}</p>
                                ))}
                                {event.reason_codes.map((code) => (
                                  <p key={code}>
                                    {payoutGap(code)} <small>({code})</small>
                                  </p>
                                ))}
                              </details>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : null}
                <details>
                  <summary>Версия проверки</summary>
                  <p>
                    {data.method} v{data.version}
                  </p>
                  <code style={{ overflowWrap: "anywhere" }}>
                    {data.dependency_fingerprint ??
                      "Проверка версий недоступна: нет полного журнала изменений записи. Повторите чтение для нового снимка."}
                  </code>
                </details>
              </section>
            </div>
          ) : null}
          {valid && (!request || fresh) ? (
            <InstrumentWhatIf
              key={`${JSON.stringify(scope)}:${request?.generation ?? 0}:${result.data?.epoch ?? 0}`}
              scope={scope}
            />
          ) : null}
        </>
      ) : null}
    </section>
  );
}
