import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { listInstruments } from "../../api/instruments";
import { formatApiError } from "../../api/client";
import {
  applyBrokerMoney,
  previewBrokerMoney,
  readBrokerMoney,
  type MoneyDecision,
  type MoneyIntent,
  type MoneyPreview,
  type MoneyReadback,
} from "../../api/brokerMoney";
import { formatDate, formatMoney } from "../../lib/format";
import { Button, Table, Td, Th } from "../ui";
import styles from "./BrokerMonthReview.module.css";

const ownerClaims = [
  "original_row_identifiable",
  "posted_cash_date_confirmed",
  "signed_cash_convention_confirmed",
  "owner_capital_crossing",
  "not_income_tax_promotion_or_internal_cash",
  "not_settlement_or_commission",
  "cash_not_in_kind",
  "not_tracked_account_transfer",
  "counterparty_outside_account_boundary",
  "complete_occurrence_set_is_one_event",
];
const identity = (row: { import_id: number; ordinal: number }) => `${row.import_id}:${row.ordinal}`;
function minor(value: string | null | undefined) {
  if (value == null || !/^\d+$/.test(value)) return null;
  const amount = BigInt(value);
  return `${amount / 100n}.${String(amount % 100n).padStart(2, "0")}`;
}

export function MoneyStored({ saved }: { saved: MoneyReadback }) {
  return (
    <div className={styles.stack}>
      <p role="status">
        Принятые Money:{" "}
        {saved.bookkeeping_ready
          ? "компонент счёта готов к общей проверке"
          : "черновик остаётся неполным"}
        . Внешний взнос портфеля не подтверждён.
      </p>
      <Table>
        <caption>Сохранённые купоны и пополнения</caption>
        <thead>
          <tr>
            <Th>Событие</Th>
            <Th>Цель</Th>
            <Th numeric>Net / граница счёта</Th>
            <Th>Налог</Th>
            <Th>Authority</Th>
          </tr>
        </thead>
        <tbody>
          {saved.targets.map((target) => (
            <tr key={`${target.role}:${target.target_id}`}>
              <Td>{target.role === "coupon" ? "Купон" : "Пополнение счёта"}</Td>
              <Td>{target.target_id}</Td>
              <Td numeric>
                {formatMoney(
                  minor(
                    target.facts?.[
                      target.role === "coupon" ? "net_amount_kopecks" : "boundary_amount_kopecks"
                    ],
                  ),
                )}
              </Td>
              <Td>
                {target.role === "coupon"
                  ? formatMoney(
                      minor(
                        target.components
                          ? target.components.tax_amount_kopecks
                          : target.facts?.tax_amount_kopecks,
                      ),
                      { empty: "Неизвестно" },
                    )
                  : "Не применяется"}
              </Td>
              <Td>{target.effective ? "Подтверждено" : "Требуется сверка"}</Td>
            </tr>
          ))}
        </tbody>
      </Table>
      <p>
        Gross и комиссия новых net-купонов неизвестны. Остаток RUB cash не увеличивается. Полнота
        портфеля и точная доходность не подтверждены.
      </p>
      {saved.exceptions.length > 0 && (
        <details>
          <summary>Сохранившиеся ограничения</summary>
          <ul>
            {saved.exceptions.map((code) => (
              <li key={code}>{code}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

export function BrokerMoneyReview({
  baseRequestId,
  monthId,
  accountId,
  importId,
  closed,
  stored,
}: {
  baseRequestId: string;
  monthId: number;
  accountId: number;
  importId: number;
  closed: boolean;
  stored?: MoneyReadback | null;
}) {
  const cache = useQueryClient();
  const instruments = useQuery({
    queryKey: ["money-bonds"],
    queryFn: ({ signal }) => listInstruments({ instrument_type: "bond" }, signal),
    enabled: !closed,
  });
  const [files, setFiles] = useState<File[]>([]);
  const [preview, setPreview] = useState<MoneyPreview | null>(null);
  const [decisions, setDecisions] = useState<MoneyDecision[]>([]);
  const [reviewed, setReviewed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [currentPlan, setCurrentPlan] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<MoneyReadback | null>(null);
  const [pending, setPending] = useState<{
    committed: MoneyReadback;
    digest: string;
    id: string;
  } | null>(null);
  const active = useRef(true);
  const closedRef = useRef(closed);
  closedRef.current = closed;
  const request = useRef<string | null>(null);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  useEffect(() => {
    if (stored) setSaved(null);
  }, [stored]);
  const intent = (selected = decisions): MoneyIntent => ({
    contract_version: "broker_money_v1",
    base_request_id: baseRequestId,
    reporting_month_id: monthId,
    account_id: accountId,
    money_decisions: selected,
  });
  function invalidate() {
    setReviewed(false);
    setCurrentPlan(false);
    request.current = null;
    setError(null);
  }
  function valid(result: MoneyPreview | MoneyReadback) {
    if (
      result.contract_version !== "broker_money_v1" ||
      result.account_id !== accountId ||
      result.reporting_month_id !== monthId ||
      result.base_request_id !== baseRequestId
    )
      throw new Error("Получены Money другого счёта, месяца или источника.");
  }
  async function inspect() {
    if (!files.length || busy || closed) return;
    invalidate();
    setBusy(true);
    try {
      const result = await previewBrokerMoney(files, intent());
      valid(result);
      if (active.current) {
        setPreview(result);
        setCurrentPlan(true);
      }
    } catch (e) {
      if (active.current) setError(formatApiError(e));
    } finally {
      if (active.current) setBusy(false);
    }
  }
  async function apply() {
    if (!preview || !reviewed || !currentPlan || busy || closed || pending) return;
    setBusy(true);
    setError(null);
    try {
      const selected = preview.decisions.map((proposed) => {
        const decision = { ...proposed.decision };
        if (decision.role === "coupon" && proposed.action !== "reuse")
          decision.coupon_claims = {
            reference: "desktop-specific-money-review",
            review_context_digest: proposed.review_context_digest ?? "",
            actual_coupon_payment: true,
            exact_row_instrument_link: true,
            complete_occurrence_set_is_one_event: true,
            existing_target_is_same_payment: decision.investment_cash_flow_id != null,
          };
        if (decision.role === "account_funding" && proposed.h2_plan && proposed.owner_flow_intent)
          decision.owner_flow_intent = {
            ...proposed.owner_flow_intent,
            claims: {
              provenance_kind: "owner_attested_source_row",
              reference: "desktop-account-boundary-review",
              direction: "contribution",
              source_set_fingerprint: proposed.h2_plan.source_set_fingerprint,
              review_context_digest: proposed.h2_plan.review_context_digest,
              ...Object.fromEntries(ownerClaims.map((name) => [name, true])),
            },
          };
        return decision;
      });
      const requested = intent(selected);
      const confirmed = await previewBrokerMoney(files, requested);
      valid(confirmed);
      if (!active.current || closedRef.current) return;
      if (!confirmed.can_apply) {
        if (active.current) {
          setPreview(confirmed);
          setReviewed(false);
        }
        throw new Error(confirmed.blockers.join("; "));
      }
      request.current ??= crypto.randomUUID();
      const committed = await applyBrokerMoney(
        files,
        requested,
        confirmed.confirmation_digest,
        request.current,
      );
      const awaiting = { committed, digest: confirmed.confirmation_digest, id: request.current };
      if (active.current) setPending(awaiting);
      const read = await readBrokerMoney(awaiting.id);
      valid(read);
      if (
        read.request_id !== request.current ||
        read.confirmation_digest !== confirmed.confirmation_digest ||
        JSON.stringify(read.accepted) !== JSON.stringify(committed.accepted) ||
        JSON.stringify(read.targets) !== JSON.stringify(committed.targets)
      )
        throw new Error(
          "Независимое GET не подтвердило Money. Обнови состояние; повтор не создаёт новые деньги.",
        );
      if (!active.current) return;
      setSaved(read);
      setPending(null);
      setPreview(null);
      setReviewed(false);
      await cache.invalidateQueries();
    } catch (e) {
      if (active.current) setError(formatApiError(e));
    } finally {
      if (active.current) setBusy(false);
    }
  }
  async function retryRead() {
    if (!pending || busy) return;
    setBusy(true);
    setError(null);
    try {
      const read = await readBrokerMoney(pending.id);
      valid(read);
      if (
        read.request_id !== pending.id ||
        read.confirmation_digest !== pending.digest ||
        JSON.stringify(read.accepted) !== JSON.stringify(pending.committed.accepted) ||
        JSON.stringify(read.targets) !== JSON.stringify(pending.committed.targets)
      )
        throw new Error("Независимое GET Money не совпало с сохранённым batch.");
      if (!active.current) return;
      setSaved(read);
      setPending(null);
      setPreview(null);
      setReviewed(false);
      await cache.invalidateQueries();
    } catch (e) {
      if (active.current) setError(formatApiError(e));
    } finally {
      if (active.current) setBusy(false);
    }
  }
  function update(decision: MoneyDecision) {
    setDecisions((rows) =>
      rows.map((row) => (identity(row.seed) === identity(decision.seed) ? decision : row)),
    );
    setPreview(null);
    invalidate();
  }
  const current = saved ?? stored;
  return (
    <div className={styles.stack}>
      {current && <MoneyStored saved={current} />}
      {pending && (
        <Button type="button" disabled={busy} onClick={() => void retryRead()}>
          Повторить GET Money
        </Button>
      )}
      {!closed && (
        <details>
          <summary>Принять купоны и пополнения в этот черновик</summary>
          <div className={styles.stack}>
            <p>
              Счёт #{accountId}. Точные даты и RUB суммы взяты из источника. Один batch дополняет
              существующий черновик. НКД, комиссии и неразобранные строки сохраняют ограничения.
            </p>
            <label className={styles.field}>
              Оригинальные XML для Money, включая принятые пересекающиеся отчёты
              <input
                type="file"
                accept=".xml"
                multiple
                disabled={busy || pending != null}
                onChange={(e) => {
                  setFiles(Array.from(e.target.files ?? []));
                  setDecisions([]);
                  setPreview(null);
                  invalidate();
                }}
              />
            </label>
            <Button
              type="button"
              disabled={busy || !files.length || pending != null}
              onClick={() => void inspect()}
            >
              Проверить Money
            </Button>
            {preview && (
              <>
                <Table>
                  <caption>Все наблюдения Money</caption>
                  <thead>
                    <tr>
                      <Th>Источник / строка</Th>
                      <Th>Дата</Th>
                      <Th numeric>RUB сумма</Th>
                      <Th>Наблюдение</Th>
                      <Th>Решение</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.inventory.map((row) => (
                      <tr key={identity(row.occurrence)}>
                        <Td>
                          #{row.occurrence.import_id} / {row.occurrence.ordinal + 1}
                        </Td>
                        <Td>{formatDate(row.date)}</Td>
                        <Td numeric>{formatMoney(row.signed_amount)}</Td>
                        <Td>
                          {row.description}
                          <br />
                          {row.candidate_kind}
                        </Td>
                        <Td>
                          {row.occurrence.import_id === importId &&
                          ["coupon_paid_candidate", "account_cash_in_candidate"].includes(
                            row.candidate_kind,
                          ) ? (
                            <label>
                              <input
                                type="checkbox"
                                disabled={busy}
                                checked={decisions.some(
                                  (d) => identity(d.seed) === identity(row.occurrence),
                                )}
                                onChange={(e) => {
                                  const seed = {
                                    import_id: row.occurrence.import_id,
                                    section: "money" as const,
                                    ordinal: row.occurrence.ordinal,
                                  };
                                  setDecisions((items) =>
                                    e.target.checked
                                      ? [
                                          ...items,
                                          {
                                            role:
                                              row.candidate_kind === "coupon_paid_candidate"
                                                ? "coupon"
                                                : "account_funding",
                                            seed,
                                          },
                                        ]
                                      : items.filter((d) => identity(d.seed) !== identity(seed)),
                                  );
                                  invalidate();
                                }}
                              />
                              Принять эту конкретную строку
                            </label>
                          ) : (
                            "Наблюдение / ограничение"
                          )}
                        </Td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
                {preview.sources
                  .filter((source) => source.original_required)
                  .map((source) => (
                    <p role="alert" key={source.import_id}>
                      Нужен принятый оригинал источника #{source.import_id},{" "}
                      {source.source.covered_from} — {source.source.covered_to}.
                    </p>
                  ))}
              </>
            )}
            {decisions.map((decision) => (
              <div key={identity(decision.seed)} className={styles.stack}>
                <p>
                  Строка #{decision.seed.import_id} / {decision.seed.ordinal + 1}:{" "}
                  {decision.role === "coupon" ? "Купон" : "Пополнение только этого счёта"}
                </p>
                {decision.role === "coupon" && (
                  <>
                    <label className={styles.field}>
                      Подтверждённая облигация для строки {decision.seed.ordinal + 1}
                      <select
                        disabled={busy}
                        value={decision.instrument_id ?? ""}
                        onChange={(e) =>
                          update({
                            ...decision,
                            instrument_id: Number(e.target.value) || undefined,
                          })
                        }
                      >
                        <option value="">Выбери точную облигацию</option>
                        {instruments.data
                          ?.filter((i) => i.currency === "RUB")
                          .map((i) => (
                            <option key={i.id} value={i.id}>
                              {i.name} · {i.isin}
                            </option>
                          ))}
                      </select>
                    </label>
                    <label className={styles.field}>
                      ID уже принятой той же выплаты, если она существует
                      <input
                        type="number"
                        min="1"
                        disabled={busy}
                        value={decision.investment_cash_flow_id ?? ""}
                        onChange={(e) =>
                          update({
                            ...decision,
                            investment_cash_flow_id: Number(e.target.value) || undefined,
                          })
                        }
                      />
                    </label>
                  </>
                )}
                <label className={styles.field}>
                  Действие для строки {decision.seed.ordinal + 1}
                  <select
                    disabled={busy}
                    value={decision.operation ?? "accept"}
                    onChange={(e) =>
                      update({
                        ...decision,
                        operation: e.target.value as MoneyDecision["operation"],
                      })
                    }
                  >
                    <option value="accept">Принять / переиспользовать</option>
                    <option value="corroborate">Дополнить доказательства той же выплаты</option>
                    <option value="reaffirm">Повторно подтвердить отозванные доказательства</option>
                  </select>
                </label>
              </div>
            ))}
            {preview && preview.decisions.length > 0 && (
              <>
                {preview.expected_effects && (
                  <p>
                    При успешном Apply: новых купонов — {preview.expected_effects.new_coupon_facts},
                    новых пополнений счёта — {preview.expected_effects.new_account_flow_facts}. Net
                    выбранных купонов:{" "}
                    {formatMoney(minor(preview.expected_effects.selected_coupon_net_minor), {
                      empty: "Неизвестно",
                    })}
                    . ExternalFlow и дополнительного изменения cash — 0.
                  </p>
                )}
                {preview.decisions.map((proposed) => (
                  <div key={identity(proposed.decision.seed)}>
                    <p>
                      Решение строки {proposed.decision.seed.ordinal + 1}: {proposed.action}; цель{" "}
                      {proposed.target_id ?? "новое событие"}. Все наблюдения одной выплаты:{" "}
                      {proposed.occurrences
                        .map((o) => `#${o.import_id}/${o.ordinal + 1}`)
                        .join(", ")}
                      .
                    </p>
                    {proposed.decision.role === "coupon" ? (
                      <p>
                        Подтверждаю фактический купон, точную связь этой строки с выбранной
                        облигацией и что полный набор наблюдений — одна выплата. При выборе
                        существующей цели это именно та же выплата.
                      </p>
                    ) : (
                      <p>
                        Подтверждаю идентифицируемую исходную строку, дату фактической проводки,
                        знак и денежное пополнение из-за границы этого счёта. Это не доход, налог,
                        акция, внутреннее движение, расчёт сделки, комиссия, перевод другого
                        отслеживаемого счёта или вклад бумагами. Все показанные наблюдения относятся
                        к одному событию. Граница портфеля неизвестна.
                      </p>
                    )}
                  </div>
                ))}
                <label className={styles.review}>
                  <input
                    type="checkbox"
                    checked={reviewed}
                    disabled={busy || !currentPlan}
                    onChange={(e) => setReviewed(e.target.checked)}
                  />
                  Я подтверждаю перечисленные конкретные решения Money и их полный набор наблюдений.
                </label>
                <Button
                  type="button"
                  disabled={busy || !reviewed || !currentPlan || pending != null}
                  onClick={() => void apply()}
                >
                  Принять один Money batch
                </Button>
              </>
            )}
            {preview && preview.blockers.length > 0 && (
              <details>
                <summary>Недостающие подтверждения и конфликты</summary>
                <ul>
                  {preview.blockers.map((code) => (
                    <li key={code}>{code}</li>
                  ))}
                </ul>
              </details>
            )}
            {error && <p role="alert">{error}</p>}
          </div>
        </details>
      )}
    </div>
  );
}
