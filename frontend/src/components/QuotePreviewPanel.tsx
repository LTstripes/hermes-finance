import type { QuotePreview, QuotePreviewRow } from "../api/types";
import { formatDate, formatMoney } from "../lib/format";
import { INSTRUMENT_TYPE_LABELS, PRICE_SOURCE_LABELS, labelOf } from "../lib/labels";
import {
  displayPriceDelta,
  formatMarketIdentity,
  QUOTE_PREVIEW_STATUS_LABELS,
  quoteStatusTone,
} from "../lib/marketData";
import { moneyAmount } from "../lib/money";
import { Badge, Button, EmptyState, LoadingState, Panel, Table, Td, Th } from "./ui";

type Props = {
  preview: QuotePreview | null;
  loading: boolean;
  error: string | null;
  closedMonthHint: boolean;
  onRefresh: () => void;
};

function statusLabel(status: string): string {
  return labelOf(QUOTE_PREVIEW_STATUS_LABELS, status);
}

function rowClassName(row: QuotePreviewRow): string {
  return row.status === "stale"
    ? "quote-preview-row quote-preview-row--stale"
    : "quote-preview-row";
}

function PreviewRow({ row }: { row: QuotePreviewRow }) {
  const proposed = row.proposed_market_price_per_unit;
  const delta = displayPriceDelta(row.current_market_price_per_unit, proposed);
  const currentAmount = moneyAmount(row.current_market_price_per_unit);
  return (
    <tr className={rowClassName(row)} data-preview-status={row.status}>
      <Td>
        <div className="stack-8">
          <strong>{row.instrument_name}</strong>
          <span className="muted tiny">{labelOf(INSTRUMENT_TYPE_LABELS, row.instrument_type)}</span>
          {row.identity ? (
            <span className="muted tiny">{formatMarketIdentity(row.identity)}</span>
          ) : null}
        </div>
      </Td>
      <Td numeric>
        <div className="stack-8">
          <span>{formatMoney(currentAmount)}</span>
          <span className="muted tiny">
            Сейчас: {labelOf(PRICE_SOURCE_LABELS, row.current_price_source)} ·{" "}
            {formatDate(row.current_price_date)}
          </span>
        </div>
      </Td>
      <Td numeric>
        {proposed ? formatMoney(moneyAmount(proposed)) : "—"}
        {delta ? <div className="muted tiny">{delta}</div> : null}
      </Td>
      <Td>{row.proposed_price_date ? formatDate(row.proposed_price_date) : "—"}</Td>
      <Td>
        <div className="stack-8">
          <Badge tone={quoteStatusTone(row.status)}>{statusLabel(row.status)}</Badge>
          {row.status === "stale" ? (
            <span className="quote-preview-stale-note">
              Не обычное обновление. Дата внешней котировки: {formatDate(row.proposed_price_date)}.
              Чтобы применить такую цену позже, её нужно будет выбрать отдельно.
            </span>
          ) : null}
          {row.status === "unsupported" ||
          row.status === "unmapped" ||
          row.status === "excluded" ? (
            <span className="muted tiny">Текущая ручная цена остаётся обычным значением.</span>
          ) : null}
          {row.message ? <span className="muted tiny">{row.message}</span> : null}
        </div>
      </Td>
    </tr>
  );
}

export function QuotePreviewPanel({ preview, loading, error, closedMonthHint, onRefresh }: Props) {
  const monthLocked = closedMonthHint || preview?.month_editable === false;

  return (
    <Panel
      action={
        <Button disabled={loading} onClick={onRefresh} type="button" variant="primary">
          {loading ? "Обновляем…" : "Обновить котировки"}
        </Button>
      }
      label="Рынок"
      title="Предпросмотр котировок"
    >
      <p className="muted">
        Запрос к внешнему источнику идёт только по этой кнопке. Сохранённые цены месяца не меняются.
      </p>
      {monthLocked ? (
        <div className="inline-alert inline-alert--warn" role="status">
          Месяц утверждён и его нельзя изменить. Предпросмотр можно смотреть, применение цен здесь
          недоступно.
        </div>
      ) : null}
      {error ? (
        <div className="inline-alert inline-alert--error" role="alert">
          {error}
        </div>
      ) : null}
      {preview?.batch_error ? (
        <div className="inline-alert inline-alert--warn" role="status">
          Часть запросов к источнику не удалась. Строки ниже сохранены.
        </div>
      ) : null}
      {loading && !preview ? <LoadingState description="Запрашиваем котировки…" inline /> : null}
      {preview && preview.rows.length === 0 ? (
        <EmptyState
          description="В этом месяце нет позиций, для которых можно показать предпросмотр."
          inline
          title="Предпросмотр пуст"
        />
      ) : null}
      {preview && preview.rows.length > 0 ? (
        <Table aria-label="Предпросмотр котировок">
          <thead>
            <tr>
              <Th>Инструмент</Th>
              <Th numeric>Сейчас</Th>
              <Th numeric>Предложение</Th>
              <Th>Дата внешней котировки</Th>
              <Th>Статус</Th>
            </tr>
          </thead>
          <tbody>
            {preview.rows.map((row) => (
              <PreviewRow key={row.position_snapshot_id} row={row} />
            ))}
          </tbody>
        </Table>
      ) : null}
    </Panel>
  );
}
