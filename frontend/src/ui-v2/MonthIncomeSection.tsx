import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";

import { formatApiError } from "../api/client";
import { listIncomes } from "../api/incomes";
import { getMonthSummary } from "../api/summary";
import type { IncomeEntry, SalaryTaxSummary } from "../api/types";
import { SalaryTaxRateSummary } from "../components/SalaryTaxRateSummary";
import { DataValue, Field, HelpTip, MoneyInput } from "../components/ui";
import { formatMoney } from "../lib/format";
import { findIncome, upsertSalaryLine, upsertSimpleIncomeLine } from "../lib/incomeLines";
import { isBlankMoney, moneyAmount, normalizeMoneyInput, toKopecks } from "../lib/money";
import styles from "./UiV2MonthEditor.module.css";
import type { MonthEditorContext } from "./UiV2MonthEditorPage";

type IncomeForm = {
  salaryGross: string;
  salaryActualNet: string;
  bonus: string;
  sideIncome: string;
  cashback: string;
};

type SalaryTaxRatePart = {
  rate_bps: number;
};

const EMPTY_FORM: IncomeForm = {
  salaryGross: "",
  salaryActualNet: "",
  bonus: "",
  sideIncome: "",
  cashback: "",
};

const SIMPLE_LINES = [
  { key: "bonus", type: "bonus", name: "Премия" },
  { key: "sideIncome", type: "side_income", name: "Подработка" },
  { key: "cashback", type: "cashback", name: "Кэшбэк" },
] as const;

function formFromIncomes(incomes: IncomeEntry[]): IncomeForm {
  const salary = findIncome(incomes, "salary");
  const bonus = findIncome(incomes, "bonus");
  const side = findIncome(incomes, "side_income");
  const cashback = findIncome(incomes, "cashback");
  return {
    salaryGross: moneyAmount(salary?.gross_amount),
    salaryActualNet: moneyAmount(salary?.net_amount),
    bonus: moneyAmount(bonus?.net_amount),
    sideIncome: moneyAmount(side?.net_amount),
    cashback: moneyAmount(cashback?.net_amount),
  };
}

function sameForm(a: IncomeForm, b: IncomeForm): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

function canonicalMoney(value: string): string | null {
  const trimmed = value.trim();
  if (trimmed === "") return "";
  return normalizeMoneyInput(trimmed);
}

/** Exact-money comparison: "1000" === "1 000,00" === "1000.00", blank stays distinct from zero. */
function sameMoney(a: string, b: string): boolean {
  const left = canonicalMoney(a);
  const right = canonicalMoney(b);
  if (left === null || right === null) return a === b;
  if (left === "" || right === "") return left === right;
  return toKopecks(left) === toKopecks(right);
}

function isZeroMoney(value: string): boolean {
  const normalized = canonicalMoney(value);
  if (normalized === null || normalized === "") return true;
  return toKopecks(normalized) === 0n;
}

/** Mirrors the tax value `upsertSalaryLine` transports to the canonical salary replace API. */
function salaryTaxForWrite(
  form: IncomeForm,
  existing: IncomeEntry | undefined,
  calculatedTax: string,
): string {
  if (isBlankMoney(form.salaryGross) && isBlankMoney(form.salaryActualNet)) return "0.00";
  if (calculatedTax.trim() !== "" && !isBlankMoney(calculatedTax)) {
    return normalizeMoneyInput(calculatedTax) ?? "0.00";
  }
  return moneyAmount(existing?.tax_amount) || "0.00";
}

/**
 * Canonical values the section must read back after a save for the typed input:
 * blank/zero salary payloads delete the salary row, blank/zero simple lines are removed,
 * everything else stays as the exact decimal the API stores.
 */
