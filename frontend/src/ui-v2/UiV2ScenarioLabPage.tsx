import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router";

import { ApiClientError, formatApiError } from "../api/client";
import { listMonths } from "../api/months";
import {
  downloadScenarioLabExport,
  evaluateScenarioLab,
  shockTypeOf,
  type ScenarioLabEvaluation,
  type ScenarioLabShock,
  type ScenarioShockType,
} from "../api/scenarioLab";
import type { ReportingMonth } from "../api/types";
import { formatDate, formatMonth } from "../lib/format";
import { labelOf, MONTH_STATUS_LABELS } from "../lib/labels";
import {
  isAtLeast,
  isWithinRange,
  normalizeDecimalInput,
  SCENARIO_OPTIONS,
  ScenarioLabResult,
  triggerDownload,
} from "../pages/ScenarioLabPage";
import { resolveMonthSelection, sortReportingMonths } from "./monthSelection";
import sharedStyles from "./UiV2Page.module.css";
import styles from "./UiV2ScenarioLab.module.css";
import { UiV2Panel } from "./UiV2Panel";
import { UiV2Shell } from "./UiV2Shell";

type Calculated = {
  monthId: number;
  shock: ScenarioLabShock;
  key: string;
  evaluation: ScenarioLabEvaluation;
};

function inputKey(monthId: number, shock: ScenarioLabShock): string {
  return JSON.stringify([monthId, shock]);
}

