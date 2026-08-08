import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { formatApiError } from "../api/client";
import { getMonth } from "../api/months";
import type { ReportingMonth } from "../api/types";
import { Badge, Button, CloneMonthDialog, ErrorState, LoadingState, Panel } from "../components/ui";
import { formatDate, formatMonth } from "../lib/format";

/**
 * Open target for a reporting month.
 * Full editor starts at E04 — clone (E03) is available here.
 */
export function MonthDetailPage() {
  const params = useParams();
  const navigate = useNavigate();
  const monthId = Number(params.monthId);
  const [month, setMonth] = useState<ReportingMonth | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [cloneOpen, setCloneOpen] = useState(false);

  useEffect(() => {
    if (!Number.isInteger(monthId) || monthId < 1) {
      setError("Некорректный идентификатор месяца");
      setLoading(false);
      return;
    }

    const controller = new AbortController();
    setLoading(true);
    setError(null);

    void getMonth(monthId, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) {
          setMonth(data);
        }
      })
      .catch((err: unknown) => {
        if (!controller.signal.aborted) {
          setError(formatApiError(err));
          setMonth(null);
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      });

    return () => controller.abort();
  }, [monthId]);

  return (
    <section className="stack-18">
      <header className="page-header">
        <p className="eyebrow">Период</p>
        <h1>{month ? formatMonth(month.year, month.month) : "Месяц"}</h1>
        <p className="page-header__description">
          Карточка периода. Клонирование в следующий месяц доступно; редактор полей — E04+.
        </p>
      </header>

      <div className="toolbar">
        <Link className="btn" to="/months">
          ← К списку
        </Link>
        <Button
          disabled={!month}
          onClick={() => setCloneOpen(true)}
          type="button"
          variant="primary"
        >
          Создать следующий месяц
        </Button>
      </div>

      {loading ? (
        <LoadingState description="Загружаем месяц…" inline />
      ) : error ? (
        <ErrorState description={error} inline title="Не удалось открыть" />
      ) : month ? (
        <Panel
          action={
            <Badge tone={month.status === "draft" ? "draft" : "closed"}>{month.status}</Badge>
          }
          label="Сводка"
          title={formatMonth(month.year, month.month)}
        >
          <dl className="detail-list">
            <div>
              <dt>ID</dt>
              <dd>{month.id}</dd>
            </div>
            <div>
              <dt>Снимок</dt>
              <dd>{formatDate(month.snapshot_date)}</dd>
            </div>
            <div>
              <dt>Источник</dt>
              <dd>{month.source}</dd>
            </div>
          </dl>
          <p className="muted" style={{ marginTop: 16, marginBottom: 0 }}>
            Редактирование полей — E04+.
          </p>
          <div className="toolbar" style={{ marginTop: 18, marginBottom: 0 }}>
            <Button disabled type="button">
              Редактор (E04)
            </Button>
          </div>
        </Panel>
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
    </section>
  );
}
