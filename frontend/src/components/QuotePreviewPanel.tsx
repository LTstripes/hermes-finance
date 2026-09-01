import { useEffect, useMemo, useState } from "react";

import type {
  QuoteApplyResult,
  QuoteApplyRowRequest,
  QuotePreview,
  QuotePreviewRow,
} from "../api/types";
import { formatDate, formatMoney } from "../lib/format";
import { INSTRUMENT_TYPE_LABELS, labelOf, PRICE_SOURCE_LABELS } from "../lib/labels";
import {
  displayPriceDelta,
  formatMarketIdentity,
  QUOTE_PREVIEW_STATUS_LABELS,
  quoteFailureGuidance,
  quoteStatusTone,
} from "../lib/marketData";
import { moneyAmount } from "../lib/money";
import { QuotePreviewSummary } from "./month-close/TInvestStepSummary";
import { Badge, Button, EmptyState, HelpTip, LoadingState, Panel, Table, Td, Th } from "./ui";

type Props = {
  preview: QuotePreview | null;
  loading: boolean;
  applying?: boolean;
  applyResult?: QuoteApplyResult | null;
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
  const guidance = quoteFailureGuidance(row.failure_reason);
  const keepManualNote =
    row.status === "unsupported" || row.status === "unmapped" || row.status === "excluded";
  const hasStatusDetail = row.status === "stale" || keepManualNote || Boolean(guidance);
  return (
    <tr className={rowClassName(row)} data-preview-status={row.status}>
      <Td className="quote-preview-table__select">
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
        <div className="quote-preview-instrument">
          <strong>{row.instrument_name}</strong>
          <span className="muted tiny">{labelOf(INSTRUMENT_TYPE_LABELS, row.instrument_type)}</span>
          {row.identity ? (
            <HelpTip label={`Идентичность внешнего источника для ${row.instrument_name}`}>
              {formatMarketIdentity(row.identity)}
            </HelpTip>
          ) : null}
        </div>
      </Td>
      <Td numeric>
        <span className="quote-preview-price">
          <span>{formatMoney(currentAmount)}</span>
          <HelpTip label={`Текущая оценка для ${row.instrument_name}`}>
            <div>Источник: {labelOf(PRICE_SOURCE_LABELS, row.current_price_source)}</div>
            <div>Дата оценки: {formatDate(row.current_price_date)}</div>
          </HelpTip>
        </span>
      </Td>
      <Td numeric>
        <div className="quote-preview-proposed">
          <span>{proposed ? formatMoney(moneyAmount(proposed)) : "—"}</span>
          {delta ? <span className="muted tiny">{delta}</span> : null}
          <span className="quote-preview-proposed__date">
            {row.proposed_price_date ? formatDate(row.proposed_price_date) : "—"}
          </span>
        </div>
      </Td>
      <Td>
        <div className="quote-preview-status">
          <Badge tone={quoteStatusTone(row.status)}>{statusLabel(row.status)}</Badge>
          {row.status === "stale" ? (
            <span className="quote-preview-stale-note">Нужно выбрать отдельно</span>
          ) : null}
          {hasStatusDetail ? (
            <HelpTip label={`Подробности статуса для ${row.instrument_name}`}>
              {row.status === "stale" ? (
                <div>
                  Не обычное обновление. Дата внешней котировки:{" "}
                  {formatDate(row.proposed_price_date)}. Чтобы применить такую цену, её нужно
                  выбрать отдельно.
                </div>
              ) : null}
              {keepManualNote ? <div>Текущая ручная цена остаётся обычным значением.</div> : null}
              {guidance ? <div>{guidance}</div> : null}
            </HelpTip>
          ) : null}
        </div>
      </Td>
    </tr>
  );
}

export function QuotePreviewPanel({
  preview,
  loading,
  applying = false,
  applyResult = null,
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
      <QuotePreviewSummary applyResult={applyResult} preview={preview} />
      {preview?.batch_error_reason || preview?.batch_error ? (
        <div className="inline-alert inline-alert--warn" role="status">
          {quoteFailureGuidance(preview.batch_error_reason) ??
            "Часть запросов к внешнему источнику не удалась. Удачные строки ниже можно применить."}
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
        <Table aria-label="Предпросмотр котировок" className="quote-preview-table">
          <thead>
            <tr>
              <Th className="quote-preview-table__select">Выбор</Th>
              <Th>Инструмент</Th>
              <Th numeric>Сейчас</Th>
              <Th numeric>Предложение</Th>
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
