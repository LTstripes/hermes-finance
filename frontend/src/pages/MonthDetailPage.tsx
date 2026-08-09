import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { formatApiError } from "../api/client";
import { getMonth, updateMonth } from "../api/months";
import { listIncomes } from "../api/incomes";
import { getMonthSummary } from "../api/summary";
import type { IncomeEntry, ReportingMonth } from "../api/types";
import {
  Badge,
  Button,
  CloneMonthDialog,
  ErrorState,
  Field,
  Input,
  LoadingState,
  Panel,
} from "../components/ui";
import { MonthAssetsSection } from "../components/MonthAssetsSection";
import { MonthBudgetSection } from "../components/MonthBudgetSection";
import { MonthCloseoutSection } from "../components/MonthCloseoutSection";
import { MonthFlowsSection } from "../components/MonthFlowsSection";
import { MonthLiabilitiesSection } from "../components/MonthLiabilitiesSection";
import { MonthPositionsSection } from "../components/MonthPositionsSection";
import { formatDate, formatMoney, formatMonth } from "../lib/format";
import { findIncome, upsertSalaryLine, upsertSimpleIncomeLine } from "../lib/incomeLines";
import { moneyAmount, normalizeMoneyInput } from "../lib/money";

type EditorForm = {
  snapshot_date: string;
  salaryGross: string;
  salaryActualNet: string;
  bonus: string;
  sideIncome: string;
  cashback: string;
};

function emptyForm(): EditorForm {
  return {
    snapshot_date: "",
    salaryGross: "",
    salaryActualNet: "",
    bonus: "",
    sideIncome: "",
    cashback: "",
  };
}

function formFromData(month: ReportingMonth, incomes: IncomeEntry[]): EditorForm {
  const salary = findIncome(incomes, "salary");
  const bonus = findIncome(incomes, "bonus");
  const side = findIncome(incomes, "side_income");
  const cashback = findIncome(incomes, "cashback");
  return {
    snapshot_date: month.snapshot_date,
    salaryGross: moneyAmount(salary?.gross_amount),
    salaryActualNet: moneyAmount(salary?.net_amount),
    bonus: moneyAmount(bonus?.net_amount),
    sideIncome: moneyAmount(side?.net_amount),
    cashback: moneyAmount(cashback?.net_amount),
  };
}

function sameForm(a: EditorForm, b: EditorForm): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

