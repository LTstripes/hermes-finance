import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router";

import { listAccounts } from "../api/accounts";
import { formatApiError } from "../api/client";
import { listInstruments } from "../api/instruments";
import { listMonths } from "../api/months";
import {
  applyPayouts,
  getPayoutRefreshStatus,
  listPayoutCalendar,
  previewPayoutsBatch,
  previewPayouts,
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
import { PayoutPaymentsCalendar } from "../components/PayoutPaymentsCalendar";
import { PayoutPreviewPanel } from "../components/PayoutPreviewPanel";
import { StatementImportPanel } from "../components/StatementImportPanel";
import { MonthlyCloseReturnBar } from "../components/month-close/MonthlyCloseReturnBar";
import {
  monthlyCloseReturnPath,
  parseMonthlyCloseReturnContext,
  withMonthlyCloseReturn,
} from "../components/month-close/navigation";
import type { AlfaStatementTransientOutcome } from "../components/month-close/statementOutcome";
import {
  TInvestBatchItemStatus,
  TInvestBatchSummary,
  TInvestPayoutApplySummary,
} from "../components/month-close/TInvestStepSummary";
import { Badge, Button, EmptyState, Field, LoadingState, Panel, Select } from "../components/ui";
import { formatMonth, formatQuantity } from "../lib/format";
import { INSTRUMENT_TYPE_LABELS, MONTH_STATUS_LABELS, labelOf } from "../lib/labels";

function newestMonth(months: ReportingMonth[]): ReportingMonth | undefined {
  return [...months].sort((a, b) => b.year - a.year || b.month - a.month || b.id - a.id)[0];
}

const APPLY_FAILURE_LABELS: Record<string, string> = {
  preview_changed: "Предпросмотр изменился. Получи свежий preview и проверь выбор ещё раз.",
  closed_month: "Месяц закрыт. Сначала открой его для редактирования.",
  provider_error: "T-Invest не удалось безопасно перечитать данные. Ничего не применено.",
  validation_error: "Выбранные строки больше нельзя применить в этом состоянии.",
  persistence_error: "Не удалось сохранить выбранный набор. Все изменения отменены.",
};

export function PayoutsPage() {
  const closeContext = parseMonthlyCloseReturnContext(new URLSearchParams(window.location.search));
  const requestedMonthId = closeContext?.monthId ?? null;
  const [months, setMonths] = useState<ReportingMonth[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [instruments, setInstruments] = useState<Instrument[]>([]);
  const [positions, setPositions] = useState<PositionSnapshot[]>([]);
  const [calendar, setCalendar] = useState<PayoutCalendarMonth[]>([]);
  const [refreshStatus, setRefreshStatus] = useState<PayoutRefreshStatus | null>(null);
  const [batchPreview, setBatchPreview] = useState<PayoutBatchPreview | null>(null);
  const [selectedMonthId, setSelectedMonthId] = useState("");
  const [selectedPositionId, setSelectedPositionId] = useState("");
  const [forecastVersion, setForecastVersion] = useState("v1");
  const [preview, setPreview] = useState<PayoutPreview | null>(null);
  const [loadingBase, setLoadingBase] = useState(true);
  const [loadingContext, setLoadingContext] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [batchLoading, setBatchLoading] = useState(false);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [lastApplyResult, setLastApplyResult] = useState<PayoutApplyResult | null>(null);
  const [requestedMonthMissing, setRequestedMonthMissing] = useState(false);
  const [statementOutcome, setStatementOutcome] = useState<AlfaStatementTransientOutcome | null>(
    null,
  );

  const statementWizardContext = closeContext?.step === "actual_payouts" ? closeContext : null;

  useEffect(() => {
    const controller = new AbortController();
    async function loadBase() {
      setLoadingBase(true);
      setError(null);
      try {
        const [monthRows, accountRows, instrumentRows] = await Promise.all([
          listMonths(controller.signal),
          listAccounts(controller.signal),
          listInstruments({ active: true }, controller.signal),
        ]);
        if (controller.signal.aborted) return;
        setMonths(monthRows);
        setAccounts(accountRows);
        setInstruments(instrumentRows);
        const requested = requestedMonthId
          ? monthRows.find((month) => month.id === requestedMonthId)
          : undefined;
        setRequestedMonthMissing(Boolean(requestedMonthId && !requested));
        const initial = requestedMonthId ? requested : newestMonth(monthRows);
        setSelectedMonthId(initial ? String(initial.id) : "");
      } catch (err) {
        if (!controller.signal.aborted) setError(formatApiError(err));
      } finally {
        if (!controller.signal.aborted) setLoadingBase(false);
      }
    }
    void loadBase();
    return () => controller.abort();
  }, [requestedMonthId]);

  const selectedMonth = useMemo(
    () => months.find((month) => String(month.id) === selectedMonthId) ?? null,
    [months, selectedMonthId],
  );

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

  const loadContext = useCallback(
    async (monthId: number, version: string, signal?: AbortSignal) => {
      setLoadingContext(true);
      setError(null);
      try {
        const [positionRows, calendarRows, refreshRows] = await Promise.all([
          listPositions(monthId, undefined, signal),
          listPayoutCalendar(monthId, version, signal),
          getPayoutRefreshStatus(monthId, signal),
        ]);
        if (signal?.aborted) return;
        setPositions(positionRows);
        setCalendar(calendarRows);
        setRefreshStatus(refreshRows);
        setSelectedPositionId((current) =>
          positionRows.some((row) => String(row.id) === current)
            ? current
            : positionRows[0]
              ? String(positionRows[0].id)
              : "",
        );
      } catch (err) {
        if (!signal?.aborted) setError(formatApiError(err));
      } finally {
        if (!signal?.aborted) setLoadingContext(false);
      }
    },
    [],
  );

  useEffect(() => {
    const monthId = Number(selectedMonthId);
    if (!Number.isInteger(monthId) || monthId < 1 || !forecastVersion.trim()) {
      setPositions([]);
      setCalendar([]);
      setRefreshStatus(null);
      return;
    }
    setPreview(null);
    setBatchPreview(null);
    setActionError(null);
    setLastApplyResult(null);
    setStatementOutcome(null);
    const controller = new AbortController();
    void loadContext(monthId, forecastVersion.trim(), controller.signal);
    return () => controller.abort();
  }, [forecastVersion, loadContext, selectedMonthId]);

  useEffect(() => {
    if (!statementWizardContext || loadingBase || requestedMonthMissing) return;
    const target = document.getElementById("statement-import");
    if (target && typeof target.scrollIntoView === "function") {
      target.scrollIntoView({ block: "start" });
    }
  }, [loadingBase, requestedMonthMissing, statementWizardContext]);

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

  function contextPayload() {
    if (!selectedPosition || !forecastVersion.trim()) return null;
    return {
      account_id: selectedPosition.account_id,
      instrument_id: selectedPosition.instrument_id,
      position_snapshot_id: selectedPosition.id,
      forecast_version: forecastVersion.trim(),
    };
  }

  function payloadForPreview(value: PayoutPreview): PayoutContextRequest {
    return {
      account_id: value.account_id,
      instrument_id: value.instrument_id,
      position_snapshot_id: value.position_snapshot_id ?? 0,
      forecast_version: forecastVersion.trim(),
    };
  }

  async function handlePreview() {
    const monthId = Number(selectedMonthId);
    const payload = contextPayload();
    if (!payload || !Number.isInteger(monthId) || monthId < 1) return;
    setPreviewLoading(true);
    setActionError(null);
    setLastApplyResult(null);
    try {
      setPreview(await previewPayouts(monthId, payload));
    } catch (err) {
      setPreview(null);
      setActionError(formatApiError(err));
    } finally {
      setPreviewLoading(false);
    }
  }

  async function handleBatchPreview(positionSnapshotIds?: number[]) {
    const monthId = Number(selectedMonthId);
    if (!Number.isInteger(monthId) || monthId < 1 || !forecastVersion.trim()) return;
    setBatchLoading(true);
    setActionError(null);
    setLastApplyResult(null);
    try {
      setBatchPreview(
        await previewPayoutsBatch(monthId, forecastVersion.trim(), positionSnapshotIds),
      );
    } catch (err) {
      setBatchPreview(null);
      setActionError(formatApiError(err));
    } finally {
      setBatchLoading(false);
    }
  }

  async function handleBatchPositionRefresh(positionSnapshotId: number) {
    const monthId = Number(selectedMonthId);
    const position = positions.find((row) => row.id === positionSnapshotId);
    if (!position || !Number.isInteger(monthId) || monthId < 1) return;
    setPreviewLoading(true);
    setActionError(null);
    setLastApplyResult(null);
    try {
      const value = await previewPayouts(monthId, {
        account_id: position.account_id,
        instrument_id: position.instrument_id,
        position_snapshot_id: position.id,
        forecast_version: forecastVersion.trim(),
      });
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
    } catch (err) {
      setActionError(formatApiError(err));
    } finally {
      setPreviewLoading(false);
    }
  }

  async function handleApply(rows: PayoutApplySelection[]) {
    const monthId = Number(selectedMonthId);
    const payload = contextPayload();
    if (!payload || rows.length === 0 || !Number.isInteger(monthId) || monthId < 1) return;
    setApplying(true);
    setActionError(null);
    setLastApplyResult(null);
    try {
      await applyRows(payload, rows, (result) => {
        if (result.success) setPreview(null);
      });
    } finally {
      setApplying(false);
    }
  }

  async function applyRows(
    payload: PayoutContextRequest,
    rows: PayoutApplySelection[],
    onSuccess?: (result: Awaited<ReturnType<typeof applyPayouts>>) => void,
  ) {
    const monthId = Number(selectedMonthId);
    if (rows.length === 0 || !Number.isInteger(monthId) || monthId < 1) return;
    try {
      const result = await applyPayouts(monthId, { ...payload, rows });
      if (!result.success) {
        if (result.error_code === "preview_changed") setPreview(null);
        setLastApplyResult(null);
        setActionError(
          (result.error_code && APPLY_FAILURE_LABELS[result.error_code]) ||
            result.message ||
            "Выплаты не применены.",
        );
        return;
      }
      setCalendar(await listPayoutCalendar(monthId, forecastVersion.trim()));
      setRefreshStatus(await getPayoutRefreshStatus(monthId));
      setLastApplyResult(result);
      onSuccess?.(result);
    } catch (err) {
      setLastApplyResult(null);
      setActionError(formatApiError(err));
    }
  }

  async function handleBatchApply(previewValue: PayoutPreview, rows: PayoutApplySelection[]) {
    if (previewValue.position_snapshot_id === null) return;
    setApplying(true);
    setActionError(null);
    setLastApplyResult(null);
    await applyRows(payloadForPreview(previewValue), rows, (result) => {
      if (!result.success) return;
      setBatchPreview((current) =>
        current
          ? {
              ...current,
              items: current.items.map((item) =>
                item.preview?.position_snapshot_id === previewValue.position_snapshot_id
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
    });
    setApplying(false);
  }

  if (loadingBase) {
    return <LoadingState description="Загружаем автоматические выплаты…" />;
  }

  if (error && months.length === 0) {
    return <EmptyState description={error} title="Не удалось открыть автоматические выплаты" />;
  }

  return (
    <section className="stack-18">
      <MonthlyCloseReturnBar />
      <header className="page-header">
        <p className="eyebrow">Планирование</p>
        <h1>Автовыплаты</h1>
        <p className="page-header__description">
          Купоны, дивиденды и погашения из T-Invest — только после явного запроса и явного
          применения. Позиции и ручные ожидаемые выплаты остаются локальными данными Hermes.
        </p>
      </header>

      {error ? (
        <div className="inline-alert inline-alert--error" role="alert">
          {error}
        </div>
      ) : null}
      {requestedMonthMissing ? (
        <div className="inline-alert inline-alert--error" role="alert">
          Месяц из закрытия не найден. Вернись к выбору месяца и открой закрытие заново.
        </div>
      ) : null}
      <TInvestPayoutApplySummary result={lastApplyResult} />

      {statementWizardContext && selectedMonth ? (
        <Panel
          className="monthly-close__statement-context"
          label="Шаг закрытия"
          title={`Фактические выплаты · ${formatMonth(selectedMonth.year, selectedMonth.month)}`}
        >
          <p>
            Контекст месяца зафиксирован для этого перехода и возврата в закрытие. Строки PDF
            распределяются сервером по дате события; выбранный месяц не подменяет даты отчёта.
          </p>
        </Panel>
      ) : null}

      {!requestedMonthMissing ? (
        <div id="statement-import">
          <StatementImportPanel
            accounts={accounts}
            instruments={instruments}
            onApplied={async () => {
              const monthId = Number(selectedMonthId);
              if (Number.isInteger(monthId) && monthId > 0) {
                await loadContext(monthId, forecastVersion.trim());
              }
            }}
            onInstrumentsChange={setInstruments}
            onOutcome={statementWizardContext ? setStatementOutcome : undefined}
            readOnly={Boolean(statementWizardContext && selectedMonth?.status === "closed")}
          />
          {statementWizardContext && statementOutcome ? (
            <div className="statement-import__wizard-outcome" role="status">
              <div>
                <strong>Результат проверки PDF Alfa</strong>
                <p>
                  {statementOutcome.kind === "applied"
                    ? `Выбранные строки применены: ${statementOutcome.selectedCount}. Сохранённые факты будут повторно показаны в закрытии после обновления.`
                    : "Подходящих выплат не найдено. Этот результат не сохранён и не отмечает шаг выполненным."}
                </p>
              </div>
              <Link
                className="btn btn--secondary"
                state={{ alfaStatementOutcome: statementOutcome }}
                to={monthlyCloseReturnPath(statementWizardContext)}
              >
                Продолжить к закрытию
              </Link>
            </div>
          ) : null}
        </div>
      ) : null}

      <Panel
        action={
          selectedMonth ? (
            <Badge tone={selectedMonth.status === "closed" ? "closed" : "draft"}>
              {labelOf(MONTH_STATUS_LABELS, selectedMonth.status)}
            </Badge>
          ) : null
        }
        label="Контекст"
        title="Месяц и позиция"
      >
        <div className="editor-grid">
          <Field htmlFor="payout-month" label="Отчётный месяц">
            <Select
              disabled={Boolean(closeContext)}
              id="payout-month"
              onChange={(event) => {
                setSelectedMonthId(event.target.value);
                setPreview(null);
                setLastApplyResult(null);
              }}
              value={selectedMonthId}
            >
              <option value="">— выбери месяц —</option>
              {[...months]
                .sort((a, b) => b.year - a.year || b.month - a.month)
                .map((month) => (
                  <option key={month.id} value={month.id}>
                    {formatMonth(month.year, month.month)} ·{" "}
                    {labelOf(MONTH_STATUS_LABELS, month.status)}
                  </option>
                ))}
            </Select>
          </Field>

          <Field htmlFor="payout-position" label="Позиция">
            <Select
              disabled={!selectedMonthId || loadingContext}
              id="payout-position"
              onChange={(event) => {
                setSelectedPositionId(event.target.value);
                setPreview(null);
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
        </div>
        {selectedMonth ? (
          <div className="toolbar">
            <Link
              className="btn btn--ghost"
              to={
                statementWizardContext
                  ? withMonthlyCloseReturn(
                      `/months/${selectedMonth.id}?section=flows`,
                      selectedMonth.id,
                      "actual_payouts",
                    )
                  : `/months/${selectedMonth.id}?section=flows`
              }
            >
              Ручные выплаты этого месяца →
            </Link>
          </div>
        ) : null}
        {selectedMonthId && !loadingContext && positions.length === 0 ? (
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
        onApply={(rows) => void handleApply(rows)}
        onForecastVersionChange={(value) => {
          setForecastVersion(value || "v1");
          setPreview(null);
          setActionError(null);
          setLastApplyResult(null);
        }}
        onRefresh={() => void handlePreview()}
        positionLabel={positionLabel}
        preview={preview}
        readOnly={selectedMonth?.status === "closed"}
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
            выбором внутри каждой позиции.
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
                      forecastVersion={forecastVersion}
                      loading={previewLoading}
                      onApply={(rows) => void handleBatchApply(previewValue, rows)}
                      onForecastVersionChange={() => undefined}
                      onRefresh={() => void handleBatchPositionRefresh(item.position_snapshot_id)}
                      positionLabel={itemLabel}
                      preview={previewValue}
                      readOnly={selectedMonth?.status === "closed"}
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
          <PayoutPaymentsCalendar months={calendar} />
        )}
      </Panel>
    </section>
  );
}
