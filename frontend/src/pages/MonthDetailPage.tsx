import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";

import { formatApiError } from "../api/client";
import { getDashboard } from "../api/dashboard";
import { listIncomes } from "../api/incomes";
import { closeMonth, getMonth, reopenMonth, updateMonth } from "../api/months";
import { getMonthSummary } from "../api/summary";
import type { DashboardKpis, IncomeEntry, ReportingMonth } from "../api/types";
import { MonthAssetsSection } from "../components/MonthAssetsSection";
import { MonthBudgetSection } from "../components/MonthBudgetSection";
import { MonthNoteSection } from "../components/MonthNoteSection";
import { MonthReviewSection } from "../components/MonthReviewSection";
import { MonthFlowsSection } from "../components/MonthFlowsSection";
import { MonthLiabilitiesSection } from "../components/MonthLiabilitiesSection";
import { MonthPositionsSection } from "../components/MonthPositionsSection";
import { SalaryTaxRateSummary } from "../components/SalaryTaxRateSummary";
import {
  Badge,
  Button,
  CloneMonthDialog,
  ConfirmDialog,
  DataValue,
  ErrorState,
  Field,
  HelpTip,
  Input,
  LoadingState,
  Panel,
  StickySubheader,
} from "../components/ui";
import { formatMoney, formatMonth } from "../lib/format";
import { findIncome, upsertSalaryLine, upsertSimpleIncomeLine } from "../lib/incomeLines";
import { MONTH_STATUS_LABELS, SOURCE_LABELS, labelOf } from "../lib/labels";
import { moneyAmount, normalizeMoneyInput } from "../lib/money";

type EditorForm = {
  snapshot_date: string;
  salaryGross: string;
  salaryActualNet: string;
  bonus: string;
  sideIncome: string;
  cashback: string;
};

type SalaryTaxRatePart = {
  rate_bps: number;
};

const MONTH_SECTIONS = [
  { id: "general", label: "Общие данные" },
  { id: "income", label: "Доходы" },
  { id: "assets", label: "Активы" },
  { id: "positions", label: "Позиции" },
  { id: "flows", label: "Выплаты" },
  { id: "budget", label: "Бюджет" },
  { id: "liabilities", label: "Долги" },
  { id: "note", label: "Заметка" },
  { id: "review", label: "Проверка" },
] as const;

type MonthSectionId = (typeof MONTH_SECTIONS)[number]["id"];
type PendingLifecycle = "close" | "reopen" | null;

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

function normalizeSection(value: string | null): MonthSectionId {
  return MONTH_SECTIONS.some((section) => section.id === value)
    ? (value as MonthSectionId)
    : "general";
}

