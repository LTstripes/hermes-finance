# #141 Scenario Lab v1 — contract

Status: ACCEPTED contract semantics / canonical source for persistence

Workstream:

`integration/decision-support-v1`

Original workstream baseline:

`49b290df5d407fafff05a8aac6e3c081fdd8ea45`

## 1. Purpose

Scenario Lab v1 — deterministic, read-only what-if evaluator over an explicit frozen financial snapshot.

Scenario Lab:

- НЕ является market forecast;
- НЕ оценивает вероятность сценария;
- НЕ генерирует expected return;
- НЕ моделирует correlation/beta;
- НЕ предполагает recovery probability;
- НЕ прогнозирует действия пользователя;
- НЕ делает rebalancing;
- НЕ изменяет canonical financial data.

Scenario Lab отвечает только на вопрос:

> «Что получится с поддерживаемыми текущими метриками, если к известной базе детерминированно применить явно заданное пользователем предположение?»

В v1 contractually определены пять shock types:

1. `equity_drawdown`
2. `fx_translation_shock`
3. `issuer_impairment`
4. `deposit_rate_assumption`
5. `inflation_real_value`

Contractual existence shock type НЕ означает, что текущая runtime schema уже содержит данные для его точного расчёта.

При недостаточной authoritative metadata результат обязан быть `unknown` или `unavailable`, а не guessed.

---

## 2. Canonical base case

Base case формируется для явно выбранного `ReportingMonth`.

Базовая valuation date:

`ReportingMonth.snapshot_date`

Scenario Lab НЕ имеет отдельной финансовой модели.

Он обязан переиспользовать существующие canonical read semantics для:

- liquid capital;
- Risk & Allocation;
- Goals;
- passive-income metrics;
- merged future cash-flow ladder.

Нельзя повторно реализовывать эти формулы внутри Scenario Lab с отличающейся семантикой.

### 2.1 Position valuation source

Для текущей стоимости позиции Scenario Lab использует только canonical persisted:

`PositionSnapshot.market_value_kopecks`

из выбранного reporting snapshot.

Для Scenario Lab v1 запрещено:

- получать live quote;
- обращаться к provider ради обновления цены;
- заменять snapshot valuation текущей рыночной ценой;
- самостоятельно пересчитывать persisted valuation из ticker/quantity;
- использовать внешний FX lookup.

`PositionSnapshot.market_value_kopecks` является base reporting-currency value для Scenario Lab там, где соответствующий shock contract разрешает её трансформацию.

### 2.2 Base identity

Base case должен содержать как минимум:

- reporting month identifier;
- snapshot date;
- reporting month status;
- Scenario Lab contract/calculation version;
- upstream read-model/calculation versions, где применимо;
- reporting currency;
- deterministic semantic base fingerprint.

### 2.3 CLOSED / DRAFT / reopened

CLOSED month является естественно стабильной frozen base.

DRAFT или reopened month также MAY быть evaluated read-only.

Но для mutable month reproducibility относится к фактически захваченному base payload, а не к будущему состоянию базы.

Если DRAFT/reopened month позже изменён, новый run обязан получить другой base fingerprint.

Scenario Lab никогда не превращает DRAFT/reopened month в frozen canonical state.

---

## 3. Stress case

В Scenario Lab v1 один scenario содержит РОВНО ОДИН shock.

Формально:

`stressed_case = scenario_lab_v1(frozen_base_case, exactly_one_shock, contract_version)`

Shock может менять только те факты, которые его контракт явно разрешает менять.

Все остальные известные факты остаются неизменными.

Неизвестный potentially affected факт НЕЛЬЗЯ автоматически считать unaffected.

---

## 4. Applicability and support states

### 4.1 Row-level applicability

Для каждой potentially affected row применяется одно состояние:

- `applied`
- `not_applicable`
- `unknown`

#### applied

Достаточно authoritative metadata, и shock точно применим.

#### not_applicable

Authoritative metadata достаточно, чтобы доказать, что shock к row не относится.

#### unknown

Metadata недостаточно, чтобы доказать применимость или неприменимость.

`unknown` запрещено интерпретировать как `not_applicable`.

### 4.2 Metric-level support

Для aggregated metric используются существующие semantic states:

- `supported`
- `unknown`
- `unavailable`

#### supported

Полный stressed result может быть детерминированно рассчитан.

#### unknown

