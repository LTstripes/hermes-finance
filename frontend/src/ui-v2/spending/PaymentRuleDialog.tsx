import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { MonthNavigationGuard } from "../MonthNavigationGuard";
import { formatApiError } from "../../api/client";
import {
  paymentApi,
  type PaymentCard,
  type PaymentEdit,
  type PaymentRule,
  type Purchase,
} from "../../api/spendingPayments";
import { Button } from "../../components/ui";
import { formatMoney } from "../../lib/format";
import styles from "./Spending.module.css";

function initialEdit(card: PaymentCard): PaymentEdit {
  const r = card.rule;
  return {
    note: r?.note ?? "",
    mandatory_override: r?.mandatory_override ?? null,
    repeat: r?.repeat ?? false,
    period_months: r?.period_months ?? null,
    next_due: r?.next_due ?? null,
    amount: r?.amount ?? null,
  };
}

function PaymentForm({
  purchase,
  initial,
  detached,
  suggestedRuleId,
  onClose,
  protect,
}: {
  purchase: Purchase;
  initial: PaymentCard;
  detached: PaymentRule[];
  suggestedRuleId?: number;
  onClose: () => void;
  protect: (dirty: boolean, pending: boolean) => void;
}) {
  const cache = useQueryClient();
  const [saved, setSaved] = useState(initial);
  const ownedRule = saved.rule;
  const [draft, setDraft] = useState(() => initialEdit(initial));
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [attach, setAttach] = useState("");
  const [scheduleId, setScheduleId] = useState(() =>
    initial.schedules.some((s) => s.id === suggestedRuleId) ? String(suggestedRuleId) : "",
  );
  const chosenSchedule = saved.schedules.find((s) => String(s.id) === scheduleId);
  function record(decision: "payment" | "separate") {
    if (chosenSchedule)
      void write(() =>
        paymentApi.occurrence(
          purchase,
          saved.token,
          chosenSchedule.id,
          chosenSchedule.version,
          decision,
        ),
      );
  }
  const running = useRef(false);
  const dirty = JSON.stringify(initialEdit(saved)) !== JSON.stringify(draft);
  useEffect(() => protect(dirty, pending), [dirty, pending, protect]);
  const update = (values: Partial<PaymentEdit>) => {
    setDraft((old) => ({ ...old, ...values }));
    setStatus("");
  };
  async function write(action: () => Promise<PaymentCard>) {
    if (running.current) return;
    running.current = true;
    setPending(true);
    setError("");
    setStatus("");
    let acknowledged = false;
    try {
      const response = await action();
      acknowledged = true;
      const current = await paymentApi.card(purchase);
      if (current.token !== response.token)
        throw new Error("Карточка уже изменилась. Откройте её ещё раз.");
      setSaved(current);
      setDraft(initialEdit(current));
      setAttach("");
      setScheduleId("");
      setStatus("Сохранено");
    } catch (cause) {
      setError(
        acknowledged
          ? "Запись принята. Закройте и откройте карточку для повторной проверки."
          : formatApiError(cause),
      );
    } finally {
      running.current = false;
      setPending(false);
      await cache.invalidateQueries({ queryKey: ["spending", "payment-rules", purchase.month] });
      await cache.invalidateQueries({ queryKey: ["spending", "reserve"] });
    }
  }
  function submit(event: FormEvent) {
    event.preventDefault();
    void write(() =>
      paymentApi.save(purchase, saved.token, {
        ...draft,
        amount: draft.amount?.trim().replace(",", ".") || null,
      }),
    );
  }
  return (
    <form onSubmit={submit} className={styles.paymentForm}>
      <MonthNavigationGuard dirty={dirty} pending={pending} />
      <h2 id="payment-card-title">{saved.title}</h2>
      <p>Оплачено {formatMoney(saved.fact_amount)}</p>
      <fieldset disabled={pending}>
        <label>
          Моя заметка
          <textarea
            maxLength={2000}
            rows={2}
            value={draft.note}
            onChange={(e) => update({ note: e.target.value })}
          />
        </label>
        <label>
          Обязательность для бюджета
          <select
            value={
              draft.mandatory_override === null ? "category" : String(draft.mandatory_override)
            }
            onChange={(e) =>
              update({
                mandatory_override:
                  e.target.value === "category" ? null : e.target.value === "true",
              })
            }
          >
            <option value="category">
              По категории · {saved.category_mandatory ? "обязательная" : "необязательная"}
            </option>
            <option value="true">Обязательная</option>
            <option value="false">Необязательная</option>
          </select>
        </label>
        <label className={styles.paymentCheck}>
          <input
            type="checkbox"
            checked={draft.repeat}
            onChange={(e) =>
              update(
                e.target.checked
                  ? { repeat: true, amount: saved.fact_amount }
                  : { repeat: false, period_months: null, next_due: null, amount: null },
              )
            }
          />
          Планирую повторять
        </label>
        {draft.repeat && (
          <>
            <label>
              Интервал, месяцев
              <input
                type="number"
                min="1"
                max="120"
                step="1"
                placeholder="Пока неизвестно"
                value={draft.period_months ?? ""}
                onChange={(e) =>
                  update({ period_months: e.target.value ? Number(e.target.value) : null })
                }
              />
            </label>
            <label>
              Следующая оплата
              <input
                type="date"
                value={draft.next_due ?? ""}
                onChange={(e) => update({ next_due: e.target.value || null })}
              />
            </label>
            <label>
              Ожидаемая сумма, ₽
              <input
                type="text"
                inputMode="decimal"
                placeholder="Пока неизвестно"
                value={draft.amount ?? ""}
                onChange={(e) => update({ amount: e.target.value || null })}
              />
            </label>
          </>
        )}
        {saved.rule?.repeat && !dirty && (
          <p>
            В среднем за месяц ·{" "}
            {saved.rule.monthly_amount === null
              ? "пока неизвестно"
              : formatMoney(saved.rule.monthly_amount)}
          </p>
        )}
        {(saved.schedules.length > 0 || saved.decisions.length > 0) && (
          <section>
            <h3>Связь с графиком</h3>
            {saved.decisions.map((d) => (
              <p key={d.id}>
                {d.needs_review
                  ? "Требует сверки"
                  : d.decision === "payment"
                    ? "Оплачено по графику"
                    : "Самостоятельная покупка"}{" "}
                · {d.rule_title}{" "}
                <Button
                  type="button"
                  disabled={dirty}
                  onClick={() =>
                    void write(() =>
                      paymentApi.undoOccurrence(purchase, saved.token, d.id, d.rule_version),
                    )
                  }
                >
                  Отменить решение
                </Button>
              </p>
            ))}
            {saved.schedules.length > 0 && (
              <>
                <label>
                  Существующий график
                  <select value={scheduleId} onChange={(e) => setScheduleId(e.target.value)}>
                    <option value="">Выберите график</option>
                    {saved.schedules.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.title} · {s.month} ·{" "}
                        {s.amount ? formatMoney(s.amount) : "Сумма неизвестна"}
                        {s.repeat ? "" : " · продление отключено"} · №{s.id}
                      </option>
                    ))}
                  </select>
                </label>
                <div className={styles.actions}>
                  <Button
                    type="button"
                    disabled={
                      dirty ||
                      !chosenSchedule ||
                      Boolean(saved.rule?.was_recurring) ||
                      saved.decisions.some(
                        (d) => d.decision === "payment" && d.rule_id !== chosenSchedule?.id,
                      )
                    }
                    onClick={() => record("payment")}
                  >
                    Уже оплачено по этому графику
                  </Button>
                  <Button
                    type="button"
                    disabled={dirty || !chosenSchedule}
                    onClick={() => record("separate")}
                  >
                    Самостоятельная покупка
                  </Button>
                </div>
              </>
            )}
          </section>
        )}
        {ownedRule && ownedRule.occurrences.length > 0 && (
          <section>
            <h3>Решения по покупкам этого графика</h3>
            {ownedRule.occurrences.map((o) => (
              <p key={o.id}>
                {o.month} · {o.title} ·{" "}
                {o.needs_review
                  ? "Требует сверки"
                  : o.decision === "payment"
                    ? "Оплачено"
                    : "Самостоятельная покупка"}{" "}
                <Button
                  type="button"
                  disabled={dirty}
                  onClick={() =>
                    void write(() =>
                      paymentApi.undoOccurrence(purchase, saved.token, o.id, ownedRule.version),
                    )
                  }
                >
                  Отменить решение
                </Button>
              </p>
            ))}
          </section>
        )}
        {!saved.rule && detached.length > 0 && (
          <div>
            <label>
              Восстановить прежнюю пометку
              <select value={attach} onChange={(e) => setAttach(e.target.value)}>
                <option value="">Выберите пометку</option>
                {detached.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.title} · {r.note || "Без заметки"} · №{r.id}
                  </option>
                ))}
              </select>
            </label>
            <Button
              type="button"
              disabled={!attach || dirty}
              onClick={() => {
                const r = detached.find((item) => String(item.id) === attach);
                if (r) void write(() => paymentApi.reattach(purchase, saved.token, r));
              }}
            >
              Связать с этой покупкой
            </Button>
          </div>
        )}
      </fieldset>
      {error && <p role="alert">{error}</p>}
      {status && <p role="status">{status}</p>}
      <div className={styles.actions}>
        <Button type="submit" disabled={!dirty || pending}>
          Сохранить
        </Button>
        <Button type="button" disabled={pending} onClick={onClose}>
          Закрыть
        </Button>
      </div>
    </form>
  );
}