export function MonthDetailPage() {
  const params = useParams();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const monthId = Number(params.monthId);

  const [month, setMonth] = useState<ReportingMonth | null>(null);
  const [incomes, setIncomes] = useState<IncomeEntry[]>([]);
  const [form, setForm] = useState<EditorForm>(emptyForm);
  const [baseline, setBaseline] = useState<EditorForm>(emptyForm);
  const [calcTax, setCalcTax] = useState("");
  const [calcNet, setCalcNet] = useState("");
  const [calcTaxParts, setCalcTaxParts] = useState<SalaryTaxRatePart[]>([]);
  const [dashboardKpis, setDashboardKpis] = useState<DashboardKpis | null>(null);
  const [dashboardWarnings, setDashboardWarnings] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveOk, setSaveOk] = useState<string | null>(null);
  const [cloneOpen, setCloneOpen] = useState(false);
  const [pendingLifecycle, setPendingLifecycle] = useState<PendingLifecycle>(null);
  const [lifecycleBusy, setLifecycleBusy] = useState(false);
  const [lifecycleError, setLifecycleError] = useState<string | null>(null);
  const [visitedSections, setVisitedSections] = useState<Set<MonthSectionId>>(
    () => new Set(["general"]),
  );

  const dirty = useMemo(() => !sameForm(form, baseline), [form, baseline]);
  const generalDirty = form.snapshot_date !== baseline.snapshot_date;
  const incomeDirty =
    form.salaryGross !== baseline.salaryGross ||
    form.salaryActualNet !== baseline.salaryActualNet ||
    form.bonus !== baseline.bonus ||
    form.sideIncome !== baseline.sideIncome ||
    form.cashback !== baseline.cashback;
  const readOnly = month?.status === "closed";
  const activeSection = normalizeSection(searchParams.get("section"));
  const activeSectionLabel =
    MONTH_SECTIONS.find((section) => section.id === activeSection)?.label ?? "Общие данные";
  const visitedMonthIdRef = useRef(monthId);

  useEffect(() => {
    setVisitedSections((previous) => {
      if (visitedMonthIdRef.current !== monthId) {
        visitedMonthIdRef.current = monthId;
        return new Set([activeSection]);
      }
      if (previous.has(activeSection)) return previous;
      const next = new Set(previous);
      next.add(activeSection);
      return next;
    });
  }, [activeSection, monthId]);
  const visitedSectionsForMonth =
    visitedMonthIdRef.current === monthId
      ? visitedSections
      : new Set<MonthSectionId>([activeSection]);

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
        const [monthData, incomeData, summary, dashboard] = await Promise.all([
          getMonth(monthId, signal),
          listIncomes(monthId, signal),
          getMonthSummary(monthId, signal),
          getDashboard(monthId, signal).catch(() => null),
        ]);
        if (signal?.aborted) return;

        setMonth(monthData);
        setIncomes(incomeData);
        const next = formFromData(monthData, incomeData);
        setForm(next);
        setBaseline(next);
        setCalcTax(moneyAmount(summary.salary_tax.tax));
        setCalcNet(moneyAmount(summary.salary_tax.calculated_net));
        const salaryTax = summary.salary_tax as typeof summary.salary_tax & {
          parts?: SalaryTaxRatePart[];
        };
        setCalcTaxParts(salaryTax.parts ?? []);
        setDashboardKpis(dashboard?.kpis ?? null);
        setDashboardWarnings(dashboard?.warnings ?? []);
      } catch (err) {
        if (!signal?.aborted) {
          setError(formatApiError(err));
          setMonth(null);
          setDashboardKpis(null);
          setDashboardWarnings([]);
        }
      } finally {
        if (!signal?.aborted) setLoading(false);
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
      if (!dirty) return;
      event.preventDefault();
      event.returnValue = "";
    }
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [dirty]);

  function selectSection(sectionId: MonthSectionId) {
    const next = new URLSearchParams(searchParams);
    if (sectionId === "general") next.delete("section");
    else next.set("section", sectionId);
    setSearchParams(next, { replace: true });
  }

  function patchForm<K extends keyof EditorForm>(key: K, value: EditorForm[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
    setSaveOk(null);
  }

  async function handleSave(event: FormEvent) {
    event.preventDefault();
    if (!month || readOnly) return;

    setSaving(true);
    setSaveError(null);
    setSaveOk(null);
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
      setSaveOk("Сохранено.");
    } catch (err) {
      setSaveError(formatApiError(err));
    } finally {
      setSaving(false);
    }
  }

  async function confirmLifecycle() {
    if (!month || !pendingLifecycle) return;
    if (pendingLifecycle === "close" && dirty) return;

    setLifecycleBusy(true);
    setLifecycleError(null);
    try {
      if (pendingLifecycle === "close") await closeMonth(month.id);
      else await reopenMonth(month.id);
      setPendingLifecycle(null);
      await load();
    } catch (err) {
      setLifecycleError(formatApiError(err));
    } finally {
      setLifecycleBusy(false);
    }
  }

  if (loading || (month !== null && month.id !== monthId)) {
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

  const lifecycleButton = readOnly ? (
    <Button
      disabled={lifecycleBusy}
      onClick={() => setPendingLifecycle("reopen")}
      size="sm"
      type="button"
      variant="secondary"
    >
      Открыть для редактирования
    </Button>
  ) : activeSection === "review" ? null : (
    <Button onClick={() => selectSection("review")} size="sm" type="button" variant="primary">
      Проверить и закрыть
    </Button>
  );

  return (
    <section className="month-workspace stack-18">
      <header className="page-header month-workspace__page-header">
        <p className="eyebrow">Месяц</p>
        <h1>{formatMonth(month.year, month.month)}</h1>
        <p className="page-header__description">
          Работай по разделам и переходи между ними в любом порядке — изменения не сохраняются
          автоматически.
        </p>
      </header>

      <StickySubheader
        actions={
          <>
            <Button
              disabled={readOnly || saving || !dirty}
              form="month-core-form"
              size="sm"
              type="submit"
              variant="secondary"
            >
              {saving ? "Сохраняем…" : "Сохранить"}
            </Button>
            {lifecycleButton}
          </>
        }
        className="month-workspace__sticky"
        meta={
          <span className="month-workspace__sticky-meta">
            <Badge tone={month.status === "draft" ? "draft" : "closed"}>
              {labelOf(MONTH_STATUS_LABELS, month.status)}
            </Badge>
            {dirty ? <Badge tone="draft">Не сохранено</Badge> : null}
            <span>Раздел: {activeSectionLabel}</span>
          </span>
        }
        summary={
          <MonthStickySummary kpis={dashboardKpis} warningCount={dashboardWarnings.length} />
        }
        title={formatMonth(month.year, month.month)}
      />

      <nav aria-label="Разделы месяца" className="month-section-nav">
        {MONTH_SECTIONS.map((section) => {
          const isActive = section.id === activeSection;
          const hasUnsaved =
            (section.id === "general" && generalDirty) || (section.id === "income" && incomeDirty);
          const warningCount = section.id === "review" ? dashboardWarnings.length : 0;
          return (
            <button
              aria-current={isActive ? "page" : undefined}
              className={`month-section-nav__item${isActive ? " is-active" : ""}`}
              key={section.id}
              onClick={() => selectSection(section.id)}
              type="button"
            >
              <span>{section.label}</span>
              {hasUnsaved ? (
                <span
                  aria-hidden="true"
                  className="month-section-nav__indicator month-section-nav__indicator--dirty"
                >
                  •
                </span>
              ) : warningCount > 0 ? (
                <span
                  aria-hidden="true"
                  className="month-section-nav__indicator month-section-nav__indicator--warning"
                >
                  {warningCount}
                </span>
              ) : null}
            </button>
          );
        })}
      </nav>

      <div className="toolbar month-workspace__secondary-actions">
        <Link aria-label="К списку месяцев" className="btn btn--ghost" to="/months">
          ← Все месяцы
        </Link>
        <Button onClick={() => setCloneOpen(true)} type="button" variant="ghost">
          Создать следующий месяц
        </Button>
      </div>

      {dirty ? (
        <div className="month-workspace__notice" role="status">
          Есть несохранённые изменения. Между разделами можно переходить свободно; перед выходом из
          редактора сохрани их вручную.
        </div>
      ) : null}
      {saveError ? (
        <div className="inline-alert inline-alert--error" role="alert">
          {saveError}
        </div>
      ) : null}
      {lifecycleError ? (
        <div className="inline-alert inline-alert--error" role="alert">
          {lifecycleError}
        </div>
      ) : null}
      {saveOk ? (
        <div className="month-workspace__save-ok" role="status">
          {saveOk}
        </div>
      ) : null}

      <form className="month-workspace__core-form" id="month-core-form" onSubmit={handleSave}>
        <section hidden={activeSection !== "general"}>
          <Panel label="Период" title="Общие сведения">
            <div className="editor-grid">
              <Field htmlFor="period-label" label="Период">
                <Input id="period-label" readOnly value={formatMonth(month.year, month.month)} />
              </Field>
              <Field htmlFor="status" label="Статус">
                <Input id="status" readOnly value={labelOf(MONTH_STATUS_LABELS, month.status)} />
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
                <Input id="source" readOnly value={labelOf(SOURCE_LABELS, month.source)} />
              </Field>
            </div>
            <details className="field-details">
              <summary>Как используется дата снимка</summary>
              <p>Это дата, на которую фиксируются состояния активов и другие данные месяца.</p>
            </details>
          </Panel>
        </section>

        <section hidden={activeSection !== "income"}>
          <Panel label="Доходы" title="Зарплата и прочее">
            <div className="editor-grid">
              <Field htmlFor="salary-gross" label="Зарплата до вычета налогов">
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
              <Field htmlFor="bonus" label="Премия">
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
              <Field htmlFor="side" label="Дополнительный доход">
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
              <Field htmlFor="cashback" label="Кэшбэк (не пассивный доход)">
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
            <details className="field-details">
              <summary>О расчёте и кэшбэке</summary>
              <p>
                Кэшбэк учитывается отдельно и не входит в пассивный доход. Расчётные значения
                обновляются после ручного сохранения.
              </p>
            </details>
          </Panel>
        </section>
      </form>

      {visitedSectionsForMonth.has("assets") ? (
        <section hidden={activeSection !== "assets"}>
          <MonthAssetsSection monthId={month.id} readOnly={readOnly} />
        </section>
      ) : null}

      {visitedSectionsForMonth.has("positions") ? (
        <section hidden={activeSection !== "positions"}>
          <MonthPositionsSection
            defaultPriceDate={month.snapshot_date}
            monthId={month.id}
            readOnly={readOnly}
          />
        </section>
      ) : null}

      {visitedSectionsForMonth.has("flows") ? (
        <section hidden={activeSection !== "flows"}>
          <MonthFlowsSection
            defaultDate={month.snapshot_date}
            monthId={month.id}
            readOnly={readOnly}
          />
        </section>
      ) : null}

      {visitedSectionsForMonth.has("budget") ? (
        <section hidden={activeSection !== "budget"}>
          <MonthBudgetSection monthId={month.id} readOnly={readOnly} />
        </section>
      ) : null}

      {visitedSectionsForMonth.has("liabilities") ? (
        <section hidden={activeSection !== "liabilities"}>
          <MonthLiabilitiesSection monthId={month.id} readOnly={readOnly} />
        </section>
      ) : null}

      {visitedSectionsForMonth.has("note") ? (
        <section hidden={activeSection !== "note"}>
          <MonthNoteSection monthId={month.id} readOnly={readOnly} />
        </section>
      ) : null}

      {visitedSectionsForMonth.has("review") ? (
        <section hidden={activeSection !== "review"}>
          <MonthReviewSection
            dirty={dirty}
            monthId={month.id}
            onStatusChanged={() => void load()}
            readOnly={readOnly}
            status={month.status === "closed" ? "closed" : "draft"}
          />
        </section>
      ) : null}

      <CloneMonthDialog
        onCancel={() => setCloneOpen(false)}
        onCloned={(cloned) => {
          setCloneOpen(false);
          navigate(`/months/${cloned.id}`);
        }}
        open={cloneOpen}
        source={month}
      />

      <ConfirmDialog
        busy={lifecycleBusy}
        cancelLabel="Отмена"
        confirmLabel={pendingLifecycle === "close" ? "Закрыть" : "Открыть"}
        danger={pendingLifecycle === "close"}
        description={
          pendingLifecycle === "close"
            ? "Закрыть месяц? Данные будут зафиксированы до явного повторного открытия."
            : "Открыть месяц для редактирования? Данные снова станут изменяемыми."
        }
        onCancel={() => setPendingLifecycle(null)}
        onConfirm={() => void confirmLifecycle()}
        open={pendingLifecycle !== null}
        title={pendingLifecycle === "close" ? "Закрыть месяц?" : "Открыть месяц?"}
      />
    </section>
  );
}

function MonthStickySummary({
  kpis,
  warningCount,
}: {
  kpis: DashboardKpis | null;
  warningCount: number;
}) {
  if (!kpis) {
    const fallback =
      warningCount > 0 ? `${warningCount} предупреждений` : "Краткие показатели недоступны";
    return <span className="month-workspace__summary-item">{fallback}</span>;
  }

  return (
    <div className="month-workspace__summary">
      <span className="month-workspace__summary-item">
        Капитал <strong>{formatMoney(moneyAmount(kpis.liquid_capital_net))}</strong>
      </span>
      <span className="month-workspace__summary-item">
        Пассивный доход <strong>{formatMoney(moneyAmount(kpis.passive_income_average))}</strong>
      </span>
      <span className={`month-workspace__summary-item${warningCount > 0 ? " is-warning" : ""}`}>
        {warningCount > 0 ? `${warningCount} предупреждений` : "Без предупреждений"}
      </span>
    </div>
  );
}
