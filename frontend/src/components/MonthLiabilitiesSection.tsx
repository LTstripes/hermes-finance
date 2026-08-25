import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";

import { formatApiError } from "../api/client";
import { getDashboard } from "../api/dashboard";
import { createDebt, deleteDebt, listDebts, updateDebt } from "../api/debts";
import { createProperty, deleteProperty, listProperties, updateProperty } from "../api/properties";
import { getMonthSummary } from "../api/summary";
import type { DashboardMortgage, DebtEntry, PropertySnapshot } from "../api/types";
import {
  Badge,
  Button,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  Field,
  Input,
  LoadingState,
  Panel,
  Select,
  Table,
  Td,
  Th,
  OverflowMenu,
  OverflowMenuItem,
} from "./ui";
import { formatMoney } from "../lib/format";
import { DEBT_TYPE_LABELS, labelOf } from "../lib/labels";
import { moneyAmount, normalizeMoneyInput, rub, sumMoneyAmounts } from "../lib/money";

type Props = { monthId: number; readOnly: boolean; onDirtyChange?: (dirty: boolean) => void };

type DebtDraft = {
  name: string;
  debt_type: string;
  current_balance: string;
  include_in_liquid_capital: boolean;
};

type PropertyDraft = {
  name: string;
  estimated_value: string;
  mortgage_balance: string;
  monthly_payment: string;
};

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
  const [editingDebtId, setEditingDebtId] = useState<number | null>(null);
  const [editDebt, setEditDebt] = useState<DebtDraft | null>(null);
  const [editingPropId, setEditingPropId] = useState<number | null>(null);
  const [editProp, setEditProp] = useState<PropertyDraft | null>(null);

  const localDirty =
    debtDraftTouched || propertyDraftTouched || editingDebtId !== null || editingPropId !== null;

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

  async function handleSaveDebtEdit() {
    if (editingDebtId == null || !editDebt) {
      return;
    }
    setBusy(true);
    setActionError(null);
    try {
      if (!editDebt.name.trim() || !normalizeMoneyInput(editDebt.current_balance)) {
        throw new Error("Имя и баланс долга обязательны");
      }
      await updateDebt(editingDebtId, {
        name: editDebt.name.trim(),
        debt_type: editDebt.debt_type,
        current_balance: rub(editDebt.current_balance),
        include_in_liquid_capital: editDebt.include_in_liquid_capital,
      });
      setEditingDebtId(null);
      setEditDebt(null);
      await load();
    } catch (err) {
      setActionError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleSavePropertyEdit() {
    if (editingPropId == null || !editProp) {
      return;
    }
    setBusy(true);
    setActionError(null);
    try {
      if (
        !editProp.name.trim() ||
        !normalizeMoneyInput(editProp.estimated_value) ||
        !normalizeMoneyInput(editProp.mortgage_balance) ||
        !normalizeMoneyInput(editProp.monthly_payment)
      ) {
        throw new Error("Заполни название, стоимость, остаток ипотеки и платёж");
      }
      await updateProperty(editingPropId, {
        name: editProp.name.trim(),
        estimated_value: rub(editProp.estimated_value),
        mortgage_balance: rub(editProp.mortgage_balance),
        monthly_payment: rub(editProp.monthly_payment),
      });
      setEditingPropId(null);
      setEditProp(null);
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
  if (error)
    return <ErrorState description={error} inline title="Не удалось загрузить обязательства" />;

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
          <Table className="month-debts-table">
            <thead>
              <tr>
                <Th className="month-debts-table__name">Название</Th>
                <Th className="month-debts-table__type">Тип</Th>
                <Th numeric>Баланс</Th>
                <Th className="month-debts-table__inclusion">Учёт</Th>
                <Th className="month-debts-table__actions">Действия</Th>
              </tr>
            </thead>
            <tbody>
              {debts.map((row) => {
                const editing = editingDebtId === row.id && editDebt;
                return (
                  <tr key={row.id}>
                    <Td>
                      {editing ? (
                        <Input
                          aria-label="Название долга"
                          onChange={(e) => setEditDebt({ ...editDebt, name: e.target.value })}
                          value={editDebt.name}
                        />
                      ) : (
                        row.name
                      )}
                    </Td>
                    <Td>
                      {editing ? (
                        <Select
                          aria-label="Тип долга"
                          onChange={(e) => setEditDebt({ ...editDebt, debt_type: e.target.value })}
                          value={editDebt.debt_type}
                        >
                          <option value="credit_card">Кредитная карта</option>
                          <option value="other">Прочее</option>
                        </Select>
                      ) : (
                        labelOf(DEBT_TYPE_LABELS, row.debt_type)
                      )}
                    </Td>
                    <Td numeric>
                      {editing ? (
                        <Input
                          aria-label="Текущий баланс долга"
                          className="input--money"
                          onChange={(e) =>
                            setEditDebt({ ...editDebt, current_balance: e.target.value })
                          }
                          value={editDebt.current_balance}
                        />
                      ) : (
                        formatMoney(moneyAmount(row.current_balance))
                      )}
                    </Td>
                    <Td>
                      {editing ? (
                        <label className="check-row">
                          <input
                            checked={editDebt.include_in_liquid_capital}
                            onChange={(e) =>
                              setEditDebt({
                                ...editDebt,
                                include_in_liquid_capital: e.target.checked,
                              })
                            }
                            type="checkbox"
                          />
                          В капитале
                        </label>
                      ) : (
                        <Badge tone={row.include_in_liquid_capital ? "ok" : "neutral"}>
                          {row.include_in_liquid_capital ? "В капитале" : "Отдельно"}
                        </Badge>
                      )}
                    </Td>
                    <Td className="month-debts-table__actions">
                      <div className="row-actions">
                        {editing ? (
                          <>
                            <Button
                              disabled={busy || readOnly}
                              onClick={() => void handleSaveDebtEdit()}
                              size="sm"
                              type="button"
                              variant="primary"
                            >
                              OK
                            </Button>
                            <Button
                              disabled={busy}
                              onClick={() => {
                                setEditingDebtId(null);
                                setEditDebt(null);
                              }}
                              size="sm"
                              type="button"
                            >
                              Отмена
                            </Button>
                          </>
                        ) : (
                          <OverflowMenu label={`Действия для долга «${row.name}»`}>
                            <OverflowMenuItem
                              disabled={busy || readOnly}
                              onClick={() => {
                                setEditingDebtId(row.id);
                                setEditDebt({
                                  name: row.name,
                                  debt_type: row.debt_type,
                                  current_balance: moneyAmount(row.current_balance),
                                  include_in_liquid_capital: row.include_in_liquid_capital,
                                });
                              }}
                            >
                              Изменить
                            </OverflowMenuItem>
                            <OverflowMenuItem
                              danger
                              disabled={busy || readOnly}
                              onClick={() => setDelDebt(row)}
                            >
                              Удалить
                            </OverflowMenuItem>
                          </OverflowMenu>
                        )}
                      </div>
                    </Td>
                  </tr>
                );
              })}
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
          <Table className="month-property-table">
            <thead>
              <tr>
                <Th className="month-property-table__name">Объект</Th>
                <Th numeric>Стоимость</Th>
                <Th numeric>Ипотека</Th>
                <Th numeric>Платёж / мес</Th>
                <Th className="month-property-table__actions">Действия</Th>
              </tr>
            </thead>
            <tbody>
              {properties.map((row) => {
                const editing = editingPropId === row.id && editProp;
                return (
                  <tr key={row.id}>
                    <Td>
                      {editing ? (
                        <Input
                          aria-label="Название объекта"
                          onChange={(e) => setEditProp({ ...editProp, name: e.target.value })}
                          value={editProp.name}
                        />
                      ) : (
                        row.name
                      )}
                    </Td>
                    <Td numeric>
                      {editing ? (
                        <Input
                          aria-label="Стоимость"
                          className="input--money"
                          onChange={(e) =>
                            setEditProp({ ...editProp, estimated_value: e.target.value })
                          }
                          value={editProp.estimated_value}
                        />
                      ) : (
                        formatMoney(moneyAmount(row.estimated_value))
                      )}
                    </Td>
                    <Td numeric>
                      {editing ? (
                        <Input
                          aria-label="Остаток ипотеки"
                          className="input--money"
                          onChange={(e) =>
                            setEditProp({ ...editProp, mortgage_balance: e.target.value })
                          }
                          value={editProp.mortgage_balance}
                        />
                      ) : (
                        formatMoney(moneyAmount(row.mortgage_balance))
                      )}
                    </Td>
                    <Td numeric>
                      {editing ? (
                        <Input
                          aria-label="Ежемесячный платёж"
                          className="input--money"
                          onChange={(e) =>
                            setEditProp({ ...editProp, monthly_payment: e.target.value })
                          }
                          value={editProp.monthly_payment}
                        />
                      ) : (
                        formatMoney(moneyAmount(row.monthly_payment))
                      )}
                    </Td>
                    <Td className="month-property-table__actions">
                      <div className="row-actions">
                        {editing ? (
                          <>
                            <Button
                              disabled={busy || readOnly}
                              onClick={() => void handleSavePropertyEdit()}
                              size="sm"
                              type="button"
                              variant="primary"
                            >
                              OK
                            </Button>
                            <Button
                              disabled={busy}
                              onClick={() => {
                                setEditingPropId(null);
                                setEditProp(null);
                              }}
                              size="sm"
                              type="button"
                            >
                              Отмена
                            </Button>
                          </>
                        ) : (
                          <OverflowMenu label={`Действия для объекта «${row.name}»`}>
                            <OverflowMenuItem
                              disabled={busy || readOnly}
                              onClick={() => {
                                setEditingPropId(row.id);
                                setEditProp({
                                  name: row.name,
                                  estimated_value: moneyAmount(row.estimated_value),
                                  mortgage_balance: moneyAmount(row.mortgage_balance),
                                  monthly_payment: moneyAmount(row.monthly_payment),
                                });
                              }}
                            >
                              Изменить
                            </OverflowMenuItem>
                            <OverflowMenuItem
                              danger
                              disabled={busy || readOnly}
                              onClick={() => setDelProp(row)}
                            >
                              Удалить
                            </OverflowMenuItem>
                          </OverflowMenu>
                        )}
                      </div>
                    </Td>
                  </tr>
                );
              })}
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
