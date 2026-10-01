import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router";

import { ApiClientError, formatApiError } from "../api/client";
import { createComment, deleteComment, listComments, moveComment } from "../api/comments";
import { getMonth, reopenMonth, updateMonth } from "../api/months";
import type { MonthlyComment, ReportingMonth } from "../api/types";
import {
  monthlyCloseReturnPath,
  parseMonthlyCloseReturnContext,
  withMonthlyCloseReturn,
} from "../components/month-close/navigation";
import { ConfirmDialog } from "../components/ui";
import { formatDate, formatMonth } from "../lib/format";
import { SOURCE_LABELS, labelOf } from "../lib/labels";
import { UiV2DataFrame, DataMonthContext } from "./UiV2DataShell";
import styles from "./UiV2MonthEditor.module.css";
import { MonthIncomeSection } from "./MonthIncomeSection";
import { UiV2MonthAssetsSection } from "./UiV2MonthAssetsSection";
import { UiV2MonthPositionsSection } from "./UiV2MonthPositionsSection";
import { UiV2MonthPayoutsSection } from "./UiV2MonthPayoutsSection";
import { UiV2MonthBudgetSection } from "./UiV2MonthBudgetSection";
import { UiV2MonthLiabilities } from "./UiV2MonthLiabilities";

const EDITOR_SECTIONS = {
  general: "Общие данные",
  income: "Зарплата и прочее",
  assets: "Активы",
  positions: "Позиции",
  payouts: "Выплаты",
  budget: "Бюджет",
  liabilities: "Долги и недвижимость",
  note: "Заметки",
} as const;
type EditorSection = keyof typeof EDITOR_SECTIONS;

/** Leaf sections #559–#564 receive this exact-month contract, not a global save action. */
export type MonthEditorContext = {
  month: ReportingMonth;
  readOnly: boolean;
  refresh: () => Promise<ReportingMonth>;
  setDirty: (section: string, dirty: boolean) => void;
  returnToClose: string | null;
};

function validMonthId(value: string | undefined): number | null {
  if (!value || !/^[1-9]\d*$/.test(value)) return null;
  const id = Number(value);
  return Number.isSafeInteger(id) ? id : null;
}

function selectedSection(params: URLSearchParams): EditorSection | null {
  const values = params.getAll("section");
  if (values.length === 0 || (values.length === 1 && values[0] === "general")) return "general";
  if (values.length === 1 && Object.hasOwn(EDITOR_SECTIONS, values[0]))
    return values[0] as EditorSection;
  return null;
}

