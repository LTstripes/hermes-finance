import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router";
import { ApiClientError, formatApiError } from "../api/client";
import {
  getSourceQuantityBases,
  previewSourcePayouts,
  type SourcePayoutPreview,
} from "../api/sourcePayoutPreview";
import { Button } from "../components/ui";
import { money, Reasons, References } from "./SourceInstrumentDetail";
import styles from "./UiV2BondSlice.module.css";

const rowLabels: Record<SourcePayoutPreview["rows"][number]["status"], string> = {
  future: "Будущая",
  possible_paid: "Возможно уже выплачено",
  past_unreconciled: "Прошлая, не сверена",
  outside_horizon: "Вне горизонта",
  reconciliation_required: "Нужна сверка",
  tentative: "Предварительная",
  ambiguous_identity: "Неоднозначная идентичность",
  unsupported: "Не поддерживается",
  unavailable: "Недоступна",
  error: "Ошибка провайдера",
};

function ScheduleRows({ title, rows }: { title: string; rows: SourcePayoutPreview["rows"] }) {
  return (
    <section aria-label={title}>
      <h4>{title}</h4>
      {!rows.length ? (
        <p>Таких кандидатов в ответе нет. Это не подтверждает полноту выплат.</p>
      ) : (
        <div className={styles.tableWrap}>
          <table className={styles.table} aria-label={title}>
            <thead>
              <tr>
                <th>Дата / вид</th>
                <th>Объявленная сумма · не личный net</th>
                <th>Состояние / происхождение</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                // biome-ignore lint/suspicious/noArrayIndexKey: Ambiguous provider identities remain distinct read-only occurrences.
                <tr key={`${row.identity_key}:${index}`}>
                  <td>
                    {row.payment_date ?? "Дата неизвестна"} · {row.event_kind}
                  </td>
                  <td>
                    {row.currency === "RUB"
                      ? money(row.announced_amount_kopecks)
                      : "Сумма в RUB недоступна"}
                    <br />
                    Личный налог неизвестен
                  </td>
                  <td>
                    {rowLabels[row.status]} · {row.status}
                    <details>
                      <summary>Идентичность и сопоставление</summary>
                      <p>
                        {row.identity_key ?? "Идентичность не подтверждена"} ·{" "}
                        {row.source_method ?? "Метод не указан"}
                      </p>
                      <p>Ключи actual: {row.actual_event_keys.join(", ") || "нет"}</p>
                      <p>
                        Объявлено за бумагу: {row.per_unit_amount ?? "неизвестно"}{" "}
                        {row.currency ?? ""} · {row.provider_status ?? "статус не указан"}
                      </p>
                    </details>
                    <Reasons codes={row.reason_codes} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

/** Ephemeral, explicit provider preview; no automatic request, acceptance or financial writer. */
export function MonthInstrumentPayouts({
  account,
  nativeAccount,
  isin,
  closingDate,
  sourceReferences,
}: {
  account: string;
  nativeAccount: string;
  isin: string;
  closingDate: string;
  sourceReferences: SourcePayoutPreview["source_references"];
}) {
  const client = useQueryClient();
  const [params, setParams] = useSearchParams();
  const bases = useQuery({
    queryKey: ["source-returns", "quantity-bases", account, isin, closingDate],
    queryFn: async ({ signal }) => {
      const value = await getSourceQuantityBases(account, isin, closingDate, signal);
      if (
        value.source_account !== account ||
        value.native_source_account !== nativeAccount ||
        value.isin !== isin ||
        value.on_or_before !== closingDate ||
        value.authority !== "provisional" ||
        value.financial_authority !== "none" ||
        !Array.isArray(value.bases) ||
        value.bases.some((basis) => basis.as_of > closingDate)
      )
        throw new Error("Счёт, ISIN или граница сохранённого количества не подтверждены.");
      return value;
    },
    refetchOnMount: "always",
    refetchOnWindowFocus: true,
  });
  const dates = params.getAll("payout_as_of");
  const asOf = dates.length === 0 ? closingDate : dates.length === 1 ? dates[0] : "";
  const parsedDate = Date.parse(`${asOf}T00:00:00Z`);
  const validDate =
    /^\d{4}-\d{2}-\d{2}$/.test(asOf) &&
    !Number.isNaN(parsedDate) &&
    new Date(parsedDate).toISOString().slice(0, 10) === asOf;
  const selectedBasis = bases.data?.bases.find((basis) => basis.as_of === asOf);
  const [result, setResult] = useState<SourcePayoutPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const epoch = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const inFlight = useRef(false);
  const retire = useCallback(() => {
    epoch.current++;
    controller.current?.abort();
    inFlight.current = false;
    setResult(null);
    setError(null);
    setBusy(false);
  }, []);
  // biome-ignore lint/correctness/useExhaustiveDependencies: Back/Forward date identity retires the previous explicit request.
  useLayoutEffect(() => {
    retire();
  }, [asOf, retire]);
  useEffect(() => {
    const unsubscribe = client.getQueryCache().subscribe((event) => {
      if (
        !event.query ||
        ![
          "source-intakes",
          "source-returns",
          "instruments",
          "broker-identity-mappings",
          "accounts",
          "months",
        ].includes(String(event.query.queryKey[0]))
      )
        return;
      if (
        event.type === "removed" ||
        (event.type === "updated" &&
          (event.action.type === "invalidate" ||
            (event.action.type === "success" &&
              (event.action.manual || event.query.state.dataUpdateCount > 1))))
      )
        retire();
    });
    return () => {
      unsubscribe();
      epoch.current++;
      controller.current?.abort();
    };
  }, [client, retire]);

  async function run() {
    if (inFlight.current || !validDate) return;
    retire();
    const version = epoch.current;
    const abort = new AbortController();
    controller.current = abort;
    inFlight.current = true;
    setBusy(true);
    const current = () => version === epoch.current && !abort.signal.aborted;
    try {
      const value = await previewSourcePayouts(
        { source_account: account, isin, as_of: asOf },
        abort.signal,
      );
      if (!current()) return;
      const provenance = (refs: typeof sourceReferences) =>
        JSON.stringify(
          [...refs]
            .sort((left, right) => left.intake_id - right.intake_id)
            .map((ref) => [
              ref.intake_id,
              ref.journal_revision,
              ref.parser_version,
              ref.original_digest,
              ref.manifest_digest,
              [...ref.classification_dependencies].sort(),
              ref.link_dependencies,
            ]),
        );
      if (provenance(value.source_references) !== provenance(sourceReferences))
        throw new Error(
          "Источники результата и preview изменились. Обнови чтение инструментов и явно запроси preview заново.",
        );
      if (
        value.source_account !== account ||
        value.native_source_account !== nativeAccount ||
        value.isin !== isin ||
        value.as_of !== asOf ||
        value.authority !== "provisional" ||
        value.financial_authority !== "none" ||
        value.quantity_authority !== "source_observed" ||
        value.provider !== "t_invest" ||
        !value.dependency_fingerprint ||
        value.rows.some((row) => row.countable_future && row.status !== "future")
      )
        throw new Error(
          "Счёт, ISIN, дата или состояние ответа выплат не подтверждены. Обнови чтение источника.",
        );
      setResult(value);
    } catch (e) {
      if (current())
        setError(
          e instanceof ApiClientError && e.status === 409
            ? "Источник или сопоставления изменились. Обнови чтение инструментов и явно запроси новый preview."
            : formatApiError(e),
        );
    } finally {
      if (current()) {
        inFlight.current = false;
        setBusy(false);
      }
    }
  }

  return (
    <section
      id="month-payout-preview"
      className={styles.preview}
      aria-label={`Предварительные выплаты ${isin}`}
    >
      <h3>Предварительные выплаты · T-Invest</h3>
      <details>
        <summary>О предварительных выплатах</summary>
        <p className={styles.note}>
          Только по явному запросу. Сохранённое количество — сценарий, а не доказательство права на
          будущую выплату. Прогноз не включается в P&amp;L или фактический доход.
        </p>
      </details>
      {bases.isFetching || bases.isPending ? (
        <p>Читаем даты количества из сохранённых выписок…</p>
      ) : bases.isError ? (
        <p role="status">
          Не удалось подтвердить сохранённые даты количества: {formatApiError(bases.error)}
        </p>
      ) : (
        <>
          <label>
            Сохранённая дата количества{" "}
            <select
              aria-label="Сохранённая дата количества"
              value={selectedBasis ? asOf : ""}
              onChange={(event) => {
                if (!event.target.value) return;
                retire();
                setParams((previous) => {
                  const next = new URLSearchParams(previous);
                  next.set("payout_as_of", event.target.value);
                  return next;
                });
              }}
            >
              <option value="">Выбери доказанную дату из выписки</option>
              {bases.data?.bases.map((basis) => (
                <option key={basis.as_of} value={basis.as_of}>
                  {basis.as_of} · количество {basis.quantity ?? "не подтверждено"}
                </option>
              ))}
            </select>
          </label>
          {selectedBasis ? (
            <>
              <p>
                Наблюдаемое количество: {selectedBasis.quantity ?? "не подтверждено"} на{" "}
                {selectedBasis.as_of}. Не финансовая позиция.
              </p>
              <Reasons codes={selectedBasis.reason_codes} />
            </>
          ) : (
            <p>
              На {asOf || closingDate} сохранённое количество не подтверждено. Выбери доступную дату
              или добавь точную выписку с EOD этой даты.
            </p>
          )}
          {asOf !== closingDate && (
            <p>
              Количество другой даты — только сценарий выплат. Оно не заменяет закрывающий EOD{" "}
              {closingDate} для доходности месяца.
            </p>
          )}
        </>
      )}
      <label>
        Дата количества из выписки{" "}
        <input
          aria-label="Дата количества из выписки"
          type="date"
          value={asOf}
          onChange={(event) => {
            retire();
            setParams((previous) => {
              const next = new URLSearchParams(previous);
              next.set("payout_as_of", event.target.value);
              return next;
            });
          }}
        />
      </label>{" "}
      <Button
        type="button"
        variant="primary"
        disabled={busy || !validDate}
        onClick={() => void run()}
      >
        {busy ? "Запрашиваем…" : "Запросить предварительные выплаты T-Invest"}
      </Button>
      {!validDate && (
        <p role="alert">
          Нужна одна корректная дата количества. Выбери её явно; другая дата не подставляется.
        </p>
      )}
      {error && <p role="alert">{error}</p>}
      {result && (
        <>
          <p>
            Источник: {result.native_source_account} · ISIN: {result.isin} · количество:{" "}
            {result.quantity ?? "неизвестно"} на {result.as_of}. Финансовых записей не создаётся.
          </p>
          <Reasons
            codes={[...result.reason_codes, ...result.reconciliation_reasons, ...result.failures]}
          />
          <section aria-label="Фактические строки источника (actual)">
            <h4>Фактические строки источника (actual) · вся сохранённая история</h4>
            <p className={styles.note}>
              Включая известные выплаты после даты количества. Неизвестная или устаревшая атрибуция
              остаётся видимой; эти строки не складываются повторно с прогнозом.
            </p>
            {!result.actuals.length ? (
              <p>Сохранённых actual в ответе нет; это не доказательство нулевого дохода.</p>
            ) : (
              <div className={styles.tableWrap}>
                <table className={styles.table}>
                  <caption>Actual для сверки · включая события после даты количества</caption>
                  <thead>
                    <tr>
                      <th>Дата / вид</th>
                      <th>Зачислено net</th>
                      <th>Gross / налог</th>
                      <th>Атрибуция и источник</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.actuals.map((event) => (
                      <tr key={event.event_key}>
                        <td>
                          {event.event_date ?? "Дата неизвестна"} · {event.kind}
                        </td>
                        <td>{money(event.net_payout_kopecks)}</td>
                        <td>
                          {money(event.gross_payout_kopecks)} / {money(event.withheld_tax_kopecks)}
                        </td>
                        <td>
                          {event.native_source_account} ·{" "}
                          {event.effective_isin ?? event.isin ?? "ISIN неизвестен"}
                          <br />
                          {event.current ? "Актуальное сопоставление" : "Сопоставление неактуально"}{" "}
                          · {event.counted ? "Учтено в доступном компоненте" : "Не учтено"}
                          <br />
                          {event.classification_status ?? "Классификация неизвестна"} ·{" "}
                          {event.attribution_basis ?? "Основание неизвестно"}
                          <details>
                            <summary>Ключ actual и классификация</summary>
                            <code>{event.event_key}</code>
                            <p>
                              {event.classification} · {event.classification_origin} ·{" "}
                              {event.persisted_link_status}
                            </p>
                          </details>
                          <References values={event.source_references} />
                          <Reasons codes={[...event.reason_codes, ...event.assumptions]} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
          <ScheduleRows
            title="Возможно уже выплачено (possible_paid)"
            rows={result.rows.filter((row) => row.status === "possible_paid")}
          />
          <p>
            possible_paid — кандидат сопоставления, а не доказанная выплата. Он не учитывается как
            будущий; автоматического подтверждения нет.
          </p>
          <ScheduleRows
            title="Будущие кандидаты (future)"
            rows={result.rows.filter((row) => row.status === "future" && row.countable_future)}
          />
          <ScheduleRows
            title="Остальные кандидаты · не входят в future"
            rows={result.rows.filter(
              (row) =>
                row.status !== "possible_paid" &&
                !(row.status === "future" && row.countable_future),
            )}
          />
          <details>
            <summary>Происхождение preview</summary>
            <p>
              Provider: {result.provider} · UID:{" "}
              {result.instrument_uid ?? "нет принятого сопоставления"} · Hermes-счёт:{" "}
              {result.account_id ?? "без привязки"} · инструмент:{" "}
              {result.instrument_id ?? "не принят"}
            </p>
            <References values={result.quantity_references} />
            <code>{result.dependency_fingerprint}</code>
            {result.source_references.map((source) => (
              <p key={source.intake_id}>
                Источник #{source.intake_id} · ревизия {source.journal_revision} ·{" "}
                {source.parser_version}
                <br />
                <code>
                  {source.original_digest} · {source.manifest_digest} · {source.link_dependencies} ·{" "}
                  {source.classification_dependencies.join(", ")}
                </code>
              </p>
            ))}
          </details>
        </>
      )}
    </section>
  );
}
