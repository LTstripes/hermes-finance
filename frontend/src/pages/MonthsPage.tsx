import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { Link } from "react-router";

import { formatApiError } from "../api/client";
import { createMonth, deleteMonth, listMonths } from "../api/months";
import type { ReportingMonth } from "../api/types";
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
} from "../components/ui";
import { formatDate, formatMonth } from "../lib/format";

const MONTH_LABELS = [
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
] as const;

function lastDayOfMonth(year: number, month: number): string {
  // day 0 of next month = last day of this month (local calendar)
  const date = new Date(year, month, 0);
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function defaultCreateDraft(): { year: number; month: number; snapshot_date: string } {
  const now = new Date();
  const year = now.getFullYear();
  const month = now.getMonth() + 1;
  return { year, month, snapshot_date: lastDayOfMonth(year, month) };
}

function sourceLabel(source: string): string {
  switch (source) {
    case "manual":
      return "manual";
    case "excel_migration":
      return "excel";
    case "alfa_pdf":
      return "alfa pdf";
    default:
      return source;
  }
}

export function MonthsPage() {
  const [months, setMonths] = useState<ReportingMonth[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [draft, setDraft] = useState(defaultCreateDraft);
  const [pendingDelete, setPendingDelete] = useState<ReportingMonth | null>(null);
  const [deleting, setDeleting] = useState(false);

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    try {
      const data = await listMonths(signal);
      if (signal?.aborted) {
        return;
      }
      // Newest first for the UI (API returns ascending).
      setMonths([...data].sort((a, b) => b.year - a.year || b.month - a.month));
    } catch (err) {
      if (signal?.aborted) {
        return;
      }
      setError(formatApiError(err));
      setMonths([]);
    } finally {
      if (!signal?.aborted) {
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const monthOptions = useMemo(
    () =>
      MONTH_LABELS.map((label, index) => ({
        value: index + 1,
        label,
      })),
    [],
  );

  async function handleCreate(event: FormEvent) {
    event.preventDefault();
    setFormError(null);
    setActionError(null);
    setCreating(true);
    try {
      await createMonth({
        year: draft.year,
        month: draft.month,
        snapshot_date: draft.snapshot_date,
        source: "manual",
      });
      setDraft(defaultCreateDraft());
      await load();
    } catch (err) {
      setFormError(formatApiError(err));
    } finally {
      setCreating(false);
    }
  }

  async function handleConfirmDelete() {
    if (!pendingDelete) {
      return;
    }
    setDeleting(true);
    setActionError(null);
    try {
      await deleteMonth(pendingDelete.id);
      setPendingDelete(null);
      await load();
    } catch (err) {
      setActionError(formatApiError(err));
      setPendingDelete(null);
    } finally {
      setDeleting(false);
    }
  }

  return (
    <section className="stack-18">
      <header className="page-header">
        <p className="eyebrow">Периоды</p>
        <h1>Месяцы</h1>
        <p className="page-header__description">
          Отчётные периоды: список, создание manual draft и удаление draft с подтверждением.
          Редактор месяца — со следующего этапа.
        </p>
      </header>

      <div className="toolbar">
        <Button
          disabled={loading}
          onClick={() => {
            void load();
          }}
          type="button"
        >
          Обновить
        </Button>
      </div>

      {actionError ? (
        <div className="inline-alert inline-alert--error" role="alert">
          {actionError}
        </div>
      ) : null}

      <div className="dashboard-grid">
        <Panel label="Список" title="Отчётные месяцы">
          {loading ? (
            <LoadingState description="Загружаем /api/months…" inline />
          ) : error ? (
            <ErrorState description={error} inline title="Не удалось загрузить" />
          ) : months.length === 0 ? (
            <EmptyState
              description="Пока нет периодов — создай первый draft справа."
              inline
              title="Пусто"
            />
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>Период</Th>
                  <Th>Статус</Th>
                  <Th>Источник</Th>
                  <Th numeric>Снимок</Th>
                  <Th>Действия</Th>
                </tr>
              </thead>
              <tbody>
                {months.map((row) => (
                  <tr key={row.id}>
                    <Td>{formatMonth(row.year, row.month)}</Td>
                    <Td>
                      <Badge tone={row.status === "draft" ? "draft" : "closed"}>{row.status}</Badge>
                    </Td>
                    <Td>
                      <span className="muted">{sourceLabel(row.source)}</span>
                    </Td>
                    <Td numeric>{formatDate(row.snapshot_date)}</Td>
                    <Td>
                      <div className="row-actions">
                        <Link className="btn btn--sm" to={`/months/${row.id}`}>
                          Открыть
                        </Link>
                        {row.status === "draft" ? (
                          <Button
                            onClick={() => setPendingDelete(row)}
                            size="sm"
                            type="button"
                            variant="danger"
                          >
                            Удалить
                          </Button>
                        ) : null}
                      </div>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Panel>

        <Panel label="Создание" title="Новый draft">
          <form className="form-stack" onSubmit={handleCreate}>
            <Field htmlFor="year" label="Год">
              <Input
                id="year"
                inputMode="numeric"
                max={9999}
                min={1}
                name="year"
                onChange={(event) => {
                  const year = Number(event.target.value);
                  setDraft((prev) => ({
                    ...prev,
                    year,
                    snapshot_date: lastDayOfMonth(year, prev.month),
                  }));
                }}
                required
                type="number"
                value={draft.year}
              />
            </Field>
            <Field htmlFor="month" label="Месяц">
              <Select
                id="month"
                name="month"
                onChange={(event) => {
                  const month = Number(event.target.value);
                  setDraft((prev) => ({
                    ...prev,
                    month,
                    snapshot_date: lastDayOfMonth(prev.year, month),
                  }));
                }}
                value={draft.month}
              >
                {monthOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </Select>
            </Field>
            <Field htmlFor="snapshot_date" label="Дата снимка">
              <Input
                id="snapshot_date"
                name="snapshot_date"
                onChange={(event) =>
                  setDraft((prev) => ({ ...prev, snapshot_date: event.target.value }))
                }
                required
                type="date"
                value={draft.snapshot_date}
              />
            </Field>
            {formError ? (
              <div className="inline-alert inline-alert--error" role="alert">
                {formError}
              </div>
            ) : null}
            <Button block disabled={creating || loading} type="submit" variant="primary">
              {creating ? "Создаём…" : "Создать месяц"}
            </Button>
          </form>
        </Panel>
      </div>

      <ConfirmDialog
        busy={deleting}
        cancelLabel="Отмена"
        confirmLabel="Удалить draft"
        danger
        description={
          pendingDelete
            ? `Удалить ${formatMonth(pendingDelete.year, pendingDelete.month)}? Действие необратимо. Closed месяцы удалить нельзя.`
            : ""
        }
        onCancel={() => {
          if (!deleting) {
            setPendingDelete(null);
          }
        }}
        onConfirm={() => {
          void handleConfirmDelete();
        }}
        open={pendingDelete !== null}
        title="Удалить draft?"
      />
    </section>
  );
}
