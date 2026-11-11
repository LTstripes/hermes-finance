import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router";
import { listAccounts } from "../api/accounts";
import { formatApiError } from "../api/client";
import { listExpectedFlows } from "../api/expectedFlows";
import { getInstrumentMapping } from "../api/instrumentMappings";
import { listInstruments } from "../api/instruments";
import { getCloseReadiness, getMonth, listMonths } from "../api/months";
import {
  applyPayouts,
  getPayoutRefreshStatus,
  listPayoutCalendar,
  type PayoutApplyResult,
  type PayoutApplySelection,
  type PayoutBatchPreview,
  type PayoutCalendarMonth,
  type PayoutContextRequest,
  type PayoutPreview,
  type PayoutRefreshStatus,
  previewPayouts,
  previewPayoutsBatch,
} from "../api/payouts";
import { listPositions } from "../api/positions";
import type {
  Account,
  ExpectedFlow,
  Instrument,
  InstrumentMarketMapping,
  MoneyValue,
  PositionSnapshot,
  ReportingMonth,
} from "../api/types";
import {
  type MonthlyCloseReturnContext,
  monthlyCloseReturnPath,
  parseMonthlyCloseReturnContext,
  withMonthlyCloseReturn,
  withSelectedReturnMonth,
} from "../components/month-close/navigation";
import type { AlfaStatementTransientOutcome } from "../components/month-close/statementOutcome";
import {
  TInvestBatchItemStatus,
  TInvestBatchSummary,
  TInvestPayoutApplySummary,
} from "../components/month-close/TInvestStepSummary";
import { shortInstrumentName } from "./instrumentName";
import { wholeMoneyText } from "./wholeMoney";
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
import { formatDate, formatMoney, formatMonth, formatQuantity } from "../lib/format";
import { INSTRUMENT_TYPE_LABELS, labelOf, MONTH_STATUS_LABELS } from "../lib/labels";
import { reasonCopy } from "../lib/reasonCopy";
import { queryKeys } from "../queryClient";
import { latestClosedMonth, resolveMonthSelection } from "./monthSelection";
import {
  executePayoutSelection,
  type FrozenPayoutGroup,
  isPayoutExecutionActive,
  type PayoutExecutionResult,
} from "./payoutExecution";
import { DataMonthContext, UiV2DataFrame } from "./UiV2DataShell";
import styles from "./UiV2PayoutForecast.module.css";
import { isQueryReady, UiV2Loading, UiV2Notice } from "./UiV2StateBlocks";
import { UiV2StatementImportSection } from "./UiV2StatementImportSection";

const PAYOUT_OUTCOME_LABELS: Record<PayoutExecutionResult["outcome"], string> = {
  CONFIRMED: "Сохранение подтверждено",
  APPLIED_UNVERIFIED: "Сохранение не подтверждено",
  REJECTED_NO_WRITE: "Отклонено без сохранения",
  STALE_NO_WRITE: "Данные устарели, запрос не отправлен",
  UNKNOWN: "Результат неизвестен",
  NOT_SENT: "Запрос не отправлен",
  ALREADY_PRESENT: "Уже сохранено",
};

const STALE_APPLY_MESSAGE = "Параметры изменились. Обнови предпросмотр.";

const IDENTITY_MISMATCH_MESSAGE = "Предпросмотр не соответствует выбранной позиции. Обнови его.";

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
    value.position_snapshot_id === payload.position_snapshot_id &&
    value.rows.every(
      (row) =>
        row.reporting_month_id === monthId &&
        row.account_id === payload.account_id &&
        row.instrument_id === payload.instrument_id &&
        row.position_snapshot_id === payload.position_snapshot_id &&
        row.provider === value.provider &&
        row.instrument_uid === value.instrument_uid,
    )
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
  if (new Set(value.items.map((item) => item.position_snapshot_id)).size !== value.items.length)
    return false;
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
  group: FrozenPayoutGroup,
  expected: ExpectedFlow[],
): boolean {
  const payload = group.payload;
  const reviewed = group.reviewedRows.find(
    (row) =>
      row.provider === item.provider &&
      row.instrument_uid === item.instrument_uid &&
      row.event_kind === item.event_kind &&
      row.identity_key === item.identity_key,
  );
  const counting = item.counting_decision ?? reviewed?.reconciliation?.counting_decision;
  const manualId = item.expected_cash_flow_id ?? reviewed?.reconciliation?.expected_cash_flow_id;
  const rows = calendar
    .flatMap((entry) => entry.items)
    .filter(
      (row) =>
        row.account_id === payload.account_id &&
        row.instrument_id === payload.instrument_id &&
        row.flow_type === item.event_kind,
    );
  const provider = rows.find(
    (row) =>
      row.source_kind === "provider" &&
      row.source_id === item.payout_id &&
      row.provider === item.provider &&
      row.provider_instrument_uid === item.instrument_uid &&
      row.provider_identity_key === item.identity_key &&
      row.provider_lifecycle === item.lifecycle &&
      row.expected_date === reviewed?.payment_date &&
      row.expected_net_amount.amount === item.total_amount.amount &&
      row.expected_net_amount.currency === item.total_amount.currency,
  );
  if (manualId == null)
    return (
      !!provider &&
      provider.reconciliation_id === null &&
      provider.counting_decision === null &&
      provider.linked_manual_id === null
    );
  const manual = expected.find(
    (row) =>
      row.id === manualId &&
      row.account_id === payload.account_id &&
      row.instrument_id === payload.instrument_id &&
      row.flow_type === item.event_kind,
  );
  if (!manual) return false;
  const manualProof = rows.some(
    (row) =>
      row.source_kind === "manual" &&
      row.source_id === manualId &&
      row.linked_provider_payout_id === item.payout_id &&
      row.reconciliation_id === item.reconciliation_id &&
      row.counting_decision === counting &&
      row.expected_date === manual.expected_date &&
      row.expected_net_amount.amount === manual.expected_net_amount.amount &&
      row.expected_net_amount.currency === manual.expected_net_amount.currency,
  );
  const providerProof =
    !!provider &&
    provider.reconciliation_id === item.reconciliation_id &&
    provider.counting_decision === counting &&
    provider.linked_manual_id === manualId;
  if (counting === "count_manual") return manualProof;
  if (counting === "count_provider") return providerProof;
  return counting === "keep_both" && providerProof && manualProof;
}

