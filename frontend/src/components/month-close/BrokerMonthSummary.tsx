import type { BrokerMonthPreview } from "../../api/brokerMonths";
import type { MyBrokerDocument } from "../../api/mybrokerImport";
import { formatDate, formatMoney } from "../../lib/format";
import { normalizeMoneyInput, sumMoneyAmounts } from "../../lib/money";
import { brokerSourceTitle } from "../../lib/ownerCopy";
import styles from "./BrokerMonthReview.module.css";

type Side = "beginning" | "ending";
export function sourceCash(document: MyBrokerDocument, side: Side) {
  return document.rub_money?.length === 1
    ? ((side === "beginning"
        ? document.rub_money[0].beginning_amount
        : document.rub_money[0].ending_amount) ?? null)
    : null;
}
export function sourceTotal(document: MyBrokerDocument, side: Side, includeCash = true) {
  if (!document.positions.length) return null;
  const values = document.positions.map((p) =>
    side === "beginning" ? p.beginning_value : p.ending_value,
  );
  if (includeCash) values.push(sourceCash(document, side));
  return values.length &&
    values.every((v): v is string => typeof v === "string" && normalizeMoneyInput(v) !== null)
    ? sumMoneyAmounts(values)
    : null;
}
const amount = (value: string | null) =>
  value === null || normalizeMoneyInput(value) === null ? "Неизвестно" : formatMoney(value);

const COPY: Record<string, { title: string; action: string }> = {
  instrument_currency_unproven: {
    title: "Валюта инструмента не подтверждена",
    action:
      "Подтверди валюту в каталоге по доказательству и повтори Preview. RUB автоматически не назначается.",
  },
  instrument_type_unproven: {
    title: "Тип инструмента не подтверждён",
    action: "Уточни тип в каталоге по исходным данным и повтори Preview.",
  },
  source_month_range_mismatch: {
    title: "Период источника не совпадает с месяцем",
    action: "Открой соответствующий DRAFT или выбери полный XML текущего месяца и повтори Preview.",
  },
  reporting_month_closed: {
    title: "Месяц закрыт",
    action: "В закрытом месяце доступно чтение; сохранение source-DRAFT недоступно.",
  },
  account_mapping_conflict: {
    title: "Привязка счёта противоречит источнику",
    action: "Проверь точные aliases и целевой счёт, затем получи свежий Preview.",
  },
  source_account_conflict: {
    title: "Исходные aliases относятся к разным счетам",
    action: "Разреши противоречие привязок; не выбирай счёт по похожему имени.",
  },
  broker_month_preview_stale: {
    title: "Preview устарел",
    action: "Повтори Preview после изменения источников или справочников и заново проверь сводку.",
  },
  source_projection_changed: {
    title: "Принятые доказательства изменились",
    action: "Обнови состояние и повтори Preview; прежняя сводка больше не подтверждает источник.",
  },
  source_economic_conflict: {
    title: "Источник противоречит принятым фактам",
    action: "Сверь оригиналы и принятые данные. Получи свежий Preview после разрешения конфликта.",
  },
  overlapping_endpoint_conflict: {
    title: "Пересекающиеся источники противоречат друг другу",
    action: "Сверь пересекающиеся оригиналы и повтори Preview после разрешения конфликта.",
  },
  settlement_cash_missing_or_ambiguous: {
    title: "Денежная строка расчётов отсутствует или неоднозначна",
    action: "Связь расчётов проверяется отдельно в Money; сводка её не подтверждает.",
  },
};
const ACTIONS: Record<string, string> = {
  money_semantics_unsupported:
    "Разбери подтверждённые денежные строки отдельно в Money; это сохранение их не классифицирует.",
  commission_basis_unresolved:
    "Подтверди доказательства комиссии отдельно; общая сводка не заменяет это решение.",
  settlement_principal_unresolved: "Сверь исходные расчёты и их доказательства отдельно в Money.",
  unparsed_source_rows:
    "Открой полный состав источника и проверь неразобранные строки; они остаются нерешёнными.",
  "4_Transfers_unsupported":
    "Сверь переводы по источнику отдельно; это сохранение их не классифицирует.",
  "5_UFSR_unsupported":
    "Проверь неподдержанные данные в полном составе источника; они остаются нерешёнными.",
};

