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
import type { AlfaStatementTransientOutcome } from "../components/month-close/statementOutcome";
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
import { UiV2StatementImportSection } from "./UiV2StatementImportSection";
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

const IDENTITY_MISMATCH_MESSAGE =
  "Preview не соответствует запрошенному месяцу, версии и позиции. Получи свежий preview.";

const UNCONFIRMED_READBACK_MESSAGE =
  "Применённые выплаты не подтверждены повторной загрузкой. Успех не показан.";

type PendingApply = {
  payload: PayoutContextRequest;
  rows: PayoutApplySelection[];
  previewMonthId: number;
  previewVersion: string;
  batchPreviewId: number | null;
};

function isExactSinglePreview(
  value: PayoutPreview,
  monthId: number,
  payload: PayoutContextRequest,
): boolean {
  return (
    value.reporting_month_id === monthId &&
    value.account_id === payload.account_id &&
    value.instrument_id === payload.instrument_id &&
    value.position_snapshot_id === payload.position_snapshot_id
  );
}

function isConsistentBatchItem(
  item: PayoutBatchPreview["items"][number],
  monthId: number,
  positions: PositionSnapshot[],
  requestedIds?: number[],
): boolean {
  if (requestedIds && !requestedIds.includes(item.position_snapshot_id)) return false;
  const position = positions.find((row) => row.id === item.position_snapshot_id);
  if (!position || position.reporting_month_id !== monthId) return false;
  if (position.account_id !== item.account_id || position.instrument_id !== item.instrument_id)
    return false;
  if (item.preview) {
    if (
      !isExactSinglePreview(item.preview, monthId, {
        account_id: item.account_id,
        instrument_id: item.instrument_id,
        position_snapshot_id: item.position_snapshot_id,
        forecast_version: "",
      })
    )
      return false;
  }
  return true;
}

function isExactBatchPreview(
  value: PayoutBatchPreview,
  monthId: number,
  version: string,
  positions: PositionSnapshot[],
  requestedIds?: number[],
): boolean {
  if (value.reporting_month_id !== monthId || value.forecast_version !== version) return false;
  return value.items.every((item) => isConsistentBatchItem(item, monthId, positions, requestedIds));
}

/**
 * Authoritative calendar proof for one applied payout. The canonical merged
 * calendar may represent a persisted payout either as a provider row or,
 * when reconciliation says count_manual (or counting is unresolved), as a
 * manual row carrying the applied identity in linked_provider_payout_id.
 * When the apply result claims an expected/manual reconciliation identity,
 * the same manual row must prove both the manual source_id and the link.
 */