export function PaymentRuleDialog({
  purchase,
  detached,
  suggestedRuleId,
  onClose,
}: {
  purchase: Purchase;
  detached: PaymentRule[];
  suggestedRuleId?: number;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const guard = useRef({ dirty: false, pending: false });
  const protect = useRef((dirty: boolean, pending: boolean) => {
    guard.current = { dirty, pending };
  }).current;
  useEffect(() => {
    const node = dialog.current;
    node?.showModal();
    return () => node?.close();
  }, []);
  function close() {
    if (
      !guard.current.pending &&
      (!guard.current.dirty || window.confirm("Закрыть без сохранения изменений?"))
    )
      onClose();
  }
  const query = useQuery({
    queryKey: ["spending", "payment-card", purchase.month, purchase.source, purchase.id],
    queryFn: ({ signal }) => paymentApi.card(purchase, signal),
    staleTime: 0,
    gcTime: 0,
  });
  return (
    <dialog
      ref={dialog}
      className={styles.paymentDialog}
      aria-label="Карточка покупки"
      onCancel={(e) => {
        e.preventDefault();
        close();
      }}
    >
      {query.isError ? (
        <>
          <p role="alert">{formatApiError(query.error)}</p>
          <Button onClick={() => void query.refetch()}>Повторить</Button>
          <Button onClick={close}>Закрыть</Button>
        </>
      ) : !query.data ? (
        <p>Загружаем карточку…</p>
      ) : (
        <PaymentForm
          purchase={purchase}
          initial={query.data}
          detached={detached}
          suggestedRuleId={suggestedRuleId}
          onClose={close}
          protect={protect}
        />
      )}
    </dialog>
  );
}