Есть potentially affected scope, для которого applicability или value невозможно определить из сохранённых authoritative data.

#### unavailable

Contract требует semantic/input basis, которой текущая data model вообще не предоставляет для данного расчёта.

Scenario Lab MAY показывать known-scope impact с explicit coverage.

Но если potentially affected rows имеют `unknown`, partial known-scope value НЕ может называться:

- exact stressed total;
- full portfolio stressed total;
- complete stressed metric.

Coverage и limitation должны быть видимыми.

---

## 5. Shock: equity_drawdown

### 5.1 Input

`drawdown_pct`

Decimal percentage в диапазоне:

`0 <= drawdown_pct <= 100`

Например:

`20`

означает уменьшение applicable equity market value на 20%.

### 5.2 Applicability

Scenario Lab v1 применяет equity drawdown ТОЛЬКО к позиции с authoritative:

`instrument_type = stock`

Никакие другие категории автоматически equity не считаются.

В частности НЕ считаются equity для этого shock:

- fund;
- bond;
- currency;
- gold;
- other.

Fund look-through отсутствует.

Даже если фонд экономически содержит акции, `instrument_type=fund` не подвергается v1 equity drawdown.

Если `instrument_type` отсутствует или невалиден:

row applicability = `unknown`.

### 5.3 Base valuation

Единственный разрешённый valuation source:

`PositionSnapshot.market_value_kopecks`

выбранного reporting snapshot.

Никаких live/provider quotes.

### 5.4 Formula

Для applicable stock:

`stressed_market_value = base_market_value * (1 - drawdown_pct / 100)`

Financial calculation использует Decimal semantics и canonical money rounding boundary.

### 5.5 Supported effects

При полном coverage могут быть пересчитаны:

- liquid assets;
- liquid capital;
- asset allocation;
- account allocation;
- top-position concentration;
- capital Goal current value;
- capital Goal gap;
- capital Goal progress;
- affected instrument impact.

Debts shock не затрагивает.

Liquid capital остаётся результатом canonical liquid-capital formula, только с transformed applicable position values.

### 5.6 Explicitly unchanged / unsupported relationships

Equity price drawdown НЕ означает автоматически:

- снижение dividend cash flow;
- снижение coupon cash flow;
- снижение bond redemption;
- снижение deposit income;
- изменение historical actual passive income.

Scenario Lab не предполагает фиксированный dividend yield.

Поэтому passive-income effect от equity drawdown без отдельной deterministic relationship:

`unavailable`

reason:

`no_deterministic_income_relationship`

Это НЕ является `0 income impact`.

Visible assumptions:

- explicit stock-only applicability;
- no fund look-through;
- no rebalancing;
- no dividend assumption;
- no coupon assumption;
- no tax assumption;
- no recovery/default assumption.

---

## 6. Shock: fx_translation_shock

### 6.1 Input

- `target_currency`
- `reporting_value_change_pct`

`target_currency` — explicit normalized currency identifier.

Sign convention задаётся С ТОЧКИ ЗРЕНИЯ reporting currency value.

Пример:

`target_currency = USD`

`reporting_value_change_pct = +10`

означает:

> одна и та же native USD value после shock стоит на 10% больше в reporting currency.

Отрицательное значение означает уменьшение reporting-currency value.

### 6.2 Currency tag alone is insufficient

Наличие только:

`Instrument.currency`

НЕ является достаточным основанием для exact FX revaluation.

Currency tag может определить candidate scope, но НЕ доказывает:

- полную 1:1 FX exposure;
- native position amount;
- base FX rate;
- valuation currency mechanics;
- hedge;
- synthetic currency link.

Scenario Lab не имеет права делать:

`RUB market value × 1.10`

только потому, что `Instrument.currency = USD`.

### 6.3 Exact applicability requirements

Position может быть точно FX-shocked только при наличии authoritative translation semantics, достаточной для воспроизводимого преобразования reporting value.

Например, contract/data model должна явно предоставить необходимые компоненты вроде:

- exposure / valuation currency;
- native value;
- accepted base FX reference или эквивалентную deterministic translation basis.

Конкретный upstream FX metadata contract должен быть принят отдельно.

### 6.4 Current-baseline consequence

В текущей baseline schema наличие только:

- `Instrument.currency`;
- и RUB-valued `market_value_kopecks`

НЕ позволяет выполнить exact FX translation.

Такая metric relationship:

