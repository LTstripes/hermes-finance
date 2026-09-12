import { useState } from "react";

import { downloadAiFinancialReviewJson } from "../api/exports";
import { formatApiError } from "../api/client";
import { Badge, Button, Panel } from "./ui";

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.style.display = "none";
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export function AiFinancialReviewPanel() {
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  async function handleDownload() {
    setDownloading(true);
    setDownloadError(null);
    setSuccess(null);
    try {
      const file = await downloadAiFinancialReviewJson();
      triggerDownload(file.blob, file.filename);
      setSuccess(`Файл ${file.filename} скачан.`);
    } catch (error) {
      setDownloadError(formatApiError(error));
    } finally {
      setDownloading(false);
    }
  }

  return (
    <Panel label="Рекомендуемый для AI-анализа" title="Полный финансовый отчёт для AI">
      <div className="stack-12">
        <p>
          <Badge tone="ok">Рекомендуется</Badge>
        </p>
        <p>
          Обычный ежемесячный файл для ChatGPT или другого AI. Включает капитал, портфель, динамику
          по месяцам, пассивный доход, цели, долги и недвижимость, будущие выплаты, сигналы о
          качестве данных и ваши комментарии.
        </p>
        <div className="inline-alert inline-alert--warn" role="note">
          <strong>Внимание:</strong> файл содержит финансовые данные. Проверь его перед ручной
          загрузкой в ассистент.
        </div>
        <p className="muted">
          Hermes только создаёт локальный файл и ничего никуда не отправляет. Загрузи его вручную и
          спроси ассистента о трендах, рисках или решениях.
        </p>
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
            disabled={downloading}
            onClick={() => void handleDownload()}
            type="button"
            variant="primary"
          >
            {downloading ? "Готовим отчёт…" : "Выгрузить отчёт для AI"}
          </Button>
        </div>
      </div>
    </Panel>
  );
}
