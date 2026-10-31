# Product and user journeys

Current normative handbook. Historical evidence and section-by-section provenance are in the [migration map](archive/2026-10-18/MIGRATION_MAP.md); it is not required reading for ordinary work. Current delivery/installation/task state is owned by [CURRENT_STATUS](CURRENT_STATUS.md).

[1. Purpose and product boundaries](#p1) | [2. Monthly workflows](#p2) | [3. Screens and honest interpretation](#p3) | [4. Supported source families](#p4) | [5. Goals, scenarios and exports](#p5) | [6. Desktop UX](#p6)

<a id="p1"></a>
## 1. Purpose and product boundaries

Hermes Finance is a local single-user Windows application for monthly personal finance, portfolio evidence, actual income, planning and review. The normal endpoint is `127.0.0.1:8000`; the owner-facing UI is Russian. It supports desktop/laptop browser use, keyboard navigation and browser zoom. Public hosting, multi-user authentication, telemetry, trading and autonomous investment actions require a separate product decision.

The five books are the complete current handbook: product here; [financial/data contracts](ARCHITECTURE_AND_CONTRACTS.md); [development and integration](DEVELOPMENT.md); [runtime, releases and recovery](OWNER_RUNTIME_OPERATIONS.md); and [current evidence, limitations and next actions](CURRENT_STATUS.md). ADRs explain decisions, release notes describe their version, and the archive preserves provenance. Their historical next-task lists are not standing instructions.

Reporting month and snapshot date are separate identities. A month may contain a later observation date; the UI must show both. CLOSED financial facts remain immutable until explicit Reopen. Money and rates use exact backend arithmetic; frontend display is never financial authority. C2 owns definitions and formulas; no display may silently fill absent observations with zero.

<a id="p2"></a>
## 2. Monthly workflows

After XML intake, exception correction and a saved, independently reread financial
DRAFT, **«Получить и сохранить прогнозы Т-Инвест»** updates every eligible positive
native broker/IIS position in that month, across accounts. A source-list filter
does not narrow this action. Exact ISIN/UID/type/RUB discovery uses the existing
instrument mapping; ambiguities and excluded instruments stay in manual review.
The next click refreshes existing events and appends changed revisions. Calendar
GET/Reload never contacts the provider or repeats a write. Partial failures retain
successful positions and show exceptions; a lost acknowledgement requires GET
recovery before another explicit click. Coupons/dividends and principal repayment
are separate, labelled announced/forecast with personal tax/net unknown. Source
previews and actual payout reconciliation retain their existing authority.

Start with the selected reporting month and its snapshot date. Manual facts, full source documents and provider observations have different authority. The supported source flow is: unchanged original → zero-write Preview → explicit identity/mapping review or durable non-economic journal → strict financial DRAFT Apply → ACK → independent GET → readiness review → explicit Close. A journal Save preserves observations and decisions; it creates no financial positions, cash, income, flows or accepted financial receipt.

Ordinary Close of a completely unfilled manual DRAFT is blocked with
`empty_manual_month`. Saved actual month facts, including an explicit zero, make
the month nonempty; XML is optional and partial completeness remains advisory.
Notes, plans, forecasts, copied salary/expense/saving templates and source-only
Save do not fill a month. Copied templates require explicit amount confirmation,
including zero; legacy rows without provenance are not silently confirmed. A separate
intentional-empty command requires a fresh exact-period confirmation and reason,
retains audit and creates no economic facts. It waives only this empty guard;
snapshot/source/receipt guards remain mandatory. Reopen/clone require new consent.
The backend contract is in [C3](ARCHITECTURE_AND_CONTRACTS.md#c3-empty-manual-close);
the Month final-review screen offers a separate reasoned confirmation only after
server readiness confirms eligibility. It displays the exact calendar period,
month ID and snapshot date, requires an explicit checkbox and a nonblank reason,
and rereads readiness before sending. Pending intent survives Back/Reload in the
same browser session; recovery reads the receipt and current month by GET only.
Owner Test UAT remains a separate acceptance gate.

Data → Files permits source review without selecting a month. Keep every observed position, trade, Money occurrence and unsupported branch visible. The full original is indivisible: hiding one problem row does not turn 12 of 13 into a complete source. A default RUB preference is a proposal with provenance, not denomination proof. An incomplete DRAFT may retain unresolved evidence under its explicit contract; it does not waive financial or Close guards.

After a successful ACK, failed readback is recovered by GET. Never replay a financial POST merely because GET failed. If ACK itself is lost, the outcome is uncertain: resolve the same immutable intent/key and committed state. After mapping changes obtain a fresh full-original Preview. Saved decisions may survive restart; original bytes must be reselected for mutations/reparse. C3–C5 own exact rules.

The monthly workflow derives progress from authoritative read models, not a second progress ledger. It presents one next useful action, keeps optional provider stages conditional on supported accounts/data and returns native month edits to the selected Close context. Final review composes existing income, capital, budget, tax and readiness reads. Close is explicit; next-month outlook is read-only until an explicit month-create/copy action.

`/v2/close` is the normal **Month** entry: personal data first, then broker statements before dependent positions and payouts, followed by comments and final review/explicit Close. It reuses the existing editor sections, shared multi-file source-intake upload and saved-source/exception list. The ordinary **Выплаты** entry reuses saved financial DRAFT positions for one explicit T-Invest forecast action and the saved calendar, alongside accepted actual records. It does not mount a second XML upload/review. Source-only Save does not establish that financial DRAFT. Source observations and quantity-date scenarios remain accessible in **Брокерские выписки**, with payout observations in a separate disclosure; an earlier scenario date never becomes month-end EOD. Source observations are not added to accepted actual totals; unknown tax remains unknown. Manual payout forms are secondary disclosures, retaining existing records and guards. Panel/section/step links, exact month/account/ISIN/quantity date, dirty/pending recovery and Back/Reload remain supported. Each XML has its own Save/readback result; a broken file does not discard valid siblings. Month displays sources bound to that month and unbound sources overlapping its calendar period, with an explicit source-account filter; this display never binds or financially accepts an original. Source review reuses the existing identity/journal/strict-DRAFT controls, with exact originals reselected after reload. Unknown ISINs require explicit review. Account-and-period links open the existing read-only bond/monthly-return reader; source estimates do not establish financial readiness. The backend-owned DRAFT/Close/Reopen workflow and existing routes remain available.

In the period list, every compact row has the same primary **Открыть месяц** action
to `/v2/close?month=id`, including immediately after create/copy and list readback.
Copy, the separate manual editor, reports and eligible draft deletion live in the
accessible **⋯** menu. There is no duplicate **Проверить и закрыть** action.
The workspace initially shows the existing manual tiles, **Брокерские выписки**
and **Закрыть месяц**, with no work area below them. Choosing a tile opens one
inline work area; another tile replaces it. The active tile and `panel` URL agree;
Back/Reload and **← К месяцу** preserve the exact month. Existing leaf forms keep
their own Save/readback actions and APIs. Dirty changes require explicit discard;
pending writes and uncertain ACK/readback require recovery before navigation.
The statements tile provides one multi-file XML input, saved originals for the
selected period/account, exceptions, recognized instruments and quantities,
corrections, explicit T-Invest preview and the available preliminary result.
Source-only Save and strict financial Preview/Apply remain distinct internal
stages. Verified saved uploads can supply the same in-memory original to strict
review; a fresh exact original is required again after Reload.
Under the same XML upload, **Расшифровка купонов и дивидендов — PDF Альфы** accepts
one investment-report PDF for the last selected XML account set. It previews the
file's actual range, matched actual payouts, saved-history repeats/conflicts and
source account/instrument RUB results with period and annual percentage labels.
Long originals explicitly show a historical interval; new monthly originals use
their own matching closing date. The PDF supplies identity/control, never another
payment. Account-wide costs/taxes and unresolved links remain separate. This slice
allows explicit source-only Save of verified PDF links after XML Save, with
conflict preview and explicit replacement confirmation. Saved evidence is
rechecked and results recomputed after Reload in the ordinary returns readers;
stale evidence hides numbers and requires fresh Preview. Neither Save financially
applies history nor rewrites CLOSED; no old month needs Close. The ordinary **Выплаты** step keeps actual records and its existing
explicit future T-Invest action without another broker-document upload form.
Full calendar originals and historical/partial overlaps are counted separately;
historical/partial overlaps are collapsed separately. Both the month list and
saved-review selector include bound sources or unbound calendar overlaps, not
unrelated unbound months. An overlap never hides the missing full-month
original/closing EOD. Accounts from
earlier saved originals remain selectable for inspection; they do not supply this
month's closing EOD. Monthly results require exact calendar boundaries; absent
results name the required EOD dates instead of displaying zero.

The final tile composes the existing month totals, filling/readiness status and
visible blockers with explicit guarded Close. Technical provenance and extended
checks remain in **Подробнее**. A confirmed lifecycle change requires independent
workflow GET and invalidates Home/Capital/Returns/chart reads. Unknown Close ACK
keeps commands/navigation blocked with GET-only recovery. No second calculation
or progress/financial ledger is introduced. Desktop deposit rows allocate space
to names, exact amounts and actions; narrower work areas use labelled fields
without hiding data or clipping overflow.

The Month source-account filter also selects the read-only instrument list for that calendar month's EOD interval. Stocks and bonds reuse the same dated detail as the bond reader: full P&L/Modified Dietz, known partial components and conditional statement estimates remain separate, with NULL and evidence reasons preserved. An explicit missing ISIN never substitutes another instrument. The reporting snapshot date remains separate from the selected result interval and payout quantity date.

T-Invest source payout preview runs only after an explicit action for the displayed account, ISIN and quantity date. It keeps saved actuals (including later known payments), `possible_paid` candidates, countable future candidates and other unresolved rows separate, with no combined actual/forecast total or automatic paid-state mutation. It shows announced amounts with unknown personal tax, source-observed quantity and source/revision provenance. Account/ISIN/date/source changes retire the ephemeral result; Reload requires another explicit request. This read-only slice changes no Close or financial writer. See [instrument analysis](ARCHITECTURE_AND_CONTRACTS.md#c7-instrument-return-v2) and [source payout preview](ARCHITECTURE_AND_CONTRACTS.md#c9-source-payout-preview).

Month offers saved closing dates and guarded source quantities for the selected
account/ISIN, with concrete identity, settlement or conflicting-source reasons.
The default date remains the selected month's closing date: an earlier quantity
requires explicit selection and is labelled a payout scenario. Local discovery
never calls T-Invest. Selecting a historical quantity neither fabricates a monthly
return nor persists a forecast or accepted position.

<a id="p2-statement-led-target"></a>
### Statement-led monthly workflow — Owner target

The approved product direction is one ordinary monthly path. [CURRENT_STATUS](CURRENT_STATUS.md#s3) identifies what is delivered, pending and frozen; the sequence below is not a claim that every step is already connected.

1. **Manual personal facts:** salary and other personal entries, deposits/savings, credit-card debt and comments stay convenient to enter and correct.
2. **Broker statements:** upload one or several originals; show which securities were bought/sold, dates, quantities, prices/costs, new securities and actual coupons/dividends. Match known instruments and create clearly identified new ones without a separate manual catalogue task. Ask for decisions only on unresolved or conflicting facts; reuse saved mappings. The Owner default is RUB unless explicitly specified otherwise, with provenance and contradictory evidence preserved under C/#889.
3. **Future payouts:** refresh the existing T-Invest schedule by ISIN, using the relevant MyBroker-derived position quantity and its date. Reconcile statement-observed payouts with forecast events so paid events do not remain future and the same income is not counted twice. Forecast is not actual receipt; an unknown tax basis must not be labelled personal after-tax income.
4. **Recalculation:** backend read models provide the supported instrument and account/month results. The instrument view includes dated acquisition/disposal history, position/value, payouts and costs, and a supported period percentage. Reinvestment must not duplicate income. Full result, known partial components and missing evidence remain distinguishable; C owns formulas and authority.
5. **Dashboards:** present those same saved facts and forecasts without requiring another round of input. Keep correction/history access, recoverable Save/readback and explicit Close/Reopen.

The normal presentation is one month workspace with a useful instrument detail. Technical preparation and diagnostic material is secondary and opened when needed; show a short actionable explanation when missing evidence affects a result. Existing Alfa PRO integration and legacy manual/service screens are optional capabilities, not required monthly steps.

This target changes neither journal Save into financial Apply nor a forecast into confirmed income. Implement the missing statement → identity/position → forecast connection through the accepted contracts, preserving provenance, deduplication, currentness and manual facts. Do not introduce another finance ledger to hide a disconnected workflow.

The backend [saved-statement payout preview](ARCHITECTURE_AND_CONTRACTS.md#c9-source-payout-preview)
exposes dated source-observed quantity and actual-vs-schedule candidates to typed consumers.
It is provisional and read-only; an ambiguous paid match needs review and cannot count
again as a future payment. Screen integration remains a separate UI milestone.

Historical loading is part of the same source-first direction. A long report can supply dated events and outer valuations; missing intermediate month-end values require specific additional evidence. Do not demand redundant monthly exports, invent intermediate prices, or imply that accepting a long file automatically reconstructs every financial month.

<a id="p2-master_spec-931"></a>
### Manual month lifecycle and editor capabilities

<a id="p2-master_spec-931-112-список-месяцев"></a>
#### 11.2. Список месяцев

Функции:

- открыть месяц;
- создать пустой месяц;
- создать месяц на основе предыдущего;
- закрыть месяц;
- повторно открыть закрытый месяц;
- удалить только черновик с подтверждением;
- изменить дату снимка;
- увидеть источник данных.


<a id="p2-master_spec-931-113-копирование-месяца"></a>
#### 11.3. Копирование месяца

При копировании переносятся:

- счета;
- активные позиции и количества;
- депозиты и накопительные счета;
- денежные средства;
- обязательные расходы;
- плановый бюджет (§9.16);
- плановые откладывания;
- долг по кредитке, включая ставку и окончание договора;
- недвижимость, ипотека, платёж и ставка ипотеки;
- зарплатные настройки;
- цели;
- ИИС-настройки.

При копировании обнуляются:

- фактические купоны;
- дивиденды;
- полученные проценты;
- премии;
- кэшбэк;
- комиссии;
- налоги;
- пополнения;
- выводы;
- комментарии;
- фактический net, если он должен вводиться после выплаты;
- `next_due_date` долга (ближайший платёж подтверждается в новом месяце заново).

Копирование должно быть транзакционным: либо создаётся весь новый месяц, либо ничего.


<a id="p2-master_spec-931-114-редактор-месяца"></a>
#### 11.4. Редактор месяца

Редактор состоит из разделов:

1. Общие сведения.
2. Доходы.
3. Депозиты и накопительные счета.
4. Инвестиционные счета.
5. Позиции.
6. Фактические инвестиционные выплаты.
7. Прогноз будущих выплат.
8. Обязательные расходы.
9. План расходов.
10. Откладывание.
11. Долги.
12. Недвижимость и ипотека.
13. Цели.
14. Комментарии.

Каждый раздел поддерживает добавление, изменение и удаление строк.


<a id="p2-master_spec-931-115-счета"></a>
#### 11.5. Счета

Нужны статусы:

- активный;
- замороженный;
- закрытый;
- скрытый.

Замороженный счёт может входить в капитал, но не предполагает новых операций.


<a id="p2-master_spec-931-116-депозиты"></a>
#### 11.6. Депозиты

Для каждой строки:

- название;
- тип;
- баланс;
- ставка;
- прогноз процентов;
- фактически полученные проценты;
- комментарий.


<a id="p2-master_spec-931-117-инструменты-и-позиции"></a>
#### 11.7. Инструменты и позиции

Пользователь может:

- создать инструмент;
- выбрать существующий инструмент;
- указать ISIN;
- указать счёт;
- указать количество;
- среднюю цену;
- текущую цену;
- дату цены;
- добавить примечание.

Должно быть видно, рассчитана цена вручную или получена из источника.


<a id="p2-master_spec-931-118-доходы"></a>
#### 11.8. Доходы

Поля для зарплаты:

- gross;
- расчётный налог;
- расчётный net;
- фактический net;
- дата выплаты.

Премия и дополнительные доходы вводятся отдельными строками.

Кэшбэк отображается в прочих доходах/экономии и не попадает в пассивный доход.


<a id="p2-master_spec-931-119-расходы"></a>
#### 11.9. Расходы

В текущей версии ведутся обязательные расходы по категориям. Структура позволяет вести
«комфортный бюджет» без миграции всей модели.

Плановый бюджет ведётся отдельно от фактических расходов (§9.16 `planned_budget_lines`)
и не считается «бюджетом» по факту. Пустой план валиден и не блокирует закрытие месяца.


<a id="p2-master_spec-931-1110-долги"></a>
#### 11.10. Долги

Для долга владелец ведёт:

- название;
- текущий долг;
- годовую ставку / APR (пусто = неизвестно, `0` = реальная нулевая ставка);
- ближайший обязательный платёж, когда применимо;
- окончание договора, когда применимо;
- комментарий.

Даты и ставки необязательны: их отсутствие не мешает закрытию месяца.


<a id="p2-master_spec-931-1111-недвижимость"></a>
#### 11.11. Недвижимость

Поля:

- ориентировочная стоимость;
- остаток ипотеки;
- ежемесячный платёж;
- годовая процентная ставка ипотеки (пусто = неизвестно, `0` = реальная нулевая ставка);
- комментарий.

Ставка вводится владельцем вручную и не выводится из платежа или остатка. Расчёт графика
амортизации, процентов и даты окончания ипотеки в scope не входит.


<a id="p2-master_spec-931-1112-иис"></a>
#### 11.12. ИИС

Для основного ИИС показывать:

- тип ИИС;
- дату открытия;
- контрольную дату возможного закрытия;
- внесённые суммы по годам;
- выполнена ли сумма для вычета за год;
- полученные налоговые вычеты;
- планируемые вычеты;
- результат без налоговой выгоды;
- результат с полученной налоговой выгодой.


<a id="p2-master_spec-931-1113-комментарии"></a>
#### 11.13. Комментарии

Пользователь может добавлять несколько заметок к месяцу, менять порядок и удалять их.

<a id="p3"></a>
## 3. Screens and honest interpretation

Home and Capital show the selected monthly/closed-history known subtotals with coverage. An exact sum of known rows may have partial source coverage. Keep missing accounts visible and attach reasons to totals, deltas, goals and allocation; C2 owns the required-account rule. Missing calendar months are gaps, not zero points.

The primary sidebar has five destinations: Мои финансы, Капитал, Доходность,
Доход и планы, Настройки. Data, source review, exports/copies and application
settings remain reachable inside Настройки; existing deep links keep working.
On desktop the sidebar remains visible while the page scrolls, with its own
scrolling at short heights and no content overlap.

Capital places the existing allocation by asset class/account and largest
positions below its main chart, followed by property and Где лежит капитал.
The duplicated current-snapshot, changes, linked-pair and portfolio-performance
blocks are removed from this page; their data, calculations and dedicated tools
are retained. Instrument names lead directly to the standalone instrument page,
preserving the holding filter on return. Home retains the changes block and
shows readable RUB vertical axes on portfolio/passive-income graphs, including
zero and negative observations with unchanged exact tooltips. Income and plans
omits the embedded 12-month forecast and goals-progress blocks; their models and
dedicated destinations are not deleted.

Performance separates capability from data readiness and separates portfolio, account, class and instrument scopes. XIRR is annualized; TWRR is period return; statement S3 and WHAT-IF use nonannualized `rate_fraction`. Readiness explains each metric independently with its required evidence and supported next action. PERF04 is a money bridge, not a percentage return or automatic profit/loss. The instrument readers show known net payouts, comparable EOD observations and executions with partial coverage; they do not promise a complete stock/bond economic result.

Exact historical performance uses historical membership, dated cash/in-kind coverage, exact endpoints and required PRE/POST observations. Current holdings, empty XML or matching totals cannot establish missing flows. Hard reasons remain visible in hypothetical results; solver failure is distinct from missing evidence. Preparation forms protect unsaved edits, use exact identity/currentness and independently reread saved evidence. See C6–C7 for the complete metric contracts.

### Returns workspace

The ordinary `/v2/returns` entry opens **В целом** for all available history.
The main journey follows the compact account layout: result cards, a graph of
supported observations, searchable instruments and leaders. Both available broker
accounts are selected initially; a selector chooses one or both, each with its own
proved history. The broker RUB result uses eligible nonoverlapping account
components once. It is neither full portfolio P&L nor a profit floor. Never add
its instrument or payout explanations again, sum rates or average different
account periods. A changed account must select its own supported interval rather
than retain another account's inception dates. Private runtime/browser display names are
labels only and never alter source identity, mappings or financial records.

Figures and actions lead. Do not present a technical prose wall, repeated
provenance/caveats, a column of account/period codes, or empty blocks. Show known
zero and missing data distinctly; omit irrelevant zero coupon rows for stocks.
Explain a material incompleteness once in plain language, with an actionable
detail only where necessary. Different-method percentages are secondary and
retain method and exact dates; Modified Dietz is a period return, not annualized.
For a sold position its weighted capital can be small over a long reporting
window; do not silently crop that window or substitute another denominator.

All exact ISIN groups, including sold instruments and separate account contexts,
remain reachable from Returns. Entering an instrument opens its own exact-ISIN page
over all available account histories; individual account periods, rates and
local gaps remain visible through the existing detail presentation. The default
overview loads visible summaries and identity metadata only; instrument details load on
entry, and credited coupon/dividend events load on disclosure. Known paid income
is shown across included accounts, then by account, ISIN and dated operation,
without adding it again to P&L. Back/Reload preserve context. Capital provides the same entry; accepted
TWRR/XIRR and coverage diagnostics remain in their dedicated tools. Missing names stay explicit; only exact
source/catalogue metadata may name a security, without changing the Owner catalogue.

Deposits are outside this Returns UX package and remain a separate task; their
existing data and independent readers are preserved. Gold shows saved unrealized value and cost-based
percentage with its valuation date, independently of an unavailable realised or
period return. A compact manual BUY/SELL history may be confirmed inside the
existing gold instrument, using its existing monthly price field. It preserves
actual dates, grams, amount/fee basis, completeness and correction history;
supported realized, unrealized and total results remain independently visible.
Preview/confirmation records Owner evidence without rewriting CLOSED months or
broker operations. It is not a universal transaction editor, a second price
field or a deposit importer. Use one compact heading and exact quantities without
insignificant trailing zeros. Real Owner entry and visual acceptance remain
separate authorized operations.

The following selected-period capabilities remain on the lazy
`/v2/returns/account` screen; they are not hidden monthly operands in the default.

«Моя доходность» on this same screen selects brokerage, IIS, deposits/savings
and physical gold, all checked initially, over one backend-selected period.
URL/Back/Reload retain membership. Empty selection asks for a category; unknown
data do not uncheck a category or become zero. The first bounded panel shows a
separately labelled source-only partial RUB result and separate actual deposit
interest, with dates, observation coverage and concrete exclusions. It does not
add these different methods. Full basket result/rate and unsupported physical
gold period return remain unavailable; principal increases and current cost gains
are not period income. Historical brokerage/IIS subtype is never inferred from
today's account type. Existing account/class detail retains its scope. Exact
capabilities and conservative crossing exclusions are in [C7](ARCHITECTURE_AND_CONTRACTS.md#c7-returns-selected-basket).

`/v2/returns/account` retains explicit selected account/EOD dates and existing
source/accepted URL compatibility. The source-versus-accepted selector is removed
from the ordinary journey; provenance and precise financial basis remain in
explanations rather than being silently switched. CLOSED alone is not numerical
financial acceptance. The selected scope uses its existing producer and refusal
reasons; stale evidence never receives numeric fallback from a different basis.
Refresh, cancellation, errors and Back/Reload retain their selection guarantees.
The full detail still shows interval result/rate, credited coupons/dividends and
available history separately. Unknown values remain unavailable with reasons.

Monthly bars select the same period used by instruments and both top-five lists;
their paged table alternative preserves gaps, signs and zero. Instrument search,
type filters, exact sorting and on-demand trades include sold securities. Tops
compare only full instrument-v2 results with the same dates, method and basis;
positive/negative rows alone qualify, defaulting to RUB P&L with a percent toggle.
Conditional bond estimates remain in details. The overview never replaces a
whole-period result with available fragments or calculates financial returns.
Custom intervals keep unavailable account rates explicit while retaining any
independently supported dated instrument results.

Expanding an instrument reuses the shared source detail: personal RUB result for
the displayed interval, remaining quantity and reported value at a visible date,
and actual credited coupons/dividends. Closed positions remain reachable. Dated
buys/sales expose their own prices, units, amounts, NKD, commissions and settlement
dates; payments retain withholding unknowns and source references. Full results,
known components and conditional statement estimates remain distinct. Modified
Dietz is secondary, named with its actual interval and nonannualized units. The
source-history flag does not establish lifetime ownership or move the starting
boundary to the first visible buy.
Source rows without an effective instrument binding appear in a separate
disclosure with account cash, reasons and references. A name match alone does not
make them this instrument's operations; pending trades with a native binding
remain in its history with their uncounted status.

Old `/v2/capital/monthly-returns` links enter the same Returns screen, preserving
source account, ISIN and selected bond interval. A legacy bond-slice URL with no
`bond_period` means **full source history**, not the latest CLOSED month.
For a history longer than 12 months, the selected past month remains visible
in the chart/table after period changes, Back and Reload; cards and top five
use that exact same period. Explicit `diagnostics=1` retains the existing
technical workspace, opened through “Подробнее о данных”.

The diagnostic bond block on `/v2/capital/monthly-returns?diagnostics=1` shows each native
account separately: reported quantity/value and their EOD boundary, dated trades
with source price units/NKD/commission, actual coupon rows and source references.
Account, bond and month selection travel in the page URL for Back/Reload. Missing
holdings, values, NKD, gross or tax remain unknown. The server's complete economic
P&L/Modified Dietz are separate from its eligible conditional `statement_estimate`;
the latter is explicitly labelled as an estimate using statement value with
unverified valuation/NKD composition. Known coupon components are not full P&L.
Forecast stays in the existing income view. This read-only presentation grants
no financial position, Apply or Close authority and does not replace the Month
workspace or its existing guards.

<a id="p3-ui_v2_analytics_reconciliation-25"></a>
### Preserved analytics meanings

<a id="p3-ui_v2_analytics_reconciliation-25-2-semantic-guardrails"></a>
#### 2. Semantic guardrails

1. **Monetary result for a reporting month is not XIRR/TWRR or profit earned during that month.** [Dashboard result service](https://github.com/LTstripes/hermes-finance/blob/10d545882041593f37d65cf8f56b42b3a18ccebd/backend/src/hermes_finance/services/dashboard.py) and [DTO/chart](../frontend/src/ui-v2/UiV2MonthlyResultPage.tsx) combine cash income recorded in the selected month with unrealized result from open-position snapshots. The latter is not the month-over-month change in unrealized result. Keep both components separately labelled; do not rename their displayed sum to "earned this month".
2. Account results and instrument-class results are not identical scopes. Cash events without an instrument can appear by account but not by class. A cash-income-only class has no current market/cost/unrealized evidence; preserve its null values and unavailable total, not invented zeros. Class grouping here is `instrument_type`, not a new Performance asset-class taxonomy. [S3]
3. Capital delta is a change of state, not investment return. Home/Capital already label the distinction; class transfers may change rows without increasing capital. [Home](https://github.com/LTstripes/hermes-finance/blob/b05487b822252fad9d9ec7cf4410d6d96c91c8bb/frontend/src/ui-v2/UiV2Page.tsx), [Capital](https://github.com/LTstripes/hermes-finance/blob/b05487b822252fad9d9ec7cf4410d6d96c91c8bb/frontend/src/ui-v2/UiV2CapitalPage.tsx)
4. The exact monetary bridge after external flows is not P&L, "earned" or class/instrument return attribution. Preserve the existing labels, exactness gate, scope, currency and interval. [Performance detail](../frontend/src/ui-v2/UiV2CapitalPerformanceDetail.tsx), [Capital](../frontend/src/ui-v2/UiV2CapitalPage.tsx)
5. Allocation/concentration is not class performance. Risk allocation describes denominators, support, holdings and future payout/redemption concentration; #534/#535/#540 own the delivered bounded class-specific rate capability in C7. [Allocation](../frontend/src/ui-v2/UiV2CapitalAllocationPage.tsx), [Performance plan](archive/2026-10-18/docs/performance/PERFORMANCE_UI_V2_PLAN.md)
6. Current v2 Home/Capital and Income planning use latest closed data; historical facts and draft work have separate destinations. D2 below approves not recreating the old global selected-month planning mode, not deleting local factual or workflow context. The new allocation detail has its own local month selector, including drafts; the monetary-result detail selects closed months only. [Allocation detail](https://github.com/LTstripes/hermes-finance/blob/b05487b822252fad9d9ec7cf4410d6d96c91c8bb/frontend/src/ui-v2/UiV2CapitalAllocationPage.tsx), [Monthly result](https://github.com/LTstripes/hermes-finance/blob/b05487b822252fad9d9ec7cf4410d6d96c91c8bb/frontend/src/ui-v2/UiV2MonthlyResultPage.tsx)

<a id="p3-ui_v2_analytics_reconciliation-86"></a>
### Current route, period and scope rules

<a id="p3-ui_v2_analytics_reconciliation-86-5-route--period--scope-contract"></a>
#### 5. Route / period / scope contract


<a id="p3-ui_v2_analytics_reconciliation-86-home-and-capital"></a>
#### Home and Capital

- `/v2` and `/v2/capital` show latest closed data. A newer draft is workflow context, not confirmed financial truth.
- Their current `month`/`step` handling contributes to a legacy return path; it does not select a historical main-data view. Do not pretend otherwise by changing only a link label. [Home](https://github.com/LTstripes/hermes-finance/blob/b05487b822252fad9d9ec7cf4410d6d96c91c8bb/frontend/src/ui-v2/UiV2Page.tsx), [Capital](https://github.com/LTstripes/hermes-finance/blob/b05487b822252fad9d9ec7cf4410d6d96c91c8bb/frontend/src/ui-v2/UiV2CapitalPage.tsx)
- Historical closed capital facts live in `/v2/reports/:monthId`; current latest closed is deliberately handled by Home/Capital rather than duplicated in the archive. [Reports](https://github.com/LTstripes/hermes-finance/blob/b05487b822252fad9d9ec7cf4410d6d96c91c8bb/frontend/src/ui-v2/UiV2ReportPage.tsx)
- Accepted #575, #569 and Performance #531 detail routes remain available. The ordinary Capital page embeds existing allocation/concentration and removes duplicated summary panels; their source calculations and diagnostic destinations are retained. Empty Home/Capital/Income actions lead to native `/v2/close`. All are native `/v2` routes.


<a id="p3-ui_v2_analytics_reconciliation-86-income"></a>
#### Income

- `/v2/income` plans from latest closed. Its `month` selects factual passive-income breakdown, not historical/draft planning, goals or ladder. [Income](https://github.com/LTstripes/hermes-finance/blob/b05487b822252fad9d9ec7cf4410d6d96c91c8bb/frontend/src/ui-v2/UiV2IncomePage.tsx)
- D2 does not overload this parameter or remove legitimate local month/as-of selection in #552 Goals, #553 Tax/IIS, #556 Scenario Lab or #569 risk detail. Those task contracts remain unchanged.


<a id="p3-ui_v2_analytics_reconciliation-86-monetary-result-detail-delivered-by-575"></a>
#### Monetary-result detail delivered by #575

- `/v2/capital/monthly-result?month=<id>` is a local read-only closed-report selector, latest or older closed, not a global Home/Capital mode.
- No `month`: explicitly identify latest closed. Invalid/deleted/draft/reopened explicit target: explain, do not silently substitute latest closed.
- Bounded `view=accounts|classes`, correct back/refresh and native return. Exact-month links from historical Reports.
- [Registered route](https://github.com/LTstripes/hermes-finance/blob/b05487b822252fad9d9ec7cf4410d6d96c91c8bb/frontend/src/app/App.tsx) and [page](https://github.com/LTstripes/hermes-finance/blob/b05487b822252fad9d9ec7cf4410d6d96c91c8bb/frontend/src/ui-v2/UiV2MonthlyResultPage.tsx) use the existing Dashboard DTO only. No new financial formulas or class-return scope. This is accepted source on accepted implementation, not aggregate UAT.


<a id="p3-ui_v2_analytics_reconciliation-86-allocation-detail-and-iis-writes-delivered"></a>
#### Allocation detail and IIS writes delivered

- [Allocation detail](https://github.com/LTstripes/hermes-finance/blob/b05487b822252fad9d9ec7cf4410d6d96c91c8bb/frontend/src/ui-v2/UiV2CapitalAllocationPage.tsx) at `/v2/capital/allocation` has a local month selector (closed or draft) and canonical class/account allocation, top positions, payout/redemption concentration, support and exclusions. The [Capital link](https://github.com/LTstripes/hermes-finance/blob/b05487b822252fad9d9ec7cf4410d6d96c91c8bb/frontend/src/ui-v2/UiV2CapitalPage.tsx) carries the latest closed month; this does not create a global Home/Capital historical mode. Explicit invalid/duplicate month and mismatched response fail closed in this detail.
- [IIS forms](https://github.com/LTstripes/hermes-finance/blob/b05487b822252fad9d9ec7cf4410d6d96c91c8bb/frontend/src/ui-v2/UiV2IisAccountForms.tsx) are reached through [account catalogs](https://github.com/LTstripes/hermes-finance/blob/b05487b822252fad9d9ec7cf4410d6d96c91c8bb/frontend/src/ui-v2/UiV2DataCatalogsPage.tsx) with an account identifier. They write the existing profile, contribution and type-A benefit records for the account/tax year, then confirm through fresh reads. The contextual link returns to the Tax/IIS planner. They are not a second tax planner or a reporting-month write model.


<a id="p3-ui_v2_analytics_reconciliation-86-performance"></a>
#### Performance

- Accepted #529 owns exact period/scope/action contracts; accepted #531 supplies portfolio/account detail at `/v2/capital/performance` on this common tree.
- Accepted #532/#533 supply evidence preparation/capture on the same tree. Canonical CI retains `performance-real-backend.spec.ts`: unavailable -> XIRR-only -> explicitly observed synthetic PRE/POST -> TWRR, correction invalidation and stale-token rejection.
- Historical Performance periods remain required under the accepted Performance scope. D2 does not waive them.
- Bounded class-return API/UI is delivered under C7 C1–C5/no-crossing rules. It does not replace the separate monthly monetary result. Current acceptance/UAT evidence belongs in S2.


<a id="p3-ui_v2_analytics_reconciliation-86-legacy-compatibility"></a>
#### Legacy compatibility

UI v1 was removed in #905. `/v1` and the former legacy paths redirect to their native `/v2` workspaces; there is no retained second interface or legacy escape. A native route must still explain an invalid, deleted or reopened target instead of silently substituting latest closed data. [App routes](../frontend/src/app/App.tsx)


<a id="p3-ui_v2_analytics_reconciliation-86-monthly-close-wiring-accepted-and-integrated-571"></a>
#### Monthly Close wiring accepted and integrated: #571

Current [Close action map](https://github.com/LTstripes/hermes-finance/blob/b05487b822252fad9d9ec7cf4410d6d96c91c8bb/frontend/src/components/month-close/navigation.ts) defines native paths for every guided action with `monthly-close-v2` origin: editor/general/positions under `/v2/data/months/:monthId`, native Alfa/payout/reconciliation/freshness tools, final review/close at `/v2/close`, and next-month management under `/v2/data/months`. [Final-review Edit links](https://github.com/LTstripes/hermes-finance/blob/b05487b822252fad9d9ec7cf4410d6d96c91c8bb/frontend/src/components/month-close/FinalMonthReview.tsx) use the exact native month/section and return to the same Close step; CLOSED v2 review hides mutation links. [Editor](https://github.com/LTstripes/hermes-finance/blob/b05487b822252fad9d9ec7cf4410d6d96c91c8bb/frontend/src/ui-v2/UiV2MonthEditorPage.tsx) and [month management](https://github.com/LTstripes/hermes-finance/blob/b05487b822252fad9d9ec7cf4410d6d96c91c8bb/frontend/src/ui-v2/UiV2MonthsPage.tsx) retain return context, and [v2 Close](https://github.com/LTstripes/hermes-finance/blob/b05487b822252fad9d9ec7cf4410d6d96c91c8bb/frontend/src/ui-v2/UiV2ClosePage.tsx) validates workflow/final-review/outlook month identity while reusing the backend-owned lifecycle/readiness reads.

[PR #639's independent ACCEPT](https://github.com/LTstripes/hermes-finance/pull/639#issuecomment-5899002497) covers candidate `f69d2603709a06ac483875415bef6fc247c347cc`, integrated as `fb0c3b29cbf8e54df00cf7ee849a202b060de105`. Its [real-backend acceptance harness](https://github.com/LTstripes/hermes-finance/blob/b05487b822252fad9d9ec7cf4410d6d96c91c8bb/frontend/e2e/monthly-close.acceptance.ts) is now retained in required canonical CI via `playwright.config.ts --project=monthly-close`, with actual historical archive readback added on the common tree. `playwright.config.ts --project=statement` retains native statement import/apply/readback. Exact execution results belong to #572 PR/job evidence; registration/source presence alone is not a pass or Owner PASS.


<a id="p3-ui_v2_analytics_reconciliation-86-6-owner-decisions--recorded-2026-09-26"></a>
#### 6. Owner decisions — recorded 2026-09-26

Authority: [Integrator record of the actual Owner chat decision](https://github.com/LTstripes/hermes-finance/issues/570#issuecomment-5847307129). After the proposal to keep the monetary result and not reproduce the global historical/draft analytics mode, Owner replied: **«Да давай так и сделаем и идём дальше»**.

The linked note is an Integrator transcription of that instruction. Publishing through the Owner's GitHub connection does not itself constitute an independent Owner decision, review or UAT.


<a id="p3-ui_v2_analytics_reconciliation-86-d1--keep-approved-575-delivered"></a>
#### D1 — KEEP approved; #575 delivered

- Preserve monetary result by account and instrument class in a compact Capital detail, using existing Dashboard API.
- Keep closed historical factual context and separate cash-income/month versus unrealized/snapshot meanings.
- No second XIRR/TWRR implementation, no new financial calculations, no artificial portfolio/class totals.
- Keep this accepted scope; old staging/retirement checkpoints remain historical.


<a id="p3-ui_v2_analytics_reconciliation-86-d2--bounded-global-mode-reduction-approved"></a>
#### D2 — bounded global-mode reduction approved

Do not reproduce the old global arbitrary-month selector that moves the entire Dashboard/Analytics/planning picture to an historical period or draft. Consequently there is no requirement to recreate the historical/draft forecast/coverage/ladder as that global dashboard mode.

Preserve:

- latest-closed confirmed Home/Capital/planning;
- closed historical facts in Reports, factual Income history and #575;
- draft editing/readiness/validation in native editor/close;
- existing local month/as-of contracts in Goals, Tax/IIS, Scenario and risk detail;
- historical Performance periods/scopes assigned to its own stream.

This does not authorize deleting stored history, APIs, financial logic, existing routes, or any unrelated capability. No speculative new draft-preview feature is introduced. If an implementation uncovers another missing local fact/action, retain it as a bounded gap rather than treating D2 as permission to drop it.

The bounded UX decisions do not bypass D5 acceptance/integration/release gates.

<a id="p3-performance_ui_v2_contract-34"></a>
### Performance detail, periods, diagnostics and preparation UX

<a id="p3-performance_ui_v2_contract-34-3-информационная-архитектура"></a>
#### 3. Информационная архитектура


<a id="p3-performance_ui_v2_contract-34-31-обзор-capital"></a>
#### 3.1. Обзор Capital

Существующий PerformanceBlock заменяется компактным summary, не дублируется:

- «Доходность за период · TWRR»;
- «Доходность ваших вложений · XIRR, годовых»;
- даты интервала, валюта и вход «Состав расчёта»;
- один основной переход «Подробнее» либо «Проверить данные» по состоянию.

На первом экране максимум две приоритетные причины. Доступная метрика остаётся видимой независимо от другой. Нулевое значение показывается как 0%, убыток со знаком; unavailable не получает зелёный ноль. Денежный bridge убран из ряда процентных KPI и доступен только в деталях с названием «Изменение стоимости после внешних потоков» и оговоркой «Не прибыль и не доходность».


<a id="p3-performance_ui_v2_contract-34-32-delivered-detail-and-preparation-routes"></a>
#### 3.2. Delivered detail and preparation routes

- `/v2/capital/performance`: интервал, scope, две метрики, одна таблица по счетам, раскрываемые основания/методика.
- `/v2/capital/performance/data`: контекстная проверка данных и только реально реализованные действия. Действия доступны только в принятом объёме C6; отсутствие нужной authority сохраняет read-only/UNKNOWN.
- «По счетам / По классам» используют принятые ограниченные class C1–C5/no-crossing правила, без обещания доходности всех классов.

URL-параметры: `start`, `end` (ISO dates), `scope=portfolio|account`, `account_id` только для account, `view=accounts|classes` для detail. Это локальный контекст, не глобальные настройки приложения. Открытие account row сохраняет даты. Возврат из проверки восстанавливает тот же контекст.

Отсутствующие start/end допускают документированный дефолт. Частично заданные, повторённые, malformed, одинаковые или перевёрнутые даты — ошибка контекста, не тихая замена. Неизвестный/удалённый счёт и недопустимые scope/account сочетания не заменяются портфелем. Explicit dates, ставшие недоступными после reopen/delete/restore, остаются выбранными с объяснением, а не перескакивают на другой интервал.

`view=classes` использует поддержанный class scope; неподдержанный разрез объясняется как ограничение продукта, а не нехватка данных Owner. Разрешённые переходы задаются enum/параметрами; произвольный redirect URL из данных не выполняется.

Общие `frontend/src/app/App.tsx`, UiV2Entry, Capital/Reports links и навигация интегрируются одним последовательным Integrator slot совместно с #554/#555/#569/#575. Leaf UI не перетягивает соседнюю ветку. Существующие PortfolioCoverageNote и смысл partial subtotal сохраняются.


<a id="p3-performance_ui_v2_contract-34-4-период-и-состав"></a>
#### 4. Период и состав

Дефолт: последний и предыдущий закрытые отчёты с различными однозначными snapshot dates, по порядку отчётных периодов; подпись «Между отчётами» с фактическими датами. При неоднозначности/нехронологичности нет поиска другой удобной пары: предложить ручной выбор. Меньше двух границ — объяснение, без запроса несуществующего интервала.

Ручной выбор двух подтверждённых дат обязателен. Не путать reporting month с snapshot date: снимок за июль может быть датирован августом.

Пресеты 1/3/12 месяцев отсчитываются от показанной конечной snapshot date календарным сдвигом назад: сохраняется номер дня, а для последнего дня месяца сохраняется конец целевого месяца; иначе день ограничивается длиной целевого месяца. «С начала года» требует снимок 31 декабря предыдущего года. «Вся история» выбирает самую раннюю закрытую границу, не первый успешный для solver интервал. Пресет доступен только при однозначном существовании обеих требуемых дат. Нельзя подменять отсутствующую дату соседней, интерполировать или сокращать период для получения available. Пропуск промежуточного месяца не заполняется: достаточность конкретного интервала определяет backend.

Все выбранные даты передаются в canonical API без клиентского пересчёта доходности. Каждая показанная метрика обязана соответствовать запрошенным scope/account/date/currency/units. XIRR annualized, TWRR не annualized. При интервале короче 365 дней рядом с XIRR: «Приведено к году по короткому периоду; это не прогноз». Это presentation warning, не изменение значения/availability.

Состав Performance — исторический, не список текущих active accounts и не весь капитал Home. В текущем availability **нет одного готового поля «вот эти счета исторически включены в расчёт»**. На portfolio scope `scope_membership.account_ids` — это все каталожные счета, для которых проверяется история участия; туда попадает и счёт с цельной историей `include_in_returns=false`. Поэтому этот список, в том числе после вычитания `missing_or_ambiguous_account_ids`, нельзя показывать как состав доходности. `missing_or_ambiguous_account_ids` означает только пробел/неоднозначность истории участия.

Для выбранного интервала текущий авторитетный список счетов, которым нужна **денежная** проверка Performance, — `cash_boundary_coverage.account_ids`: это счета, чья effective-dated history содержит `include_in_returns=true` на пересечении с интервалом. Отдельный `in_kind_boundary_coverage.account_ids` уже и означает только счета, для которых требуется **неденежная** проверка (brokerage/IIS либо счета с position history по принятому сервису). Эти списки нельзя взаимозаменять.

«Состав расчёта» поэтому показывает три разные вещи: (1) счета денежной проверки из `cash_boundary_coverage.account_ids`; (2) отдельный, при наличии, список счетов неденежной проверки из `in_kind_boundary_coverage.account_ids`; (3) состояние проверки истории участия, где `scope_membership.account_ids` — именно проверяемый каталог, а `missing_or_ambiguous_account_ids` — проблемные identity. До появления отдельного canonical included-set нельзя переименовывать membership `account_ids` в «включённые счета». Для названий допустим lookup всех accounts, но не реконструкция membership из имён/текущих флагов. Исчезнувшее название не разрешает подменить identity.

В таблице счетов rates не суммируются и не усредняются. У каждой строки свои final availability/quality при одинаковом запрошенном интервале; доступные отдельные счета не делают итог портфеля доступным. Отсутствие одного ответа не прячется за сообщением «все счета проверены».


<a id="p3-performance_ui_v2_contract-34-5-диагностика-и-приоритеты"></a>
#### 5. Диагностика и приоритеты

Источник причин — точные canonical reason codes плюс подтверждающие вложенные evidence fields. `code.includes("flow")` запрещён для нового mapping. Одному code могут соответствовать несколько подтверждённых причин; без нужных деталей выводится общее честное объяснение, не выдуманные счёт/дата/число операций.

Приоритет summary: (1) некорректный контекст/транспортный сбой, (2) исходные границы и membership, (3) cash/in-kind history/legacy/transfer, (4) наблюдения и валюта, (5) solver/unsupported. Приоритет не удаляет остальных причин из details и не блокирует независимо доступную метрику. Одинаковый blocker группируется между метриками с пометками XIRR/TWRR.

В следующей таблице `NC_` обозначает точный префикс `not_computable_`, а не поиск подстроки. Коды полностью определены в canonical domain/API; будущий неизвестный code получает нейтральный fallback.

| Code + подтверждающее evidence | Человеческий смысл / место проверки | Action и проверка результата |
| --- | --- | --- |
| `NC_opening_valuation_missing`, `NC_closing_valuation_missing`; соответствующая boundary | Нет однозначной подтверждённой оценки на выбранную дату. Не сообщать «месяц отсутствует», если причина может быть неоднозначностью. | Выбрать даты или открыть существующий month ID из boundary. Только после исправления/закрытия перечитать boundary и final metrics. |
| `NC_reporting_month_not_closed`, `NC_snapshot_date_missing`, `NC_unsupported_position_valuation`; component IDs, если есть | Отчёт ещё не закрыт, дата/оценка не подтверждена. | Проверить конкретный отчёт через поддержанный month editor/close. Не закрывать автоматически и не обещать, что одного close достаточно. |
| `NC_scope_membership_history_missing`; missing/ambiguous account IDs | Не подтверждён исторический состав за интервал. | Details показывают scope и счета. Использовать принятый finite membership writer C6; текущий include flag не является исправлением исторической записи. |
| `NC_scope_membership_changed` | Состав менялся; текущий контракт не подтверждает расчёт этого интервала. | Показать имеющееся evidence; допустим явный ручной выбор другого интервала. Не переписывать историю ради расчёта. |
| `NC_scope_cash_unclassified`, `NC_scope_coverage_incomplete`; boundary components | Не подтверждены принадлежность денег или компоненты выбранного scope. | Открыть нужный month/component только при подтверждённом ID; иначе section-level проверка. Не использовать capital-source coverage как замену Performance gate. |
| `NC_external_flows_incomplete` + cash coverage missing IDs | Нет подтверждения полноты истории денежных пересечений у указанных счетов. | #532: известные canonical операции → проверка Owner → явный POST/PATCH cash coverage → новые reads. Отсутствие строк не доказывает нулевую активность. |
| Тот же code + `legacy_unclassified_flow_ids` | Есть legacy операции, которые нельзя автоматически использовать в расчёте. | Показать именно эти записи и canonical crossings. Не удалять legacy evidence и не конвертировать gross/net эвристикой. Отсутствующий safe reconciliation path обозначить отдельно. |
| Тот же code без достаточной детализации | Полнота/классификация внешних потоков не подтверждена; точная причина не локализована. | Read-only details и общая проверка ledger. Не утверждать, что нужно добавить определённое пополнение или просто поставить complete. |
| `NC_transfer_identity_unresolved`, `NC_transfer_reconciliation_incomplete`; flow/link IDs | Перевод не связан/не сверён по существующим правилам. | Canonical accepted transfer-link/evidence path in C6. Broker reconciliation page не является его заменой; никаких residual fees. |
| `NC_transfer_in_transit_unvalued` | Нет принятой оценки денег в пути. | Показать ограничение и имеющиеся факты; не обещать «связать перевод» как гарантированное исправление стоимости в пути. |
| `NC_in_kind_boundary_coverage_unknown`; missing account IDs | Не проверена история неденежных перемещений. | #532: отдельная проверка/явное attestation через существующий in-kind coverage API; не выводить его из cash coverage. |
| `NC_in_kind_movement_unvalued`; known movements | Известно неденежное перемещение, но его стоимость для Performance не подтверждена. | Показать факт и ограничение. Ни complete, ни ввод cash-flow вместо бумаг не снимают его. Новая оценочная семантика вне #532. |
| `NC_valuation_boundary_missing`; flow/group/дата/PRE/POST из evidence | Нет полного подтверждённого наблюдения до/после операции; старое evidence также могло утратить пригодность. | #533 accepted capture: фактическое observation + provenance и current signature. Не утверждать «устарело», если API не отличает это от отсутствия. |
| `NC_valuation_boundary_order_unknown` | Порядок относительно потока/группы не подтверждён. | Только явная принятая relation/group; не сортировка по ID или условное начало дня. Для endpoint flows это может блокировать не только TWRR: следовать final metric reasons. |
| `NC_currency_conversion_incomplete` | Нет принятого перевода в валюту расчёта на нужную дату. | Сообщить неподдержанный historical FX path. Текущий курс/переименование валюты не исправление. |
| `NC_xirr_no_valid_root`, `NC_xirr_root_ambiguity`, `NC_xirr_convergence_failed` | Final XIRR не получен однозначно/надёжно даже при пройденных prerequisites. | Показать ограничение и данные расчёта. Не повторять запись/attestation; не подставлять 0 и не скрывать TWRR. |
| Любой иной final code, включая числовую проблему TWRR | Подтверждённый результат не получен; приложение не умеет подробнее объяснить эту причину. | Безопасные read-only details, raw code только в техническом раскрытии. Не угадывать новую формулу или mutation action. |
| Network/HTTP/DTO mismatch | Проверка не завершилась, это не доказательство неполноты финансов. | Retry чтения; никакой рекомендации править данные или менять scope автоматически. |

Для action различаются: `available` (действие реально реализовано), `requires_reopen`, `not_implemented`, `source_required`, `unsupported`. `source_required` означает, что нужен фактический источник; приложение не может доказать его отсутствие по пустой таблице. «Исторических наблюдений нет» допустимо как подтверждение Owner, а не автоматический диагноз.


<a id="p3-performance_ui_v2_contract-34-6-read-projection--граница-530"></a>
#### 6. Read projection — граница #530

Delivered read-only endpoint: GET `/api/performance/readiness` с теми же `start_date/end_date/scope/account_id`. Он возвращает `schema_version=1`, identity запроса, финальные XIRR/TWRR DTO, существующее evidence и список diagnostics/actions. Это композиция существующих services в одном coherent SQLite read, не второй calculator/availability engine. Сохранить старые endpoints совместимыми. Если Worker доказывает более узкую композицию с теми же guarantees, решение фиксируется Integrator до реализации.

Diagnostic item: стабильный UI diagnostic key, исходные canonical reason codes, affected metrics, только доказанные refs/даты, action kind/params/capability. UI diagnostics keys не становятся новыми финансовыми reason codes. Не включать private paths, raw provider payload, credentials или произвольный executable URL. Capability включается сервером только вместе с поддержанной операцией; frontend не выводит её из слов причины.

Successful prerequisites не заменяют final solver result. Top-level union availability не применяется как общий hide-switch. Финальный процент показывается только при available/exact, непустом value, правильных units/annualized и совпадающей identity. Несогласованный DTO — технический сбой, не вычисленный UI fallback.

Для запроса отдельного счёта не нужны все остальные account solver calls. Таблица допускает отдельные ленивые запросы, но не должна называться атомарной сверкой всего портфеля. Readiness DTO обязан сохранять различие между `membership_checked_account_ids` (источник: `scope_membership.account_ids`), `cash_required_account_ids` (источник: `cash_boundary_coverage.account_ids`) и `in_kind_required_account_ids` (источник: `in_kind_boundary_coverage.account_ids`) либо передавать исходные evidence blocks без переименования. Нельзя создавать `included_account_ids` простым `scope_membership.account_ids - missing_or_ambiguous`: это ошибочно включает исторически исключённые счета. Если #530 захочет добавить отдельный canonical included-set, его семантика должна переиспользовать effective-dated membership selection и получить отдельную contract/test фиксацию, а не выводиться во frontend.

После финансового изменения все затронутые results/diagnostics инвалидируются; новый ответ другой генерации не склеивается со старым. Не требуется новая persisted revision/schema только ради UI.


<a id="p3-performance_ui_v2_contract-34-7-поддержанный-путь-записи--532533"></a>
#### 7. Поддержанный путь записи — #532/#533

#532 сначала использует существующие canonical external flows, cash coverage, in-kind coverage и cash-account linkage, с явным Owner action и действующими guards. Ledger review и attestation раздельны; оба вида coverage нельзя подтвердить одним неявным действием. Кнопка подтверждения не выбрана по умолчанию. Указывать, что остаётся проверить после сохранения.

**Historical membership:** accepted finite interval editor/lifecycle and membership-aware identity are fully specified in C6/C4. Use those supported services and exact stale-state/overlap/CLOSED/atomic invalidation guards; never direct ORM insertion or historical backfill from the current include flag. Saving membership does not confirm cash/in-kind/PRE/POST evidence.

#533 расширяет только принятый capture service: сначала получить реальный target и его current material signature, затем сохранять observation с подписью, прочитанной при начале capture. Нельзя вычислить подпись на сервере только в момент POST и тем самым принять старую форму как новую. Согласовать узкий capture/read-target DTO до кодирования. PRE/POST должны относиться к одной актуальной версии. Частично сохранённая пара остаётся неполной; UI честно показывает, какая сторона сохранена, и не повторяет запись вслепую.

Никаких PRE+flow, интерполяций, копирования month totals как intra-day evidence, вывода completeness из quote refresh. Изменение amount/date/group требует свежих допустимых свидетельств. Старые unbound observations не становятся exact миграцией. #494 уже в базе; не портировать его повторно.

Reopen — отдельное явное действие в существующем owner lifecycle; исторический источник затем проверяется/исправляется и месяц закрывается владельцем заново. По одному клику «Проверить данные» нет reopen/close, provider calls или записи. После ambiguous write outcome — read-back и объяснение, не автоматический retry POST.


<a id="p3-performance_ui_v2_contract-34-8-проверяемые-acceptance-vectors"></a>
#### 8. Проверяемые acceptance vectors

Это specification vectors, **не выполненные runtime-тесты**. Конкретные synthetic fixtures строят Workers в существующих suites. Во всех сравнениях UI получает числа из backend, а не рассчитывает их.

| ID | Вход/действие | Ожидаемый результат |
| --- | --- | --- |
| V01 | Обе final metrics available/exact | Две цифры, XIRR годовых/TWRR за период, одинаковые identity и валюта. |
| V02 | XIRR available, TWRR missing PRE/POST | XIRR виден; одна конкретная TWRR причина и action согласно capability. |
| V03 | XIRR prerequisite available, final root ambiguous | XIRR недоступен с solver explanation; available TWRR сохранён. |
| V04 | Missing cash coverage + legacy IDs | Две доказанные причины, а не сообщение «добавьте одно пополнение». |
| V05 | Пустой ledger, cash coverage unknown | Не 0 flows complete; требуется отдельное явное attestation. |
| V06 | Cash coverage complete, in-kind coverage unknown | XIRR/TWRR не объявляются готовыми; показана независимая причина. |
| V07 | Known in-kind movement unvalued | Complete coverage не превращает движение в оценённое. |
| V08 | Portfolio содержит счёт с цельной историей `include_in_returns=false` и отдельный historical gap; текущий include flag меняется | Исторически исключённый счёт может присутствовать в `scope_membership.account_ids`, но не показывается участником расчёта; денежный состав берётся из `cash_boundary_coverage.account_ids`, gap остаётся отдельным blocker, текущий flag прошлое не лечит. |
| V09 | Нет snapshot на точную дату пресета / duplicate date | Пресет недоступен с объяснением, без соседней даты или shorter window. |
| V10 | Scope/период изменены, поздний старый ответ | Старая цифра не показана как текущая; back/refresh восстанавливает валидный URL. |
| V11 | Reopen/delete/restore затронули выбранную границу | Старый успех скрыт; explicit выбор не заменён последним периодом. |
| V12 | Нулевой/отрицательный backend result | Корректный 0%/знак убытка, не unavailable и не отсутствие текста. |
| V13 | Неизвестный reason / техошибка | Generic limitation либо retry чтения; никаких угаданных writes. |
| V14 | Linked transfer внутри портфеля, account drill-in | Классификация берётся для каждого scope, не переносится из portfolio в account. |
| V15 | PRE capture начат, flow изменён перед POST | Expected signature rejected; form не переподписывается автоматически. |
| V16 | Поддержанные данные проверены и явно сохранены | Read-back показывает оставшиеся blockers либо реальные final metrics; success save не равен success calculation. |
| V17 | Desktop/laptop, keyboard, 200% zoom, длинные названия/причины | Нет горизонтального page overflow; видны даты/units/основной action, раскрытие и возврат с управляемым focus. |
| V18 | Переход между #575 и Performance | Денежный месяц и интервал доходности не смешаны; один экран не подменяет другой. |

<a id="p4"></a>
## 4. Supported source families

Manual persisted facts remain explicit Owner inputs. MyBroker supports the bounded accepted XML family, frozen filename/range/account authority and versioned S1 receipts. H0 is discovery; H1 supplies exact accepted source endpoints; H2 records independently reviewed dated crossings/coverage. None automatically reconstructs a complete ledger.

Alfa PDF supports bounded historical realised payout events. It is not a generic portfolio/price/future-payout importer. Alfa PRO supplies a current compare/reconcile snapshot through the accepted transport and mapping contract; provider numbers are observations, not historical performance truth. T-Invest is the accepted market quote/future payout provider. MOEX identity/reference proof is bounded and explicit; official bond FACEUNIT proof is not a universal FX engine. C9 owns field-by-field authority, exact units, dates, revision and omission behavior.

<a id="p5"></a>
## 5. Goals, scenarios and exports

Keep actual, forecast and hypothetical values visibly separate. Passive-income goal progress uses actual C03 eligible CLOSED-month rolling average; forecast shocks do not rewrite it. Goal target dates are deadlines, not evidence of a future trajectory; unchanged current value cannot justify an invented future achievement date. C8 owns formulas, eligibility, support states and scenario matrices.

Scenario Lab freezes its base and supports only the accepted single-shock families and explicit applicability evidence. Currency tags alone do not authorize FX translation; issuer exposure cannot be guessed from names. Account WHAT-IF uses finite named assumptions under C7. Instrument WHAT-IF is the supported fixed-holding stock scenario; editing prose does not enable bonds or changing-quantity total return.

The recommended AI JSON includes provisional source returns with explicit dates,
methods, limitations, sold instruments and a reading guide. Full-history source
intervals, the selected month and available monthly history remain separate;
[C10](ARCHITECTURE_AND_CONTRACTS.md#c10-ai_financial_review-1-2-composition-boundary)
owns the exact units, source authority and privacy contract.

The recommended AI JSON download uses the versioned referenced format (C10):
repeated source payloads are stored once with typed links; periods, occurrences,
provenance and availability remain explicit. It is still one full-history file,
without a concise/full selector or a second financial calculation. Legacy API
consumers retain the v1 format through the documented compatibility route.

Markdown, JSON, AI analysis bundle, financial review and portfolio review package retain decimal precision, units, nullable values, coverage, reason codes and independent format versions. AI analysis bundle format is `1.4.0`, independent of app release version. Consumer limitations travel with the values; an export incapable of representing partial coverage must not assert complete capital or exact returns. C10 contains the full human-readable contracts; the retained machine schemas/examples remain at their existing paths.

<a id="p6"></a>
## 6. Desktop UX

The primary interface is `/` (UI v2); `/v2` is a valid alias. Retired `/v1` and legacy routes redirect to their native `/v2` workspaces, and no previous-interface link or fallback remains. Failed lazy loading offers a page reload to retry. Preserve period/scope context, browser Back, selected account identity, visible keyboard focus and Russian number/date formatting. Use desktop widths appropriate to the acceptance contract (normally about 1280–1440 px), practical zoom and keyboard coverage; phone widths are not an Owner UAT requirement.

Every read has explicit loading/error/empty/partial states. Failed or stale refresh hides the previous success/export. A mutation cannot erase input typed while the request was in flight. ACK is not saved-state proof; independent GET must agree with the intended create/update/delete, exact entity/month and current dependency identity. Dirty form navigation warns; CLOSED is clearly read-only until explicit Reopen. Restore invalidates stale pre-restore selection and pending confirmations. D3 owns implementation mechanics and C1 the native editor protocol.

<a id="p6-master_spec-1152"></a>
### Desktop formatting and states

<a id="p6-master_spec-1152-12-uxui-требования"></a>
#### 12. UX/UI требования


<a id="p6-master_spec-1152-121-визуальный-стиль"></a>
#### 12.1. Визуальный стиль

- чистый современный дашборд;
- светлая тема по умолчанию;
- нейтральная палитра;
- один акцентный цвет;
- красный только для отрицательных значений и предупреждений;
- зелёный только для положительной динамики;
- крупные числа с понятными подписями;
- графики в меру;
- без визуального стиля торгового терминала.


<a id="p6-master_spec-1152-122-форматирование"></a>
#### 12.2. Форматирование

- рубли: `1 234 567 ₽`;
- проценты: максимум 1–2 знака после запятой;
- даты: `ДД.ММ.ГГГГ`;
- месяц: `Июль 2026`;
- отрицательные значения — заметно, но без кричащего интерфейса;
- нулевые значения можно показывать как `—` в таблицах, где это улучшает читаемость.


<a id="p6-master_spec-1152-123-состояния-интерфейса"></a>
#### 12.3. Состояния интерфейса

Обязательны:

- загрузка;
- пустой список;
- ошибка;
- несохранённые изменения;
- подтверждение удаления;
- предупреждение о неполных данных;
- предупреждение, что точная доходность пока недоступна.


<a id="p6-master_spec-1152-124-навигация"></a>
#### 12.4. Навигация

Основные разделы:

- Мои финансы;
- Капитал;
- Доходность;
- Доход и планы;
- Настройки.

Данные, разбор источника, экспорт/копии и настройки приложения доступны внутри
«Настройки». Рабочие месяцы, справочники и отдельные аналитические инструменты
сохраняют существующие адреса и переходы.

---

<a id="p6-030-55"></a>
### Action hierarchy, progressive disclosure and fact/forecast states

<a id="p6-030-55-1-ux-contract-03"></a>
#### 1. UX contract 0.3


<a id="p6-030-55-11-основной-принцип"></a>
#### 1.1 Основной принцип

По умолчанию интерфейс показывает:

1. результат;
2. контекст, необходимый для правильной интерпретации результата;
3. одно главное следующее действие.

Методология, API/backend terminology, диагностические поля и редкие действия не должны постоянно занимать первый уровень интерфейса.


<a id="p6-030-55-12-action-hierarchy"></a>
#### 1.2 Action hierarchy

- В одной визуальной области должна быть не более одной явной primary action.
- Secondary actions остаются видимыми только когда используются регулярно.
- Редкие действия уходят в `…` / overflow menu.
- Destructive actions по умолчанию не конкурируют с primary; они живут в overflow/menu/dialog и требуют confirm там, где действие необратимо.
- `Обновить` не является визуальной primary action, если данные обычно загружаются автоматически.
- Calculated/read-only value не маскируется под editable input без необходимости.


<a id="p6-030-55-13-progressive-disclosure"></a>
#### 1.3 Progressive disclosure

Три уровня пояснений:

- **всегда видно** — только информация, без которой пользователь может неверно понять цифру или выполнить опасное действие;
- **`ⓘ` tooltip/popover** — короткое объяснение метрики, неполного окна, причины недоступного прогноза, lock-state;
- **`Подробнее` / `<details>`** — длинная методология, composition rules, технические подробности.

User-facing основной поток не должен содержать ссылки вида `MASTER_SPEC §...`, endpoint names (`/api/...`), storage names (`income_type=...`) и слова `backend` как объяснение поведения. Такие детали допустимы только в Diagnostics/technical details.


<a id="p6-030-55-14-fact--forecast--goal"></a>
#### 1.4 Fact / Forecast / Goal

Единый визуальный язык по всему приложению:

- **Fact / Факт** — solid и самый контрастный data series/state;
- **Forecast / Прогноз** — визуально вторичный, dashed/amber или эквивалентный стиль, никогда не выглядит как уже полученный результат;
- **Goal / Цель** — reference/target marker, не data series факта;
- **incomplete history** — muted indicator + help, а не большой warning, если действие пользователя не требуется.

Цель passive income показывает current value только по принятому контракту 0.2: rolling average фактического net passive income по CLOSED месяцам. Forecast остаётся отдельной метрикой.


<a id="p6-030-55-15-state-model"></a>
#### 1.5 State model

| State | Presentation |
|---|---|
| Error, операция невозможна | persistent red alert + recovery action, если есть |
| Warning, требуется решение пользователя | persistent amber alert |
| Неполные данные, но интерфейс корректен | muted badge / `ⓘ` / concise note |
| Empty | короткое объяснение + максимум один основной CTA |
| Closed / locked | статус в sticky header + read-only presentation; длинное постоянное объяснение не требуется |
| Success | короткий transient feedback/toast там, где это возможно |
| Technical diagnostics | Settings → Diagnostics / раскрываемые technical details |

<a id="p6-030-owner-review-2026-08-12-24"></a>
### Desktop density and formatting rules

<a id="p6-030-owner-review-2026-08-12-24-r03-14a--единое-форматирование-чисел"></a>
#### Formatting consistency

- Use the shared formatter for displayed money and quantities; group digits with non-breaking spaces.
- Do not leave user-facing raw values such as `123456` where `123 456` is expected. Editable inputs stay raw and parseable.
- Apply the same conventions to Home, Capital, months/editor, goals, accounts, settings, badges, totals, table cells, tooltips and chart labels.
- Presentation only: no frontend financial arithmetic.

<a id="p6-030-owner-review-2026-08-12-24-r03-14b--month--positions-densityaction-hierarchy"></a>
#### Month positions density

- Keep `price_date` in the data contract; default new and edited positions to the month snapshot date.
- On the first table level, hide a price date equal to the snapshot date; keep a differing date and the price source in secondary detail, except where the source/deviation is genuinely important for interpretation and must stay prominent.
- Label average cost as the average acquisition price per unit: a saved input snapshot, not a reconstructed trade average.
- Market value, cost and unrealized result remain backend-calculated.
- Keep one visible row action, `Изменить`; destructive `Удалить` belongs in overflow with confirmation.
- Keep NKD and price metadata available without widening every row. Use a dialog/drawer or compact edit form where that reads better.

<a id="p6-030-owner-review-2026-08-12-24-r03-14c--month--debtsproperty-density"></a>
#### Month debts and property density

- Keep only the columns needed for quick reading; show `В ликвидном капитале` as compact state/detail unless the value is non-standard.
- Move destructive delete out of permanent visual competition into overflow/compact actions.
- Property value, mortgage and payment must read without colliding with actions.
- Do not change debt/property formulas or include semantics.

<a id="p6-030-owner-review-2026-08-12-24-r03-14d--goals-card-width"></a>
#### Goals card width

- Active secondary goal cards should use available width rather than staying artificially narrow; prefer full-width/adaptive cards or a grid with a sensible minimum width.
- Keep `Сейчас / Цель / Осталось` on one readable line where the viewport allows, without aggressive wrapping of monetary values.
- Preserve the main/secondary visual hierarchy.

Desktop acceptance for these rules: readable at 1366/1024, a clean 760 fallback, keyboard/focus/menu behavior preserved, formatter and key presentation paths keep their regression tests, 760 remains single-column, and no financial calculation changes.