`unavailable`

reason:

`fx_translation_basis_unavailable`

Если currency metadata отсутствует:

row applicability = `unknown`

reason:

`missing_currency`

Существующая saved RUB valuation при этом остаётся валидной base valuation.

### 6.5 Formula once authoritative basis exists

Когда accepted translation basis существует:

`stressed_fx_rate = base_fx_rate * (1 + reporting_value_change_pct / 100)`

`stressed_reporting_value = native_value * stressed_fx_rate`

Никакого live FX lookup.

### 6.6 Potential supported effects once metadata exists

При достаточной authoritative metadata FX shock MAY change:

- liquid capital;
- allocation/concentration;
- capital Goals;
- instrument impact;
- reporting-currency value future cash flows.

Future cash flow может быть FX-shocked только если сам flow имеет достаточную authoritative translation metadata.

Нельзя наследовать currency от unrelated position только по имени/issuer/ticker.

### 6.7 Forbidden inference

Нельзя выводить FX exposure из:

- issuer domicile;
- ticker;
- exchange;
- instrument name;
- company revenue geography;
- exporter status;
- gold correlation;
- synthetic economic intuition;
- assumed hedge.

---

## 7. Shock: issuer_impairment

### 7.1 Input

- canonical authoritative `issuer_id`
- `haircut_pct`
- `impact_scope`

`haircut_pct`:

`0 <= haircut_pct <= 100`

`impact_scope` обязан быть одним из:

- `capital_value`
- `future_cash_flows`
- `both`

Impact scope ОБЯЗАТЕЛЕН.

Scenario Lab никогда не трактует слово «issuer impairment» как implicit total default.

### 7.2 Applicability

Shock применяется только к exact authoritative issuer identity match.

Запрещено определять issuer по:

- name;
- ticker;
- ISIN heuristics;
- account;
- provider;
- payout description;
- notes.

### 7.3 Current-baseline consequence

В текущей baseline issuer identity для необходимых portfolio entities не persisted как canonical identity.

Следовательно issuer impairment сейчас:

`unavailable`

reason:

`issuer_not_persisted`

Это ожидаемый и корректный v1 result.

Scenario Lab НЕ должен создавать guessed issuer mapping внутри #141.

### 7.4 capital_value mode

Для issuer-linked current capital row:

`stressed_market_value = base_market_value * (1 - haircut_pct / 100)`

Future cash flows не меняются.

### 7.5 future_cash_flows mode

Current market value не меняется.

Только explicitly issuer-linked known future flows:

`stressed_flow_amount = base_flow_amount * (1 - haircut_pct / 100)`

Flow kind не меняется.

То есть отдельно сохраняются:

- coupon;
- dividend;
- interest;
- other income;
- redemption/principal.

Redemption/principal НИКОГДА не становится passive income.

### 7.6 both mode

Один выбранный пользователем haircut percentage применяется независимо к:

- issuer-linked capital value;
- issuer-linked future known cash flows.

Но результаты остаются раздельными финансовыми категориями.

### 7.7 Interpretation

Haircut — explicit uniform WHAT-IF assumption.

Это НЕ:

- probability of default;
- prediction;
- recovery probability;
- default timing;
- seniority model;
- waterfall;
- contagion;
- correlation assumption.

---

## 8. Shock: deposit_rate_assumption

### 8.1 Input

- explicit deposit target set ИЛИ explicit `all_eligible_deposits`;
- `assumed_annual_rate_pct`.

`assumed_annual_rate_pct` — абсолютная hypothetical annual rate.

Это НЕ delta.

Например:

`12`

означает hypothetical rate = 12%, а не «+12 percentage points».

### 8.2 Applicability

Shock применяется только к deposits, для которых canonical deposit semantics позволяют вычислять expected interest.

Нельзя применять его к:

- securities;
- bonds;
- equities;
- cash;
- unknown account-like assets;
- products, которые только по имени похожи на deposit.

Нельзя reverse-engineer rate из исторических interest payments.

### 8.3 Formula

Используется существующая canonical simplified deposit forecast semantics:

`expected_monthly_interest = balance * annual_rate / 12`

Для stressed case:

`stressed_expected_monthly_interest = balance * assumed_annual_rate / 12`

Principal balance не меняется.

### 8.4 Effects

Deposit-rate assumption:

UNCHANGED:

- deposit principal;
- liquid capital;
- capital allocation;
- capital Goals.