export default function UiV2ScenarioLabPage() {
  const [params, setParams] = useSearchParams();
  const [months, setMonths] = useState<ReportingMonth[]>([]);
  const [monthsLoading, setMonthsLoading] = useState(true);
  const [monthsError, setMonthsError] = useState<string | null>(null);
  const [scenarioType, setScenarioType] = useState<ScenarioShockType>("equity_drawdown");
  const [equityPct, setEquityPct] = useState("");
  const [depositRate, setDepositRate] = useState("");
  const [inflationPct, setInflationPct] = useState("");
  const [fxCurrency, setFxCurrency] = useState("USD");
  const [fxPct, setFxPct] = useState("");
  const [running, setRunning] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [calculated, setCalculated] = useState<Calculated | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [errorCode, setErrorCode] = useState<string | null>(null);
  const [exportNotice, setExportNotice] = useState<string | null>(null);
  const requestSeq = useRef(0);
  const requestAbort = useRef<AbortController | null>(null);
  const previousMonthId = useRef<number | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    listMonths(controller.signal)
      .then((rows) => setMonths(sortReportingMonths(rows)))
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) setMonthsError(formatApiError(cause));
      })
      .finally(() => {
        if (!controller.signal.aborted) setMonthsLoading(false);
      });
    return () => controller.abort();
  }, []);

  const selection = resolveMonthSelection(params.getAll("month"), months);
  const selectedMonth =
    selection.kind === "selected"
      ? selection.month
      : selection.kind === "automatic"
        ? (months.find((month) => month.status === "closed") ?? months[0] ?? null)
        : null;

  function buildShock(): ScenarioLabShock | null {
    if (scenarioType === "equity_drawdown") {
      const value = normalizeDecimalInput(equityPct, false);
      return isWithinRange(value, 100)
        ? { equity_drawdown: { drawdown_pct: value as string } }
        : null;
    }
    if (scenarioType === "deposit_rate_assumption") {
      const value = normalizeDecimalInput(depositRate, false);
      return value === null
        ? null
        : {
            deposit_rate_assumption: {
              assumed_annual_rate_pct: value,
              all_eligible_deposits: true,
            },
          };
    }
    if (scenarioType === "inflation_real_value") {
      const value = normalizeDecimalInput(inflationPct, false);
      return value === null ? null : { inflation_real_value: { annual_inflation_pct: value } };
    }
    const value = normalizeDecimalInput(fxPct, true);
    return fxCurrency.trim() !== "" && isAtLeast(value, -100)
      ? {
          fx_translation_shock: {
            target_currency: fxCurrency.trim().toUpperCase(),
            reporting_value_change_pct: value as string,
          },
        }
      : null;
  }

  const shock = buildShock();
  const currentKey = selectedMonth && shock ? inputKey(selectedMonth.id, shock) : null;
  const currentResult = calculated?.key === currentKey ? calculated : null;
  const scenarioDescription = SCENARIO_OPTIONS.find(
    (option) => option.value === scenarioType,
  )?.description;

  const invalidate = useCallback(() => {
    requestSeq.current += 1;
    requestAbort.current?.abort();
    requestAbort.current = null;
    setRunning(false);
    setDownloading(false);
    setCalculated(null);
    setError(null);
    setErrorCode(null);
    setExportNotice(null);
  }, []);

  const monthId = selectedMonth?.id ?? null;
  useEffect(() => {
    if (previousMonthId.current !== monthId) {
      previousMonthId.current = monthId;
      invalidate();
    }
  }, [invalidate, monthId]);

  useEffect(() => {
    return () => {
      requestSeq.current += 1;
      requestAbort.current?.abort();
    };
  }, []);

  async function calculate() {
    if (!selectedMonth || !shock || running || downloading) return;
    invalidate();
    const seq = requestSeq.current;
    const controller = new AbortController();
    requestAbort.current = controller;
    const snapshot = { monthId: selectedMonth.id, shock, key: inputKey(selectedMonth.id, shock) };
    setRunning(true);
    try {
      const evaluation = await evaluateScenarioLab(
        snapshot.monthId,
        snapshot.shock,
        controller.signal,
      );
      if (seq !== requestSeq.current || controller.signal.aborted) return;
      if (
        evaluation.reporting_month.id !== snapshot.monthId ||
        shockTypeOf(evaluation) !== scenarioType
      ) {
        throw new Error("Ответ расчёта не соответствует выбранному месяцу или сценарию.");
      }
      setCalculated({ ...snapshot, evaluation });
    } catch (cause) {
      if (seq !== requestSeq.current || controller.signal.aborted) return;
      setError(formatApiError(cause));
      setErrorCode(cause instanceof ApiClientError ? cause.code : null);
    } finally {
      if (seq === requestSeq.current) {
        requestAbort.current = null;
        setRunning(false);
      }
    }
  }

  async function exportJson() {
    if (!currentResult || downloading || running) return;
    const seq = requestSeq.current;
    setDownloading(true);
    setExportNotice(null);
    setError(null);
    setErrorCode(null);
    try {
      const file = await downloadScenarioLabExport(currentResult.monthId, currentResult.shock);
      if (seq !== requestSeq.current) return;
      triggerDownload(file.blob, file.filename);
      setExportNotice(`Файл ${file.filename} скачан.`);
    } catch (cause) {
      if (seq !== requestSeq.current) return;
      setError(formatApiError(cause));
      setErrorCode(cause instanceof ApiClientError ? cause.code : null);
    } finally {
      if (seq === requestSeq.current) setDownloading(false);
    }
  }

  function changeMonth(value: string) {
    invalidate();
    const next = new URLSearchParams(params);
    next.set("month", value);
    setParams(next);
  }

  const returnPath =
    selectedMonth?.status === "closed" ? `/v2/income?month=${selectedMonth.id}` : "/v2/income";
  const v1ReturnPath = "/scenario-lab";

  return (
    <UiV2Shell
      active="income"
      busy={monthsLoading || running || downloading}
      header={
        <>
          <p className={sharedStyles.eyebrow}>Доход и планы / Сценарии</p>
          <h1>Сценарии</h1>
          <p className={sharedStyles.subtitle}>
            Расчёт «что если» по снимку месяца. Один сценарий за раз, только по кнопке; данные не
            меняются.
          </p>
          <Link className={sharedStyles.contextLink} to={returnPath}>
            ← Вернуться к доходу и планам
          </Link>
        </>
      }
      v1ReturnPath={v1ReturnPath}
    >
      <div className={styles.page}>
        <UiV2Panel
          eyebrow="Параметры"
          id="scenario-controls"
          testIdPrefix="scenario"
          title="Какой сценарий считаем"
        >
          {monthsLoading ? <p role="status">Загружаем отчётные месяцы…</p> : null}
          {monthsError ? <p role="alert">Не удалось загрузить месяцы: {monthsError}</p> : null}
          {!monthsLoading && !monthsError && months.length === 0 ? (
            <p role="status">Нет отчётных месяцев.</p>
          ) : null}
          {!monthsLoading && !monthsError && months.length > 0 ? (
            <>
              {selection.kind === "invalid" || selection.kind === "missing" ? (
                <p className={styles.error} role="alert">
                  Указанный месяц недействителен или отсутствует. Выберите отчётный месяц.
                </p>
              ) : null}
              <div className={styles.fields}>
                <label>
                  Отчётный месяц
                  <select
                    onChange={(event) => changeMonth(event.target.value)}
                    value={selectedMonth?.id ?? ""}
                  >
                    {!selectedMonth ? <option value="">Выберите месяц</option> : null}
                    {months.map((month) => (
                      <option key={month.id} value={month.id}>
                        {formatMonth(month.year, month.month)} ·{" "}
                        {labelOf(MONTH_STATUS_LABELS, month.status)}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Сценарий
                  <select
                    onChange={(event) => {
                      invalidate();
                      setScenarioType(event.target.value as ScenarioShockType);
                    }}
                    value={scenarioType}
                  >
                    {SCENARIO_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <p className={styles.description}>{scenarioDescription}</p>
              <div className={styles.fields}>
                {scenarioType === "equity_drawdown" ? (
                  <label>
                    Размер просадки акций, %
                    <input
                      inputMode="decimal"
                      onChange={(event) => {
                        invalidate();
                        setEquityPct(event.target.value);
                      }}
                      placeholder="10"
                      value={equityPct}
                    />
                  </label>
                ) : null}
                {scenarioType === "deposit_rate_assumption" ? (
                  <label>
                    Гипотетическая годовая ставка по вкладам, %
                    <input
                      inputMode="decimal"
                      onChange={(event) => {
                        invalidate();
                        setDepositRate(event.target.value);
                      }}
                      placeholder="8"
                      value={depositRate}
                    />
                  </label>
                ) : null}
                {scenarioType === "inflation_real_value" ? (
                  <label>
                    Годовая инфляция, %
                    <input
                      inputMode="decimal"
                      onChange={(event) => {
                        invalidate();
                        setInflationPct(event.target.value);
                      }}
                      placeholder="12"
                      value={inflationPct}
                    />
                  </label>
                ) : null}
                {scenarioType === "fx_translation_shock" ? (
                  <>
                    <label>
                      Валюта шока
                      <select
                        onChange={(event) => {
                          invalidate();
                          setFxCurrency(event.target.value);
                        }}
                        value={fxCurrency}
                      >
                        {["USD", "EUR", "GBP", "CHF", "JPY", "CNY"].map((currency) => (
                          <option key={currency} value={currency}>
                            {currency}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>
                      Изменение стоимости в отчёте, %
                      <input
                        inputMode="decimal"
                        onChange={(event) => {
                          invalidate();
                          setFxPct(event.target.value);
                        }}
                        placeholder="10"
                        value={fxPct}
                      />
                    </label>
                  </>
                ) : null}
              </div>
              {selectedMonth ? (
                <p className={styles.asof}>
                  Отчётный месяц: {formatMonth(selectedMonth.year, selectedMonth.month)} · снимок{" "}
                  {formatDate(selectedMonth.snapshot_date)}
                </p>
              ) : null}
              <div className={styles.actions}>
                <button
                  disabled={!selectedMonth || !shock || running || downloading}
                  onClick={() => void calculate()}
                  type="button"
                >
                  {running ? "Считаем…" : "Рассчитать сценарий"}
                </button>
                <button
                  disabled={!currentResult || running || downloading}
                  onClick={() => void exportJson()}
                  type="button"
                >
                  {downloading ? "Скачиваем…" : "Скачать JSON"}
                </button>
              </div>
              <p className={styles.description}>
                Изменение месяца, сценария или параметров убирает прежний результат и экспорт.
              </p>
            </>
          ) : null}
        </UiV2Panel>

        {error ? (
          <p className={styles.error} role="alert">
            Не удалось выполнить запрос: {error}
            {errorCode ? ` · код: ${errorCode}` : ""}
          </p>
        ) : null}
        {exportNotice ? <p role="status">{exportNotice}</p> : null}
        {currentResult && selectedMonth ? (
          <div className={styles.result}>
            <ScenarioLabResult
              evaluation={currentResult.evaluation}
              onRetry={() => void calculate()}
              selectedMonth={selectedMonth}
            />
          </div>
        ) : null}
        {!currentResult && !error && selectedMonth && !running ? (
          <p role="status">Результат появится после нажатия «Рассчитать сценарий».</p>
        ) : null}
      </div>
    </UiV2Shell>
  );
}
