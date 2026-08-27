import { useCallback, useEffect, useMemo, useState } from "react";

import { formatApiError } from "../api/client";
import { createBackup, listBackups, restoreBackup } from "../api/backups";
import {
  downloadAiAnalysisBundleJson,
  downloadAiAnalysisBundleMarkdown,
  downloadJsonReport,
  downloadMarkdownReport,
} from "../api/exports";
import { listMonths } from "../api/months";
import type { BackupMetadata, ReportingMonth } from "../api/types";
import {
  Button,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  Field,
  LoadingState,
  Panel,
  Select,
  Table,
  Td,
  Th,
} from "../components/ui";
import { formatDate, formatMonth } from "../lib/format";
import { MONTH_STATUS_LABELS, labelOf } from "../lib/labels";

export function ExportPage() {
  const [months, setMonths] = useState<ReportingMonth[]>([]);
  const [selectedMonthId, setSelectedMonthId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingError, setLoadingError] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [downloading, setDownloading] = useState<"markdown" | "json" | null>(null);
  const [bundleDownloadError, setBundleDownloadError] = useState<string | null>(null);
  const [bundleSuccess, setBundleSuccess] = useState<string | null>(null);
  const [bundleDownloading, setBundleDownloading] = useState<"markdown" | "json" | null>(null);
  const [backups, setBackups] = useState<BackupMetadata[]>([]);
  const [backupsLoading, setBackupsLoading] = useState(true);
  const [backupsError, setBackupsError] = useState<string | null>(null);
  const [creatingBackup, setCreatingBackup] = useState(false);
  const [restoreCandidate, setRestoreCandidate] = useState<BackupMetadata | null>(null);
  const [restoringBackupId, setRestoringBackupId] = useState<string | null>(null);
  const [restoreError, setRestoreError] = useState<string | null>(null);
  const [restoreSuccess, setRestoreSuccess] = useState<string | null>(null);

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

  const loadBackups = useCallback(async (signal?: AbortSignal) => {
    setBackupsLoading(true);
    setBackupsError(null);
    try {
      const data = await listBackups(signal);
      if (!signal?.aborted) {
        setBackups(data);
      }
    } catch (error) {
      if (!signal?.aborted) {
        setBackupsError(formatApiError(error));
        setBackups([]);
      }
    } finally {
      if (!signal?.aborted) {
        setBackupsLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void loadBackups(controller.signal);
    return () => controller.abort();
  }, [loadBackups]);

  const selectedMonth = useMemo(
    () => months.find((month) => month.id === selectedMonthId) ?? null,
    [months, selectedMonthId],
  );

  async function handleDownload(format: "markdown" | "json") {
    if (!selectedMonth) {
      return;
    }
    setDownloading(format);
    setDownloadError(null);
    setSuccess(null);
    try {
      const file =
        format === "markdown"
          ? await downloadMarkdownReport(selectedMonth.id)
          : await downloadJsonReport(selectedMonth.id);
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
      setDownloading(null);
    }
  }

  async function handleBundleDownload(format: "markdown" | "json") {
    setBundleDownloading(format);
    setBundleDownloadError(null);
    setBundleSuccess(null);
    setSuccess(null);
    try {
      const file =
        format === "markdown"
          ? await downloadAiAnalysisBundleMarkdown()
          : await downloadAiAnalysisBundleJson();
      const url = URL.createObjectURL(file.blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = file.filename;
      anchor.style.display = "none";
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
      setBundleSuccess(`Файл ${file.filename} скачан.`);
    } catch (error) {
      setBundleDownloadError(formatApiError(error));
    } finally {
      setBundleDownloading(null);
    }
  }

  async function handleCreateBackup() {
    setCreatingBackup(true);
    setBackupsError(null);
    setSuccess(null);
    try {
      const backup = await createBackup();
      setBackups((current) => [backup, ...current]);
      setSuccess(`Резервная копия ${backup.name} создана.`);
    } catch (error) {
      setBackupsError(formatApiError(error));
    } finally {
      setCreatingBackup(false);
    }
  }

  async function handleRestore() {
    if (restoreCandidate === null) {
      return;
    }
    const candidate = restoreCandidate;
    setRestoringBackupId(candidate.id);
    setRestoreError(null);
    setRestoreSuccess(null);
    try {
      const result = await restoreBackup(candidate.id);
      setBackups((current) => [result.pre_restore_backup, ...current]);
      setRestoreCandidate(null);
      setRestoreSuccess(`База восстановлена из ${result.restored_backup.name}.`);
    } catch (error) {
      setRestoreError(formatApiError(error));
    } finally {
      setRestoringBackupId(null);
    }
  }

  return (
    <section className="stack-18">
      <header className="page-header">
        <p className="eyebrow">Система</p>
        <h1>Экспорт</h1>
        <p className="page-header__description">
          Скачай отчёт в Markdown или JSON для выбранного отчётного месяца.
        </p>
      </header>

      <Panel label="Markdown и JSON" title="Скачать отчёт">
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
                    {formatMonth(month.year, month.month)} ·{" "}
                    {labelOf(MONTH_STATUS_LABELS, month.status)}
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
            <div className="stack-12">
              <Button
                disabled={
                  downloading !== null || bundleDownloading !== null || selectedMonth === null
                }
                onClick={() => void handleDownload("markdown")}
                type="button"
                variant="primary"
              >
                {downloading === "markdown" ? "Готовим файл…" : "Скачать Markdown"}
              </Button>
              <Button
                disabled={
                  downloading !== null || bundleDownloading !== null || selectedMonth === null
                }
                onClick={() => void handleDownload("json")}
                type="button"
              >
                {downloading === "json" ? "Готовим JSON…" : "Скачать JSON"}
              </Button>
            </div>
          </div>
        )}
      </Panel>

      <Panel label="AI Analysis Bundle" title="Полный анализ для ассистента">
        <div className="stack-12">
          <p>
            Bundle собирает всю доступную историю Hermes Finance, а не только выбранный отчётный
            месяц.
          </p>
          <p className="muted">
            Схема: <code>hermes.finance.ai_analysis_bundle</code> v1.0.0. Дата as-of фиксируется
            backend при генерации и указана в скачанном файле как <code>metadata.as_of_date</code>.
          </p>
          <div className="inline-alert inline-alert--warn" role="note">
            <strong>Внимание:</strong> файл содержит финансовые данные. Проверь его перед ручной
            загрузкой в ассистент.
          </div>
          <p className="muted">
            Hermes только создаёт локальный файл и ничего не отправляет в облачные сервисы.
            Загрузить его можно вручную и спросить ассистента о трендах, рисках или решениях.
          </p>
          {bundleDownloadError ? (
            <div className="inline-alert inline-alert--error" role="alert">
              {bundleDownloadError}
            </div>
          ) : null}
          {bundleSuccess ? (
            <div className="inline-alert inline-alert--ok" role="status">
              {bundleSuccess}
            </div>
          ) : null}
          <div className="stack-12">
            <Button
              disabled={downloading !== null || bundleDownloading !== null}
              onClick={() => void handleBundleDownload("json")}
              type="button"
              variant="primary"
            >
              {bundleDownloading === "json"
                ? "Готовим bundle…"
                : "Скачать AI Analysis Bundle (JSON)"}
            </Button>
            <Button
              disabled={downloading !== null || bundleDownloading !== null}
              onClick={() => void handleBundleDownload("markdown")}
              type="button"
            >
              {bundleDownloading === "markdown"
                ? "Готовим Markdown…"
                : "Скачать Markdown-компаньон"}
            </Button>
          </div>
        </div>
      </Panel>

      <Panel
        action={
          <Button
            disabled={creatingBackup || restoringBackupId !== null || bundleDownloading !== null}
            onClick={() => void handleCreateBackup()}
            type="button"
          >
            {creatingBackup ? "Создаём резервную копию…" : "Создать резервную копию"}
          </Button>
        }
        label="Локальная база"
        title="Резервные копии"
      >
        {backupsLoading ? (
          <LoadingState description="Загружаем список резервных копий…" inline />
        ) : backupsError ? (
          <ErrorState
            description={backupsError}
            inline
            title="Не удалось загрузить резервные копии"
          />
        ) : backups.length === 0 ? (
          <EmptyState
            description="Создай первую локальную копию базы."
            inline
            title="Резервных копий пока нет"
          />
        ) : (
          <>
            {restoreError ? (
              <div className="inline-alert inline-alert--error" role="alert">
                {restoreError}
              </div>
            ) : null}
            {restoreSuccess ? (
              <div className="inline-alert inline-alert--ok" role="status">
                {restoreSuccess}
              </div>
            ) : null}
            <Table>
              <thead>
                <tr>
                  <Th>Имя</Th>
                  <Th>Создан</Th>
                  <Th numeric>Размер</Th>
                  <Th>Исходная база</Th>
                  <Th>Действия</Th>
                </tr>
              </thead>
              <tbody>
                {backups.map((backup) => (
                  <tr key={backup.id}>
                    <Td>{backup.name}</Td>
                    <Td>
                      <time dateTime={backup.created_at}>{formatDate(backup.created_at)}</time>
                    </Td>
                    <Td numeric>{backup.size_bytes} Б</Td>
                    <Td>{backup.source_database.name}</Td>
                    <Td>
                      <Button
                        disabled={creatingBackup || restoringBackupId !== null}
                        onClick={() => {
                          setRestoreError(null);
                          setRestoreSuccess(null);
                          setRestoreCandidate(backup);
                        }}
                        type="button"
                        variant="danger"
                      >
                        Восстановить
                      </Button>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </>
        )}
      </Panel>
      <ConfirmDialog
        busy={restoringBackupId !== null}
        danger
        description={
          restoreCandidate === null
            ? ""
            : `Текущая база будет заменена копией ${restoreCandidate.name}. Перед этим приложение автоматически сохранит текущую базу.`
        }
        onCancel={() => {
          if (restoringBackupId === null) {
            setRestoreCandidate(null);
          }
        }}
        onConfirm={() => void handleRestore()}
        open={restoreCandidate !== null}
        title="Восстановить базу?"
        confirmLabel="Восстановить"
      />
    </section>
  );
}
