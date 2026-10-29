import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { ApiClientError, formatApiError } from "../../api/client";
import {
  type IntakeAck,
  listAllSourceIntakes,
  readSourceIntake,
  type SourceIntake,
  saveSourceIntake,
} from "../../api/sourceIntake";
import { formatDate } from "../../lib/format";
import { brokerSourceTitle } from "../../lib/ownerCopy";
import { SourceReportPreviewPanel } from "../SourceReportPreviewPanel";
import styles from "./SourceIntakeUpload.module.css";

async function originalDigest(file: File) {
  const bytes =
    typeof file.arrayBuffer === "function"
      ? await file.arrayBuffer()
      : await new Promise<ArrayBuffer>((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(reader.result as ArrayBuffer);
          reader.onerror = () => reject(reader.error);
          reader.readAsArrayBuffer(file);
        });
  const hash = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(hash)].map((value) => value.toString(16).padStart(2, "0")).join("");
}

type Upload = {
  id: string;
  name: string;
  state: string;
  detail: string;
  ack?: IntakeAck;
  readbackFailed?: boolean;
  uncertain?: boolean;
  technical?: string;
};
/** Shared multi-file source-only intake. No identity acceptance or financial Apply. */
export function SourceIntakeUpload({
  compact = false,
  onPendingChange,
  onSaved,
  onReview,
  reviewDisabled = false,
  knownSources,
  disabled = false,
}: {
  compact?: boolean;
  onPendingChange?: (value: boolean) => void;
  onSaved?: (file: File, intake: SourceIntake) => void;
  onReview?: (intakeId: number) => void;
  reviewDisabled?: boolean;
  knownSources?: SourceIntake[];
  disabled?: boolean;
}) {
  const client = useQueryClient();
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [previewFiles, setPreviewFiles] = useState<File[]>([]);
  const uploadBusy = useRef(false);
  const [uploading, setUploading] = useState(false);
  const [heldFiles, setHeldFiles] = useState<string[]>([]);
  const mounted = useRef(true);
  const filesByRequest = useRef(new Map<string, File>());
  const unresolved = uploads.some((item) => item.uncertain || item.readbackFailed);
  useEffect(() => {
    onPendingChange?.(uploading || unresolved);
  }, [uploading, unresolved, onPendingChange]);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  function updateUpload(id: string, patch: Partial<Upload>) {
    if (!mounted.current) return;
    setUploads((old) => old.map((item) => (item.id === id ? { ...item, ...patch } : item)));
  }
  async function readUploadedIntake(id: string, ack: IntakeAck) {
    updateUpload(id, { state: "Сохранен · читаем", ack, readbackFailed: false });
    try {
      const intake = await readSourceIntake(ack.intake_id);
      if (
        intake.contract_version !== "source_intake_v1" ||
        intake.id !== ack.intake_id ||
        intake.financial_authority !== "none" ||
        !Number.isSafeInteger(intake.head_seq) ||
        intake.head_seq < ack.head_seq ||
        !intake.history.some(
          (entry) => entry.seq === ack.head_seq && entry.request_id === ack.request_id,
        )
      )
        throw new Error("Независимое чтение не подтвердило сохранённую ревизию источника.");
      if (!mounted.current) return;
      const detail = compact
        ? `${formatDate(intake.covered_from)} — ${formatDate(intake.covered_to)}. Сохранено наблюдений: ${intake.observations.length}. Исключений: ${intake.exceptions.length}.`
        : intake.exceptions.length
          ? `Сохранено наблюдений: ${intake.observations.length}. Флаги: ${intake.exceptions.join(", ")}`
          : `Сохранено наблюдений: ${intake.observations.length}. Пробелов не найдено.`;
      updateUpload(id, { state: "Сохранен", detail });
      setHeldFiles([]);
      const file = filesByRequest.current.get(id);
      if (file) onSaved?.(file, intake);
    } catch (error) {
      updateUpload(id, {
        state: "Сохранен · не удалось прочитать",
        detail: `Сохранение подтверждено. Повторите чтение без повторной загрузки. ${formatApiError(error)}`,
        readbackFailed: true,
      });
    }
  }
  async function retryReadback(id: string, ack: IntakeAck) {
    if (uploadBusy.current) return;
    uploadBusy.current = true;
    setUploading(true);
    try {
      await readUploadedIntake(id, ack);
    } finally {
      uploadBusy.current = false;
      if (mounted.current) setUploading(false);
    }
  }
  async function upload(files: File[]) {
    if (uploadBusy.current || disabled || !files.length) return;
    // This is a conservative UI hold, not source identity/financial deduplication.
    // Independent files can still be saved while another file needs GET recovery.
    const held = files.filter((file) =>
      uploads.some((item) => {
        const prior = filesByRequest.current.get(item.id);
        return (
          (item.uncertain || item.readbackFailed) &&
          prior?.name === file.name &&
          prior.size === file.size
        );
      }),
    );
    setHeldFiles(held.map((file) => file.name));
    const fresh = files.filter((file) => !held.includes(file));
    if (!fresh.length) return;
    uploadBusy.current = true;
    setUploading(true);
    const batch = fresh.map((file) => ({ file, id: crypto.randomUUID() }));
    batch.forEach(({ id, file }) => {
      filesByRequest.current.set(id, file);
    });
    setUploads((previous) => [
      ...previous.filter((item) => item.readbackFailed || item.uncertain),
      ...batch.map(({ file, id }) => ({ id, name: file.name, state: "Сохраняем", detail: "" })),
    ]);
    try {
      await Promise.all(
        batch.map(async ({ file, id }) => {
          let ack: IntakeAck;
          let dispatched = false;
          try {
            let binding: SourceIntake["state"] | undefined;
            const bound = knownSources?.filter((source) => source.state.account_id !== null) ?? [];
            if (bound.length) {
              const digest = await originalDigest(file);
              const matches = bound.filter((source) => source.document_sha256 === digest);
              if (
                new Set(
                  matches.map(
                    (source) => `${source.state.account_id}:${source.state.reporting_month_id}`,
                  ),
                ).size > 1
              )
                throw new Error(
                  "У сохранённых версий этого XML разные привязки. Проверь существующий разбор и счёт.",
                );
              binding = matches[0]?.state;
            }
            // Exact original discovery preserves an existing annotation. Backend
            // Save and independent GET still validate it; no binding is inferred.
            dispatched = true;
            ack = await saveSourceIntake(
              file,
              id,
              binding?.reporting_month_id ?? 0,
              binding?.account_id ?? null,
            );
            if (
              !ack ||
              ack.request_id !== id ||
              !Number.isSafeInteger(ack.intake_id) ||
              ack.intake_id <= 0 ||
              !Number.isSafeInteger(ack.head_seq) ||
              ack.head_seq <= 0
            )
              throw new Error("Ответ сохранения не соответствует исходному запросу.");
          } catch (error) {
            const detail =
              error instanceof ApiClientError && error.status === 409
                ? `${formatApiError(error)} Причина: ${error.message}`
                : formatApiError(error);
            const rejected =
              !dispatched ||
              (error instanceof ApiClientError && error.status >= 400 && error.status < 500);
            updateUpload(id, {
              state: rejected ? "Не сохранен" : "Результат сохранения неизвестен",
              uncertain: !rejected,
              detail: compact
                ? rejected
                  ? error instanceof ApiClientError && error.message === "xml_invalid"
                    ? "XML не распознан. Проверь формат и целостность брокерской выписки."
                    : (brokerSourceTitle(error instanceof Error ? error.message : "") ??
                      formatApiError(error))
                  : "Неизвестно, завершилось ли сохранение. Проверь сохранение этого файла."
                : rejected
                  ? detail
                  : `Не повторяй загрузку вслепую. Обнови список источников и проверь результат. ${detail}`,
              technical: compact ? detail : undefined,
            });
            return;
          }
          await readUploadedIntake(id, ack);
        }),
      );
      await client.invalidateQueries({ queryKey: ["source-intakes"] });
      await client.invalidateQueries({ queryKey: ["source-returns"] });
    } finally {
      uploadBusy.current = false;
      if (mounted.current) setUploading(false);
    }
  }
  async function recoverUnknown(id: string) {
    if (uploadBusy.current) return;
    uploadBusy.current = true;
    setUploading(true);
    try {
      const matches = (await listAllSourceIntakes()).flatMap((intake) =>
        intake.history
          .filter((entry) => entry.request_id === id)
          .map((entry) => ({
            intake_id: intake.id,
            request_id: id,
            head_seq: entry.seq,
            duplicate: false,
          })),
      );
      if (matches.length !== 1)
        throw new Error(
          "Результат запроса пока не найден. Повтори чтение позже; новая загрузка не выполняется.",
        );
      await readUploadedIntake(id, matches[0]);
      updateUpload(id, { uncertain: false });
      await client.invalidateQueries({ queryKey: ["source-intakes"] });
    } catch (error) {
      updateUpload(id, { detail: formatApiError(error) });
    } finally {
      uploadBusy.current = false;
      if (mounted.current) setUploading(false);
    }
  }
  return (
    <div className={styles.upload}>
      <label>
        XML-файлы
        <input
          aria-label="XML-файлы"
          accept=".xml"
          multiple
          type="file"
          disabled={uploading || disabled}
          onChange={(event) => {
            const files = Array.from(event.target.files ?? []);
            setPreviewFiles(files);
            event.target.value = "";
            void upload(files);
          }}
        />
      </label>
      <SourceReportPreviewPanel xmlFiles={previewFiles} />
      <details className={styles.note}>
        <summary>Подробнее о сохранении выписок</summary>
        <p>
          Source Save ≠ financial Apply. Каждый файл обрабатывается отдельно: всё распознанное
          сохраняется в журнал без финансовых изменений, а пробелы и флаги остаются видимыми.
        </p>
      </details>
      {!!heldFiles.length && (
        <p role="alert">
          Сохранение {heldFiles.join(", ")} ещё не подтверждено. Сначала перечитай результат
          сохранения этого файла.
        </p>
      )}
      {uploads.length > 0 && (
        <ul className={styles.fileList}>
          {uploads.map((item) => (
            <li key={item.id}>
              <strong>
                {item.name}: {item.state}
              </strong>
              {item.detail && <> — {item.detail}</>}
              {item.technical && (
                <details>
                  <summary>Подробнее об ошибке</summary>
                  {item.technical}
                </details>
              )}
              {onReview &&
                item.ack &&
                item.state === "Сохранен" &&
                !item.uncertain &&
                !item.readbackFailed && (
                  <button
                    type="button"
                    disabled={uploading || reviewDisabled}
                    onClick={() => {
                      if (item.ack) onReview(item.ack.intake_id);
                    }}
                  >
                    Открыть разбор загрузки #{item.ack.intake_id}
                  </button>
                )}
              {item.uncertain && (
                <button
                  type="button"
                  disabled={uploading}
                  onClick={() => void recoverUnknown(item.id)}
                >
                  Проверить сохранение
                </button>
              )}
              {item.readbackFailed && item.ack && (
                <button
                  type="button"
                  disabled={uploading}
                  onClick={() => {
                    if (item.ack) void retryReadback(item.id, item.ack);
                  }}
                >
                  Повторить чтение {item.name}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
