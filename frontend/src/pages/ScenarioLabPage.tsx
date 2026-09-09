import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ApiClientError, formatApiError, type ApiDownload } from "../api/client";
import { listMonths } from "../api/months";
import {
  downloadScenarioLabExport,
  evaluateScenarioLab,
  shockTypeOf,
  type DepositEvaluation,
  type EquityEvaluation,
  type FxEvaluation,
  type InflationEvaluation,
  type ScenarioLabEvaluation,
  type ScenarioLabShock,
  type ScenarioMetricSupport,
  type ScenarioShockType,
} from "../api/scenarioLab";
import type { ReportingMonth } from "../api/types";
import {
  Badge,
  Button,
  DataValue,
  EmptyState,
  ErrorState,
  Field,
  Input,
  LoadingState,
  Panel,
  Select,
  Table,
  Td,
  Th,
} from "../components/ui";
import {
  formatDate,
  formatMoney,
  formatMoneyDelta,
  formatMonth,
  formatMonthKey,
  formatPercent,
} from "../lib/format";
import { INSTRUMENT_TYPE_LABELS, labelOf, MONTH_STATUS_LABELS } from "../lib/labels";

const FX_TRANSLATION_BASIS_UNAVAILABLE = "fx_translation_basis_unavailable";
const FX_STRESS_UNAVAILABLE_TITLE = "Недоступен точный пересчёт";
const FX_UNKNOWN_DATA_TITLE = "Нет данных для точного пересчёта";
const FX_EMPTY_SCOPE_TITLE = "Нет позиций в валюте шока";

const SCENARIO_OPTIONS: {
  value: ScenarioShockType;
  label: string;
  description: string;
}[] = [
  {
    value: "equity_drawdown",
    label: "Падение акций",
    description:
      "Просадка рыночной стоимости позиций с типом инструмента «Акции» на выбранный процент. Фонды не раскрываются (без look-through), купоны, дивиденды и погашения не меняются.",
  },
  {
    value: "deposit_rate_assumption",
    label: "Ставка по вкладам",
    description:
      "Гипотетическая абсолютная годовая ставка по всем подходящим вкладам. Тело вкладов и ликвидный капитал не меняются — пересчитывается только прогнозный процентный доход.",
  },
  {
    value: "inflation_real_value",
    label: "Инфляция и реальная стоимость",
    description:
      "Покупательная способность известных будущих потоков при годовой инфляции. Номинальные факты не меняются; это не прогноз будущего капитала.",
  },
  {
    value: "fx_translation_shock",
    label: "Валютный шок",
    description:
      "Изменение стоимости в отчётной валюте для инструментов с явной валютой. Валюта инструмента — только кандидатный признак: без авторитетной базы пересчёта точный результат недоступен и не выдаётся за ноль.",
  },
];

const SCENARIO_TYPE_LABELS: Record<ScenarioShockType, string> = {
  equity_drawdown: "Падение акций",
  deposit_rate_assumption: "Ставка по вкладам",
  inflation_real_value: "Инфляция и реальная стоимость",
  fx_translation_shock: "Валютный шок",
};

const SUPPORT_STATUS_LABELS: Record<string, string> = {
  supported: "Рассчитано",
  unknown: "Неизвестно",
  unavailable: "Недоступно",
};

const APPLICABILITY_LABELS: Record<string, string> = {
  applied: "Учтено",
  not_applicable: "Не применимо",
  unknown: "Неизвестно",
};

const SUPPORT_TONE: Record<string, "ok" | "unknown" | "missing"> = {
  supported: "ok",
  unknown: "unknown",
  unavailable: "missing",
};

const METRIC_LABELS: Record<string, string> = {
  liquid_assets: "Ликвидные активы",
  liquid_capital_net: "Ликвидный капитал нетто",
  asset_allocation: "Распределение по классам",
  account_allocation: "Распределение по счетам",
  top_positions: "Крупнейшие позиции",
  capital_goals: "Капитальные цели",
  per_position: "Изменения по позициям",
  per_deposit: "Изменения по вкладам",
  passive_income_effect: "Эффект на пассивный доход",
  passive_income_goal: "Цель пассивного дохода",
  forecast_passive_income: "Прогноз пассивного дохода",
  future_cash_flow_ladder: "Календарь будущих потоков",
  future_cash_flows: "Будущие потоки",
  historical_actual_passive_income: "Фактический пассивный доход (история)",
  deposit_interest: "Проценты по вкладам",
  other_capital_income: "Прочий капитальный доход",
  dividends: "Дивиденды",
  coupons: "Купоны",
  redemption: "Погашения",
  debts: "Долги",
  current_capital_real_value: "Текущий капитал в ценах базы",
  future_capital_purchasing_power: "Покупательная способность будущего капитала",
  future_income_real_value: "Реальная стоимость будущего дохода",
  future_redemption_real_value: "Реальная стоимость будущих погашений",
  future_total_cash_flow_real_value: "Реальная стоимость будущих потоков",
  inflation_adjusted_goal_coverage: "Покрытие цели с учётом инфляции",
};

