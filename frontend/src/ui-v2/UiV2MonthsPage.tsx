import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useRef, useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";

import { formatApiError } from "../api/client";
import { cloneMonth, createMonth, deleteMonth, listMonths } from "../api/months";
import type { ReportingMonth } from "../api/types";
import {
  monthlyCloseReturnPath,
  parseMonthlyCloseReturnContext,
  withMonthlyCloseReturn,
} from "../components/month-close/navigation";
import { ConfirmDialog, OverflowMenu, OverflowMenuItem } from "../components/ui";
import { getCapitalComposition, getPassiveIncomeHistory } from "../api/analytics";
import { formatMonth } from "../lib/format";
import { lastDayOfMonth, nextPeriod } from "../lib/period";
import { queryKeys } from "../queryClient";
import { UiV2Shell } from "./UiV2Shell";
import { isQueryReady } from "./UiV2StateBlocks";
import { moneyText, moneyWholeText } from "./valueFormat";
import { groupMonthsWithoutCapital, matchingCapitalPoint } from "./reportsArchive";
import {
  latestClosedMonth,
  monthWorkspacePath,
  resolveMonthSelection,
  sortReportingMonths,
} from "./monthSelection";
import { CURRENT_ROW_ACTION, reportPath } from "./reportsArchive";
import styles from "./UiV2Months.module.css";

type Target = { year: number; month: number; snapshot_date: string };
type Action = { kind: "create" } | { kind: "clone"; source: ReportingMonth };

const MONTHS = [
  "Январь",
  "Февраль",
  "Март",
  "Апрель",
  "Май",
  "Июнь",
  "Июль",
  "Август",
  "Сентябрь",
  "Октябрь",
  "Ноябрь",
  "Декабрь",
];

function initialTarget(): Target {
  const today = new Date();
  const year = today.getFullYear();
  const month = today.getMonth() + 1;
  return { year, month, snapshot_date: lastDayOfMonth(year, month) };
}

function isConfirmedMonth(value: ReportingMonth, target: Target): boolean {
  return (
    Number.isSafeInteger(value.id) &&
    value.id > 0 &&
    value.status === "draft" &&
    value.year === target.year &&
    value.month === target.month &&
    value.snapshot_date === target.snapshot_date
  );
}

