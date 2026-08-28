import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";

import { formatApiError } from "../api/client";
import { createMonth, deleteMonth, listMonths } from "../api/months";
import type { ReportingMonth } from "../api/types";
import {
  Badge,
  Button,
  CloneMonthDialog,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  Field,
  Input,
  LoadingState,
  OverflowMenu,
  OverflowMenuItem,
  Panel,
  Select,
  Table,
  Td,
  Th,
} from "../components/ui";
import { formatDate, formatMonth } from "../lib/format";
import { MONTH_STATUS_LABELS, SOURCE_LABELS, labelOf } from "../lib/labels";
import { lastDayOfMonth } from "../lib/period";
import { queryKeys } from "../queryClient";

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

function defaultCreateDraft(): { year: number; month: number; snapshot_date: string } {
  const now = new Date();
  const year = now.getFullYear();
  const month = now.getMonth() + 1;
  return { year, month, snapshot_date: lastDayOfMonth(year, month) };
}

function sourceLabel(source: string): string {
  return labelOf(SOURCE_LABELS, source);
}

type ManualCreateDialogProps = {
  open: boolean;
  busy: boolean;
  error: string | null;
  draft: { year: number; month: number; snapshot_date: string };
  monthOptions: { value: number; label: string }[];
  onChange: (draft: { year: number; month: number; snapshot_date: string }) => void;
  onCancel: () => void;
  onSubmit: (event: FormEvent) => void;
};