function Diagnostics({ codes, title }: { codes: string[]; title: string }) {
  if (!codes.length) return null;
  return (
    <div className={styles.exceptions}>
      <h4>{title}</h4>
      <ul>
        {[...new Set(codes)].map((code) => {
          const copy = Object.hasOwn(COPY, code) ? COPY[code] : null;
          const knownTitle = copy?.title ?? brokerSourceTitle(code);
          return (
            <li key={code}>
              <strong>{knownTitle ?? "Неизвестная причина — требуется разбор"}</strong>.{" "}
              {copy?.action ??
                (Object.hasOwn(ACTIONS, code) ? ACTIONS[code] : null) ??
                "Открой диагностические причины и сверь доказательства; причина остаётся нерешённой."}
              {!knownTitle ? (
                <>
                  {" "}
                  Код: <code>{code}</code>.
                </>
              ) : null}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export function BrokerMonthSummary({
  preview,
  filename,
}: {
  preview: BrokerMonthPreview;
  filename: string;
}) {
  const { document, identity } = preview;
  const account = preview.account_aliases.find(
    (a) => a.hermes_id === preview.account_id,
  )?.target_name;
  const gaps = identity?.evidence_gaps ?? [];
  return (
    <section aria-label="Сводка исходного DRAFT" className={styles.summary}>
      <h3>Сводка исходного DRAFT</h3>
      <p role="status">
        <strong>
          {!preview.can_apply
            ? "Сохранение source-DRAFT недоступно"
            : preview.bookkeeping_ready
              ? "Можно сохранить source-DRAFT"
              : "Можно сохранить неполный source-DRAFT"}
          .
        </strong>{" "}
        {!preview.can_apply
          ? "Разреши конфликт и получи свежий Preview."
          : !preview.bookkeeping_ready
            ? "Неполнота останется в черновике; это не готовность к Close."
            : "Готовность брокерского компонента к общей проверке не означает закрытие месяца."}
      </p>
      <Diagnostics codes={preview.conflicts} title="Конфликты источника или идентичности" />
      <Diagnostics
        codes={[...preview.exceptions, ...gaps.map((g) => g.code)]}
        title="Неполнота и недостающие доказательства"
      />
      {!preview.bookkeeping_ready &&
      !preview.exceptions.length &&
      !preview.conflicts.length &&
      !gaps.length ? (
        <p>Причина неполноты не указана в Preview — неизвестно.</p>
      ) : null}
      <p>
        <strong>
          {account ?? "Имя счёта неизвестно"} (#{preview.account_id})
        </strong>{" "}
        · месяц #{preview.reporting_month_id} · {formatDate(document.covered_from)} —{" "}
        {formatDate(document.covered_to)} · снимок {formatDate(preview.ending_date)}.
      </p>
      <p className={styles.sourceName}>Оригинал: {filename}.</p>
      <dl className={styles.metrics}>
        <div>
          <dt>Оценка бумаг по XML</dt>
          <dd>
            {amount(sourceTotal(document, "beginning", false))} →{" "}
            {amount(sourceTotal(document, "ending", false))}
          </dd>
        </div>
        <div>
          <dt>Отдельный RUB cash</dt>
          <dd>
            {amount(sourceCash(document, "beginning"))} → {amount(sourceCash(document, "ending"))}
          </dd>
        </div>
        <div>
          <dt>Общая оценка источника, включая cash</dt>
          <dd>
            {amount(sourceTotal(document, "beginning"))} → {amount(sourceTotal(document, "ending"))}
          </dd>
        </div>
      </dl>
      <p>
        Начальная оценка — на {formatDate(preview.opening_date)}, конечная — на{" "}
        {formatDate(preview.ending_date)}. Это оценки брокера, не точная экономическая доходность.
      </p>
      <p>
        Aliases счёта: существующих{" "}
        {preview.account_aliases.filter((a) => a.action === "reuse").length}; новых решений{" "}
        {preview.account_bindings.length}.
      </p>
      {identity ? (
        <p>
          Инструменты каталога: переиспользуются{" "}
          {identity.instruments.filter((i) => i.action === "reuse").length}; новых решений{" "}
          {identity.instruments.filter((i) => i.action === "stage_create").length}. Привязки
          инструментов: существующих{" "}
          {identity.instruments.filter((i) => i.mapping_action === "reuse").length}; новых в
          source-DRAFT{" "}
          {identity.instruments.filter((i) => i.mapping_action === "stage_create").length}.
        </p>
      ) : null}
      {gaps.length ? (
        <p>
          Инструменты с недостающими доказательствами:{" "}
          {gaps.map((g) => `${g.isin} (${g.code})`).join("; ")}.
        </p>
      ) : null}
      {identity ? (
        <details>
          <summary>Инструменты и контроль количества</summary>
          <ul>
            {identity.instruments.map((instrument) => (
              <li key={instrument.isin}>
                {instrument.isin} · {instrument.instrument_type ?? "Тип неизвестен"} ·{" "}
                {instrument.currency ?? "Валюта неизвестна"} ·{" "}
                {instrument.action === "reuse"
                  ? `Инструмент каталога #${instrument.hermes_id} переиспользуется`
                  : "Планируется новый инструмент по доказательствам Preview"}{" "}
                ·{" "}
                {instrument.mapping_action === "reuse"
                  ? "Существующая привязка"
                  : "Новая привязка в source-DRAFT"}
                .
                {instrument.evidence_gaps.length
                  ? ` Недостающие доказательства: ${instrument.evidence_gaps.join(", ")}.`
                  : ""}
              </li>
            ))}
          </ul>
          {preview.quantity_controls ? (
            <ul>
              {preview.quantity_controls.map((row) => (
                <li key={row.isin}>
                  {row.isin}: разница количества {row.difference ?? "Неизвестно"}.
                </li>
              ))}
            </ul>
          ) : (
            <p>Контроль количества не указан — неизвестно.</p>
          )}
        </details>
      ) : (
        <p>Решения по инструментам в Preview не указаны — неизвестно.</p>
      )}
      <p>
        Покрытие счёта, себестоимость, налоги и НКД не подтверждены этой сводкой. Денежные связи,
        комиссии и НКД проверяются отдельно в Money; Close и точные XIRR/TWRR требуют своих
        доказательств.
      </p>
      <details>
        <summary>Технические причины Preview</summary>
        <ul>
          {[
            ...new Set([...preview.conflicts, ...preview.exceptions, ...gaps.map((g) => g.code)]),
          ].map((code) => (
            <li key={code}>
              <code>{code}</code>
            </li>
          ))}
        </ul>
      </details>
    </section>
  );
}