export default function UiV2MonthsPage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const monthsQuery = useQuery({
    queryKey: queryKeys.months,
    queryFn: ({ signal }) => listMonths(signal),
  });
  const months = useMemo(() => sortReportingMonths(monthsQuery.data ?? []), [monthsQuery.data]);
  const selection = resolveMonthSelection(params.getAll("month"), months);
  const selected = selection.kind === "selected" ? selection.month : null;
  const closeContext = parseMonthlyCloseReturnContext(params);
  const returnToClose =
    closeContext && months.some((month) => month.id === closeContext.monthId)
      ? monthlyCloseReturnPath(closeContext)
      : null;
  const latest = months[0] ?? null;
  const latestClosed = latestClosedMonth(months);
  const compositionQuery = useQuery({
    enabled: latestClosed !== null,
    queryKey: queryKeys.capitalComposition,
    queryFn: ({ signal }) => getCapitalComposition(signal),
  });
  const incomeQuery = useQuery({
    enabled: latestClosed !== null,
    queryKey: queryKeys.passiveIncomeHistory(latestClosed?.id ?? null),
    queryFn: ({ signal }) => getPassiveIncomeHistory(latestClosed!.id, signal),
  });
  const capitalConfirmed =
    isQueryReady(monthsQuery) &&
    isQueryReady(compositionQuery) &&
    compositionQuery.data?.points.at(-1)?.reporting_month_id === latestClosed?.id;
  const incomeConfirmed =
    isQueryReady(monthsQuery) &&
    isQueryReady(incomeQuery) &&
    incomeQuery.data?.latest_closed_report_id === latestClosed?.id;
  const capitalFor = (month: ReportingMonth) =>
    capitalConfirmed ? matchingCapitalPoint(month, compositionQuery.data?.points ?? []) : null;
  const incomeFor = (month: ReportingMonth) =>
    incomeConfirmed && month.status === "closed"
      ? incomeQuery.data?.points.find(
          (item) =>
            item.reporting_month_id === month.id &&
            item.year === month.year &&
            item.month === month.month &&
            item.snapshot_date === month.snapshot_date,
        )?.passive_income_actual
      : null;
  const groups =
    compositionQuery.isPending || compositionQuery.isFetching
      ? months.map((month) => [month])
      : groupMonthsWithoutCapital(months, capitalFor);
  const [action, setAction] = useState<Action | null>(null);
  const [target, setTarget] = useState<Target>(initialTarget);
  const [pendingDelete, setPendingDelete] = useState<ReportingMonth | null>(null);
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  function selectMonth(id: number | null) {
    const next = new URLSearchParams(params);
    if (id === null) next.delete("month");
    else next.set("month", String(id));
    setParams(next, { replace: true });
  }

  function startCreate() {
    if (busyRef.current) return;
    setAction({ kind: "create" });
    setTarget(initialTarget());
    setError(null);
    setNotice(null);
  }

  function startClone(source: ReportingMonth) {
    if (busyRef.current) return;
    const next = nextPeriod(source.year, source.month);
    setAction({ kind: "clone", source });
    setTarget({ ...next, snapshot_date: lastDayOfMonth(next.year, next.month) });
    setError(null);
    setNotice(null);
  }

  async function readBack() {
    const result = await monthsQuery.refetch();
    if (!result.isSuccess || !result.data) throw new Error("Список месяцев не удалось перечитать.");
    return result.data;
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!action || busyRef.current || monthsQuery.isError) return;
    busyRef.current = true;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const created =
        action.kind === "clone"
          ? await cloneMonth(action.source.id, target)
          : await createMonth({ ...target, source: "manual" });
      if (!isConfirmedMonth(created, target))
        throw new Error("Ответ не подтверждает созданный черновик.");
      const fresh = await readBack();
      const confirmed = fresh.find((month) => month.id === created.id);
      if (!confirmed || !isConfirmedMonth(confirmed, target)) {
        throw new Error("Созданный черновик не подтверждён обновлённым списком.");
      }
      await queryClient.invalidateQueries({ refetchType: "none" });
      selectMonth(created.id);
      setAction(null);
      setNotice(
        `Черновик ${formatMonth(created.year, created.month)} подтверждён обновлённым списком.`,
      );
    } catch (cause) {
      setError(`${formatApiError(cause)} Проверь обновлённый список перед повторной отправкой.`);
      await queryClient.invalidateQueries({ refetchType: "none" });
      void monthsQuery.refetch();
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }

  async function confirmDelete() {
    const month = pendingDelete;
    if (!month || busyRef.current || monthsQuery.isError) return;
    if (months.find((row) => row.id === month.id)?.status !== "draft") {
      setPendingDelete(null);
      setError("Черновик изменился. Обнови список перед удалением.");
      return;
    }
    busyRef.current = true;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await deleteMonth(month.id);
      const fresh = await readBack();
      if (fresh.some((row) => row.id === month.id)) {
        throw new Error("Удаление не подтверждено обновлённым списком.");
      }
      await queryClient.invalidateQueries({ refetchType: "none" });
      if (params.getAll("month").length === 1 && params.get("month") === String(month.id)) {
        selectMonth(null);
      }
      setPendingDelete(null);
      setNotice(`Черновик ${formatMonth(month.year, month.month)} удалён.`);
    } catch (cause) {
      setPendingDelete(null);
      setError(`${formatApiError(cause)} Проверь обновлённый список перед повторной отправкой.`);
      await queryClient.invalidateQueries({ refetchType: "none" });
      void monthsQuery.refetch();
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }

  function monthActions(month: ReportingMonth) {
    return (
      <div className={styles.actions}>
        <Link className={styles.primary} to={monthWorkspacePath(month.id)}>
          Открыть
        </Link>
        <OverflowMenu label={`Действия месяца ${formatMonth(month.year, month.month)}`}>
          <OverflowMenuItem disabled={busy} onClick={() => startClone(month)}>
            Копировать
          </OverflowMenuItem>
          <OverflowMenuItem
            onClick={() =>
              navigate(
                closeContext?.monthId === month.id
                  ? withMonthlyCloseReturn(
                      `/v2/data/months/${month.id}`,
                      month.id,
                      closeContext.step,
                      closeContext.origin,
                    )
                  : `/v2/data/months/${month.id}`,
              )
            }
          >
            Редактор
          </OverflowMenuItem>
          {month.status === "closed" ? (
            <OverflowMenuItem
              onClick={() => navigate(latestClosed?.id === month.id ? "/v2" : reportPath(month.id))}
            >
              {latestClosed?.id === month.id ? CURRENT_ROW_ACTION : "Посмотреть отчёт"}
            </OverflowMenuItem>
          ) : (
            <OverflowMenuItem danger disabled={busy} onClick={() => setPendingDelete(month)}>
              Удалить черновик
            </OverflowMenuItem>
          )}
        </OverflowMenu>
      </div>
    );
  }
  function monthName(month: ReportingMonth) {
    return (
      <>
        <span>{formatMonth(month.year, month.month)}</span>
        {selected?.id === month.id ? <span className={styles.selected}>Выбран</span> : null}
      </>
    );
  }
  function monthRow(month: ReportingMonth) {
    const point = capitalFor(month);
    const income = incomeFor(month);
    const coverage = point?.portfolio_source_coverage;
    const partial =
      coverage?.status === "partial" ||
      coverage?.source_account_financial_coverage?.status === "partial";
    const capital = coverage?.status === "unavailable" ? null : point?.liquid_capital_net;
    return (
      <tr key={month.id} data-testid={`reports-row-${month.id}`}>
        <th scope="row">{monthName(month)}</th>
        <td>{month.status === "closed" ? "Закрыт" : "Черновик"}</td>
        <td className={styles.money} title={moneyText(capital, "—")}>
          {moneyWholeText(capital, "—")}
          {partial && capital ? <small className={styles.hint}>неполный</small> : null}
        </td>
        <td className={styles.money} title={moneyText(income, "—")}>
          {moneyWholeText(income, "—")}
        </td>
        <td>{monthActions(month)}</td>
      </tr>
    );
  }

  return (
    <UiV2Shell
      busy={monthsQuery.isPending || busy}
      showRefresh={false}
      header={<h1>Все месяцы</h1>}
    >
      <div className={styles.toolbar}>
        {returnToClose ? (
          <Link to={returnToClose}>Вернуться к закрытию исходного месяца</Link>
        ) : null}
        <button
          className={styles.primary}
          disabled={monthsQuery.isPending || monthsQuery.isError || busy || !latest}
          onClick={() => {
            if (latest) startClone(latest);
          }}
          type="button"
        >
          Создать следующий месяц
        </button>
        <button
          className={styles.secondary}
          disabled={monthsQuery.isPending || monthsQuery.isError || busy}
          onClick={startCreate}
          type="button"
        >
          Создать другой период
        </button>
        <button
          className={styles.secondary}
          disabled={busy || monthsQuery.isFetching}
          onClick={() => {
            void monthsQuery.refetch();
            if (latestClosed) {
              void compositionQuery.refetch();
              void incomeQuery.refetch();
            }
          }}
          type="button"
        >
          Обновить список
        </button>
      </div>

      {error ? (
        <p className={styles.error} role="alert">
          {error}
        </p>
      ) : null}
      {notice ? (
        <p className={styles.notice} role="status">
          {notice}
        </p>
      ) : null}
      {monthsQuery.isError ? (
        <p className={styles.error} role="alert">
          Список месяцев недоступен: {formatApiError(monthsQuery.error)}. Повтори загрузку.
        </p>
      ) : null}
      {selection.kind === "invalid" ? (
        <p className={styles.error} role="alert">
          Некорректный параметр month. Выбери период из списка; подмена не выполняется.
        </p>
      ) : selection.kind === "missing" && !monthsQuery.isError && !monthsQuery.isPending ? (
        <p className={styles.error} role="alert">
          Запрошенный месяц не найден. Выбери другой период явно.
        </p>
      ) : null}

      {action ? (
        <section
          className={styles.panel}
          aria-label={action.kind === "clone" ? "Копирование месяца" : "Создание месяца"}
        >
          <h2>{action.kind === "clone" ? "Копировать данные" : "Создать отчётный месяц"}</h2>
          {action.kind === "clone" ? (
            <>
              <p>
                Источник: <strong>{formatMonth(action.source.year, action.source.month)}</strong> ·{" "}
                {action.source.status === "closed" ? "закрыт" : "черновик"}. Цель: новый черновик,
                указанный ниже.
              </p>
              <p className={styles.hint}>
                Копируются позиции, депозиты, денежные средства, обязательные расходы, накопления,
                долги, недвижимость и шаблон регулярной зарплаты. Фактический процент вкладов
                обнуляется; прогноз пересчитывается. Инвестиционные потоки и прогноз, необязательные
                расходы, премии, кэшбэк, комментарии, закрытые результаты и подтверждения не
                переносятся.
              </p>
            </>
          ) : (
            <p>Укажи период и дату снимка. Дубликат периода и некорректную дату отклоняет API.</p>
          )}
          <form
            className={styles.form}
            onSubmit={(event) => {
              void submit(event);
            }}
          >
            <label>
              Целевой год
              <input
                max={9999}
                min={1}
                onChange={(event) => {
                  const year = Number(event.target.value);
                  setTarget((value) => ({
                    ...value,
                    year,
                    snapshot_date: lastDayOfMonth(year, value.month),
                  }));
                }}
                required
                type="number"
                value={target.year}
              />
            </label>
            <label>
              Целевой месяц
              <select
                onChange={(event) => {
                  const month = Number(event.target.value);
                  setTarget((value) => ({
                    ...value,
                    month,
                    snapshot_date: lastDayOfMonth(value.year, month),
                  }));
                }}
                value={target.month}
              >
                {MONTHS.map((label, index) => (
                  <option key={label} value={index + 1}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Дата снимка нового периода
              <input
                onChange={(event) =>
                  setTarget((value) => ({ ...value, snapshot_date: event.target.value }))
                }
                required
                type="date"
                value={target.snapshot_date}
              />
            </label>
            <div className={styles.actions}>
              <button className={styles.primary} disabled={busy} type="submit">
                {busy
                  ? "Сохраняем…"
                  : action.kind === "clone"
                    ? "Копировать данные"
                    : "Создать месяц"}
              </button>
              <button
                className={styles.secondary}
                disabled={busy}
                onClick={() => setAction(null)}
                type="button"
              >
                Отмена
              </button>
            </div>
          </form>
        </section>
      ) : null}

      <section className={styles.panel} aria-label="Список отчётных месяцев">
        {monthsQuery.isPending ? <p role="status">Загружаем месяцы…</p> : null}
        {!monthsQuery.isPending && !monthsQuery.isError && months.length === 0 ? (
          <p>Периодов пока нет. Создай первый отчётный месяц.</p>
        ) : null}
        {!monthsQuery.isError && months.length > 0 ? (
          <>
            {latestClosed && (compositionQuery.isError || incomeQuery.isError) ? (
              <p className={styles.hint} role="status">
                Часть сумм недоступна. Обнови список, чтобы повторить чтение.
              </p>
            ) : null}
            <table
              aria-label="Отчётные месяцы"
              className={styles.monthTable}
              data-testid="months-table"
            >
              <thead>
                <tr>
                  <th scope="col">Месяц</th>
                  <th scope="col">Статус</th>
                  <th scope="col" className={styles.money}>
                    Ликвидный капитал
                  </th>
                  <th scope="col" className={styles.money}>
                    Пассивный доход
                  </th>
                  <th scope="col">Действие</th>
                </tr>
              </thead>
              <tbody>
                {groups.map((group) =>
                  group.length === 1 ? (
                    monthRow(group[0])
                  ) : (
                    <tr key={`group-${group[0].id}`}>
                      <td colSpan={5}>
                        <details className={styles.missingGroup}>
                          <summary>
                            {formatMonth(group.at(-1)!.year, group.at(-1)!.month)} —{" "}
                            {formatMonth(group[0].year, group[0].month)} · без капитала ·{" "}
                            {group.length} мес.
                          </summary>
                          <ul className={styles.list}>
                            {group.map((month) => (
                              <li className={styles.row} key={month.id}>
                                <div>
                                  {monthName(month)}
                                  <span className={styles.hint}>Закрыт · капитал —</span>
                                </div>
                                <span
                                  className={styles.money}
                                  title={moneyText(incomeFor(month), "—")}
                                >
                                  Пассивный доход: {moneyWholeText(incomeFor(month), "—")}
                                </span>
                                {monthActions(month)}
                              </li>
                            ))}
                          </ul>
                        </details>
                      </td>
                    </tr>
                  ),
                )}
              </tbody>
            </table>
            <p className={styles.hint}>
              Неполный капитал — итог известных записей. Прочерк означает отсутствие подтверждённой
              суммы; черновики не входят в историю закрытых отчётов.
            </p>
          </>
        ) : null}
      </section>
      <ConfirmDialog
        busy={busy}
        cancelLabel="Отмена"
        confirmLabel="Удалить черновик"
        danger
        description={
          pendingDelete
            ? `Удалить черновик ${formatMonth(pendingDelete.year, pendingDelete.month)}? Действие необратимо. Закрытые месяцы не удаляются.`
            : ""
        }
        onCancel={() => {
          if (!busyRef.current) setPendingDelete(null);
        }}
        onConfirm={() => {
          void confirmDelete();
        }}
        open={pendingDelete !== null}
        title="Удалить черновик?"
      />
    </UiV2Shell>
  );
}
