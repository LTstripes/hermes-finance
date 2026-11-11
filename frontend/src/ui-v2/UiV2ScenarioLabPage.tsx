import { IncomeTabs } from "./IncomeTabs";
import { triggerDownload } from "../lib/download";
import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router";

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
import { formatMonth } from "../lib/format";
import { labelOf, MONTH_STATUS_LABELS } from "../lib/labels";
import { isAtLeast, isWithinRange, normalizeDecimalInput, SCENARIO_OPTIONS } from "./scenarioLab";
import { ScenarioLabResult } from "./ScenarioLabResult";
import { resolveMonthSelection, sortReportingMonths } from "./monthSelection";
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
  const [inputError, setInputError] = useState<string | null>(null);
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

  const invalidate = useCallback(() => {
    requestSeq.current += 1;
    requestAbort.current?.abort();
    requestAbort.current = null;
    setRunning(false);
    setDownloading(false);
    setCalculated(null);
    setError(null);
    setInputError(null);
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
    if (running || downloading) return;
    if (!selectedMonth || !shock) {
      setInputError(
        !selectedMonth ? "Выберите отчётный месяц." : "Введите допустимое значение параметра.",
      );
      return;
    }
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

  return (
    <UiV2Shell
      showRefresh={false}
      active="income"
      busy={monthsLoading || running || downloading}
      header={<h1>Доход и планы</h1>}
    >
      <IncomeTabs active="scenarios" monthId={selectedMonth?.id} />
      <div className={styles.layout}>
        <div className={styles.page}>
          <UiV2Panel
            eyebrow=""
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
                </div>
                <fieldset className={styles.scenarios}>
                  <legend>Сценарий</legend>
                  {SCENARIO_OPTIONS.map((option) => (
                    <label key={option.value} className={styles.scenario}>
                      <input
                        type="radio"
                        name="scenario"
                        value={option.value}
                        checked={scenarioType === option.value}
                        onChange={() => {
                          invalidate();
                          setScenarioType(option.value);
                        }}
                      />
                      <span>
                        <strong>{option.label}</strong>
                        <small>{option.question}</small>
                      </span>
                    </label>
                  ))}
                </fieldset>
                <fieldset className={styles.presets} aria-label="Готовые значения параметра">
                  {(scenarioType === "equity_drawdown"
                    ? ["10", "20", "30"]
                    : scenarioType === "deposit_rate_assumption"
                      ? ["8", "12", "16"]
                      : scenarioType === "inflation_real_value"
                        ? ["4", "8", "12"]
                        : ["-10", "10", "20"]
                  ).map((value) => (
                    <button
                      type="button"
                      key={value}
                      aria-pressed={
                        (scenarioType === "equity_drawdown"
                          ? equityPct
                          : scenarioType === "deposit_rate_assumption"
                            ? depositRate
                            : scenarioType === "inflation_real_value"
                              ? inflationPct
                              : fxPct) === value
                      }
                      onClick={() => {
                        invalidate();
                        (scenarioType === "equity_drawdown"
                          ? setEquityPct
                          : scenarioType === "deposit_rate_assumption"
                            ? setDepositRate
                            : scenarioType === "inflation_real_value"
                              ? setInflationPct
                              : setFxPct)(value);
                      }}
                    >
                      {value}%
                    </button>
                  ))}
                </fieldset>
                <div className={styles.fields}>
                  {scenarioType === "equity_drawdown" ? (
                    <label>
                      Размер просадки акций, %
                      <input
                        aria-describedby={inputError ? "scenario-input-error" : undefined}
                        aria-invalid={inputError && !shock ? true : undefined}
                        title="Своё значение"
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
                        aria-describedby={inputError ? "scenario-input-error" : undefined}
                        aria-invalid={inputError && !shock ? true : undefined}
                        title="Своё значение"
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
                        aria-describedby={inputError ? "scenario-input-error" : undefined}
                        aria-invalid={inputError && !shock ? true : undefined}
                        title="Своё значение"
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
                          aria-describedby={inputError ? "scenario-input-error" : undefined}
                          aria-invalid={inputError && !shock ? true : undefined}
                          title="Своё значение"
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
                {inputError ? (
                  <p id="scenario-input-error" className={styles.error} role="alert">
                    {inputError}
                  </p>
                ) : null}
                <div className={styles.actions}>
                  <button
                    aria-busy={running}
                    aria-disabled={running || downloading}
                    onClick={() => void calculate()}
                    type="button"
                  >
                    {running ? "Считаем…" : "Рассчитать сценарий"}
                  </button>
                </div>
              </>
            ) : null}
          </UiV2Panel>

          <div className={styles.resultColumn}>
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
                <button
                  className={styles.exportLink}
                  disabled={downloading || running}
                  onClick={() => void exportJson()}
                  type="button"
                >
                  {downloading ? "Скачиваем…" : "Скачать расчёт (JSON)"}
                </button>
              </div>
            ) : null}
            {!currentResult && !error && selectedMonth && !running ? (
              <p role="status">Результат появится после нажатия «Рассчитать сценарий».</p>
            ) : null}
          </div>
        </div>
      </div>
    </UiV2Shell>
  );
}