const REASON_LABELS: Record<string, string> = {
  fx_translation_basis_unavailable:
    "Нет авторитетной базы валютного пересчёта: точный стресс-результат не рассчитывается",
  missing_currency: "Валюта инструмента отсутствует или некорректна",
  instrument_type_not_authoritative:
    "Тип инструмента — не авторитетный признак акций (без look-through в фонды)",
  no_deterministic_income_relationship: "У сценария нет детерминированной связи с этим доходом",
  no_fund_lookthrough: "Фонды не раскрываются до акций (без look-through)",
  no_future_capital_trajectory: "Траектория будущего капитала не моделируется",
  goal_price_basis_not_defined: "Для цели не задана ценовая база",
  no_live_fx_lookup: "Живой валютный курс не запрашивается",
  no_inferred_fx_exposure: "Валютная экспозиция не достраивается по косвенным признакам",
  no_hedge_inference: "Хеджирование не предполагается",
  no_ticker_name_issuer_domicile_inference: "Эмитент и страна не выводятся из тикера или названия",
};

const ASSUMPTION_LABELS: Record<string, string> = {
  dividends_unchanged: "Дивиденды не меняются",
  coupons_unchanged: "Купоны не меняются",
  redemption_unchanged: "Погашения не меняются",
  deposit_income_unchanged: "Процентный доход по вкладам не меняется",
  other_capital_income_unchanged: "Прочий капитальный доход не меняется",
  future_cash_flow_rows_unchanged: "Строки будущих потоков не меняются",
  no_fund_lookthrough: "Фонды не раскрываются (без look-through)",
  no_fx: "Валютный пересчёт не выполняется",
  no_probabilistic_forecast: "Вероятностный прогноз не строится",
  principal_unchanged: "Тело вкладов не меняется",
  liquid_capital_unchanged: "Ликвидный капитал не меняется",
  allocation_unchanged: "Распределение не меняется",
  capital_goals_unchanged: "Капитальные цели не меняются",
  historical_actual_income_unchanged: "Фактический доход (история) не меняется",
  current_actual_based_goal_unchanged: "Текущая цель на основе факта не меняется",
  no_fabricated_deposit_dates: "Дат по вкладам не выдумывается",
  no_reinvestment_assumption: "Реинвестирование не предполагается",
  no_tax_assumption: "Налоги не пересчитываются",
  no_provider_network_access: "Сетевые провайдеры не вызываются",
  no_provider_network: "Сетевые провайдеры не вызываются",
  nominal_values_unchanged: "Номинальные факты не меняются",
  nominal_forecast_unchanged: "Номинальный прогноз не меняется",
  nominal_cash_flows_unchanged: "Номинальные потоки не меняются",
  future_income_real_value_changed: "Меняется реальная стоимость будущего дохода",
  future_redemption_real_value_changed: "Меняется реальная стоимость будущих погашений",
  future_total_cash_flow_real_value_changed: "Меняется реальная стоимость будущих потоков",
  future_capital_purchasing_power_unavailable:
    "Покупательная способность будущего капитала недоступна",
  inflation_adjusted_goal_unavailable: "Цель с учётом инфляции недоступна",
  v1_monthly_inflation_convention: "Месячная инфляция v1 = годовая ÷ 12, дисконт по месяцам вперёд",
  no_future_capital_trajectory: "Траектория будущего капитала не моделируется",
  no_goal_price_basis: "Для цели нет ценовой базы",
  no_live_fx_lookup: "Живой валютный курс не запрашивается",
  no_inferred_fx_exposure: "Валютная экспозиция не достраивается",
  no_hedge_inference: "Хеджирование не предполагается",
  no_ticker_name_issuer_domicile_inference: "Эмитент и страна не выводятся из тикера или названия",
};

function sortMonths(months: ReportingMonth[]): ReportingMonth[] {
  return [...months].sort((a, b) => b.year - a.year || b.month - a.month || b.id - a.id);
}

function defaultMonth(months: ReportingMonth[]): ReportingMonth | null {
  const sorted = sortMonths(months);
  return sorted.find((month) => month.status === "closed") ?? sorted[0] ?? null;
}

