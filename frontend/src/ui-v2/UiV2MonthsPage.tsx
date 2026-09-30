import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useRef, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router";

import { formatApiError } from "../api/client";
import { cloneMonth, createMonth, deleteMonth, listMonths } from "../api/months";
import type { ReportingMonth } from "../api/types";
import {
  monthlyCloseReturnPath,
  parseMonthlyCloseReturnContext,
  withMonthlyCloseReturn,
} from "../components/month-close/navigation";
import { ConfirmDialog } from "../components/ui";
import { formatDate, formatMonth } from "../lib/format";
import { lastDayOfMonth, nextPeriod } from "../lib/period";
import { queryKeys } from "../queryClient";
import { UiV2DataFrame } from "./UiV2DataShell";
import { resolveMonthSelection, sortReportingMonths } from "./monthSelection";
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
  const queryClient = useQueryClient();
  const monthsQuery = useQuery({
    queryKey: queryKeys.months,
    queryFn: ({ signal }) => listMonths(signal),
    refetchOnWindowFocus: true,
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

  return (
    <UiV2DataFrame
      active="months"
      busy={monthsQuery.isPending || busy}
      monthId={selected?.id}
      subtitle="Создай отчётный период, скопируй данные или удали разрешённый черновик."
      title="Отчётные месяцы"
      v1ReturnPath="/months"
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
        <h2>Все периоды</h2>
        {monthsQuery.isPending ? <p role="status">Загружаем месяцы…</p> : null}
        {!monthsQuery.isPending && !monthsQuery.isError && months.length === 0 ? (
          <p>Периодов пока нет. Создай первый отчётный месяц.</p>
        ) : null}
        {!monthsQuery.isError && months.length > 0 ? (
          <ul className={styles.list}>
            {months.map((month) => (
              <li className={styles.row} key={month.id}>
                <div>
                  <strong>{formatMonth(month.year, month.month)}</strong>{" "}
                  <span className={styles.status}>
                    {month.status === "draft" ? "Черновик" : "Закрыт"}
                  </span>
                  {selected?.id === month.id ? (
                    <span className={styles.selected}>Выбран</span>
                  ) : null}
                  <small>Снимок {formatDate(month.snapshot_date)}</small>
                </div>
                <div className={styles.actions}>
                  <button
                    className={styles.secondary}
                    disabled={busy}
                    onClick={() => selectMonth(month.id)}
                    type="button"
                  >
                    Выбрать
                  </button>
                  <button
                    className={styles.secondary}
                    disabled={busy}
                    onClick={() => startClone(month)}
                    type="button"
                  >
                    Копировать
                  </button>
                  {month.status === "draft" ? (
                    <button
                      className={styles.danger}
                      disabled={busy}
                      onClick={() => setPendingDelete(month)}
                      type="button"
                    >
                      Удалить черновик
                    </button>
                  ) : null}
                  <Link
                    to={
                      closeContext?.monthId === month.id
                        ? withMonthlyCloseReturn(
                            `/v2/data/months/${month.id}`,
                            month.id,
                            closeContext.step,
                            closeContext.origin,
                          )
                        : `/v2/data/months/${month.id}`
                    }
                  >
                    Открыть редактор месяца
                  </Link>
                  <Link to={`/months/${month.id}`}>Редактор в предыдущем интерфейсе ↗</Link>
                </div>
              </li>
            ))}
          </ul>
        ) : null}
        <p className={styles.hint}>
          В native редакторе доступны данные и заметки выбранного месяца. Архив подтверждённых
          отчётов остаётся отдельным разделом.
        </p>
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
    </UiV2DataFrame>
  );
}
