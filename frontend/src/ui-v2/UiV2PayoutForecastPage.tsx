import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router";

import { listAccounts } from "../api/accounts";
import { formatApiError } from "../api/client";
import { listExpectedFlows } from "../api/expectedFlows";
import { listInstruments } from "../api/instruments";
import { getCloseReadiness, getMonth, listMonths } from "../api/months";
import {
  applyPayouts,
  getPayoutRefreshStatus,
  listPayoutCalendar,
  previewPayouts,
  previewPayoutsBatch,
  type PayoutApplyResult,
  type PayoutApplySelection,
  type PayoutBatchPreview,
  type PayoutCalendarMonth,
  type PayoutContextRequest,
  type PayoutPreview,
  type PayoutRefreshStatus,
} from "../api/payouts";
import { listPositions } from "../api/positions";
import type { Account, Instrument, PositionSnapshot, ReportingMonth } from "../api/types";
import {
  monthlyCloseReturnPath,
  parseMonthlyCloseReturnContext,
  withMonthlyCloseReturn,
  withSelectedReturnMonth,
  type MonthlyCloseReturnContext,
} from "../components/month-close/navigation";
import {
  TInvestBatchItemStatus,
  TInvestBatchSummary,
  TInvestPayoutApplySummary,
} from "../components/month-close/TInvestStepSummary";
import { PayoutPaymentsCalendar } from "../components/PayoutPaymentsCalendar";
import { PayoutPreviewPanel } from "../components/PayoutPreviewPanel";
import {
  Badge,
  Button,
  ConfirmDialog,
  EmptyState,
  Field,
  LoadingState,
  Panel,
  Select,
} from "../components/ui";
import { formatMonth, formatQuantity } from "../lib/format";
import { INSTRUMENT_TYPE_LABELS, MONTH_STATUS_LABELS, labelOf } from "../lib/labels";
import { queryKeys } from "../queryClient";
import { resolveMonthSelection } from "./monthSelection";
import { DataMonthContext, UiV2DataFrame } from "./UiV2DataShell";
import { isQueryReady, UiV2Loading, UiV2Notice } from "./UiV2StateBlocks";
import styles from "./UiV2PayoutForecast.module.css";

const APPLY_FAILURE_LABELS: Record<string, string> = {
  preview_changed: "Предпросмотр изменился. Получи свежий preview и проверь выбор ещё раз.",
  closed_month: "Месяц закрыт. Сначала открой его для редактирования.",
  provider_error: "T-Invest не удалось безопасно перечитать данные. Ничего не применено.",
  validation_error: "Выбранные строки больше нельзя применить в этом состоянии.",
  persistence_error: "Не удалось сохранить выбранный набор. Все изменения отменены.",
};

const STALE_APPLY_MESSAGE =
  "Параметры изменились после preview. Получи свежий preview для текущего месяца, версии и позиции.";

type PendingApply = {
  payload: PayoutContextRequest;
  rows: PayoutApplySelection[];
  previewMonthId: number;
  previewVersion: string;
  batchPreviewId: number | null;
};

function newestMonth(months: ReportingMonth[]): ReportingMonth | undefined {
  return [...months].sort((a, b) => b.year - a.year || b.month - a.month || b.id - a.id)[0];
}

