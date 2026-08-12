import { useCallback, useEffect, useState, type FormEvent } from "react";

import { formatApiError } from "../api/client";
import { createComment, deleteComment, listComments, moveComment } from "../api/comments";
import type { MonthlyComment } from "../api/types";
import {
  Badge,
  Button,
  ConfirmDialog,
  EmptyState,
  Field,
  Input,
  LoadingState,
  Panel,
  Table,
  Td,
  Th,
} from "./ui";

type Props = { monthId: number; readOnly: boolean; onDirtyChange?: (dirty: boolean) => void };

export function MonthNoteSection({ monthId, readOnly, onDirtyChange }: Props) {
  const [comments, setComments] = useState<MonthlyComment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [commentText, setCommentText] = useState("");
  const [commentTouched, setCommentTouched] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<MonthlyComment | null>(null);

  useEffect(() => {
    onDirtyChange?.(commentTouched);
  }, [commentTouched, onDirtyChange]);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      setLoading(true);
      setError(null);
      try {
        const rows = await listComments(monthId, signal);
        if (!signal?.aborted) setComments(rows);
      } catch (err) {
        if (!signal?.aborted) setError(formatApiError(err));
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

  async function addNote(event: FormEvent) {
    event.preventDefault();
    if (!commentText.trim()) return;
    setBusy(true);
    setActionError(null);
    try {
      await createComment({ reporting_month_id: monthId, text: commentText.trim() });
      setCommentText("");
      setCommentTouched(false);
      await load();
    } catch (err) {
      setActionError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function moveNote(comment: MonthlyComment, position: number) {
    setBusy(true);
    setActionError(null);
    try {
      await moveComment(comment.id, position);
      await load();
    } catch (err) {
      setActionError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function removeNote() {
    if (!deleteTarget) return;
    setBusy(true);
    setActionError(null);
    try {
      await deleteComment(deleteTarget.id);
      setDeleteTarget(null);
      await load();
    } catch (err) {
      setActionError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <LoadingState description="Загружаем заметки…" inline />;
  if (error) return <EmptyState description={error} inline title="Ошибка заметок" />;

  return (
    <div className="stack-18">
      {actionError ? (
        <div className="inline-alert inline-alert--error" role="alert">
          {actionError}
        </div>
      ) : null}
      <Panel action={<Badge>{comments.length} шт.</Badge>} label="Месяц" title="Заметка месяца">
        {comments.length === 0 ? (
          <EmptyState description="Заметок пока нет." inline title="Пусто" />
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>#</Th>
                <Th>Текст</Th>
                <Th>Порядок</Th>
              </tr>
            </thead>
            <tbody>
              {comments.map((comment, index) => (
                <tr key={comment.id}>
                  <Td>{comment.position}</Td>
                  <Td>{comment.text}</Td>
                  <Td>
                    <div className="row-actions">
                      <Button
                        aria-label="Переместить заметку выше"
                        disabled={busy || readOnly || index === 0}
                        onClick={() => void moveNote(comment, Math.max(1, comment.position - 1))}
                        size="sm"
                        type="button"
                      >
                        ↑
                      </Button>
                      <Button
                        aria-label="Переместить заметку ниже"
                        disabled={busy || readOnly || index === comments.length - 1}
                        onClick={() => void moveNote(comment, comment.position + 1)}
                        size="sm"
                        type="button"
                      >
                        ↓
                      </Button>
                      <Button
                        disabled={busy || readOnly}
                        onClick={() => setDeleteTarget(comment)}
                        size="sm"
                        type="button"
                        variant="danger"
                      >
                        Удалить
                      </Button>
                    </div>
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
        {!readOnly ? (
          <form className="form-stack asset-form" onSubmit={addNote}>
            <Field htmlFor="month-note" label="Новая заметка">
              <Input
                id="month-note"
                onChange={(event) => {
                  setCommentText(event.target.value);
                  setCommentTouched(true);
                }}
                required
                value={commentText}
              />
            </Field>
            <Button disabled={busy} type="submit" variant="primary">
              Добавить заметку
            </Button>
          </form>
        ) : null}
      </Panel>
      <ConfirmDialog
        busy={busy}
        cancelLabel="Отмена"
        confirmLabel="Удалить"
        danger
        description={deleteTarget ? `Удалить заметку #${deleteTarget.position}?` : ""}
        onCancel={() => setDeleteTarget(null)}
        onConfirm={() => void removeNote()}
        open={deleteTarget !== null}
        title="Удалить заметку?"
      />
    </div>
  );
}