/** Normalize an owner-typed percent/rate: "10,5" → "10.5". Returns null when not a decimal string. No financial caps here. */
function normalizeDecimalInput(raw: string, allowSigned: boolean): string | null {
  const value = raw.trim().replace(/\s/g, "").replace(",", ".");
  if (value === "" || value === "." || value === "-." || value === "-") return null;
  const pattern = allowSigned ? /^-?\d+(\.\d+)?$/ : /^\d+(\.\d+)?$/;
  if (!pattern.test(value)) return null;
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return null;
  return value;
}

function isWithinRange(value: string | null, max: number): boolean {
  if (value == null) return false;
  const numeric = Number(value);
  return Number.isFinite(numeric) && numeric >= 0 && numeric <= max;
}

function isAtLeast(value: string | null, min: number): boolean {
  if (value == null) return false;
  const numeric = Number(value);
  return Number.isFinite(numeric) && numeric >= min;
}

function parseMoneyOrNull(value: unknown): string | null {
  return typeof value === "string" && value.trim() !== "" ? value : null;
}

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.style.display = "none";
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
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

function ScenarioLabResult({
  evaluation,
  selectedMonth,
  onRetry,
}: {
  evaluation: ScenarioLabEvaluation;
  selectedMonth: ReportingMonth;
  onRetry: () => void;
}) {
  const shockType = shockTypeOf(evaluation);
  const reportingMonth = evaluation.reporting_month;
  const scenario = SCENARIO_TYPE_LABELS[shockType] ?? shockType;

  return (
    <>
      <section aria-label={`Результат сценария ${scenario}`} className="scenario-lab__result">
        <div className="scenario-lab__result-heading">
          <div>
            <p className="panel__label">Результат</p>
            <h2>
              {formatMonth(reportingMonth.year, reportingMonth.month)} · {scenario}
            </h2>
          </div>
          <div className="scenario-lab__result-actions">
            <Button onClick={onRetry} size="sm" variant="ghost">
              Пересчитать
            </Button>
          </div>
        </div>
        <p className="muted tiny scenario-lab__result-asof">
          {formatMonth(reportingMonth.year, reportingMonth.month)} ·{" "}
          {labelOf(MONTH_STATUS_LABELS, reportingMonth.status)} · снимок{" "}
          {formatDate(reportingMonth.snapshot_date)} · {humanShockInput(evaluation)}
        </p>

        <details className="scenario-lab__fingerprints">
          <summary>Идентификаторы расчёта</summary>
          <dl>
            <div>
              <dt>База</dt>
              <dd>
                <code>{evaluation.base_fingerprint}</code>
              </dd>
            </div>
            <div>
              <dt>Сценарий</dt>
              <dd>
                <code>{evaluation.semantic_fingerprint}</code>
              </dd>
            </div>
          </dl>
          <p className="muted tiny">
            Отпечаток не меняется от времени генерации: одинаковый снимок и одинаковый
            нормализованный вход дают одинаковый результат.
          </p>
        </details>
      </section>

      <BaseScenarioSummary evaluation={evaluation} selectedMonth={selectedMonth} />
      <ScenarioDetail evaluation={evaluation} />
      <SupportPanel evaluation={evaluation} />
      <AssumptionsPanel evaluation={evaluation} />
    </>
  );
}

function humanShockInput(evaluation: ScenarioLabEvaluation): string {
  const input = evaluation.normalized_shock_input;
  if (input.shock_type === "equity_drawdown") {
    return `просадка ${formatPercent(input.drawdown_pct)}`;
  }
  if (input.shock_type === "deposit_rate_assumption") {
    return `ставка ${formatPercent(input.assumed_annual_rate_pct)} годовых · все подходящие вклады`;
  }
  if (input.shock_type === "inflation_real_value") {
    return `инфляция ${formatPercent(input.annual_inflation_pct)} годовых`;
  }
  if (input.shock_type === "fx_translation_shock") {
    return `${input.target_currency} · изменение стоимости ${formatPercent(
      input.reporting_value_change_pct,
    )}`;
  }
  return "";
}

