import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router";
import { formatApiError } from "../api/client";
import {
  getSourceInstrumentReturns,
  type InstrumentAnalysis,
  type InstrumentEndpoint,
  type InstrumentEvent,
  type InstrumentMetric,
  type SourceInstrumentReturns,
} from "../api/sourceReturns";
import styles from "./UiV2BondSlice.module.css";
import { UiV2Panel } from "./UiV2Panel";
import { UiV2Loading, UiV2Notice } from "./UiV2StateBlocks";

const money = (value: number | null) =>
  value === null
    ? "Неизвестно"
    : `${new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 2 }).format(value / 100)} ₽`;
const rate = (value: string | null) =>
  value === null
    ? "Недоступен"
    : `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 4 }).format(Number(value) * 100)} %`;
const observed = (value: string | null) => value ?? "Неизвестно";
const statusLabel = (value: InstrumentMetric<unknown>["status"]) =>
  ({
    supported: "полные данные выбранного периода",
    provisional: "с допущениями",
    partial: "неполный компонент",
    unavailable: "недоступно",
  })[value];
const labels: Record<string, string> = {
  bond_valuation_basis_unknown: "Нужна dirty-оценка или clean-оценка с НКД на обеих границах.",
  face_value_assumed: "Номинал сделки принят с допущением; нужен датированный источник.",
  income_assumed: "Классификация выплаты основана на правиле по умолчанию.",
  missing_endpoint: "Нет подтверждённой стоимости или количества на границе периода.",
  missing_quantity: "Нет количества на границе; отсутствие позиции не означает ноль.",
  instrument_type_unknown: "Тип инструмента не подтверждён.",
  trade_nkd_basis_unknown: "Не подтверждено, входит ли НКД в сумму сделки.",
  trade_nkd_basis_conflict: "Источники противоречат друг другу о составе НКД сделки.",
  trade_missing_settlement: "Нужна дата фактического денежного или депозитарного расчёта.",
  trade_identity_unresolved: "Не установлена полная нативная идентичность сделки.",
  trade_components_missing: "Не хватает составляющих суммы сделки.",
  unmatched_trade_money: "Не установлена принадлежность денежной строки сделке.",
  trade_money_cash_conflict: "Сумма сделки расходится с денежными строками.",
  quantity_events_incomplete: "Не все движения количества подтверждены.",
  quantity_reconciliation_mismatch: "Количество не сверено с учтёнными движениями.",
  source_period_inferred: "Период выписки выведен из операций; даты остатков не подтверждены.",
  incomplete_source_coverage: "Источники не покрывают весь выбранный период.",
  payout_link_unresolved_no_match: "Нужно точное сопоставление выплаты с инструментом.",
  payout_link_stale: "Сохранённое сопоставление выплаты требует повторной проверки.",
  unattributed_income: "Есть выплата без подтверждённого инструмента.",
  unallocated_instrument_cost: "Не установлена принадлежность расхода инструменту.",
  unrecognized_money: "Есть нераспознанная денежная операция.",
  repo_trade_unsupported: "Экономика REPO не поддерживается этим расчётом.",
  redemption_amortization_unsupported: "Не подтверждена экономика погашения или амортизации.",
  "4_Transfers_unsupported": "Есть неразобранные переводы или аннулирование бумаг.",
  "5_UFSR_unsupported": "Служебная секция источника не распознана полностью.",
  unparsed_source_rows: "Не все структуры выписки распознаны.",
  non_positive_dietz_denominator: "Нет положительной базы для Modified Dietz.",
};
function Reasons({ codes }: { codes: string[] }) {
  const unique = [...new Set(codes)];
  return unique.length ? (
    <div>
      <ul className={styles.reasons}>
        {unique.map((code) => (
          <li key={code}>{labels[code] ?? "Нужно проверить источник операции."}</li>
        ))}
      </ul>
      <details className={styles.note}>
        <summary>Коды причин</summary>
        <code>{unique.join(", ")}</code>
      </details>
    </div>
  ) : null;
}
function References({ values }: { values: string[] }) {
  return values.length ? (
    <details>
      <summary>Строки источников ({values.length})</summary>
      <ul className={styles.references}>
        {values.map((value) => (
          <li key={value}>
            <code>{value}</code>
          </li>
        ))}
      </ul>
    </details>
  ) : (
    <span>Ссылка не предоставлена</span>
  );
}
function Endpoint({ title, value }: { title: string; value: InstrumentEndpoint }) {
  return (
    <div className={styles.card}>
      <h4>
        {title} · {value.date}
      </h4>
      <dl>
        <dt>Количество</dt>
        <dd>{observed(value.quantity)}</dd>
        <dt>Стоимость по выписке</dt>
        <dd>{money(value.reported_value_kopecks)}</dd>
        <dt>НКД на границе</dt>
        <dd>{money(value.accrued_interest_kopecks)}</dd>
        <dt>Состав оценки</dt>
        <dd>
          {value.valuation_basis === "reported_unknown"
            ? "Состав стоимости (clean/dirty) не подтверждён"
            : value.valuation_basis}
        </dd>
      </dl>
      <References values={value.source_references} />
    </div>
  );
}
function Metric(
  props: { title: string } & (
    | { percent: true; metric: InstrumentMetric<string> }
    | { percent?: false; metric: InstrumentMetric<number> }
  ),
) {
  const { title, metric } = props;
  return (
    <div className={styles.card}>
      <h4>{title}</h4>
      <p className={styles.value}>
        {props.percent
          ? rate(props.metric.value)
          : props.metric.value === null
            ? "Недоступен"
            : money(props.metric.value)}
      </p>
      <p className={styles.note}>{statusLabel(metric.status)}</p>
      <Reasons codes={[...metric.reason_codes, ...metric.assumptions]} />
    </div>
  );
}
function Events({ events, coupons = false }: { events: InstrumentEvent[]; coupons?: boolean }) {
  return events.length ? (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <caption>
          {coupons ? "Купоны по строкам источников" : "Сделки по строкам источников"}
        </caption>
        <thead>
          <tr>
            <th>Дата / состояние</th>
            {coupons ? (
              <>
                <th>Зачислено (net)</th>
                <th>Gross / налог</th>
                <th>Сопоставление</th>
              </>
            ) : (
              <>
                <th>Операция / количество</th>
                <th>Цена / единица</th>
                <th>Сумма по источнику</th>
                <th>НКД / комиссия</th>
              </>
            )}
            <th>Источники и ограничения</th>
          </tr>
        </thead>
        <tbody>
          {events.map((event) => (
            <tr key={event.event_key}>
              <td>
                {coupons ? observed(event.event_date) : observed(event.trade_time)}
                {!coupons && (
                  <>
                    <br />
                    Деньги: {observed(event.cash_settlement_date)}
                    <br />
                    Бумаги: {observed(event.depository_settlement_date)}
                  </>
                )}
                <p>{event.counted ? "Учтено в доступных компонентах" : "Не учтено в расчёте"}</p>
                {!event.current && <strong>Сопоставление неактуально</strong>}
              </td>
              {coupons ? (
                <>
                  <td>{money(event.net_payout_kopecks)}</td>
                  <td>
                    {money(event.gross_payout_kopecks)} / {money(event.withheld_tax_kopecks)}
                  </td>
                  <td>
                    {event.persisted_link_status === "linked" &&
                    event.current &&
                    event.effective_isin === event.isin
                      ? "Сохранённая связь с инструментом"
                      : `Основание: ${event.attribution_basis ?? "неизвестно"}`}
                    <br />
                    Классификация:{" "}
                    {event.classification_status === "confirmed"
                      ? "подтверждена"
                      : event.classification_status === "assumed"
                        ? "правило по умолчанию"
                        : "неизвестна"}
                  </td>
                </>
              ) : (
                <>
                  <td>
                    {event.kind === "BUY" ? "Покупка" : "Продажа"}
                    <br />
                    {observed(event.quantity_delta)}
                  </td>
                  <td>
                    {observed(event.unit_price)}
                    <br />
                    {event.price_unit === "PERCENT_OF_FACE"
                      ? "% от номинала"
                      : event.price_unit === "RUB_PER_UNIT"
                        ? "₽ за бумагу"
                        : "Единица не подтверждена"}
                  </td>
                  <td>
                    {money(event.native_trade_amount_kopecks)}
                    <br />
                    <small>
                      Состав:{" "}
                      {event.native_total_basis === "includes_paid_nkd"
                        ? "НКД входит в сумму"
                        : event.native_total_basis === "excludes_paid_nkd"
                          ? "НКД отдельно от суммы"
                          : "не подтверждён"}
                    </small>
                  </td>
                  <td>
                    {money(event.accrued_interest_kopecks)} / {money(event.commission_kopecks)}
                    <br />
                    <small>
                      Номинал: {observed(event.face_value)} · дата:{" "}
                      {observed(event.face_value_date)}
                    </small>
                  </td>
                </>
              )}
              <td>
                <References values={event.source_references} />
                <Reasons codes={[...event.reason_codes, ...event.assumptions]} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  ) : (
    <p>
      {coupons
        ? "Купонных строк в выбранном интервале нет. Полнота выплат указана ниже."
        : "Сделок в выбранном интервале нет. Это не доказывает полноту истории."}
    </p>
  );
}
function BondDetail({ analysis }: { analysis: InstrumentAnalysis }) {
  const estimate = analysis.statement_estimate;
  const hasEstimate = estimate.pnl.value !== null || estimate.modified_dietz.value !== null;
  return (
    <>
      <p>
        Интервал: ({analysis.opening_date}, {analysis.closing_date}].
      </p>
      <div className={styles.grid}>
        <Endpoint title="Начало" value={analysis.opening} />
        <Endpoint title="Конец" value={analysis.closing} />
      </div>
      <h4>Полный экономический результат</h4>
      <div className={styles.grid}>
        <Metric title="Полный P&L, ₽" metric={analysis.pnl} />
        <Metric
          title="Modified Dietz · приблизительно, за период"
          metric={analysis.modified_dietz}
          percent
        />
      </div>
      {hasEstimate ? (
        <section className={styles.estimate} aria-label="Условная оценка по выписке">
          <h4>Условная доходность по стоимости из выписки</h4>
          <p>
            Состав оценки / НКД не подтверждён. Условные показатели не являются полным экономическим
            результатом.
          </p>
          <div className={styles.grid}>
            <Metric title="Условный результат, ₽" metric={estimate.pnl} />
            <Metric
              title="Условный Modified Dietz · приблизительно, за период"
              metric={estimate.modified_dietz}
              percent
            />
          </div>
          <Reasons codes={estimate.assumptions} />
        </section>
      ) : (
        <details>
          <summary>Условная оценка недоступна</summary>
          <Reasons
            codes={[...estimate.pnl.reason_codes, ...estimate.modified_dietz.reason_codes]}
          />
        </details>
      )}
      <p>
        <strong>Известный компонент купонов:</strong> {money(analysis.components.coupons.value)} ·{" "}
        {statusLabel(analysis.components.coupons.status)}. Он не заменяет полный результат.
      </p>
      <Events
        events={analysis.events.filter((event) => event.kind === "BUY" || event.kind === "SELL")}
      />
      <Events events={analysis.events.filter((event) => event.kind === "COUPON")} coupons />
      <p className={styles.note}>
        Прогноз выплат смотрите отдельно в <Link to="/v2/income">«Доход и планы»</Link>; будущие
        выплаты не включены в фактические купоны.
      </p>
      <details>
        <summary>Полнота и происхождение</summary>
        <ul>
          {Object.entries(analysis.coverage).map(([name, value]) => (
            <li key={name}>
              {name}: {value.complete ? "полно" : "неполно"}
              <Reasons codes={value.reason_codes} />
            </li>
          ))}
        </ul>
        <p>
          История источников: {analysis.history_start} — {analysis.history_end}. История с
          приобретения:{" "}
          {analysis.history_complete_since_acquisition ? "подтверждена" : "не подтверждена"}.
        </p>
        <ul className={styles.references}>
          {analysis.source_references.map((source) => (
            <li key={source.intake_id}>
              Выписка #{source.intake_id} · ревизия {source.journal_revision} ·{" "}
              {source.parser_version}
              <br />
              <code>{source.original_digest}</code>
            </li>
          ))}
        </ul>
        <Link to="/v2/data/source-intake">Открыть сохранённые источники</Link>
      </details>
    </>
  );
}

/** Presentation of server v2 facts only: no return arithmetic, writers or evidence promotion. */
export function UiV2BondSlice({
  account,
  sources,
}: {
  account: string;
  sources: SourceInstrumentReturns;
}) {
  const [params, setParams] = useSearchParams();
  const ownContext = !params.get("source_account") || params.get("source_account") === account;
  const period = ownContext ? (params.get("bond_period") ?? "history") : "history";
  const chosenIsin = ownContext ? (params.get("bond_isin") ?? "") : "";
  function select(key: "bond_period" | "bond_isin", value: string) {
    setParams((previous) => {
      const next = new URLSearchParams(previous);
      next.set("source_account", account);
      if (value === "history") next.delete(key);
      else next.set(key, value);
      return next;
    });
  }
  const sourceBonds = sources.instruments.filter((row) => row.instrument_type === "bond");
  const months = [...new Set(sourceBonds.flatMap((row) => row.months.map((value) => value.month)))]
    .sort()
    .reverse();
  const selectedMonth = sourceBonds
    .flatMap((row) => row.months)
    .find((row) => row.month === period)?.analysis;
  const selected = useQuery({
    queryKey: ["source-returns", "bond-period", account, period],
    queryFn: ({ signal }) =>
      getSourceInstrumentReturns(account, signal, {
        opening_date: selectedMonth?.opening_date ?? "",
        closing_date: selectedMonth?.closing_date ?? "",
      }),
    enabled: period !== "history" && !!selectedMonth,
  });
  const data = period === "history" ? sources : selected.data;
  const bonds = data?.instruments.filter((row) => row.instrument_type === "bond") ?? [];
  const instrument = bonds.find((row) => row.isin === chosenIsin) ?? bonds[0];
  const scopeMismatch =
    data &&
    (data.source_account !== account ||
      data.native_source_account !== sources.native_source_account);
  return (
    <UiV2Panel
      eyebrow="Из сохранённых источников"
      id="bond-slice"
      testIdPrefix="returns"
      title="Облигации: позиции, сделки и купоны"
      wide
    >
      <p>
        Счёт источника:{" "}
        <strong>{sources.native_source_account ?? "нативный счёт не установлен"}</strong> · выбран:{" "}
        {account}.
      </p>
      <p className={styles.note}>
        Только чтение. Данные выписок не являются принятой финансовой позицией и не дают готовности
        к Close.
      </p>
      {sourceBonds.length === 0 ? (
        <p>В сохранённых источниках этого счёта нет облигаций с подтверждённым типом.</p>
      ) : (
        <>
          <label>
            Период облигаций{" "}
            <select
              aria-label="Период облигаций"
              value={period}
              onChange={(event) => select("bond_period", event.target.value)}
            >
              <option value="history">Доступная история источников</option>
              {months.map((value) => (
                <option key={value} value={value}>
                  {value.slice(0, 7)}
                </option>
              ))}
            </select>
          </label>
          {scopeMismatch ? (
            <UiV2Notice title="Счёт ответа не совпадает с выбранным">
              Обновите чтение источников.
            </UiV2Notice>
          ) : period !== "history" && !selectedMonth ? (
            <UiV2Notice title="Период больше не доступен в источниках">
              Выберите другой период.
            </UiV2Notice>
          ) : period !== "history" && selected.isPending ? (
            <UiV2Loading label="Читаем период облигаций…" />
          ) : selected.isError && period !== "history" ? (
            <UiV2Notice title="Не удалось прочитать облигации">
              {formatApiError(selected.error)}
              <button type="button" onClick={() => void selected.refetch()}>
                Повторить чтение облигаций
              </button>
            </UiV2Notice>
          ) : (
            <>
              <div className={styles.tableWrap}>
                <table className={styles.table}>
                  <caption>Облигации выбранного счёта и периода</caption>
                  <thead>
                    <tr>
                      <th>Облигация</th>
                      <th>Количество на конец</th>
                      <th>Стоимость по выписке</th>
                      <th>Дата оценки</th>
                      <th>Известные купоны</th>
                    </tr>
                  </thead>
                  <tbody>
                    {bonds.map((row) => (
                      <tr key={row.isin}>
                        <th>
                          <button
                            type="button"
                            aria-pressed={instrument?.isin === row.isin}
                            onClick={() => select("bond_isin", row.isin)}
                          >
                            {row.source_name ?? row.isin}
                          </button>
                          <br />
                          <small>{row.isin}</small>
                        </th>
                        <td>{observed(row.analysis.closing.quantity)}</td>
                        <td>{money(row.analysis.closing.reported_value_kopecks)}</td>
                        <td>
                          {row.analysis.closing.reported_value_kopecks === null
                            ? `Нет оценки на ${row.analysis.closing.date}`
                            : row.analysis.closing.date}
                        </td>
                        <td>
                          {money(row.analysis.components.coupons.value)} ·{" "}
                          {statusLabel(row.analysis.components.coupons.status)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className={styles.note}>
                Стоимость показана как reported value из выписки. Подтверждённый состав clean/dirty
                указан в деталях.
              </p>
              {instrument && (
                <section aria-label={`Детали облигации ${instrument.isin}`}>
                  <h3>
                    {instrument.source_name ?? instrument.isin} · {instrument.isin}
                  </h3>
                  <BondDetail analysis={instrument.analysis} />
                </section>
              )}
              {!!data?.unresolved_events.length && (
                <details>
                  <summary>
                    Нераспределённые события счёта в истории источников:{" "}
                    {data.unresolved_events.length}
                  </summary>
                  <p>Эти события не отнесены автоматически к выбранной облигации.</p>
                  <ul>
                    {data.unresolved_events.map((event) => (
                      <li key={event.event_key}>
                        {observed(event.event_date)} · {event.kind}
                        <Reasons codes={event.reason_codes} />
                        <References values={event.source_references} />
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </>
          )}
        </>
      )}
    </UiV2Panel>
  );
}
