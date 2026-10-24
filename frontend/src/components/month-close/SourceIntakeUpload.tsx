import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { ApiClientError, formatApiError } from "../../api/client";
import { type IntakeAck, readSourceIntake, saveSourceIntake } from "../../api/sourceIntake";
import { formatDate } from "../../lib/format";
import styles from "./SourceIntakeUpload.module.css";

type Upload = {
  id: string;
  name: string;
  state: string;
  detail: string;
  ack?: IntakeAck;
  readbackFailed?: boolean;
  uncertain?: boolean;
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
    if (uploadBusy.current || !files.length) return;
    uploadBusy.current = true;
    setUploading(true);
    const batch = files.map((file) => ({ file, id: crypto.randomUUID() }));
    setUploads((previous) => [
      ...previous.filter((item) => item.readbackFailed || item.uncertain),
      ...batch.map(({ file, id }) => ({ id, name: file.name, state: "Сохраняем", detail: "" })),
    ]);
    try {
      await Promise.all(
        batch.map(async ({ file, id }) => {
          let ack: IntakeAck;
          try {
            ack = await saveSourceIntake(file, id, 0, null);
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
              error instanceof ApiClientError && error.status >= 400 && error.status < 500;
            updateUpload(id, {
              state: rejected ? "Не сохранен" : "Результат сохранения неизвестен",
              uncertain: !rejected,
              detail: rejected
                ? detail
                : `Не повторяй загрузку вслепую. Обнови список источников и проверь результат. ${detail}`,
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
