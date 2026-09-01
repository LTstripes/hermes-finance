import type {
  PayoutApplyResult,
  PayoutBatchPreview,
  PayoutBatchPreviewItem,
} from "../../api/payouts";
import type { QuoteApplyResult, QuotePreview, QuotePreviewStatus } from "../../api/types";
import { formatDate } from "../../lib/format";
import { Badge } from "../ui";

type SummaryTone = "ok" | "info" | "stale";

function quoteStatusCount(preview: QuotePreview, status: QuotePreviewStatus): number {
  return preview.rows.filter((row) => row.status === status).length;
}

function quoteErrorCount(preview: QuotePreview): number {
  return preview.rows.filter(
    (row) => row.status === "network_error" || row.status === "malformed_response",
  ).length;
}

function quoteSummaryTone(preview: QuotePreview, errors: number): SummaryTone {
  if (errors > 0 || preview.batch_error) return "stale";
  if (
    quoteStatusCount(preview, "stale") > 0 ||
    quoteStatusCount(preview, "unavailable") > 0 ||
    quoteStatusCount(preview, "unmapped") > 0 ||
    quoteStatusCount(preview, "ambiguous") > 0
  ) {
    return "stale";
  }
  if (quoteStatusCount(preview, "excluded") > 0 || quoteStatusCount(preview, "unsupported") > 0) {
    return "info";
  }
  return "ok";
}

function appliedQuoteDates(result: QuoteApplyResult): string {
  const dates = [...new Set(result.rows.map((row) => row.price_date).filter(Boolean))];
  return dates.length > 0 ? dates.map((date) => formatDate(date)).join(", ") : "—";
}

export function QuotePreviewSummary({
  applyResult,
  preview,
}: {
  applyResult: QuoteApplyResult | null;
  preview: QuotePreview | null;
}) {
  if (applyResult) {
    return (
      <div
        aria-label="Результат применения котировок"
        className="inline-alert inline-alert--ok"
        role="status"
      >
        <strong>Котировки применены: {applyResult.applied_count}.</strong> Данные месяца изменены
        только для выбранных строк. Даты цен: {appliedQuoteDates(applyResult)}. Новый preview
        запускается отдельной кнопкой.
      </div>
    );
  }

  if (!preview) return null;

  const errors = quoteErrorCount(preview);
  const tone = quoteSummaryTone(preview, errors);
  const unmapped = quoteStatusCount(preview, "unmapped") + quoteStatusCount(preview, "ambiguous");
  return (
    <div
      aria-label="Итог предпросмотра котировок"
      className="inline-alert inline-alert--info"
      role="status"
    >
      <Badge tone={tone}>
        {tone === "ok"
          ? "Предпросмотр готов"
          : tone === "info"
            ? "Есть исключения"
            : "Нужно внимание"}
      </Badge>{" "}
      {preview.rows.length} строк · готово {quoteStatusCount(preview, "ok")} · старых{" "}
      {quoteStatusCount(preview, "stale")} · недоступно {quoteStatusCount(preview, "unavailable")} ·
      без сопоставления {unmapped} · исключено {quoteStatusCount(preview, "excluded")} · ошибок{" "}
      {errors}. Целевая дата оценки: {formatDate(preview.target_date)}.
    </div>
  );
}

export function TInvestBatchSummary({ preview }: { preview: PayoutBatchPreview }) {
  const { summary } = preview;
  const tone: SummaryTone =
    summary.errors > 0
      ? "stale"
      : summary.skipped > 0 || summary.without_events > 0
        ? "info"
        : "ok";
  const label =
    summary.errors > 0
      ? "Частичный результат"
      : summary.skipped > 0
        ? "Есть пропуски"
        : summary.without_events > 0
          ? "Есть позиции без событий"
          : "Проверка завершена";
  return (
    <div
      aria-label="Итог проверки будущих выплат"
      className="inline-alert inline-alert--info"
      role="status"
    >
      <Badge tone={tone}>{label}</Badge> {summary.total_positions} позиций · {summary.with_events} с
      событиями · {summary.without_events} без событий · {summary.errors} ошибок · {summary.skipped}{" "}
      пропущено · доступно для T-Invest: {summary.eligible_positions}.
    </div>
  );
}

function batchItemStatus(status: string): { label: string; tone: SummaryTone } {
  if (status === "skipped") return { label: "Пропущено", tone: "info" };
  if (status === "no_events") return { label: "Событий нет", tone: "info" };
  if (status === "applied") return { label: "Применено", tone: "ok" };
  if (status === "previewed") return { label: "Предпросмотр готов", tone: "ok" };
  return { label: "Ошибка", tone: "stale" };
}

export function TInvestBatchItemStatus({ item }: { item: PayoutBatchPreviewItem }) {
  const status = batchItemStatus(item.status);
  return <Badge tone={status.tone}>{status.label}</Badge>;
}

export function TInvestPayoutApplySummary({ result }: { result: PayoutApplyResult | null }) {
  if (!result) return null;
  return (
    <div
      aria-label="Результат применения выплат"
      className="inline-alert inline-alert--ok"
      role="status"
    >
      <strong>Применено выплат: {result.selected_count}.</strong> Календарь обновлён. Результат
      относится только к выбранным строкам; новый preview запускается отдельной кнопкой.
    </div>
  );
}