CHANGED, если canonical inputs полностью supported:

- expected monthly deposit interest;
- approximate monthly deposit-interest component будущего cash-flow ladder;
- passive-income forecast через existing canonical deposit-interest component.

### 8.5 Cash-flow calendar rule

Нельзя fabricated dated events из undated monthly deposit-interest forecast.

Существующая accepted cash-flow semantics сохраняется:

`DepositSnapshot.expected_monthly_interest_kopecks`

может оставаться approximate monthly ladder component.

Она НЕ превращается автоматически в:

- payment in 14 days;
- payment in 30 days;
- arbitrary monthly dated event.

### 8.6 Passive-income Goal

Current canonical passive-income Goal progress использует historical actual passive-income rolling average.

Следовательно hypothetical future deposit-rate assumption НЕ изменяет:

- current passive-income Goal current value;
- current passive-income Goal progress;
- current passive-income Goal gap,

если эти canonical Goal metrics основаны на historical actual rolling average.

Scenario Lab обязан различать:

- passive-income FORECAST effect — может измениться;
- current passive-income GOAL progress — остаётся canonical actual-based.

Historical actual income никогда не переписывается scenario assumption.

---

## 9. Shock: inflation_real_value

### 9.1 Nature

Inflation shock в v1 является только secondary real-value presentation.

Он НЕ мутирует nominal financial facts.

Это не forecast рыночной стоимости капитала.

### 9.2 Input

`annual_inflation_pct`

и выбранный base reporting month.

### 9.3 Convention

V1 использует явную monthly convention:

`monthly_rate = annual_inflation_pct / 12`

Для future amount на `months_ahead`:

`real_value = nominal_future_value / (1 + monthly_rate) ^ months_ahead`

`months_ahead` определяется deterministic calendar-month distance от base reporting month до month соответствующего future cash flow.

Используются Decimal semantics.

Rounding выполняется только на canonical money boundary.

Это намеренная v1 nominal monthly assumption.

Это НЕ утверждение о методологии CPI.

### 9.4 Supported outputs

Для future dated или month-known cash flows Scenario Lab может показывать:

- original nominal value;
- stressed real-value equivalent.

Income и redemption/principal остаются отдельными категориями.

### 9.5 Current capital

Current liquid capital на base date не изменяется inflation_real_value shock.

В base-period purchasing power:

`real current capital = nominal current capital`

Future purchasing power текущего капитала НЕ прогнозируется, потому что Scenario Lab v1 не имеет future capital trajectory/reinvestment contract.

Такой future-capital result:

`unavailable`

### 9.6 Goals

Scenario Lab v1 НЕ inflation-indexes Goal target automatically.

Current Goal schema не устанавливает нормативно, означает ли target:

- today's-money target;
- nominal target at target date;
- already inflation-adjusted target.

Следовательно inflation-adjusted Goal target/coverage:

`unavailable`

до отдельного Goal price-basis contract.

Нельзя самостоятельно выбирать одну из этих трактовок.

---

## 10. Output families

Scenario result должен разделять как минимум:

- `base`
- `stressed`
- `impact`
- `support`
- `assumptions`

Supported output families:

1. liquid capital;
2. allocation/concentration;
3. Goal gap/coverage/current/progress — только если canonical Goal действительно зависит от изменённой shock metric;
4. passive-income effect — только при deterministic relationship;
5. future cash-flow effect;
6. issuer/instrument impact.

Historical actual passive income никогда не превращается в hypothetical stressed actual.

---

## 11. Shock × output semantic matrix

Ниже `changed` означает: shock contract разрешает deterministic изменение при полном required metadata coverage.

`unchanged` означает: shock contract явно не меняет эту metric.

`conditional` означает: изменение возможно только при достаточной authoritative metadata / canonical deterministic relationship.

`unavailable` означает: v1 contract намеренно не определяет такую relationship.

### equity_drawdown

- liquid capital: `changed`
- allocation/concentration: `changed`
- capital Goals: `changed`
- passive-income forecast: `unavailable`, если нет отдельной deterministic income relationship
- historical passive income: `unchanged`
- future cash flow: `unchanged`
- redemption/principal: `unchanged`

### fx_translation_shock

При accepted authoritative FX translation basis:

- liquid capital: `conditional`
- allocation/concentration: `conditional`
- capital Goals: `conditional`
- passive-income forecast: `conditional` только для future income flows с sufficient FX translation metadata
- future cash flow: `conditional`
- redemption/principal: `conditional`