function BaseScenarioSummary({
  evaluation,
  selectedMonth,
}: {
  evaluation: ScenarioLabEvaluation;
  selectedMonth: ReportingMonth;
}) {
  const shockType = shockTypeOf(evaluation);
  const liquidSupport = metricSupportFor(evaluation, "liquid_assets");
  const stressedAvailable = liquidSupport?.status !== "unavailable";

  return (
    <Panel label="Базовый случай против сценария" title="Ключевые метрики">
      <div className="scenario-lab__summary-grid">
        <DataValue
          label="Отчётный месяц"
          meta={labelOf(MONTH_STATUS_LABELS, selectedMonth.status)}
          value={formatMonth(selectedMonth.year, selectedMonth.month)}
        />
        <DataValue
          label="Ликвидные активы · база"
          meta={!stressedAvailable ? "точный стресс-пересчёт недоступен" : undefined}
          value={formatMoney(moneyStringOf(evaluation.base, "liquid_assets"))}
        />
        {stressedAvailable ? (
          <DataValue
            label="Ликвидные активы · сценарий"
            value={formatMoney(moneyStringOf(evaluation.stressed, "liquid_assets"))}
          />
        ) : null}
        <DataValue
          label="Ликвидный капитал · база"
          value={formatMoney(moneyStringOf(evaluation.base, "liquid_capital_net"))}
        />
        {stressedAvailable ? (
          <DataValue
            label="Ликвидный капитал · сценарий"
            value={formatMoney(moneyStringOf(evaluation.stressed, "liquid_capital_net"))}
          />
        ) : null}
        {stressedAvailable &&
        (shockType === "deposit_rate_assumption" || shockType === "inflation_real_value") ? (
          <DataValue
            label="Прогноз пассивного дохода · месяц"
            meta={passiveIncomeMeta(evaluation)}
            value={`${formatMoney(forecastMonthly(evaluation.base))} → ${formatMoney(
              forecastMonthly(evaluation.stressed),
            )}`}
          />
        ) : null}
        {stressedAvailable ? <ImpactSummary evaluation={evaluation} /> : null}
      </div>
    </Panel>
  );
}

function passiveIncomeMeta(evaluation: ScenarioLabEvaluation): string | undefined {
  const support = metricSupportFor(evaluation, "forecast_passive_income");
  if (!support) return undefined;
  if (support.status === "supported") {
    return "прогноз по известным данным";
  }
  return supportReasonsText(support);
}

function ImpactSummary({ evaluation }: { evaluation: ScenarioLabEvaluation }) {
  const shockType = shockTypeOf(evaluation);
  const impact = evaluation.impact;
  if (shockType === "deposit_rate_assumption") {
    return (
      <>
        <DataValue
          label="Проценты по вкладам · месяц"
          value={formatMoneyDelta(moneyDeltaOf(impact, "monthly_interest_delta"))}
        />
        <DataValue
          label="Проценты по вкладам · год"
          value={formatMoneyDelta(moneyDeltaOf(impact, "annual_deposit_interest_delta"))}
        />
        <DataValue
          label="Прогноз пассивного дохода · год"
          value={formatMoneyDelta(moneyDeltaOf(impact, "forecast_annual_total_delta"))}
        />
        <DataValue
          label="Ликвидный капитал"
          meta="тело вкладов не меняется"
          value={formatMoneyDelta(moneyDeltaOf(impact, "liquid_capital_net_delta"))}
        />
      </>
    );
  }
  if (shockType === "inflation_real_value") {
    return (
      <>
        <DataValue
          label="Будущий доход · реальная стоимость"
          value={formatMoneyDelta(moneyDeltaOf(impact, "future_income_real_value_delta"))}
        />
        <DataValue
          label="Будущие погашения · реальная стоимость"
          value={formatMoneyDelta(moneyDeltaOf(impact, "future_redemption_real_value_delta"))}
        />
        <DataValue
          label="Будущие потоки · реальная стоимость"
          value={formatMoneyDelta(moneyDeltaOf(impact, "future_total_cash_flow_real_value_delta"))}
        />
        <DataValue
          label="Ликвидный капитал"
          meta="номинал не меняется"
          value={formatMoneyDelta(moneyDeltaOf(impact, "liquid_capital_net_delta"))}
        />
      </>
    );
  }
  return (
    <>
      <DataValue
        label="Известный скоуп · влияние"
        value={formatMoneyDelta(moneyDeltaOf(impact, "known_scope_impact"))}
      />
      <DataValue
        label="Ликвидные активы"
        value={formatMoneyDelta(moneyDeltaOf(impact, "liquid_assets_delta"))}
      />
      <DataValue
        label="Ликвидный капитал"
        value={formatMoneyDelta(moneyDeltaOf(impact, "liquid_capital_net_delta"))}
      />
    </>
  );
}

function ScenarioDetail({ evaluation }: { evaluation: ScenarioLabEvaluation }) {
  const shockType = shockTypeOf(evaluation);
  if (shockType === "equity_drawdown") {
    return <EquityDrawdownDetail evaluation={evaluation as EquityEvaluation} />;
  }
  if (shockType === "deposit_rate_assumption") {
    return <DepositRateDetail evaluation={evaluation as DepositEvaluation} />;
  }
  if (shockType === "inflation_real_value") {
    return <InflationRealValueDetail evaluation={evaluation as InflationEvaluation} />;
  }
  return <FxTranslationDetail evaluation={evaluation as FxEvaluation} />;
}

