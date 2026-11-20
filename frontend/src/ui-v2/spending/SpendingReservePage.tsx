import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { formatApiError } from "../../api/client";
import {
  getReserve,
  putReserve,
  type ReservePlan,
  type ReserveView,
} from "../../api/spendingReserve";
import { Button, Table, Td, Th } from "../../components/ui";
import { formatMonthKey } from "../../lib/format";
import { MonthNavigationGuard } from "../MonthNavigationGuard";
import { UiV2Shell } from "../UiV2Shell";
import { UiV2Loading, UiV2WidgetState } from "../UiV2StateBlocks";
import sheet from "../ReportSheet.module.css";
import { Money, Section, shortDate } from "./common";
import { ExpenseTabs } from "./ExpenseTabs";
import styles from "./Spending.module.css";

const queryKey = ["spending", "reserve"];
const currencyPattern = "[0-9]{1,14}([.,][0-9]{1,2})?";
function ReserveSettings({ data }: { data: ReserveView }) {
  const client = useQueryClient();
  const [draft, setDraft] = useState<{ revision: number; plan: ReservePlan } | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [month, setMonth] = useState("");
  const plan = draft?.plan ?? data.plan;
  function change(update: Partial<ReservePlan>) {
    setDraft({ revision: draft?.revision ?? data.revision, plan: { ...plan, ...update } });
    setError("");
    setNotice("");
  }
  async function save(event: FormEvent) {
    event.preventDefault();
    if (!draft || pending) return;
    setPending(true);
    setError("");
    setNotice("");
    try {
      const ack = await putReserve(plan, draft.revision);
      const read = await getReserve();
      client.setQueryData(queryKey, read);
      if (read.revision !== ack.revision || JSON.stringify(read.plan) !== JSON.stringify(ack.plan))
        throw new Error("План изменился после сохранения.");
      setDraft(null);
      setNotice("План сохранён.");
    } catch (problem) {
      setError(formatApiError(problem));
    } finally {
      setPending(false);
    }
  }
  const sources = [
    ...data.sources,
    ...plan.sources
      .filter((s) => !data.sources.some((row) => row.key === s.key))
      .map((s) => ({
        key: s.key,
        label: "Ранее выбранный источник",
        balance: null,
        kind: "missing",
      })),
  ];
  const categories = [
    ...data.categories,
    ...plan.categories
      .filter((c) => !data.categories.some((row) => row.id === c.id))
      .map((c) => ({ id: c.id, name: "Ранее выбранная категория" })),
  ];
  return (
    <Section title="Состав подушки и период">
      <MonthNavigationGuard dirty={!!draft} pending={pending} />
      <form onSubmit={save}>
        <fieldset disabled={pending} className={styles.reserveFields}>
          <legend>Период цели</legend>
          <label>
            С{" "}
            <input
              type="date"
              required
              value={plan.start}
              onChange={(e) => change({ start: e.target.value })}
            />
          </label>
          <label>
            До{" "}
            <input
              type="date"
              required
              min={plan.start}
              value={plan.end}
              onChange={(e) => change({ end: e.target.value })}
            />
          </label>
        </fieldset>
        <fieldset disabled={pending} className={styles.reserveFields}>
          <legend>Деньги в резерве</legend>
          {data.snapshot_date && (
            <p>Остатки на {shortDate(data.snapshot_date, true)} по закрытому отчёту.</p>
          )}
          {!sources.length && <p>В закрытых отчётах пока нет подходящих остатков.</p>}
          <p>
            Включите доступные рублёвые деньги и накопительные счета. Деньги, отложенные на
            продление, входят в выбранную сумму.
          </p>
          {sources.map((row) => {
            const sel = plan.sources.find((s) => s.key === row.key);
            return (
              <div key={row.key} className={styles.reserveLine}>
                <label>
                  <input
                    type="checkbox"
                    checked={!!sel}
                    onChange={(e) =>
                      change({
                        sources: e.target.checked
                          ? [...plan.sources, { key: row.key, portion: null }]
                          : plan.sources.filter((s) => s.key !== row.key),
                      })
                    }
                  />{" "}
                  {row.label} · {row.kind === "savings" ? "накопления" : "деньги"} ·{" "}
                  <Money value={row.balance} empty="остаток неизвестен" />
                </label>
                {sel && (
                  <label>
                    Часть остатка, ₽{" "}
                    <input
                      aria-label={`Часть остатка · ${row.label}`}
                      type="text"
                      inputMode="decimal"
                      pattern={currencyPattern}
                      placeholder="Весь остаток"
                      value={sel.portion ?? ""}
                      onChange={(e) =>
                        change({
                          sources: plan.sources.map((s) =>
                            s.key === row.key
                              ? { ...s, portion: e.target.value.replace(",", ".") || null }
                              : s,
                          ),
                        })
                      }
                    />
                  </label>
                )}
              </div>
            );
          })}
        </fieldset>
        <fieldset disabled={pending} className={styles.reserveFields}>
          <legend>Переменные обязательные расходы</legend>
          <p>
            Для выбранной категории укажите сумму в месяц или оставьте поле пустым для среднего.
            Отдельные повторяющиеся платежи уже входят в календарь.
          </p>
          {categories.map((row) => {
            const sel = plan.categories.find((c) => c.id === row.id);
            return (
              <div key={row.id} className={styles.reserveLine}>
                <label>
                  <input
                    type="checkbox"
                    checked={!!sel}
                    onChange={(e) =>
                      change({
                        categories: e.target.checked
                          ? [...plan.categories, { id: row.id, estimate: null }]
                          : plan.categories.filter((c) => c.id !== row.id),
                      })
                    }
                  />{" "}
                  {row.name}
                </label>
                {sel && (
                  <label>
                    Оценка в месяц, ₽{" "}
                    <input
                      aria-label={`Оценка · ${row.name}`}
                      type="text"
                      inputMode="decimal"
                      pattern={currencyPattern}
                      placeholder="По истории"
                      value={sel.estimate ?? ""}
                      onChange={(e) =>
                        change({
                          categories: plan.categories.map((c) =>
                            c.id === row.id
                              ? { ...c, estimate: e.target.value.replace(",", ".") || null }
                              : c,
                          ),
                        })
                      }
                    />
                  </label>
                )}
              </div>
            );
          })}
          {plan.categories.some((c) => c.estimate === null) && (
            <>
              <div className={styles.actions}>
                <label>
                  Месяц для среднего{" "}
                  <input type="month" value={month} onChange={(e) => setMonth(e.target.value)} />
                </label>
                <button
                  type="button"
                  disabled={!month || plan.months.includes(month) || plan.months.length >= 12}
                  onClick={() => {
                    change({ months: [...plan.months, month].sort() });
                    setMonth("");
                  }}
                >
                  Добавить месяц
                </button>
              </div>
              <div className={styles.actions}>
                {plan.months.map((m) => (
                  <button
                    type="button"
                    key={m}
                    aria-label={`Убрать ${formatMonthKey(m)}`}
                    onClick={() => change({ months: plan.months.filter((item) => item !== m) })}
                  >
                    {formatMonthKey(m)} ×
                  </button>
                ))}
              </div>
            </>
          )}
        </fieldset>
        <div className={styles.actions}>
          <Button type="submit" disabled={!draft || pending}>
            {pending ? "Сохранение…" : "Сохранить план"}
          </Button>
          {draft && (
            <Button
              type="button"
              disabled={pending}
              onClick={async () => {
                setPending(true);
                try {
                  const current = await getReserve();
                  client.setQueryData(queryKey, current);
                  setDraft(null);
                  setError("");
                } catch (err) {
                  setError(formatApiError(err));
                } finally {
                  setPending(false);
                }
              }}
            >
              Вернуться к сохранённому
            </Button>
          )}
        </div>
        {error && <p role="alert">{error}</p>}
        {notice && <p role="status">{notice}</p>}
      </form>
    </Section>
  );
}
export default function SpendingReservePage() {
  const query = useQuery({ queryKey, queryFn: ({ signal }) => getReserve(signal) });
  const data = query.data;
  return (
    <UiV2Shell active="spending" header={<h1>Подушка безопасности</h1>}>
      <div className={sheet.sheet}>
        <ExpenseTabs reserve />
        {query.isError ? (
          <UiV2WidgetState retry={() => void query.refetch()} />
        ) : !data ? (
          <UiV2Loading label="Загружаем подушку" />
        ) : (
          <>
            <section className={sheet.section}>
              <div className={sheet.figures}>
                <div className={sheet.figure}>
                  <strong className={sheet.hero}>
                    <Money value={data.reserve} empty="Не указан" />
                  </strong>
                  <span className={sheet.figureLabel}>Доступный резерв</span>
                </div>
                <div className={sheet.figure}>
                  <strong className={sheet.figureValue}>
                    <Money value={data.monthly} empty="Недостаточно данных" />
                  </strong>
                  <span className={sheet.figureLabel}>Обязательные в месяц</span>
                </div>
                <div className={sheet.figure}>
                  <strong className={sheet.figureValue}>
                    {data.coverage_months === null
                      ? "—"
                      : `${data.coverage_months.replace(".", ",")} мес.`}
                  </strong>
                  <span className={sheet.figureLabel}>Покрытие по среднему</span>
                </div>
              </div>
            </section>
            <Section title={`Цель до ${shortDate(data.plan.end, true)}`}>
              <p>
                Потребуется{" "}
                <strong>
                  <Money value={data.target} empty="недостаточно данных" />
                </strong>{" "}
                с {shortDate(data.plan.start, true)}.
              </p>
              {data.difference && (
                <p>
                  {data.difference.amount.startsWith("-")
                    ? "Осталось накопить"
                    : "Запас сверх цели"}{" "}
                  <strong>
                    <Money
                      value={{
                        ...data.difference,
                        amount: data.difference.amount.replace(/^-/, ""),
                      }}
                    />
                  </strong>
                </p>
              )}
              {data.gaps.map((gap) => (
                <p key={gap} className={sheet.gapNote}>
                  {gap}
                </p>
              ))}
            </Section>
            {!!data.basis.length && (
              <Section title="Состав месячной оценки">
                <Table>
                  <thead>
                    <tr>
                      <Th>Категория</Th>
                      <Th>Основание</Th>
                      <Th numeric>В месяц</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.basis.map((row) => (
                      <tr key={row.id}>
                        <Td>{row.name}</Td>
                        <Td>
                          {row.method === "estimate"
                            ? "Ваша оценка"
                            : "Среднее · " +
                              data.plan.months.map((m) => formatMonthKey(m)).join(", ")}
                        </Td>
                        <Td numeric>
                          <Money value={row.amount} />
                        </Td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </Section>
            )}
            {data.history_coverage.length > 0 && (
              <details>
                <summary>Покрытие месяцев в среднем</summary>
                <ul>
                  {data.history_coverage.map((m) => (
                    <li key={m.month}>
                      {formatMonthKey(m.month)} ·{" "}
                      {m.full ? "по загруженным выпискам весь месяц" : "период выписок неполный"} ·
                      счетов Альфы {m.accounts} ·{" "}
                      {m.manual ? "ручной файл загружен" : "ручного файла нет"}
                      {!m.same_sources ? " · другой набор источников" : ""}
                      {m.unresolved ? " · есть вопросы к операциям" : ""}
                    </li>
                  ))}
                </ul>
              </details>
            )}
            <ReserveSettings data={data} />
            {!!data.rules.length && (
              <Section title="Правила обязательных платежей">
                <Table>
                  <thead>
                    <tr>
                      <Th>Платёж</Th>
                      <Th>Следующая оплата</Th>
                      <Th numeric>Сумма</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.rules.map((r) => (
                      <tr key={r.id}>
                        <Td>
                          {r.title}
                          {r.needs_review ? " · проверить" : ""}
                        </Td>
                        <Td>
                          {r.next_due ? shortDate(r.next_due, true) : "Дата неизвестна"}
                          {r.period_months ? ` · каждые ${r.period_months} мес.` : ""}
                        </Td>
                        <Td numeric>
                          <Money value={r.amount} />
                        </Td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </Section>
            )}
            <Section title="Календарь обязательных расходов">
              <p>
                В неполном месяце переменная часть пропорциональна числу дней. Продления приходятся
                на даты оплаты.
              </p>
              <Table>
                <thead>
                  <tr>
                    <Th>Месяц</Th>
                    <Th numeric>Переменные</Th>
                    <Th>Платежи</Th>
                    <Th numeric>Всего</Th>
                  </tr>
                </thead>
                <tbody>
                  {data.calendar.map((m) => (
                    <tr key={m.month}>
                      <Td>{formatMonthKey(m.month)}</Td>
                      <Td numeric>
                        <Money value={m.variable} />
                      </Td>
                      <Td>
                        {m.payments.map((p) => (
                          <div key={`${p.date}-${p.rule_id}`}>
                            {shortDate(p.date)} · {p.title} · <Money value={p.amount} />
                          </div>
                        ))}
                      </Td>
                      <Td numeric>
                        <Money value={m.total} />
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </Section>
          </>
        )}
      </div>
    </UiV2Shell>
  );
}
