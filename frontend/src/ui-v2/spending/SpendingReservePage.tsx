import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import type { MoneyValue } from "../../api/types";
import { MonthMoneyInput } from "../MonthMoneyInput";
import type { Purchase } from "../../api/spendingPayments";
import { PaymentRuleDialog } from "./PaymentRuleDialog";
import { formatApiError } from "../../api/client";
import {
  getReserve,
  putReserve,
  type ReservePlan,
  type ReserveView,
} from "../../api/spendingReserve";
import { Badge, Button, Field, Input, Table, Td, Th } from "../../components/ui";
import { formatMonthKey, pluralRu } from "../../lib/format";
import { MonthNavigationGuard } from "../MonthNavigationGuard";
import { UiV2Shell } from "../UiV2Shell";
import { UiV2Loading, UiV2WidgetState } from "../UiV2StateBlocks";
import sheet from "../ReportSheet.module.css";
import { Money, Section, shortDate, isNonzero } from "./common";
import { ExpenseTabs } from "./ExpenseTabs";
import styles from "./Reserve.module.css";

const queryKey = ["spending", "reserve"];
const currencyPattern = /^[0-9]{1,14}([.,][0-9]{1,2})?$/;

function ShareBar({ value, max }: { value: MoneyValue | null; max: number }) {
  if (!value || !(max > 0)) return null;
  return (
    <span className={styles.share} aria-hidden="true">
      <span
        style={{ width: `${Math.min(100, Math.max(0, (Number(value.amount) / max) * 100))}%` }}
      />
    </span>
  );
}
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
    if (
      [
        ...plan.sources.map((row) => row.portion),
        ...plan.categories.map((row) => row.estimate),
      ].some((value) => value !== null && !currencyPattern.test(value))
    ) {
      setError("Проверьте суммы. Допустимы до 14 цифр и до двух знаков после запятой.");
      return;
    }
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
          <div className={styles.dates}>
            <Field label="С" htmlFor="reserve-start">
              <Input
                id="reserve-start"
                type="date"
                required
                value={plan.start}
                onChange={(e) => change({ start: e.target.value })}
              />
            </Field>
            <Field label="До" htmlFor="reserve-end">
              <Input
                id="reserve-end"
                type="date"
                required
                min={plan.start}
                value={plan.end}
                onChange={(e) => change({ end: e.target.value })}
              />
            </Field>
          </div>
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
                <label className={styles.choice}>
                  <input
                    className={styles.check}
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
                  <span>
                    {row.label} <small>· {row.kind === "savings" ? "накопления" : "деньги"}</small>
                  </span>
                </label>
                <span className={`num ${styles.balance}`}>
                  <Money value={row.balance} empty="остаток неизвестен" />
                </span>
                {sel && (
                  <Field htmlFor={`portion-${row.key}`} label="Часть остатка">
                    <MonthMoneyInput
                      id={`portion-${row.key}`}
                      aria-label={`Часть остатка · ${row.label}`}
                      placeholder="Весь остаток"
                      value={sel.portion ?? ""}
                      onChange={(value) =>
                        change({
                          sources: plan.sources.map((s) =>
                            s.key === row.key
                              ? { ...s, portion: value.replace(",", ".") || null }
                              : s,
                          ),
                        })
                      }
                    />
                  </Field>
                )}
              </div>
            );
          })}
        </fieldset>
        <fieldset disabled={pending} className={styles.reserveFields}>
          <legend>Переменные обязательные расходы</legend>
          <p>
            Для ручной оценки укажите только переменную часть расходов. Регулярные платежи с
            отдельным правилом прибавятся к ней. Оставьте поле пустым для среднего по выбранным
            месяцам.
          </p>
          {categories.map((row) => {
            const sel = plan.categories.find((c) => c.id === row.id);
            return (
              <div key={row.id} className={styles.reserveLine}>
                <label className={styles.choice}>
                  <input
                    className={styles.check}
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
                  <Field htmlFor={`estimate-${row.id}`} label="Оценка в месяц">
                    <MonthMoneyInput
                      id={`estimate-${row.id}`}
                      aria-label={`Оценка · ${row.name}`}
                      placeholder="По истории"
                      value={sel.estimate ?? ""}
                      onChange={(value) =>
                        change({
                          categories: plan.categories.map((c) =>
                            c.id === row.id
                              ? { ...c, estimate: value.replace(",", ".") || null }
                              : c,
                          ),
                        })
                      }
                    />
                  </Field>
                )}
              </div>
            );
          })}
          {plan.categories.some((c) => c.estimate === null) && (
            <>
              <div className={styles.actions}>
                <Field label="Месяц для среднего" htmlFor="reserve-month">
                  <Input
                    id="reserve-month"
                    type="month"
                    value={month}
                    onChange={(e) => setMonth(e.target.value)}
                  />
                </Field>
                <Button
                  variant="secondary"
                  size="sm"
                  type="button"
                  disabled={!month || plan.months.includes(month) || plan.months.length >= 12}
                  onClick={() => {
                    change({ months: [...plan.months, month].sort() });
                    setMonth("");
                  }}
                >
                  Добавить
                </Button>
              </div>
              <div className={styles.actions}>
                {plan.months.map((m) => (
                  <Button
                    variant="ghost"
                    size="sm"
                    className={styles.monthChip}
                    type="button"
                    key={m}
                    aria-label={`Убрать ${formatMonthKey(m)}`}
                    onClick={() => change({ months: plan.months.filter((item) => item !== m) })}
                  >
                    {formatMonthKey(m)} ×
                  </Button>
                ))}
              </div>
            </>
          )}
        </fieldset>
        <div className={styles.actions}>
          <Button variant="primary" type="submit" disabled={!draft || pending}>
            {pending ? "Сохранение…" : "Сохранить план"}
          </Button>
          {draft && (
            <Button
              variant="ghost"
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
        {error && (
          <p className="inline-alert inline-alert--error" role="alert">
            {error}
          </p>
        )}
        {notice && (
          <p className="inline-alert inline-alert--ok" role="status">
            {notice}
          </p>
        )}
      </form>
    </Section>
  );
}
export default function SpendingReservePage() {
  const [settingsChoice, setSettingsChoice] = useState<boolean | null>(null);
  const [candidate, setCandidate] = useState<(Purchase & { ruleId: number }) | null>(null);
  const query = useQuery({ queryKey, queryFn: ({ signal }) => getReserve(signal) });
  const data = query.data;
  const settingsOpen = settingsChoice ?? !data?.plan.sources.length;
  const targetAmount = Number(data?.target?.amount);
  const calendarPeak = Math.max(
    0,
    ...(data?.calendar.map((month) => Number(month.total?.amount ?? 0)) ?? []),
  );
  return (
    <UiV2Shell
      active="spending"
      showRefresh={false}
      header={
        <div className={styles.header}>
          <h1>Подушка безопасности</h1>
          {data && !query.isError && (
            <Button
              aria-expanded={settingsOpen}
              aria-controls="reserve-settings"
              onClick={() => setSettingsChoice(!settingsOpen)}
            >
              {settingsOpen ? "Свернуть настройки" : "Настроить подушку"}
            </Button>
          )}
        </div>
      }
    >
      <div className={sheet.sheet}>
        <ExpenseTabs />
        {query.isError ? (
          <UiV2WidgetState retry={() => void query.refetch()} />
        ) : !data ? (
          <UiV2Loading label="Загружаем подушку" />
        ) : (
          <>
            <div
              id="reserve-settings"
              hidden={!settingsOpen}
              onChangeCapture={() => setSettingsChoice(true)}
            >
              <ReserveSettings data={data} />
            </div>
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
              <div className={styles.goal}>
                <div className={styles.goalHead}>
                  <span>
                    Цель к дате{" "}
                    <strong className="num">
                      <Money value={data.target} empty="недостаточно данных" />
                    </strong>
                  </span>
                  {data.difference && (
                    <span
                      className={sheet.delta}
                      data-tone={data.difference.amount.startsWith("-") ? "neutral" : "positive"}
                    >
                      {data.difference.amount.startsWith("-")
                        ? "Осталось накопить"
                        : !isNonzero(data.difference)
                          ? "Цель достигнута"
                          : "Запас сверх цели"}{" "}
                      {isNonzero(data.difference) && (
                        <strong className="num">
                          <Money
                            value={{
                              ...data.difference,
                              amount: data.difference.amount.replace(/^-/, ""),
                            }}
                          />
                        </strong>
                      )}
                    </span>
                  )}
                </div>
                {data.reserve && targetAmount > 0 && (
                  <progress
                    className={styles.goalBar}
                    max={targetAmount}
                    value={Math.min(targetAmount, Math.max(0, Number(data.reserve.amount)))}
                    aria-label="Доступный резерв относительно цели"
                  />
                )}
                <div className={styles.meta}>
                  <span>
                    {shortDate(data.plan.start, true)} — {shortDate(data.plan.end, true)}
                  </span>
                  <span>
                    {data.plan.sources.length}{" "}
                    {pluralRu(data.plan.sources.length, ["счёт", "счёта", "счетов"])}
                  </span>
                  <span>
                    {data.plan.categories.length}{" "}
                    {pluralRu(data.plan.categories.length, ["категория", "категории", "категорий"])}
                  </span>
                  {!settingsOpen && (
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-controls="reserve-settings"
                      onClick={() => {
                        setSettingsChoice(true);
                        requestAnimationFrame(() =>
                          document.getElementById("reserve-start")?.focus(),
                        );
                      }}
                    >
                      Изменить состав
                    </Button>
                  )}
                </div>
              </div>
              {data.payment_candidates.map((c) => (
                <div
                  className={styles.candidate}
                  key={`${c.month}:${c.source}:${c.operation_id}:${c.rule_id}`}
                >
                  <p>
                    <strong>{c.title}</strong> ·{" "}
                    <span className="num">
                      <Money value={c.amount} />
                    </span>
                    <br />
                    {shortDate(c.date, true)} · {c.category} · Возможная оплата по графику
                  </p>
                  <Button
                    variant="secondary"
                    size="sm"
                    aria-label={`Проверить покупку «${c.title}»`}
                    type="button"
                    onClick={() =>
                      setCandidate({
                        month: c.month,
                        source: c.source,
                        id: c.operation_id,
                        ruleId: c.rule_id,
                      })
                    }
                  >
                    Проверить
                  </Button>
                </div>
              ))}
              {candidate && (
                <PaymentRuleDialog
                  purchase={candidate}
                  suggestedRuleId={candidate.ruleId}
                  detached={[]}
                  onClose={() => setCandidate(null)}
                />
              )}
              {data.gaps.length > 0 && (
                <div className={styles.gaps}>
                  {Array.from(new Set(data.gaps)).map((gap) => (
                    <div key={gap}>{gap}</div>
                  ))}
                </div>
              )}
            </Section>
            {(data.basis.length > 0 ||
              data.rules.length > 0 ||
              data.history_coverage.length > 0) && (
              <Section title="Из чего складывается обязательный месяц">
                {(data.basis.length > 0 || data.rules.length > 0) && (
                  <Table>
                    <thead>
                      <tr>
                        <Th>Статья</Th>
                        <Th>Основание расчёта</Th>
                        <Th numeric>В месяц</Th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.rules.map((rule) => (
                        <tr key={`rule-${rule.id}`}>
                          <Td>
                            {rule.title}
                            {rule.needs_review && (
                              <>
                                {" "}
                                <Badge tone="draft">Проверить</Badge>
                              </>
                            )}
                          </Td>
                          <Td>
                            <Money value={rule.amount} empty="Сумма неизвестна" />{" "}
                            {rule.period_months
                              ? `раз в ${rule.period_months} мес.`
                              : "· период неизвестен"}
                            <br />
                            <small className={sheet.muted}>
                              Следующая оплата ·{" "}
                              {rule.next_due ? shortDate(rule.next_due, true) : "дата неизвестна"}
                            </small>
                          </Td>
                          <Td numeric>
                            <Money value={rule.monthly} />
                            <ShareBar value={rule.monthly} max={Number(data.monthly?.amount)} />
                          </Td>
                        </tr>
                      ))}
                      {data.basis.map((row) => (
                        <tr key={`category-${row.id}`}>
                          <Td>{row.name}</Td>
                          <Td>
                            {row.method === "estimate"
                              ? "Ваша оценка переменных расходов"
                              : data.plan.months.length
                                ? `Переменные расходы · среднее за ${data.plan.months.map((m) => formatMonthKey(m)).join(", ")}`
                                : "Месяцы для среднего не выбраны"}
                          </Td>
                          <Td numeric>
                            <Money value={row.amount} />
                            <ShareBar value={row.amount} max={Number(data.monthly?.amount)} />
                          </Td>
                        </tr>
                      ))}
                    </tbody>
                  </Table>
                )}
                {data.basis.some((c) => c.method === "history") && (
                  <p className={sheet.gapNote}>
                    Среднее исключает покупки с отдельным графиком и подтверждённые оплаты по нему.
                    Для других оплат по тому же графику подтвердите связь в карточке покупки или
                    укажите переменную часть вручную.
                  </p>
                )}
                {data.history_coverage.length > 0 && (
                  <details className={styles.coverage}>
                    <summary>Покрытие месяцев в среднем</summary>
                    <ul>
                      {data.history_coverage.map((m) => (
                        <li key={m.month}>
                          {formatMonthKey(m.month)} ·{" "}
                          {m.full
                            ? "по загруженным выпискам весь месяц"
                            : "период выписок неполный"}{" "}
                          · счетов Альфы {m.accounts} ·{" "}
                          {m.manual ? "ручной файл загружен" : "ручного файла нет"}
                          {!m.same_sources ? " · другой набор источников" : ""}
                          {m.unresolved ? " · есть вопросы к операциям" : ""}
                        </li>
                      ))}
                    </ul>
                  </details>
                )}
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
                          <div className={styles.payment} key={`${p.date}-${p.rule_id}`}>
                            <span className="num">{shortDate(p.date)}</span>
                            <span>{p.title}</span>
                            <strong className="num">
                              <Money value={p.amount} empty="сумма неизвестна" />
                            </strong>
                          </div>
                        ))}
                      </Td>
                      <Td numeric>
                        <Money value={m.total} />
                        <ShareBar value={m.total} max={calendarPeak} />
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