При текущей baseline без accepted translation basis exact stressed metrics:

`unavailable`

где соответствующий FX translation необходим.

### issuer_impairment — capital_value

- liquid capital: `changed`
- allocation/concentration: `changed`
- capital Goals: `changed`
- passive-income forecast: `unchanged`
- future cash flow: `unchanged`
- redemption/principal: `unchanged`

при наличии authoritative issuer identity.

В текущей baseline без issuer identity:

`unavailable`.

### issuer_impairment — future_cash_flows

- current liquid capital: `unchanged`
- current allocation/concentration: `unchanged`
- capital Goals: `unchanged`
- passive-income forecast: `conditional`, только через explicitly affected income flows
- future cash flow: `changed`
- redemption/principal: `changed` только для explicitly issuer-linked redemption rows

при наличии authoritative issuer identity.

### issuer_impairment — both

Комбинирует два предыдущих scope ВНУТРИ ОДНОГО issuer shock contract:

- capital metrics: `changed`
- future linked flows: `changed`
- passive-income forecast: `conditional`
- redemption/principal: `changed` separately

Это НЕ multi-shock composition.

### deposit_rate_assumption

- liquid capital: `unchanged`
- allocation/concentration: `unchanged`
- capital Goals: `unchanged`
- passive-income forecast: `changed`
- current actual-based passive-income Goal: `unchanged`
- future cash flow: `changed` только в canonical approximate monthly deposit-interest component
- redemption/principal: `unchanged`

### inflation_real_value

Nominal metrics:

- liquid capital: `unchanged`
- allocation/concentration: `unchanged`
- current Goals: `unchanged`
- nominal passive-income forecast: `unchanged`
- nominal future cash flow: `unchanged`
- nominal redemption/principal: `unchanged`

Secondary real-value presentation:

- future income real-value: `changed`
- future redemption real-value: `changed`
- future other known cash-flow real-value: `changed`
- future capital purchasing-power forecast: `unavailable`
- inflation-adjusted Goal target/coverage: `unavailable`

---

## 12. Missing data and reason semantics

Scenario Lab никогда не угадывает:

- currency;
- issuer;
- instrument type;
- rate semantics;
- FX translation basis;
- correlation;
- probability.

Examples:

Missing currency:

row applicability:

`unknown`

reason:

`missing_currency`

Currency exists but sufficient translation basis отсутствует:

metric support:

`unavailable`

reason:

`fx_translation_basis_unavailable`

Issuer identity отсутствует:

`unavailable`

reason:

`issuer_not_persisted`

Instrument type отсутствует для equity shock:

row applicability:

`unknown`

reason:

`unknown_asset_class`

Required deterministic rate semantics отсутствуют:

`unavailable`

reason:

`missing_rate_semantics`

Potentially affected flow lacks issuer/currency metadata:

row:

`unknown`

Aggregate full stressed metric не может называться exact, если эта row может изменить aggregate.

Отсутствует deterministic financial relationship:

`unavailable`

reason:

`no_deterministic_relationship`

Нельзя заменять это значением:

`impact = 0`.

---

## 13. Scenario composition

Scenario Lab v1 поддерживает РОВНО ОДИН shock на scenario.

Допускается сравнивать несколько независимых scenarios, каждый построенный от одного и того же base case.

Например:

- Scenario A = equity drawdown -20%;
- Scenario B = USD reporting value +10%.

Но один Scenario v1 НЕ может содержать одновременно equity + FX.

Combined input возвращает:

`unsupported_composition_v1`

V1 намеренно НЕ определяет:

- additive composition;
- multiplicative composition;
- shock ordering;
- correlation;
- overlapping exposure semantics;
- double-shock avoidance.

Если combined scenarios понадобятся, требуется отдельный future contract.

Нельзя молча выбрать порядок или математику комбинации в implementation #141.

---

## 14. Export and reproducibility

Scenario Lab export должен быть deterministic semantic artifact.

Он содержит как минимум:

- Scenario Lab contract/calculation version;
- reporting month;
- snapshot date;
- reporting month status;
- semantic base fingerprint;
- relevant upstream calculation/read-model versions;
- reporting currency;
- normalized shock type;
- normalized shock parameters;
- normalized target scope;
- explicit assumptions;
- base outputs;
- stressed outputs;
- impacts;
- support states;
- reason codes;
- row-level applicability;
- coverage information;
- affected canonical refs;
- financial math/rounding convention.