function EquityDrawdownDetail({ evaluation }: { evaluation: EquityEvaluation }) {
  const coverage = evaluation.coverage;
  const names = evaluation.presentation_metadata?.instrument_names ?? {};
  const accounts = evaluation.presentation_metadata?.account_names ?? {};
  const positionIds = Object.keys(evaluation.impact.per_position).sort(
    (a, b) => Number(a) - Number(b),
  );

  return (
    <Panel label="Падение акций" title="Детали по позициям">
      <div className="scenario-lab__coverage-line">
        <span>
          Применено: <strong>{coverage.applied}</strong>
        </span>
        <span>
          Не применимо: <strong>{coverage.not_applicable}</strong>
        </span>
        <span>
          Неизвестно: <strong>{coverage.unknown}</strong>
        </span>
        <span>
          Всего позиций: <strong>{coverage.total_positions}</strong>
        </span>
      </div>
      <p className="muted tiny">
        Просадка применяется к позициям с типом инструмента «Акции». Дивиденды, купоны, погашения и
        вкладные проценты не пересчитываются.
      </p>
      <Table>
        <thead>
          <tr>
            <Th scope="col">Позиция</Th>
            <Th scope="col">Тип</Th>
            <Th numeric scope="col">
              База
            </Th>
            <Th numeric scope="col">
              Сценарий
            </Th>
            <Th numeric scope="col">
              Изменение
            </Th>
            <Th scope="col">Статус</Th>
          </tr>
        </thead>
        <tbody>
          {positionIds.map((positionId) => {
            const baseRow = evaluation.base.per_position[positionId];
            const stressedRow = evaluation.stressed.per_position[positionId];
            const impactRow = evaluation.impact.per_position[positionId];
            const instrumentName =
              baseRow && names[String(baseRow.instrument_id)]
                ? names[String(baseRow.instrument_id)]
                : `Позиция #${positionId}`;
            const accountName =
              baseRow && accounts[String(baseRow.account_id)]
                ? accounts[String(baseRow.account_id)]
                : undefined;
            return (
              <tr key={positionId}>
                <Td>
                  {instrumentName}
                  {accountName ? <span className="muted tiny"> · {accountName}</span> : null}
                </Td>
                <Td>{baseRow ? labelOf(INSTRUMENT_TYPE_LABELS, baseRow.instrument_type) : "—"}</Td>
                <Td numeric>{baseRow ? formatMoney(baseRow.market_value) : "—"}</Td>
                <Td numeric>{stressedRow ? formatMoney(stressedRow.market_value) : "—"}</Td>
                <Td numeric>
                  {impactRow ? formatMoneyDelta(impactRow.delta) : "—"}
                  {impactRow?.reason_codes && impactRow.reason_codes.length > 0 ? (
                    <span className="muted tiny"> ({supportReasonsText(impactRow)})</span>
                  ) : null}
                </Td>
                <Td>
                  {impactRow ? (
                    <Badge tone={applicabilityTone(impactRow.applicability)}>
                      {labelOf(APPLICABILITY_LABELS, impactRow.applicability)}
                    </Badge>
                  ) : (
                    "—"
                  )}
                </Td>
              </tr>
            );
          })}
        </tbody>
      </Table>
    </Panel>
  );
}

