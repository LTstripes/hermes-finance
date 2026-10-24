import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { ApiClientError, formatApiError } from "../../api/client";
import { readSourceIntake, saveSourceIntake } from "../../api/sourceIntake";
import { formatDate } from "../../lib/format";
import styles from "./SourceIntakeUpload.module.css";

type Upload = {
  id: string;
  name: string;
  state: string;
  detail: string;
  intakeId?: number;
  readbackFailed?: boolean;
};
/** Shared multi-file source-only intake. No identity acceptance or financial Apply. */
export function SourceIntakeUpload({ compact = false }: { compact?: boolean }) {
  const client = useQueryClient();
  const [uploads, setUploads] = useState<Upload[]>([]);
  const uploadBusy = useRef(false);
  const [uploading, setUploading] = useState(false);
  const mounted = useRef(true);
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
  async function readUploadedIntake(id: string, intakeId: number) {
    updateUpload(id, { state: "Сохранен · читаем", intakeId, readbackFailed: false });
    try {
      const intake = await readSourceIntake(intakeId);
      if (intake.id !== intakeId || intake.financial_authority !== "none")
        throw new Error("Независимое чтение вернуло другой источник или финансовую власть.");
      const detail = compact
        ? `${formatDate(intake.covered_from)} — ${formatDate(intake.covered_to)}. Сохранено наблюдений: ${intake.observations.length}. Исключений: ${intake.exceptions.length}.`
        : intake.exceptions.length
          ? `Сохранено наблюдений: ${intake.observations.length}. Флаги: ${intake.exceptions.join(", ")}`
          : `Сохранено наблюдений: ${intake.observations.length}. Пробелов не найдено.`;
      updateUpload(id, { state: "Сохранен", detail });
    } catch (error) {
      updateUpload(id, {
        state: "Сохранен · не удалось прочитать",
        detail: `Сохранение подтверждено. Повторите чтение без повторной загрузки. ${formatApiError(error)}`,
        readbackFailed: true,
      });
    }
  }
  async function retryReadback(id: string, intakeId: number) {
    if (uploadBusy.current) return;
    uploadBusy.current = true;
    setUploading(true);
    try {
      await readUploadedIntake(id, intakeId);
    } finally {
      uploadBusy.current = false;
      if (mounted.current) setUploading(false);
    }
  }
  async function upload(files: File[]) {
    if (uploadBusy.current || !files.length) return;
    uploadBusy.current = true;
    setUploading(true);
    const batch = files.map((file) => ({ file, id: crypto.randomUUID() }));
    setUploads(
      batch.map(({ file, id }) => ({ id, name: file.name, state: "Сохраняем", detail: "" })),
    );
    try {
      await Promise.all(
        batch.map(async ({ file, id }) => {
          let intakeId: number;
          try {
            const ack = await saveSourceIntake(file, id, 0, null);
            intakeId = ack.intake_id;
          } catch (error) {
            const detail =
              error instanceof ApiClientError && error.status === 409
                ? `${formatApiError(error)} Причина: ${error.message}`
                : formatApiError(error);
            const rejected =
              error instanceof ApiClientError && error.status >= 400 && error.status < 500;
            updateUpload(id, {
              state: rejected ? "Не сохранен" : "Результат сохранения неизвестен",
              detail: rejected
                ? detail
                : `Не повторяй загрузку вслепую. Обнови список источников и проверь результат. ${detail}`,
            });
            return;
          }
          await readUploadedIntake(id, intakeId);
        }),
      );
      await client.invalidateQueries({ queryKey: ["source-intakes"] });
      await client.invalidateQueries({ queryKey: ["source-returns"] });
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
          disabled={uploading}
          onChange={(event) => {
            const files = Array.from(event.target.files ?? []);
            event.target.value = "";
            void upload(files);
          }}
        />
      </label>
      <p className={styles.note}>
        Source Save ≠ financial Apply. Каждый файл обрабатывается отдельно: всё распознанное
        сохраняется в журнал без финансовых изменений, а пробелы и флаги остаются видимыми.
      </p>
      {uploads.length > 0 && (
        <ul className={styles.fileList}>
          {uploads.map((item) => (
            <li key={item.id}>
              <strong>
                {item.name}: {item.state}
              </strong>
              {item.detail && <> — {item.detail}</>}
              {item.readbackFailed && item.intakeId !== undefined && (
                <button
                  type="button"
                  disabled={uploading}
                  onClick={() => {
                    if (item.intakeId !== undefined) void retryReadback(item.id, item.intakeId);
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