Financial values:

- money serialized as deterministic decimal/minor-unit representation consistent with project contracts;
- rates and percentages serialized as decimal strings;
- no binary float.

Ordering must быть stable.

`generated_at` MAY присутствовать как UX/audit metadata.

Но `generated_at` MUST NOT входить в semantic fingerprint.

Normative invariant:

> same frozen base payload + same Scenario Lab contract version + same normalized scenario input = same semantic output and same semantic fingerprint.

Если mutable DRAFT/reopened base изменён, новый base payload обязан иметь другой base fingerprint и может дать другой result.

Scenario export НЕ является canonical financial state и не должен изменять database state.

---

## 15. Acceptance examples

### Example A — clean stock drawdown

Base:

- stock market value = 1000
- deposit = 500
- no debt

Scenario:

`equity_drawdown = 20%`

Result:

- stock = 800
- deposit = 500
- liquid capital = 1300

Dividend/coupon/redemption не меняются автоматически.

Passive-income reduction НЕ выводится только из price drawdown.

### Example B — unknown asset type

Base:

- explicit stock = 1000
- position with missing instrument type = 400

Scenario:

`equity_drawdown = 20%`

Known-scope impact:

- stock impact = -200

Но potentially affected 400-position имеет unknown applicability.

Следовательно implementation НЕ может назвать:

`1200`

exact full stressed capital только потому, что unknown row была оставлена без shock.

Должен быть explicit unknown/coverage state.

### Example C — deposit rate

Base deposit:

- balance = 120000
- current annual rate = 6%

Scenario:

`assumed_annual_rate_pct = 12`

Stressed expected monthly interest:

`120000 * 0.12 / 12 = 1200`

Deposit principal остаётся 120000.

Liquid capital не меняется.

Approximate monthly ladder component может измениться.

Fabricated dated payment не создаётся.

Passive-income forecast может измениться.

Current passive-income Goal progress, основанный на historical actual rolling average, не меняется.

### Example D — issuer shock on current baseline

Scenario:

issuer X, haircut 40%, scope `both`.

Current schema не содержит authoritative canonical issuer identity.

Result:

`unavailable`

reason:

`issuer_not_persisted`

Нельзя искать X по ticker/name/ISIN heuristic.

### Example E — future issuer-capable fixture

Предположим future accepted schema содержит authoritative issuer identity.

Base:

- issuer-linked market value = 1000
- coupon = 100
- redemption principal = 1000

Scenario:

- haircut = 40%
- impact_scope = both

Result:

- market value = 600
- coupon = 60
- redemption principal = 600

Coupon остаётся income.

Redemption 600 остаётся principal/capital return.

Redemption НЕ входит в passive income.

### Example F — currency tag without translation basis

Base:

- instrument currency = USD
- market_value_kopecks = RUB 1000 equivalent
- native value absent
- accepted base FX translation basis absent

Scenario:

USD reporting value +10%.

Result:

`unavailable`

reason:

`fx_translation_basis_unavailable`

Расчёт:

`1000 × 1.10 = 1100`

только на основании currency tag ЗАПРЕЩЁН.

### Example G — inflation real-value

Base month = M0.

Known future payment через 6 calendar months.

Nominal payment = N.

Scenario:

annual inflation = 12%.

V1 monthly rate:

`1%`

Real-value equivalent:

`N / 1.01^6`

Nominal payment N остаётся неизменным.

### Example H — combined shocks

Input содержит одновременно:

- equity_drawdown;
- fx_translation_shock.

Result:

`unsupported_composition_v1`

Implementation не выбирает additive/multiplicative/order semantics.

### Example I — deterministic replay

Run 1:

- frozen base payload X
- contract version V
- normalized scenario S

Run 2:

- frozen base payload X
- contract version V
- normalized scenario S

Semantic outputs и fingerprint обязаны совпасть.

Разница `generated_at` не влияет на semantic fingerprint.

### Example J — no DB mutation

После любого Scenario Lab evaluation не изменяются:

- ReportingMonth;
- PositionSnapshot;
- DepositSnapshot;
- CashBalance;
- canonical future cash flows;
- provider data;
- actual income;
- Goals;
- other canonical financial state.

