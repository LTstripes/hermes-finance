import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";

import { formatApiError } from "../api/client";
import { getDashboard } from "../api/dashboard";
import { createDebt, deleteDebt, listDebts } from "../api/debts";
import { createProperty, deleteProperty, listProperties } from "../api/properties";
import { getMonthSummary } from "../api/summary";
import type { DashboardMortgage, DebtEntry, PropertySnapshot } from "../api/types";
import {
  Badge,
  Button,
  ConfirmDialog,
  EmptyState,
  Field,
  Input,
  LoadingState,
  Panel,
  Select,
  Table,
  Td,
  Th,
} from "./ui";
import { formatMoney } from "../lib/format";
import { DEBT_TYPE_LABELS, labelOf } from "../lib/labels";
import { moneyAmount, normalizeMoneyInput, rub, sumMoneyAmounts } from "../lib/money";

type Props = { monthId: number; readOnly: boolean; onDirtyChange?: (dirty: boolean) => void };

export function MonthLiabilitiesSection({ monthId, readOnly, onDirtyChange }: Props) {
  const [debts, setDebts] = useState<DebtEntry[]>([]);
  const [properties, setProperties] = useState<PropertySnapshot[]>([]);
  const [mortgage, setMortgage] = useState<DashboardMortgage | null>(null);
  const [coveragePct, setCoveragePct] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [debtName, setDebtName] = useState("Кредитка");
  const [debtType, setDebtType] = useState("credit_card");
  const [debtBal, setDebtBal] = useState("");
  const [propName, setPropName] = useState("");
  const [propValue, setPropValue] = useState("");
  const [propMortgage, setPropMortgage] = useState("");
  const [propPayment, setPropPayment] = useState("");
  const [debtDraftTouched, setDebtDraftTouched] = useState(false);
  const [propertyDraftTouched, setPropertyDraftTouched] = useState(false);
  const [delDebt, setDelDebt] = useState<DebtEntry | null>(null);
  const [delProp, setDelProp] = useState<PropertySnapshot | null>(null);

  const localDirty = debtDraftTouched || propertyDraftTouched;

  useEffect(() => {
    onDirtyChange?.(localDirty);
  }, [localDirty, onDirtyChange]);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      setLoading(true);
      setError(null);
      try {
        const [d, p, dash, summary] = await Promise.all([
          listDebts(monthId, signal),
          listProperties(monthId, signal),
          getDashboard(monthId, signal).catch(() => null),
          getMonthSummary(monthId, signal).catch(() => null),
        ]);
        if (signal?.aborted) return;
        setDebts(d);
        setProperties(p);
        setMortgage(dash?.mortgage ?? null);
        setCoveragePct(summary?.coverage?.coverage_pct ?? null);
      } catch (err) {
        if (!signal?.aborted) setError(formatApiError(err));
      } finally {
        if (!signal?.aborted) setLoading(false);
      }
    },
    [monthId],
  );

  useEffect(() => {
    const c = new AbortController();
    void load(c.signal);
    return () => c.abort();
  }, [load]);

  const cardDebtTotal = useMemo(
    () =>
      sumMoneyAmounts(
        debts
          .filter((x) => x.debt_type === "credit_card")
          .map((x) => moneyAmount(x.current_balance)),
      ),
    [debts],
  );
  const propertyValueTotal = useMemo(
    () => sumMoneyAmounts(properties.map((x) => moneyAmount(x.estimated_value))),
    [properties],
  );
  const mortgageBalanceTotal = useMemo(
    () => sumMoneyAmounts(properties.map((x) => moneyAmount(x.mortgage_balance))),
    [properties],
  );
  const paymentTotal = useMemo(
    () => sumMoneyAmounts(properties.map((x) => moneyAmount(x.monthly_payment))),
    [properties],
  );

  async function addDebt(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setActionError(null);
    try {
      if (!debtName.trim() || !normalizeMoneyInput(debtBal)) {
        throw new Error("Имя и баланс долга обязательны");
      }
      await createDebt({
        reporting_month_id: monthId,
        debt_type: debtType,
        name: debtName.trim(),
        current_balance: rub(debtBal),
        include_in_liquid_capital: true,
      });
      setDebtBal("");
      setDebtDraftTouched(false);
      await load();
    } catch (err) {
      setActionError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function addProperty(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setActionError(null);
    try {
      if (
        !propName.trim() ||
        !normalizeMoneyInput(propValue) ||
        !normalizeMoneyInput(propMortgage) ||
        !normalizeMoneyInput(propPayment)
      ) {
        throw new Error("Заполни название, стоимость, остаток ипотеки и платёж");
      }
      await createProperty({
        reporting_month_id: monthId,
        name: propName.trim(),
        estimated_value: rub(propValue),
        mortgage_balance: rub(propMortgage),
        monthly_payment: rub(propPayment),
      });
      setPropName("");
      setPropValue("");
      setPropMortgage("");
      setPropPayment("");
      setPropertyDraftTouched(false);
      await load();
    } catch (err) {
      setActionError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <LoadingState description="Загружаем долги и недвижимость…" inline />;
  if (error) return <EmptyState description={error} inline title="Ошибка" />;

  return (
    <div className="stack-18">
      {actionError ? (
        <div className="inline-alert inline-alert--error" role="alert">
          {actionError}
        </div>
      ) : null}

      <Panel
        action={<Badge>CC {formatMoney(cardDebtTotal)}</Badge>}
        label="Обязательства"
        title="Долги"
      >
        {debts.length === 0 ? (
          <EmptyState description="Долгов нет." inline title="Пусто" />
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>Название</Th>
                <Th>Тип</Th>
                <Th numeric>Баланс</Th>
                <Th>В ликвидном капитале</Th>
                <Th>Действия</Th>
              </tr>
            </thead>
            <tbody>
              {debts.map((row) => (
                <tr key={row.id}>
                  <Td>{row.name}</Td>
                  <Td>{labelOf(DEBT_TYPE_LABELS, row.debt_type)}</Td>
                  <Td numeric>{formatMoney(moneyAmount(row.current_balance))}</Td>
                  <Td>{row.include_in_liquid_capital ? "да" : "нет"}</Td>
                  <Td>
                    <Button
                      disabled={busy || readOnly}
                      onClick={() => setDelDebt(row)}
                      size="sm"
                      type="button"
                      variant="danger"
                    >
                      Удал.
                    </Button>
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
        <div className="totals-bar">
          <span>
            Долг по кредитным картам: <strong>{formatMoney(cardDebtTotal)}</strong>
          </span>
        </div>
        {!readOnly ? (
          <form className="form-stack asset-form" onSubmit={addDebt}>
            <div className="editor-grid">
              <Field htmlFor="debt-name" label="Название долга">
                <Input
                  id="debt-name"
                  onChange={(e) => {
                    setDebtName(e.target.value);
                    setDebtDraftTouched(true);
                  }}
                  required
                  value={debtName}
                />
              </Field>
              <Field htmlFor="debt-type" label="Тип долга">
                <Select
                  id="debt-type"
                  onChange={(e) => {
                    setDebtType(e.target.value);
                    setDebtDraftTouched(true);
                  }}
                  value={debtType}
                >
                  <option value="credit_card">Кредитная карта</option>
                  <option value="other">Прочее</option>
                </Select>
              </Field>
              <Field htmlFor="debt-bal" label="Текущий баланс долга">
                <Input
                  className="input--money"
                  id="debt-bal"
                  onChange={(e) => {
                    setDebtBal(e.target.value);
                    setDebtDraftTouched(true);
                  }}
                  required
                  value={debtBal}
                />
              </Field>
            </div>
            <Button disabled={busy} type="submit" variant="primary">
              Добавить долг
            </Button>
          </form>
        ) : null}
      </Panel>

      <Panel
        action={<Badge>RE {formatMoney(propertyValueTotal)}</Badge>}
        label="Обязательства"
        title="Недвижимость"
      >
        <details className="field-details">
          <summary>О недвижимости и покрытии</summary>
          <p>
            Недвижимость не входит в ликвидный капитал. Покрытие ипотеки показывается как ориентир
            из сводки месяца.
          </p>
        </details>
        {properties.length === 0 ? (
          <EmptyState description="Объектов нет." inline title="Пусто" />
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>Объект</Th>
                <Th numeric>Стоимость</Th>
                <Th numeric>Ипотека</Th>
                <Th numeric>Платёж / мес</Th>
                <Th>Действия</Th>
              </tr>
            </thead>
            <tbody>
              {properties.map((row) => (
                <tr key={row.id}>
                  <Td>{row.name}</Td>
                  <Td numeric>{formatMoney(moneyAmount(row.estimated_value))}</Td>
                  <Td numeric>{formatMoney(moneyAmount(row.mortgage_balance))}</Td>
                  <Td numeric>{formatMoney(moneyAmount(row.monthly_payment))}</Td>
                  <Td>
                    <Button
                      disabled={busy || readOnly}
                      onClick={() => setDelProp(row)}
                      size="sm"
                      type="button"
                      variant="danger"
                    >
                      Удал.
                    </Button>
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
        <div className="totals-bar">
          <span>
            Стоимость: <strong>{formatMoney(propertyValueTotal)}</strong>
          </span>
          <span>
            Остаток ипотеки: <strong>{formatMoney(mortgageBalanceTotal)}</strong>
          </span>
          <span>
            Платёж: <strong>{formatMoney(paymentTotal)}</strong>
          </span>
        </div>
        <div className="totals-bar">
          <span>
            Покрытие ипотеки (ориентир):{" "}
            <strong>{mortgage?.coverage_pct != null ? `${mortgage.coverage_pct}%` : "—"}</strong>
          </span>
          <span>
            Недостаток покрытия:{" "}
            <strong>{mortgage ? formatMoney(moneyAmount(mortgage.gap)) : "—"}</strong>
          </span>
          <span>
            Покрытие обязательных расходов:{" "}
            <strong>{coveragePct != null ? `${coveragePct}%` : "—"}</strong>
          </span>
        </div>
        {!readOnly ? (
          <form className="form-stack asset-form" onSubmit={addProperty}>
            <div className="editor-grid">
              <Field htmlFor="prop-name" label="Название объекта">
                <Input
                  id="prop-name"
                  onChange={(e) => {
                    setPropName(e.target.value);
                    setPropertyDraftTouched(true);
                  }}
                  required
                  value={propName}
                />
              </Field>
              <Field htmlFor="prop-val" label="Стоимость">
                <Input
                  className="input--money"
                  id="prop-val"
                  onChange={(e) => {
                    setPropValue(e.target.value);
                    setPropertyDraftTouched(true);
                  }}
                  required
                  value={propValue}
                />
              </Field>
              <Field htmlFor="prop-mort" label="Остаток ипотеки">
                <Input
                  className="input--money"
                  id="prop-mort"
                  onChange={(e) => {
                    setPropMortgage(e.target.value);
                    setPropertyDraftTouched(true);
                  }}
                  required
                  value={propMortgage}
                />
              </Field>
              <Field htmlFor="prop-pay" label="Ежемесячный платёж">
                <Input
                  className="input--money"
                  id="prop-pay"
                  onChange={(e) => {
                    setPropPayment(e.target.value);
                    setPropertyDraftTouched(true);
                  }}
                  required
                  value={propPayment}
                />
              </Field>
            </div>
            <Button disabled={busy} type="submit" variant="primary">
              Добавить объект
            </Button>
          </form>
        ) : null}
      </Panel>

      <ConfirmDialog
        busy={busy}
        cancelLabel="Отмена"
        confirmLabel="Удалить"
        danger
        description={delDebt ? `Удалить долг «${delDebt.name}»?` : ""}
        onCancel={() => setDelDebt(null)}
        onConfirm={() => {
          if (!delDebt) return;
          setBusy(true);
          void deleteDebt(delDebt.id)
            .then(() => load())
            .catch((err) => setActionError(formatApiError(err)))
            .finally(() => {
              setBusy(false);
              setDelDebt(null);
            });
        }}
        open={delDebt !== null}
        title="Удалить долг?"
      />
      <ConfirmDialog
        busy={busy}
        cancelLabel="Отмена"
        confirmLabel="Удалить"
        danger
        description={delProp ? `Удалить «${delProp.name}»?` : ""}
        onCancel={() => setDelProp(null)}
        onConfirm={() => {
          if (!delProp) return;
          setBusy(true);
          void deleteProperty(delProp.id)
            .then(() => load())
            .catch((err) => setActionError(formatApiError(err)))
            .finally(() => {
              setBusy(false);
              setDelProp(null);
            });
        }}
        open={delProp !== null}
        title="Удалить объект?"
      />
    </div>
  );
}