function ManualCreateDialog({
  open,
  busy,
  error,
  draft,
  monthOptions,
  onChange,
  onCancel,
  onSubmit,
}: ManualCreateDialogProps) {
  useEffect(() => {
    if (!open) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !busy) onCancel();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, busy, onCancel]);

  if (!open) return null;

  return (
    <div className="dialog-backdrop" role="presentation">
      <div aria-label="Создать месяц" aria-modal="true" className="dialog" role="dialog">
        <h2 className="dialog__title">Создать месяц</h2>
        <p className="dialog__body">
          Укажи произвольный отчётный период и дату снимка. Для следующего периода используй главное
          действие выше.
        </p>
        <form className="form-stack" onSubmit={onSubmit}>
          <Field htmlFor="manual-year" label="Год">
            <Input
              autoFocus
              id="manual-year"
              inputMode="numeric"
              max={9999}
              min={1}
              name="year"
              onChange={(event) => {
                const year = Number(event.target.value);
                onChange({ ...draft, year, snapshot_date: lastDayOfMonth(year, draft.month) });
              }}
              required
              type="number"
              value={draft.year}
            />
          </Field>
          <Field htmlFor="manual-month" label="Месяц">
            <Select
              id="manual-month"
              name="month"
              onChange={(event) => {
                const month = Number(event.target.value);
                onChange({ ...draft, month, snapshot_date: lastDayOfMonth(draft.year, month) });
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
          <Field htmlFor="manual-snapshot-date" label="Дата снимка">
            <Input
              id="manual-snapshot-date"
              name="snapshot_date"
              onChange={(event) => onChange({ ...draft, snapshot_date: event.target.value })}
              required
              type="date"
              value={draft.snapshot_date}
            />
          </Field>
          {error ? (
            <div className="inline-alert inline-alert--error" role="alert">
              {error}
            </div>
          ) : null}
          <div className="dialog__actions">
            <Button disabled={busy} onClick={onCancel} type="button">
              Отмена
            </Button>
            <Button disabled={busy} type="submit" variant="primary">
              {busy ? "Создаём…" : "Создать месяц"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}

export function MonthsPage() {
  const navigate = useNavigate();
  const [formError, setFormError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [draft, setDraft] = useState(defaultCreateDraft);
  const [manualCreateOpen, setManualCreateOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<ReportingMonth | null>(null);
  const [cloneSource, setCloneSource] = useState<ReportingMonth | null>(null);
  const queryClient = useQueryClient();
  const monthsQuery = useQuery({
    queryKey: queryKeys.months,
    queryFn: ({ signal }) => listMonths(signal),
    select: (rows: ReportingMonth[]) =>
      [...rows].sort((a, b) => b.year - a.year || b.month - a.month),
  });
  const months = monthsQuery.data ?? [];
  const loading = monthsQuery.isPending;
  const error = monthsQuery.error ? formatApiError(monthsQuery.error) : null;

  const createMutation = useMutation({
    mutationFn: (payload: Parameters<typeof createMonth>[0]) => createMonth(payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.months }),
  });
  const deleteMutation = useMutation({
    mutationFn: (monthId: number) => deleteMonth(monthId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.months }),
  });
  const creating = createMutation.isPending;
  const deleting = deleteMutation.isPending;

  const monthOptions = useMemo(
    () =>
      MONTH_LABELS.map((label, index) => ({
        value: index + 1,
        label,
      })),
    [],
  );

  const latestMonth = months[0] ?? null;

  async function handleCreate(event: FormEvent) {
    event.preventDefault();
    setFormError(null);
    setActionError(null);
    try {
      await createMutation.mutateAsync({
        year: draft.year,
        month: draft.month,
        snapshot_date: draft.snapshot_date,
        source: "manual",
      });
      setDraft(defaultCreateDraft());
      setManualCreateOpen(false);
    } catch (err) {
      setFormError(formatApiError(err));
    }
  }

  async function handleConfirmDelete() {
    if (!pendingDelete) {
      return;
    }
    setActionError(null);
    try {
      await deleteMutation.mutateAsync(pendingDelete.id);
      setPendingDelete(null);
    } catch (err) {
      setActionError(formatApiError(err));
      setPendingDelete(null);
    }
  }

  return (
    <section className="stack-18">
      <header className="page-header">
        <p className="eyebrow">Периоды</p>
        <h1>Месяцы</h1>
        <p className="page-header__description">
          Список отчётных периодов и быстрый доступ к рабочим месяцам.
        </p>
      </header>

      <div className="toolbar">
        <Button
          disabled={loading || !latestMonth}
          onClick={() => {
            if (latestMonth) {
              setCloneSource(latestMonth);
            }
          }}
          type="button"
          variant="primary"
        >
          Создать следующий месяц
        </Button>
        <Button
          disabled={loading}
          onClick={() => {
            setManualCreateOpen(true);
            setFormError(null);
          }}
          type="button"
        >
          Создать другой период
        </Button>
        <Button
          disabled={loading}
          onClick={() => {
            void monthsQuery.refetch();
          }}
          type="button"
          variant="ghost"
        >
          Обновить список
        </Button>
      </div>

      {actionError ? (
        <div className="inline-alert inline-alert--error" role="alert">
          {actionError}
        </div>
      ) : null}

      <div className="months-page__content">
        <Panel label="Список" title="Отчётные месяцы">
          {loading ? (
            <LoadingState description="Загружаем отчётные месяцы…" inline />
          ) : error ? (
            <ErrorState description={error} inline title="Не удалось загрузить" />
          ) : months.length === 0 ? (
            <EmptyState
              description="Пока нет периодов. Создай первый период кнопкой «Создать другой период»."
              inline
              title="Пусто"
            />
          ) : (
            <Table className="months-table">
              <thead>
                <tr>
                  <Th>Период</Th>
                  <Th>Статус</Th>
                  <Th className="months-table__snapshot" numeric>
                    Снимок
                  </Th>
                  <Th className="months-table__actions">Действия</Th>
                </tr>
              </thead>
              <tbody>
                {months.map((row) => (
                  <tr key={row.id}>
                    <Td>
                      <div className="month-period">
                        <strong>{formatMonth(row.year, row.month)}</strong>
                        <details className="month-period__details">
                          <summary>Детали</summary>
                          <span>Источник: {sourceLabel(row.source)}</span>
                        </details>
                      </div>
                    </Td>
                    <Td>
                      <Badge tone={row.status === "draft" ? "draft" : "closed"}>
                        {labelOf(MONTH_STATUS_LABELS, row.status)}
                      </Badge>
                    </Td>
                    <Td className="months-table__snapshot" numeric>
                      {formatDate(row.snapshot_date)}
                    </Td>
                    <Td className="months-table__actions">
                      <div className="row-actions">
                        <Link
                          className="btn btn--sm btn--primary months-table__open"
                          to={`/months/${row.id}`}
                        >
                          Открыть
                        </Link>
                        <OverflowMenu label={`Действия для ${formatMonth(row.year, row.month)}`}>
                          <OverflowMenuItem onClick={() => setCloneSource(row)}>
                            Копировать данные
                          </OverflowMenuItem>
                          {row.status === "draft" ? (
                            <OverflowMenuItem danger onClick={() => setPendingDelete(row)}>
                              Удалить черновик
                            </OverflowMenuItem>
                          ) : null}
                        </OverflowMenu>
                      </div>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Panel>
      </div>

      <ManualCreateDialog
        busy={creating}
        draft={draft}
        error={formError}
        monthOptions={monthOptions}
        onCancel={() => {
          if (!creating) setManualCreateOpen(false);
        }}
        onChange={setDraft}
        onSubmit={handleCreate}
        open={manualCreateOpen}
      />

      <ConfirmDialog
        busy={deleting}
        cancelLabel="Отмена"
        confirmLabel="Удалить черновик"
        danger
        description={
          pendingDelete
            ? `Удалить ${formatMonth(pendingDelete.year, pendingDelete.month)}? Действие необратимо. Утверждённые месяцы удалить нельзя.`
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
        title="Удалить черновик?"
      />

      <CloneMonthDialog
        onCancel={() => setCloneSource(null)}
        onCloned={(cloned) => {
          setCloneSource(null);
          void queryClient.invalidateQueries({ queryKey: queryKeys.months });
          navigate(`/months/${cloned.id}`);
        }}
        open={cloneSource !== null}
        source={cloneSource}
      />
    </section>
  );
}