function expectedFormAfterSave(
  form: IncomeForm,
  incomes: IncomeEntry[],
  calculatedTax: string,
): IncomeForm {
  const existingSalary = findIncome(incomes, "salary");
  const grossBlank = isBlankMoney(form.salaryGross);
  const netBlank = isBlankMoney(form.salaryActualNet);
  let salaryGross = "";
  let salaryActualNet = "";
  if (!(grossBlank && netBlank)) {
    const gross = grossBlank ? "0.00" : (normalizeMoneyInput(form.salaryGross) ?? "0.00");
    const net = netBlank ? "0.00" : (normalizeMoneyInput(form.salaryActualNet) ?? "0.00");
    const tax = salaryTaxForWrite(form, existingSalary, calculatedTax);
    if (!(isZeroMoney(gross) && isZeroMoney(tax) && isZeroMoney(net))) {
      salaryGross = gross;
      salaryActualNet = net;
    }
  }
  const simple = (value: string) => (isBlankMoney(value) ? "" : (normalizeMoneyInput(value) ?? ""));
  return {
    salaryGross,
    salaryActualNet,
    bonus: simple(form.bonus),
    sideIncome: simple(form.sideIncome),
    cashback: simple(form.cashback),
  };
}

function matchesExpected(actual: IncomeForm, expected: IncomeForm): boolean {
  return (Object.keys(expected) as Array<keyof IncomeForm>).every((key) =>
    sameMoney(expected[key], actual[key]),
  );
}

