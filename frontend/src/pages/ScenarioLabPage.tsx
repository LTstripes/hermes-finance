import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiClientError, formatApiError, type ApiDownload } from "../api/client";
import { listMonths } from "../api/months";
import {
  downloadScenarioLabExport,
  evaluateScenarioLab,
  type ScenarioLabEvaluation,
  type ScenarioLabShock,
  type ScenarioShockType,
} from "../api/scenarioLab";
import type { ReportingMonth } from "../api/types";
import {
  Button,
  EmptyState,
  ErrorState,
  Field,
  Input,
  LoadingState,
  Panel,
  Select,
} from "../components/ui";
import { formatMonth } from "../lib/format";
import { labelOf, MONTH_STATUS_LABELS } from "../lib/labels";
import {
  isAtLeast,
  isWithinRange,
  normalizeDecimalInput,
  SCENARIO_OPTIONS,
  triggerDownload,
} from "../ui-v2/scenarioLab";
import { ScenarioLabResult } from "../ui-v2/ScenarioLabResult";

function sortMonths(months: ReportingMonth[]): ReportingMonth[] {
  return [...months].sort((a, b) => b.year - a.year || b.month - a.month || b.id - a.id);
}

function defaultMonth(months: ReportingMonth[]): ReportingMonth | null {
  const sorted = sortMonths(months);
  return sorted.find((month) => month.status === "closed") ?? sorted[0] ?? null;
}

