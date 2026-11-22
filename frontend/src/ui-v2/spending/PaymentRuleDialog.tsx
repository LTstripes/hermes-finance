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
import { Button, ConfirmDialog, Field, Input, Select } from "../../components/ui";
import { formatMoney, formatMonthKey } from "../../lib/format";
import { MonthMoneyInput } from "../MonthMoneyInput";
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
      <header className={styles.paymentHeader}>
        <div>
          <h2 id="payment-card-title">{saved.title}</h2>
          <p>
            Оплачено <span className="num">{formatMoney(saved.fact_amount)}</span>
          </p>
        </div>
        <Button
          type="button"
          variant="ghost"
          aria-label="Закрыть карточку покупки"
          disabled={pending}
          onClick={onClose}
        >
          ×
        </Button>
      </header>
      <fieldset disabled={pending}>
        <Field htmlFor="payment-note" label="Моя заметка">
          <textarea
            className="input"
            id="payment-note"
            maxLength={2000}
            rows={2}
            value={draft.note}
            onChange={(e) => update({ note: e.target.value })}
          />
        </Field>
        <Field htmlFor="payment-mandatory" label="Обязательность для бюджета">
          <Select
            id="payment-mandatory"
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
          </Select>
        </Field>
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
          <div className={styles.scheduleFields}>
            <Field htmlFor="payment-period" label="Интервал, месяцев">
              <Input
                id="payment-period"
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
            </Field>
            <Field htmlFor="payment-due" label="Следующая оплата">
              <Input
                id="payment-due"
                type="date"
                value={draft.next_due ?? ""}
                onChange={(e) => update({ next_due: e.target.value || null })}
              />
            </Field>
            <Field htmlFor="payment-amount" label="Ожидаемая сумма, ₽">
              <MonthMoneyInput
                id="payment-amount"
                placeholder="Пока неизвестно"
                value={draft.amount ?? ""}
                onChange={(amount) => update({ amount: amount || null })}
              />
            </Field>
          </div>
        )}
        {saved.rule?.repeat && !dirty && (
          <p className={styles.averageAmount}>
            В среднем за месяц ·{" "}
            <span className="num">
              {saved.rule.monthly_amount === null
                ? "пока неизвестно"
                : formatMoney(saved.rule.monthly_amount)}
            </span>
          </p>
        )}
        {(saved.schedules.length > 0 || saved.decisions.length > 0) && (
          <section className={styles.paymentSection}>
            <h3>Связь с графиком</h3>
            {saved.decisions.map((d) => (
              <div key={d.id} className={styles.decisionRow}>
                <span>
                  {d.needs_review
                    ? "Требует сверки"
                    : d.decision === "payment"
                      ? "Оплачено по графику"
                      : "Самостоятельная покупка"}{" "}
                  · {d.rule_title}
                </span>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  disabled={dirty}
                  onClick={() =>
                    void write(() =>
                      paymentApi.undoOccurrence(purchase, saved.token, d.id, d.rule_version),
                    )
                  }
                >
                  Отменить решение
                </Button>
              </div>
            ))}
            {saved.schedules.length > 0 && (
              <>
                <Field htmlFor="payment-schedule" label="Существующий график">
                  <Select
                    id="payment-schedule"
                    value={scheduleId}
                    onChange={(e) => setScheduleId(e.target.value)}
                  >
                    <option value="">Выберите график</option>
                    {saved.schedules.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.title} · {formatMonthKey(s.month)} ·{" "}
                        {s.amount ? formatMoney(s.amount) : "Сумма неизвестна"}
                        {s.repeat ? "" : " · продление отключено"}
                      </option>
                    ))}
                  </Select>
                </Field>
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
                    variant="ghost"
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
          <section className={styles.paymentSection}>
            <h3>Решения по покупкам этого графика</h3>
            {ownedRule.occurrences.map((o) => (
              <div key={o.id} className={styles.decisionRow}>
                <span>
                  {formatMonthKey(o.month)} · {o.title} ·{" "}
                  {o.needs_review
                    ? "Требует сверки"
                    : o.decision === "payment"
                      ? "Оплачено"
                      : "Самостоятельная покупка"}
                </span>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  disabled={dirty}
                  onClick={() =>
                    void write(() =>
                      paymentApi.undoOccurrence(purchase, saved.token, o.id, ownedRule.version),
                    )
                  }
                >
                  Отменить решение
                </Button>
              </div>
            ))}
          </section>
        )}
        {!saved.rule && detached.length > 0 && (
          <div>
            <Field htmlFor="payment-attach" label="Восстановить прежнюю пометку">
              <Select
                id="payment-attach"
                value={attach}
                onChange={(e) => setAttach(e.target.value)}
              >
                <option value="">Выберите пометку</option>
                {detached.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.title} · {r.note || "Без заметки"}
                  </option>
                ))}
              </Select>
            </Field>
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
      {error && (
        <p className="inline-alert inline-alert--error" role="alert">
          {error}
        </p>
      )}
      {status && (
        <p className="inline-alert inline-alert--ok" role="status">
          {status}
        </p>
      )}
      <div className={styles.dialogActions}>
        <Button type="button" variant="ghost" disabled={pending} onClick={onClose}>
          Закрыть
        </Button>
        <Button type="submit" variant="primary" disabled={!dirty || pending}>
          Сохранить
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
  const [discard, setDiscard] = useState(false);
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
    if (guard.current.pending) return;
    if (guard.current.dirty) setDiscard(true);
    else onClose();
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
      onKeyDownCapture={(event) => {
        if (discard && event.key === "Escape") {
          event.preventDefault();
          event.stopPropagation();
          setDiscard(false);
        }
      }}
      onCancel={(e) => {
        e.preventDefault();
        close();
      }}
    >
      <div inert={discard}>
        {query.isError ? (
          <>
            <p className="inline-alert inline-alert--error" role="alert">
              {formatApiError(query.error)}
            </p>
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
      </div>
      <ConfirmDialog
        open={discard}
        title="Закрыть без сохранения?"
        description="Изменения в карточке покупки будут потеряны."
        cancelLabel="Продолжить редактирование"
        confirmLabel="Закрыть без сохранения"
        onCancel={() => setDiscard(false)}
        onConfirm={onClose}
      />
    </dialog>
  );
}
