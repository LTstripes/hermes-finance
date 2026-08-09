import { useCallback, useEffect, useMemo, useState } from "react";

import { formatApiError } from "../api/client";
import { downloadMarkdownReport } from "../api/exports";
import { listMonths } from "../api/months";
import type { ReportingMonth } from "../api/types";
import {
  Button,
  EmptyState,
  ErrorState,
  Field,
  LoadingState,
  Panel,
  Select,
} from "../components/ui";
import { formatMonth } from "../lib/format";

export function ExportPage() {
  const [months, setMonths] = useState<ReportingMonth[]>([]);
  const [selectedMonthId, setSelectedMonthId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingError, setLoadingError] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);

  const loadMonths = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setLoadingError(null);
    try {
      const data = await listMonths(signal);
      if (signal?.aborted) {
        return;
      }
      const ordered = [...data].sort((a, b) => b.year - a.year || b.month - a.month);
      setMonths(ordered);
      setSelectedMonthId((current) =>
        ordered.some((month) => month.id === current) ? current : (ordered[0]?.id ?? null),
      );
    } catch (error) {
      if (signal?.aborted) {
        return;
      }
      setLoadingError(formatApiError(error));
      setMonths([]);
      setSelectedMonthId(null);
    } finally {
      if (!signal?.aborted) {
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void loadMonths(controller.signal);
    return () => controller.abort();
  }, [loadMonths]);

  const selectedMonth = useMemo(
    () => months.find((month) => month.id === selectedMonthId) ?? null,
    [months, selectedMonthId],
  );

  async function handleDownload() {
    if (!selectedMonth) {
      return;
    }
    setDownloading(true);
    setDownloadError(null);
    setSuccess(null);
    try {
      const file = await downloadMarkdownReport(selectedMonth.id);
      const url = URL.createObjectURL(file.blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = file.filename;
      anchor.style.display = "none";
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
      setSuccess(`Файл ${file.filename} скачан.`);
    } catch (error) {
      setDownloadError(formatApiError(error));
    } finally {
      setDownloading(false);
    }
  }

  return (
    <section className="stack-18">
      <header className="page-header">
        <p className="eyebrow">Система</p>
        <h1>Экспорт</h1>
        <p className="page-header__description">
          Скачай готовый Markdown-отчёт выбранного отчётного месяца для анализа в Hermes.
        </p>
      </header>

      <Panel label="Markdown" title="Скачать отчёт">
        {loading ? (
          <LoadingState description="Загружаем месяцы…" inline />
        ) : loadingError ? (
          <ErrorState description={loadingError} inline title="Не удалось загрузить месяцы" />
        ) : months.length === 0 ? (
          <EmptyState
            description="Сначала создай хотя бы один отчётный месяц."
            inline
            title="Нет месяцев"
          />
        ) : (
          <div className="form-stack">
            <Field htmlFor="export-month" label="Месяц отчёта">
              <Select
                id="export-month"
                onChange={(event) => {
                  setSelectedMonthId(Number(event.target.value));
                  setDownloadError(null);
                  setSuccess(null);
                }}
                value={selectedMonthId ?? ""}
              >
                {months.map((month) => (
                  <option key={month.id} value={month.id}>
                    {formatMonth(month.year, month.month)} · {month.status}
                  </option>
                ))}
              </Select>
            </Field>
            {downloadError ? (
              <div className="inline-alert inline-alert--error" role="alert">
                {downloadError}
              </div>
            ) : null}
            {success ? (
              <div className="inline-alert inline-alert--ok" role="status">
                {success}
              </div>
            ) : null}
            <Button
              disabled={downloading || selectedMonth === null}
              onClick={() => void handleDownload()}
              type="button"
              variant="primary"
            >
              {downloading ? "Готовим файл…" : "Скачать Markdown"}
            </Button>
          </div>
        )}
      </Panel>
    </section>
  );
}
