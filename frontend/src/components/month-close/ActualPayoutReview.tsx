import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  confirmActualPayout,
  listPayoutObligations,
  previewActualPayout,
  readActualPayout,
  type PayoutIntent,
  type PayoutObligation,
  type PayoutPlan,
  type PayoutReceipt,
} from "../../api/actualPayouts";
import { ApiClientError, formatApiError } from "../../api/client";
import { Button } from "../ui";
import styles from "./BrokerMonthReview.module.css";

export function ActualPayoutReview({
  monthId,
  accountId,
  baseRequestId,
  closed,
}: {
  monthId: number;
  accountId: number;
  baseRequestId: string;
  closed: boolean;
}) {
  const query = useQuery({
    queryKey: ["actual-payout-obligations", monthId, accountId, baseRequestId],
    queryFn: ({ signal }) => listPayoutObligations(monthId, accountId, signal),
  });
  return (
    <section aria-label="Сверка фактических выплат" className={styles.stack}>
      <h4>Сверка фактических выплат с прогнозами</h4>
      <p>
        Факт берётся из принятого Money. Связь требует доказательства полного исполнения конкретного
        события; близость дат и сумм этого не доказывает.
      </p>
      {query.isFetching ? (
        <p role="status">Проверяем актуальность выплат…</p>
      ) : query.isError ? (
        <p role="alert">{formatApiError(query.error)}</p>
      ) : (
        query.data
          ?.filter((row) => row.base_request_id === baseRequestId)
          .map((row) => (
            <SettlementRow
              key={`${row.investment_cash_flow_id}:${query.dataUpdatedAt}`}
              row={row}
              closed={closed}
            />
          ))
      )}
    </section>
  );
}

