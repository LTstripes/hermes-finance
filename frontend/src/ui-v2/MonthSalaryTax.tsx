import { useQuery } from "@tanstack/react-query";

import { listIncomes } from "../api/incomes";
import { getMonthSummary } from "../api/summary";
import type { MoneyValue } from "../api/types";
import { formatRateBps } from "../components/SalaryTaxRateSummary";
import { normalizeMoneyInput, toKopecks } from "../lib/money";
import styles from "./MonthSalaryTax.module.css";
import { moneyText } from "./valueFormat";

/** Owner decision 15.11.2026: explain only differences above 1 000 RUB (100 000 kopecks). */
const MATERIAL_NET_DIFFERENCE_KOPECKS = 100_000n;

function known(value: MoneyValue | null | undefined): value is MoneyValue {
  return value != null && normalizeMoneyInput(value.amount ?? "") != null;
}

/** Read-only API facts. No tax, gross or effective-rate calculation in the UI. */
export function MonthSalaryTax({ monthId, report = false }: { monthId: number; report?: boolean }) {
  const summary = useQuery({
    queryKey: ["month-income-summary", monthId],
    queryFn: ({ signal }) => getMonthSummary(monthId, signal, false),
    retry: false,
  });
  const incomes = useQuery({
    queryKey: ["month-income", monthId],
    queryFn: ({ signal }) => listIncomes(monthId, signal),
    retry: false,
  });
  // Failed/refetching reads must never leave the previous tax displayed as current.
  const data = summary.isSuccess && !summary.isFetching ? summary.data : undefined;
  const tax = data?.salary_tax;
  if (data?.month.id !== monthId || !known(tax?.tax)) return null;

  const salaries =
    incomes.isSuccess && !incomes.isFetching
      ? incomes.data.filter(
          (row) => row.reporting_month_id === monthId && row.income_type === "salary",
        )
      : [];
  if (
    salaries.length === 0 ||
    salaries.some((row) => row.actual_fact_origin === "clone_template_v1")
  )
    return null;
  // Legacy multiple rows have no gross total in summary; do not invent one here.
  const gross = salaries.length === 1 ? salaries[0].gross_amount : undefined;
  const actual = data.salary_actual_net;
  const calculated = tax.calculated_net;
  const rates = [...new Set(tax.parts?.map((part) => part.rate_bps) ?? [])]
    .filter((rate) => Number.isInteger(rate) && rate >= 0)
    .map(formatRateBps);
  // Display threshold only: compares two backend facts, shows no derived delta.
  const gap =
    known(actual) && known(calculated) && actual.currency === calculated.currency
      ? toKopecks(actual.amount) - toKopecks(calculated.amount)
      : 0n;
  const mismatch = gap > MATERIAL_NET_DIFFERENCE_KOPECKS || -gap > MATERIAL_NET_DIFFERENCE_KOPECKS;

  return (
    <section
      aria-label="Налог на зарплату"
      className={styles.summary}
      data-report={report || undefined}
    >
      {report ? <h2>Зарплата</h2> : null}
      <p className={styles.flow}>
        {known(gross) ? (
          <>
            <span>
              До налога <strong>{moneyText(gross)}</strong>
            </span>
            <span aria-hidden="true">→</span>
          </>
        ) : null}
        <span>
          Налог{rates.length ? ` (${rates.join(" + ")})` : ""} <strong>{moneyText(tax.tax)}</strong>
        </span>
        {known(actual) ? (
          <>
            <span aria-hidden="true">→</span>
            <span>
              На руки <strong>{moneyText(actual)}</strong>
            </span>
          </>
        ) : null}
      </p>
      {mismatch ? (
        <p className={styles.difference}>
          Фактически на руки {moneyText(actual)}, по расчёту — {moneyText(calculated)}. Выплата
          отличается от расчётной.
        </p>
      ) : null}
    </section>
  );
}
