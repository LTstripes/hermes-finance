import { Link } from "react-router";
import type {
  InstrumentAnalysis,
  InstrumentEndpoint,
  InstrumentEvent,
  InstrumentMetric,
} from "../api/sourceReturns";
import styles from "./UiV2BondSlice.module.css";

/** Display integer minor units exactly; reject already-unsafe legacy JSON numbers. */
export function money(value: number | string | null): string {
  if (value === null) return "Неизвестно";
  if ((typeof value === "number" && !Number.isSafeInteger(value)) || !/^-?\d+$/.test(String(value)))
    return "Недоступна точная сумма";
  const minor = BigInt(value);
  const abs = minor < 0n ? -minor : minor;
  return `${minor < 0n ? "−" : ""}${new Intl.NumberFormat("ru-RU").format(abs / 100n)},${String(abs % 100n).padStart(2, "0")} ₽`;
}
/** Decimal fraction to percentage display, HALF_UP at four places, without binary floats. */
export function rate(value: string | null): string {
  const match = value?.match(/^(-?)(\d+)(?:\.(\d+))?(?:[eE]([+-]?\d+))?$/);
  if (!match) return "Недоступен";
  const negative = match[1] === "-";
  const major = match[2];
  const fraction = match[3] ?? "";
  const exponent = Number(match[4] ?? "0");
  if (!Number.isSafeInteger(exponent) || Math.abs(exponent) > 1000) return "Недоступен";
  const places = fraction.length - exponent;
  const denominator = 10n ** BigInt(Math.max(0, places));
  const numerator = BigInt(major + fraction) * 1000000n * 10n ** BigInt(Math.max(0, -places));
  const scaled =
    numerator / denominator + ((numerator % denominator) * 2n >= denominator ? 1n : 0n);
  const tail = String(scaled % 10000n)
    .padStart(4, "0")
    .replace(/0+$/, "");
  return `${negative && scaled !== 0n ? "−" : ""}${new Intl.NumberFormat("ru-RU").format(scaled / 10000n)}${tail ? `,${tail}` : ""} %`;
}
export const observed = (value: string | null) => value ?? "Неизвестно";
export const statusLabel = (value: InstrumentMetric<unknown>["status"]) =>
  ({
    supported: "полные данные выбранного периода",
    provisional: "с допущениями",
    partial: "неполный компонент",
    unavailable: "недоступно",
  })[value];
const labels: Record<string, string> = {
  exact_t_invest_mapping_required:
    "Нужно принятое сопоставление T-Invest в справочнике. Автоматический поиск не запускается.",
  exact_instrument_required:
    "Нужно подтвердить точную карточку инструмента; новый ISIN не принимается автоматически.",
  quantity_absent_or_ambiguous:
    "На выбранную дату нет однозначного количества по этому счёту и ISIN.",
  quantity_unknown: "Количество не подтверждено. Выбери дату конца точной сохранённой выписки.",
  quantity_date_unproven: "Дата количества не подтверждена как конец отчётного дня.",
  overlapping_quantity_conflict:
    "Выписки расходятся в количестве. Нужно разобрать исходные доказательства.",
  endpoint_unsettled:
    "Расчёты на границе не завершены; это количество нельзя использовать для preview.",
  account_binding_conflict: "Привязки счёта противоречат друг другу. Проверь разбор источников.",
  actual_provider_identity_unproven:
    "Совпадение с actual — только кандидат. Идентичность выплаты провайдера не доказана.",
  actual_attribution_unresolved:
    "Есть неуточнённые фактические выплаты. Будущий доход не подтверждён.",
  duplicate_provider_identity:
    "Повторная или неоднозначная идентичность события исключена из future.",
  error: "Не удалось получить ответ провайдера. Запрос можно повторить явно.",
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
export function Reasons({ codes }: { codes: string[] }) {
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
export function References({ values }: { values: string[] }) {
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
function Events({
  events,
  coupons = false,
  caption,
  emptyPayoutLabel = "Купонных",
}: {
  events: InstrumentEvent[];
  coupons?: boolean;
  caption?: string;
  emptyPayoutLabel?: string;
}) {
  return events.length ? (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <caption>
          {caption ?? (coupons ? "Купоны по строкам источников" : "Сделки по строкам источников")}
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
        ? `${emptyPayoutLabel} строк в выбранном интервале нет. Полнота выплат указана ниже.`
        : "Сделок в выбранном интервале нет. Это не доказывает полноту истории."}
    </p>
  );
}
export function SourceInstrumentDetail({
  analysis,
  instrumentType = "bond",
  payoutPreviewHere = false,
}: {
  analysis: InstrumentAnalysis;
  instrumentType?: string | null;
  payoutPreviewHere?: boolean;
}) {
  const bond = instrumentType === "bond";
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
            {bond
              ? "Состав оценки / НКД не подтверждён. "
              : "Оценка зависит от допущений источника. "}
            Условные показатели не являются полным экономическим результатом.
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
        <strong>{bond ? "Известный компонент купонов:" : "Известный компонент дивидендов:"}</strong>{" "}
        {money((bond ? analysis.components.coupons : analysis.components.dividends).value)} ·{" "}
        {statusLabel((bond ? analysis.components.coupons : analysis.components.dividends).status)}.
        Он не заменяет полный результат.
      </p>
      <details>
        <summary>Известные компоненты, выплаты и расходы</summary>
        <Metric
          title="Известная часть результата · не полный P&L"
          metric={analysis.known_subtotal}
        />
        <div className={styles.grid}>
          {Object.entries(analysis.components).map(([name, metric]) => (
            <Metric
              key={name}
              title={
                (
                  {
                    buys: "Покупки",
                    sells: "Продажи",
                    coupons: "Купоны",
                    dividends: "Дивиденды",
                    redemption: "Погашение",
                    fees: "Отдельные комиссии",
                    taxes: "Отдельные налоги",
                    valuation_and_trades: "Оценка и сделки, включая встроенные расходы",
                  } as Record<string, string>
                )[name]
              }
              metric={metric}
            />
          ))}
        </div>
      </details>
      <Events
        events={analysis.events.filter((event) => event.kind === "BUY" || event.kind === "SELL")}
      />
      <Events
        events={analysis.events.filter((event) => event.kind === (bond ? "COUPON" : "DIVIDEND"))}
        coupons
        caption={bond ? "Купоны по строкам источников" : "Дивиденды по строкам источников"}
        emptyPayoutLabel={bond ? "Купонных" : "Дивидендных"}
      />
      <p className={styles.note}>
        {payoutPreviewHere ? (
          "Предварительные выплаты запрашиваются ниже отдельным действием."
        ) : (
          <>
            Прогноз выплат смотрите отдельно в <Link to="/v2/income">«Доход и планы»</Link>.
          </>
        )}{" "}
        Будущие выплаты не включены в фактический доход.
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
              <br />
              Манифест: <code>{source.manifest_digest}</code>
              <br />
              Связи: <code>{source.link_dependencies}</code>
              <br />
              Классификации: <code>{source.classification_dependencies.join(", ") || "нет"}</code>
            </li>
          ))}
        </ul>
        <Link to="/v2/data/source-intake">Открыть сохранённые источники</Link>
      </details>
    </>
  );
}