export function MonthDetailPage() {
  const params = useParams();
  const navigate = useNavigate();
  const monthId = Number(params.monthId);

  const [month, setMonth] = useState<ReportingMonth | null>(null);
  const [incomes, setIncomes] = useState<IncomeEntry[]>([]);
  const [form, setForm] = useState<EditorForm>(emptyForm);
  const [baseline, setBaseline] = useState<EditorForm>(emptyForm);
  const [calcTax, setCalcTax] = useState("");
  const [calcNet, setCalcNet] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveOk, setSaveOk] = useState<string | null>(null);
  const [cloneOpen, setCloneOpen] = useState(false);

  const dirty = useMemo(() => !sameForm(form, baseline), [form, baseline]);
  const readOnly = month?.status === "closed";

  const load = useCallback(
    async (signal?: AbortSignal) => {
      if (!Number.isInteger(monthId) || monthId < 1) {
        setError("Некорректный идентификатор месяца");
        setLoading(false);
        return;
      }
      setLoading(true);
      setError(null);
      setSaveError(null);
      try {
        const [monthData, incomeData, summary] = await Promise.all([
          getMonth(monthId, signal),
          listIncomes(monthId, signal),
          getMonthSummary(monthId, signal),
        ]);
        if (signal?.aborted) {
          return;
        }
        setMonth(monthData);
        setIncomes(incomeData);
        const next = formFromData(monthData, incomeData);
        setForm(next);
        setBaseline(next);
        setCalcTax(moneyAmount(summary.salary_tax.tax));
        setCalcNet(moneyAmount(summary.salary_tax.calculated_net));
      } catch (err) {
        if (!signal?.aborted) {
          setError(formatApiError(err));
          setMonth(null);
        }
      } finally {
        if (!signal?.aborted) {
          setLoading(false);
        }
      }
    },
    [monthId],
  );

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  useEffect(() => {
    function onBeforeUnload(event: BeforeUnloadEvent) {
      if (!dirty) {
        return;
      }
      event.preventDefault();
      event.returnValue = "";
    }
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [dirty]);

  function patchForm<K extends keyof EditorForm>(key: K, value: EditorForm[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
    setSaveOk(null);
  }

  async function handleSave(event: FormEvent) {
    event.preventDefault();
    if (!month || readOnly) {
      return;
    }
    setSaving(true);
    setSaveError(null);
    setSaveOk(null);
    try {
      // validate money fields first
      for (const [label, value] of [
        ["Зарплата gross", form.salaryGross],
        ["Фактический net", form.salaryActualNet],
        ["Bonus", form.bonus],
        ["Side income", form.sideIncome],
        ["Cashback", form.cashback],
      ] as const) {
        if (value.trim() !== "" && normalizeMoneyInput(value) == null) {
          throw new Error(`Некорректная сумма: ${label}`);
        }
      }

      if (form.snapshot_date !== month.snapshot_date) {
        const updated = await updateMonth(month.id, { snapshot_date: form.snapshot_date });
        setMonth(updated);
      }

      await upsertSalaryLine(month.id, {
        gross: form.salaryGross,
        actualNet: form.salaryActualNet,
        existing: findIncome(incomes, "salary"),
        calculatedTax: calcTax,
      });
      await upsertSimpleIncomeLine(month.id, {
        type: "bonus",
        name: "Премия",
        amount: form.bonus,
        existing: findIncome(incomes, "bonus"),
      });
      await upsertSimpleIncomeLine(month.id, {
        type: "side_income",
        name: "Подработка",
        amount: form.sideIncome,
        existing: findIncome(incomes, "side_income"),
      });
      await upsertSimpleIncomeLine(month.id, {
        type: "cashback",
        name: "Кэшбэк",
        amount: form.cashback,
        existing: findIncome(incomes, "cashback"),
      });

      await load();
      setSaveOk("Сохранено. Расчётный налог/net обновлены с backend summary.");
    } catch (err) {
      setSaveError(formatApiError(err));
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <section className="stack-18">
        <LoadingState description="Загружаем редактор месяца…" inline />
      </section>
    );
  }

  if (error || !month) {
    return (
      <section className="stack-18">
        <ErrorState description={error ?? "Месяц не найден"} inline title="Ошибка" />
        <Link className="btn" to="/months">
          ← К списку
        </Link>
      </section>
    );
  }

  return (
    <section className="stack-18">
      <header className="page-header">
        <p className="eyebrow">Редактор</p>
        <h1>{formatMonth(month.year, month.month)}</h1>
        <p className="page-header__description">
          Общие сведения, доходы, активы, позиции, выплаты, бюджет, долги/RE, ИИС и комментарии.
          Финансовые формулы — только backend.
        </p>
      </header>

      <div className="toolbar">
        <Link className="btn" to="/months">
          ← К списку
        </Link>
        <Button onClick={() => setCloneOpen(true)} type="button">
          Создать следующий месяц
        </Button>
        <Badge tone={month.status === "draft" ? "draft" : "closed"}>{month.status}</Badge>
        {dirty ? <Badge tone="draft">несохранённые изменения</Badge> : null}
      </div>

      {dirty ? (
        <div className="inline-alert inline-alert--warn" role="status">
          Есть несохранённые изменения. Сохрани перед уходом со страницы.
        </div>
      ) : null}
      {readOnly ? (
        <div className="inline-alert" role="status">
          Месяц closed — редактирование заблокировано (reopen на backend / later UI).
        </div>
      ) : null}
      {saveError ? (
        <div className="inline-alert inline-alert--error" role="alert">
          {saveError}
        </div>
      ) : null}
      {saveOk ? (
        <div className="inline-alert inline-alert--ok" role="status">
          {saveOk}
        </div>
      ) : null}

      <form className="stack-18" onSubmit={handleSave}>
        <Panel label="Период" title="Общие сведения">
          <div className="editor-grid">
            <Field htmlFor="period-label" label="Период">
              <Input id="period-label" readOnly value={formatMonth(month.year, month.month)} />
            </Field>
            <Field htmlFor="status" label="Статус">
              <Input id="status" readOnly value={month.status} />
            </Field>
            <Field htmlFor="snapshot" label="Дата снимка">
              <Input
                disabled={readOnly}
                id="snapshot"
                onChange={(event) => patchForm("snapshot_date", event.target.value)}
                required
                type="date"
                value={form.snapshot_date}
              />
            </Field>
            <Field htmlFor="source" label="Источник">
              <Input id="source" readOnly value={month.source} />
            </Field>
          </div>
          <p className="muted field-hint">Снимок: {formatDate(form.snapshot_date)}</p>
        </Panel>

        <Panel label="Доходы" title="Зарплата и прочее">
          <div className="editor-grid">
            <Field htmlFor="salary-gross" label="Зарплата gross">
              <Input
                className="input--money"
                disabled={readOnly}
                id="salary-gross"
                inputMode="decimal"
                onChange={(event) => patchForm("salaryGross", event.target.value)}
                placeholder="0.00"
                value={form.salaryGross}
              />
            </Field>
            <Field htmlFor="salary-tax" label="Расчётный налог (backend)">
              <Input
                className="input--money input--calc"
                id="salary-tax"
                readOnly
                value={calcTax ? formatMoney(calcTax) : "—"}
              />
            </Field>
            <Field htmlFor="salary-calc-net" label="Расчётный net (backend)">
              <Input
                className="input--money input--calc"
                id="salary-calc-net"
                readOnly
                value={calcNet ? formatMoney(calcNet) : "—"}
              />
            </Field>
            <Field htmlFor="salary-actual-net" label="Фактический net (employer)">
              <Input
                className="input--money"
                disabled={readOnly}
                id="salary-actual-net"
                inputMode="decimal"
                onChange={(event) => patchForm("salaryActualNet", event.target.value)}
                placeholder="0.00"
                value={form.salaryActualNet}
              />
            </Field>
            <Field htmlFor="bonus" label="Bonus">
              <Input
                className="input--money"
                disabled={readOnly}
                id="bonus"
                inputMode="decimal"
                onChange={(event) => patchForm("bonus", event.target.value)}
                placeholder="0.00"
                value={form.bonus}
              />
            </Field>
            <Field htmlFor="side" label="Side income">
              <Input
                className="input--money"
                disabled={readOnly}
                id="side"
                inputMode="decimal"
                onChange={(event) => patchForm("sideIncome", event.target.value)}
                placeholder="0.00"
                value={form.sideIncome}
              />
            </Field>
            <Field htmlFor="cashback" label="Cashback (не passive)">
              <Input
                className="input--money"
                disabled={readOnly}
                id="cashback"
                inputMode="decimal"
                onChange={(event) => patchForm("cashback", event.target.value)}
                placeholder="0.00"
                value={form.cashback}
              />
            </Field>
          </div>
          <p className="muted field-hint">
            Cashback хранится отдельной строкой income_type=cashback и не входит в passive income.
            Расчётный налог обновляется после сохранения (GET /summary).
          </p>
        </Panel>

        <div className="toolbar">
          <Button disabled={readOnly || saving || !dirty} type="submit" variant="primary">
            {saving ? "Сохраняем…" : "Сохранить"}
          </Button>
          <Button
            disabled={saving || !dirty}
            onClick={() => {
              setForm(baseline);
              setSaveOk(null);
              setSaveError(null);
            }}
            type="button"
          >
            Сбросить
          </Button>
        </div>
      </form>

      <MonthAssetsSection monthId={month.id} readOnly={readOnly} />

      <MonthPositionsSection
        defaultPriceDate={month.snapshot_date}
        monthId={month.id}
        readOnly={readOnly}
      />

      <MonthFlowsSection defaultDate={month.snapshot_date} monthId={month.id} readOnly={readOnly} />

      <MonthBudgetSection monthId={month.id} readOnly={readOnly} />

      <MonthLiabilitiesSection monthId={month.id} readOnly={readOnly} />

      <MonthCloseoutSection
        monthId={month.id}
        onStatusChanged={() => void load()}
        readOnly={readOnly}
        status={month.status === "closed" ? "closed" : "draft"}
        year={month.year}
      />

      <CloneMonthDialog
        onCancel={() => setCloneOpen(false)}
        onCloned={(cloned) => {
          setCloneOpen(false);
          navigate(`/months/${cloned.id}`);
        }}
        open={cloneOpen}
        source={month}
      />
    </section>
  );
}