function payoutSubtotal(rows: PayoutPreview["rows"], principal: boolean): string {
  const relevant = rows.filter((row) => (row.event_kind === "redemption") === principal);
  const totals = new Map<string, bigint>();
  for (const row of relevant) {
    const value = row.total_amount;
    if (!value || !/^\d+\.\d{2}$/.test(value.amount)) return "не определён";
    const minor = BigInt(value.amount.replace(".", ""));
    totals.set(value.currency, (totals.get(value.currency) ?? 0n) + minor);
  }
  if (!relevant.length) return "нет событий этого типа";
  return [...totals]
    .map(
      ([currency, minor]) => `${minor / 100n}.${String(minor % 100n).padStart(2, "0")} ${currency}`,
    )
    .join("; ");
}

// Aggregate authoritative calendar buckets exactly, keeping currencies separate.
function calendarTotal(values: MoneyValue[]): string {
  const totals = new Map<string, bigint>();
  for (const value of values) {
    if (!/^-?\d+\.\d{2}$/.test(value.amount)) return "Не определён";
    totals.set(
      value.currency,
      (totals.get(value.currency) ?? 0n) + BigInt(value.amount.replace(".", "")),
    );
  }
  if (!totals.size) return formatMoney("0.00");
  return [...totals]
    .map(([currency, minor]) => {
      const absolute = minor < 0n ? -minor : minor;
      const amount = `${minor < 0n ? "-" : ""}${absolute / 100n}.${String(absolute % 100n).padStart(2, "0")}`;
      return formatMoney(amount, { currency: currency === "RUB" ? "₽" : currency });
    })
    .join(" · ");
}

function payoutKindLabel(kind: string): string {
  const labels: Record<string, string> = {
    coupon: "Купон",
    dividend: "Дивиденд",
    redemption: "Возврат номинала",
    interest: "Проценты",
    other: "Другая выплата",
  };
  return labels[kind] ?? "Другая выплата";
}

const PAYOUT_ATTENTION: Record<string, string> = {
  revised: "Изменена: проверь детали",
  possible_manual_duplicate: "Возможный ручной дубль: укажи способ учёта и ручную запись",
  cancelled_by_provider: "Отменена провайдером",
  missing_from_provider: "Отсутствует в ответе провайдера",
  tentative: "Предварительное событие",
  ambiguous_identity: "Не удалось однозначно определить событие",
  unsupported: "Не поддерживается",
  unavailable: "Недоступно",
  error: "Ошибка",
  position_gone: "Позиция отсутствует",
};

