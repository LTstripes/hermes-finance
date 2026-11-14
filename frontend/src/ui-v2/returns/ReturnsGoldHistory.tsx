import { reasonCopy } from "../../lib/reasonCopy";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useState } from "react";
import { Button, Input, Select } from "../../components/ui";
import formStyles from "./ReturnsGoldHistory.module.css";
import { ApiClientError } from "../../api/client";
import { formatDate, formatQuantity } from "../../lib/format";
import { fromKopecks } from "../../lib/money";
import { MonthNavigationGuard } from "../MonthNavigationGuard";
import { money } from "../SourceInstrumentDetail";
import {
  applyGoldHistory,
  checkGoldHistory,
  GOLD_VERSION,
  type GoldEventInput,
  type GoldHistory,
  type GoldIntent,
  type GoldPreview,
  type GoldReceipt,
  type GoldResult,
  type GoldValuation,
  getGoldHistories,
  getGoldHistory,
  getGoldReceipt,
  goldPendingKey,
  previewGoldHistory,
} from "./goldHistory";
import styles from "./InstrumentCard.module.css";
import type { Metric } from "./model";

const event = (): GoldEventInput => ({
  event_id: `g_${crypto.randomUUID().replaceAll("-", "")}`,
  event_date: "",
  side: "BUY",
  grams: "",
  amount_basis: "actual",
  amount_rub: "",
  unit_price_rub: null,
  fee_state: "unknown",
  fee_rub: null,
});
function empty(account_id: number, instrument_id: number): GoldIntent {
  return {
    contract_version: GOLD_VERSION,
    account_id,
    instrument_id,
    expected_revision: 0,
    covered_from: "",
    covered_to: "",
    complete: false,
    zero_start: false,
    current_quantity: "",
    current_quantity_date: "",
    provenance_reference: "",
    change_reason: null,
    events: [event()],
  };
}
function edit(history: GoldHistory): GoldIntent {
  const { events, ...declaration } = history.declaration;
  return {
    ...declaration,
    expected_revision: history.revision,
    change_reason: "",
    events: events.map((row) => ({
      event_id: row.event_id,
      event_date: row.event_date,
      side: row.side,
      grams: row.grams,
      amount_basis: row.amount_basis,
      amount_rub: row.amount_basis === "actual" ? fromKopecks(BigInt(row.amount_kopecks)) : null,
      unit_price_rub: row.amount_basis === "derived_unit_price" ? row.unit_price_rub : null,
      fee_state: row.fee_state,
      fee_rub:
        row.fee_state === "known" && row.separate_fee_kopecks !== null
          ? fromKopecks(BigInt(row.separate_fee_kopecks))
          : null,
    })),
  };
}
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object")
    return `{${Object.entries(value)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([key, item]) => `${JSON.stringify(key)}:${canonical(item)}`)
      .join(",")}}`;
  return JSON.stringify(value) ?? "undefined";
}
function Result({
  value,
  valuation,
  clean,
}: {
  value: GoldResult;
  valuation: GoldValuation | null;
  clean?: Metric | null;
}) {
  const limitations = [
    ...new Set(
      (
        clean?.reason_codes ??
        value.reason_codes.filter((code) => code !== "gold_separate_fees_unknown")
      ).map((code) => reasonCopy(code, { surface: "gold" }).message),
    ),
  ];
  const facts = [
    ["Результат", clean?.value ?? null],
    ["Покупки", value.buy_amount_kopecks],
    ["Продажи", value.sale_amount_kopecks],
  ] as const;
  return (
    <div>
      {facts.some(([, amount]) => amount !== null) && (
        <dl className={styles.goldFacts}>
          {facts
            .filter(([, amount]) => amount !== null)
            .map(([label, amount]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>{money(amount)}</dd>
              </div>
            ))}
        </dl>
      )}
      {clean?.value == null && (
        <p className={styles.notice}>
          Общий результат пока не подтверждён.{" "}
          {limitations.join(" ") || "Проверьте историю и оценку остатка."} Известные части показаны
          отдельно.
        </p>
      )}
      {valuation && (
        <p className={styles.muted}>
          Оценка {money(valuation.market_value_kopecks)} на {formatDate(valuation.price_date)};{" "}
          {formatQuantity(valuation.quantity)} г; снимок месяца{" "}
          {formatDate(valuation.snapshot_date)}
          {valuation.provisional || valuation.month_status === "draft" ? " · предварительная" : ""}.
        </p>
      )}
      <p className={styles.muted}>
        Операции учтены по {formatDate(value.as_of_date)}
        {!valuation ? "; оценка не подтверждена" : ""}.
      </p>
      <details className={styles.details}>
        <summary>Основа расчёта</summary>
        {!!value.reason_codes.length && <code>{value.reason_codes.join(", ")}</code>}
        <p>
          История с {formatDate(value.period.covered_from)} по{" "}
          {formatDate(value.period.covered_to ?? value.as_of_date)}. Комиссии и налоги не входят в
          результат.{" "}
          {value.amount_basis === "derived"
            ? "Суммы операций выведены из цены за грамм."
            : "Использованы фактические суммы операций."}
        </p>
        {value.separate_fees_kopecks !== null && (
          <p>Отдельные комиссии в источнике: {money(value.separate_fees_kopecks)}.</p>
        )}
        {!valuation && <p>Сохранённая оценка остатка не подтверждена.</p>}
        {clean?.value != null && !!limitations.length && <p>{limitations.join(" ")}</p>}
      </details>
    </div>
  );
}
export function ReturnsGoldHistory({
  accountId,
  instrumentId,
  onConfirmed,
  onNavigationStateChange,
  refreshing = false,
  revision = 0,
  cleanResult,
}: {
  accountId: number;
  instrumentId: number;
  onConfirmed?: () => Promise<unknown>;
  onNavigationStateChange?: (state: { dirty: boolean; pending: boolean }) => void;
  refreshing?: boolean;
  revision?: number;
  targetLabel?: string;
  cleanResult?: Metric | null;
}) {
  const formId = useId();
  const queryClient = useQueryClient();
  const key = ["returns", "gold-history", accountId, instrumentId, revision];
  const storageKey = goldPendingKey(accountId, instrumentId);
  const query = useQuery({
    queryKey: key,
    queryFn: ({ signal }) => getGoldHistories(accountId, instrumentId, signal),
    staleTime: 5 * 60 * 1000,
  });
  const [draft, setDraft] = useState(() => empty(accountId, instrumentId));
  const [dirty, setDirty] = useState(false);
  const [formOpen, setFormOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<{
    intent: GoldIntent;
    value: GoldPreview;
    revision: number;
  } | null>(null);
  const [pending, setPending] = useState<string | null>(() => sessionStorage.getItem(storageKey));
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const histories = !refreshing && !query.isFetching && !query.isError ? query.data : undefined;
  const current = histories?.length === 1 ? histories[0] : null;
  const blocked = busy || pending !== null;
  useEffect(() => {
    onNavigationStateChange?.({ dirty, pending: blocked });
  }, [dirty, blocked, onNavigationStateChange]);
  useEffect(
    () => () => onNavigationStateChange?.({ dirty: false, pending: false }),
    [onNavigationStateChange],
  );
  const unavailable =
    !histories || histories.length > 1 || (!!current && draft.expected_revision === 0);
  const change = (next: GoldIntent) => {
    setDraft(next);
    setDirty(true);
    setPreview(null);
    setMessage("");
    setError("");
  };
  const changeEvent = (index: number, update: Partial<GoldEventInput>) =>
    change({
      ...draft,
      events: draft.events.map((row, rowIndex) =>
        rowIndex === index ? { ...row, ...update } : row,
      ),
    });
  async function verify(receipt: GoldReceipt, requestId: string) {
    if (
      receipt?.contract_version !== GOLD_VERSION ||
      receipt.request_id !== requestId ||
      !Number.isSafeInteger(receipt.accepted_revision) ||
      receipt.accepted_revision < 1
    )
      throw new Error("Gold receipt context mismatch");
    checkGoldHistory(receipt.history, accountId, instrumentId);
    const saved = await getGoldHistory(receipt.history.history_id, accountId, instrumentId);
    const accepted = receipt.history.revisions.find(
      (revision) => revision.revision === receipt.accepted_revision,
    );
    const observed = saved.revisions.find(
      (revision) => revision.revision === receipt.accepted_revision,
    );
    if (
      !accepted ||
      !observed ||
      canonical(accepted.declaration) !== canonical(observed.declaration) ||
      (preview && canonical(preview.value.declaration) !== canonical(observed.declaration))
    )
      throw new Error("Gold revision readback mismatch");
    if (
      preview &&
      receipt.accepted_revision !==
        preview.intent.expected_revision + (preview.value.action === "noop" ? 0 : 1)
    )
      throw new Error("Gold accepted revision mismatch");
    queryClient.setQueryData(key, [saved]);
    sessionStorage.removeItem(storageKey);
    setPending(null);
    setPreview(null);
    setDirty(false);
    setFormOpen(false);
    setDraft(empty(accountId, instrumentId));
    setMessage(`История подтверждена независимым чтением: ревизия ${receipt.accepted_revision}.`);
    try {
      await onConfirmed?.();
    } catch {
      setError(
        "История подтверждена. Не удалось обновить общую сводку; обновите её перед использованием результата.",
      );
    }
  }
  async function recover() {
    if (!pending || busy) return;
    setBusy(true);
    setError("");
    try {
      await verify(await getGoldReceipt(pending), pending);
    } catch (cause) {
      setError(
        `Сохранение не подтверждено. Повторная отправка заблокирована. ${cause instanceof Error ? cause.message : "Ошибка чтения"}`,
      );
    } finally {
      setBusy(false);
    }
  }
  async function previewDraft() {
    setBusy(true);
    setError("");
    setMessage("");
    setPreview(null);
    const intent = structuredClone(draft);
    try {
      const value = await previewGoldHistory(intent);
      setPreview({ intent, value, revision });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Не удалось проверить историю");
    } finally {
      setBusy(false);
    }
  }
  async function confirm() {
    if (!preview || preview.revision !== revision || blocked || !preview.value.can_apply) return;
    const requestId = `gold_${crypto.randomUUID().replaceAll("-", "")}`;
    try {
      sessionStorage.setItem(storageKey, requestId);
    } catch {
      setError("Не удалось сохранить идентификатор проверки квитанции. Отправка не выполнена.");
      return;
    }
    setPending(requestId);
    setBusy(true);
    setError("");
    let acknowledged = false;
    try {
      const receipt = await applyGoldHistory(
        preview.intent,
        preview.value.confirmation_digest,
        requestId,
      );
      acknowledged = true;
      await verify(receipt, requestId);
    } catch (cause) {
      if (!acknowledged && cause instanceof ApiClientError && [409, 422].includes(cause.status)) {
        sessionStorage.removeItem(storageKey);
        setPending(null);
        setPreview(null);
        setError(`Изменение отклонено: ${cause.message}. Повторите чтение и предпросмотр.`);
      } else
        setError(
          "Сохранение не подтверждено. Повторная отправка заблокирована; проверьте квитанцию чтением.",
        );
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className={formStyles.history} aria-label="История золота владельца">
      <MonthNavigationGuard
        dirty={dirty}
        pending={blocked}
        onDiscard={() => {
          setDirty(false);
          setPreview(null);
        }}
      />
      <header className={formStyles.heading}>
        <h3>История операций</h3>
        {histories?.length === 0 && <p>История операций пока не сохранена.</p>}
      </header>
      {query.isError ? (
        <p role="alert">
          Не удалось прочитать историю.{" "}
          <Button type="button" onClick={() => void query.refetch()}>
            Повторить чтение истории
          </Button>
        </p>
      ) : query.isFetching ? (
        <p role="status">Читаем историю золота…</p>
      ) : null}
      {histories && histories.length > 1 && (
        <p role="alert">
          Найдено несколько историй для одной точной пары. Редактирование заблокировано.
        </p>
      )}
      {current && (
        <>
          <div className={formStyles.savedHeading}>
            <h4>Сохранённая история · ревизия {current.revision}</h4>
            <Button
              disabled={blocked || !current.events_loaded}
              aria-expanded={formOpen}
              onClick={() => {
                setFormOpen(true);
                setDraft(edit(current));
                setDirty(false);
                setPreview(null);
                setMessage("");
              }}
            >
              Исправить
            </Button>
          </div>
          <p>
            {current.currentness === "current"
              ? "Основа актуальна"
              : "Зависимости изменились; прежний результат не является актуальным"}{" "}
            · {formatDate(current.declaration.covered_from)} —{" "}
            {formatDate(current.declaration.covered_to)}
          </p>
          <Result value={current.result} valuation={current.valuation} clean={cleanResult} />
          <table className={formStyles.savedTable} aria-label="Сохранённые операции">
            <thead>
              <tr>
                <th scope="col">Дата</th>
                <th scope="col">Операция</th>
                <th scope="col">Граммы</th>
                <th scope="col">Сумма, ₽</th>
                <th scope="col">Комиссия</th>
              </tr>
            </thead>
            <tbody>
              {current.events.map((row) => (
                <tr key={row.event_id}>
                  <td data-label="Дата">{formatDate(row.event_date)}</td>
                  <td data-label="Операция">{row.side === "BUY" ? "Покупка" : "Продажа"}</td>
                  <td data-label="Граммы">{formatQuantity(row.grams)}</td>
                  <td data-label="Сумма, ₽">{money(row.amount_kopecks)}</td>
                  <td data-label="Комиссия">
                    {row.separate_fee_kopecks === null
                      ? "Неизвестна"
                      : money(row.separate_fee_kopecks)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      {message && <p role="status">{message}</p>}
      {error && <p role="alert">{error}</p>}
      {pending && (
        <p>
          Исход отправки требует чтения квитанции.{" "}
          <Button type="button" disabled={busy} onClick={() => void recover()}>
            Проверить результат сохранения
          </Button>
        </p>
      )}
      <details
        className={`${formStyles.editor} ${current ? formStyles.editorSaved : ""}`}
        open={formOpen}
        onToggle={(event) => setFormOpen(event.currentTarget.open)}
      >
        <summary>Ввести или исправить историю операций</summary>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void previewDraft();
          }}
        >
          <fieldset disabled={blocked || unavailable} className={formStyles.form}>
            <legend className={formStyles.visuallyHidden}>
              {draft.expected_revision
                ? "Полная новая ревизия истории"
                : "Новая история: заполните фактические сведения"}
            </legend>
            <div className={formStyles.headerFields}>
              <label htmlFor={`${formId}-from`}>
                С
                <Input
                  id={`${formId}-from`}
                  type="date"
                  required
                  aria-label="История с"
                  value={draft.covered_from}
                  onChange={(event) => change({ ...draft, covered_from: event.target.value })}
                />
              </label>
              <label htmlFor={`${formId}-to`}>
                По
                <Input
                  id={`${formId}-to`}
                  type="date"
                  required
                  aria-label="История по"
                  value={draft.covered_to}
                  onChange={(event) =>
                    change({
                      ...draft,
                      covered_to: event.target.value,
                      current_quantity_date: event.target.value,
                    })
                  }
                />
              </label>
              <label htmlFor={`${formId}-quantity`}>
                Остаток на конец, г
                <Input
                  id={`${formId}-quantity`}
                  required
                  inputMode="decimal"
                  pattern="(0|[1-9][0-9]{0,11})([.][0-9]{1,6})?"
                  title="Заявленное количество на конец истории, г"
                  aria-label="Заявленное количество на конец истории, г"
                  className="input--money"
                  value={draft.current_quantity}
                  onChange={(event) => change({ ...draft, current_quantity: event.target.value })}
                />
              </label>
              <label htmlFor={`${formId}-source`}>
                Источник
                <Input
                  id={`${formId}-source`}
                  required
                  maxLength={128}
                  title="Источник: документ или запись"
                  aria-label="Источник: документ или запись"
                  value={draft.provenance_reference}
                  onChange={(event) =>
                    change({
                      ...draft,
                      provenance_reference: event.target.value,
                    })
                  }
                />
              </label>
            </div>
            <div className={formStyles.checks}>
              <label htmlFor={`${formId}-complete`}>
                <Input
                  id={`${formId}-complete`}
                  type="checkbox"
                  checked={draft.complete}
                  onChange={(event) => change({ ...draft, complete: event.target.checked })}
                />
                История за указанный период полная
              </label>
              <label htmlFor={`${formId}-zero-start`}>
                <Input
                  id={`${formId}-zero-start`}
                  type="checkbox"
                  checked={draft.zero_start}
                  onChange={(event) => change({ ...draft, zero_start: event.target.checked })}
                />
                На начало периода золота не было
              </label>
            </div>
            {!!draft.expected_revision && (
              <label htmlFor={`${formId}-reason`}>
                Причина исправления
                <Input
                  id={`${formId}-reason`}
                  required
                  maxLength={500}
                  value={draft.change_reason ?? ""}
                  onChange={(event) => change({ ...draft, change_reason: event.target.value })}
                />
              </label>
            )}
            <div>
              <div className={formStyles.columns} aria-hidden="true">
                <span>Дата</span>
                <span>Операция</span>
                <span>Граммы</span>
                <span>Основа суммы</span>
                <span>Сумма, ₽</span>
                <span>Комиссия</span>
                <span />
              </div>
              {draft.events.map((row, index) => (
                <fieldset key={row.event_id} className={formStyles.operation}>
                  <legend className={formStyles.visuallyHidden}>Операция {index + 1}</legend>
                  <label htmlFor={`${formId}-${row.event_id}-date`}>
                    <span className={formStyles.fieldLabel}>Дата</span>
                    <Input
                      id={`${formId}-${row.event_id}-date`}
                      aria-label="Дата операции"
                      type="date"
                      required
                      value={row.event_date}
                      onChange={(event) => changeEvent(index, { event_date: event.target.value })}
                    />
                  </label>
                  <label htmlFor={`${formId}-${row.event_id}-side`}>
                    <span className={formStyles.fieldLabel}>Операция</span>
                    <Select
                      id={`${formId}-${row.event_id}-side`}
                      aria-label="Покупка или продажа"
                      value={row.side}
                      onChange={(event) =>
                        changeEvent(index, {
                          side: event.target.value as GoldEventInput["side"],
                        })
                      }
                    >
                      <option value="BUY">Покупка</option>
                      <option value="SELL">Продажа</option>
                    </Select>
                  </label>
                  <label htmlFor={`${formId}-${row.event_id}-grams`}>
                    <span className={formStyles.fieldLabel}>Граммы</span>
                    <Input
                      id={`${formId}-${row.event_id}-grams`}
                      required
                      inputMode="decimal"
                      pattern="(0|[1-9][0-9]{0,11})([.][0-9]{1,6})?"
                      aria-label="Граммы"
                      value={row.grams}
                      onChange={(event) => changeEvent(index, { grams: event.target.value })}
                    />
                  </label>
                  <label htmlFor={`${formId}-${row.event_id}-basis`}>
                    <span className={formStyles.fieldLabel}>Основа суммы</span>
                    <Select
                      id={`${formId}-${row.event_id}-basis`}
                      aria-label="Основа суммы"
                      value={row.amount_basis}
                      onChange={(event) =>
                        changeEvent(index, {
                          amount_basis: event.target.value as GoldEventInput["amount_basis"],
                          amount_rub: event.target.value === "actual" ? "" : null,
                          unit_price_rub: event.target.value === "derived_unit_price" ? "" : null,
                        })
                      }
                    >
                      <option value="actual">Сумма сделки</option>
                      <option value="derived_unit_price">Цена за грамм</option>
                    </Select>
                  </label>
                  <label htmlFor={`${formId}-${row.event_id}-amount`} className={formStyles.amount}>
                    <span
                      className={row.amount_basis === "actual" ? formStyles.fieldLabel : undefined}
                    >
                      {row.amount_basis === "actual" ? "Сумма, ₽" : "Цена, ₽/г"}
                    </span>
                    <Input
                      id={`${formId}-${row.event_id}-amount`}
                      className="input--money"
                      aria-label={
                        row.amount_basis === "actual"
                          ? "Сумма операции без отдельной комиссии, ₽"
                          : "Цена за грамм без отдельной комиссии, ₽"
                      }
                      required
                      inputMode="decimal"
                      pattern="(0|[1-9][0-9]{0,13})([.][0-9]{1,2})?"
                      value={
                        (row.amount_basis === "actual" ? row.amount_rub : row.unit_price_rub) ?? ""
                      }
                      onChange={(event) =>
                        changeEvent(
                          index,
                          row.amount_basis === "actual"
                            ? { amount_rub: event.target.value }
                            : { unit_price_rub: event.target.value },
                        )
                      }
                    />
                  </label>
                  <div className={formStyles.fee}>
                    <label htmlFor={`${formId}-${row.event_id}-fee-state`}>
                      <span className={formStyles.fieldLabel}>Комиссия</span>
                      <Select
                        id={`${formId}-${row.event_id}-fee-state`}
                        aria-label="Отдельная комиссия"
                        value={row.fee_state}
                        onChange={(event) =>
                          changeEvent(index, {
                            fee_state: event.target.value as GoldEventInput["fee_state"],
                            fee_rub: event.target.value === "known" ? "" : null,
                          })
                        }
                      >
                        <option value="unknown">Неизвестна</option>
                        <option value="known_zero">Нет · 0 ₽</option>
                        <option value="known">Известная сумма</option>
                      </Select>
                    </label>
                    {row.fee_state === "known" && (
                      <label htmlFor={`${formId}-${row.event_id}-fee-amount`}>
                        <span className={formStyles.visuallyHidden}>Сумма комиссии, ₽</span>
                        <Input
                          id={`${formId}-${row.event_id}-fee-amount`}
                          required
                          inputMode="decimal"
                          className="input--money"
                          placeholder="Сумма, ₽"
                          value={row.fee_rub ?? ""}
                          onChange={(event) => changeEvent(index, { fee_rub: event.target.value })}
                        />
                      </label>
                    )}
                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    className={formStyles.remove}
                    aria-label={`Удалить операцию ${index + 1}`}
                    title={
                      draft.events.length === 1
                        ? "В истории должна остаться хотя бы одна операция"
                        : `Удалить операцию ${index + 1}`
                    }
                    disabled={draft.events.length === 1}
                    onClick={() =>
                      change({
                        ...draft,
                        events: draft.events.filter((_, rowIndex) => rowIndex !== index),
                      })
                    }
                  >
                    <span aria-hidden="true">×</span>
                  </Button>
                </fieldset>
              ))}
            </div>
            <Button
              type="button"
              variant="ghost"
              className={formStyles.add}
              disabled={draft.events.length >= 100}
              onClick={() => change({ ...draft, events: [...draft.events, event()] })}
            >
              Добавить операцию
            </Button>
            <div>
              <p className={formStyles.hint}>
                Сумма сделки — без отдельной комиссии; комиссию укажите отдельно.
              </p>
              <details className={formStyles.help}>
                <summary>Как считать сумму</summary>
                <p>
                  Сумма сделки или граммы × цена — без отдельно уплаченной комиссии. Для продажи
                  укажите полную сумму сделки, а не поступление после удержания комиссии. Комиссию
                  укажите отдельно: известный ноль, известная сумма или неизвестно. Неизвестная
                  комиссия не считается нулевой. Налоги не выводятся автоматически.
                </p>
              </details>
            </div>
            <div className={formStyles.actions}>
              <Button type="submit" variant="primary">
                Предпросмотр истории
              </Button>
            </div>
          </fieldset>
        </form>
      </details>
      {preview && preview.revision === revision && !refreshing && !query.isFetching && (
        <section aria-label="Предпросмотр истории золота">
          <h4>
            Предпросмотр:{" "}
            {preview.value.action === "create"
              ? "создание"
              : preview.value.action === "revise"
                ? "исправление"
                : "без изменения сведений"}
          </h4>
          <p>
            {formatDate(preview.value.declaration.covered_from)} —{" "}
            {formatDate(preview.value.declaration.covered_to)} ·{" "}
            {preview.value.declaration.events.length} операций
          </p>
          <Result
            value={preview.value.result}
            valuation={preview.value.valuation}
            clean={preview.value.clean_result}
          />
          <Button
            type="button"
            disabled={blocked || !preview.value.can_apply}
            onClick={() => void confirm()}
          >
            Подтвердить сохранение истории
          </Button>
        </section>
      )}
    </section>
  );
}
