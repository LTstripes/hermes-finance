import { triggerDownload } from "../lib/download";
import { brokerOriginalSession } from "../components/month-close/brokerOriginalSession";
import { type UseQueryResult, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { createBackup, listBackups, restoreBackup } from "../api/backups";
import { ApiClientError, formatApiError } from "../api/client";
import {
  downloadAiAnalysisBundleJson,
  downloadAiAnalysisBundleMarkdown,
  downloadAiFinancialReviewJson,
  downloadJsonReport,
  downloadMarkdownReport,
} from "../api/exports";
import { listMonths } from "../api/months";
import type { BackupMetadata, ReportingMonth, RestoreResponse } from "../api/types";
import { MyBrokerImportPanel } from "../components/MyBrokerImportPanel";
import { PortfolioReviewPackagePanel } from "../components/PortfolioReviewPackagePanel";
import { ConfirmDialog, OverflowMenu, OverflowMenuItem } from "../components/ui";
import { formatDate, formatMonth } from "../lib/format";
import { labelOf, MONTH_STATUS_LABELS } from "../lib/labels";
import { queryKeys } from "../queryClient";
import { latestClosedMonth, sortReportingMonths } from "./monthSelection";
import styles from "./UiV2DataFiles.module.css";
import {
  DataMonthContext,
  type DataMonthResolution,
  resolveDataMonth,
  UiV2DataFrame,
} from "./UiV2DataShell";
import { isQueryReady, UiV2Loading, UiV2Notice } from "./UiV2StateBlocks";

type ExportMonthResolution = DataMonthResolution | { kind: "no-closed" };

type MonthExportFormat = "markdown" | "json";
type DownloadKind =
  | "ai-review"
  | "month-markdown"
  | "month-json"
  | "bundle-markdown"
  | "bundle-json";
type RestoreErrorKind = "confirmed" | "unknown";
const CONFIRMED_RESTORE_FAILURE_CODES = new Set([
  "bad_request",
  "conflict",
  "not_found",
  "unprocessable",
]);

function prependUnique(items: BackupMetadata[], item: BackupMetadata): BackupMetadata[] {
  return [item, ...items.filter((current) => current.id !== item.id)];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isBackupMetadata(value: unknown): value is BackupMetadata {
  if (!isRecord(value)) return false;
  const sourceDatabase = value.source_database;
  return (
    typeof value.id === "string" &&
    typeof value.name === "string" &&
    typeof value.created_at === "string" &&
    typeof value.size_bytes === "number" &&
    Number.isFinite(value.size_bytes) &&
    isRecord(sourceDatabase) &&
    typeof sourceDatabase.name === "string" &&
    typeof sourceDatabase.size_bytes === "number" &&
    Number.isFinite(sourceDatabase.size_bytes)
  );
}

function isRestoreResponse(value: unknown): value is RestoreResponse {
  return (
    isRecord(value) &&
    isBackupMetadata(value.restored_backup) &&
    isBackupMetadata(value.pre_restore_backup)
  );
}

function isConfirmedRestoreFailure(error: unknown): error is ApiClientError {
  return error instanceof ApiClientError && CONFIRMED_RESTORE_FAILURE_CODES.has(error.code);
}

function BackupMetadataList({ backup }: { backup: BackupMetadata }) {
  return (
    <dl className={styles.metadataGrid}>
      <div>
        <dt>Создана</dt>
        <dd>
          <time dateTime={backup.created_at}>{formatDate(backup.created_at)}</time>
        </dd>
      </div>
      <div>
        <dt>Размер</dt>
        <dd>{backup.size_bytes} Б</dd>
      </div>
      <div>
        <dt>Исходная база</dt>
        <dd>{backup.source_database.name}</dd>
      </div>
    </dl>
  );
}

function RestoreEvidence({ backup }: { backup: BackupMetadata }) {
  return (
    <section
      aria-labelledby="pre-restore-evidence-title"
      className={styles.evidence}
      data-testid="pre-restore-evidence"
    >
      <div className={styles.evidenceHeader}>
        <div>
          <p className={styles.kicker}>Проверка перед восстановлением</p>
          <h3 id="pre-restore-evidence-title">Текущая база сохранена перед восстановлением</h3>
        </div>
        <span className={styles.recommendationBadge}>Подтверждено системой</span>
      </div>
      <p>
        Это точные сведения о копии, которую система создала до замены базы. Сохрани их как
        подтверждение безопасного восстановления.
      </p>
      <p className={styles.backupName}>{backup.name}</p>
      <BackupMetadataList backup={backup} />
    </section>
  );
}

function MonthExportState({
  monthsQuery,
  resolution,
  selectedMonth,
  params,
  setParams,
  downloadKind,
  onDownload,
  downloadError,
  downloadSuccess,
}: {
  monthsQuery: UseQueryResult<ReportingMonth[]>;
  resolution: ExportMonthResolution;
  selectedMonth: ReportingMonth | null;
  params: URLSearchParams;
  setParams: ReturnType<typeof useSearchParams>[1];
  downloadKind: DownloadKind | null;
  onDownload: (format: MonthExportFormat) => void;
  downloadError: string | null;
  downloadSuccess: string | null;
}) {
  if (monthsQuery.isError) {
    return (
      <UiV2Notice
        title="Не удалось загрузить отчётные месяцы"
        retry={() => void monthsQuery.refetch()}
      >
        Экспорт по месяцу скрыт, пока локальный список не подтверждён.
      </UiV2Notice>
    );
  }

  if (!isQueryReady(monthsQuery)) {
    return <UiV2Loading label="Проверяем доступные отчётные месяцы…" />;
  }

  if (resolution.kind === "invalid") {
    return (
      <UiV2Notice title="Некорректный параметр месяца">
        Выбор месяца должен содержать один положительный идентификатор. Числа не показаны — без
        тихой подмены.
      </UiV2Notice>
    );
  }

  if (resolution.kind === "missing") {
    return (
      <UiV2Notice title="Месяц не найден">
        Запрошенный отчётный месяц отсутствует. Экспорт не переключён на другой месяц.
      </UiV2Notice>
    );
  }

  if (resolution.kind === "empty") {
    return (
      <div className={styles.empty} data-testid="files-no-months">
        <strong>Нет отчётных месяцев</strong>
        Сначала создай хотя бы один отчётный месяц. Экспорт полной истории и локальные копии базы
        остаются отдельными операциями.
        <div className={styles.buttonRow}>
          <Link className={styles.secondaryButton} to="/v2/data/months">
            Открыть месяцы →
          </Link>
        </div>
      </div>
    );
  }

  if (resolution.kind !== "ready" && resolution.kind !== "no-closed") return null;

  function selectMonth(id: string) {
    const next = new URLSearchParams(params);
    next.set("month", id);
    setParams(next, { replace: true });
  }

  return (
    <>
      {resolution.kind === "ready" && selectedMonth ? (
        <DataMonthContext automatic={resolution.automatic} month={selectedMonth} />
      ) : (
        <p className={styles.muted}>Закрытых месяцев пока нет. Выбери месяц для отчёта.</p>
      )}
      <div className={styles.monthToolbar}>
        <div className={styles.field}>
          <label htmlFor="files-export-month">Месяц отчёта</label>
          <select
            className={styles.monthSelect}
            id="files-export-month"
            onChange={(event) => selectMonth(event.currentTarget.value)}
            value={selectedMonth?.id ?? ""}
          >
            <option disabled value="">
              Выбери месяц
            </option>
            {(monthsQuery.data ?? []).map((month) => (
              <option key={month.id} value={month.id}>
                {formatMonth(month.year, month.month)} ·{" "}
                {labelOf(MONTH_STATUS_LABELS, month.status)}
              </option>
            ))}
          </select>
        </div>
      </div>
      {downloadError ? (
        <div className={styles.error} role="alert">
          {downloadError}
        </div>
      ) : null}
      {downloadSuccess ? (
        <div className={styles.success} role="status">
          {downloadSuccess}
        </div>
      ) : null}
      <div className={styles.buttonRow}>
        <button
          className={styles.primaryButton}
          disabled={downloadKind !== null || selectedMonth === null}
          onClick={() => onDownload("markdown")}
          type="button"
        >
          {downloadKind === "month-markdown" ? "Готовим Markdown…" : "Скачать Markdown"}
        </button>
        <button
          className={styles.secondaryButton}
          disabled={downloadKind !== null || selectedMonth === null}
          onClick={() => onDownload("json")}
          type="button"
        >
          {downloadKind === "month-json" ? "Готовим JSON…" : "Скачать JSON"}
        </button>
      </div>
    </>
  );
}

export default function UiV2DataFilesPage() {
  const [params, setParams] = useSearchParams();
  const queryClient = useQueryClient();
  const [downloadKind, setDownloadKind] = useState<DownloadKind | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [downloadSuccess, setDownloadSuccess] = useState<string | null>(null);
  const [creatingBackup, setCreatingBackup] = useState(false);
  const [backupError, setBackupError] = useState<string | null>(null);
  const [backupSuccess, setBackupSuccess] = useState<string | null>(null);
  const [restoreCandidate, setRestoreCandidate] = useState<BackupMetadata | null>(null);
  const [restoringBackupId, setRestoringBackupId] = useState<string | null>(null);
  const [restoreError, setRestoreError] = useState<string | null>(null);
  const [restoreErrorKind, setRestoreErrorKind] = useState<RestoreErrorKind | null>(null);
  const [restoreSuccess, setRestoreSuccess] = useState<string | null>(null);
  const [preRestoreEvidence, setPreRestoreEvidence] = useState<BackupMetadata | null>(null);
  const restoreTriggerRef = useRef<HTMLButtonElement | null>(null);
  useEffect(() => {
    if (restoreCandidate === null) restoreTriggerRef.current?.focus();
  }, [restoreCandidate]);
  const mutationInFlightRef = useRef<"create" | "restore" | null>(null);

  const monthsQuery = useQuery({
    queryKey: queryKeys.months,
    queryFn: ({ signal }) => listMonths(signal),
  });
  const backupsQuery = useQuery({
    queryKey: queryKeys.backups,
    queryFn: ({ signal }) => listBackups(signal),
  });
  const months = useMemo(() => sortReportingMonths(monthsQuery.data ?? []), [monthsQuery.data]);
  const monthParams = params.getAll("month");
  const closedMonth = latestClosedMonth(months);
  const resolution: ExportMonthResolution =
    isQueryReady(monthsQuery) && monthParams.length === 0 && months.length > 0
      ? closedMonth
        ? { kind: "ready", month: closedMonth, automatic: true }
        : { kind: "no-closed" }
      : resolveDataMonth(monthParams, months, isQueryReady(monthsQuery));
  const selectedMonth = resolution.kind === "ready" ? resolution.month : null;

  async function downloadMonth(format: MonthExportFormat) {
    if (selectedMonth === null) return;
    const kind = format === "markdown" ? "month-markdown" : "month-json";
    setDownloadKind(kind);
    setDownloadError(null);
    setDownloadSuccess(null);
    try {
      const file =
        format === "markdown"
          ? await downloadMarkdownReport(selectedMonth.id)
          : await downloadJsonReport(selectedMonth.id);
      triggerDownload(file.blob, file.filename);
      setDownloadSuccess(`Файл ${file.filename} скачан.`);
    } catch (error) {
      setDownloadError(formatApiError(error));
    } finally {
      setDownloadKind(null);
    }
  }

  async function downloadAiReview() {
    setDownloadKind("ai-review");
    setDownloadError(null);
    setDownloadSuccess(null);
    try {
      const file = await downloadAiFinancialReviewJson();
      triggerDownload(file.blob, file.filename);
      setDownloadSuccess(`Файл ${file.filename} скачан.`);
    } catch (error) {
      setDownloadError(formatApiError(error));
    } finally {
      setDownloadKind(null);
    }
  }

  async function downloadBundle(format: "markdown" | "json") {
    setDownloadKind(format === "markdown" ? "bundle-markdown" : "bundle-json");
    setDownloadError(null);
    setDownloadSuccess(null);
    try {
      const file =
        format === "markdown"
          ? await downloadAiAnalysisBundleMarkdown()
          : await downloadAiAnalysisBundleJson();
      triggerDownload(file.blob, file.filename);
      setDownloadSuccess(`Файл ${file.filename} скачан.`);
    } catch (error) {
      setDownloadError(formatApiError(error));
    } finally {
      setDownloadKind(null);
    }
  }

  async function handleCreateBackup() {
    if (
      mutationInFlightRef.current !== null ||
      creatingBackup ||
      restoringBackupId !== null ||
      restoreCandidate !== null
    ) {
      return;
    }
    mutationInFlightRef.current = "create";
    setCreatingBackup(true);
    setBackupError(null);
    setBackupSuccess(null);
    setRestoreError(null);
    try {
      const backup = await createBackup();
      queryClient.setQueryData<BackupMetadata[]>(queryKeys.backups, (current) =>
        prependUnique(current ?? [], backup),
      );
      setBackupSuccess(`Резервная копия ${backup.name} создана.`);
    } catch (error) {
      setBackupError(formatApiError(error));
    } finally {
      if (mutationInFlightRef.current === "create") {
        mutationInFlightRef.current = null;
      }
      setCreatingBackup(false);
    }
  }

  async function handleRestore() {
    if (
      restoreCandidate === null ||
      mutationInFlightRef.current !== null ||
      creatingBackup ||
      restoringBackupId !== null
    ) {
      return;
    }
    const candidate = restoreCandidate;
    mutationInFlightRef.current = "restore";
    setRestoringBackupId(candidate.id);
    setRestoreError(null);
    setRestoreErrorKind(null);
    setRestoreSuccess(null);
    setPreRestoreEvidence(null);
    setBackupError(null);
    try {
      brokerOriginalSession(queryClient).clear();
      const result: unknown = await restoreBackup(candidate.id);
      if (!isRestoreResponse(result)) {
        throw new Error("Restore response payload is missing or malformed");
      }
      queryClient.setQueryData<BackupMetadata[]>(queryKeys.backups, (current) =>
        prependUnique(
          prependUnique(current ?? [], result.pre_restore_backup),
          result.restored_backup,
        ),
      );
      await queryClient.invalidateQueries();
      setPreRestoreEvidence(result.pre_restore_backup);
      setRestoreCandidate(null);
      setRestoreSuccess(`База восстановлена из ${result.restored_backup.name}.`);
    } catch (error) {
      if (!isConfirmedRestoreFailure(error)) {
        await queryClient.invalidateQueries().catch(() => undefined);
        setRestoreErrorKind("unknown");
        setRestoreError(
          "Результат восстановления не подтверждён. Состояние данных обновлено; сначала проверь его вручную.",
        );
        setRestoreCandidate(null);
      } else {
        setRestoreErrorKind("confirmed");
        setRestoreError(formatApiError(error));
      }
    } finally {
      if (mutationInFlightRef.current === "restore") {
        mutationInFlightRef.current = null;
      }
      setRestoringBackupId(null);
    }
  }

  const backupList = [...(backupsQuery.data ?? [])].sort(
    (a, b) => Date.parse(b.created_at) - Date.parse(a.created_at),
  );
  const noBackups = isQueryReady(backupsQuery) && backupList.length === 0;
  const filesBusy = !isQueryReady(monthsQuery) || !isQueryReady(backupsQuery);

  return (
    <UiV2DataFrame
      active="files"
      busy={filesBusy}
      monthId={selectedMonth?.id}
      subtitle="Сохрани копию базы или скачай отчёт."
      title="Экспорт и копии"
    >
      <div className={styles.surfaceStack} data-testid="data-files-page">
        <section
          aria-labelledby="files-backups-title"
          className={`${styles.surface} ${noBackups ? styles.backupWarning : ""}`}
          data-testid="files-backups"
        >
          <header className={styles.surfaceHeader}>
            <div>
              <h2 id="files-backups-title">Резервная копия</h2>
              {noBackups ? (
                <p data-testid="files-no-backups">
                  Резервных копий пока нет. Создай первую, чтобы сохранить данные.
                </p>
              ) : isQueryReady(backupsQuery) && backupList[0] ? (
                <p className={styles.latestBackup}>
                  Последняя —{" "}
                  <time dateTime={backupList[0].created_at}>
                    {formatDate(backupList[0].created_at)}
                  </time>
                </p>
              ) : null}
            </div>
            <div className={styles.backupHeaderAction}>
              <button
                className={noBackups ? styles.primaryButton : styles.secondaryButton}
                disabled={creatingBackup || restoringBackupId !== null}
                onClick={() => void handleCreateBackup()}
                type="button"
              >
                {creatingBackup ? "Создаём резервную копию…" : "Создать копию"}
              </button>
            </div>
          </header>

          {backupError ? (
            <div className={styles.error} role="alert">
              {backupError}
            </div>
          ) : null}
          {backupSuccess ? (
            <div className={styles.success} role="status">
              {backupSuccess}
            </div>
          ) : null}
          {restoreError ? (
            <div className={styles.error} role="alert">
              {restoreErrorKind === "unknown"
                ? restoreError
                : `Восстановление не выполнено: ${restoreError}`}
            </div>
          ) : null}
          {restoreSuccess ? (
            <div className={styles.success} role="status">
              {restoreSuccess}
            </div>
          ) : null}
          {preRestoreEvidence ? <RestoreEvidence backup={preRestoreEvidence} /> : null}

          {backupsQuery.isError ? (
            <UiV2Notice
              title="Не удалось загрузить резервные копии"
              retry={() => void backupsQuery.refetch()}
            >
              Список скрыт, пока локальное хранилище не подтверждено.
            </UiV2Notice>
          ) : !isQueryReady(backupsQuery) ? (
            <UiV2Loading label="Загружаем список резервных копий…" />
          ) : backupList.length === 0 ? null : (
            <table className={styles.backupTable} aria-label="Резервные копии">
              <thead>
                <tr>
                  <th scope="col">Создана</th>
                  <th scope="col">Копия</th>
                  <th scope="col" className={styles.size}>
                    Размер
                  </th>
                  <th scope="col">
                    <span className={styles.muted}>Действия</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {backupList.map((backup) => (
                  <tr key={backup.id}>
                    <td>
                      <time dateTime={backup.created_at}>{formatDate(backup.created_at)}</time>
                    </td>
                    <td
                      className={styles.backupName}
                      title={`Исходная база: ${backup.source_database.name}`}
                    >
                      {backup.name}
                    </td>
                    <td className={styles.size}>{backup.size_bytes} Б</td>
                    <td
                      onFocusCapture={(event) => {
                        if (
                          event.target instanceof HTMLButtonElement &&
                          event.target.getAttribute("aria-haspopup") === "menu"
                        ) {
                          restoreTriggerRef.current = event.target;
                        }
                      }}
                    >
                      <OverflowMenu label={`Действия с копией ${backup.name}`}>
                        <OverflowMenuItem
                          danger
                          aria-label={`Восстановить резервную копию ${backup.name}`}
                          disabled={creatingBackup || restoringBackupId !== null}
                          onClick={() => {
                            if (
                              mutationInFlightRef.current !== null ||
                              creatingBackup ||
                              restoringBackupId !== null
                            ) {
                              return;
                            }
                            setRestoreError(null);
                            setRestoreErrorKind(null);
                            setRestoreSuccess(null);
                            setRestoreCandidate(backup);
                          }}
                        >
                          Восстановить…
                        </OverflowMenuItem>
                      </OverflowMenu>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        <section
          aria-labelledby="files-exports-title"
          className={styles.surface}
          data-testid="files-exports"
        >
          <div className={styles.cardGrid}>
            <article className={`${styles.card} ${styles.cardRecommended}`}>
              <h2 id="files-exports-title">Отчёт для AI</h2>
              <p>
                Ежемесячный файл с капиталом, портфелем, динамикой, пассивным доходом, целями,
                долгами, недвижимостью, будущими выплатами, сигналами качества и комментариями.
              </p>
              <div className={styles.warning} role="note">
                <strong>Внимание:</strong> файл содержит финансовые данные. Hermes создаёт его
                только локально — ничего не загружается и не отправляется автоматически.
              </div>
              <div className={styles.buttonRow}>
                <button
                  className={styles.primaryButton}
                  disabled={downloadKind !== null}
                  onClick={() => void downloadAiReview()}
                  type="button"
                >
                  {downloadKind === "ai-review" ? "Готовим отчёт…" : "Выгрузить отчёт для AI"}
                </button>
              </div>
            </article>

            <article className={styles.card} data-testid="month-exports">
              <h2>Отчёт одного месяца</h2>
              <p>
                Скачай существующие Markdown или JSON отчёты для явно выбранного отчётного месяца.
              </p>
              <MonthExportState
                downloadError={downloadError}
                downloadKind={downloadKind}
                downloadSuccess={downloadSuccess}
                monthsQuery={monthsQuery}
                onDownload={(format) => void downloadMonth(format)}
                params={params}
                resolution={resolution}
                selectedMonth={selectedMonth}
                setParams={setParams}
              />
            </article>
          </div>

          <details className={styles.technicalDisclosure}>
            <summary>Технические выгрузки</summary>
            <div className={styles.technicalContent}>
              <section className={styles.technicalCard}>
                <p className={styles.kicker}>Дополнительный технический раздел</p>
                <h3>Пакет для AI-анализа</h3>
                <p>
                  Полная доступная история и коды причин для проверки AI-контракта. Это локальный
                  файл; перед ручной передачей проверь его состав.
                </p>
                <div className={styles.buttonRow}>
                  <button
                    className={styles.primaryButton}
                    disabled={downloadKind !== null}
                    onClick={() => void downloadBundle("json")}
                    type="button"
                  >
                    {downloadKind === "bundle-json"
                      ? "Готовим JSON…"
                      : "Скачать пакет анализа (JSON)"}
                  </button>
                  <button
                    className={styles.secondaryButton}
                    disabled={downloadKind !== null}
                    onClick={() => void downloadBundle("markdown")}
                    type="button"
                  >
                    {downloadKind === "bundle-markdown"
                      ? "Готовим Markdown…"
                      : "Скачать Markdown-компаньон"}
                  </button>
                </div>
              </section>
              <PortfolioReviewPackagePanel />
              <MyBrokerImportPanel />
            </div>
          </details>
        </section>
      </div>

      <ConfirmDialog
        busy={restoringBackupId !== null}
        danger
        description={
          restoreCandidate === null
            ? ""
            : `Выбрана копия: ${restoreCandidate.name}. Текущая локальная база будет заменена этой копией. Все изменения, внесённые после создания выбранной копии, будут потеряны. Это необратимое действие; перед заменой система сохранит копию текущей базы.`
        }
        onCancel={() => {
          if (restoringBackupId === null) setRestoreCandidate(null);
        }}
        onConfirm={() => void handleRestore()}
        open={restoreCandidate !== null}
        title="Восстановить базу?"
        confirmLabel="Восстановить"
      />
    </UiV2DataFrame>
  );
}
