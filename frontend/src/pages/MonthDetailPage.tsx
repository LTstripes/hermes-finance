import { useEffect, useState } from "react";
import { Link, useParams } from "react-router";

import { formatApiError } from "../api/client";
import { getMonth } from "../api/months";
import type { ReportingMonth } from "../api/types";
import { Badge, Button, ErrorState, LoadingState, Panel } from "../components/ui";
import { formatDate, formatMonth } from "../lib/format";

/**
 * Lightweight open target for E02.
 * Full month editor starts at E04 — this page only confirms the period exists.
 */
export function MonthDetailPage() {
  const params = useParams();
  const monthId = Number(params.monthId);
  const [month, setMonth] = useState<ReportingMonth | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

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
          Карточка периода. Редактор (зарплата, активы, расходы) появится в E04–E10.
        </p>
      </header>

      <div className="toolbar">
        <Link className="btn" to="/months">
          ← К списку
        </Link>
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
            Клонирование — E03. Редактирование полей — E04+.
          </p>
          <div className="toolbar" style={{ marginTop: 18, marginBottom: 0 }}>
            <Button disabled type="button" variant="primary">
              Редактор (E04)
            </Button>
          </div>
        </Panel>
      ) : null}
    </section>
  );
}