function isAppliedPayoutRepresented(
  item: PayoutApplyResult["items"][number],
  calendar: PayoutCalendarMonth[],
): boolean {
  const rows = calendar.flatMap((entry) => entry.items);
  if (rows.some((row) => row.source_kind === "provider" && row.source_id === item.payout_id)) {
    return true;
  }
  const linked = rows.filter(
    (row) => row.source_kind === "manual" && row.linked_provider_payout_id === item.payout_id,
  );
  if (linked.length === 0) return false;
  if (item.expected_cash_flow_id == null) return true;
  return linked.some((row) => row.source_id === item.expected_cash_flow_id);
}

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
  // B4: explicit context revision for the whole apply + readback lifetime.
  // Any position/version edit retires an in-flight completion.
  const contextRevision = useRef(0);

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
      contextRevision.current += 1;
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
      if (!isExactSinglePreview(value, monthId, payload)) {
        setPreview(null);
        setPreviewMeta(null);
        setActionError(IDENTITY_MISMATCH_MESSAGE);
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
    // Capture the current position identities for exact batch validation.
    const positionsAtRequest = positions;
    setBatchLoading(true);
    setActionError(null);
    setLastApplyResult(null);
    try {
      const value = await previewPayoutsBatch(monthId, version, positionSnapshotIds);
      if (!alive.current || token !== applyGeneration.current) return;
      if (!isExactBatchPreview(value, monthId, version, positionsAtRequest, positionSnapshotIds)) {
        setBatchPreview(null);
        setBatchMeta(null);
        setActionError(IDENTITY_MISMATCH_MESSAGE);
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
    const requested: PayoutContextRequest = {
      account_id: position.account_id,
      instrument_id: position.instrument_id,
      position_snapshot_id: position.id,
      forecast_version: version,
    };
    const token = ++applyGeneration.current;
    setPreviewLoading(true);
    setActionError(null);
    setLastApplyResult(null);
    try {
      const value = await previewPayouts(monthId, requested);
      if (!alive.current || token !== applyGeneration.current) return;
      // A refreshed item must prove its own identity and can only replace
      // the batch item with the same PositionSnapshot id.
      if (!isExactSinglePreview(value, monthId, requested)) {
        setActionError(IDENTITY_MISMATCH_MESSAGE);
        return;
      }
      setBatchPreview((current) =>
        current
          ? {
              ...current,
              items: current.items.map((item) =>
                item.position_snapshot_id === positionSnapshotId &&
                item.account_id === requested.account_id &&
                item.instrument_id === requested.instrument_id
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
      !isExactSinglePreview(preview, monthId, payload)
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
    // B3: a pending single apply must still match the currently selected
    // position/account/instrument. Batch applies stay independent of the
    // single-position selector.
    if (pending.batchPreviewId === null) {
      const current = contextPayload();
      if (
        !current ||
        current.account_id !== pending.payload.account_id ||
        current.instrument_id !== pending.payload.instrument_id ||
        current.position_snapshot_id !== pending.payload.position_snapshot_id
      ) {
        setPendingApply(null);
        setPreview(null);
        setPreviewMeta(null);
        setActionError(STALE_APPLY_MESSAGE);
        return;
      }
    }
    const token = ++applyGeneration.current;
    setApplying(true);
    setActionError(null);
    setLastApplyResult(null);
    // B4: freeze the apply context. Any position/version edit during the
    // POST + authoritative readback retires this completion.
    const frozenRevision = contextRevision.current;
    const frozenMonthId = monthId;
    const frozenVersion = version;
    const frozenPayload = { ...pending.payload };
    try {
      const result = await applyPayouts(monthId, { ...pending.payload, rows: pending.rows });
      if (!alive.current || token !== applyGeneration.current) return;
      if (frozenRevision !== contextRevision.current) return;
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
      // B2: the backend identity is not enough. A successful apply must prove
      // the applied rows and readiness before any success is published.
      // B5: the response must confirm the exact submitted set.
      if (
        result.items.length !== result.selected_count ||
        result.selected_count !== pending.rows.length
      ) {
        setPreview(null);
        setPreviewMeta(null);
        setBatchPreview(null);
        setBatchMeta(null);
        setLastApplyResult(null);
        setActionError(UNCONFIRMED_READBACK_MESSAGE);
        return;
      }
      // Authoritative readback for the same exact month/version before success.
      try {
        const [rereadMonth, rereadCalendar, rereadRefresh, rereadExpected, rereadReadiness] =
          await Promise.all([
            getMonth(frozenMonthId),
            listPayoutCalendar(frozenMonthId, frozenVersion),
            getPayoutRefreshStatus(frozenMonthId),
            listExpectedFlows(frozenMonthId, frozenVersion),
            getCloseReadiness(frozenMonthId),
          ]);
        if (
          !alive.current ||
          token !== applyGeneration.current ||
          frozenRevision !== contextRevision.current
        )
          return;
        // B4: the frozen context must still be current before publishing.
        if (frozenMonthId !== monthId || frozenVersion !== version) {
          setPreview(null);
          setPreviewMeta(null);
          setBatchPreview(null);
          setBatchMeta(null);
          setLastApplyResult(null);
          setActionError(STALE_APPLY_MESSAGE);
          return;
        }
        if (pending.batchPreviewId === null) {
          const current = contextPayload();
          if (
            !current ||
            current.account_id !== frozenPayload.account_id ||
            current.instrument_id !== frozenPayload.instrument_id ||
            current.position_snapshot_id !== frozenPayload.position_snapshot_id
          ) {
            setPreview(null);
            setPreviewMeta(null);
            setBatchPreview(null);
            setBatchMeta(null);
            setLastApplyResult(null);
            setActionError(STALE_APPLY_MESSAGE);
            return;
          }
        }
        const readinessMatchesLifecycle =
          rereadReadiness.year === rereadMonth.year &&
          rereadReadiness.month === rereadMonth.month &&
          rereadReadiness.snapshot_date === rereadMonth.snapshot_date &&
          rereadReadiness.status === rereadMonth.status;
        if (
          rereadMonth.id !== frozenMonthId ||
          rereadRefresh.reporting_month_id !== frozenMonthId ||
          rereadExpected.some(
            (row) =>
              row.reporting_month_id !== frozenMonthId || row.forecast_version !== frozenVersion,
          ) ||
          !readinessMatchesLifecycle ||
          !result.items.every((item) => isAppliedPayoutRepresented(item, rereadCalendar))
        ) {
          setPreview(null);
          setPreviewMeta(null);
          setBatchPreview(null);
          setBatchMeta(null);
          setLastApplyResult(null);
          setActionError(UNCONFIRMED_READBACK_MESSAGE);
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
        if (
          !alive.current ||
          token !== applyGeneration.current ||
          frozenRevision !== contextRevision.current
        )
          return;
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
              disabled={loadingContext || applying}
              id="payout-forecast-position"
              onChange={(event) => {
                setSelectedPositionId(event.target.value);
                contextRevision.current += 1;
                setPreview(null);
                setPreviewMeta(null);
                // B3: a pending single confirm must not survive a position
                // change. Batch confirms stay independent of this selector.
                setPendingApply((current) =>
                  current && current.batchPreviewId === null ? null : current,
                );
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
        versionDisabled={applying}
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
                      versionDisabled={applying}
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
  const [statementOutcomeByMonth, setStatementOutcomeByMonth] = useState<{
    monthId: number;
    outcome: AlfaStatementTransientOutcome;
  } | null>(null);
  const [statementWriteActive, setStatementWriteActive] = useState(false);
  const closeStepActive =
    close !== null && close.step === "actual_payouts" && close.monthId === month?.id;
  const monthOptions = useMemo(() => {
    const rows = months.data ?? [];
    const fallback = newestMonth(rows);
    return { rows, fallback };
  }, [months.data]);

  useEffect(() => {
    if (!month || location.hash !== "#statement-import") return;
    const target = document.getElementById("statement-import");
    if (target && typeof target.scrollIntoView === "function") {
      target.scrollIntoView({ block: "start" });
    }
  }, [location.hash, month]);

  // The transient close outcome belongs to one explicit month: an older month
  // must never publish it into the current month context.
  const statementOutcome =
    statementOutcomeByMonth && statementOutcomeByMonth.monthId === month?.id
      ? statementOutcomeByMonth.outcome
      : null;
  const handleStatementOutcome = useCallback(
    (next: AlfaStatementTransientOutcome | null) => {
      if (!closeStepActive || month === null) return;
      setStatementOutcomeByMonth(next ? { monthId: month.id, outcome: next } : null);
    },
    [closeStepActive, month],
  );

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
          disabled={statementWriteActive}
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
          <div id="statement-import">
            <UiV2StatementImportSection
              closeStepActive={closeStepActive}
              key={month.id}
              month={month}
              onApplyingChange={setStatementWriteActive}
              onOutcome={handleStatementOutcome}
              outcome={statementOutcome}
              returnPath={returnPath}
            />
          </div>
          <p className="muted">
            Импорт фактической выписки (#567) — секция выше; ручные выплаты (#562) остаются в
            редакторе месяца. Календарь ниже показывает ожидания и применяет только поддержанные
            прогнозные события после явного подтверждения.
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