Любой Scenario Lab write path в эти данные — BLOCKER.

---

## 16. Explicit controversial decisions

Следующие решения являются намеренными v1 decisions.

### C1 — single-shock only

ACCEPT.

Combined scenarios вне v1.

### C2 — equity means explicit stock only

ACCEPT.

Fund и другие market-priced assets автоматически equity не считаются.

### C3 — Instrument.currency alone is insufficient for FX revaluation

ACCEPT.

Это намеренно консервативная semantics.

Current FX scenario может быть largely unavailable до принятия authoritative FX translation contract.

Это лучше, чем технически точная, но финансово выдуманная цифра.

### C4 — issuer impairment requires explicit impact_scope

ACCEPT.

Нельзя implicit решить, что «issuer impairment» означает одновременно падение market value, cancellation coupons и haircut redemption.

### C5 — future-flow issuer haircut

Если impact_scope включает future cash flows, выбранный haircut применяется одинаковым explicit percentage к issuer-linked known flows.

Но income и redemption/principal остаются разными output categories.

Это uniform deterministic what-if, не recovery model.

### C6 — future forecast shocks не переписывают current actual-based passive-income Goal progress

ACCEPT.

Canonical Goal semantics имеют приоритет.

### C7 — inflation is real-value view, not future-capital forecast

ACCEPT.

Future capital trajectory отсутствует.

---

## 17. Explicitly outside Scenario Lab v1

Вне scope:

- combined/multi-shock scenarios;
- Monte Carlo;
- probabilities;
- VaR;
- correlations;
- beta;
- likelihood presets;
- market forecasts;
- expected returns;
- issuer default probability;
- recovery timing;
- seniority waterfall;
- contagion;
- sector shocks;
- bond duration/rate-price modeling;
- FX beta inference;
- synthetic currency exposure inference;
- fund look-through;
- reinvestment assumptions;
- hypothetical sale tax;
- behavioral response;
- automatic rebalancing;
- provider refresh;
- network refresh;
- canonical financial writes.

Если один из этих пунктов нужен реализации, задача должна STOP + re-scope и получить отдельный contract.

---

## 18. Recommended first implementation slice after contract acceptance

Первая implementation task:

`141-A — Scenario core + equity_drawdown`

Scope:

- versioned Scenario Lab input/output DTO;
- frozen base adapter поверх existing canonical read models;
- pure single-shock evaluator;
- `equity_drawdown`;
- exact stock-only applicability;
- valuation from persisted `PositionSnapshot.market_value_kopecks`;
- row-level `applied / not_applicable / unknown`;
- stressed liquid capital;
- propagation через existing allocation/concentration semantics;
- canonical capital Goal propagation;
- deterministic export/fingerprint;
- support states;
- reason codes;
- visible assumptions.

Prefer no UI in this slice beyond strict test/debug harness if necessary.

No:

- DB schema changes;
- Scenario persistence into canonical financial data;
- issuer implementation;
- FX implementation;
- provider/network access.

Reason:

Current data already supports stock drawdown, а slice проверяет reusable Scenario Lab machinery:

- frozen base vs stress;
- applicability;
- unknown propagation;
- aggregation completeness;
- reuse canonical read models;
- deterministic serialization;
- strict read-only behavior.

Recommended later order:

1. `141-A` core + equity drawdown
2. deposit-rate assumption
3. inflation real-value view
4. FX only after accepted authoritative FX translation basis
5. issuer impairment only after authoritative issuer identity exists

---

# Accepted reviewer additions

В canonical Git document добавь следующие три уточнения, не меняя остальную семантику.

## Addition 1 — FX reporting-currency edge

В `fx_translation_shock` нормативно добавить:

если:

`target_currency == reporting_currency`

то для reporting-currency exposure:

- row applicability = `not_applicable`;
- value = `unchanged`.

Это не FX translation.

## Addition 2 — inflation same-month acceptance case

Основную inflation formula НЕ менять.

Добавить acceptance case:

при:

`months_ahead = 0`

получаем:

`real_value = nominal_value`.

## Addition 3 — all_eligible_deposits reproducibility

Если `deposit_rate_assumption.target_scope = all_eligible_deposits`:

- eligibility set определяется один раз из frozen base payload scenario;
- этот frozen eligibility set становится частью `normalized_target_scope`;
- он участвует в semantic fingerprint;
- selector НЕ переоценивается позднее против изменившейся database.