function SettlementRow({ row, closed }: { row: PayoutObligation; closed: boolean }) {
  const cache = useQueryClient();
  const alive = useRef(true);
  const epoch = useRef(0);
  const [operation, setOperation] = useState<PayoutIntent["operation"]>(
    row.terminal_relation ? "reaffirm" : "link",
  );
  const [app, setApp] = useState(row.terminal_relation?.applied_payout_id ?? "");
  const [ecf, setEcf] = useState(row.terminal_relation?.expected_cash_flow_id ?? "");
  const [legacy, setLegacy] = useState("");
  const [reference, setReference] = useState("");
  const [eventReference, setEventReference] = useState("");
  const [settlementReference, setSettlementReference] = useState("");
  const [providerIdentity, setProviderIdentity] = useState("");
  const [actualKey, setActualKey] = useState("");
  const [forecastKey, setForecastKey] = useState("");
  const [prepared, setPrepared] = useState<{ intent: PayoutIntent; plan: PayoutPlan } | null>(null);
  const [approved, setApproved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [receipt, setReceipt] = useState<PayoutReceipt | null>(null);
  const storageKey = `payout-pending:${row.base_request_id}:${row.account_id}:${row.reporting_month_id}:${row.investment_cash_flow_id}`;
  const [pending, setPending] = useState<{ id: string; digest: string; accepted?: unknown } | null>(
    () => {
      const saved = sessionStorage.getItem(storageKey);
      if (!saved) return null;
      try {
        const value = JSON.parse(saved);
        if (
          typeof value.id === "string" &&
          /^[a-zA-Z0-9_-]{1,64}$/.test(value.id) &&
          typeof value.digest === "string" &&
          /^[a-f0-9]{64}$/.test(value.digest)
        )
          return value;
      } catch {
        /* Preserve uncertain state; malformed recovery data must not permit Confirm. */
      }
      return { id: "invalid-pending-record", digest: "" };
    },
  );
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      epoch.current++;
    };
  }, []);
  function invalidate() {
    epoch.current++;
    setPrepared(null);
    setApproved(false);
    setError(null);
  }
  function intent(): PayoutIntent {
    return {
      contract_version: "broker_payout_reconciliation_v1",
      operation,
      base_request_id: row.base_request_id,
      reporting_month_id: row.reporting_month_id,
      account_id: row.account_id,
      investment_cash_flow_id: row.investment_cash_flow_id,
      applied_payout_id: app ? Number(app) : null,
      expected_cash_flow_id: ecf ? Number(ecf) : null,
      predecessor_id:
        operation === "distinct"
          ? null
          : row.terminal_relation
            ? Number(row.terminal_relation.id)
            : legacy
              ? Number(legacy)
              : null,
    };
  }
  function validPlan(plan: PayoutPlan) {
    if (
      plan.contract_version !== "broker_payout_reconciliation_v1" ||
      plan.scope.account_id !== row.account_id ||
      plan.scope.reporting_month_id !== row.reporting_month_id
    )
      throw new Error("Получен Preview другого счёта или месяца.");
  }
  async function prepare() {
    if (busy || closed || pending) return;
    invalidate();
    const generation = epoch.current;
    setBusy(true);
    try {
      const requested = intent();
      const initial = await previewActualPayout(requested);
      validPlan(initial);
      const same = operation === "link" || operation === "reaffirm";
      requested.claims = {
        reference,
        independent_event_reference: eventReference,
        settlement_basis_reference: settlementReference,
        review_context_digest: initial.review_context_digest,
        actual_is_exact_event: same,
        full_event_settled_not_partial: same,
        exact_manual_row_is_same_event: same && !!ecf,
        provider_identity_key: app ? providerIdentity : null,
        actual_and_forecast_are_distinct: operation === "distinct",
        actual_independent_event_key: actualKey || null,
        forecast_independent_event_key: forecastKey || null,
      };
      const plan = await previewActualPayout(requested);
      validPlan(plan);
      if (alive.current && generation === epoch.current) setPrepared({ intent: requested, plan });
    } catch (e) {
      if (alive.current && generation === epoch.current) setError(formatApiError(e));
    } finally {
      if (alive.current && generation === epoch.current) setBusy(false);
    }
  }
  async function recover(expected: NonNullable<typeof pending>) {
    const current = await readActualPayout(expected.id);
    if (
      current.contract_version !== "broker_payout_reconciliation_v1" ||
      current.request_id !== expected.id ||
      current.confirmation_digest !== expected.digest ||
      current.account_id !== row.account_id ||
      current.reporting_month_id !== row.reporting_month_id ||
      (expected.accepted !== undefined &&
        JSON.stringify(current.accepted) !== JSON.stringify(expected.accepted))
    )
      throw new Error("Независимый GET не подтвердил сохранённое решение.");
    if (alive.current) {
      sessionStorage.removeItem(storageKey);
      setReceipt(current);
      setPending(null);
      setPrepared(null);
      setApproved(false);
      await cache.invalidateQueries();
    }
  }
  async function confirm() {
    if (!prepared?.plan.can_apply || !approved || closed || busy || pending) return;
    setBusy(true);
    setError(null);
    const expected = { id: crypto.randomUUID(), digest: prepared.plan.confirmation_digest };
    try {
      sessionStorage.setItem(storageKey, JSON.stringify(expected));
      setPending(expected); // Back/Reload and lost ACK permit only GET recovery.
      const accepted = await confirmActualPayout(prepared.intent, expected.digest, expected.id);
      if (alive.current) setPending({ ...expected, accepted: accepted.accepted });
      await recover({ ...expected, accepted: accepted.accepted });
    } catch (e) {
      if (alive.current) {
        if (e instanceof ApiClientError && e.status === 409) {
          sessionStorage.removeItem(storageKey);
          setPending(null);
          setPrepared(null);
          setApproved(false);
        }
        setError(formatApiError(e));
      }
    } finally {
      if (alive.current) setBusy(false);
    }
  }
  async function retryRead() {
    if (!pending || busy) return;
    setBusy(true);
    setError(null);
    try {
      await recover(pending);
    } catch (e) {
      if (alive.current) setError(formatApiError(e));
    } finally {
      if (alive.current) setBusy(false);
    }
  }
  const disabled = busy || closed || pending !== null;
  const forecastLabel = (kind: "app" | "ecf", id: string | null) => {
    const f = row.forecast_choices.find((x) => x.kind === kind && x.facts.id === id);
    return f
      ? `#${id} · ${f.facts.payment_date ?? f.facts.expected_date} · ${f.facts.identity_key ?? f.facts.forecast_version}`
      : `#${id}`;
  };
  return (
    <details className={styles.stack}>
      <summary>
        Выплата #{row.investment_cash_flow_id}:{" "}
        {row.terminal_relation
          ? stateLabel(row.terminal_relation.state)
          : row.coverage_state === "unknown"
            ? "требуется сверка"
            : "без связи"}
      </summary>
      <p>
        Фактическая дата: {row.actual.event_date}. Net: {row.actual.net_amount_kopecks} коп. Налог:{" "}
        {row.actual.tax_amount_kopecks ?? "неизвестно"}.
      </p>
      {row.candidates.map((c) => (
        <p key={`${c.kind}:${c.facts.id}`}>
          {forecastLabel(c.kind, c.facts.id)}: {stateLabel(c.state ?? "unresolved")}
        </p>
      ))}
      {row.terminal_relation && (
        <p>
          Принятое решение: {row.terminal_relation.accepted_request_id}; отзыв:{" "}
          {row.terminal_relation.retired_request_id ?? "отсутствует"}.
        </p>
      )}
      {!closed && (
        <>
          <label>
            Решение
            <select
              value={operation}
              disabled={disabled}
              onChange={(e) => {
                setOperation(e.target.value as PayoutIntent["operation"]);
                invalidate();
              }}
            >
              {!row.terminal_relation && (
                <option value="link">Связать с исполненным событием</option>
              )}
              {row.terminal_relation && (
                <option value="reaffirm">Подтвердить заново отдельной записью</option>
              )}
              {row.terminal_relation && !row.terminal_relation.retired_request_id && (
                <option value="retire">Отозвать доказательство связи</option>
              )}
              <option value="distinct">Доказанно разные события</option>
            </select>
          </label>
          {!row.terminal_relation && row.legacy_relations.length > 0 && (
            <label>
              Существующая связь прогнозов
              <select
                disabled={disabled || operation !== "link"}
                value={legacy}
                onChange={(e) => {
                  setLegacy(e.target.value);
                  const pair = row.legacy_relations.find((link) => link.id === e.target.value);
                  setApp(pair?.applied_payout_id ?? "");
                  setEcf(pair?.expected_cash_flow_id ?? "");
                  invalidate();
                }}
              >
                <option value="">Новая связь</option>
                {row.legacy_relations.map((link) => (
                  <option key={link.id} value={link.id ?? ""}>
                    Связь #{link.id}: прогноз провайдера #{link.applied_payout_id} и ручной #
                    {link.expected_cash_flow_id}
                  </option>
                ))}
              </select>
            </label>
          )}
          {(["app", "ecf"] as const).map((kind) => (
            <label key={kind}>
              {kind === "app" ? "Принятый прогноз провайдера" : "Ручной прогноз"}
              <select
                disabled={
                  disabled ||
                  operation === "retire" ||
                  operation === "reaffirm" ||
                  (operation === "link" && !!legacy)
                }
                value={kind === "app" ? app : ecf}
                onChange={(e) => {
                  (kind === "app" ? setApp : setEcf)(e.target.value);
                  invalidate();
                }}
              >
                <option value="">Без этой стороны</option>
                {row.forecast_choices
                  .filter((c) => c.kind === kind)
                  .map((c) => (
                    <option key={c.facts.id} value={c.facts.id ?? ""}>
                      {forecastLabel(kind, c.facts.id)}
                    </option>
                  ))}
              </select>
            </label>
          ))}
          {app && (
            <label>
              Точная identity события из независимого подтверждения
              <input
                value={providerIdentity}
                disabled={disabled}
                onChange={(e) => {
                  setProviderIdentity(e.target.value);
                  invalidate();
                }}
              />
            </label>
          )}
          {[
            ["Ссылка на проверенный источник", reference, setReference],
            ["Основание точной связи события", eventReference, setEventReference],
            [
              "Основание полного исполнения или отзыва",
              settlementReference,
              setSettlementReference,
            ],
            ...(operation === "distinct"
              ? [
                  ["Независимый ключ actual", actualKey, setActualKey],
                  ["Независимый ключ прогноза", forecastKey, setForecastKey],
                ]
              : []),
          ].map(([label, value, setter]) => (
            <label key={label as string}>
              {label as string}
              <input
                disabled={disabled}
                value={value as string}
                onChange={(e) => {
                  (setter as (s: string) => void)(e.target.value);
                  invalidate();
                }}
              />
            </label>
          ))}
          <p>Ссылки — идентификаторы проверенных доказательств (латиница, цифры, _ или -).</p>
          <Button
            type="button"
            disabled={disabled || !reference || !eventReference || !settlementReference}
            onClick={() => void prepare()}
          >
            Проверить связь выплаты
          </Button>
          {prepared && (
            <>
              <p>Новых денежных фактов: 0. Cash не меняется. {prepared.plan.blockers.join("; ")}</p>
              <label>
                <input
                  type="checkbox"
                  checked={approved}
                  disabled={disabled || !prepared.plan.can_apply}
                  onChange={(e) => setApproved(e.target.checked)}
                />
                Подтверждаю это конкретное решение: точное событие и полное исполнение либо
                доказанный отзыв / разные события.
              </label>
              <Button
                type="button"
                disabled={disabled || !approved || !prepared.plan.can_apply}
                onClick={() => void confirm()}
              >
                Подтвердить связь выплаты
              </Button>
            </>
          )}
        </>
      )}
      {pending && (
        <Button type="button" disabled={busy} onClick={() => void retryRead()}>
          Повторить GET связи
        </Button>
      )}
      {receipt && <p role="status">Решение {receipt.request_id} подтверждено независимым GET.</p>}
      {error && <p role="alert">{error}</p>}
    </details>
  );
}

function stateLabel(state: string) {
  return (
    (
      {
        paid: "исполнено",
        future: "отдельная будущая выплата",
        unresolved: "требуется сверка",
        stale: "доказательство устарело",
        retired: "доказательство отозвано",
      } as Record<string, string>
    )[state] ?? state
  );
}
