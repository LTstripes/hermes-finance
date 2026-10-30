import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiClientError } from "../../api/client";
import { fromKopecks } from "../../lib/money";
import { MonthNavigationGuard } from "../MonthNavigationGuard";
import { money } from "../SourceInstrumentDetail";
import {
  applyGoldHistory,
  checkGoldHistory,
  getGoldHistories,
  getGoldHistory,
  getGoldReceipt,
  GOLD_VERSION,
  goldPendingKey,
  previewGoldHistory,
  type GoldEventInput,
  type GoldHistory,
  type GoldIntent,
  type GoldPreview,
  type GoldReceipt,
  type GoldResult,
  type GoldValuation,
} from "./goldHistory";
import styles from "./Returns.module.css";
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
function Result({ value, valuation }: { value: GoldResult; valuation: GoldValuation | null }) {
  return (
    <div>
      <dl className={styles.goldFacts}>
        <dt>Общий результат</dt>
        <dd>{money(value.total_result_kopecks)}</dd>
        <dt>Реализованный результат</dt>
        <dd>{money(value.realized_result_kopecks)}</dd>
        <dt>Нереализованный результат</dt>
        <dd>{money(value.unrealized_result_kopecks)}</dd>
        <dt>Остаток затрат</dt>
        <dd>{money(value.remaining_cost_kopecks)}</dd>
        <dt>Отдельные комиссии</dt>
        <dd>{money(value.separate_fees_kopecks)}</dd>
      </dl>
      <p>
        Расчётный интервал: {value.period.covered_from} —{" "}
        {value.period.covered_to ?? "граница не подтверждена"}; операции учтены по{" "}
        {value.as_of_date}. Оценка на {value.valuation_date ?? "неподтверждённую дату"};{" "}
        {value.valuation_basis === "owner_declared_zero_quantity"
          ? "заявленное нулевое количество"
          : value.valuation_basis === "saved_snapshot_quote"
            ? "сохранённая цена"
            : "оценка не подтверждена"}
        .
      </p>
      <p>
        Налоги не предоставлены. Основа сумм:{" "}
        {value.amount_basis === "actual"
          ? "фактические суммы операций"
          : "есть суммы, выведенные из цены за грамм"}
        .
      </p>
      <p>
        {valuation
          ? `Сохранённая оценка: ${money(valuation.market_value_kopecks)} на ${valuation.date}; снимок отчёта ${valuation.snapshot_date}; цена на ${valuation.price_date}; количество ${valuation.quantity} г.`
          : "Подходящая сохранённая оценка недоступна."}
      </p>
      {(valuation?.provisional ||
        valuation?.month_status === "draft" ||
        value.valuation_provisional) && (
        <p>
          Предварительная оценка из DRAFT: сохранённая котировка на{" "}
          {valuation?.price_date ?? value.valuation_date}. Это наблюдение чернового месяца, а не
          принятый финансовый Close.
        </p>
      )}
      {!!value.reason_codes.length && (
        <details>
          <summary>Ограничения результата</summary>
          <code>{value.reason_codes.join(", ")}</code>
        </details>
      )}
    </div>
  );
}
export function ReturnsGoldHistory({
  accountId,
  instrumentId,
  onConfirmed,
}: {
  accountId: number;
  instrumentId: number;
  onConfirmed?: () => Promise<unknown>;
}) {
  const queryClient = useQueryClient();
  const key = ["returns", "gold-history", accountId, instrumentId];
  const storageKey = goldPendingKey(accountId, instrumentId);
  const query = useQuery({
    queryKey: key,
    queryFn: ({ signal }) => getGoldHistories(accountId, instrumentId, signal),
    staleTime: 0,
  });
  const [draft, setDraft] = useState(() => empty(accountId, instrumentId));
  const [dirty, setDirty] = useState(false);
  const [formOpen, setFormOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<{ intent: GoldIntent; value: GoldPreview } | null>(null);
  const [pending, setPending] = useState<string | null>(() => sessionStorage.getItem(storageKey));
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const histories = !query.isFetching && !query.isError ? query.data : undefined;
  const current = histories?.length === 1 ? histories[0] : null;
  const blocked = busy || pending !== null;
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
      setPreview({ intent, value });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Не удалось проверить историю");
    } finally {
      setBusy(false);
    }
  }
  async function confirm() {
    if (!preview || blocked || !preview.value.can_apply) return;
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
    <section className={styles.goldHistory} aria-label="История золота владельца">
      <MonthNavigationGuard
        dirty={dirty}
        pending={blocked}
        onDiscard={() => {
          setDirty(false);
          setPreview(null);
        }}
      />
      <h3>История покупок и продаж золота</h3>
      <p>
        Отдельный источник сведений владельца для выбранного счёта и инструмента. Закрытые месяцы не
        редактируются. Оценка берётся из сохранённого снимка; новой цены здесь нет.
      </p>
      {query.isError ? (
        <p role="alert">
          Не удалось прочитать историю.{" "}
          <button type="button" onClick={() => void query.refetch()}>
            Повторить чтение истории
          </button>
        </p>
      ) : query.isFetching ? (
        <p role="status">Читаем историю золота…</p>
      ) : null}
      {histories?.length === 0 && <p>История операций пока не сохранена.</p>}
      {histories && histories.length > 1 && (
        <p role="alert">
          Найдено несколько историй для одной точной пары. Редактирование заблокировано.
        </p>
      )}
      {current && (
        <>
          <h4>Сохранённая история · ревизия {current.revision}</h4>
          <p>
            {current.currentness === "current"
              ? "Основа актуальна"
              : "Зависимости изменились; прежний результат не является актуальным"}{" "}
            · {current.declaration.covered_from} — {current.declaration.covered_to}
          </p>
          <Result value={current.result} valuation={current.valuation} />
          <details>
            <summary>Сохранённые операции ({current.events.length})</summary>
            <ul>
              {current.events.map((row) => (
                <li key={row.event_id}>
                  {row.event_date} · {row.side === "BUY" ? "Покупка" : "Продажа"} · {row.grams} г ·{" "}
                  {money(row.amount_kopecks)} · комиссия {money(row.separate_fee_kopecks)}
                </li>
              ))}
            </ul>
          </details>
          <button
            type="button"
            disabled={blocked || !current.events_loaded}
            onClick={() => {
              setFormOpen(true);
              setDraft(edit(current));
              setDirty(false);
              setPreview(null);
              setMessage("");
            }}
          >
            Изменить сохранённую историю
          </button>
        </>
      )}
      {message && <p role="status">{message}</p>}
      {error && <p role="alert">{error}</p>}
      {pending && (
        <p>
          Исход отправки требует чтения квитанции.{" "}
          <button type="button" disabled={busy} onClick={() => void recover()}>
            Проверить результат сохранения
          </button>
        </p>
      )}
      <details open={formOpen} onToggle={(event) => setFormOpen(event.currentTarget.open)}>
        <summary>Ввести или исправить историю операций</summary>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void previewDraft();
          }}
        >
          <fieldset disabled={blocked || unavailable} className={styles.goldForm}>
            <legend>
              {draft.expected_revision
                ? "Полная новая ревизия истории"
                : "Новая история: заполните фактические сведения"}
            </legend>
            <label>
              История с
              <input
                type="date"
                required
                value={draft.covered_from}
                onChange={(event) => change({ ...draft, covered_from: event.target.value })}
              />
            </label>
            <label>
              История по
              <input
                type="date"
                required
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
            <label>
              Заявленное количество на конец истории, г
              <input
                required
                inputMode="decimal"
                pattern="(0|[1-9][0-9]{0,11})([.][0-9]{1,6})?"
                value={draft.current_quantity}
                onChange={(event) => change({ ...draft, current_quantity: event.target.value })}
              />
            </label>
            <label>
              Источник: документ или запись
              <input
                required
                maxLength={128}
                value={draft.provenance_reference}
                onChange={(event) => change({ ...draft, provenance_reference: event.target.value })}
              />
            </label>
            <label>
              <input
                type="checkbox"
                checked={draft.complete}
                onChange={(event) => change({ ...draft, complete: event.target.checked })}
              />
              История за указанный период полная
            </label>
            <label>
              <input
                type="checkbox"
                checked={draft.zero_start}
                onChange={(event) => change({ ...draft, zero_start: event.target.checked })}
              />
              На начало периода золота не было
            </label>
            {!!draft.expected_revision && (
              <label>
                Причина исправления
                <input
                  required
                  maxLength={500}
                  value={draft.change_reason ?? ""}
                  onChange={(event) => change({ ...draft, change_reason: event.target.value })}
                />
              </label>
            )}
            {draft.events.map((row, index) => (
              <fieldset key={row.event_id} className={styles.goldOperation}>
                <legend>Операция {index + 1}</legend>
                <label>
                  Дата операции
                  <input
                    type="date"
                    required
                    value={row.event_date}
                    onChange={(event) => changeEvent(index, { event_date: event.target.value })}
                  />
                </label>
                <label>
                  Покупка или продажа
                  <select
                    value={row.side}
                    onChange={(event) =>
                      changeEvent(index, { side: event.target.value as GoldEventInput["side"] })
                    }
                  >
                    <option value="BUY">Покупка</option>
                    <option value="SELL">Продажа</option>
                  </select>
                </label>
                <label>
                  Граммы
                  <input
                    required
                    inputMode="decimal"
                    pattern="(0|[1-9][0-9]{0,11})([.][0-9]{1,6})?"
                    value={row.grams}
                    onChange={(event) => changeEvent(index, { grams: event.target.value })}
                  />
                </label>
                <label>
                  Основа суммы
                  <select
                    value={row.amount_basis}
                    onChange={(event) =>
                      changeEvent(index, {
                        amount_basis: event.target.value as GoldEventInput["amount_basis"],
                        amount_rub: event.target.value === "actual" ? "" : null,
                        unit_price_rub: event.target.value === "derived_unit_price" ? "" : null,
                      })
                    }
                  >
                    <option value="actual">Фактическая сумма</option>
                    <option value="derived_unit_price">Цена за грамм — производная сумма</option>
                  </select>
                </label>
                <label>
                  {row.amount_basis === "actual"
                    ? "Сумма операции без отдельной комиссии, ₽"
                    : "Цена за грамм без отдельной комиссии, ₽"}
                  <input
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
                <label>
                  Отдельная комиссия
                  <select
                    value={row.fee_state}
                    onChange={(event) =>
                      changeEvent(index, {
                        fee_state: event.target.value as GoldEventInput["fee_state"],
                        fee_rub: event.target.value === "known" ? "" : null,
                      })
                    }
                  >
                    <option value="unknown">Неизвестна</option>
                    <option value="known_zero">Известно, что комиссии нет</option>
                    <option value="known">Известная сумма</option>
                  </select>
                </label>
                {row.fee_state === "known" && (
                  <label>
                    Сумма комиссии, ₽
                    <input
                      required
                      inputMode="decimal"
                      value={row.fee_rub ?? ""}
                      onChange={(event) => changeEvent(index, { fee_rub: event.target.value })}
                    />
                  </label>
                )}
                <button
                  type="button"
                  disabled={draft.events.length === 1}
                  onClick={() =>
                    change({
                      ...draft,
                      events: draft.events.filter((_, rowIndex) => rowIndex !== index),
                    })
                  }
                >
                  Удалить операцию
                </button>
              </fieldset>
            ))}
            <p>
              Сумма сделки или граммы × цена — без отдельно уплаченной комиссии. Для продажи укажите
              полную сумму сделки, а не поступление после удержания комиссии. Комиссию укажите
              отдельно: известный ноль, известная сумма или неизвестно. Неизвестная комиссия не
              считается нулевой. Налоги не выводятся автоматически.
            </p>
            <button
              type="button"
              disabled={draft.events.length >= 100}
              onClick={() => change({ ...draft, events: [...draft.events, event()] })}
            >
              Добавить операцию
            </button>
            <button type="submit">Предпросмотр истории</button>
          </fieldset>
        </form>
      </details>
      {preview && (
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
            {preview.value.declaration.covered_from} — {preview.value.declaration.covered_to} ·{" "}
            {preview.value.declaration.events.length} операций
          </p>
          <Result value={preview.value.result} valuation={preview.value.valuation} />
          <button
            type="button"
            disabled={blocked || !preview.value.can_apply}
            onClick={() => void confirm()}
          >
            Подтвердить сохранение истории
          </button>
        </section>
      )}
    </section>
  );
}
