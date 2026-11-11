import { useState } from "react";
import { SCENARIO_OPTIONS } from "./scenarioLab";
import { reasonCopy } from "../lib/reasonCopy";
import {
  shockTypeOf,
  type DepositEvaluation,
  type EquityEvaluation,
  type FxEvaluation,
  type InflationEvaluation,
  type ScenarioLabEvaluation,
  type ScenarioMetricSupport,
  type ScenarioShockType,
} from "../api/scenarioLab";
import type { ReportingMonth } from "../api/types";
import { Badge, Button, DataValue, Panel, Table, Td, Th } from "../components/ui";
import { formatMoney, formatMoneyDelta, formatMonthKey, formatPercent } from "../lib/format";
import { labelOf } from "../lib/labels";

const FX_TRANSLATION_BASIS_UNAVAILABLE = "fx_translation_basis_unavailable";
const FX_STRESS_UNAVAILABLE_TITLE = "Недоступен точный пересчёт";
const FX_UNKNOWN_DATA_TITLE = "Нет данных для точного пересчёта";
const FX_EMPTY_SCOPE_TITLE = "Нет позиций в валюте шока";

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

function parseMoneyOrNull(value: unknown): string | null {
  return typeof value === "string" && value.trim() !== "" ? value : null;
}

export function ScenarioLabResult({
  evaluation,
  selectedMonth,
  onRetry,
}: {
  evaluation: ScenarioLabEvaluation;
  selectedMonth: ReportingMonth;
  onRetry: () => void;
}) {
  const shockType = shockTypeOf(evaluation);
  const scenario = SCENARIO_TYPE_LABELS[shockType] ?? shockType;

  return (
    <>
      <section aria-label={`Результат сценария ${scenario}`} className="scenario-lab__result">
        <div className="scenario-lab__result-heading">
          <div>
            <p className="panel__label">Результат</p>
            <h2>{scenario}</h2>
          </div>
          <div className="scenario-lab__result-actions">
            <Button onClick={onRetry} size="sm" variant="ghost">
              Пересчитать
            </Button>
          </div>
        </div>
        <p className="muted tiny scenario-lab__result-asof">{humanShockInput(evaluation)}</p>
        <MainAnswer evaluation={evaluation} />
      </section>

      <BaseScenarioSummary evaluation={evaluation} selectedMonth={selectedMonth} />
      <ScenarioDetail evaluation={evaluation} />
      <details className="scenario-lab__more">
        <summary>Что сценарий не меняет · {evaluation.assumptions.length}</summary>
        <p>{SCENARIO_OPTIONS.find((option) => option.value === shockType)?.description}</p>
        <AssumptionsPanel evaluation={evaluation} />
        <SupportPanel evaluation={evaluation} />
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
      </details>
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

function MainAnswer({ evaluation }: { evaluation: ScenarioLabEvaluation }) {
  const type = shockTypeOf(evaluation);
  const support =
    metricSupportFor(evaluation, "liquid_capital_net") ??
    metricSupportFor(evaluation, "liquid_assets");
  let label = "Ликвидный капитал";
  let base = moneyStringOf(evaluation.base, "liquid_capital_net");
  let stressed =
    support?.status === "supported"
      ? moneyStringOf(evaluation.stressed, "liquid_capital_net")
      : null;
  let delta =
    support?.status === "supported"
      ? (moneyDeltaOf(evaluation.impact, "liquid_capital_net_delta") ??
        moneyDeltaOf(evaluation.impact, "liquid_capital_net"))
      : null;
  if (type === "deposit_rate_assumption") {
    label = "Прогноз пассивного дохода · месяц";
    base = forecastMonthly(evaluation.base);
    stressed = forecastMonthly(evaluation.stressed);
    delta = moneyDeltaOf(evaluation.impact, "monthly_interest_delta");
  } else if (type === "inflation_real_value") {
    const rows = (evaluation as InflationEvaluation).stressed.cash_flow_real_value;
    const key = Object.keys(rows)
      .sort()
      .find((key) => rows[key].months_ahead > 0);
    const row = key ? rows[key] : null;
    label = `Будущие потоки · ${key ? formatMonthKey(key) : "нет будущих месяцев"}`;
    base = row?.nominal_total_cash_flow ?? null;
    stressed = row?.real_total_cash_flow ?? null;
    delta = row?.total_cash_flow_delta ?? null;
  }
  return (
    <div className="scenario-lab__answer">
      <p>{label}</p>
      <div className="scenario-lab__comparison">
        <span>
          <small>Сейчас</small>
          <strong>{formatMoney(base)}</strong>
        </span>
        <span aria-hidden="true">→</span>
        <span>
          <small>В сценарии</small>
          <strong>{formatMoney(stressed)}</strong>
        </span>
      </div>
      {delta !== null ? <p className="scenario-lab__delta">{formatMoneyDelta(delta)}</p> : null}
      {stressed === null && type !== "inflation_real_value" ? (
        <p className="muted tiny">
          {support?.status === "unknown"
            ? "Нет данных для точного результата"
            : "точный стресс-пересчёт недоступен"}
        </p>
      ) : null}
    </div>
  );
}

function BaseScenarioSummary({
  evaluation,
}: {
  evaluation: ScenarioLabEvaluation;
  selectedMonth: ReportingMonth;
}) {
  const type = shockTypeOf(evaluation);
  const available = metricSupportFor(evaluation, "liquid_assets")?.status === "supported";
  return (
    <div className="scenario-lab__summary-grid">
      <DataValue
        label="Ликвидные активы · база"
        value={formatMoney(moneyStringOf(evaluation.base, "liquid_assets"))}
      />
      <DataValue
        label="Ликвидные активы · сценарий"
        value={formatMoney(available ? moneyStringOf(evaluation.stressed, "liquid_assets") : null)}
      />
      {type === "equity_drawdown" || type === "fx_translation_shock" ? (
        available ? (
          <DataValue
            label="Изменение по известным позициям"
            value={formatMoneyDelta(moneyDeltaOf(evaluation.impact, "known_scope_impact"))}
          />
        ) : null
      ) : (
        <DataValue
          label="Ликвидный капитал"
          meta={
            type === "deposit_rate_assumption" ? "тело вкладов не меняется" : "номинал не меняется"
          }
          value={formatMoney(moneyStringOf(evaluation.stressed, "liquid_capital_net"))}
        />
      )}
    </div>
  );
}

function strongestFirst<T extends { delta?: string }>(rows: Record<string, T>): string[] {
  function magnitude(key: string) {
    const raw = rows[key].delta;
    return raw && /^-?\d+(\.\d{1,2})?$/.test(raw)
      ? BigInt(raw.replace("-", "").split(".")[0] + (raw.split(".")[1] ?? "").padEnd(2, "0"))
      : null;
  }
  return Object.keys(rows).sort((a, b) => {
    const left = magnitude(a),
      right = magnitude(b);
    if (left === right) return a.localeCompare(b, "ru", { numeric: true });
    if (left === null) return 1;
    if (right === null) return -1;
    return left > right ? -1 : 1;
  });
}

function MoreRows({ count, show, onClick }: { count: number; show: boolean; onClick: () => void }) {
  return count > 5 ? (
    <Button variant="ghost" onClick={onClick}>
      {show ? "Свернуть" : `Показать все ${count}`}
    </Button>
  ) : null;
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
  const [showAll, setShowAll] = useState(false);
  const coverage = evaluation.coverage;
  const names = evaluation.presentation_metadata?.instrument_names ?? {};
  const accounts = evaluation.presentation_metadata?.account_names ?? {};
  const positionIds = strongestFirst(evaluation.impact.per_position);

  return (
    <Panel label="Падение акций" title="Что изменилось сильнее всего">
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
      <Table aria-label="Стоимость акций в сценарии">
        <thead>
          <tr>
            <Th scope="col">Позиция</Th>
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
          {positionIds.slice(0, showAll ? undefined : 5).map((positionId) => {
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
      <MoreRows count={positionIds.length} show={showAll} onClick={() => setShowAll(!showAll)} />
    </Panel>
  );
}

function DepositRateDetail({ evaluation }: { evaluation: DepositEvaluation }) {
  const [showAll, setShowAll] = useState(false);
  const coverage = evaluation.coverage;
  const names = evaluation.presentation_metadata?.deposit_names ?? {};
  const accounts = evaluation.presentation_metadata?.account_names ?? {};
  const depositIds = strongestFirst(evaluation.impact.per_deposit);
  const goalEffect = evaluation.stressed.passive_income_goal_effect;

  return (
    <Panel label="Ставка по вкладам" title="Что изменилось сильнее всего">
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
      <Table aria-label="Проценты по вкладам в сценарии">
        <thead>
          <tr>
            <Th scope="col">Вклад</Th>
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
          {depositIds.slice(0, showAll ? undefined : 5).map((depositId) => {
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
                <Td>
                  {depositName}
                  <small>{accountName ?? "—"}</small>
                  <details>
                    <summary>Тело и ставка</summary>
                    <p>Тело (не меняется): {baseRow ? formatMoney(baseRow.balance) : "—"}</p>
                    <p>
                      Ставка: {baseRow ? formatPercent(baseRow.annual_rate_pct) : "—"} →{" "}
                      {stressedRow ? formatPercent(stressedRow.annual_rate_pct) : "—"}
                    </p>
                  </details>
                </Td>
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
      <MoreRows count={depositIds.length} show={showAll} onClick={() => setShowAll(!showAll)} />
      <p className="muted tiny">
        Меняется только прогнозный процентный доход: тело вкладов и ликвидный капитал остаются на
        базовом уровне.
      </p>
    </Panel>
  );
}

function InflationRealValueDetail({ evaluation }: { evaluation: InflationEvaluation }) {
  const [showAll, setShowAll] = useState(false);
  const stressedRows = evaluation.stressed.cash_flow_real_value;
  const monthKeys = strongestFirst(
    Object.fromEntries(
      Object.entries(stressedRows).map(([key, row]) => [key, { delta: row.total_cash_flow_delta }]),
    ),
  );
  const coverage = evaluation.coverage;

  return (
    <Panel label="Инфляция и реальная стоимость" title="Что изменилось сильнее всего">
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
      <Table aria-label="Денежные потоки сценария">
        <thead>
          <tr>
            <Th scope="col">Месяц</Th>
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
          {monthKeys.slice(0, showAll ? undefined : 5).map((monthKey) => {
            const row = stressedRows[monthKey];
            if (!row) return null;
            return (
              <tr key={monthKey}>
                <Td>
                  {formatMonthKey(monthKey)}
                  <details>
                    <summary>Состав потока</summary>
                    <p>
                      Доход: {formatMoney(row.nominal_income)} → {formatMoney(row.real_income)}
                    </p>
                    <p>
                      Погашение: {formatMoney(row.nominal_redemption)} →{" "}
                      {formatMoney(row.real_redemption)}
                    </p>
                  </details>
                  <span className="muted tiny">
                    {" "}
                    · {row.months_ahead === 0 ? "базовый" : `${row.months_ahead} мес.`}
                  </span>
                </Td>
                <Td numeric>{formatMoney(row.nominal_total_cash_flow)}</Td>
                <Td numeric>{formatMoney(row.real_total_cash_flow)}</Td>
                <Td numeric>{formatMoneyDelta(row.total_cash_flow_delta)}</Td>
              </tr>
            );
          })}
        </tbody>
      </Table>
      <MoreRows count={monthKeys.length} show={showAll} onClick={() => setShowAll(!showAll)} />
    </Panel>
  );
}

function FxTranslationDetail({ evaluation }: { evaluation: FxEvaluation }) {
  const [showAll, setShowAll] = useState(false);
  const coverage = evaluation.coverage;
  const names = evaluation.presentation_metadata?.instrument_names ?? {};
  const accounts = evaluation.presentation_metadata?.account_names ?? {};
  const positionIds = strongestFirst(evaluation.impact.per_position);
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

      <Table aria-label="Позиции вне расчёта сценария">
        <thead>
          <tr>
            <Th scope="col">Позиция</Th>
            <Th numeric scope="col">
              База (без пересчёта)
            </Th>
            <Th scope="col">Статус в шоке</Th>
            <Th scope="col">Причина</Th>
          </tr>
        </thead>
        <tbody>
          {positionIds.slice(0, showAll ? undefined : 5).map((positionId) => {
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
      <MoreRows count={positionIds.length} show={showAll} onClick={() => setShowAll(!showAll)} />
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
      <Table aria-label="Доступность метрик сценария">
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
    .map((code) => reasonCopy(code, { surface: "scenario" }).message)
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