function PayoutForecastTool({
  monthId,
  close,
  onApplyingChange,
}: {
  onApplyingChange: (active: boolean) => void;
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
  const [mappings, setMappings] = useState<InstrumentMarketMapping[]>([]);
  const [mappingUnavailable, setMappingUnavailable] = useState(false);
  const [diagnosticsPending, setDiagnosticsPending] = useState(true);
  const [savedConflict, setSavedConflict] = useState<boolean | null>(null);
  const [calendarLoaded, setCalendarLoaded] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);
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
  const [selectedGroups, setSelectedGroups] = useState<Record<number, PayoutApplySelection[]>>({});
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [selectionCommands, setSelectionCommands] = useState<
    Record<number, { revision: number; action: "eligible" | "clear" }>
  >({});
  const [pendingBulk, setPendingBulk] = useState<FrozenPayoutGroup[] | null>(null);
  const [executionResults, setExecutionResults] = useState<PayoutExecutionResult[]>([]);
  const [activeGroup, setActiveGroup] = useState<number | null>(null);
  const stopRequested = useRef(false);
  const [retiredPreview, setRetiredPreview] = useState(false);
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
      : "Неизвестный инструмент";
    return `${account?.name ?? "Неизвестный счёт"} · ${instrumentText}`;
  }, [accountById, instrumentById, selectedPosition]);

  function positionLabelFor(accountId: number, instrumentId: number): string {
    const account = accountById.get(accountId);
    const instrument = instrumentById.get(instrumentId);
    const instrumentText = instrument
      ? `${instrument.name}${instrument.ticker ? ` (${instrument.ticker})` : ""}`
      : "Неизвестный инструмент";
    return `${instrumentText} · ${account?.name ?? "Неизвестный счёт"}`;
  }

  const readContext = useCallback(async (target: number, targetVersion: string) => {
    const generation = ++readGeneration.current;
    setLoadingContext(true);
    setContextError(null);
    setMonthMismatch(false);
    setMappings([]);
    setMappingUnavailable(false);
    setSavedConflict(null);
    setDiagnosticsPending(true);
    try {
      const [
        freshMonth,
        accountRows,
        instrumentRows,
        positionRows,
        [calendarRead, refreshRead],
        expectedRows,
      ] = await Promise.all([
        getMonth(target),
        listAccounts(),
        listInstruments({ active: true }),
        listPositions(target),
        Promise.allSettled([
          listPayoutCalendar(target, targetVersion),
          getPayoutRefreshStatus(target),
        ]),
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
      setMonth(freshMonth);
      setAccounts(accountRows);
      setInstruments(instrumentRows);
      setPositions(positionRows);
      if (calendarRead.status === "fulfilled") {
        setCalendar(calendarRead.value);
        setCalendarLoaded(true);
      }
      // Date and status must describe the same successful calendar read.
      if (calendarRead.status === "fulfilled") {
        setRefreshStatus(
          refreshRead.status === "fulfilled" && refreshRead.value.reporting_month_id === target
            ? refreshRead.value
            : null,
        );
      }
      if (
        calendarRead.status === "rejected" ||
        refreshRead.status === "rejected" ||
        (refreshRead.status === "fulfilled" && refreshRead.value.reporting_month_id !== target)
      ) {
        setContextError("Не удалось перечитать сохранённый прогноз или его состояние.");
      }
      setExpectedCount(expectedRows.length);
      setSelectedPositionId((current) =>
        positionRows.some((row) => String(row.id) === current)
          ? current
          : positionRows[0]
            ? String(positionRows[0].id)
            : "",
      );
      setLoadingContext(false);
      const mappingInstrumentIds = [
        ...new Set(
          positionRows
            .filter((position) => {
              const instrument = instrumentRows.find((row) => row.id === position.instrument_id);
              return (
                instrument &&
                ["stock", "bond"].includes(instrument.instrument_type) &&
                /^\d+(?:\.\d+)?$/.test(position.quantity) &&
                /[1-9]/.test(position.quantity)
              );
            })
            .map((row) => row.instrument_id),
        ),
      ];
      const mappingReadsPromise = Promise.allSettled(
        mappingInstrumentIds.map(async (id) => {
          const value = await getInstrumentMapping(id);
          if (value.instrument_id !== id) throw new Error("Сопоставление другой бумаги.");
          return value;
        }),
      );
      const [mappingReads, readiness] = await Promise.all([
        mappingReadsPromise,
        getCloseReadiness(target).catch(() => null),
      ]);
      if (!alive.current || generation !== readGeneration.current) return;
      setMappings(mappingReads.flatMap((row) => (row.status === "fulfilled" ? [row.value] : [])));
      setMappingUnavailable(mappingReads.some((row) => row.status === "rejected"));
      // Local-only readback: no provider request happens here.
      const readinessMatches =
        readiness &&
        readiness.year === freshMonth.year &&
        readiness.month === freshMonth.month &&
        readiness.status === freshMonth.status &&
        readiness.snapshot_date === freshMonth.snapshot_date;
      setSavedConflict(
        readinessMatches
          ? readiness.items.some((item) => item.code === "unresolved_payout_reconciliation")
          : null,
      );
      setDiagnosticsPending(false);
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
      setPendingBulk(null);
      setPendingApply(null);
      setCalendar([]);
      setCalendarLoaded(false);
      setRefreshStatus(null);
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
    if (!payload || applying || previewLoading || batchLoading || isPayoutExecutionActive()) return;
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
      await readContext(monthId, version);
      if (!alive.current || token !== applyGeneration.current) return;
      setRetiredPreview(false);
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
    if (!version || applying || previewLoading || batchLoading || isPayoutExecutionActive()) return;
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
      await readContext(monthId, version);
      if (!alive.current || token !== applyGeneration.current) return;
      setRetiredPreview(false);
      setSelectedGroups({});
      setExpanded(new Set());
      setSelectionCommands({});
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
    if (!position || applying || previewLoading || batchLoading || isPayoutExecutionActive())
      return;
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
      await readContext(monthId, version);
      if (!alive.current || token !== applyGeneration.current) return;
      setRetiredPreview(false);
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
    if (
      !payload ||
      rows.length === 0 ||
      applying ||
      previewLoading ||
      batchLoading ||
      retiredPreview ||
      isPayoutExecutionActive()
    )
      return;
    if (readOnly) {
      setActionError(reasonCopy("closed_month", { surface: "payoutApply" }).message);
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
    if (
      previewValue.position_snapshot_id === null ||
      applying ||
      previewLoading ||
      batchLoading ||
      retiredPreview ||
      isPayoutExecutionActive()
    )
      return;
    if (readOnly) {
      setActionError(reasonCopy("closed_month", { surface: "payoutApply" }).message);
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

  function selectionCommand(ids: number[], action: "eligible" | "clear") {
    setSelectionCommands((current) => {
      const next = { ...current };
      for (const id of ids) next[id] = { revision: (current[id]?.revision ?? 0) + 1, action };
      return next;
    });
  }

  function requestBulkApply() {
    if (
      applying ||
      previewLoading ||
      batchLoading ||
      retiredPreview ||
      readOnly ||
      isPayoutExecutionActive() ||
      !batchPreview ||
      batchMeta?.monthId !== monthId ||
      batchMeta.version !== version
    )
      return;
    const groups = batchPreview.items.flatMap((item) => {
      const rows = selectedGroups[item.position_snapshot_id] ?? [];
      if (!item.preview || !rows.length) return [];
      return [
        {
          payload: {
            account_id: item.account_id,
            instrument_id: item.instrument_id,
            position_snapshot_id: item.position_snapshot_id,
            forecast_version: version,
          },
          rows,
          quantity: item.preview.quantity,
          label: positionLabelFor(item.account_id, item.instrument_id),
          reviewedRows: item.preview.rows,
        },
      ];
    });
    if (groups.length) setPendingBulk(structuredClone(groups));
  }

  async function runSelection(groups: FrozenPayoutGroup[], single: boolean) {
    if (
      applying ||
      previewLoading ||
      batchLoading ||
      isPayoutExecutionActive() ||
      retiredPreview ||
      readOnly
    )
      return;
    // Fence any preview activation queued before the busy state was painted.
    // Its late response must never rearm a consumed/UNKNOWN selection.
    applyGeneration.current += 1;
    setPreviewLoading(false);
    setBatchLoading(false);
    const frozenRevision = contextRevision.current;
    const frozenMonthId = monthId;
    const frozenVersion = version;
    const current = () =>
      alive.current &&
      contextRevision.current === frozenRevision &&
      versionRef.current === frozenVersion;
    stopRequested.current = false;
    setApplying(true);
    onApplyingChange(true);
    setRetiredPreview(true);
    setPendingApply(null);
    setPendingBulk(null);
    setActionError(null);
    setLastApplyResult(null);
    try {
      const results = await executePayoutSelection(groups, {
        current,
        stop: () => stopRequested.current,
        progress: (results, active) => {
          if (!alive.current) return;
          setExecutionResults(results);
          setActiveGroup(active);
        },
        before: async (group) => {
          const [freshMonth, freshPositions] = await Promise.all([
            getMonth(frozenMonthId),
            listPositions(frozenMonthId),
          ]);
          const position = freshPositions.find(
            (row) => row.id === group.payload.position_snapshot_id,
          );
          return (
            freshMonth.id === frozenMonthId &&
            freshMonth.status !== "closed" &&
            freshMonth.year === month?.year &&
            freshMonth.month === month?.month &&
            freshMonth.snapshot_date === month?.snapshot_date &&
            freshPositions.length === positions.length &&
            positions.every((old) =>
              freshPositions.some(
                (value) =>
                  value.id === old.id &&
                  value.reporting_month_id === old.reporting_month_id &&
                  value.account_id === old.account_id &&
                  value.instrument_id === old.instrument_id &&
                  value.quantity === old.quantity,
              ),
            ) &&
            !!position &&
            position.reporting_month_id === frozenMonthId &&
            position.account_id === group.payload.account_id &&
            position.instrument_id === group.payload.instrument_id &&
            position.quantity === group.quantity
          );
        },
        apply: (group) => applyPayouts(frozenMonthId, { ...group.payload, rows: group.rows }),
        verify: async (group, result) => {
          const [rereadMonth, rereadCalendar, rereadRefresh, rereadExpected, readiness] =
            await Promise.all([
              getMonth(frozenMonthId),
              listPayoutCalendar(frozenMonthId, frozenVersion),
              getPayoutRefreshStatus(frozenMonthId),
              listExpectedFlows(frozenMonthId, frozenVersion),
              getCloseReadiness(frozenMonthId),
            ]);
          if (
            !current() ||
            rereadMonth.id !== frozenMonthId ||
            rereadMonth.status === "closed" ||
            rereadMonth.year !== month?.year ||
            rereadMonth.month !== month?.month ||
            rereadMonth.snapshot_date !== month?.snapshot_date ||
            rereadRefresh.reporting_month_id !== frozenMonthId ||
            rereadExpected.some(
              (row) =>
                row.reporting_month_id !== frozenMonthId || row.forecast_version !== frozenVersion,
            ) ||
            readiness.year !== rereadMonth.year ||
            readiness.month !== rereadMonth.month ||
            readiness.snapshot_date !== rereadMonth.snapshot_date ||
            readiness.status !== rereadMonth.status ||
            !result.items.every((item) =>
              isAppliedPayoutRepresented(item, rereadCalendar, group, rereadExpected),
            )
          )
            return false;
          setMonth(rereadMonth);
          setSavedConflict(
            readiness.items.some((item) => item.code === "unresolved_payout_reconciliation"),
          );
          setCalendar(rereadCalendar);
          setRefreshStatus(rereadRefresh);
          setExpectedCount(rereadExpected.length);
          await client.invalidateQueries({ refetchType: "none" });
          if (!current()) return false;
          if (single) setLastApplyResult(result);
          return true;
        },
      });
      if (!current() || results === null) return;
      // Every submitted attempt consumes this preview, including a lost reply.
      // Another mutation requires a fresh explicit preview and confirmation.
      setRetiredPreview(true);
      setSelectedGroups({});
      const unresolved = results.find((row) => row.outcome !== "CONFIRMED");
      if (unresolved)
        setActionError(
          unresolved.outcome === "APPLIED_UNVERIFIED"
            ? UNCONFIRMED_READBACK_MESSAGE
            : unresolved.outcome === "STALE_NO_WRITE"
              ? reasonCopy("preview_changed", { surface: "payoutApply" }).message
              : unresolved.message,
        );
      setPreview(null);
      setPreviewMeta(null);
      setBatchPreview(null);
      setBatchMeta(null);
    } finally {
      onApplyingChange(false);
      if (alive.current) {
        setApplying(false);
        setActiveGroup(null);
      }
    }
  }

  async function confirmPendingApply() {
    const pending = pendingApply;
    if (!pending || pending.previewMonthId !== monthId || pending.previewVersion !== version)
      return;
    if (
      pending.batchPreviewId === null &&
      contextPayload()?.position_snapshot_id !== pending.payload.position_snapshot_id
    )
      return;
    const value =
      pending.batchPreviewId === null
        ? preview
        : batchPreview?.items.find((row) => row.position_snapshot_id === pending.batchPreviewId)
            ?.preview;
    if (!value) return;
    await runSelection(
      [
        {
          payload: { ...pending.payload },
          rows: structuredClone(pending.rows),
          quantity: value.quantity,
          label: positionLabelFor(pending.payload.account_id, pending.payload.instrument_id),
          reviewedRows: value.rows,
        },
      ],
      true,
    );
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

  function reloadCalendar() {
    contextRevision.current += 1;
    setPendingApply(null);
    setPendingBulk(null);
    setPreview(null);
    setPreviewMeta(null);
    setBatchPreview(null);
    setBatchMeta(null);
    setSelectedGroups({});
    void readContext(monthId, version);
  }

  // Geometry only. Labels retain the authoritative calendar money.
  const chartMax = Math.max(0, ...calendar.map((entry) => Number(entry.total_net.amount) || 0));
  const automatic = refreshStatus?.automatic_refresh;
  const forecastDate = refreshStatus?.forecast_as_of;
  const dateLabel = forecastDate
    ? `Последний прогноз: ${formatDate(forecastDate)}.`
    : "Дата последнего прогноза неизвестна.";
  const attention: string[] = [];
  if (contextError || automatic?.status === "error") {
    attention.push(
      `Обновление недоступно. ${calendarLoaded ? "Показан прежний прогноз." : "Сохранённый прогноз не загружен."} ${dateLabel}`,
    );
  } else if (automatic?.status === "pending" || automatic?.status === "running") {
    attention.push("Прогноз обновляется. Пока показаны сохранённые выплаты.");
  } else if (automatic?.status === "partial" || automatic?.status === "needs_review") {
    attention.push("Прогноз неполный: часть бумаг требует проверки.");
  }
  if (automatic?.reason_codes.includes("draft_changed")) {
    attention.push("Данные месяца изменились. Прежний прогноз может быть устаревшим.");
  }
  if (
    automatic?.reason_codes.some((code) =>
      [
        "possible_manual_duplicate",
        "ambiguous_identity",
        "saved_provider_identity_changed",
      ].includes(code),
    )
  ) {
    attention.push("Есть конфликт выплат или сопоставления бумаг. Проверь подробности.");
  }
  if (refreshStatus?.positions_changed) {
    attention.push(
      `Изменились позиции: ${refreshStatus.positions_changed}. Сохранённый прогноз требует проверки.`,
    );
  }
  if (savedConflict)
    attention.push("Есть несогласованные выплаты. Проверь способ учёта в подробностях.");
  if (!diagnosticsPending && savedConflict === null)
    attention.push("Не удалось проверить согласованность выплат.");
  if (mappingUnavailable) attention.push("Не удалось проверить сопоставление части бумаг.");
  if (positions.some((position) => !instrumentById.has(position.instrument_id))) {
    attention.push("Часть бумаг не найдена в справочнике. Прогноз может быть неполным.");
  }
  for (const mapping of mappings) {
    if (mapping.state === "mapped" && mapping.identity?.provider === "t_invest") continue;
    const name = instrumentById.get(mapping.instrument_id)?.name ?? "Бумага";
    const problem =
      mapping.state === "unmapped"
        ? "нет сопоставления с T-Invest"
        : mapping.state === "excluded"
          ? "исключена из прогноза"
          : "требуется сопоставление с T-Invest";
    attention.push(`${name}: ${problem}.`);
  }
  if (calendar.some((entry) => entry.actual_attribution_coverage === "unknown")) {
    attention.push("Полнота выплат неизвестна. В итогах показана известная часть.");
  }
  const reviewedPreviews = [
    ...(preview ? [preview] : []),
    ...(batchPreview?.items.flatMap((item) => (item.preview ? [item.preview] : [])) ?? []),
  ];
  for (const value of reviewedPreviews) {
    if (
      value.rows.some((row) =>
        ["possible_manual_duplicate", "ambiguous_identity", "revised"].includes(row.status),
      )
    ) {
      attention.push(
        `${positionLabelFor(value.account_id, value.instrument_id)}: есть конфликт или изменение выплаты. Проверь подробности.`,
      );
    }
  }
  if (batchPreview?.items.some((item) => ["error", "skipped"].includes(item.status))) {
    attention.push("Для части бумаг прогноз недоступен. Проверь подробности.");
  }
  if (actionError) attention.push("Операция не завершена. Проверь подробности.");

  if (loadingContext && !month && !contextError && !monthMismatch) {
    return <LoadingState description="Загружаем локальный календарь…" inline />;
  }
  if (contextError && !month) {
    return (
      <section className={styles.overview} aria-label="Основной прогноз">
        <h2>Прогноз недоступен</h2>
        <p>Не удалось загрузить сохранённые выплаты. Дата последнего прогноза неизвестна.</p>
        <div className="toolbar">
          <Button type="button" disabled={loadingContext} onClick={reloadCalendar}>
            Обновить
          </Button>
          <Button
            type="button"
            aria-expanded={detailsOpen}
            aria-controls="payout-forecast-error"
            onClick={() => setDetailsOpen((value) => !value)}
          >
            Подробности
          </Button>
        </div>
        <div id="payout-forecast-error" hidden={!detailsOpen}>
          {contextError}
        </div>
      </section>
    );
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
      <section aria-label="Основной прогноз" className={styles.overview}>
        <div className={styles.heading}>
          <div>
            <h2>Прогноз на 12 месяцев</h2>
          </div>
          <div className="toolbar">
            <Button
              disabled={applying || loadingContext || previewLoading || batchLoading}
              onClick={reloadCalendar}
              type="button"
              title="Перечитать сохранённый прогноз"
            >
              {loadingContext ? "Обновляем…" : "Обновить"}
            </Button>
            <Button
              type="button"
              aria-expanded={detailsOpen}
              aria-controls="payout-forecast-details"
              onClick={() => setDetailsOpen((value) => !value)}
            >
              Подробности
            </Button>
          </div>
        </div>
        <dl className={styles.totals}>
          <div>
            <dt>Прогноз дохода · купоны и дивиденды</dt>
            <dd>
              ≈{" "}
              {calendarLoaded
                ? calendarTotal(calendar.flatMap((entry) => [entry.coupon, entry.dividend]))
                : "Не определён"}
            </dd>
          </div>
          <div>
            <dt>Возврат номинала · не доход</dt>
            <dd>
              {calendarLoaded
                ? calendarTotal(calendar.map((entry) => entry.redemption))
                : "Не определён"}
            </dd>
          </div>
        </dl>
        <p className="muted tiny">
          Приблизительно · от снимка {formatDate(month.snapshot_date)} · {dateLabel} Личный налог по
          выплатам T-Invest не учтён.
        </p>
        <p className={styles.composition}>
          Купоны{" "}
          {calendarLoaded ? calendarTotal(calendar.map((entry) => entry.coupon)) : "Не определён"}
          {" / "}дивиденды{" "}
          {calendarLoaded ? calendarTotal(calendar.map((entry) => entry.dividend)) : "Не определён"}
          {" / "}возврат номинала (не доход)
        </p>
        {attention.length ? (
          <section className={styles.attention} aria-label="Требует внимания" role="status">
            <h3>Требует внимания</h3>
            <ul>
              {[...new Set(attention)].map((message) => (
                <li key={message}>{message}</li>
              ))}
            </ul>
          </section>
        ) : null}
        {calendarLoaded && calendar.length > 0 ? (
          <>
            <figure className={styles.chart} aria-label="Прогноз выплат по месяцам">
              <figcaption className="muted tiny">
                Весь денежный поток · включая возврат номинала
              </figcaption>
              <div className={styles.bars}>
                {calendar.map((entry) => {
                  const value = Number(entry.total_net.amount);
                  const height =
                    chartMax > 0 && Number.isFinite(value)
                      ? (Math.max(0, value) / chartMax) * 100
                      : 0;
                  return (
                    <div className={styles.barColumn} key={`${entry.year}-${entry.month}`}>
                      <span
                        className={styles.barTrack}
                        title={`${formatMonth(entry.year, entry.month)}: ${wholeMoneyText(entry.total_net)}`}
                      >
                        <span style={{ height: `${height}%` }} />
                      </span>
                      <span>{String(entry.month).padStart(2, "0")}</span>
                    </div>
                  );
                })}
              </div>
            </figure>
            <div className={styles.months}>
              {calendar.map((entry, index) => (
                <details
                  className={styles.month}
                  key={`${entry.year}-${entry.month}`}
                  open={index === 0}
                >
                  <summary>
                    <span>{formatMonth(entry.year, entry.month)}</span>
                    <span className="muted tiny">{entry.items.length} выплат</span>
                    {entry.actual_attribution_coverage === "unknown" ? (
                      <span className="muted tiny">Полнота неизвестна; известная часть</span>
                    ) : null}
                    <strong title={calendarTotal([entry.total_net])}>
                      ≈ {wholeMoneyText(entry.total_net)}
                    </strong>
                  </summary>
                  {entry.items.length ? (
                    <table
                      className={styles.payments}
                      aria-label={`Выплаты ${formatMonth(entry.year, entry.month)}`}
                    >
                      <thead>
                        <tr>
                          <th scope="col">Дата</th>
                          <th scope="col">Бумага / счёт</th>
                          <th scope="col">Вид</th>
                          <th scope="col">Сумма</th>
                        </tr>
                      </thead>
                      <tbody>
                        {[...entry.items]
                          .sort((a, b) => a.expected_date.localeCompare(b.expected_date))
                          .map((item) => {
                            const instrument = instrumentById.get(item.instrument_id);
                            const name = instrument
                              ? shortInstrumentName(instrument)
                              : (item.instrument_name ?? "Бумага не определена");
                            return (
                              <tr key={`${item.source_kind}-${item.source_id}`}>
                                <td>{formatDate(item.expected_date)}</td>
                                <td>
                                  {instrument?.isin ? (
                                    <Link
                                      to={`/v2/returns/instrument/${encodeURIComponent(instrument.isin)}`}
                                      title={instrument.name}
                                    >
                                      {name}
                                    </Link>
                                  ) : (
                                    <strong>{name}</strong>
                                  )}
                                  <small>{item.account_name}</small>
                                </td>
                                <td>
                                  {payoutKindLabel(item.flow_type)}
                                  {item.flow_type === "redemption" ? (
                                    <small>возврат капитала, не доход</small>
                                  ) : null}
                                </td>
                                <td
                                  className={styles.paymentAmount}
                                  title={calendarTotal([item.expected_net_amount])}
                                >
                                  {item.is_approximate ? "≈ " : ""}
                                  {wholeMoneyText(item.expected_net_amount)}
                                </td>
                              </tr>
                            );
                          })}
                      </tbody>
                    </table>
                  ) : (
                    <p className="muted tiny">Нет сохранённых выплат.</p>
                  )}
                </details>
              ))}
            </div>
          </>
        ) : (
          <p>
            {calendarLoaded
              ? "На этом горизонте нет сохранённых выплат."
              : "Сохранённые выплаты пока недоступны."}
          </p>
        )}
      </section>
      <div id="payout-forecast-details" hidden={!detailsOpen} className={styles.diagnostics}>
        <h2>Подробности прогноза</h2>
        <p>
          «Обновить» перечитывает сохранённый календарь. Проверка T-Invest ниже получает
          предпросмотр; применение выбранных событий требует подтверждения.
        </p>
        <p>
          <Link to={`/v2/close?month=${monthId}&panel=brokers`}>
            Загрузка файлов месяца · PDF выплат
          </Link>
        </p>
        {automatic ? (
          <p>
            Автообновление: {automatic.status}
            {automatic.reason_codes.length ? ` · ${automatic.reason_codes.join(", ")}` : ""}
          </p>
        ) : null}
        {contextError ? (
          <div className="inline-alert inline-alert--error" role="alert">
            {contextError}
          </div>
        ) : null}
        <TInvestPayoutApplySummary result={lastApplyResult} />
        <Panel label="Операции" title="Проверка и применение прогноза">
          <div className="toolbar">
            <Button
              disabled={
                previewLoading ||
                batchLoading ||
                applying ||
                loadingContext ||
                positions.length === 0
              }
              onClick={() => void handleBatchPreview()}
              variant="primary"
              type="button"
            >
              {batchLoading ? "Запрашиваем…" : "Проверить все позиции T-Invest"}
            </Button>
            <Button
              disabled={
                applying ||
                previewLoading ||
                batchLoading ||
                retiredPreview ||
                readOnly ||
                !Object.values(selectedGroups).some((rows) => rows.length)
              }
              onClick={requestBulkApply}
              type="button"
              variant="primary"
            >
              Применить выбранные
            </Button>
            <span role="status">
              Выбрано событий:{" "}
              {Object.values(selectedGroups).reduce((count, rows) => count + rows.length, 0)}
            </span>
            <Button
              disabled={applying || retiredPreview || readOnly || !batchPreview}
              onClick={() =>
                selectionCommand(
                  batchPreview?.items.map((item) => item.position_snapshot_id) ?? [],
                  "eligible",
                )
              }
              type="button"
            >
              Выбрать доступные
            </Button>
            <Button
              disabled={applying || !batchPreview}
              onClick={() =>
                selectionCommand(
                  batchPreview?.items.map((item) => item.position_snapshot_id) ?? [],
                  "clear",
                )
              }
              type="button"
            >
              Очистить выбор
            </Button>
            <Button
              disabled={!batchPreview}
              onClick={() =>
                setExpanded(new Set(batchPreview?.items.map((item) => item.position_snapshot_id)))
              }
              type="button"
            >
              Развернуть всё
            </Button>
            <Button disabled={!batchPreview} onClick={() => setExpanded(new Set())} type="button">
              Свернуть всё
            </Button>
            {applying ? (
              <Button
                type="button"
                onClick={() => {
                  stopRequested.current = true;
                }}
              >
                Остановить после текущей группы
              </Button>
            ) : null}
          </div>
          {actionError ? (
            <div role="alert" className="inline-alert inline-alert--warn">
              {actionError}
            </div>
          ) : null}
          {executionResults.length ? (
            <div aria-live="polite">
              <p>
                Результат по группам. Подтверждено:{" "}
                {executionResults.filter((row) => row.outcome === "CONFIRMED").length} из{" "}
                {executionResults.length}.
              </p>
              {executionResults.map((row, index) => (
                <p key={row.group.payload.position_snapshot_id}>
                  <strong>{row.group.label}</strong>: {PAYOUT_OUTCOME_LABELS[row.outcome]} · версия
                  «{row.group.payload.forecast_version}» ·{" "}
                  {activeGroup === index
                    ? "Проверяем / применяем…"
                    : row.message.replaceAll("об Apply", "о применении")}
                </p>
              ))}
            </div>
          ) : null}
        </Panel>

        {refreshStatus && refreshStatus.positions_changed > 0 ? (
          <div className="inline-alert inline-alert--warn payout-refresh-needed" role="status">
            <div>
              <strong>Прогноз выплат требует обновления.</strong> {refreshStatus.positions_changed}{" "}
              позиции изменились локально; T-Invest ещё не перечитан.
            </div>
            <Button
              disabled={batchLoading || applying || loadingContext}
              onClick={() =>
                void handleBatchPreview(
                  refreshStatus.items.map((item) => item.position_snapshot_id),
                )
              }
              type="button"
            >
              {batchLoading ? "Запрашиваем…" : "Проверить изменённые"}
            </Button>
          </div>
        ) : null}

        <Panel label="Синхронизация" title="Проверка позиций T-Invest">
          {batchPreview ? (
            <div className="stack-18 payout-batch-results">
              <TInvestBatchSummary preview={batchPreview} />
              {batchPreview.items.map((item) => {
                const itemLabel = positionLabelFor(item.account_id, item.instrument_id);
                const previewValue = item.preview;
                const attention = previewValue?.rows.filter(
                  (row) => row.status !== "new" && row.status !== "unchanged",
                );
                return (
                  <div className="payout-batch-results__group" key={item.position_snapshot_id}>
                    <div className="payout-batch-results__heading">
                      <strong>{itemLabel}</strong>
                      <TInvestBatchItemStatus item={item} />
                    </div>
                    <p>
                      Событий: {previewValue?.rows.length ?? 0} · Выбрано:{" "}
                      {selectedGroups[item.position_snapshot_id]?.length ?? 0}
                    </p>
                    <p>
                      Доход: {payoutSubtotal(previewValue?.rows ?? [], false)} · Возврат капитала:{" "}
                      {payoutSubtotal(previewValue?.rows ?? [], true)}
                    </p>
                    {attention?.length ? (
                      <p>
                        {attention
                          .map(
                            (row) =>
                              `${PAYOUT_ATTENTION[row.status] ?? "Требует проверки"}${row.message ? `: ${row.message}` : ""}`,
                          )
                          .join(" · ")}
                      </p>
                    ) : null}
                    {previewValue?.rows.some((row) => row.status === "unchanged") ? (
                      <p>Уже сохранено; повторно не отправляется.</p>
                    ) : null}
                    {item.message ? <p role="status">{item.message}</p> : null}
                    <Button
                      type="button"
                      aria-expanded={expanded.has(item.position_snapshot_id)}
                      aria-controls={`payout-group-${item.position_snapshot_id}`}
                      onClick={() =>
                        setExpanded((current) => {
                          const next = new Set(current);
                          if (next.has(item.position_snapshot_id))
                            next.delete(item.position_snapshot_id);
                          else next.add(item.position_snapshot_id);
                          return next;
                        })
                      }
                    >
                      {expanded.has(item.position_snapshot_id) ? "Свернуть" : "Развернуть"}{" "}
                      {itemLabel}
                    </Button>
                    <Button
                      type="button"
                      disabled={applying || retiredPreview || readOnly || !previewValue}
                      onClick={() =>
                        selectionCommand(
                          [item.position_snapshot_id],
                          selectedGroups[item.position_snapshot_id]?.length ? "clear" : "eligible",
                        )
                      }
                    >
                      Выбрать / очистить {itemLabel}
                    </Button>
                    <div
                      id={`payout-group-${item.position_snapshot_id}`}
                      hidden={!expanded.has(item.position_snapshot_id)}
                    >
                      {previewValue ? (
                        <PayoutPreviewPanel
                          applying={applying}
                          error={null}
                          forecastVersion={version}
                          loading={previewLoading || batchLoading}
                          onApply={(rows) => requestBatchApply(previewValue, rows)}
                          onForecastVersionChange={() => undefined}
                          onRefresh={() =>
                            void handleBatchPositionRefresh(item.position_snapshot_id)
                          }
                          positionLabel={itemLabel}
                          preview={previewValue}
                          readOnly={readOnly || retiredPreview}
                          versionDisabled={true}
                          selectionCommand={selectionCommands[item.position_snapshot_id]}
                          onSelectionChange={(rows) =>
                            setSelectedGroups((current) =>
                              JSON.stringify(current[item.position_snapshot_id]) ===
                              JSON.stringify(rows)
                                ? current
                                : { ...current, [item.position_snapshot_id]: rows },
                            )
                          }
                        />
                      ) : (
                        <div
                          className={`inline-alert ${
                            item.status === "error" ? "inline-alert--warn" : "inline-alert--info"
                          }`}
                          role="status"
                        >
                          <TInvestBatchItemStatus item={item} />{" "}
                          {item.message ?? "Нет предпросмотра для позиции."}
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          ) : null}
        </Panel>

        <details open className={styles.individual}>
          <summary>Одна позиция · индивидуальное применение</summary>
          <Panel
            action={
              <Badge tone={month.status === "closed" ? "closed" : "draft"}>
                {labelOf(MONTH_STATUS_LABELS, month.status)}
              </Badge>
            }
            label="Контекст"
            title="Месяц, версия и позиция"
          >
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
                        {account?.name ?? "Неизвестный счёт"} ·{" "}
                        {instrument?.name ?? "Неизвестный инструмент"}
                        {instrument?.ticker ? ` (${instrument.ticker})` : ""} · {type} ·{" "}
                        {formatQuantity(position.quantity)} шт.
                      </option>
                    );
                  })}
                </Select>
              </Field>
              <div className="stack-8">
                <span className="muted tiny">Версия прогноза</span>
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
              <EmptyState description="Добавь позицию в этом месяце." inline title="Нет позиций" />
            ) : null}
          </Panel>

          <PayoutPreviewPanel
            applying={applying}
            error={null}
            forecastVersion={forecastVersion}
            loading={previewLoading || batchLoading}
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
        </details>
      </div>

      <ConfirmDialog
        open={pendingBulk !== null}
        busy={applying}
        title="Применить выбранные группы?"
        description={`${formatMonth(month.year, month.month)}, версия «${version}». ${pendingBulk?.map((group) => `${group.label}: ${group.rows.length} событий`).join("; ") ?? ""}. Группы применяются последовательно. При остановке подтверждённые изменения сохраняются; неопределённый запрос не повторяется.`}
        confirmLabel={`Подтвердить выбор (${pendingBulk?.length ?? 0} групп)`}
        cancelLabel="Отмена"
        onCancel={() => setPendingBulk(null)}
        onConfirm={() => {
          if (pendingBulk) void runSelection(pendingBulk, false);
        }}
      />
      <ConfirmDialog
        busy={applying}
        cancelLabel="Отмена"
        confirmLabel={`Применить (${pendingApply?.rows.length ?? 0})`}
        description={
          pendingApply
            ? `Применить ${pendingApply.rows.length} прогнозных событий T-Invest за ${formatMonth(month.year, month.month)} (версия «${pendingApply.previewVersion}»)? Календарь будет перечитан перед подтверждением.`
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
  const month = isQueryReady(months)
    ? selection.kind === "selected"
      ? selection.month
      : selection.kind === "automatic"
        ? latestClosedMonth(months.data ?? [])
        : null
    : null;
  const close = parseMonthlyCloseReturnContext(params);
  const returnPath = close && close.monthId === month?.id ? monthlyCloseReturnPath(close) : null;
  const [payoutWriteActive, setPayoutWriteActive] = useState(false);
  const [statementWriteActive, setStatementWriteActive] = useState(false);
  const statementDisclosure = useRef<HTMLDetailsElement>(null);
  const [statementOutcomeByMonth, setStatementOutcomeByMonth] = useState<{
    monthId: number;
    outcome: AlfaStatementTransientOutcome;
  } | null>(null);
  const closeStepActive =
    close !== null && close.step === "actual_payouts" && close.monthId === month?.id;
  const statementOutcome =
    statementOutcomeByMonth?.monthId === month?.id
      ? (statementOutcomeByMonth?.outcome ?? null)
      : null;
  const handleStatementOutcome = useCallback(
    (next: AlfaStatementTransientOutcome | null) => {
      if (!closeStepActive || month === null) return;
      setStatementOutcomeByMonth(next ? { monthId: month.id, outcome: next } : null);
    },
    [closeStepActive, month],
  );

  useEffect(() => {
    if (location.hash !== "#statement-import" || !month || !statementDisclosure.current) return;
    const disclosure = statementDisclosure.current;
    disclosure.open = true;
    disclosure.scrollIntoView?.({ block: "start" });
  }, [location.hash, month]);
  const monthOptions = useMemo(() => {
    const rows = months.data ?? [];
    const fallback = latestClosedMonth(rows);
    return { rows, fallback };
  }, [months.data]);

  return (
    <UiV2DataFrame
      active="payouts"
      title="Выплаты"
      subtitle="Доход и возврат номинала по сохранённому прогнозу."
      monthId={month?.id}
    >
      <div className={styles.context}>
        <label htmlFor="payout-forecast-month">Отчётный месяц</label>
        <select
          disabled={payoutWriteActive || statementWriteActive}
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
          Выбери доступный месяц.
          {monthOptions.fallback
            ? ` Последний доступный: ${formatMonth(monthOptions.fallback.year, monthOptions.fallback.month)}.`
            : ""}
        </UiV2Notice>
      ) : (
        <>
          <DataMonthContext month={month} automatic={selection.kind === "automatic"} />
          <div inert={statementWriteActive}>
            <PayoutForecastTool
              key={`${month.id}:${location.search}`}
              monthId={month.id}
              onApplyingChange={setPayoutWriteActive}
              close={close && close.monthId === month.id ? close : null}
            />
          </div>
          <details
            className={styles.individual}
            id="statement-import"
            inert={payoutWriteActive}
            key={month.id}
            ref={statementDisclosure}
          >
            <summary>Импорт выписок (старый)</summary>
            <UiV2StatementImportSection
              closeStepActive={closeStepActive}
              month={month}
              onApplyingChange={setStatementWriteActive}
              onOutcome={handleStatementOutcome}
              outcome={statementOutcome}
              returnPath={returnPath}
            />
          </details>
        </>
      )}
    </UiV2DataFrame>
  );
}