/** Leaf section #559: salary and other month income, isolated from the shared editor frame. */
export function MonthIncomeSection({ context }: { context: MonthEditorContext }) {
  const { month, readOnly, refresh, setDirty } = context;
  const queryClient = useQueryClient();
  const incomesQuery = useQuery({
    queryKey: ["month-income", month.id],
    queryFn: ({ signal }) => listIncomes(month.id, signal),
    retry: false,
  });
  const summaryQuery = useQuery({
    queryKey: ["month-income-summary", month.id],
    queryFn: ({ signal }) => getMonthSummary(month.id, signal),
    retry: false,
  });

  const [form, setForm] = useState<IncomeForm>(EMPTY_FORM);
  const [baseline, setBaseline] = useState<IncomeForm>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  /**
   * After a failed write the canonical rows may already contain some of the
   * attempts (partial or persisted-but-timeout creates). Retry stays gated
   * until this exact month has been re-read, so a stale ID map can never turn
   * a retry into a duplicate income.
   */
  const [recovery, setRecovery] = useState<"idle" | "pending" | "confirmed" | "failed">("idle");
  const [recoveryError, setRecoveryError] = useState<string | null>(null);
  const [identity, setIdentity] = useState(month.id);
  const operation = useRef(0);
  const dirty = !sameForm(form, baseline);
  const retryBlocked = recovery === "pending" || recovery === "failed";

  // Never keep edits or a pending save from another month on this leaf.
  if (identity !== month.id) {
    setIdentity(month.id);
    setForm(EMPTY_FORM);
    setBaseline(EMPTY_FORM);
    setSaving(false);
    setError(null);
    setNotice(null);
    setRecovery("idle");
    setRecoveryError(null);
    operation.current += 1;
  }

  useEffect(() => setDirty("income", dirty), [dirty, setDirty]);
  useEffect(
    () => () => {
      operation.current += 1;
      setDirty("income", false);
    },
    [setDirty],
  );

  const incomes = incomesQuery.isSuccess ? incomesQuery.data : null;
  const draft = useMemo(() => (incomes ? formFromIncomes(incomes) : null), [incomes]);
  useEffect(() => {
    if (dirty || !draft) return;
    setForm(draft);
    setBaseline(draft);
  }, [dirty, draft]);

  const summary = summaryQuery.isSuccess ? summaryQuery.data : null;
  const calcTax = summary ? moneyAmount(summary.salary_tax.tax) : "";
  const calcNet = summary ? moneyAmount(summary.salary_tax.calculated_net) : "";
  const calcTaxParts = summary
    ? ((summary.salary_tax as SalaryTaxSummary & { parts?: SalaryTaxRatePart[] }).parts ?? [])
    : [];

  const loading = incomesQuery.isPending || summaryQuery.isPending;
  const loadFailed = incomesQuery.isError || summaryQuery.isError;
  const loadError = incomesQuery.isError ? incomesQuery.error : summaryQuery.error;

  function patch(key: keyof IncomeForm, value: string) {
    setForm((previous) => ({ ...previous, [key]: value }));
    setNotice(null);
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (readOnly || saving || retryBlocked || !dirty) return;
    const token = ++operation.current;
    setSaving(true);
    setError(null);
    setNotice(null);
    setRecovery("idle");
    setRecoveryError(null);
    const monthId = month.id;
    let writesStarted = false;
    try {
      for (const [label, value] of [
        ["Зарплата до вычета налогов", form.salaryGross],
        ["Фактическая зарплата после налогов", form.salaryActualNet],
        ["Премия", form.bonus],
        ["Дополнительный доход", form.sideIncome],
        ["Кэшбэк", form.cashback],
      ] as const) {
        if (value.trim() !== "" && normalizeMoneyInput(value) == null) {
          throw new Error(`Некорректная сумма: ${label}`);
        }
      }

      const loaded = incomes ?? [];
      const expected = expectedFormAfterSave(form, loaded, calcTax);

      writesStarted = true;
      await upsertSalaryLine(monthId, {
        gross: form.salaryGross,
        actualNet: form.salaryActualNet,
        existing: findIncome(loaded, "salary"),
        calculatedTax: calcTax,
      });
      for (const line of SIMPLE_LINES) {
        await upsertSimpleIncomeLine(monthId, {
          type: line.type,
          name: line.name,
          amount: form[line.key],
          existing: findIncome(loaded, line.type),
        });
      }

      // The month switched while the writes were in flight: they belong to the
      // original period, so never confirm them against the newly selected month.
      if (operation.current !== token) return;

      const [freshMonth, freshIncomes, freshSummary] = await Promise.all([
        refresh(),
        listIncomes(monthId),
        getMonthSummary(monthId),
      ]);
      if (operation.current !== token) return;
      if (freshMonth.id !== monthId) {
        throw new Error("Сохранение не подтверждено: выбран другой месяц.");
      }
      if (freshMonth.status !== "draft") {
        throw new Error("Месяц закрыт во время сохранения. Данные не подтверждены.");
      }
      const confirmed = formFromIncomes(freshIncomes);
      if (!matchesExpected(confirmed, expected)) {
        throw new Error("Сохранение не подтверждено повторной загрузкой данных.");
      }

      queryClient.setQueryData(["month-income", monthId], freshIncomes);
      queryClient.setQueryData(["month-income-summary", monthId], freshSummary);
      setForm(confirmed);
      setBaseline(confirmed);
      setNotice("Доходы сохранены и подтверждены.");
    } catch (cause) {
      if (operation.current !== token) return;
      setError(formatApiError(cause));
      setSaving(false);
      // A write may have committed before this failure (partial or timed-out
      // create): re-read this month's canonical rows so the retry updates the
      // persisted identity instead of replaying a create with pre-write IDs.
      if (writesStarted) {
        setRecovery("pending");
        await reconcileAfterFailure(token, monthId);
      }
    } finally {
      if (operation.current === token) setSaving(false);
    }
  }

  async function reconcileAfterFailure(token: number, monthId: number): Promise<void> {
    try {
      const freshIncomes = await listIncomes(monthId);
      if (operation.current !== token) return;
      queryClient.setQueryData(["month-income", monthId], freshIncomes);
      setRecoveryError(null);
      setRecovery("confirmed");
      try {
        const freshSummary = await getMonthSummary(monthId);
        if (operation.current === token) {
          queryClient.setQueryData(["month-income-summary", monthId], freshSummary);
        }
      } catch {
        // A stale tax readout never gates retry: it cannot duplicate a row.
      }
    } catch (cause) {
      if (operation.current !== token) return;
      setRecoveryError(formatApiError(cause));
      setRecovery("failed");
    }
  }

  async function retryRecovery(): Promise<void> {
    if (readOnly || saving || recovery !== "failed") return;
    const token = operation.current;
    setRecovery("pending");
    await reconcileAfterFailure(token, month.id);
  }

  return (
    <section aria-label="Зарплата и прочее" className={styles.panel}>
      <h2>Зарплата и прочее</h2>
      <p>
        {readOnly
          ? "Закрытый месяц доступен только для чтения."
          : "Изменения этого раздела сохраняются отдельно от других разделов."}
      </p>
      {loading ? <p role="status">Загружаем доходы месяца…</p> : null}
      {loadFailed ? (
        <div className={styles.warning} role="alert">
          <p>Не удалось загрузить данные: {formatApiError(loadError)}</p>
          <button
            onClick={() => {
              void incomesQuery.refetch();
              void summaryQuery.refetch();
            }}
            type="button"
          >
            Повторить загрузку
          </button>
        </div>
      ) : null}
      {!loading && !loadFailed ? (
        <form onSubmit={(event) => void save(event)}>
          <div className="editor-grid">
            <Field htmlFor="salary-gross" label="Зарплата до вычета налогов">
              <MoneyInput
                disabled={readOnly || saving}
                id="salary-gross"
                inputMode="decimal"
                onChange={(value) => patch("salaryGross", value)}
                placeholder="0.00"
                value={form.salaryGross}
              />
            </Field>
            <section className="summary-grid" aria-label="Расчёт зарплаты">
              <DataValue
                label={
                  <>
                    Расчётный налог
                    <HelpTip label="О расчётном налоге">
                      Значение обновляется после сохранения зарплаты и рассчитывается по правилам
                      налогообложения месяца.
                    </HelpTip>
                  </>
                }
                value={calcTax ? formatMoney(calcTax) : "—"}
                muted
              />
              <SalaryTaxRateSummary parts={calcTaxParts} />
              <DataValue
                label={
                  <>
                    Расчётный net
                    <HelpTip label="О расчётном net">
                      Это ориентир после расчётного налога. Фактическая выплата вводится отдельно.
                    </HelpTip>
                  </>
                }
                value={calcNet ? formatMoney(calcNet) : "—"}
                muted
              />
            </section>
            <Field htmlFor="salary-actual-net" label="Фактическая зарплата после налогов">
              <MoneyInput
                disabled={readOnly || saving}
                id="salary-actual-net"
                inputMode="decimal"
                onChange={(value) => patch("salaryActualNet", value)}
                placeholder="0.00"
                value={form.salaryActualNet}
              />
            </Field>
            <Field htmlFor="bonus" label="Премия">
              <MoneyInput
                disabled={readOnly || saving}
                id="bonus"
                inputMode="decimal"
                onChange={(value) => patch("bonus", value)}
                placeholder="0.00"
                value={form.bonus}
              />
            </Field>
            <Field htmlFor="side" label="Дополнительный доход">
              <MoneyInput
                disabled={readOnly || saving}
                id="side"
                inputMode="decimal"
                onChange={(value) => patch("sideIncome", value)}
                placeholder="0.00"
                value={form.sideIncome}
              />
            </Field>
            <Field htmlFor="cashback" label="Кэшбэк (не пассивный доход)">
              <MoneyInput
                disabled={readOnly || saving}
                id="cashback"
                inputMode="decimal"
                onChange={(value) => patch("cashback", value)}
                placeholder="0.00"
                value={form.cashback}
              />
            </Field>
          </div>
          <details className="field-details">
            <summary>О расчёте и кэшбэке</summary>
            <p>
              Кэшбэк учитывается отдельно и не входит в пассивный доход. Расчётные значения
              обновляются после ручного сохранения.
            </p>
          </details>
          {!readOnly ? (
            <button disabled={!dirty || saving || retryBlocked} type="submit">
              {saving ? "Сохраняем…" : "Сохранить доходы"}
            </button>
          ) : null}
        </form>
      ) : null}
      {error ? (
        <p className={styles.warning} role="alert">
          {error}
        </p>
      ) : null}
      {recovery === "pending" ? (
        <p role="status">Часть изменений могла сохраниться. Перечитываем данные месяца…</p>
      ) : null}
      {recovery === "confirmed" ? (
        <p role="status">
          Данные месяца перечитаны после сбоя. Проверь значения и сохрани ещё раз.
        </p>
      ) : null}
      {recovery === "failed" ? (
        <div className={styles.warning} role="alert">
          <p>
            Не удалось перечитать данные месяца: {recoveryError ?? "неизвестная ошибка"}. Сохранение
            заблокировано, чтобы не создать дубликат дохода.
          </p>
          <button onClick={() => void retryRecovery()} type="button">
            Перечитать данные
          </button>
        </div>
      ) : null}
      {notice ? <p role="status">{notice}</p> : null}
    </section>
  );
}