function DepositRateDetail({ evaluation }: { evaluation: DepositEvaluation }) {
  const coverage = evaluation.coverage;
  const names = evaluation.presentation_metadata?.deposit_names ?? {};
  const accounts = evaluation.presentation_metadata?.account_names ?? {};
  const depositIds = Object.keys(evaluation.impact.per_deposit).sort(
    (a, b) => Number(a) - Number(b),
  );
  const goalEffect = evaluation.stressed.passive_income_goal_effect;

  return (
    <Panel label="Ставка по вкладам" title="Пересчёт прогнозных процентов">
      <div className="scenario-lab__coverage-line">
        <span>
          Применено вкладов: <strong>{coverage.applied}</strong>
        </span>
        <span>
          Всего подходящих: <strong>{coverage.eligible_deposits}</strong>
        </span>
        {goalEffect ? (
          <span>
            Цель пассивного дохода:{" "}
            <strong>
              {goalEffect.status === "unchanged" ? "не затронута" : goalEffect.status}
            </strong>
          </span>
        ) : null}
      </div>
      <Table>
        <thead>
          <tr>
            <Th scope="col">Вклад</Th>
            <Th scope="col">Счёт</Th>
            <Th numeric scope="col">
              Тело (не меняется)
            </Th>
            <Th numeric scope="col">
              Ставка · база
            </Th>
            <Th numeric scope="col">
              Ставка · сценарий
            </Th>
            <Th numeric scope="col">
              Проценты/мес · база
            </Th>
            <Th numeric scope="col">
              Проценты/мес · сценарий
            </Th>
            <Th numeric scope="col">
              Изменение/мес
            </Th>
          </tr>
        </thead>
        <tbody>
          {depositIds.map((depositId) => {
            const baseRow = evaluation.base.per_deposit[depositId];
            const stressedRow = evaluation.stressed.per_deposit[depositId];
            const impactRow = evaluation.impact.per_deposit[depositId];
            const depositName =
              baseRow && names[String(baseRow.deposit_id)]
                ? names[String(baseRow.deposit_id)]
                : `Вклад #${depositId}`;
            const accountName =
              baseRow && accounts[String(baseRow.account_id)]
                ? accounts[String(baseRow.account_id)]
                : undefined;
            return (
              <tr key={depositId}>
                <Td>{depositName}</Td>
                <Td>{accountName ?? "—"}</Td>
                <Td numeric>{baseRow ? formatMoney(baseRow.balance) : "—"}</Td>
                <Td numeric>{baseRow ? formatPercent(baseRow.annual_rate_pct) : "—"}</Td>
                <Td numeric>{stressedRow ? formatPercent(stressedRow.annual_rate_pct) : "—"}</Td>
                <Td numeric>{baseRow ? formatMoney(baseRow.expected_monthly_interest) : "—"}</Td>
                <Td numeric>
                  {stressedRow ? formatMoney(stressedRow.expected_monthly_interest) : "—"}
                </Td>
                <Td numeric>{impactRow ? formatMoneyDelta(impactRow.delta) : "—"}</Td>
              </tr>
            );
          })}
        </tbody>
      </Table>
      <p className="muted tiny">
        Меняется только прогнозный процентный доход: тело вкладов и ликвидный капитал остаются на
        базовом уровне.
      </p>
    </Panel>
  );
}

function InflationRealValueDetail({ evaluation }: { evaluation: InflationEvaluation }) {
  const stressedRows = evaluation.stressed.cash_flow_real_value;
  const monthKeys = Object.keys(stressedRows).sort();
  const coverage = evaluation.coverage;

  return (
    <Panel label="Инфляция и реальная стоимость" title="Номинал против реальной стоимости">
      <div className="scenario-lab__coverage-line">
        <span>
          Месяцев в сетке: <strong>{coverage.applied}</strong>
        </span>
        <span>
          Горизонт: <strong>{coverage.eligible_months}</strong>
        </span>
      </div>
      <p className="muted tiny">
        Номинальные суммы строк не меняются. «Реальная стоимость» — покупательная способность этих
        сумм в ценах базового месяца при годовой инфляции{" "}
        {formatPercent(String(evaluation.normalized_shock_input.annual_inflation_pct))} (
        {evaluation.assumptions.includes("v1_monthly_inflation_convention")
          ? "помесячная ставка v1: годовая ÷ 12"
          : "помесячная ставка по конвенции v1"}
        ).
      </p>
      <Table>
        <thead>
          <tr>
            <Th scope="col">Месяц</Th>
            <Th numeric scope="col">
              Доход · номинал
            </Th>
            <Th numeric scope="col">
              Доход · реальный
            </Th>
            <Th numeric scope="col">
              Погашение · номинал
            </Th>
            <Th numeric scope="col">
              Погашение · реальное
            </Th>
            <Th numeric scope="col">
              Поток · номинал
            </Th>
            <Th numeric scope="col">
              Поток · реальный
            </Th>
            <Th numeric scope="col">
              Δ реального потока
            </Th>
          </tr>
        </thead>
        <tbody>
          {monthKeys.map((monthKey) => {
            const row = stressedRows[monthKey];
            if (!row) return null;
            return (
              <tr key={monthKey}>
                <Td>
                  {formatMonthKey(monthKey)}
                  <span className="muted tiny">
                    {" "}
                    · {row.months_ahead === 0 ? "базовый" : `${row.months_ahead} мес.`}
                  </span>
                </Td>
                <Td numeric>{formatMoney(row.nominal_income)}</Td>
                <Td numeric>{formatMoney(row.real_income)}</Td>
                <Td numeric>{formatMoney(row.nominal_redemption)}</Td>
                <Td numeric>{formatMoney(row.real_redemption)}</Td>
                <Td numeric>{formatMoney(row.nominal_total_cash_flow)}</Td>
                <Td numeric>{formatMoney(row.real_total_cash_flow)}</Td>
                <Td numeric>{formatMoneyDelta(row.total_cash_flow_delta)}</Td>
              </tr>
            );
          })}
        </tbody>
      </Table>
    </Panel>
  );
}

