import { useEffect, useMemo, useState } from "react";

import type { QuoteApplyRowRequest, QuotePreview, QuotePreviewRow } from "../api/types";
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
  applying?: boolean;
  error: string | null;
  closedMonthHint: boolean;
  onRefresh: () => void;
  onApply?: (rows: QuoteApplyRowRequest[]) => void;
};

function statusLabel(status: string): string {
  return labelOf(QUOTE_PREVIEW_STATUS_LABELS, status);
}

function rowClassName(row: QuotePreviewRow): string {
  return row.status === "stale"
    ? "quote-preview-row quote-preview-row--stale"
    : "quote-preview-row";
}

function canSelect(row: QuotePreviewRow, monthEditable: boolean): boolean {
  if (!monthEditable || row.proposed_market_price_per_unit == null || row.identity == null) {
    return false;
  }
  if (row.apply_allowed) {
    return true;
  }
  return row.status === "stale" && row.identity.provider === "t_invest";
}

function toApplyRequest(row: QuotePreviewRow, acceptStale: boolean): QuoteApplyRowRequest | null {
  if (
    row.proposed_market_price_per_unit == null ||
    row.proposed_price_date == null ||
    row.identity == null
  ) {
    return null;
  }
  return {
    position_snapshot_id: row.position_snapshot_id,
    accept_stale: acceptStale,
    expected_market_price_per_unit: row.proposed_market_price_per_unit,
    expected_price_date: row.proposed_price_date,
    expected_identity: row.identity,
    expected_quote_kind: row.proposed_quote_kind,
  };
}

function PreviewRow({
  row,
  selected,
  selectable,
  onToggle,
}: {
  row: QuotePreviewRow;
  selected: boolean;
  selectable: boolean;
  onToggle: (next: boolean) => void;
}) {
  const proposed = row.proposed_market_price_per_unit;
  const delta = displayPriceDelta(row.current_market_price_per_unit, proposed);
  const currentAmount = moneyAmount(row.current_market_price_per_unit);
  return (
    <tr className={rowClassName(row)} data-preview-status={row.status}>
      <Td>
        {selectable ? (
          <label className="stack-8">
            <input
              aria-label={
                row.status === "stale"
                  ? `Выбрать старую котировку ${row.instrument_name}`
                  : `Выбрать ${row.instrument_name}`
              }
              checked={selected}
              onChange={(event) => onToggle(event.target.checked)}
              type="checkbox"
            />
          </label>
        ) : null}
      </Td>
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
              Чтобы применить такую цену, её нужно выбрать отдельно.
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

export function QuotePreviewPanel({
  preview,
  loading,
  applying = false,
  error,
  closedMonthHint,
  onRefresh,
  onApply,
}: Props) {
  const monthLocked = closedMonthHint || preview?.month_editable === false;
  const [selectedIds, setSelectedIds] = useState<Set<number>>(
    () =>
      new Set(
        preview && !monthLocked
          ? preview.rows.filter((row) => row.apply_allowed).map((row) => row.position_snapshot_id)
          : [],
      ),
  );

  useEffect(() => {
    setSelectedIds(
      new Set(
        preview && !monthLocked
          ? preview.rows.filter((row) => row.apply_allowed).map((row) => row.position_snapshot_id)
          : [],
      ),
    );
  }, [preview, monthLocked]);

  const selectedRows = useMemo(() => {
    if (!preview) {
      return [];
    }
    return preview.rows.filter(
      (row) => selectedIds.has(row.position_snapshot_id) && canSelect(row, !monthLocked),
    );
  }, [preview, selectedIds, monthLocked]);

  const applyRequests = selectedRows
    .map((row) => toApplyRequest(row, row.status === "stale"))
    .filter((row): row is QuoteApplyRowRequest => row != null);

  return (
    <Panel
      action={
        <div className="inline-actions">
          <Button
            disabled={loading || applying}
            onClick={onRefresh}
            type="button"
            variant="primary"
          >
            {loading ? "Обновляем…" : "Обновить котировки"}
          </Button>
          {preview &&
          onApply &&
          !monthLocked &&
          preview.rows.some((row) => canSelect(row, true)) ? (
            <Button
              disabled={loading || applying || applyRequests.length === 0}
              onClick={() => onApply(applyRequests)}
              type="button"
            >
              {applying ? "Применяем…" : "Применить выбранные"}
            </Button>
          ) : null}
        </div>
      }
      label="Рынок"
      title="Предпросмотр котировок"
    >
      <p className="muted">
        Запрос к внешнему источнику идёт только по этой кнопке. Сохранённые цены месяца меняются
        только после явного применения выбранных строк.
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
              <Th>Выбор</Th>
              <Th>Инструмент</Th>
              <Th numeric>Сейчас</Th>
              <Th numeric>Предложение</Th>
              <Th>Дата внешней котировки</Th>
              <Th>Статус</Th>
            </tr>
          </thead>
          <tbody>
            {preview.rows.map((row) => (
              <PreviewRow
                key={row.position_snapshot_id}
                onToggle={(next) => {
                  setSelectedIds((current) => {
                    const copy = new Set(current);
                    if (next) {
                      copy.add(row.position_snapshot_id);
                    } else {
                      copy.delete(row.position_snapshot_id);
                    }
                    return copy;
                  });
                }}
                row={row}
                selectable={canSelect(row, !monthLocked)}
                selected={selectedIds.has(row.position_snapshot_id)}
              />
            ))}
          </tbody>
        </Table>
      ) : null}
    </Panel>
  );
}