export function ScenarioLabPage() {
  const [months, setMonths] = useState<ReportingMonth[]>([]);
  const [monthsLoading, setMonthsLoading] = useState(true);
  const [monthsError, setMonthsError] = useState<string | null>(null);
  const [selectedMonthId, setSelectedMonthId] = useState<number | null>(null);

  const [scenarioType, setScenarioType] = useState<ScenarioShockType>("equity_drawdown");
  const [equityPct, setEquityPct] = useState("");
  const [depositRate, setDepositRate] = useState("");
  const [inflationPct, setInflationPct] = useState("");
  const [fxCurrency, setFxCurrency] = useState("USD");
  const [fxPct, setFxPct] = useState("");

  const [running, setRunning] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [result, setResult] = useState<ScenarioLabEvaluation | null>(null);
  const [resultError, setResultError] = useState<string | null>(null);
  const [resultErrorCode, setResultErrorCode] = useState<string | null>(null);
  const [exportNotice, setExportNotice] = useState<string | null>(null);
  const requestSeqRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let alive = true;
    setMonthsLoading(true);
    setMonthsError(null);
    listMonths(controller.signal)
      .then((rows) => {
        if (!alive) return;
        const sorted = sortMonths(rows);
        setMonths(sorted);
        setSelectedMonthId((current) => current ?? defaultMonth(sorted)?.id ?? null);
      })
      .catch((error: unknown) => {
        if (!alive || controller.signal.aborted) return;
        setMonthsError(formatApiError(error));
      })
      .finally(() => {
        if (alive) setMonthsLoading(false);
      });
    return () => {
      alive = false;
      controller.abort();
    };
  }, []);

  const selectedMonth = useMemo(
    () => months.find((month) => month.id === selectedMonthId) ?? null,
    [months, selectedMonthId],
  );

  const invalidateResult = useCallback(() => {
    requestSeqRef.current += 1;
    abortRef.current?.abort();
    abortRef.current = null;
    setRunning(false);
    setResult(null);
    setResultError(null);
    setResultErrorCode(null);
    setExportNotice(null);
  }, []);

  const scenarioParamValid = useMemo(() => {
    if (scenarioType === "equity_drawdown") {
      return isWithinRange(normalizeDecimalInput(equityPct, false), 100);
    }
    if (scenarioType === "deposit_rate_assumption") {
      return normalizeDecimalInput(depositRate, false) != null;
    }
    if (scenarioType === "inflation_real_value") {
      return normalizeDecimalInput(inflationPct, false) != null;
    }
    if (scenarioType === "fx_translation_shock") {
      return fxCurrency.trim() !== "" && isAtLeast(normalizeDecimalInput(fxPct, true), -100);
    }
    return false;
  }, [depositRate, equityPct, fxCurrency, fxPct, inflationPct, scenarioType]);

  const canCalculate = selectedMonthId != null && scenarioParamValid && !running && !downloading;

  const buildShock = useCallback((): ScenarioLabShock | null => {
    if (scenarioType === "equity_drawdown") {
      const drawdownPct = normalizeDecimalInput(equityPct, false);
      if (drawdownPct == null) return null;
      return { equity_drawdown: { drawdown_pct: drawdownPct } };
    }
    if (scenarioType === "deposit_rate_assumption") {
      const rate = normalizeDecimalInput(depositRate, false);
      if (rate == null) return null;
      return {
        deposit_rate_assumption: { assumed_annual_rate_pct: rate, all_eligible_deposits: true },
      };
    }
    if (scenarioType === "inflation_real_value") {
      const pct = normalizeDecimalInput(inflationPct, false);
      if (pct == null) return null;
      return { inflation_real_value: { annual_inflation_pct: pct } };
    }
    if (scenarioType === "fx_translation_shock") {
      const pct = normalizeDecimalInput(fxPct, true);
      if (fxCurrency.trim() === "" || pct == null) return null;
      return {
        fx_translation_shock: {
          target_currency: fxCurrency.trim().toUpperCase(),
          reporting_value_change_pct: pct,
        },
      };
    }
    return null;
  }, [depositRate, equityPct, fxCurrency, fxPct, inflationPct, scenarioType]);

  async function runScenario() {
    if (selectedMonthId == null || !canCalculate) return;
    const shock = buildShock();
    if (!shock) return;
    requestSeqRef.current += 1;
    const seq = requestSeqRef.current;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setRunning(true);
    setResultError(null);
    setResultErrorCode(null);
    setExportNotice(null);
    try {
      const evaluation = await evaluateScenarioLab(selectedMonthId, shock, controller.signal);
      if (seq !== requestSeqRef.current || controller.signal.aborted) return;
      setResult(evaluation);
    } catch (cause) {
      if (seq !== requestSeqRef.current || controller.signal.aborted) return;
      setResultError(formatApiError(cause));
      setResultErrorCode(cause instanceof ApiClientError ? cause.code : null);
    } finally {
      if (seq === requestSeqRef.current) {
        abortRef.current = null;
        setRunning(false);
      }
    }
  }

  async function runExport() {
    if (selectedMonthId == null || result == null || downloading) return;
    const shock = buildShock();
    if (!shock) return;
    setDownloading(true);
    setResultError(null);
    setResultErrorCode(null);
    setExportNotice(null);
    try {
      const file: ApiDownload = await downloadScenarioLabExport(selectedMonthId, shock);
      triggerDownload(file.blob, file.filename);
      setExportNotice(`Файл ${file.filename} скачан.`);
    } catch (cause) {
      setResultError(formatApiError(cause));
      setResultErrorCode(cause instanceof ApiClientError ? cause.code : null);
    } finally {
      setDownloading(false);
    }
  }

  function changeScenario(next: ScenarioShockType) {
    if (next === scenarioType) return;
    setScenarioType(next);
    invalidateResult();
  }

  const scenarioDescription =
    SCENARIO_OPTIONS.find((option) => option.value === scenarioType)?.description ?? "";

  return (
    <section className="scenario-lab-page stack-18">
      <header className="page-header scenario-lab-page__header">
        <p className="eyebrow">Планирование</p>
        <h1>Сценарии</h1>
        <p className="page-header__description">
          Детерминированный расчёт «что если» по зафиксированному снимку месяца: один сценарий за
          раз, запуск вручную, ничего не сохраняется и не записывается в данные. Результат
          показывает базовый случай и сценарий — без прогноза рынка и без рекомендаций.
        </p>
      </header>

      <Panel label="Параметры" title="Какой сценарий считаем">
        {monthsLoading ? (
          <LoadingState description="Загружаем отчётные месяцы…" inline />
        ) : monthsError ? (
          <ErrorState
            description={monthsError}
            inline
            title="Не удалось загрузить список месяцев"
          />
        ) : months.length === 0 ? (
          <EmptyState
            description="Сначала создай хотя бы один отчётный месяц — сценарий считается по его снимку."
            inline
            title="Нет отчётных месяцев"
          />
        ) : (
          <>
            <div className="scenario-lab__controls">
              <Field htmlFor="scenario-lab-month" label="Отчётный месяц">
                <Select
                  id="scenario-lab-month"
                  onChange={(event) => {
                    const next = Number(event.target.value);
                    if (next !== selectedMonthId) {
                      setSelectedMonthId(next);
                      invalidateResult();
                    }
                  }}
                  value={selectedMonthId ?? ""}
                >
                  {sortMonths(months).map((month) => (
                    <option key={month.id} value={month.id}>
                      {formatMonth(month.year, month.month)} ·{" "}
                      {labelOf(MONTH_STATUS_LABELS, month.status)}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field htmlFor="scenario-lab-type" label="Сценарий">
                <Select
                  id="scenario-lab-type"
                  onChange={(event) => changeScenario(event.target.value as ScenarioShockType)}
                  value={scenarioType}
                >
                  {SCENARIO_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </Select>
              </Field>
            </div>

            <p className="muted tiny scenario-lab__scenario-description">{scenarioDescription}</p>

            <ScenarioParameterFields
              equityPct={equityPct}
              setEquityPct={setEquityPct}
              depositRate={depositRate}
              setDepositRate={setDepositRate}
              inflationPct={inflationPct}
              setInflationPct={setInflationPct}
              fxCurrency={fxCurrency}
              setFxCurrency={setFxCurrency}
              fxPct={fxPct}
              setFxPct={setFxPct}
              onParameterChange={invalidateResult}
              scenarioType={scenarioType}
            />

            <div className="scenario-lab__actions">
              <Button disabled={!canCalculate} onClick={() => void runScenario()} variant="primary">
                {running ? "Считаем…" : "Рассчитать сценарий"}
              </Button>
              <Button
                disabled={result == null || running || downloading}
                onClick={() => void runExport()}
              >
                {downloading ? "Скачиваем…" : "Скачать JSON"}
              </Button>
            </div>
            <p className="muted tiny scenario-lab__run-hint">
              Расчёт запускается только по кнопке. Смена месяца, сценария или параметров убирает
              старый результат до следующего запуска.
            </p>
          </>
        )}
      </Panel>

      {resultError ? (
        <div className="inline-alert inline-alert--error scenario-lab__action-error" role="alert">
          <strong>Не удалось выполнить запрос</strong>
          <span>{resultError}</span>
          {resultErrorCode ? (
            <code className="scenario-lab__error-code">код: {resultErrorCode}</code>
          ) : null}
        </div>
      ) : null}

      {exportNotice ? (
        <div className="inline-alert inline-alert--ok" role="status">
          {exportNotice}
        </div>
      ) : null}

      {result && selectedMonth ? (
        <ScenarioLabResult
          evaluation={result}
          selectedMonth={selectedMonth}
          onRetry={() => void runScenario()}
        />
      ) : null}

      {!result && !resultError && selectedMonth && !running ? (
        <div className="inline-alert scenario-lab__run-hint" role="status">
          Результат появится после нажатия «Рассчитать сценарий».
        </div>
      ) : null}
    </section>
  );
}

function ScenarioParameterFields({
  scenarioType,
  equityPct,
  setEquityPct,
  depositRate,
  setDepositRate,
  inflationPct,
  setInflationPct,
  fxCurrency,
  setFxCurrency,
  fxPct,
  setFxPct,
  onParameterChange,
}: {
  scenarioType: ScenarioShockType;
  equityPct: string;
  setEquityPct: (value: string) => void;
  depositRate: string;
  setDepositRate: (value: string) => void;
  inflationPct: string;
  setInflationPct: (value: string) => void;
  fxCurrency: string;
  setFxCurrency: (value: string) => void;
  fxPct: string;
  setFxPct: (value: string) => void;
  onParameterChange: () => void;
}) {
  if (scenarioType === "equity_drawdown") {
    return (
      <div className="scenario-lab__parameter">
        <Field htmlFor="scenario-lab-equity-pct" label="Размер просадки акций, %">
          <Input
            id="scenario-lab-equity-pct"
            inputMode="decimal"
            onChange={(event) => {
              setEquityPct(event.currentTarget.value);
              onParameterChange();
            }}
            placeholder="10"
            value={equityPct}
          />
        </Field>
        <p className="muted tiny scenario-lab__parameter-hint">
          Учитываются только позиции с типом инструмента «Акции»: без look-through и без догадок по
          остальным классам.
        </p>
      </div>
    );
  }
  if (scenarioType === "deposit_rate_assumption") {
    return (
      <div className="scenario-lab__parameter">
        <Field
          htmlFor="scenario-lab-deposit-rate"
          label="Гипотетическая годовая ставка по вкладам, %"
        >
          <Input
            id="scenario-lab-deposit-rate"
            inputMode="decimal"
            onChange={(event) => {
              setDepositRate(event.currentTarget.value);
              onParameterChange();
            }}
            placeholder="8"
            value={depositRate}
          />
        </Field>
        <p className="muted tiny scenario-lab__parameter-hint">
          Абсолютная ставка (не дельта). Применяется ко всем подходящим вкладам; тело вкладов и
          ликвидный капитал не меняются.
        </p>
      </div>
    );
  }
  if (scenarioType === "inflation_real_value") {
    return (
      <div className="scenario-lab__parameter">
        <Field htmlFor="scenario-lab-inflation-pct" label="Годовая инфляция, %">
          <Input
            id="scenario-lab-inflation-pct"
            inputMode="decimal"
            onChange={(event) => {
              setInflationPct(event.currentTarget.value);
              onParameterChange();
            }}
            placeholder="12"
            value={inflationPct}
          />
        </Field>
        <p className="muted tiny scenario-lab__parameter-hint">
          Номинальные доходы и погашения не меняются: результат показывает покупательную способность
          известных будущих потоков, а не прогноз будущего капитала.
        </p>
      </div>
    );
  }
  return (
    <div className="scenario-lab__controls">
      <Field htmlFor="scenario-lab-fx-currency" label="Валюта шока">
        <Select
          id="scenario-lab-fx-currency"
          onChange={(event) => {
            setFxCurrency(event.currentTarget.value);
            onParameterChange();
          }}
          value={fxCurrency}
        >
          {["USD", "EUR", "GBP", "CHF", "JPY", "CNY"].map((currency) => (
            <option key={currency} value={currency}>
              {currency}
            </option>
          ))}
        </Select>
      </Field>
      <Field htmlFor="scenario-lab-fx-pct" label="Изменение стоимости в отчёте, %">
        <Input
          id="scenario-lab-fx-pct"
          inputMode="decimal"
          onChange={(event) => {
            setFxPct(event.currentTarget.value);
            onParameterChange();
          }}
          placeholder="10"
          value={fxPct}
        />
      </Field>
      <p className="muted tiny scenario-lab__parameter-hint scenario-lab__parameter-hint--wide">
        Кандидаты — инструменты с валютой, отличной от валюты отчёта. Если ни одна позиция не
        совпала с валютой шока, затронутый скоуп пуст и точный эффект — 0; иначе без авторитетной
        базы пересчёта результат недоступен и не выдаётся за ноль.
      </p>
    </div>
  );
}