export default function UiV2MonthEditorPage() {
  const { monthId: rawMonthId } = useParams();
  const monthId = validMonthId(rawMonthId);
  const [params] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  const section = selectedSection(params);
  const monthQuery = useQuery({
    queryKey: ["month-editor", monthId],
    queryFn: ({ signal }) => getMonth(monthId as number, signal),
    enabled: monthId !== null,
    retry: false,
    refetchOnWindowFocus: true,
  });
  const identity = useRef<{ id: number; year: number; month: number } | null>(null);
  if (identity.current?.id !== monthId) identity.current = null;
  const fetchedMonth =
    monthQuery.isSuccess && monthQuery.data.id === monthId ? monthQuery.data : null;
  if (fetchedMonth && !identity.current) identity.current = { ...fetchedMonth };
  const month =
    fetchedMonth &&
    fetchedMonth.year === identity.current?.year &&
    fetchedMonth.month === identity.current?.month
      ? fetchedMonth
      : null;
  const [dirtySections, setDirtySections] = useState<Record<string, boolean>>({});
  const [pendingHref, setPendingHref] = useState<string | null>(null);
  const [rereadNotice, setRereadNotice] = useState<string | null>(null);
  const [rereadVersion, setRereadVersion] = useState(0);
  const historyGuard = useRef(false);
  const allowHistoryPop = useRef(false);
  const setDirty = useCallback(
    (name: string, value: boolean) =>
      setDirtySections((previous) =>
        previous[name] === value ? previous : { ...previous, [name]: value },
      ),
    [],
  );
  const dirty = Object.values(dirtySections).some(Boolean);

  useEffect(() => {
    if (!dirty || monthId === null) return;
    if (!historyGuard.current) {
      allowHistoryPop.current = false;
      historyGuard.current = true;
      window.history.pushState(
        { ...window.history.state, monthEditorDirtyGuard: monthId },
        "",
        window.location.href,
      );
    }
    const onPopState = () => {
      if (allowHistoryPop.current) return;
      if (window.confirm("Есть несохранённые изменения. Перейти и потерять их?")) {
        allowHistoryPop.current = true;
        historyGuard.current = false;
        setDirtySections({});
        window.setTimeout(() => window.history.back(), 0);
      } else {
        window.history.pushState(
          { ...window.history.state, monthEditorDirtyGuard: monthId },
          "",
          window.location.href,
        );
      }
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [dirty, monthId]);

  useEffect(() => {
    if (dirty || !historyGuard.current || window.history.state?.monthEditorDirtyGuard !== monthId)
      return;
    allowHistoryPop.current = true;
    historyGuard.current = false;
    window.history.back();
  }, [dirty, monthId]);

  useEffect(() => {
    if (!dirty) return;
    const guardLinks = (event: MouseEvent) => {
      if (event.button !== 0 || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey)
        return;
      const anchor = (event.target as Element).closest("a[href]");
      if (!anchor || anchor.getAttribute("target") === "_blank") return;
      const url = new URL(anchor.getAttribute("href") ?? "", window.location.href);
      if (url.origin !== window.location.origin) return;
      const next = `${url.pathname}${url.search}${url.hash}`;
      if (next === `${location.pathname}${location.search}${location.hash}`) return;
      event.preventDefault();
      event.stopPropagation();
      setPendingHref(next);
    };
    document.addEventListener("click", guardLinks, true);
    return () => document.removeEventListener("click", guardLinks, true);
  }, [dirty, location.pathname, location.search, location.hash]);

  useEffect(() => {
    if (!dirty) return;
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [dirty]);

  const returnContext = parseMonthlyCloseReturnContext(params);
  const returnToClose =
    returnContext && returnContext.monthId === monthId
      ? monthlyCloseReturnPath(returnContext)
      : null;
  const editorContext: MonthEditorContext | null = month
    ? {
        month,
        readOnly: month.status === "closed",
        refresh: async () => {
          const result = await monthQuery.refetch();
          if (
            !result.isSuccess ||
            result.data.id !== monthId ||
            result.data.year !== month.year ||
            result.data.month !== month.month
          )
            throw new Error("Месяц не подтверждён повторной загрузкой.");
          return result.data;
        },
        setDirty,
        returnToClose,
      }
    : null;

  return (
    <UiV2DataFrame
      active="months"
      busy={monthQuery.isPending || monthQuery.isFetching}
      monthId={monthId ?? undefined}
      subtitle="Данные выбранного месяца сохраняются по разделам. Автоматического общего сохранения нет."
      title="Редактор месяца"
      v1ReturnPath={monthId ? `/months/${monthId}` : "/months"}
    >
      <div className={styles.toolbar}>
        <Link
          to={
            monthId && returnContext?.monthId === monthId
              ? withMonthlyCloseReturn(
                  `/v2/data/months?month=${monthId}`,
                  monthId,
                  returnContext.step,
                  returnContext.origin,
                )
              : monthId
                ? `/v2/data/months?month=${monthId}`
                : "/v2/data/months"
          }
        >
          ← Отчётные месяцы
        </Link>
        {returnToClose ? <Link to={returnToClose}>Вернуться к закрытию</Link> : null}
        {monthId && !returnToClose ? (
          <Link to={`/v2/close?month=${monthId}&step=final_review_close`}>Проверить и закрыть</Link>
        ) : null}
        <button
          disabled={!monthId || monthQuery.isFetching || dirty}
          onClick={async () => {
            setRereadNotice("Перечитываем сохранённые данные…");
            const result = await monthQuery.refetch();
            if (
              result.isSuccess &&
              result.data.id === monthId &&
              result.data.year === month?.year &&
              result.data.month === month?.month
            ) {
              setRereadVersion((value) => value + 1);
            }
            setRereadNotice(
              result.isSuccess &&
                result.data.id === monthId &&
                result.data.year === month?.year &&
                result.data.month === month?.month
                ? "Сведения о месяце перечитаны. Сохранённые данные раздела загружаются заново."
                : "Не удалось перечитать сохранённые данные.",
            );
          }}
          type="button"
        >
          {monthQuery.isFetching ? "Перечитываем…" : "Перечитать сохранённые данные"}
        </button>
      </div>
      {rereadNotice ? <p role="status">{rereadNotice}</p> : null}
      <ConfirmDialog
        cancelLabel="Остаться"
        confirmLabel="Перейти без сохранения"
        description="Есть несохранённые изменения. Перейти и потерять их?"
        onCancel={() => setPendingHref(null)}
        onConfirm={() => {
          if (pendingHref) {
            allowHistoryPop.current = true;
            historyGuard.current = false;
            setDirtySections({});
            setPendingHref(null);
            navigate(pendingHref, { replace: true });
          }
        }}
        open={pendingHref !== null}
        title="Несохранённые изменения"
      />
      {monthId === null ? <p role="alert">Некорректный идентификатор месяца.</p> : null}
      {monthId !== null && monthQuery.isPending ? (
        <p role="status">Загружаем выбранный месяц…</p>
      ) : null}
      {monthQuery.isError ? (
        <div className={styles.warning} role="alert">
          <p>
            {monthQuery.error instanceof ApiClientError && monthQuery.error.status === 404
              ? "Запрошенный месяц не найден. Выбери месяц из списка явно."
              : `Не удалось загрузить месяц: ${formatApiError(monthQuery.error)}`}
          </p>
          <button onClick={() => void monthQuery.refetch()} type="button">
            Повторить загрузку
          </button>
        </div>
      ) : null}
      {monthQuery.isSuccess && !month ? (
        <p role="alert">
          Период выбранного месяца изменился. Действия скрыты; выбери месяц из списка явно.
        </p>
      ) : null}
      {month && editorContext ? (
        <div key={`${month.id}:${rereadVersion}`}>
          <DataMonthContext month={month} automatic={false} />
          <p className={styles.status} role="status">
            {dirty ? "Есть несохранённые изменения" : "Изменения сохранены или не вносились"}
          </p>
          <nav aria-label="Разделы редактора месяца" className={styles.tabs}>
            {Object.entries(EDITOR_SECTIONS).map(([id, label]) => {
              const next = new URLSearchParams(params);
              next.delete("section");
              if (id !== "general") next.set("section", id);
              const query = next.toString();
              return (
                <Link
                  key={id}
                  aria-current={section === id ? "page" : undefined}
                  to={`${location.pathname}${query ? `?${query}` : ""}${location.hash}`}
                >
                  {label}
                </Link>
              );
            })}
          </nav>
          {section === null ? (
            <p className={styles.warning} role="alert">
              Неизвестный раздел. Выбери раздел редактора.
            </p>
          ) : (
            <>
              {section === "general" ? (
                <GeneralSection
                  key={month.id}
                  context={editorContext}
                  requestReopen={
                    params.getAll("action").length === 1 && params.get("action") === "reopen"
                  }
                />
              ) : null}
              {section === "income" ? (
                <MonthIncomeSection key={month.id} context={editorContext} />
              ) : null}
              {section === "assets" ? (
                <UiV2MonthAssetsSection key={month.id} context={editorContext} />
              ) : null}
              {section === "positions" ? (
                <UiV2MonthPositionsSection key={month.id} context={editorContext} />
              ) : null}
              {section === "payouts" ? (
                <UiV2MonthPayoutsSection key={month.id} context={editorContext} />
              ) : null}
              {section === "budget" ? (
                <UiV2MonthBudgetSection key={month.id} context={editorContext} />
              ) : null}
              {section === "liabilities" ? (
                <UiV2MonthLiabilities key={month.id} context={editorContext} />
              ) : null}
              {section === "note" ? <NoteSection key={month.id} context={editorContext} /> : null}
            </>
          )}
        </div>
      ) : null}
    </UiV2DataFrame>
  );
}

function GeneralSection({
  context,
  requestReopen = false,
}: {
  context: MonthEditorContext;
  requestReopen?: boolean;
}) {
  const { month, readOnly, refresh, setDirty } = context;
  const queryClient = useQueryClient();
  const [snapshotDate, setSnapshotDate] = useState(month.snapshot_date);
  const [baseline, setBaseline] = useState(month.snapshot_date);
  const [saving, setSaving] = useState(false);
  const [reopening, setReopening] = useState(false);
  const [confirmReopen, setConfirmReopen] = useState(requestReopen && readOnly);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const operation = useRef(0);
  const dirty = snapshotDate !== baseline;

  useEffect(() => setDirty("general", dirty), [dirty, setDirty]);
  useEffect(
    () => () => {
      operation.current += 1;
      setDirty("general", false);
    },
    [setDirty],
  );
  useEffect(() => {
    if (dirty) return;
    setSnapshotDate(month.snapshot_date);
    setBaseline(month.snapshot_date);
  }, [month.snapshot_date, dirty]);

  async function save(event: FormEvent) {
    event.preventDefault();
    if (readOnly || !dirty || saving || reopening) return;
    const token = ++operation.current;
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const changed = await updateMonth(month.id, { snapshot_date: snapshotDate });
      if (changed.id !== month.id || changed.status !== "draft")
        throw new Error("Ответ сохранения не подтверждает выбранный черновик.");
      const fresh = await refresh();
      if (fresh.status !== "draft" || fresh.snapshot_date !== snapshotDate)
        throw new Error("Сохранение не подтверждено повторной загрузкой месяца.");
      if (operation.current === token) {
        setBaseline(fresh.snapshot_date);
        setNotice("Общие данные сохранены и подтверждены.");
      }
    } catch (cause) {
      if (operation.current === token) setError(formatApiError(cause));
    } finally {
      if (operation.current === token) setSaving(false);
    }
  }

  async function confirm() {
    if (!readOnly || reopening) return;
    const token = ++operation.current;
    setReopening(true);
    setError(null);
    setNotice(null);
    try {
      const before = await refresh();
      if (operation.current !== token) return;
      if (before.status !== "closed") throw new Error("Месяц уже открыт. Состояние перечитано.");
      const result = await reopenMonth(month.id);
      if (
        result.id !== month.id ||
        result.year !== month.year ||
        result.month !== month.month ||
        result.status !== "draft"
      )
        throw new Error("Reopen не подтверждён ответом API.");
      const fresh = await refresh();
      if (fresh.status !== "draft") throw new Error("Reopen не подтверждён повторной загрузкой.");
      if (operation.current === token) {
        setConfirmReopen(false);
        setSnapshotDate(fresh.snapshot_date);
        setBaseline(fresh.snapshot_date);
        setNotice("Месяц открыт для редактирования. Данные перечитаны.");
      }
    } catch (cause) {
      if (operation.current === token) setError(formatApiError(cause));
    } finally {
      await queryClient.invalidateQueries({ refetchType: "none" });
      if (operation.current === token) setReopening(false);
    }
  }

  return (
    <section aria-label="Общие данные месяца" className={styles.panel}>
      <h2>Общие данные</h2>
      <p>
        {readOnly
          ? "Закрытый месяц доступен только для чтения."
          : "Изменения этого раздела сохраняются отдельно от заметок."}
      </p>
      <form className={styles.form} onSubmit={(event) => void save(event)}>
        <label>
          Дата снимка
          <input
            disabled={readOnly || saving}
            onChange={(event) => {
              setSnapshotDate(event.target.value);
              setNotice(null);
            }}
            required
            type="date"
            value={snapshotDate}
          />
        </label>
        <p>Источник: {labelOf(SOURCE_LABELS, month.source)}</p>
        <p>
          Снимок: {formatDate(month.snapshot_date)} · {formatMonth(month.year, month.month)}
        </p>
        {!readOnly ? (
          <button disabled={!dirty || saving} type="submit">
            {saving ? "Сохраняем…" : "Сохранить общие данные"}
          </button>
        ) : null}
      </form>
      {readOnly ? (
        <button disabled={reopening} onClick={() => setConfirmReopen(true)} type="button">
          Открыть для редактирования
        </button>
      ) : null}
      {error ? (
        <p className={styles.warning} role="alert">
          {error}
        </p>
      ) : null}
      {notice ? <p role="status">{notice}</p> : null}
      <ConfirmDialog
        busy={reopening}
        cancelLabel="Отмена"
        confirmLabel="Открыть месяц"
        description="Закрытый месяц станет черновиком. Сохранённые подтверждения и результаты требуют повторной проверки перед новым закрытием."
        onCancel={() => setConfirmReopen(false)}
        onConfirm={() => void confirm()}
        open={confirmReopen}
        title="Открыть месяц для редактирования?"
      />
    </section>
  );
}

function NoteSection({ context }: { context: MonthEditorContext }) {
  const { month, readOnly, setDirty } = context;
  const queryClient = useQueryClient();
  const commentsQuery = useQuery({
    queryKey: ["month-notes", month.id],
    queryFn: ({ signal }) => listComments(month.id, signal),
    retry: false,
  });
  const comments = commentsQuery.data ?? [];
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<MonthlyComment | null>(null);
  const active = useRef(true);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
      setDirty("note", false);
    };
  }, [setDirty]);
  useEffect(() => setDirty("note", text.trim().length > 0), [text, setDirty]);

  async function readBack() {
    const result = await commentsQuery.refetch();
    if (!result.isSuccess) throw new Error("Заметки не подтверждены повторной загрузкой.");
    return result.data;
  }

  async function add(event: FormEvent) {
    event.preventDefault();
    const value = text.trim();
    if (readOnly || busy || !value) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const created = await createComment({ reporting_month_id: month.id, text: value });
      if (created.reporting_month_id !== month.id)
        throw new Error("Ответ не подтверждает выбранный месяц.");
      const fresh = await readBack();
      if (!fresh.some((row) => row.id === created.id && row.reporting_month_id === month.id))
        throw new Error("Заметка не подтверждена повторной загрузкой.");
      if (active.current) {
        setText("");
        setNotice("Заметка сохранена и подтверждена.");
      }
    } catch (cause) {
      if (active.current) setError(formatApiError(cause));
    } finally {
      if (active.current) setBusy(false);
    }
  }

  async function mutate(
    action: () => Promise<unknown>,
    expected: (rows: MonthlyComment[]) => boolean,
  ) {
    if (readOnly || busy) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await action();
      const fresh = await readBack();
      if (!expected(fresh))
        throw new Error("Изменение заметок не подтверждено повторной загрузкой.");
      await queryClient.invalidateQueries({
        queryKey: ["month-notes", month.id],
        refetchType: "none",
      });
      if (active.current) {
        setDeleteTarget(null);
        setNotice("Заметки обновлены.");
      }
    } catch (cause) {
      if (active.current) setError(formatApiError(cause));
    } finally {
      if (active.current) setBusy(false);
    }
  }

  return (
    <section aria-label="Заметки месяца" className={styles.panel}>
      <h2>Заметки месяца</h2>
      {commentsQuery.isPending ? <p role="status">Загружаем заметки…</p> : null}
      {commentsQuery.isError ? (
        <p className={styles.warning} role="alert">
          Не удалось загрузить заметки: {formatApiError(commentsQuery.error)}
        </p>
      ) : null}
      {commentsQuery.isSuccess && comments.length === 0 ? <p>Заметок пока нет.</p> : null}
      {commentsQuery.isSuccess ? (
        <ol className={styles.notes}>
          {comments.map((comment, index) => (
            <li key={comment.id}>
              <span>{comment.text}</span>
              {!readOnly ? (
                <span className={styles.noteActions}>
                  <button
                    aria-label={`Переместить заметку ${index + 1} выше`}
                    disabled={busy || index === 0}
                    onClick={() =>
                      void mutate(
                        () => moveComment(comment.id, comment.position - 1),
                        (rows) =>
                          rows.some(
                            (row) => row.id === comment.id && row.position === comment.position - 1,
                          ),
                      )
                    }
                    type="button"
                  >
                    ↑
                  </button>
                  <button
                    aria-label={`Переместить заметку ${index + 1} ниже`}
                    disabled={busy || index === comments.length - 1}
                    onClick={() =>
                      void mutate(
                        () => moveComment(comment.id, comment.position + 1),
                        (rows) =>
                          rows.some(
                            (row) => row.id === comment.id && row.position === comment.position + 1,
                          ),
                      )
                    }
                    type="button"
                  >
                    ↓
                  </button>
                  <button disabled={busy} onClick={() => setDeleteTarget(comment)} type="button">
                    Удалить
                  </button>
                </span>
              ) : null}
            </li>
          ))}
        </ol>
      ) : null}
      {!readOnly && commentsQuery.isSuccess ? (
        <form className={styles.form} onSubmit={(event) => void add(event)}>
          <label>
            Новая заметка{" "}
            <input
              onChange={(event) => {
                setText(event.target.value);
                setNotice(null);
              }}
              required
              value={text}
            />
          </label>
          <button disabled={busy || !text.trim()} type="submit">
            {busy ? "Сохраняем…" : "Добавить заметку"}
          </button>
        </form>
      ) : null}
      {error ? (
        <p className={styles.warning} role="alert">
          {error}
        </p>
      ) : null}
      {notice ? <p role="status">{notice}</p> : null}
      <ConfirmDialog
        busy={busy}
        cancelLabel="Отмена"
        confirmLabel="Удалить"
        danger
        description={deleteTarget ? `Удалить заметку #${deleteTarget.position}?` : ""}
        onCancel={() => setDeleteTarget(null)}
        onConfirm={() => {
          if (deleteTarget)
            void mutate(
              () => deleteComment(deleteTarget.id),
              (rows) => !rows.some((row) => row.id === deleteTarget.id),
            );
        }}
        open={deleteTarget !== null}
        title="Удалить заметку?"
      />
    </section>
  );
}
