import { useEffect, useState, type ReactNode } from "react";
import { getGoalPlan, type Goal, type GoalPlan } from "../api/goals";
import { formatApiError } from "../api/client";
import { DataValue, Field, Input } from "../components/ui";
import { formatDate, formatPercent } from "../lib/format";
import { fromKopecks, moneySharePercent, normalizeMoneyInput, rub, toKopecks } from "../lib/money";
import { GoalPlanChart } from "./GoalPlanChart";
import { MonthMoneyInput } from "./MonthMoneyInput";
import { moneyWholeText } from "./valueFormat";

const money = (amount: string) => moneyWholeText(rub(amount));

function firstDate(value: string): string | null {
  if (!value) return "";
  const match = /^(\d{2})\.(\d{2})\.(\d{4})$/.exec(value);
  if (!match) return null;
  const iso = `${match[3]}-${match[2]}-${match[1]}`;
  const date = new Date(`${iso}T00:00:00Z`);
  return Number.isNaN(date.getTime()) || date.toISOString().slice(0, 10) !== iso ? null : iso;
}

export function GoalPlanBlock({
  goal,
  monthId,
  currentIncome,
  details,
}: {
  goal: Goal;
  monthId: number;
  currentIncome?: string | null;
  details?: ReactNode;
}) {
  const passive = goal.goal_type === "passive_income";
  const [open, setOpen] = useState(true);
  const [payment, setPayment] = useState("");
  const [rate, setRate] = useState("0");
  const [first, setFirst] = useState("");
  const [plan, setPlan] = useState<GoalPlan | null>(null);
  const [error, setError] = useState<string | null>(null);
  const normalizedPayment = normalizeMoneyInput(payment);
  const normalizedRate = normalizeMoneyInput(rate);
  const normalizedFirst = firstDate(first);
  const inputError =
    payment !== "" && (normalizedPayment === null || toKopecks(normalizedPayment) < 0n)
      ? "Введите взнос от 0 ₽, не больше двух знаков после запятой."
      : normalizedRate === null ||
          toKopecks(normalizedRate) < 0n ||
          toKopecks(normalizedRate) > 10000n
        ? "Введите доходность от 0 до 100%."
        : normalizedFirst === null
          ? "Введите дату в формате ДД.ММ.ГГГГ."
          : null;
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setPlan(null);
    setError(null);
    if (inputError) return;
    const parameters: Record<string, string> = { annual_rate_pct: normalizedRate ?? "0" };
    if (normalizedPayment !== null) parameters.monthly_contribution = normalizedPayment;
    if (normalizedFirst) parameters.first_contribution_date = normalizedFirst;
    const timer = setTimeout(() => {
      void getGoalPlan(goal.id, monthId, parameters, controller.signal)
        .then((result) => {
          if (!controller.signal.aborted) setPlan(result);
        })
        .catch((reason) => {
          if (!controller.signal.aborted) setError(formatApiError(reason));
        });
    }, 250);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [open, goal.id, monthId, normalizedPayment, normalizedRate, normalizedFirst, inputError]);

  const visiblePlan = inputError ? null : plan;
  const content = (
    <>
      {inputError || error ? <p role="alert">{inputError ?? error}</p> : null}
      {!inputError && !error && !visiblePlan ? <p role="status">Расчёт…</p> : null}
      {visiblePlan ? (
        <>
          {visiblePlan.status === "base_unavailable" ? (
            <>
              <p>Нет базы для расчёта.</p>
              <details className="goal-plan-more">
                <summary>Подробнее</summary>
                {details}
              </details>
            </>
          ) : (
            <>
              {visiblePlan.coverage !== "complete" ? (
                <p className="goal-plan-note">
                  Расчёт по известной части капитала: данные неполные.
                </p>
              ) : null}
              {passive ? (
                <PassiveEstimate plan={visiblePlan} currentIncome={currentIncome} />
              ) : (
                <>
                  <PlanResult plan={visiblePlan} payment={normalizedPayment} />
                  {visiblePlan.trajectory?.length && visiblePlan.base_capital !== null ? (
                    <GoalPlanChart plan={visiblePlan} goal={goal} />
                  ) : null}
                </>
              )}
              <details className="goal-plan-more">
                <summary>Подробнее</summary>
                <div className="goal-plan-explanation">
                  {details}
                  <p>
                    База на {formatDate(visiblePlan.as_of_date)}: ликвидные активы{" "}
                    {money(visiblePlan.components.liquid_assets)} минус включённые долги{" "}
                    {money(visiblePlan.components.included_debts)}. Недвижимость исключена;
                    сохранённые снимки выбранного месяца. Покрытие не подтверждает актуальность
                    каждой оценки.
                  </p>
                  {passive ? (
                    <>
                      <p>
                        Отдача = фактический среднемесячный чистый пассивный доход × 12 / ликвидный
                        капитал. Оценка предполагает сохранение текущей отдачи.
                      </p>
                      {visiblePlan.income_months_used?.length ? (
                        <p>Месяцы дохода: {visiblePlan.income_months_used.join(", ")}.</p>
                      ) : null}
                    </>
                  ) : (
                    <>
                      <p>
                        Рост применяется ко всей базе, включая отрицательный капитал; начисление раз
                        в месяц перед взносом. Без выбранной даты первый взнос —{" "}
                        {visiblePlan.first_contribution_date
                          ? formatDate(visiblePlan.first_contribution_date)
                          : "первый день месяца после снимка"}
                        . Следующие — в тот же день, в коротком месяце — в последний день.
                      </p>
                      {visiblePlan.required_contribution != null ? (
                        <p>
                          До срока: {visiblePlan.remaining_contributions} взносов. Последний
                          необходимый взнос: {money(visiblePlan.last_required_contribution ?? "0")}.
                        </p>
                      ) : null}
                      {visiblePlan.trajectory?.length ? (
                        <div className="goal-plan-table-scroll">
                          <table className="goal-plan-table">
                            <caption>Помесячные взносы</caption>
                            <thead>
                              <tr>
                                <th>Дата взноса</th>
                                <th>Капитал после взноса</th>
                              </tr>
                            </thead>
                            <tbody>
                              {visiblePlan.trajectory.map((point) => (
                                <tr key={point.date}>
                                  <td>{formatDate(point.date)}</td>
                                  <td>{money(point.capital)}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      ) : null}
                    </>
                  )}
                </div>
              </details>
            </>
          )}
        </>
      ) : null}
    </>
  );
  if (passive) return <div className="goal-card__details goal-plan">{content}</div>;
  return (
    <details
      className="goal-card__details goal-plan"
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>План достижения</summary>
      <p className="goal-plan-note">
        Условный расчёт: взнос в начале месяца, доходность — ваше допущение (0% — без роста)
      </p>
      <div className="goal-plan-fields">
        <Field label="Взнос в месяц" htmlFor={`payment-${goal.id}`}>
          <MonthMoneyInput id={`payment-${goal.id}`} value={payment} onChange={setPayment} />
        </Field>
        <Field label="Доходность в год" htmlFor={`rate-${goal.id}`}>
          <MonthMoneyInput id={`rate-${goal.id}`} value={rate} onChange={setRate} suffix="%" />
        </Field>
        <Field label="Первый взнос" htmlFor={`first-${goal.id}`}>
          <Input
            id={`first-${goal.id}`}
            type="text"
            inputMode="numeric"
            placeholder="ДД.ММ.ГГГГ"
            maxLength={10}
            value={first}
            onChange={(event) => setFirst(event.target.value)}
          />
        </Field>
      </div>
      {open ? content : null}
    </details>
  );
}

function PlanResult({ plan, payment }: { plan: GoalPlan; payment: string | null }) {
  const state =
    plan.status === "achieved"
      ? "Цель уже достигнута по базе."
      : plan.deadline_status === "passed"
        ? "Срок цели прошёл."
        : plan.status === "not_reached"
          ? "При этих условиях цель не достигается за 100 лет."
          : plan.status === "contribution_missing"
            ? "Введите взнос в месяц (0 — без взносов)."
            : null;
  if (state)
    return (
      <p className="goal-plan-state" role="status">
        {state}
      </p>
    );
  const difference = plan.contribution_difference;
  const negative = difference != null && toKopecks(difference) < 0n;
  return (
    <>
      <div className="goal-card__values goal-plan-results">
        {plan.achievement_date ? (
          <DataValue
            label="Достигнете"
            value={new Intl.DateTimeFormat("ru-RU", {
              month: "long",
              year: "numeric",
              timeZone: "UTC",
            })
              .format(new Date(`${plan.achievement_date}T00:00:00Z`))
              .replace(/\s*г\.$/, "")}
          />
        ) : null}
        {plan.required_contribution != null ? (
          <DataValue label="Нужно в месяц к сроку" value={money(plan.required_contribution)} />
        ) : null}
        {payment !== null ? (
          <DataValue
            label="Ваш взнос"
            value={money(payment)}
            meta={
              difference != null ? (
                <span className={negative ? "goal-plan-shortfall" : "goal-plan-surplus"}>
                  {negative
                    ? `не хватает ${money(difference.slice(1))} в месяц`
                    : toKopecks(difference) === 0n
                      ? "Достаточно к сроку"
                      : `+${money(difference)} запаса`}
                </span>
              ) : undefined
            }
          />
        ) : null}
      </div>
      {plan.deadline_status === "absent" ? (
        <p className="goal-plan-note">Срок цели не задан.</p>
      ) : null}
      {plan.deadline_status === "no_contributions" ? (
        <p className="goal-plan-note">До срока нет дат взносов.</p>
      ) : null}
      {plan.deadline_status === "outside_horizon" ? (
        <p className="goal-plan-note">Срок цели дальше горизонта расчёта в 100 лет.</p>
      ) : null}
    </>
  );
}

function PassiveEstimate({
  plan,
  currentIncome,
}: {
  plan: GoalPlan;
  currentIncome?: string | null;
}) {
  if (plan.required_capital == null) return <p>Недостаточно данных для оценки нужного капитала.</p>;
  const yieldPct =
    currentIncome != null &&
    plan.base_capital != null &&
    toKopecks(plan.base_capital) > 0n &&
    toKopecks(currentIncome) > 0n
      ? moneySharePercent(fromKopecks(toKopecks(currentIncome) * 12n), plan.base_capital, 1)
      : null;
  return (
    <>
      <div className="goal-card__values goal-plan-results">
        <DataValue label="Нужный капитал" value={`≈ ${money(plan.required_capital)}`} />
      </div>
      <p className="goal-plan-note">
        {yieldPct !== null
          ? `При текущей отдаче ${formatPercent(yieldPct, { digits: 1 })} в год, `
          : "При текущей отдаче капитала, "}
        доход за {plan.income_months_count} из 12 мес.
      </p>
    </>
  );
}