function FxTranslationDetail({ evaluation }: { evaluation: FxEvaluation }) {
  const coverage = evaluation.coverage;
  const names = evaluation.presentation_metadata?.instrument_names ?? {};
  const accounts = evaluation.presentation_metadata?.account_names ?? {};
  const positionIds = Object.keys(evaluation.impact.per_position).sort(
    (a, b) => Number(a) - Number(b),
  );
  // Relevant aggregate support comes from the server envelope (#334): the
  // backend maps candidate/unknown row coverage to liquid_assets (and the
  // sibling capital aggregates) as unavailable / unknown / supported.
  // Fall back across the sibling aggregates defensively; when in doubt the
  // UI fails closed to the conservative unavailable presentation (#332).
  const liquidSupport = metricSupportFor(evaluation, "liquid_assets");
  const fxSupport =
    liquidSupport ??
    metricSupportFor(evaluation, "liquid_capital_net") ??
    metricSupportFor(evaluation, "per_position");
  const fxStatus = fxSupport?.status ?? "unavailable";
  const targetCurrency = evaluation.normalized_shock_input.target_currency;

  return (
    <Panel label="Валютный шок" title="Кандидаты и доступность пересчёта">
      {fxStatus === "supported" ? (
        <div className="scenario-lab__empty-scope" role="status" aria-label={FX_EMPTY_SCOPE_TITLE}>
          <strong>{FX_EMPTY_SCOPE_TITLE}</strong>
          <p>
            Ни одна позиция не совпала с выбранной валютой {targetCurrency}: затронутый скоуп пуст,
            поэтому точный эффект сценария для этого снимка — 0, а ликвидные активы и капитал
            остаются на базовом уровне.
          </p>
        </div>
      ) : fxStatus === "unknown" ? (
        <div className="scenario-lab__limitation" role="note" aria-label={FX_UNKNOWN_DATA_TITLE}>
          <strong>{FX_UNKNOWN_DATA_TITLE}</strong>
          <p>
            По части позиций валюта отсутствует или некорректна, поэтому точный эффект в рублях
            неизвестен и не выдаётся за уверенный ноль.
          </p>
          {fxSupport && fxSupport.reason_codes.length > 0 ? (
            <span className="scenario-lab__reason-chips">
              {fxSupport.reason_codes.map((code) => (
                <code key={code}>{code}</code>
              ))}
            </span>
          ) : null}
        </div>
      ) : (
        <div
          className="scenario-lab__limitation"
          role="note"
          aria-label={FX_STRESS_UNAVAILABLE_TITLE}
        >
          <strong>{FX_STRESS_UNAVAILABLE_TITLE}</strong>
          <p>
            Валюта инструмента — только кандидатный признак. Авторитетная база валютного пересчёта
            отсутствует, поэтому точное стрессовое значение в рублях не рассчитывается и не выдаётся
            за успешный нулевой эффект.
          </p>
          {liquidSupport && liquidSupport.reason_codes.length > 0 ? (
            <span className="scenario-lab__reason-chips">
              {liquidSupport.reason_codes.map((code) => (
                <code key={code}>{code}</code>
              ))}
            </span>
          ) : null}
        </div>
      )}

      <div className="scenario-lab__coverage-line">
        <span>
          Применено: <strong>{coverage.applied}</strong>
        </span>
        <span>
          Кандидаты (валюта совпадает): <strong>{coverage.candidate_target_currency}</strong>
        </span>
        <span>
          Не применимо: <strong>{coverage.not_applicable}</strong>
        </span>
        <span>
          Всего позиций: <strong>{coverage.total_positions}</strong>
        </span>
      </div>

      <Table>
        <thead>
          <tr>
            <Th scope="col">Позиция</Th>
            <Th scope="col">Тип</Th>
            <Th numeric scope="col">
              База (без пересчёта)
            </Th>
            <Th scope="col">Статус в шоке</Th>
            <Th scope="col">Причина</Th>
          </tr>
        </thead>
        <tbody>
          {positionIds.map((positionId) => {
            const baseRow = evaluation.base.per_position[positionId];
            const impactRow = evaluation.impact.per_position[positionId];
            const instrumentName =
              baseRow && names[String(baseRow.instrument_id)]
                ? names[String(baseRow.instrument_id)]
                : `Позиция #${positionId}`;
            const accountName =
              baseRow && accounts[String(baseRow.account_id)]
                ? accounts[String(baseRow.account_id)]
                : undefined;
            return (
              <tr key={positionId}>
                <Td>
                  {instrumentName}
                  {accountName ? <span className="muted tiny"> · {accountName}</span> : null}
                </Td>
                <Td>{baseRow ? labelOf(INSTRUMENT_TYPE_LABELS, baseRow.instrument_type) : "—"}</Td>
                <Td numeric>{baseRow ? formatMoney(baseRow.market_value) : "—"}</Td>
                <Td>
                  {impactRow ? (
                    <Badge tone={applicabilityTone(impactRow.applicability)}>
                      {applicabilityLabel(impactRow.applicability, impactRow.reason_codes)}
                    </Badge>
                  ) : (
                    "—"
                  )}
                </Td>
                <Td>
                  {impactRow?.reason_codes && impactRow.reason_codes.length > 0 ? (
                    <span className="muted tiny">{supportReasonsText(impactRow)}</span>
                  ) : (
                    "—"
                  )}
                </Td>
              </tr>
            );
          })}
        </tbody>
      </Table>
    </Panel>
  );
}