function PayoutForecastTool({
  monthId,
  close,
}: {
  monthId: number;
  close: MonthlyCloseReturnContext | null;
}) {
  const client = useQueryClient();
  const alive = useRef(true);
  const readGeneration = useRef(0);
  const applyGeneration = useRef(0);

  const [month, setMonth] = useState<ReportingMonth | null>(null);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [instruments, setInstruments] = useState<Instrument[]>([]);
  const [positions, setPositions] = useState<PositionSnapshot[]>([]);
  const [calendar, setCalendar] = useState<PayoutCalendarMonth[]>([]);
  const [refreshStatus, setRefreshStatus] = useState<PayoutRefreshStatus | null>(null);
  const [expectedCount, setExpectedCount] = useState<number | null>(null);

  const [selectedPositionId, setSelectedPositionId] = useState("");
  const [forecastVersion, setForecastVersion] = useState("v1");

  const [preview, setPreview] = useState<PayoutPreview | null>(null);
  const [previewMeta, setPreviewMeta] = useState<{
    monthId: number;
    version: string;
    positionSnapshotId: number;
  } | null>(null);
  const [batchPreview, setBatchPreview] = useState<PayoutBatchPreview | null>(null);
  const [batchMeta, setBatchMeta] = useState<{ monthId: number; version: string } | null>(null);

  const [loadingContext, setLoadingContext] = useState(true);
  const [contextError, setContextError] = useState<string | null>(null);
  const [monthMismatch, setMonthMismatch] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [batchLoading, setBatchLoading] = useState(false);
  const [applying, setApplying] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [lastApplyResult, setLastApplyResult] = useState<PayoutApplyResult | null>(null);
  const [pendingApply, setPendingApply] = useState<PendingApply | null>(null);

  const readOnly = month?.status === "closed";
  const version = forecastVersion.trim() || "v1";

  const accountById = useMemo(
    () => new Map(accounts.map((account) => [account.id, account])),
    [accounts],
  );
  const instrumentById = useMemo(
    () => new Map(instruments.map((instrument) => [instrument.id, instrument])),
    [instruments],
  );
  const selectedPosition = useMemo(
    () => positions.find((position) => String(position.id) === selectedPositionId) ?? null,
    [positions, selectedPositionId],
  );
  const positionLabel = useMemo(() => {
    if (!selectedPosition) return null;
    const account = accountById.get(selectedPosition.account_id);
    const instrument = instrumentById.get(selectedPosition.instrument_id);
    const instrumentText = instrument
      ? `${instrument.name}${instrument.ticker ? ` (${instrument.ticker})` : ""}`
      : `#${selectedPosition.instrument_id}`;
    return `${account?.name ?? `#${selectedPosition.account_id}`} · ${instrumentText}`;
  }, [accountById, instrumentById, selectedPosition]);

  function positionLabelFor(accountId: number, instrumentId: number): string {
    const account = accountById.get(accountId);
    const instrument = instrumentById.get(instrumentId);
    const instrumentText = instrument
      ? `${instrument.name}${instrument.ticker ? ` (${instrument.ticker})` : ""}`
      : `#${instrumentId}`;
    return `${instrumentText} · ${account?.name ?? `#${accountId}`}`;
  }

  const readContext = useCallback(async (target: number, targetVersion: string) => {
    const generation = ++readGeneration.current;
    setLoadingContext(true);
    setContextError(null);
    setMonthMismatch(false);
    try {
      const [
        freshMonth,
        accountRows,
        instrumentRows,
        positionRows,
        calendarRows,
        refreshRows,
        expectedRows,
      ] = await Promise.all([
        getMonth(target),
        listAccounts(),
        listInstruments({ active: true }),
        listPositions(target),
        listPayoutCalendar(target, targetVersion),
        getPayoutRefreshStatus(target),
        listExpectedFlows(target, targetVersion),
      ]);
      if (!alive.current || generation !== readGeneration.current) return;
      if (
        freshMonth.id !== target ||
        positionRows.some((row) => row.reporting_month_id !== target) ||
        expectedRows.some((row) => row.reporting_month_id !== target)
      ) {
        setMonthMismatch(true);
        setMonth(null);
        setAccounts([]);
        setInstruments([]);
        setPositions([]);
        setCalendar([]);
        setRefreshStatus(null);
        setExpectedCount(null);
        return;
      }
      // Local-only readback: no provider request happens here.
      await getCloseReadiness(target).catch(() => null);
      if (!alive.current || generation !== readGeneration.current) return;
      setMonth(freshMonth);
      setAccounts(accountRows);
      setInstruments(instrumentRows);
      setPositions(positionRows);
      setCalendar(calendarRows);
      setRefreshStatus(refreshRows);
      setExpectedCount(expectedRows.length);
      setSelectedPositionId((current) =>
        positionRows.some((row) => String(row.id) === current)
          ? current
          : positionRows[0]
            ? String(positionRows[0].id)
            : "",
      );
    } catch (cause) {
      if (alive.current && generation === readGeneration.current)
        setContextError(formatApiError(cause));
    } finally {
      if (alive.current && generation === readGeneration.current) setLoadingContext(false);
    }
  }, []);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      readGeneration.current += 1;
      applyGeneration.current += 1;
    };
  }, []);

  const versionRef = useRef(version);
  useEffect(() => {
    // Version is an explicit preview identity: local calendar reloads,
    // any previous provider preview becomes stale and can no longer apply.
    // Explicit local context only. Provider preview stays behind buttons.
    if (versionRef.current !== version) {
      versionRef.current = version;
      setPreview(null);
      setPreviewMeta(null);
      setBatchPreview(null);
      setBatchMeta(null);
      setActionError(null);
      setLastApplyResult(null);
      setPendingApply(null);
    }
    void readContext(monthId, version);
  }, [monthId, version, readContext]);

  function handleVersionChange(next: string) {
    const value = next || "v1";
    if (value !== forecastVersion) setForecastVersion(value);
  }

  function contextPayload(): PayoutContextRequest | null {
    if (!selectedPosition || !version) return null;
    return {
      account_id: selectedPosition.account_id,
      instrument_id: selectedPosition.instrument_id,
      position_snapshot_id: selectedPosition.id,
      forecast_version: version,
    };
  }

  async function handlePreview() {
    const payload = contextPayload();
    if (!payload || applying) return;
    const token = ++applyGeneration.current;
    setPreviewLoading(true);
    setActionError(null);
    setLastApplyResult(null);
    try {
      const value = await previewPayouts(monthId, payload);
      if (!alive.current || token !== applyGeneration.current) return;
      if (value.reporting_month_id !== monthId) {
        setPreview(null);
        setPreviewMeta(null);
        setActionError("Получен preview другого месяца. Обнови данные.");
        return;
      }
      setPreview(value);
      setPreviewMeta({
        monthId,
        version,
        positionSnapshotId: payload.position_snapshot_id,
      });
    } catch (cause) {
      if (!alive.current || token !== applyGeneration.current) return;
      setPreview(null);
      setPreviewMeta(null);
      setActionError(formatApiError(cause));
    } finally {
      if (alive.current && token === applyGeneration.current) setPreviewLoading(false);
    }
  }

  async function handleBatchPreview(positionSnapshotIds?: number[]) {
    if (!version || applying) return;
    const token = ++applyGeneration.current;
    setBatchLoading(true);
    setActionError(null);
    setLastApplyResult(null);
    try {
      const value = await previewPayoutsBatch(monthId, version, positionSnapshotIds);
      if (!alive.current || token !== applyGeneration.current) return;
      if (value.reporting_month_id !== monthId) {
        setBatchPreview(null);
        setBatchMeta(null);
        setActionError("Получен batch preview другого месяца. Обнови данные.");
        return;
      }
      setBatchPreview(value);
      setBatchMeta({ monthId, version });
    } catch (cause) {
      if (!alive.current || token !== applyGeneration.current) return;
      setBatchPreview(null);
      setBatchMeta(null);
      setActionError(formatApiError(cause));
    } finally {
      if (alive.current && token === applyGeneration.current) setBatchLoading(false);
    }
  }

  async function handleBatchPositionRefresh(positionSnapshotId: number) {
    const position = positions.find((row) => row.id === positionSnapshotId);
    if (!position || applying) return;
    const token = ++applyGeneration.current;
    setPreviewLoading(true);
    setActionError(null);
    setLastApplyResult(null);
    try {
      const value = await previewPayouts(monthId, {
        account_id: position.account_id,
        instrument_id: position.instrument_id,
        position_snapshot_id: position.id,
        forecast_version: version,
      });
      if (!alive.current || token !== applyGeneration.current) return;
      if (value.reporting_month_id !== monthId) {
        setActionError("Получен preview другого месяца. Обнови данные.");
        return;
      }
      setBatchPreview((current) =>
        current
          ? {
              ...current,
              items: current.items.map((item) =>
                item.position_snapshot_id === positionSnapshotId
                  ? {
                      ...item,
                      status: value.rows.length === 0 ? "no_events" : "previewed",
                      message: null,
                      preview: value,
                    }
                  : item,
              ),
            }
          : current,
      );
    } catch (cause) {
      if (!alive.current || token !== applyGeneration.current) return;
      setActionError(formatApiError(cause));
    } finally {
      if (alive.current && token === applyGeneration.current) setPreviewLoading(false);
    }
  }

  function requestSingleApply(rows: PayoutApplySelection[]) {
    const payload = contextPayload();
    if (!payload || rows.length === 0 || applying) return;
    if (readOnly) {
      setActionError(APPLY_FAILURE_LABELS.closed_month);
      return;
    }
    if (
      !preview ||
      !previewMeta ||
      previewMeta.monthId !== monthId ||
      previewMeta.version !== version ||
      previewMeta.positionSnapshotId !== payload.position_snapshot_id ||
      preview.reporting_month_id !== monthId
    ) {
      setPreview(null);
      setPreviewMeta(null);
      setActionError(STALE_APPLY_MESSAGE);
      return;
    }
    setPendingApply({
      payload,
      rows,
      previewMonthId: monthId,
      previewVersion: version,
      batchPreviewId: null,
    });
  }

  function requestBatchApply(previewValue: PayoutPreview, rows: PayoutApplySelection[]) {
    if (previewValue.position_snapshot_id === null || applying) return;
    if (readOnly) {
      setActionError(APPLY_FAILURE_LABELS.closed_month);
      return;
    }
    if (
      !batchMeta ||
      batchMeta.monthId !== monthId ||
      batchMeta.version !== version ||
      previewValue.reporting_month_id !== monthId
    ) {
      setBatchPreview(null);
      setBatchMeta(null);
      setActionError(STALE_APPLY_MESSAGE);
      return;
    }
    setPendingApply({
      payload: {
        account_id: previewValue.account_id,
        instrument_id: previewValue.instrument_id,
        position_snapshot_id: previewValue.position_snapshot_id,
        forecast_version: version,
      },
      rows,
      previewMonthId: monthId,
      previewVersion: version,
      batchPreviewId: previewValue.position_snapshot_id,
    });
  }

  async function confirmPendingApply() {
    const pending = pendingApply;
    if (!pending || applying) return;
    // Fail closed when the explicit target moved while confirming.
    if (pending.previewMonthId !== monthId || pending.previewVersion !== version) {
      setPendingApply(null);
      setPreview(null);
      setPreviewMeta(null);
      setBatchPreview(null);
      setBatchMeta(null);
      setActionError(STALE_APPLY_MESSAGE);
      return;
    }
    if (readOnly) {
      setPendingApply(null);
      setActionError(APPLY_FAILURE_LABELS.closed_month);
      return;
    }
    const token = ++applyGeneration.current;
    setApplying(true);
    setActionError(null);
    setLastApplyResult(null);
    try {
      const result = await applyPayouts(monthId, { ...pending.payload, rows: pending.rows });
      if (!alive.current || token !== applyGeneration.current) return;
      if (!result.success) {
        if (result.error_code === "preview_changed") {
          setPreview(null);
          setPreviewMeta(null);
          setBatchPreview(null);
          setBatchMeta(null);
        }
        setLastApplyResult(null);
        setActionError(
          (result.error_code && APPLY_FAILURE_LABELS[result.error_code]) ||
            result.message ||
            "Выплаты не применены.",
        );
        return;
      }
      // Authoritative readback for the same exact month/version before success.
      try {
        const [rereadMonth, rereadCalendar, rereadRefresh, rereadExpected] = await Promise.all([
          getMonth(monthId),
          listPayoutCalendar(monthId, version),
          getPayoutRefreshStatus(monthId),
          listExpectedFlows(monthId, version),
        ]);
        if (!alive.current || token !== applyGeneration.current) return;
        if (
          rereadMonth.id !== monthId ||
          rereadExpected.some((row) => row.reporting_month_id !== monthId)
        ) {
          setPreview(null);
          setPreviewMeta(null);
          setBatchPreview(null);
          setBatchMeta(null);
          setLastApplyResult(null);
          setActionError("Актуальный результат не подтверждён повторной загрузкой.");
          return;
        }
        setMonth(rereadMonth);
        setCalendar(rereadCalendar);
        setRefreshStatus(rereadRefresh);
        setExpectedCount(rereadExpected.length);
        setLastApplyResult(result);
        if (pending.batchPreviewId === null) {
          setPreview(null);
          setPreviewMeta(null);
        } else {
          setBatchPreview((current) =>
            current
              ? {
                  ...current,
                  items: current.items.map((item) =>
                    item.preview?.position_snapshot_id === pending.batchPreviewId
                      ? {
                          ...item,
                          status: "applied",
                          message: `Применено выплат: ${result.selected_count}`,
                          preview: null,
                        }
                      : item,
                  ),
                }
              : current,
          );
        }
        await client.invalidateQueries({ refetchType: "none" });
      } catch (cause) {
        if (!alive.current || token !== applyGeneration.current) return;
        setPreview(null);
        setPreviewMeta(null);
        setBatchPreview(null);
        setBatchMeta(null);
        setLastApplyResult(null);
        setActionError(formatApiError(cause));
      }
    } catch (cause) {
      if (!alive.current || token !== applyGeneration.current) return;
      setLastApplyResult(null);
      setActionError(formatApiError(cause));
    } finally {
      if (alive.current && token === applyGeneration.current) {
        setApplying(false);
        setPendingApply(null);
      }
    }
  }

  const manualEditorHref = month
    ? close
      ? withMonthlyCloseReturn(
          `/v2/data/months/${month.id}?section=payouts`,
          close.monthId,
          close.step,
          close.origin,
        )
      : `/v2/data/months/${month.id}?section=payouts`
    : null;

  if (loadingContext && !month && !contextError && !monthMismatch) {
    return <LoadingState description="Загружаем локальный календарь…" inline />;
  }
  if (contextError && !month) {
    return <EmptyState description={contextError} title="Не удалось открыть выплаты" />;
  }
  if (monthMismatch) {
    return (
      <div className="inline-alert inline-alert--error" role="alert">
        Получен результат другого месяца. Обнови данные.
      </div>
    );
  }
  if (!month) return null;

  return (
    <div className={styles.tool}>
      {contextError ? (
        <div className="inline-alert inline-alert--error" role="alert">
          {contextError}
        </div>
      ) : null}
      <TInvestPayoutApplySummary result={lastApplyResult} />

      <Panel
        action={
          <Badge tone={month.status === "closed" ? "closed" : "draft"}>
            {labelOf(MONTH_STATUS_LABELS, month.status)}
          </Badge>
        }
        label="Контекст"
        title="Месяц, версия и позиция"
      >
        <p className="muted">
          Календарь ниже — ожидание, а не факт. Погашение — возврат капитала, а не пассивный доход.
          Ручные факты остаются в разделе месяца #562 и здесь не дублируются.
        </p>
        <div className="editor-grid">
          <Field htmlFor="payout-forecast-position" label="Позиция">
            <Select
              disabled={loadingContext}
              id="payout-forecast-position"
              onChange={(event) => {
                setSelectedPositionId(event.target.value);
                setPreview(null);
                setPreviewMeta(null);
                setActionError(null);
                setLastApplyResult(null);
              }}
              value={selectedPositionId}
            >
              <option value="">— выбери позицию —</option>
              {positions.map((position) => {
                const account = accountById.get(position.account_id);
                const instrument = instrumentById.get(position.instrument_id);
                const type = instrument
                  ? labelOf(INSTRUMENT_TYPE_LABELS, instrument.instrument_type)
                  : "инструмент";
                return (
                  <option key={position.id} value={position.id}>
                    {account?.name ?? `#${position.account_id}`} ·{" "}
                    {instrument?.name ?? `#${position.instrument_id}`}
                    {instrument?.ticker ? ` (${instrument.ticker})` : ""} · {type} ·{" "}
                    {formatQuantity(position.quantity)} шт.
                  </option>
                );
              })}
            </Select>
          </Field>
          <div className="stack-8">
            <span className="muted tiny">Версия прогноза (меняется в панели preview ниже)</span>
            <strong>{version}</strong>
          </div>
        </div>
        <div className="toolbar">
          {manualEditorHref ? (
            <Link className="btn btn--ghost" to={manualEditorHref}>
              Ручные выплаты этого месяца →
            </Link>
          ) : null}
          <span className="muted tiny">
            {expectedCount === null
              ? "Ручные ожидаемые строки проверяются локально."
              : `Ручных ожидаемых строк версии «${version}»: ${expectedCount}.`}
          </span>
        </div>
        {selectedPositionId && !loadingContext && positions.length === 0 ? (
          <EmptyState
            description="В этом месяце нет локальных PositionSnapshot. Сначала добавь позицию в месяце."
            inline
            title="Нет позиций"
          />
        ) : null}
      </Panel>

      <PayoutPreviewPanel
        applying={applying}
        error={actionError}
        forecastVersion={forecastVersion}
        loading={previewLoading}
        onApply={(rows) => requestSingleApply(rows)}
        onForecastVersionChange={(value) => {
          handleVersionChange(value);
          setPreview(null);
          setPreviewMeta(null);
          setActionError(null);
          setLastApplyResult(null);
        }}
        onRefresh={() => void handlePreview()}
        positionLabel={positionLabel}
        preview={preview}
        readOnly={readOnly}
      />

      {refreshStatus && refreshStatus.positions_changed > 0 ? (
        <div className="inline-alert inline-alert--warn payout-refresh-needed" role="status">
          <div>
            <strong>Прогноз выплат требует обновления.</strong> {refreshStatus.positions_changed}{" "}
            позиции изменились локально; T-Invest ещё не перечитан.
          </div>
          <Button
            disabled={batchLoading || applying || loadingContext}
            onClick={() =>
              void handleBatchPreview(refreshStatus.items.map((item) => item.position_snapshot_id))
            }
            type="button"
          >
            {batchLoading ? "Запрашиваем…" : "Проверить изменённые"}
          </Button>
        </div>
      ) : null}

      <Panel label="Синхронизация" title="Проверка позиций T-Invest">
        <div className="stack-8">
          <p className="muted">
            Проверка читает provider events только после явного действия. Apply остаётся отдельным
            выбором внутри каждой позиции после подтверждения.
          </p>
          <div className="toolbar">
            <Button
              disabled={batchLoading || applying || loadingContext || positions.length === 0}
              onClick={() => void handleBatchPreview()}
              type="button"
              variant="primary"
            >
              {batchLoading ? "Запрашиваем…" : "Проверить все позиции T-Invest"}
            </Button>
          </div>
        </div>
        {batchPreview ? (
          <div className="stack-18 payout-batch-results">
            <TInvestBatchSummary preview={batchPreview} />
            {batchPreview.items.map((item) => {
              const itemLabel = positionLabelFor(item.account_id, item.instrument_id);
              const previewValue = item.preview;
              return (
                <div className="payout-batch-results__group" key={item.position_snapshot_id}>
                  <div className="payout-batch-results__heading">
                    <strong>{itemLabel}</strong>
                    <TInvestBatchItemStatus item={item} />
                    <span className="muted tiny">
                      PositionSnapshot #{item.position_snapshot_id}
                    </span>
                  </div>
                  {previewValue ? (
                    <PayoutPreviewPanel
                      applying={applying}
                      error={null}
                      forecastVersion={version}
                      loading={previewLoading}
                      onApply={(rows) => requestBatchApply(previewValue, rows)}
                      onForecastVersionChange={() => undefined}
                      onRefresh={() => void handleBatchPositionRefresh(item.position_snapshot_id)}
                      positionLabel={itemLabel}
                      preview={previewValue}
                      readOnly={readOnly}
                    />
                  ) : (
                    <div
                      className={`inline-alert ${
                        item.status === "error" ? "inline-alert--warn" : "inline-alert--info"
                      }`}
                      role="status"
                    >
                      <TInvestBatchItemStatus item={item} />{" "}
                      {item.message ?? "Для позиции нет доступного preview."}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        ) : null}
      </Panel>

      <Panel
        action={<Badge>12 месяцев · manual + T-Invest</Badge>}
        label="Прогноз"
        title="Объединённый календарь выплат"
      >
        {loadingContext ? (
          <LoadingState description="Загружаем локальный календарь…" inline />
        ) : (
          <section
            aria-label="Календарь выплат: горизонтальная прокрутка таблицы"
            className={styles.scroll}
          >
            <PayoutPaymentsCalendar months={calendar} />
          </section>
        )}
      </Panel>

      <ConfirmDialog
        busy={applying}
        cancelLabel="Отмена"
        confirmLabel={`Применить (${pendingApply?.rows.length ?? 0})`}
        description={
          pendingApply
            ? `Применить ${pendingApply.rows.length} прогнозных событий T-Invest в месяц #${pendingApply.previewMonthId} (версия «${pendingApply.previewVersion}»)? Календарь будет перечитан перед подтверждением.`
            : ""
        }
        onCancel={() => {
          if (!applying) setPendingApply(null);
        }}
        onConfirm={() => void confirmPendingApply()}
        open={pendingApply !== null}
        title="Применить прогнозные выплаты?"
      />
    </div>
  );
}

export default function UiV2PayoutForecastPage() {
  const [params] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  const months = useQuery({
    queryKey: queryKeys.months,
    queryFn: ({ signal }) => listMonths(signal),
  });
  const selection = resolveMonthSelection(params.getAll("month"), months.data ?? []);
  const month = isQueryReady(months) && selection.kind === "selected" ? selection.month : null;
  const close = parseMonthlyCloseReturnContext(params);
  const returnPath = close && close.monthId === month?.id ? monthlyCloseReturnPath(close) : null;
  const monthOptions = useMemo(() => {
    const rows = months.data ?? [];
    const fallback = newestMonth(rows);
    return { rows, fallback };
  }, [months.data]);

  return (
    <UiV2DataFrame
      active="payouts"
      title="Выплаты"
      subtitle="Календарь ожидаемых выплат и явное применение прогнозных событий T-Invest."
      monthId={month?.id}
      v1ReturnPath="/payouts"
    >
      <div className={styles.context}>
        <label htmlFor="payout-forecast-month">Отчётный месяц</label>
        <select
          id="payout-forecast-month"
          value={month?.id ?? ""}
          onChange={(event) =>
            navigate(
              `${location.pathname}?${withSelectedReturnMonth(params, Number(event.target.value))}${location.hash}`,
            )
          }
        >
          <option value="" disabled>
            Выбери месяц
          </option>
          {(months.data ?? []).map((row) => (
            <option key={row.id} value={row.id}>
              {formatMonth(row.year, row.month)}
            </option>
          ))}
        </select>
        {returnPath ? <Link to={returnPath}>Вернуться к закрытию</Link> : null}
        {!returnPath && close ? (
          <span className="muted tiny" role="status">
            Контекст закрытия относится к другому месяцу и скрыт.
          </span>
        ) : null}
      </div>
      {months.isError ? (
        <UiV2Notice title="Не удалось загрузить месяцы" retry={() => void months.refetch()}>
          Попробуй перечитать список.
        </UiV2Notice>
      ) : !isQueryReady(months) ? (
        <UiV2Loading label="Загружаем месяцы…" />
      ) : !month ? (
        <UiV2Notice title="Месяц не выбран">
          Явный месяц отсутствует или некорректен. Выбери доступный месяц. Импорт выписки и ручные
          выплаты остаются в своих разделах (#562/#567) и здесь не выполняются.
          {monthOptions.fallback
            ? ` Последний доступный: ${formatMonth(monthOptions.fallback.year, monthOptions.fallback.month)}.`
            : ""}
        </UiV2Notice>
      ) : (
        <>
          <DataMonthContext month={month} automatic={false} />
          <p className="muted">
            Импорт фактической выписки (#567) и ручной CRUD (#562) здесь недоступны. Этот инструмент
            показывает календарь и применяет только поддержанные прогнозные события после явного
            подтверждения.
          </p>
          <PayoutForecastTool
            key={`${month.id}:${location.search}`}
            monthId={month.id}
            close={close && close.monthId === month.id ? close : null}
          />
          <p>
            <Link
              to={
                close && close.monthId === month.id
                  ? withMonthlyCloseReturn(
                      `/v2/data/months/${month.id}?section=payouts`,
                      close.monthId,
                      close.step,
                      close.origin,
                    )
                  : `/v2/data/months/${month.id}?section=payouts${location.hash}`
              }
            >
              Ручные выплаты месяца (#562) →
            </Link>
          </p>
        </>
      )}
    </UiV2DataFrame>
  );
}