function applicabilityLabel(applicability: string, reasonCodes?: string[]): string {
  if (applicability === "unknown" && reasonCodes?.includes(FX_TRANSLATION_BASIS_UNAVAILABLE)) {
    return "Кандидат · пересчёт недоступен";
  }
  return labelOf(APPLICABILITY_LABELS, applicability);
}

function applicabilityTone(applicability: string): "ok" | "unknown" | "missing" | "neutral" {
  if (applicability === "applied") return "ok";
  if (applicability === "unknown") return "unknown";
  if (applicability === "not_applicable") return "neutral";
  return "neutral";
}

function SupportPanel({ evaluation }: { evaluation: ScenarioLabEvaluation }) {
  const entries = Object.entries(evaluation.metric_support).sort(([a], [b]) =>
    metricLabel(a).localeCompare(metricLabel(b), "ru"),
  );

  return (
    <Panel label="Доступность расчёта" title="Какие метрики определены">
      <p className="muted tiny scenario-lab__support-legend">
        «Рассчитано» — точное значение по данным снимка; «Неизвестно» — данных не хватает;
        «Недоступно» — сценарий не определяет точную метрику (см. причины).
      </p>
      <Table>
        <thead>
          <tr>
            <Th scope="col">Метрика</Th>
            <Th scope="col">Статус</Th>
            <Th scope="col">Причина</Th>
          </tr>
        </thead>
        <tbody>
          {entries.map(([metricKey, support]) => (
            <tr key={metricKey}>
              <Td>{metricLabel(metricKey)}</Td>
              <Td>
                <Badge tone={SUPPORT_TONE[support.status] ?? "neutral"}>
                  {labelOf(SUPPORT_STATUS_LABELS, support.status)}
                </Badge>
              </Td>
              <Td>{supportReasonsText(support)}</Td>
            </tr>
          ))}
        </tbody>
      </Table>
    </Panel>
  );
}

function AssumptionsPanel({ evaluation }: { evaluation: ScenarioLabEvaluation }) {
  const assumptions = evaluation.assumptions;
  if (assumptions.length === 0) return null;
  return (
    <Panel label="Допущения" title="Что зафиксировано в расчёте">
      <ul className="scenario-lab__assumptions">
        {assumptions.map((assumption) => (
          <li key={assumption}>
            {labelOf(ASSUMPTION_LABELS, assumption)}
            {ASSUMPTION_LABELS[assumption] ? null : (
              <code className="scenario-lab__assumption-code"> · {assumption}</code>
            )}
          </li>
        ))}
      </ul>
      {evaluation.warnings.length > 0 ? (
        <div className="scenario-lab__warnings" role="status">
          {evaluation.warnings.map((warning) => (
            <div className="inline-alert inline-alert--warn" key={warning}>
              {warning}
            </div>
          ))}
        </div>
      ) : null}
    </Panel>
  );
}

function metricLabel(metricKey: string): string {
  return METRIC_LABELS[metricKey] ?? metricKey;
}

function metricSupportFor(
  evaluation: ScenarioLabEvaluation,
  metricKey: string,
): ScenarioMetricSupport | null {
  return evaluation.metric_support[metricKey] ?? null;
}

function supportReasonsText(
  support: { reason_codes?: readonly string[] } | null | undefined,
): string {
  if (!support?.reason_codes || support.reason_codes.length === 0) return "—";
  return support.reason_codes
    .map((code) => (REASON_LABELS[code] ? `${REASON_LABELS[code]} (${code})` : code))
    .join("; ");
}

function moneyStringOf(block: Record<string, unknown>, key: string): string | null {
  return parseMoneyOrNull(block[key]);
}

function moneyDeltaOf(block: Record<string, unknown>, key: string): string | null {
  return parseMoneyOrNull(block[key]);
}

function forecastMonthly(block: Record<string, unknown>): string | null {
  const forecast = block.forecast_passive_income as { monthly_total?: unknown } | undefined;
  if (!forecast) return null;
  return parseMoneyOrNull(forecast.monthly_total);
}
